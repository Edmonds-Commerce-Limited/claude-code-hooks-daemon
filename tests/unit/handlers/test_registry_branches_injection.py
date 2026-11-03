"""`register_all` injects the `branches:` block as `_branches` (Plan 00558 Tasks 2.0, 2.3).

Selected by declared attribute, like `_reference_repos`: only handlers that
declare `_branches` receive it. Also pins the `branch_count_advisor` alias end
to end: the old key, folded at config load, still disables the branch sweep
and still delivers its options.
"""

from typing import Any

from claude_code_hooks_daemon.config.models import BranchesConfig, Config
from claude_code_hooks_daemon.core.event import EventType
from claude_code_hooks_daemon.core.router import EventRouter
from claude_code_hooks_daemon.handlers.registry import (
    HandlerRegistry,
    build_handler_config_mapping,
)
from claude_code_hooks_daemon.handlers.session_start.branch_sweep import BranchSweepHandler


def _registered(
    config: dict[str, Any], branches: BranchesConfig | None
) -> BranchSweepHandler | None:
    registry = HandlerRegistry()
    registry.discover()
    router = EventRouter()
    registry.register_all(router, config=config, branches=branches)
    for handler in router.get_chain(EventType.SESSION_START).handlers:
        if isinstance(handler, BranchSweepHandler):
            return handler
    return None


def _sweep(branches: BranchesConfig | None) -> BranchSweepHandler:
    handler = _registered({"session_start": {"branch_sweep": {"enabled": True}}}, branches)
    assert handler is not None, "branch_sweep was not registered"
    return handler


def _from_yaml_shape(handlers: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return build_handler_config_mapping(Config.model_validate({"handlers": handlers}))


def test_the_block_is_injected() -> None:
    branches = BranchesConfig.model_validate({"wip": {"cap": 7}})
    assert _sweep(branches)._branches is branches


def test_absent_block_leaves_the_model_default() -> None:
    assert _sweep(None)._branches == BranchesConfig()


def test_old_key_disabled_keeps_the_sweep_off() -> None:
    mapping = _from_yaml_shape({"session_start": {"branch_count_advisor": {"enabled": False}}})
    assert _registered(mapping, None) is None


def test_old_key_options_reach_the_sweep() -> None:
    mapping = _from_yaml_shape(
        {"session_start": {"branch_count_advisor": {"options": {"max_open_branches": 4}}}}
    )
    handler = _registered(mapping, None)
    assert handler is not None
    assert handler._max_open_branches == 4
