#!/usr/bin/env python3
"""Hook INPUT-contract drift check — the daemon's read surface vs the vendored examples.

Plan 00273 (follow-up to Plan 00271, which covered the RESPONSE side). Handlers
and the shared helpers read hook_input fields ad hoc, so a renamed or
restructured input field would surface only as handlers silently never
matching. This check derives the top-level read surface by AST scan and applies
the plan's Technical Decision 1 SUPERSET rule against each event's vendored
``input_example`` (``contracts/claude-code-hooks/*.json``), NETWORK-FREE:

``unknown-input-field``         the daemon reads a top-level hook_input field
                                that appears in NO vendored input example for
                                that event, AND is not declared in that event's
                                ``conditional_input_fields`` — the rename
                                signal. Absence (the example carrying fields
                                the daemon never reads) is NEVER flagged:
                                examples are not schemas.

An ``input_example`` depicts ONE call, so a field that arrives only under some
condition is simply missing from it — and reading that absence as "never
delivered" is a confident false negative (Plan 00413 N12: ``agent_id`` IS
delivered to ``PreToolUse`` inside a subagent call, and no example can ever
show it). ``conditional_input_fields`` maps such a field to the CONDITION
under which it arrives; a name with no condition is rejected, and the
declaration is per-event, never global.
``stale-allowlist-entry``       an INPUT-ALLOWLIST.yaml entry whose finding no
                                longer exists.
``malformed-allowlist-entry``   an allowlist entry missing its reason or link.

The allowlist protocol (Finding/Report shapes, entry validation) is shared
with ``check_hook_contract.py`` via ``contract_allowlist.py``.

Scope (by construction, per the plan's Non-Goals):

- StatusLine and the ``nitpick`` pseudo-event are out-of-contract and never
  scanned as event packages. (Shared code DOES read StatusLine-payload fields
  such as ``terminal_columns``/``context_window``; those reads surface on the
  shared surface and are recorded in INPUT-ALLOWLIST.yaml.)
- Nested ``tool_input`` keys are NOT validated — the examples carry one tool's
  shape only, so there is no substrate; only the top-level ``tool_input`` read
  is recorded. The known gap is on record in the plan's INVENTORY.md.
- The SHARED surface — ``utils/``, ``core/`` (front controller, mode
  interceptor, session state, core utils) and ``handlers/utils`` — serves many
  events, so its reads are checked against the UNION of all input examples.
- An event package whose contract carries no (or an empty) ``input_example``
  has no substrate: it is skipped, and listed in ``--inventory`` output.

The checker primitive (``collect_read_surface`` + ``check_read_surface``) is
deliberately importable and root-parameterised so ``validate-project-handlers``
can reuse it for client project handlers later (recorded follow-up gap).
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

try:
    from contract_allowlist import (
        Finding,
        Report,
        apply_allowlist,
        load_allowlist_file,
    )
except ModuleNotFoundError:
    # Loaded by file path (e.g. importlib in tests): prime this script's own
    # directory so the shared sibling module resolves, then import for real.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from contract_allowlist import (
        Finding,
        Report,
        apply_allowlist,
        load_allowlist_file,
    )

_PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parent.parent.parent
_SRC_PACKAGE_PARTS: Final[tuple[str, str]] = ("src", "claude_code_hooks_daemon")
_CONTRACTS_DIR_PARTS: Final[tuple[str, str]] = ("contracts", "claude-code-hooks")
_META_FILENAME: Final[str] = "META.json"
_QA_OUTPUT_DIR_PARTS: Final[tuple[str, str]] = ("untracked", "qa")
_OUTPUT_FILENAME: Final[str] = "input_contract.json"

INPUT_ALLOWLIST_FILENAME: Final[str] = "INPUT-ALLOWLIST.yaml"

_HANDLERS_DIR_NAME: Final[str] = "handlers"
_UTILS_DIR_NAME: Final[str] = "utils"
_CONSTANTS_PROTOCOL_PARTS: Final[tuple[str, str]] = ("constants", "protocol.py")
_HOOK_INPUT_FIELD_CLASS: Final[str] = "HookInputField"
_HOOK_INPUT_VARIABLE: Final[str] = "hook_input"
_GET_METHOD: Final[str] = "get"
_INPUT_EXAMPLE_KEY: Final[str] = "input_example"
_EVENT_KEY: Final[str] = "event"

#: Fields an event MAY receive that no ``input_example`` can show, mapped to
#: the condition under which they arrive. An example depicts one call, so a
#: conditionally-present field is absent from it — and reading that absence as
#: "never delivered" is a confident false negative (Plan 00413 N12). The slot
#: also carries the reverse case: a field the example DOES show that can be
#: absent at runtime, so a handler must not assume it.
_CONDITIONAL_INPUT_FIELDS_KEY: Final[str] = "conditional_input_fields"

#: Handler packages excluded from the scan by construction: StatusLine is a
#: separate Claude Code feature with its own contract; ``nitpick`` is a daemon
#: pseudo-event; ``utils`` under handlers/ is a shared surface (scanned as
#: SHARED, not as an event package).
_EXCLUDED_HANDLER_PACKAGES: Final[frozenset[str]] = frozenset(
    {"status_line", "nitpick", "__pycache__"}
)
_SHARED_HANDLER_PACKAGES: Final[frozenset[str]] = frozenset({_UTILS_DIR_NAME})

#: Top-level src subpackages whose reads are made on many events' behalf:
#: ``utils/`` helpers and ``core/`` (front controller, mode interceptor,
#: session state, core utils all read hook_input directly).
_SHARED_SRC_SUBPACKAGES: Final[tuple[str, ...]] = (_UTILS_DIR_NAME, "core")

#: Sentinel event key for reads made by shared code on many events' behalf.
SHARED_SURFACE: Final[str] = "(shared)"

# Rule name (allowlist-integrity rule names live in contract_allowlist).
RULE_UNKNOWN_INPUT_FIELD: Final[str] = "unknown-input-field"


@dataclass
class InputReport(Report):
    """Report plus the derived read surface, so callers never re-scan."""

    read_surface: dict[str, set[str]] = field(default_factory=dict)
    skipped_events: list[str] = field(default_factory=list)
    conditional_fields: dict[str, dict[str, str]] = field(default_factory=dict)


def load_field_constants(src_dir: Path) -> dict[str, str]:
    """Map ``HookInputField`` attribute names to their string values.

    An absent or unparsable ``constants/protocol.py`` yields an empty map —
    the string-literal branch of the scan still works.
    """
    path = src_dir.joinpath(*_CONSTANTS_PROTOCOL_PARTS)
    if not path.is_file():
        return {}
    constants: dict[str, str] = {}
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not (isinstance(node, ast.ClassDef) and node.name == _HOOK_INPUT_FIELD_CLASS):
            continue
        for statement in node.body:
            if not (
                isinstance(statement, ast.Assign)
                and isinstance(statement.value, ast.Constant)
                and isinstance(statement.value.value, str)
            ):
                continue
            for target in statement.targets:
                if isinstance(target, ast.Name):
                    constants[target.id] = statement.value.value
    return constants


def _resolve_key(node: ast.expr, constants: dict[str, str]) -> str | None:
    """Resolve a key expression to a field name: a string literal, or a
    ``HookInputField.X`` attribute looked up in the constants map."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Attribute) and node.attr in constants:
        return constants[node.attr]
    return None


def collect_reads_from_source(source: str, constants: dict[str, str]) -> set[str]:
    """Top-level hook_input field names a module reads.

    Detected shapes: ``hook_input.get(<key>[, default])`` and
    ``hook_input[<key>]`` where ``<key>`` is a string literal or a
    ``HookInputField`` attribute. Nested reads chain off the returned value,
    so only the top-level key is ever recorded. Known shape limits (reads the
    scan cannot see) are recorded in the plan's INVENTORY.md.
    """
    reads: set[str] = set()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == _GET_METHOD
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == _HOOK_INPUT_VARIABLE
            and node.args
        ):
            key = _resolve_key(node.args[0], constants)
            if key is not None:
                reads.add(key)
        elif (
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Name)
            and node.value.id == _HOOK_INPUT_VARIABLE
        ):
            key = _resolve_key(node.slice, constants)
            if key is not None:
                reads.add(key)
    return reads


def package_to_event(package_name: str) -> str:
    """``pre_tool_use`` -> ``PreToolUse`` (handler package dir to event name)."""
    return "".join(part.capitalize() for part in package_name.split("_"))


def _reads_under(directory: Path, constants: dict[str, str]) -> set[str]:
    reads: set[str] = set()
    for path in sorted(directory.rglob("*.py")):
        reads |= collect_reads_from_source(path.read_text(encoding="utf-8"), constants)
    return reads


def collect_read_surface(root: Path) -> dict[str, set[str]]:
    """Per-event read surface across handler packages plus SHARED code.

    Handler event packages map to their event name; ``utils/``, ``core/`` and
    ``handlers/utils`` are aggregated under :data:`SHARED_SURFACE`. Excluded
    by construction: StatusLine and the nitpick pseudo-event.
    """
    src_dir = root.joinpath(*_SRC_PACKAGE_PARTS)
    constants = load_field_constants(src_dir)
    surface: dict[str, set[str]] = {}
    shared: set[str] = set()

    handlers_dir = src_dir / _HANDLERS_DIR_NAME
    if handlers_dir.is_dir():
        for package in sorted(handlers_dir.iterdir()):
            if not package.is_dir() or package.name in _EXCLUDED_HANDLER_PACKAGES:
                continue
            if package.name in _SHARED_HANDLER_PACKAGES:
                shared |= _reads_under(package, constants)
                continue
            reads = _reads_under(package, constants)
            if reads:
                surface[package_to_event(package.name)] = reads

    for subpackage in _SHARED_SRC_SUBPACKAGES:
        shared_dir = src_dir / subpackage
        if shared_dir.is_dir():
            shared |= _reads_under(shared_dir, constants)
    if shared:
        surface[SHARED_SURFACE] = shared
    return surface


def _read_conditional_fields(path: Path, data: dict[str, object]) -> dict[str, str]:
    """The event's ``conditional_input_fields`` map, validated.

    A name with no condition is rejected rather than accepted leniently: "may
    arrive" without "when" is not a contract, and leaves the next reader
    guessing — which is the exact failure the slot exists to remove.
    """
    raw = data.get(_CONDITIONAL_INPUT_FIELDS_KEY)
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(
            f"contract file {path.name} has a non-object "
            f"'{_CONDITIONAL_INPUT_FIELDS_KEY}' — it maps a field name to the "
            f"condition under which that field arrives"
        )
    conditions: dict[str, str] = {}
    for name, condition in raw.items():
        if not isinstance(condition, str) or not condition.strip():
            raise ValueError(
                f"contract file {path.name} declares conditional input field "
                f"'{name}' with no condition — state WHEN the field arrives"
            )
        conditions[name] = condition
    return conditions


def _load_contracts(contracts_dir: Path) -> dict[str, tuple[set[str], dict[str, str]]]:
    """Per-event ``(example keys, conditional field conditions)``.

    Raises:
        FileNotFoundError: when the vendored contract directory is absent —
            FAIL FAST, an input check with no examples verifies nothing.
        ValueError: when a contract file has no ``event`` key, or declares a
            malformed conditional-field slot — a malformed vendored file must
            fail loudly, naming the file.
    """
    if not contracts_dir.is_dir():
        raise FileNotFoundError(f"vendored contract directory missing: {contracts_dir}")
    contracts: dict[str, tuple[set[str], dict[str, str]]] = {}
    for path in sorted(contracts_dir.glob("*.json")):
        if path.name == _META_FILENAME:
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        if _EVENT_KEY not in data:
            raise ValueError(f"contract file {path.name} has no '{_EVENT_KEY}' key")
        contracts[data[_EVENT_KEY]] = (
            set(data.get(_INPUT_EXAMPLE_KEY) or {}),
            _read_conditional_fields(path, data),
        )
    return contracts


def load_input_examples(contracts_dir: Path) -> dict[str, set[str]]:
    """Every field an event is DOCUMENTED to deliver, per event.

    The union of the vendored ``input_example``'s top-level keys and any
    ``conditional_input_fields`` the event declares. The union is deliberately
    per-event rather than global: upstream says outright that not all events
    receive ``permission_mode``, so a field declared conditional on one event
    must not quietly become known on every other.

    An event whose example is empty stays empty here even if it declares
    conditional fields — an event with no example has no substrate and is
    skipped by :func:`check_read_surface`, and inventing one from the
    conditional slot alone would start checking it against a fragment.
    """
    return _known_fields(_load_contracts(contracts_dir))


def _known_fields(
    contracts: dict[str, tuple[set[str], dict[str, str]]],
) -> dict[str, set[str]]:
    """Example keys plus declared conditional fields, per event."""
    return {
        event: (example | set(conditions) if example else example)
        for event, (example, conditions) in contracts.items()
    }


def load_conditional_input_fields(contracts_dir: Path) -> dict[str, dict[str, str]]:
    """Per-event conditional field -> condition, for events that declare any."""
    return {
        event: conditions
        for event, (_example, conditions) in _load_contracts(contracts_dir).items()
        if conditions
    }


def check_read_surface(
    read_surface: dict[str, set[str]], examples: dict[str, set[str]]
) -> list[Finding]:
    """Apply the SUPERSET rule (Plan 00273 Technical Decision 1).

    A field an event's handlers read that appears in NO vendored example for
    that event is flagged; absence is never flagged. SHARED reads are checked
    against the union of all examples. An event with no (or an empty) example
    has no substrate and is skipped (see :func:`skipped_event_names`).
    """
    union: set[str] = set().union(*examples.values()) if examples else set()
    findings: list[Finding] = []
    for event, reads in sorted(read_surface.items()):
        if event == SHARED_SURFACE:
            known = union
            scope = "no vendored input example"
        else:
            known = examples.get(event, set())
            if not known:
                continue
            scope = f"no vendored {event} input example"
        for name in sorted(reads - known):
            findings.append(
                Finding(
                    rule=RULE_UNKNOWN_INPUT_FIELD,
                    event=event,
                    subject=name,
                    message=(
                        f"the daemon reads top-level hook_input field '{name}' "
                        f"({event}), which appears in {scope} — "
                        f"possible upstream rename or a stale read"
                    ),
                )
            )
    return findings


def skipped_event_names(
    read_surface: dict[str, set[str]], examples: dict[str, set[str]]
) -> list[str]:
    """Events with reads but no (or an empty) vendored example — no substrate."""
    return sorted(
        event for event in read_surface if event != SHARED_SURFACE and not examples.get(event)
    )


def scan(root: Path) -> InputReport:
    """Run the input-contract check against the tree at ``root``."""
    contracts_dir = root.joinpath(*_CONTRACTS_DIR_PARTS)
    contracts = _load_contracts(contracts_dir)
    examples = _known_fields(contracts)
    read_surface = collect_read_surface(root)
    findings = check_read_surface(read_surface, examples)
    remaining, allowlisted, problems = apply_allowlist(
        findings, load_allowlist_file(contracts_dir / INPUT_ALLOWLIST_FILENAME)
    )
    return InputReport(
        violations=remaining + problems,
        allowlisted=allowlisted,
        read_surface=read_surface,
        skipped_events=skipped_event_names(read_surface, examples),
        conditional_fields={
            event: conditions for event, (_example, conditions) in contracts.items() if conditions
        },
    )


def _render_inventory(report: InputReport) -> str:
    lines = ["Top-level hook_input read surface (per event; nested keys not recorded):"]
    for event, reads in sorted(report.read_surface.items()):
        lines.append(f"  {event}: {', '.join(sorted(reads))}")
    for event in report.skipped_events:
        lines.append(f"  {event}: SKIPPED — no vendored input example (no substrate to check)")
    if report.conditional_fields:
        lines.append("")
        lines.append(
            "Conditional input fields (declared in the vendored contract; an "
            "input_example shows ONE call, so its silence about these proves nothing):"
        )
        for event, conditions in sorted(report.conditional_fields.items()):
            lines.append(f"  {event}:")
            for name, condition in sorted(conditions.items()):
                lines.append(f"    {name}: {condition}")
    return "\n".join(lines)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Hook input-contract drift check (Plan 00273)")
    parser.add_argument("--root", default=str(_PROJECT_ROOT), help="repository root to scan")
    parser.add_argument("--json", action="store_true", help="write the JSON artifact")
    parser.add_argument(
        "--report-stdout", action="store_true", help="print the JSON report to stdout"
    )
    parser.add_argument(
        "--inventory",
        action="store_true",
        help="print the derived read surface (for contract-refresh re-triage)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    root = Path(args.root)

    try:
        report = scan(root)
    except (FileNotFoundError, json.JSONDecodeError, ValueError, SyntaxError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.inventory:
        print(_render_inventory(report))

    payload = report.to_dict()
    if args.json:
        output_dir = root.joinpath(*_QA_OUTPUT_DIR_PARTS)
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / _OUTPUT_FILENAME).write_text(json.dumps(payload, indent=2))

    if args.report_stdout:
        print(json.dumps(payload, indent=2))
    elif report.violations:
        print(f"Found {len(report.violations)} input-contract violation(s):")
        for violation in report.violations:
            print(f"  [{violation.rule}] {violation.event}: {violation.message}")
    else:
        print(
            f"No input-contract violations ({len(report.allowlisted)} recorded "
            f"allowlisted gap(s))"
        )
    return 1 if report.violations else 0


if __name__ == "__main__":
    sys.exit(main())
