"""Integration tests for plugin system with FrontController."""

from pathlib import Path

import pytest

from claude_code_hooks_daemon.core import FrontController, HookResult
from claude_code_hooks_daemon.core.hook_result import Decision
from claude_code_hooks_daemon.plugins import PluginLoader


class TestPluginIntegration:
    """Test plugin handlers integrated with FrontController."""

    @pytest.fixture
    def plugin_dir(self):
        """Return path to test plugin fixtures."""
        return Path(__file__).parent.parent / "fixtures" / "plugins"

    @pytest.fixture
    def controller(self):
        """Create a fresh FrontController instance."""
        return FrontController(event_name="PreToolUse")

    def test_load_and_register_plugin_handler(self, controller, plugin_dir):
        """Test loading plugin handler and registering with controller."""
        handler = PluginLoader.load_handler("custom_handler", plugin_dir)

        assert handler is not None
        controller.register(handler)

        # Handler should be in registered handlers
        assert handler in controller.handlers

    def test_plugin_handler_dispatch(self, controller, plugin_dir):
        """Test that registered plugin handler is dispatched correctly."""
        handler = PluginLoader.load_handler("custom_handler", plugin_dir)
        controller.register(handler)

        hook_input = {"tool_name": "Bash", "tool_input": {"command": "ls"}}
        result = controller.dispatch(hook_input)

        assert isinstance(result, HookResult)
        assert result.decision == Decision.ALLOW
        context_text = "\n".join(result.context)
        assert "Test custom handler" in context_text

    def test_plugin_handler_priority_ordering(self, controller, plugin_dir):
        """Test that plugin handlers are dispatched in priority order."""
        # Load handlers with different priorities
        handler1 = PluginLoader.load_handler("another_test_handler", plugin_dir)  # priority 30
        handler2 = PluginLoader.load_handler("handler_v2_example", plugin_dir)  # priority 40
        handler3 = PluginLoader.load_handler("custom_handler", plugin_dir)  # priority 50

        # Register in random order
        controller.register(handler3)
        controller.register(handler1)
        controller.register(handler2)

        # Should be sorted by priority
        assert controller.handlers[0].priority == 30
        assert controller.handlers[1].priority == 40
        assert controller.handlers[2].priority == 50

    def test_plugin_handler_with_config(self, controller, plugin_dir):
        """Test plugin handler loads with default config."""
        # Plugin handlers are responsible for their own initialization
        # Config parameter support was removed from PluginLoader
        handler = PluginLoader.load_handler("another_test_handler", plugin_dir)

        assert handler is not None
        assert handler.config == {}  # type: ignore[attr-defined]
        assert handler.test_value == "default"  # type: ignore[attr-defined]

        controller.register(handler)

        hook_input = {"tool_name": "test", "tool_input": {}}
        result = controller.dispatch(hook_input)

        context_text = "\n".join(result.context)
        assert "default" in context_text

    def test_plugin_error_handling_doesnt_break_dispatch(self, controller, plugin_dir):
        """Test that plugin errors are contained and don't crash dispatch."""
        # Load a handler that will fail (missing_methods_handler has methods but they raise NotImplementedError)
        handler = PluginLoader.load_handler("missing_methods_handler", plugin_dir)

        if handler:
            controller.register(handler)

            hook_input = {"tool_name": "Bash", "tool_input": {"command": "ls"}}

            # FrontController should catch the exception and return error in context
            result = controller.dispatch(hook_input)

            # Should return "allow" decision (fail open) with error in context
            assert result.decision == Decision.ALLOW
            context_text = "\n".join(result.context)
            assert "Hook handler error" in context_text or "error" in context_text.lower()

    def test_load_multiple_plugins_from_config(self, controller, plugin_dir):
        """Test loading multiple plugins from configuration."""
        config = {
            "enabled": True,
            "paths": [str(plugin_dir)],
            "handlers": {
                "custom_handler": {"enabled": True},
                "another_test_handler": {
                    "enabled": True,
                    "config": {"test_value": "config_test"},
                },
                "handler_v2_example": {"enabled": True},
            },
        }

        handlers = PluginLoader.load_handlers_from_config(config)

        assert len(handlers) == 3

        # Register all with controller
        for handler in handlers:
            controller.register(handler)

        assert len(controller.handlers) == 3

    def test_plugin_handlers_sorted_with_built_in_handlers(self, controller, plugin_dir):
        """Test that plugin handlers are sorted correctly with built-in handlers."""

        # Create a mock built-in handler with priority 20
        class MockBuiltInHandler:
            def __init__(self):
                self.name = "mock-builtin"
                self.priority = 20
                self.terminal = True

            def matches(self, hook_input):
                return False

            def handle(self, hook_input):
                return HookResult(decision=Decision.ALLOW)

        builtin = MockBuiltInHandler()
        controller.register(builtin)

        # Load plugin handler with priority 30
        plugin = PluginLoader.load_handler("another_test_handler", plugin_dir)
        controller.register(plugin)

        # Built-in should come first (lower priority number)
        assert controller.handlers[0] == builtin
        assert controller.handlers[1] == plugin

    def test_disabled_plugin_not_loaded(self, plugin_dir):
        """Test that disabled plugins are not loaded from config."""
        config = {
            "enabled": True,
            "paths": [str(plugin_dir)],
            "handlers": {
                "custom_handler": {"enabled": False},  # Disabled
                "another_test_handler": {"enabled": True},  # Enabled
            },
        }

        handlers = PluginLoader.load_handlers_from_config(config)

        assert len(handlers) == 1
        assert handlers[0].name == "another-test"

    def test_plugins_disabled_globally(self, plugin_dir):
        """Test that no plugins load when globally disabled."""
        config = {
            "enabled": False,  # Globally disabled
            "paths": [str(plugin_dir)],
            "handlers": {
                "custom_handler": {"enabled": True},
                "another_test_handler": {"enabled": True},
            },
        }

        handlers = PluginLoader.load_handlers_from_config(config)

        assert handlers == []


class TestPluginIntegrationWithPluginsConfig:
    """Test plugin integration using PluginsConfig model (new format)."""

    @pytest.fixture
    def plugin_dir(self):
        """Return path to test plugin fixtures."""
        return Path(__file__).parent.parent / "fixtures" / "plugins"

    @pytest.fixture
    def controller(self):
        """Create a fresh FrontController instance."""
        return FrontController(event_name="PreToolUse")

    def test_load_from_plugins_config_and_dispatch(self, controller, plugin_dir):
        """Test loading from PluginsConfig and dispatching through FrontController."""
        from claude_code_hooks_daemon.config.models import PluginConfig, PluginsConfig

        plugins_config = PluginsConfig(
            paths=[str(plugin_dir)],
            plugins=[
                PluginConfig(path="custom_handler", event_type="pre_tool_use", enabled=True),
            ],
        )

        handlers = PluginLoader.load_from_plugins_config(plugins_config)
        assert len(handlers) == 1

        controller.register(handlers[0])

        hook_input = {"tool_name": "Bash", "tool_input": {"command": "ls"}}
        result = controller.dispatch(hook_input)

        assert isinstance(result, HookResult)
        assert result.decision == Decision.ALLOW
        context_text = "\n".join(result.context)
        assert "Test custom handler" in context_text

    def test_load_multiple_plugins_from_plugins_config(self, controller, plugin_dir):
        """Test loading multiple plugins from PluginsConfig model."""
        from claude_code_hooks_daemon.config.models import PluginConfig, PluginsConfig

        plugins_config = PluginsConfig(
            paths=[str(plugin_dir)],
            plugins=[
                PluginConfig(path="custom_handler", event_type="pre_tool_use", enabled=True),
                PluginConfig(path="another_test_handler", event_type="pre_tool_use", enabled=True),
                PluginConfig(path="handler_v2_example", event_type="pre_tool_use", enabled=True),
            ],
        )

        handlers = PluginLoader.load_from_plugins_config(plugins_config)
        assert len(handlers) == 3

        # Register all with controller
        for handler in handlers:
            controller.register(handler)

        assert len(controller.handlers) == 3
        # Verify priority ordering
        assert controller.handlers[0].priority == 30  # another_test_handler
        assert controller.handlers[1].priority == 40  # handler_v2_example
        assert controller.handlers[2].priority == 50  # custom_handler

    def test_plugins_config_disabled_plugin_not_loaded(self, plugin_dir):
        """Test that disabled plugins in PluginsConfig are not loaded."""
        from claude_code_hooks_daemon.config.models import PluginConfig, PluginsConfig

        plugins_config = PluginsConfig(
            paths=[str(plugin_dir)],
            plugins=[
                PluginConfig(path="custom_handler", event_type="pre_tool_use", enabled=False),
                PluginConfig(path="another_test_handler", event_type="pre_tool_use", enabled=True),
            ],
        )

        handlers = PluginLoader.load_from_plugins_config(plugins_config)

        assert len(handlers) == 1
        assert handlers[0].name == "another-test"

    def test_plugins_config_with_event_type_filtering(self, controller, plugin_dir):
        """Test that event_type is properly associated with plugins."""
        from claude_code_hooks_daemon.config.models import PluginConfig, PluginsConfig

        plugins_config = PluginsConfig(
            paths=[str(plugin_dir)],
            plugins=[
                PluginConfig(path="custom_handler", event_type="pre_tool_use", enabled=True),
                PluginConfig(path="another_test_handler", event_type="post_tool_use", enabled=True),
            ],
        )

        handlers = PluginLoader.load_from_plugins_config(plugins_config)

        # Both should load (event_type is for registration, not filtering at load time)
        assert len(handlers) == 2

    def test_plugins_config_with_specific_handler_classes(self, controller, plugin_dir):
        """Test loading specific handler classes from PluginsConfig."""
        from claude_code_hooks_daemon.config.models import PluginConfig, PluginsConfig

        plugins_config = PluginsConfig(
            paths=[str(plugin_dir)],
            plugins=[
                PluginConfig(
                    path="custom_handler",
                    event_type="pre_tool_use",
                    handlers=["CustomHandler"],
                    enabled=True,
                ),
            ],
        )

        handlers = PluginLoader.load_from_plugins_config(plugins_config)

        assert len(handlers) == 1
        assert handlers[0].name == "test-custom"

        # Register and dispatch
        controller.register(handlers[0])
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "ls"}}
        result = controller.dispatch(hook_input)

        assert result.decision == Decision.ALLOW
        context_text = "\n".join(result.context)
        assert "Test custom handler" in context_text
