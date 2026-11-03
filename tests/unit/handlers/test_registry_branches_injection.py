"""`register_all` injects the `branches:` block as `_branches` (Plan 00558 Task 2.0).

Selected by declared attribute, like `_reference_repos`: only handlers that
declare `_branches` receive it.
"""

from claude_code_hooks_daemon.config.models import BranchesConfig
from claude_code_hooks_daemon.core.event import EventType
from claude_code_hooks_daemon.core.router import EventRouter
from claude_code_hooks_daemon.handlers.registry import HandlerRegistry
from claude_code_hooks_daemon.handlers.session_start.branch_count_advisor import (
    BranchCountAdvisorHandler,
)


def _advisor(branches: BranchesConfig | None) -> BranchCountAdvisorHandler:
    registry = HandlerRegistry()
    registry.discover()
    router = EventRouter()
    config = {"session_start": {"branch_count_advisor": {"enabled": True}}}
    registry.register_all(router, config=config, branches=branches)
    for handler in router.get_chain(EventType.SESSION_START).handlers:
        if isinstance(handler, BranchCountAdvisorHandler):
            return handler
    raise AssertionError("branch_count_advisor was not registered")


def test_the_block_is_injected() -> None:
    branches = BranchesConfig.model_validate({"wip": {"cap": 7}})
    assert _advisor(branches)._branches is branches


def test_absent_block_leaves_the_model_default() -> None:
    assert _advisor(None)._branches == BranchesConfig()
