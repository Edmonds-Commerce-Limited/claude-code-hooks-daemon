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
from claude_code_hooks_daemon.handlers.registry import HandlerRegistry
from claude_code_hooks_daemon.handlers.user_prompt_submit.idle_housekeeping_advisor import (
    IdleHousekeepingAdvisoryHandler,
)
from claude_code_hooks_daemon.utils.stale_checkouts import DEFAULT_MAX_IDLE_DAYS

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
