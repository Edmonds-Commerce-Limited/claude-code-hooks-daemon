"""Unit tests for plugin loader."""

import logging
from pathlib import Path

import pytest

from claude_code_hooks_daemon.core import Handler
from claude_code_hooks_daemon.plugins.loader import PluginLoader


class TestSnakeToPascalCase:
    """Test snake_case to PascalCase conversion."""

    def test_snake_to_pascal_basic(self):
        """Test basic snake_case to PascalCase conversion."""
        assert PluginLoader.snake_to_pascal("test_handler") == "TestHandler"
        assert PluginLoader.snake_to_pascal("my_custom_handler") == "MyCustomHandler"

    def test_snake_to_pascal_single_word(self):
        """Test single word conversion."""
        assert PluginLoader.snake_to_pascal("handler") == "Handler"
        assert PluginLoader.snake_to_pascal("test") == "Test"

    def test_snake_to_pascal_handles_numbers(self):
        """Test conversion with numbers in name."""
        assert PluginLoader.snake_to_pascal("handler_v2") == "HandlerV2"
        assert PluginLoader.snake_to_pascal("test_v2_handler") == "TestV2Handler"
        assert PluginLoader.snake_to_pascal("handler_2") == "Handler2"

    def test_snake_to_pascal_handles_multiple_underscores(self):
        """Test conversion with multiple consecutive underscores."""
        assert PluginLoader.snake_to_pascal("my__handler") == "MyHandler"
        assert PluginLoader.snake_to_pascal("test___multiple") == "TestMultiple"

    def test_snake_to_pascal_handles_leading_underscore(self):
        """Test conversion with leading underscore."""
        assert PluginLoader.snake_to_pascal("_handler") == "Handler"
        assert PluginLoader.snake_to_pascal("__private") == "Private"

    def test_snake_to_pascal_handles_trailing_underscore(self):
        """Test conversion with trailing underscore."""
        assert PluginLoader.snake_to_pascal("handler_") == "Handler"
        assert PluginLoader.snake_to_pascal("test__") == "Test"

    def test_snake_to_pascal_empty_string(self):
        """Test conversion with empty string."""
        assert PluginLoader.snake_to_pascal("") == ""

    def test_snake_to_pascal_already_pascal(self):
        """Test conversion with already PascalCase name."""
        assert PluginLoader.snake_to_pascal("TestHandler") == "Testhandler"


class TestLoadHandler:
    """Test loading individual handlers from plugin paths."""

    @pytest.fixture
    def plugin_dir(self):
        """Return path to test plugin fixtures."""
        return Path(__file__).parent.parent / "fixtures" / "plugins"

    def test_load_handler_from_path(self, plugin_dir):
        """Test loading a valid handler from plugin path."""
        handler = PluginLoader.load_handler("custom_handler", plugin_dir)

        assert handler is not None
        assert isinstance(handler, Handler)
        assert handler.name == "test-custom"
        assert handler.priority == 50

    def test_load_handler_uses_default_config(self, plugin_dir):
        """Test loading handler uses default config from handler."""
        handler = PluginLoader.load_handler("another_test_handler", plugin_dir)

        assert handler is not None
        assert handler.config == {}  # type: ignore[attr-defined]
        assert handler.test_value == "default"  # type: ignore[attr-defined]

    def test_load_handler_version_number_naming(self, plugin_dir):
        """Test loading handler with version number in name."""
        handler = PluginLoader.load_handler("handler_v2_example", plugin_dir)

        assert handler is not None
        assert handler.name == "handler-v2"

    def test_load_nonexistent_module_returns_none(self, plugin_dir):
        """Test loading non-existent module returns None."""
        handler = PluginLoader.load_handler("does_not_exist", plugin_dir)
        assert handler is None

    def test_load_invalid_handler_returns_none(self, plugin_dir):
        """Test loading class that's not a Handler subclass returns None."""
        handler = PluginLoader.load_handler("invalid_handler", plugin_dir)
        assert handler is None

    def test_load_syntax_error_module_returns_none(self, plugin_dir):
        """Test loading module with syntax errors returns None."""
        handler = PluginLoader.load_handler("syntax_error_handler", plugin_dir)
        assert handler is None

    def test_load_handler_missing_methods_returns_none(self, plugin_dir):
        """Test loading handler missing abstract methods returns None."""
        # Handler base class is ABC - handlers must implement matches() and handle()
        # Trying to instantiate without these methods will fail
        handler = PluginLoader.load_handler("missing_methods_handler", plugin_dir)
        assert handler is None

    def test_load_handler_init_error_returns_none(self, plugin_dir):
        """Test loading handler that fails during __init__ returns None."""
        handler = PluginLoader.load_handler("init_error_handler", plugin_dir)
        assert handler is None

    def test_load_logs_import_errors(self, plugin_dir, caplog):
        """Test that import errors are logged."""
        with caplog.at_level(logging.ERROR):
            PluginLoader.load_handler("syntax_error_handler", plugin_dir)

        assert any("Failed to import plugin" in record.message for record in caplog.records)

    def test_load_logs_instantiation_errors(self, plugin_dir, caplog):
        """Test that instantiation errors are logged."""
        with caplog.at_level(logging.ERROR):
            PluginLoader.load_handler("init_error_handler", plugin_dir)

        assert any("Failed to instantiate handler" in record.message for record in caplog.records)

    def test_load_logs_validation_errors(self, plugin_dir, caplog):
        """Test that validation errors are logged."""
        with caplog.at_level(logging.ERROR):
            PluginLoader.load_handler("invalid_handler", plugin_dir)

        assert any("is not a Handler subclass" in record.message for record in caplog.records)

    def test_load_validates_subclass_requirement(self, plugin_dir, caplog):
        """Test that validation checks Handler subclass requirement."""
        with caplog.at_level(logging.ERROR):
            handler = PluginLoader.load_handler("invalid_handler", plugin_dir)

        assert handler is None
        assert any("not a Handler subclass" in record.message for record in caplog.records)

    def test_load_handler_wrong_class_name_returns_none(self, plugin_dir, caplog):
        """Test loading handler with class name that doesn't match file name."""
        with caplog.at_level(logging.ERROR):
            handler = PluginLoader.load_handler("wrong_class_name", plugin_dir)

        assert handler is None
        assert any("does not contain class" in record.message for record in caplog.records)

    def test_load_handler_without_acceptance_tests_logs_warning(self, plugin_dir, caplog):
        """Test that handler with empty acceptance tests logs warning but loads successfully."""
        with caplog.at_level(logging.WARNING):
            handler = PluginLoader.load_handler("no_acceptance_tests_handler", plugin_dir)

        # Handler should load (fail-open for plugins)
        assert handler is not None
        assert isinstance(handler, Handler)
        assert handler.name == "no-acceptance-tests"

        # Should log warning about missing acceptance tests
        assert any("acceptance test" in record.message.lower() for record in caplog.records)
        assert any(record.levelname == "WARNING" for record in caplog.records)

    def test_load_handler_validates_acceptance_tests(self, plugin_dir, caplog):
        """Test that handler with valid acceptance tests loads without warnings."""
        with caplog.at_level(logging.WARNING):
            handler = PluginLoader.load_handler("custom_handler", plugin_dir)

        # Handler should load successfully
        assert handler is not None
        assert isinstance(handler, Handler)
        assert handler.name == "test-custom"

        # Should NOT log any warnings about acceptance tests
        acceptance_warnings = [
            record
            for record in caplog.records
            if record.levelname == "WARNING" and "acceptance test" in record.message.lower()
        ]
        assert len(acceptance_warnings) == 0


class TestDiscoverHandlers:
    """Test handler discovery in directories."""

    @pytest.fixture
    def plugin_dir(self):
        """Return path to test plugin fixtures."""
        return Path(__file__).parent.parent / "fixtures" / "plugins"

    def test_discover_handlers_in_directory(self, plugin_dir):
        """Test discovering all .py files in directory."""
        handlers = PluginLoader.discover_handlers(plugin_dir)

        assert isinstance(handlers, list)
        assert len(handlers) > 0
        # Should find valid handler modules (not test_ or __init__)
        assert "custom_handler" in handlers
        assert "another_test_handler" in handlers
        assert "handler_v2_example" in handlers

    def test_discover_ignores_init_files(self, plugin_dir):
        """Test that __init__.py files are ignored."""
        handlers = PluginLoader.discover_handlers(plugin_dir)

        assert "__init__" not in handlers
        assert "__init__.py" not in handlers

    def test_discover_ignores_test_files(self, plugin_dir):
        """Test that test_*.py files are ignored."""
        handlers = PluginLoader.discover_handlers(plugin_dir)

        assert "test_should_be_ignored" not in handlers
        assert not any(h.startswith("test_") for h in handlers)

    def test_discover_returns_module_names_without_extension(self, plugin_dir):
        """Test that discovery returns module names without .py extension."""
        handlers = PluginLoader.discover_handlers(plugin_dir)

        for handler_name in handlers:
            assert not handler_name.endswith(".py")
            assert isinstance(handler_name, str)

    def test_discover_nonexistent_directory_returns_empty_list(self):
        """Test discovering in non-existent directory returns empty list."""
        handlers = PluginLoader.discover_handlers(Path("/nonexistent/path"))
        assert handlers == []

    def test_discover_empty_directory_returns_empty_list(self, tmp_path):
        """Test discovering in empty directory returns empty list."""
        handlers = PluginLoader.discover_handlers(tmp_path)
        assert handlers == []


class TestLoadHandlersFromConfig:
    """Test loading handlers from configuration."""

    @pytest.fixture
    def plugin_dir(self):
        """Return path to test plugin fixtures."""
        return Path(__file__).parent.parent / "fixtures" / "plugins"

    def test_load_handlers_from_config_basic(self, plugin_dir):
        """Test loading handlers from basic config."""
        config = {
            "enabled": True,
            "paths": [str(plugin_dir)],
            "handlers": {
                "custom_handler": {"enabled": True},
                "another_test_handler": {"enabled": True},
            },
        }

        handlers = PluginLoader.load_handlers_from_config(config)

        assert len(handlers) == 2
        assert all(isinstance(h, Handler) for h in handlers)
        handler_names = [h.name for h in handlers]
        assert "test-custom" in handler_names
        assert "another-test" in handler_names

    def test_load_handlers_from_config_uses_handler_defaults(self, plugin_dir):
        """Test loading handlers uses handler's default config."""
        config = {
            "enabled": True,
            "paths": [str(plugin_dir)],
            "handlers": {
                "another_test_handler": {
                    "enabled": True,
                }
            },
        }

        handlers = PluginLoader.load_handlers_from_config(config)

        assert len(handlers) == 1
        handler = handlers[0]
        # Handler uses its own default config since loader doesn't pass config
        assert handler.test_value == "default"  # type: ignore[attr-defined]

    def test_load_handlers_skips_disabled_handlers(self, plugin_dir):
        """Test that disabled handlers are not loaded."""
        config = {
            "enabled": True,
            "paths": [str(plugin_dir)],
            "handlers": {
                "custom_handler": {"enabled": False},
                "another_test_handler": {"enabled": True},
            },
        }

        handlers = PluginLoader.load_handlers_from_config(config)

        assert len(handlers) == 1
        assert handlers[0].name == "another-test"

    def test_load_handlers_from_config_plugins_disabled(self, plugin_dir):
        """Test that no handlers loaded when plugins disabled."""
        config = {
            "enabled": False,
            "paths": [str(plugin_dir)],
            "handlers": {
                "custom_handler": {"enabled": True},
            },
        }

        handlers = PluginLoader.load_handlers_from_config(config)

        assert handlers == []

    def test_load_handlers_from_config_no_paths(self):
        """Test loading with no paths configured."""
        config = {"enabled": True, "paths": [], "handlers": {}}

        handlers = PluginLoader.load_handlers_from_config(config)

        assert handlers == []

    def test_load_handlers_from_config_multiple_paths(self, plugin_dir, tmp_path):
        """Test loading handlers from multiple paths."""
        # Create another plugin directory
        other_plugin_dir = tmp_path / "other_plugins"
        other_plugin_dir.mkdir()

        # Copy a handler to the other directory
        (other_plugin_dir / "custom_handler.py").write_text(
            (plugin_dir / "custom_handler.py").read_text()
        )

        config = {
            "enabled": True,
            "paths": [str(plugin_dir), str(other_plugin_dir)],
            "handlers": {"custom_handler": {"enabled": True}},
        }

        handlers = PluginLoader.load_handlers_from_config(config)

        # Should load from first path that has the handler
        assert len(handlers) == 1

    def test_load_handlers_from_config_invalid_path(self, plugin_dir):
        """Test that invalid paths are skipped gracefully."""
        config = {
            "enabled": True,
            "paths": ["/nonexistent/path", str(plugin_dir)],
            "handlers": {"custom_handler": {"enabled": True}},
        }

        handlers = PluginLoader.load_handlers_from_config(config)

        # Should still load from valid path
        assert len(handlers) == 1
        assert handlers[0].name == "test-custom"

    def test_load_handlers_from_config_handler_load_failure_continues(self, plugin_dir):
        """Test that handler load failures don't stop other handlers loading."""
        config = {
            "enabled": True,
            "paths": [str(plugin_dir)],
            "handlers": {
                "syntax_error_handler": {"enabled": True},  # Will fail
                "custom_handler": {"enabled": True},  # Should succeed
            },
        }

        handlers = PluginLoader.load_handlers_from_config(config)

        # Should have loaded the valid handler despite the failed one
        assert len(handlers) == 1
        assert handlers[0].name == "test-custom"

    def test_load_handlers_from_config_empty_handlers_dict(self, plugin_dir):
        """Test loading with empty handlers dict."""
        config = {"enabled": True, "paths": [str(plugin_dir)], "handlers": {}}

        handlers = PluginLoader.load_handlers_from_config(config)

        assert handlers == []

    def test_load_handlers_from_config_sorts_by_priority(self, plugin_dir):
        """Test that loaded handlers are sorted by priority."""
        config = {
            "enabled": True,
            "paths": [str(plugin_dir)],
            "handlers": {
                "custom_handler": {"enabled": True},  # priority 50
                "another_test_handler": {"enabled": True},  # priority 30
                "handler_v2_example": {"enabled": True},  # priority 40
            },
        }

        handlers = PluginLoader.load_handlers_from_config(config)

        assert len(handlers) == 3
        # Should be sorted by priority (30, 40, 50)
        assert handlers[0].priority == 30
        assert handlers[1].priority == 40
        assert handlers[2].priority == 50


class TestLoadFromPluginsConfig:
    """Test loading handlers from PluginsConfig model (new API)."""

    @pytest.fixture
    def plugin_dir(self) -> Path:
        """Return path to test plugin fixtures."""
        return Path(__file__).parent.parent / "fixtures" / "plugins"

    def test_load_from_plugins_config_basic(self, plugin_dir: Path) -> None:
        """Test loading handlers from PluginsConfig model."""
        from claude_code_hooks_daemon.config.models import PluginConfig, PluginsConfig

        plugins_config = PluginsConfig(
            paths=[str(plugin_dir)],
            plugins=[
                PluginConfig(path="custom_handler", event_type="pre_tool_use", enabled=True),
                PluginConfig(path="another_test_handler", event_type="pre_tool_use", enabled=True),
            ],
        )

        handlers = PluginLoader.load_from_plugins_config(plugins_config)

        assert len(handlers) == 2
        assert all(isinstance(h, Handler) for h in handlers)
        handler_names = [h.name for h in handlers]
        assert "test-custom" in handler_names
        assert "another-test" in handler_names

    def test_load_from_plugins_config_disabled_plugin(self, plugin_dir: Path) -> None:
        """Test that disabled plugins are not loaded."""
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

    def test_load_from_plugins_config_empty_plugins(self, plugin_dir: Path) -> None:
        """Test loading with empty plugins list."""
        from claude_code_hooks_daemon.config.models import PluginsConfig

        plugins_config = PluginsConfig(
            paths=[str(plugin_dir)],
            plugins=[],
        )

        handlers = PluginLoader.load_from_plugins_config(plugins_config)

        assert handlers == []

    def test_load_from_plugins_config_no_paths(self) -> None:
        """Test loading with no paths falls back to plugin path."""
        from claude_code_hooks_daemon.config.models import PluginConfig, PluginsConfig

        plugins_config = PluginsConfig(
            paths=[],
            plugins=[
                PluginConfig(
                    path="/absolute/path/to/custom_handler", event_type="pre_tool_use", enabled=True
                ),
            ],
        )

        # Should try to load from the absolute path in plugin.path
        handlers = PluginLoader.load_from_plugins_config(plugins_config)

        # Will fail to load (path doesn't exist), but should not crash
        assert handlers == []

    def test_load_from_plugins_config_with_specific_handlers(self, plugin_dir: Path) -> None:
        """Test loading only specific handler classes from a plugin."""
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

    def test_load_from_plugins_config_sorts_by_priority(self, plugin_dir: Path) -> None:
        """Test that loaded handlers are sorted by priority."""
        from claude_code_hooks_daemon.config.models import PluginConfig, PluginsConfig

        plugins_config = PluginsConfig(
            paths=[str(plugin_dir)],
            plugins=[
                PluginConfig(
                    path="custom_handler", event_type="pre_tool_use", enabled=True
                ),  # priority 50
                PluginConfig(
                    path="another_test_handler", event_type="pre_tool_use", enabled=True
                ),  # priority 30
                PluginConfig(
                    path="handler_v2_example", event_type="pre_tool_use", enabled=True
                ),  # priority 40
            ],
        )

        handlers = PluginLoader.load_from_plugins_config(plugins_config)

        assert len(handlers) == 3
        # Should be sorted by priority (30, 40, 50)
        assert handlers[0].priority == 30
        assert handlers[1].priority == 40
        assert handlers[2].priority == 50

    def test_load_from_plugins_config_invalid_plugin_continues(self, plugin_dir: Path) -> None:
        """Test that invalid plugins don't stop other plugins from loading."""
        from claude_code_hooks_daemon.config.models import PluginConfig, PluginsConfig

        plugins_config = PluginsConfig(
            paths=[str(plugin_dir)],
            plugins=[
                PluginConfig(
                    path="syntax_error_handler", event_type="pre_tool_use", enabled=True
                ),  # Will fail
                PluginConfig(
                    path="custom_handler", event_type="pre_tool_use", enabled=True
                ),  # Should succeed
            ],
        )

        handlers = PluginLoader.load_from_plugins_config(plugins_config)

        assert len(handlers) == 1
        assert handlers[0].name == "test-custom"

    def test_load_from_plugins_config_absolute_path_in_plugin(self, plugin_dir: Path) -> None:
        """Test loading plugin with absolute path in plugin.path."""
        from claude_code_hooks_daemon.config.models import PluginConfig, PluginsConfig

        # Use absolute path in plugin.path instead of relying on search paths
        plugins_config = PluginsConfig(
            paths=[],  # Empty search paths
            plugins=[
                PluginConfig(
                    path=str(plugin_dir / "custom_handler.py"),
                    event_type="pre_tool_use",
                    enabled=True,
                ),
            ],
        )

        handlers = PluginLoader.load_from_plugins_config(plugins_config)

        # Should load from absolute path
        assert len(handlers) == 1
        assert handlers[0].name == "test-custom"

    def test_load_from_plugins_config_multiple_paths_first_wins(
        self, plugin_dir: Path, tmp_path: Path
    ) -> None:
        """Test that first matching path is used when plugin exists in multiple paths."""
        from claude_code_hooks_daemon.config.models import PluginConfig, PluginsConfig

        # Create a second plugin directory with a different version
        other_dir = tmp_path / "other_plugins"
        other_dir.mkdir()

        plugins_config = PluginsConfig(
            paths=[str(plugin_dir), str(other_dir)],
            plugins=[
                PluginConfig(path="custom_handler", event_type="pre_tool_use", enabled=True),
            ],
        )

        handlers = PluginLoader.load_from_plugins_config(plugins_config)

        # Should load from first path
        assert len(handlers) == 1
        assert handlers[0].name == "test-custom"
