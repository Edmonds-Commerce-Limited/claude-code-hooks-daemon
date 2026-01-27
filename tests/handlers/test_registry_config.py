"""Test handler registry configuration handling."""

from claude_code_hooks_daemon.core.router import EventRouter
from claude_code_hooks_daemon.handlers.registry import HandlerRegistry


def test_register_all_with_none_config():
    """Test that register_all handles None config without errors."""
    router = EventRouter()
    registry = HandlerRegistry()
    registry.discover()

    # Should not raise AttributeError
    count = registry.register_all(router, config=None)
    assert count > 0


def test_register_all_with_empty_config():
    """Test that register_all handles empty config dict."""
    router = EventRouter()
    registry = HandlerRegistry()
    registry.discover()

    count = registry.register_all(router, config={})
    assert count > 0


def test_register_all_with_partial_config():
    """Test that register_all handles config with some events missing."""
    router = EventRouter()
    registry = HandlerRegistry()
    registry.discover()

    # Config only has pre_tool_use, other events are missing (None values)
    config = {
        "pre_tool_use": {"destructive_git": {"enabled": True}}
        # Other events not specified (will be None when accessed)
    }

    # Should not raise AttributeError when accessing missing events
    count = registry.register_all(router, config=config)
    assert count > 0


def test_register_all_with_none_event_config():
    """Test that register_all handles None values in event config."""
    router = EventRouter()
    registry = HandlerRegistry()
    registry.discover()

    # Explicitly set some events to None
    config = {
        "pre_tool_use": None,
        "post_tool_use": None,
        "session_start": {"hello_world": {"enabled": False}},
    }

    # Should not raise AttributeError
    count = registry.register_all(router, config=config)
    assert count > 0
