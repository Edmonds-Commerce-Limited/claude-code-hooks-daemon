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
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.core import EventRouter, EventType
from claude_code_hooks_daemon.handlers.registry import HandlerRegistry

HANDLERS_DIR = Path(__file__).resolve().parents[3] / "src/claude_code_hooks_daemon/handlers"

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
