"""Guard: nothing reads the hook payload with a raw string literal.

``HookInputField`` (``constants/protocol.py``) is declared the single source
of truth for hook-input field names, but a declaration nothing enforces
drifts back to magic strings the moment someone copy-pastes a handler and
forgets to import the constant. This walks every module under
``src/claude_code_hooks_daemon`` with the ``ast`` module and fails, naming
file:line, for any place that still spells a tracked field name out by hand
instead of using the matching ``HookInputField.<NAME>`` constant.

Two shapes are flagged:

(a) ``<receiver>.get(<literal>, ...)`` or ``<receiver>[<literal>]`` where the
    literal string equals one of ``HookInputField``'s values and ``receiver``
    is a name demonstrably bound to the real hook payload — either the
    universal handler parameter ``hook_input`` (every ``matches``/``handle``
    across the handler tree takes ``hook_input: dict[str, Any]``, verified
    below), or one of a small, file-scoped allowlist for the rare non-handler
    code that constructs/reads the same wire shape under a different name.

(b) a module-level assignment of a tracked field value to a private constant
    (the ``_CWD_FIELD: Final[str] = "cwd"`` shape) *when that constant is
    itself later used as the key in one of the (a) shapes*. Requiring the
    usage link is what keeps this from flagging a same-named field on an
    unrelated JSON document — e.g. a budget ledger's own ``"session_id"`` key
    is not the hook payload's, and must not be treated as one.

The receiver allowlist is intentionally narrow rather than name-based
("hook_input", "payload", "event", ...) globally: a bare name match on
"payload" or "data" would also catch transcript JSONL records and other
sub-dicts that happen to share field names with the hook protocol (a
transcript line's ``message``/``tool_name``, a cache payload's unrelated
``session_id`` — the exact confusion this test exists to avoid encouraging).
"""

from __future__ import annotations

import ast
from pathlib import Path

from claude_code_hooks_daemon.constants.protocol import HookInputField

_SRC_ROOT = Path(__file__).resolve().parents[3] / "src" / "claude_code_hooks_daemon"

# value -> constant name, for every string constant HookInputField declares.
_TRACKED_VALUES: dict[str, str] = {
    value: name
    for name, value in vars(HookInputField).items()
    if not name.startswith("_") and isinstance(value, str)
}

# The parameter name every handler's matches()/handle() (and the free
# functions in core/utils.py that take the payload) use for the real hook
# input dict. Verified project-wide in TestReceiverAssumptionHolds below.
_UNIVERSAL_RECEIVER = "hook_input"

# file (relative to _SRC_ROOT) -> extra receiver names that are demonstrably
# the hook payload IN THAT FILE ONLY. Each entry here must be justified by
# reading the file, not guessed from the name: playbook_harness.py builds
# `event = {"hook_event_name": ..., "tool_name": ..., ...}` as the literal
# dispatchable wire payload, and reads the declared `tool_payload` fragment
# of a playbook block (aliased `payload`) that is copied verbatim into it.
_EXTRA_RECEIVERS_BY_FILE: dict[str, frozenset[str]] = {
    "daemon/playbook_harness.py": frozenset({"event", "payload"}),
}


def _receivers_for(relpath: str) -> frozenset[str]:
    return frozenset({_UNIVERSAL_RECEIVER}) | _EXTRA_RECEIVERS_BY_FILE.get(relpath, frozenset())


def _module_level_private_constants(tree: ast.Module) -> dict[str, tuple[int, str]]:
    """Private module-level ``NAME = "<tracked value>"`` assignments.

    Returns constant name -> (definition line, string value). Only literal
    string assignments whose value is itself a tracked HookInputField value
    are collected; nothing else can ever be flagged as case (b).
    """
    constants: dict[str, tuple[int, str]] = {}
    for node in tree.body:
        targets: list[ast.expr] = []
        value_node: ast.expr | None = None
        if isinstance(node, ast.Assign):
            targets = node.targets
            value_node = node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
            value_node = node.value
        if value_node is None:
            continue
        if not (isinstance(value_node, ast.Constant) and isinstance(value_node.value, str)):
            continue
        if value_node.value not in _TRACKED_VALUES:
            continue
        for target in targets:
            if isinstance(target, ast.Name) and target.id.startswith("_"):
                constants[target.id] = (node.lineno, value_node.value)
    return constants


def _scan_module(path: Path, relpath: str) -> list[str]:
    """file:line offenders for shapes (a) and (b) in one module."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    receivers = _receivers_for(relpath)
    private_constants = _module_level_private_constants(tree)

    direct_offenders: list[str] = []
    constants_used_as_keys: set[str] = set()

    for node in ast.walk(tree):
        receiver: ast.expr | None = None
        key_node: ast.expr | None = None
        if not isinstance(node, ast.expr):
            continue

        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
        ):
            receiver = node.func.value
            if node.args:
                key_node = node.args[0]
        elif isinstance(node, ast.Subscript):
            receiver = node.value
            key_node = node.slice

        if receiver is None or key_node is None:
            continue
        if not (isinstance(receiver, ast.Name) and receiver.id in receivers):
            continue

        if isinstance(key_node, ast.Constant) and isinstance(key_node.value, str):
            if key_node.value in _TRACKED_VALUES:
                direct_offenders.append(f"{relpath}:{node.lineno}")
        elif isinstance(key_node, ast.Name) and key_node.id in private_constants:
            constants_used_as_keys.add(key_node.id)

    constant_offenders = [
        f"{relpath}:{private_constants[name][0]}" for name in sorted(constants_used_as_keys)
    ]
    return direct_offenders + constant_offenders


def _all_offenders() -> list[str]:
    offenders: list[str] = []
    for module_path in sorted(_SRC_ROOT.rglob("*.py")):
        relpath = str(module_path.relative_to(_SRC_ROOT))
        offenders.extend(_scan_module(module_path, relpath))
    return offenders


class TestReceiverAssumptionHolds:
    """Guard the guard: prove the naming assumption this test relies on."""

    def test_every_handler_matches_and_handle_use_hook_input_parameter(self) -> None:
        """Every ``matches``/``handle`` method in the handler tree is typed
        ``(self, hook_input: dict[str, Any])`` — if this ever stops being
        true, the receiver allowlist above needs to widen deliberately
        rather than this test silently going blind to a renamed parameter.
        """
        offenders: list[str] = []
        for module_path in sorted(_SRC_ROOT.glob("handlers/**/*.py")):
            tree = ast.parse(module_path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.FunctionDef):
                    continue
                if node.name not in {"matches", "handle"}:
                    continue
                args = node.args.args
                if len(args) < 2 or args[0].arg != "self":
                    continue
                if args[1].arg != _UNIVERSAL_RECEIVER:
                    offenders.append(
                        f"{module_path.relative_to(_SRC_ROOT)}:{node.lineno} "
                        f"({node.name} second param is {args[1].arg!r})"
                    )
        assert not offenders, (
            "A handler method no longer names its payload parameter "
            f"'{_UNIVERSAL_RECEIVER}': " + "; ".join(offenders)
        )


class TestTheScannerWorks:
    """A scanner that finds nothing and a scanner that IS nothing produce the
    same green tick, so prove it can see before trusting its silence."""

    def test_it_flags_a_direct_literal_against_hook_input(self, tmp_path: Path) -> None:
        module = tmp_path / "fixture.py"
        module.write_text('def f(hook_input):\n    return hook_input.get("tool_name")\n')
        assert _scan_module(module, "fixture.py") == ["fixture.py:2"]

    def test_it_flags_a_subscript_against_hook_input(self, tmp_path: Path) -> None:
        module = tmp_path / "fixture.py"
        module.write_text('def f(hook_input):\n    return hook_input["cwd"]\n')
        assert _scan_module(module, "fixture.py") == ["fixture.py:2"]

    def test_it_flags_a_private_constant_used_as_a_hook_input_key(self, tmp_path: Path) -> None:
        module = tmp_path / "fixture.py"
        module.write_text(
            '_CWD_FIELD = "cwd"\n' "def f(hook_input):\n" "    return hook_input.get(_CWD_FIELD)\n"
        )
        assert _scan_module(module, "fixture.py") == ["fixture.py:1"]

    def test_it_does_not_flag_a_literal_on_an_unrecognised_receiver(self, tmp_path: Path) -> None:
        """A transcript record sharing field names with the hook protocol
        must not be flagged — this is the false positive the whole design
        exists to avoid (Plan 00408 Task 1.1 field notes)."""
        module = tmp_path / "fixture.py"
        module.write_text('def f(data):\n    return data.get("tool_name")\n')
        assert _scan_module(module, "fixture.py") == []

    def test_it_does_not_flag_an_unused_private_constant(self, tmp_path: Path) -> None:
        """A same-named private constant that is never used as a hook_input
        key (e.g. a ledger's own schema) must not be flagged."""
        module = tmp_path / "fixture.py"
        module.write_text(
            '_LEDGER_SESSION_ID_KEY = "session_id"\n'
            "def f(record):\n"
            "    return {_LEDGER_SESSION_ID_KEY: record}\n"
        )
        assert _scan_module(module, "fixture.py") == []

    def test_it_does_not_flag_the_constant_form_itself(self, tmp_path: Path) -> None:
        module = tmp_path / "fixture.py"
        module.write_text(
            "from claude_code_hooks_daemon.constants import HookInputField\n"
            "def f(hook_input):\n"
            "    return hook_input.get(HookInputField.TOOL_NAME)\n"
        )
        assert _scan_module(module, "fixture.py") == []

    def test_extra_receiver_is_scoped_to_its_declared_file_only(self, tmp_path: Path) -> None:
        module = tmp_path / "fixture.py"
        module.write_text('def f(event):\n    return event["tool_response"]\n')
        # Not scoped for this relpath, so the "event" receiver is unrecognised.
        assert _scan_module(module, "fixture.py") == []


class TestNoRawHookInputFieldLiterals:
    def test_every_hook_payload_read_uses_the_constant(self) -> None:
        offenders = _all_offenders()
        assert not offenders, (
            "Hook payload field(s) read via a raw string literal instead of "
            "HookInputField.<NAME>: "
            + "; ".join(offenders)
            + ". HookInputField is the declared single source of truth for "
            "hook-input field names (constants/protocol.py) — import the "
            "matching constant instead of hand-spelling the field name, and "
            "delete any private '_FIELD = \"...\"' constant that only "
            "re-declares one of its values."
        )
