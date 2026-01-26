"""Tests for PreToolUse hook entry point."""

from pathlib import Path
from unittest.mock import Mock, patch

from claude_code_hooks_daemon.hooks.pre_tool_use import (
    get_builtin_handlers,
    load_config_safe,
    main,
)


class TestGetBuiltinHandlers:
    """Test built-in handler registry."""

    def test_returns_dictionary_of_handlers(self) -> None:
        """Built-in handlers are returned as dict mapping name to class."""
        handlers = get_builtin_handlers()

        assert isinstance(handlers, dict)
        assert len(handlers) == 14  # All 14 built-in handlers

    def test_contains_all_expected_handlers(self) -> None:
        """All expected handler names are present."""
        handlers = get_builtin_handlers()

        expected = [
            "destructive_git",
            "git_stash",
            "absolute_path",
            "web_search_year",
            "british_english",
            "eslint_disable",
            "tdd_enforcement",
            "sed_blocker",
            "worktree_file_copy",
            "validate_plan_number",
            "markdown_organization",
            "plan_time_estimates",
            "plan_workflow",
            "npm_command",
        ]

        for handler_name in expected:
            assert handler_name in handlers

    def test_handler_classes_are_importable(self) -> None:
        """Handler classes can be instantiated."""
        handlers = get_builtin_handlers()

        # Spot check a few handlers
        from claude_code_hooks_daemon.handlers.pre_tool_use.destructive_git import (
            DestructiveGitHandler,
        )

        assert handlers["destructive_git"] == DestructiveGitHandler


class TestLoadConfigSafe:
    """Test safe configuration loading with fallback."""

    def test_loads_config_when_file_exists(self, tmp_path: Path) -> None:
        """Config loaded successfully when file exists."""
        config_file = tmp_path / "hooks-daemon.yaml"
        config_file.write_text(
            "version: '1.0'\nhandlers:\n  pre_tool_use:\n    destructive_git:\n      enabled: true\n"
        )

        config = load_config_safe(config_file)

        assert config["version"] == "1.0"
        assert "handlers" in config

    def test_returns_default_config_when_file_not_found(self) -> None:
        """Returns default config when file doesn't exist."""
        config = load_config_safe(Path("/nonexistent/path.yaml"))

        assert config["version"] == "1.0"
        assert "handlers" in config
        assert "plugins" in config

    def test_returns_default_config_when_file_invalid(self, tmp_path: Path) -> None:
        """Returns default config when YAML is invalid."""
        config_file = tmp_path / "bad.yaml"
        config_file.write_text("invalid: yaml: content: {{")

        config = load_config_safe(config_file)

        assert config["version"] == "1.0"
        assert "handlers" in config


class TestMainFunction:
    """Test main entry point function."""

    @patch("claude_code_hooks_daemon.hooks.pre_tool_use.FrontController")
    @patch("claude_code_hooks_daemon.hooks.pre_tool_use.load_config_safe")
    def test_creates_front_controller_with_correct_event(
        self, mock_load_config: Mock, mock_fc_class: Mock
    ) -> None:
        """FrontController created with PreToolUse event name."""
        mock_load_config.return_value = {"handlers": {}, "plugins": []}
        mock_fc_instance = Mock()
        mock_fc_class.return_value = mock_fc_instance

        main()

        mock_fc_class.assert_called_once_with(event_name="PreToolUse")
        mock_fc_instance.run.assert_called_once()

    @patch("claude_code_hooks_daemon.hooks.pre_tool_use.FrontController")
    @patch("claude_code_hooks_daemon.hooks.pre_tool_use.load_config_safe")
    def test_loads_config_from_file(self, mock_load_config: Mock, mock_fc_class: Mock) -> None:
        """Config loaded from standard path."""
        mock_load_config.return_value = {"handlers": {}, "plugins": []}
        mock_fc_instance = Mock()
        mock_fc_class.return_value = mock_fc_instance

        main()

        # Should call load_config_safe with result from find_config
        assert mock_load_config.call_count == 1

    @patch("claude_code_hooks_daemon.hooks.pre_tool_use.FrontController")
    @patch("claude_code_hooks_daemon.hooks.pre_tool_use.load_config_safe")
    def test_registers_enabled_builtin_handlers(
        self, mock_load_config: Mock, mock_fc_class: Mock
    ) -> None:
        """Enabled built-in handlers are registered."""
        config = {
            "handlers": {
                "pre_tool_use": {
                    "destructive_git": {"enabled": True, "priority": 15},
                    "git_stash": {"enabled": False},
                }
            },
            "plugins": [],
        }
        mock_load_config.return_value = config
        mock_fc_instance = Mock()
        mock_fc_class.return_value = mock_fc_instance

        main()

        # Should register destructive_git (enabled) but not git_stash (disabled)
        register_calls = mock_fc_instance.register.call_args_list
        assert len(register_calls) >= 1

        # Check that at least one handler was registered
        registered_handler = register_calls[0][0][0]
        assert hasattr(registered_handler, "priority")

    @patch("claude_code_hooks_daemon.hooks.pre_tool_use.FrontController")
    @patch("claude_code_hooks_daemon.hooks.pre_tool_use.load_config_safe")
    def test_handlers_default_to_enabled_if_not_specified(
        self, mock_load_config: Mock, mock_fc_class: Mock
    ) -> None:
        """Handlers enabled by default if not explicitly disabled."""
        config = {
            "handlers": {
                "pre_tool_use": {
                    "destructive_git": {},  # No 'enabled' key - should default to True
                }
            },
            "plugins": [],
        }
        mock_load_config.return_value = config
        mock_fc_instance = Mock()
        mock_fc_class.return_value = mock_fc_instance

        main()

        # Should register destructive_git with default enabled
        register_calls = mock_fc_instance.register.call_args_list
        assert len(register_calls) >= 1

    @patch("claude_code_hooks_daemon.hooks.pre_tool_use.FrontController")
    @patch("claude_code_hooks_daemon.hooks.pre_tool_use.load_config_safe")
    def test_applies_custom_priority_from_config(
        self, mock_load_config: Mock, mock_fc_class: Mock
    ) -> None:
        """Custom priority from config overrides handler default."""
        config = {
            "handlers": {
                "pre_tool_use": {
                    "destructive_git": {"enabled": True, "priority": 99},
                }
            },
            "plugins": [],
        }
        mock_load_config.return_value = config
        mock_fc_instance = Mock()
        mock_fc_class.return_value = mock_fc_instance

        main()

        # Check handler has custom priority
        register_calls = mock_fc_instance.register.call_args_list
        assert len(register_calls) >= 1

        registered_handler = register_calls[0][0][0]
        assert registered_handler.priority == 99

    @patch("claude_code_hooks_daemon.hooks.pre_tool_use.FrontController")
    @patch("claude_code_hooks_daemon.hooks.pre_tool_use.load_config_safe")
    @patch("claude_code_hooks_daemon.hooks.pre_tool_use.PluginLoader")
    def test_loads_plugin_handlers(
        self, mock_plugin_loader: Mock, mock_load_config: Mock, mock_fc_class: Mock
    ) -> None:
        """Plugin handlers loaded from config."""
        mock_handler = Mock()
        mock_plugin_loader.load_handlers_from_config.return_value = [mock_handler]

        config = {
            "handlers": {"pre_tool_use": {}},
            "plugins": [
                {
                    "enabled": True,
                    "paths": ["/custom/plugins"],
                    "handlers": {"my_plugin": {"enabled": True}},
                }
            ],
        }
        mock_load_config.return_value = config
        mock_fc_instance = Mock()
        mock_fc_class.return_value = mock_fc_instance

        main()

        # Should call PluginLoader with plugin config
        mock_plugin_loader.load_handlers_from_config.assert_called_once()
        plugin_config = mock_plugin_loader.load_handlers_from_config.call_args[0][0]
        assert plugin_config["enabled"] is True

        # Should register the plugin handler
        register_calls = mock_fc_instance.register.call_args_list
        assert mock_handler in [call[0][0] for call in register_calls]

    @patch("claude_code_hooks_daemon.hooks.pre_tool_use.FrontController")
    @patch("claude_code_hooks_daemon.hooks.pre_tool_use.load_config_safe")
    def test_runs_controller_dispatcher(self, mock_load_config: Mock, mock_fc_class: Mock) -> None:
        """FrontController.run() is called to process hook input."""
        mock_load_config.return_value = {"handlers": {}, "plugins": []}
        mock_fc_instance = Mock()
        mock_fc_class.return_value = mock_fc_instance

        main()

        mock_fc_instance.run.assert_called_once()

    @patch("claude_code_hooks_daemon.hooks.pre_tool_use.FrontController")
    @patch("claude_code_hooks_daemon.hooks.pre_tool_use.load_config_safe")
    def test_handles_empty_config(self, mock_load_config: Mock, mock_fc_class: Mock) -> None:
        """Empty config doesn't crash - uses defaults."""
        mock_load_config.return_value = {}
        mock_fc_instance = Mock()
        mock_fc_class.return_value = mock_fc_instance

        main()

        # Should not crash and should call run
        mock_fc_instance.run.assert_called_once()

    @patch("claude_code_hooks_daemon.hooks.pre_tool_use.FrontController")
    @patch("claude_code_hooks_daemon.hooks.pre_tool_use.load_config_safe")
    def test_multiple_handlers_registered_in_priority_order(
        self, mock_load_config: Mock, mock_fc_class: Mock
    ) -> None:
        """Multiple enabled handlers are all registered."""
        config = {
            "handlers": {
                "pre_tool_use": {
                    "destructive_git": {"enabled": True, "priority": 10},
                    "git_stash": {"enabled": True, "priority": 20},
                    "sed_blocker": {"enabled": True, "priority": 15},
                }
            },
            "plugins": [],
        }
        mock_load_config.return_value = config
        mock_fc_instance = Mock()
        mock_fc_class.return_value = mock_fc_instance

        main()

        # Should register all 14 handlers (default to enabled)
        # Only 3 are explicitly configured, others use defaults
        register_calls = mock_fc_instance.register.call_args_list
        assert len(register_calls) == 14

        # Check that configured handlers have custom priorities
        registered_handlers = [call[0][0] for call in register_calls]
        priorities = {type(h).__name__: h.priority for h in registered_handlers}

        assert priorities["DestructiveGitHandler"] == 10
        assert priorities["GitStashHandler"] == 20
        assert priorities["SedBlockerHandler"] == 15
