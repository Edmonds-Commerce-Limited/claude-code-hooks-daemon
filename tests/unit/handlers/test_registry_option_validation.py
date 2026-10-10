"""A handler's invalid option is reported at session start, not by dropping the handler.

Options are applied by ``setattr`` inside ``register_all``'s broad per-handler
guard, so a setter that raises would drop the WHOLE handler with only a warning.
Pass 1 validates them instead, records the problem on ``option_failures`` (the
session-start alert's source) and withholds the bad value, so the handler still
runs on its default.
"""

from typing import Any

import pytest

from claude_code_hooks_daemon.core.event import EventType
from claude_code_hooks_daemon.core.router import EventRouter
from claude_code_hooks_daemon.handlers.pre_tool_use.bash_safe_mode import BashSafeModeHandler
from claude_code_hooks_daemon.handlers.registry import HandlerRegistry
from claude_code_hooks_daemon.handlers.stop.auto_continue_stop import AutoContinueStopHandler
from claude_code_hooks_daemon.handlers.user_prompt_submit.idle_housekeeping_advisor import (
    IdleHousekeepingAdvisoryHandler,
)
from claude_code_hooks_daemon.utils.stale_checkouts import DEFAULT_MAX_IDLE_DAYS
from claude_code_hooks_daemon.utils.stale_litter import DEFAULT_SCRATCH_DAYS
from claude_code_hooks_daemon.utils.stand_in_cron import DEFAULT_STAND_IN_DELAY_HOURS

_KEY = "UserPromptSubmit.idle_housekeeping_advisory"


def _config(**options: Any) -> dict[str, Any]:
    return {
        "user_prompt_submit": {"idle_housekeeping_advisory": {"enabled": True, "options": options}}
    }


def _register(**options: Any) -> tuple[HandlerRegistry, IdleHousekeepingAdvisoryHandler]:
    registry = HandlerRegistry()
    registry.discover()
    router = EventRouter()
    registry.register_all(router, config=_config(**options))
    for handler in router.get_chain(EventType.USER_PROMPT_SUBMIT).handlers:
        if isinstance(handler, IdleHousekeepingAdvisoryHandler):
            return registry, handler
    raise AssertionError("idle_housekeeping_advisory was not registered")


@pytest.mark.parametrize("bad", [0, -3, "7", 1.5, True])
def test_a_bad_stale_worktree_days_is_reported_and_the_handler_still_runs_on_the_default(
    bad: object,
) -> None:
    registry, handler = _register(stale_worktree_days=bad, base_branch="develop")

    assert "stale_worktree_days" in registry.option_failures[_KEY]
    assert handler._stale_worktree_days == DEFAULT_MAX_IDLE_DAYS
    # Its other options are untouched.
    assert handler._base_branch == "develop"


def test_a_valid_stale_worktree_days_is_applied_with_no_failure() -> None:
    registry, handler = _register(stale_worktree_days=3)

    assert registry.option_failures == {}
    assert handler._stale_worktree_days == 3


@pytest.mark.parametrize("bad", [0, -3, "14", 1.5, True])
def test_a_bad_stale_scratch_days_is_reported_and_the_handler_runs_on_the_default(
    bad: object,
) -> None:
    registry, handler = _register(stale_scratch_days=bad, base_branch="develop")

    assert "stale_scratch_days" in registry.option_failures[_KEY]
    assert handler._stale_scratch_days == DEFAULT_SCRATCH_DAYS
    assert handler._base_branch == "develop"


_STOP_KEY = "Stop.auto_continue_stop"


def _register_stop(value: object) -> tuple[HandlerRegistry, AutoContinueStopHandler]:
    registry = HandlerRegistry()
    registry.discover()
    router = EventRouter()
    config = {
        "stop": {
            "auto_continue_stop": {"enabled": True, "options": {"stand_in_delay_hours": value}}
        }
    }
    registry.register_all(router, config=config)
    for handler in router.get_chain(EventType.STOP).handlers:
        if isinstance(handler, AutoContinueStopHandler):
            return registry, handler
    raise AssertionError("auto_continue_stop was dropped by an invalid stand_in_delay_hours")


@pytest.mark.parametrize("bad", [24, 0, -1, "3", True, float("nan")])
def test_a_bad_stand_in_delay_is_reported_and_the_stop_handler_stays_on_the_default(
    bad: object,
) -> None:
    registry, handler = _register_stop(bad)

    assert "stand_in_delay_hours" in registry.option_failures[_STOP_KEY]
    assert handler._stand_in_delay_hours == DEFAULT_STAND_IN_DELAY_HOURS


def test_a_valid_stand_in_delay_is_applied_with_no_failure() -> None:
    registry, handler = _register_stop(5)

    assert registry.option_failures == {}
    assert handler._stand_in_delay_hours == 5.0


_SAFE_MODE_KEY = "PreToolUse.bash_safe_mode"


def _register_safe_mode(**options: Any) -> tuple[HandlerRegistry, BashSafeModeHandler]:
    registry = HandlerRegistry()
    registry.discover()
    router = EventRouter()
    config = {"pre_tool_use": {"bash_safe_mode": {"enabled": True, "options": options}}}
    registry.register_all(router, config=config)
    for handler in router.get_chain(EventType.PRE_TOOL_USE).handlers:
        if isinstance(handler, BashSafeModeHandler):
            return registry, handler
    raise AssertionError("bash_safe_mode was dropped by an invalid option")


@pytest.mark.parametrize("bad", ["inject", "bogus", 5, None, ["warn"]])
def test_a_bad_safe_mode_is_reported_and_the_guard_stays_registered_on_block(bad: object) -> None:
    registry, handler = _register_safe_mode(mode=bad, min_statements=3)

    assert "mode" in registry.option_failures[_SAFE_MODE_KEY]
    assert handler._mode == "block"
    assert handler._min_statements == 3  # its other options are untouched


def test_the_reserved_inject_mode_is_reported_with_the_reason() -> None:
    registry, _handler = _register_safe_mode(mode="inject")

    assert "reserved" in registry.option_failures[_SAFE_MODE_KEY]


@pytest.mark.parametrize("bad", ["^git", [1], ["["], ["^ok", "(unclosed"], {"a": "b"}, None])
def test_bad_exempt_patterns_are_reported_and_the_guard_stays_registered(bad: object) -> None:
    registry, handler = _register_safe_mode(exempt_patterns=bad)

    assert "exempt_patterns" in registry.option_failures[_SAFE_MODE_KEY]
    assert handler._exempt_patterns == []


def test_good_safe_mode_options_are_applied_with_no_failure() -> None:
    registry, handler = _register_safe_mode(mode="warn", exempt_patterns=["^git status"])

    assert registry.option_failures == {}
    assert handler._mode == "warn"
    assert [p.pattern for p in handler._exempt_patterns] == ["^git status"]
