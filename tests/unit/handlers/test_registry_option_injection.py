"""Registry option injection: what the handler receives, and what may not break.

Plan 00353. ``HandlerRegistry.register_all`` constructs every handler with NO
arguments and then applies configuration through one generic reflective loop,
``setattr(instance, f"_{option_key}", option_value)``. That loop runs last and
always wins, so a handler receives each option as ``self._<option_key>``
holding the RAW value PyYAML parsed.

``pipe_blocker`` broke that contract: its ``__init__`` compiled
``extra_whitelist`` into ``re.Pattern`` objects from an ``options`` argument
production never passes, and the injection then replaced the (empty) compiled
list with the raw ``list[str]``. ``_matches_whitelist`` called
``pattern.search(...)`` on a ``str`` and raised — before the handler reached
any verdict, so with ``strict_mode`` false the chain failed open and EVERY
``pipe_blocker`` protection was silently skipped for every piped command.

These tests therefore drive the REAL registry path. Passing options to the
constructor is exactly what gave false confidence: the existing integration
test did that and passed throughout the defect's life.
"""

from __future__ import annotations

import ast
import inspect
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.core import EventRouter, EventType
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.handlers.registry import (
    EVENT_TYPE_MAPPING,
    HandlerRegistry,
    iter_builtin_handler_classes,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
HANDLERS_DIR = _REPO_ROOT / "src/claude_code_hooks_daemon/handlers"

EVENT_DIR_NAMES = (
    "pre_tool_use",
    "post_tool_use",
    "permission_request",
    "notification",
    "user_prompt_submit",
    "session_start",
    "session_end",
    "stop",
    "subagent_stop",
    "pre_compact",
    "nitpick",
    "worktree_create",
    "worktree_remove",
    "status_line",
)


def _register_with_options(handler_key: str, options: dict[str, Any]) -> EventRouter:
    """Register every handler through the real registry with `options` applied."""
    router = EventRouter()
    registry = HandlerRegistry()
    registry.discover()
    registry.register_all(
        router,
        config={"pre_tool_use": {handler_key: {"enabled": True, "options": options}}},
    )
    return router


def _bash_input(command: str) -> dict[str, Any]:
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": command},
    }


def _registered_handler(router: EventRouter, name: str) -> Any:
    """The live instance the registry built and injected options into."""
    for handler in router.get_chain(EventType.PRE_TOOL_USE).handlers:
        if handler.name == name:
            return handler
    raise AssertionError(f"{name} was not registered")


class TestPipeBlockerExtraWhitelistInjection:
    """The reported defect, driven through registry injection."""

    def test_matches_does_not_raise_on_the_injected_option(self) -> None:
        """The defect itself: `matches()` raised before reaching any verdict.

        Asserted directly on the registry-built instance, because the chain
        catches the exception and fails open — routing alone cannot tell an
        allow-by-verdict from an allow-by-crash.
        """
        router = _register_with_options("pipe_blocker", {"extra_whitelist": [r"^my_report\b"]})
        handler = _registered_handler(router, "pipe-blocker")

        assert handler.matches(_bash_input("my_report --all | tail -20")) is False

    def test_configured_extra_whitelist_allows_its_command(self) -> None:
        """A registry-injected raw pattern must be honoured, not crash the handler."""
        router = _register_with_options("pipe_blocker", {"extra_whitelist": [r"^my_report\b"]})

        result = router.route(EventType.PRE_TOOL_USE, _bash_input("my_report --all | tail -20"))

        assert result.result.decision == "allow"

    def test_configured_extra_whitelist_does_not_disable_the_blacklist(self) -> None:
        """The severe half: a raised `matches()` skipped EVERY protection.

        With the option set, an expensive command piped to tail must still be
        denied. Under the defect this returned an allow, because the exception
        preceded any verdict and the chain failed open.
        """
        router = _register_with_options("pipe_blocker", {"extra_whitelist": [r"^my_report\b"]})

        result = router.route(EventType.PRE_TOOL_USE, _bash_input("pytest tests/ | tail -20"))

        assert result.result.decision == "deny"

    def test_configured_extra_blacklist_denies_its_command(self) -> None:
        """The sibling option takes the same injected shape and must behave."""
        router = _register_with_options("pipe_blocker", {"extra_blacklist": [r"^my_slow_job\b"]})

        result = router.route(EventType.PRE_TOOL_USE, _bash_input("my_slow_job | tail -5"))

        assert result.result.decision == "deny"

    def test_unparseable_pattern_is_not_fatal(self) -> None:
        """A malformed client regex must not take the whole handler down.

        It cannot match anything, so the command falls through to the normal
        unknown-command denial rather than raising out of `matches()`.
        """
        router = _register_with_options("pipe_blocker", {"extra_whitelist": ["^my_report(["]})

        result = router.route(EventType.PRE_TOOL_USE, _bash_input("my_report | tail -5"))

        assert result.result.decision == "deny"


def _handler_modules() -> list[Path]:
    modules: list[Path] = []
    for dir_name in EVENT_DIR_NAMES:
        event_dir = HANDLERS_DIR / dir_name
        if not event_dir.is_dir():
            continue
        modules.extend(
            path for path in sorted(event_dir.glob("*.py")) if not path.name.startswith("_")
        )
    return modules


def _init_reads_its_options_argument(tree: ast.Module) -> list[str]:
    """Names of classes whose `__init__` reads its own `options` parameter."""
    offenders: list[str] = []
    for class_node in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
        for func in [n for n in class_node.body if isinstance(n, ast.FunctionDef)]:
            if func.name != "__init__":
                continue
            parameters = {arg.arg for arg in func.args.args} | {
                arg.arg for arg in func.args.kwonlyargs
            }
            if "options" not in parameters:
                continue
            for node in ast.walk(func):
                # `options` used as a VALUE (read), not merely rebound.
                if (
                    isinstance(node, ast.Name)
                    and node.id == "options"
                    and isinstance(node.ctx, ast.Load)
                ):
                    offenders.append(class_node.name)
                    break
    return offenders


@pytest.mark.parametrize("module_path", _handler_modules(), ids=lambda p: p.stem)
def test_handler_init_never_reads_its_options_argument(module_path: Path) -> None:
    """No production handler `__init__` may read its `options` argument.

    The registry constructs handlers with no arguments, so anything read there
    is dead in production. Worse, storing a TRANSFORMED form of an option under
    `self._<option_key>` puts it at the exact address the registry's setattr
    loop overwrites with the raw YAML value — which is how Plan 00353's defect
    disabled `pipe_blocker` outright. Read options from `self._<option_key>` at
    USE time instead, and expect the raw parsed value there.
    """
    tree = ast.parse(module_path.read_text(encoding="utf-8"))

    offenders = _init_reads_its_options_argument(tree)

    assert not offenders, (
        f"{module_path.name}: {', '.join(offenders)}.__init__ reads its `options` argument, "
        "which the registry never passes. Read `self._<option_key>` at use time instead."
    )


# ---------------------------------------------------------------------------
# Plan 00466 N17: every declared option reaches the handler that declares it.
#
# `skill_opportunity_detector` read its options from `self.config["options"]`,
# which only a `configure()` call populates -- and nothing in production calls
# it. So a configured cadence was ignored at runtime while the unit tests,
# which called `configure()` directly, stayed green. The pins below build each
# handler through the REAL registry, as the daemon does.
# ---------------------------------------------------------------------------

_HANDLER_REFERENCE = _REPO_ROOT / "docs/guides/HANDLER_REFERENCE.md"
_SECTION_HEADING = re.compile(r"^#### ", re.MULTILINE)
_OPTIONS_TABLE = re.compile(r"\*\*Options:\*\*\s*\n\s*\n((?:\|.*\n)+)")
_OPTION_CELL = re.compile(r"^`([^`]+)`")
_TABLE_HEADER_ROWS = 2

#: Declared options a handler legitimately never reads. Every entry says who does.
_READ_OUTSIDE_THE_HANDLER: dict[tuple[str, str], str] = {
    ("secret_file_guard", "allow_plain_hash"): (
        "read by the `secret-meta` CLI from config; the guard itself never hashes"
    ),
}


#: Options validated as they are injected (a property setter), which reject an
#: arbitrary sentinel -- so each gets a VALID value that is not its default.
_VALID_NON_DEFAULTS: dict[tuple[str, str], object] = {
    ("bash_safe_mode", "mode"): "block",
    ("bash_safe_mode", "exempt_patterns"): [r"^zzqx-exempt\b"],
}


class _Sentinel:
    """A non-default value no handler default can equal."""

    def __repr__(self) -> str:
        return "<option sentinel>"


def _declared_options() -> dict[str, tuple[str, ...]]:
    """``config_key -> option names`` from each handler's reference `**Options:**` table."""
    declared: dict[str, tuple[str, ...]] = {}
    text = _HANDLER_REFERENCE.read_text(encoding="utf-8")
    for section in _SECTION_HEADING.split(text)[1:]:
        config_key = section.split("\n", 1)[0].strip().strip("`")
        table = _OPTIONS_TABLE.search(section)
        if table is None:
            continue
        names: list[str] = []
        for row in table.group(1).splitlines()[_TABLE_HEADER_ROWS:]:
            cells = row.split("|")
            match = _OPTION_CELL.match(cells[1].strip()) if len(cells) > 1 else None
            if match is not None:
                names.append(match.group(1))
        declared[config_key] = tuple(names)
    return declared


_DECLARED = _declared_options()
_BUILTINS = {ref.config_key: ref for ref in iter_builtin_handler_classes()}


def _option_reads(handler_cls: type) -> set[str]:
    """Option names the handler's own code reads as ``self._<name>``, outside ``__init__``.

    A string constant ``"_<name>"`` counts too: ``verification_result_gate``
    reads through ``self._extra("_extra_verifiers")``.
    """
    names: set[str] = set()
    for klass in handler_cls.__mro__:
        module = inspect.getmodule(klass)
        if module is None or not module.__name__.startswith("claude_code_hooks_daemon."):
            continue
        tree = ast.parse(inspect.getsource(module))
        for function in ast.walk(tree):
            if not isinstance(function, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            if function.name == "__init__":
                continue
            for node in ast.walk(function):
                if (
                    isinstance(node, ast.Attribute)
                    and isinstance(node.ctx, ast.Load)
                    and isinstance(node.value, ast.Name)
                    and node.value.id == "self"
                    and node.attr.startswith("_")
                ):
                    names.add(node.attr[1:])
                elif (
                    isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                    and node.value.startswith("_")
                ):
                    names.add(node.value[1:])
    return names


@pytest.fixture
def _project_context() -> Iterator[None]:
    """Some handlers need a live project context to construct; the daemon has one."""
    ProjectContext.initialize(_REPO_ROOT / ".claude" / "hooks-daemon.yaml")
    yield


def _built_by_the_registry(config_key: str, options: dict[str, Any]) -> Any:
    ref = _BUILTINS[config_key]
    router = EventRouter()
    registry = HandlerRegistry()
    registry.discover()
    registry.register_all(
        router, config={ref.event_dir: {config_key: {"enabled": True, "options": options}}}
    )
    for handler in router.get_chain(EVENT_TYPE_MAPPING[ref.event_dir]).handlers:
        if handler.config_key == config_key:
            return handler
    raise AssertionError(f"the registry did not register {config_key}")


def test_the_reference_declares_options_to_check() -> None:
    """The pin below is only as good as the inventory it reads."""
    assert len(_DECLARED) >= 30, sorted(_DECLARED)
    assert "check_interval_days" in _DECLARED["skill_opportunity_detector"]
    unknown = sorted(set(_DECLARED) - set(_BUILTINS))
    assert unknown == [], f"reference sections name no built-in handler: {unknown}"


@pytest.mark.usefixtures("_project_context")
@pytest.mark.parametrize("config_key", sorted(_DECLARED))
def test_every_declared_option_is_delivered_and_read(config_key: str) -> None:
    """Built through the real registry, the handler holds and reads each option.

    "Holds" means the attribute differs from a bare-constructed handler's
    default, so an option transformed on injection (compiled, validated)
    counts as delivered too.
    """
    values: dict[str, object] = {
        name: _VALID_NON_DEFAULTS.get((config_key, name), _Sentinel())
        for name in _DECLARED[config_key]
    }
    handler = _built_by_the_registry(config_key, dict(values))
    bare = _BUILTINS[config_key].handler_cls()
    reads = _option_reads(type(handler))

    undelivered = [
        name
        for name in values
        if getattr(handler, f"_{name}", None) == getattr(bare, f"_{name}", None)
    ]
    unread = [
        name
        for name in values
        if name not in reads and (config_key, name) not in _READ_OUTSIDE_THE_HANDLER
    ]
    assert undelivered == [], f"{config_key}: the registry did not deliver {undelivered}"
    assert unread == [], (
        f"{config_key}: declares {unread} but never reads self._<option>, so a "
        "configured value is ignored at runtime"
    )


def _config_option_reads(tree: ast.AST) -> list[tuple[int, str]]:
    """``self.config.get("<key>")`` / ``self.config["<key>"]`` reads of anything but ``enabled``."""
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        target: ast.expr | None = None
        key: ast.expr | None = None
        line = 0
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "get" and node.args:
                target, key, line = node.func.value, node.args[0], node.lineno
        elif isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Load):
            target, key, line = node.value, node.slice, node.lineno
        if (
            isinstance(target, ast.Attribute)
            and target.attr == "config"
            and isinstance(target.value, ast.Name)
            and target.value.id == "self"
            and isinstance(key, ast.Constant)
            and key.value != "enabled"
        ):
            found.append((line, str(key.value)))
    return found


@pytest.mark.parametrize("module_path", _handler_modules(), ids=lambda p: p.stem)
def test_no_handler_reads_an_option_from_a_configure_dict(module_path: Path) -> None:
    """``self.config`` is filled only by ``configure()``, which production never calls."""
    offenders = _config_option_reads(ast.parse(module_path.read_text(encoding="utf-8")))

    assert offenders == [], (
        f"{module_path.name} reads options from self.config at {offenders}. The registry "
        "delivers options as self._<option>; read them there."
    )


def test_the_configure_dict_scan_sees_both_read_shapes() -> None:
    source = (
        "class H:\n"
        "    def a(self):\n"
        "        return self.config.get('cache_ttl_hours', 24)\n"
        "    def b(self):\n"
        "        return self.config['options']\n"
        "    def c(self):\n"
        "        return self.config.get('enabled', True)\n"
    )
    assert _config_option_reads(ast.parse(source)) == [(3, "cache_ttl_hours"), (5, "options")]
