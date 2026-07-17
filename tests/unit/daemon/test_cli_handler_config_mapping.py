"""Regression tests for the daemon handler_config mapping (status_line bug).

Bug: ``_build_initialised_controller`` built the per-event ``handler_config``
mapping passed to ``register_all`` from a hand-maintained list of event types
that OMITTED ``status_line``. As a result every status-line handler fell back
to ``enabled=True`` and ``handlers.status_line.<name>.enabled: false`` was
inert — a documented config toggle silently ignored. These tests pin the
mapping to the model's own event-type fields so it can never drift again.
"""

from pathlib import Path

import claude_code_hooks_daemon.handlers as handlers_pkg
from claude_code_hooks_daemon.config.models import Config
from claude_code_hooks_daemon.daemon.cli import _build_handler_config_mapping
from claude_code_hooks_daemon.handlers.registry import EVENT_TYPE_MAPPING


def test_mapping_includes_status_line() -> None:
    """status_line must be present in the handler_config mapping."""
    mapping = _build_handler_config_mapping(Config())
    assert "status_line" in mapping


def test_mapping_covers_every_handler_directory() -> None:
    """The mapping must cover every handler directory register_all processes.

    ``register_all`` iterates ``EVENT_TYPE_MAPPING`` and, for each directory
    that exists, reads that event's config from the mapping. Any existing
    handler directory absent from the mapping falls back to ``enabled=True``
    for all its handlers — the status_line defect. Guard against that drift.
    """
    handlers_dir = Path(handlers_pkg.__file__).parent
    existing_handler_dirs = {
        dir_name for dir_name in EVENT_TYPE_MAPPING if (handlers_dir / dir_name).is_dir()
    }
    mapping = _build_handler_config_mapping(Config())
    for event_key in existing_handler_dirs:
        assert event_key in mapping, f"handler_config mapping missing '{event_key}'"


def test_status_line_disabled_flag_propagates() -> None:
    """A disabled status-line handler must surface enabled=False in the mapping.

    This is the exact defect: the loader parsed the flag, but the mapping
    never carried status_line to the registry, so the flag was discarded.
    """
    config = Config.model_validate(
        {"handlers": {"status_line": {"daemon_stats": {"enabled": False}}}}
    )
    mapping = _build_handler_config_mapping(config)
    assert mapping["status_line"]["daemon_stats"]["enabled"] is False


def test_mapping_values_are_plain_dicts() -> None:
    """register_all reads values with dict.get(...); values must be plain dicts."""
    config = Config.model_validate(
        {"handlers": {"status_line": {"account_display": {"enabled": False}}}}
    )
    mapping = _build_handler_config_mapping(config)
    account_display = mapping["status_line"]["account_display"]
    assert isinstance(account_display, dict)
    # HandlerConfig has no .get(); a plain dict does. Guards against passing
    # un-dumped pydantic models through to the registry.
    assert account_display.get("enabled") is False


def test_disabled_status_handler_absent_from_router_chain() -> None:
    """End-to-end: a disabled status handler is not registered on the router.

    Proves the full path config -> mapping -> register_all -> router honours
    ``handlers.status_line.<name>.enabled: false``. Before the fix the mapping
    omitted status_line, so the handler registered regardless of the flag.
    """
    from claude_code_hooks_daemon.core.event import EventType
    from claude_code_hooks_daemon.core.router import EventRouter
    from claude_code_hooks_daemon.handlers.registry import HandlerRegistry

    config = Config.model_validate(
        {"handlers": {"status_line": {"daemon_stats": {"enabled": False}}}}
    )
    mapping = _build_handler_config_mapping(config)

    router = EventRouter()
    registry = HandlerRegistry()
    registry.discover()
    registry.register_all(router, config=mapping)

    status_names = [h.name for h in router.get_chain(EventType.STATUS_LINE).handlers]
    assert "status-daemon-stats" not in status_names
    # Control: a sibling left enabled is still registered.
    assert "status-git-branch" in status_names
