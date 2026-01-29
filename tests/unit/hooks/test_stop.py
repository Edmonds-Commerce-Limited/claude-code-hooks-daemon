"""Tests for Stop hook entry point."""

from pathlib import Path
from unittest.mock import Mock, patch

from claude_code_hooks_daemon.hooks.stop import (
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
        assert len(handlers) == 2  # auto_continue_stop and task_completion_checker

    def test_contains_expected_handlers(self) -> None:
        """Expected handlers are present."""
        handlers = get_builtin_handlers()

        assert "auto_continue_stop" in handlers
        assert "task_completion_checker" in handlers

    def test_handler_classes_are_importable(self) -> None:
        """Handler classes can be instantiated."""
        handlers = get_builtin_handlers()

        from claude_code_hooks_daemon.handlers.stop.auto_continue_stop import (
            AutoContinueStopHandler,
        )
        from claude_code_hooks_daemon.handlers.stop.task_completion_checker import (
            TaskCompletionCheckerHandler,
        )

        assert handlers["auto_continue_stop"] == AutoContinueStopHandler
        assert handlers["task_completion_checker"] == TaskCompletionCheckerHandler


class TestLoadConfigSafe:
    """Test safe configuration loading with fallback."""

    def test_loads_config_when_file_exists(self, tmp_path: Path) -> None:
        """Config loaded successfully when file exists."""
        config_file = tmp_path / "hooks-daemon.yaml"
        config_file.write_text(
            "version: '1.0'\nhandlers:\n  stop:\n    task_completion_checker:\n      enabled: true\n"
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

    @patch("claude_code_hooks_daemon.hooks.stop.FrontController")
    @patch("claude_code_hooks_daemon.hooks.stop.load_config_safe")
    def test_creates_front_controller_with_correct_event(
        self, mock_load_config: Mock, mock_fc_class: Mock
    ) -> None:
        """FrontController created with Stop event name."""
        mock_load_config.return_value = {"handlers": {}, "daemon": {}}
        mock_fc_instance = Mock()
        mock_fc_class.return_value = mock_fc_instance

        main()

        mock_fc_class.assert_called_once_with(event_name="Stop")
        mock_fc_instance.run.assert_called_once()

    @patch("claude_code_hooks_daemon.hooks.stop.FrontController")
    @patch("claude_code_hooks_daemon.hooks.stop.load_config_safe")
    def test_registers_enabled_builtin_handlers(
        self, mock_load_config: Mock, mock_fc_class: Mock
    ) -> None:
        """Enabled built-in handlers are registered."""
        config = {
            "handlers": {
                "stop": {
                    "auto_continue_stop": {"enabled": True},
                    "task_completion_checker": {"enabled": True},
                }
            },
            "daemon": {},
        }
        mock_load_config.return_value = config
        mock_fc_instance = Mock()
        mock_fc_class.return_value = mock_fc_instance

        main()

        register_calls = mock_fc_instance.register.call_args_list
        assert len(register_calls) == 2

        # Both handlers should be registered
        handler_names = [type(call[0][0]).__name__ for call in register_calls]
        assert "AutoContinueStopHandler" in handler_names
        assert "TaskCompletionCheckerHandler" in handler_names

    @patch("claude_code_hooks_daemon.hooks.stop.FrontController")
    @patch("claude_code_hooks_daemon.hooks.stop.load_config_safe")
    def test_handlers_default_to_enabled_if_not_specified(
        self, mock_load_config: Mock, mock_fc_class: Mock
    ) -> None:
        """Handlers enabled by default if not explicitly disabled."""
        config = {
            "handlers": {
                "stop": {
                    "task_completion_checker": {},  # No 'enabled' key
                }
            },
            "daemon": {},
        }
        mock_load_config.return_value = config
        mock_fc_instance = Mock()
        mock_fc_class.return_value = mock_fc_instance

        main()

        register_calls = mock_fc_instance.register.call_args_list
        assert len(register_calls) >= 1

    @patch("claude_code_hooks_daemon.hooks.stop.FrontController")
    @patch("claude_code_hooks_daemon.hooks.stop.load_config_safe")
    def test_applies_custom_priority_from_config(
        self, mock_load_config: Mock, mock_fc_class: Mock
    ) -> None:
        """Custom priority from config overrides handler default."""
        config = {
            "handlers": {
                "stop": {
                    "auto_continue_stop": {"enabled": False},
                    "task_completion_checker": {"enabled": True, "priority": 99},
                }
            },
            "daemon": {},
        }
        mock_load_config.return_value = config
        mock_fc_instance = Mock()
        mock_fc_class.return_value = mock_fc_instance

        main()

        register_calls = mock_fc_instance.register.call_args_list
        assert len(register_calls) == 1

        registered_handler = register_calls[0][0][0]
        assert registered_handler.priority == 99

    @patch("claude_code_hooks_daemon.hooks.stop.FrontController")
    @patch("claude_code_hooks_daemon.hooks.stop.load_config_safe")
    def test_hello_world_handler_registered_when_enabled(
        self, mock_load_config: Mock, mock_fc_class: Mock
    ) -> None:
        """Hello world handler registered when enable_hello_world_handlers is True."""
        config = {
            "handlers": {"stop": {}},
            "daemon": {"enable_hello_world_handlers": True},
        }
        mock_load_config.return_value = config
        mock_fc_instance = Mock()
        mock_fc_class.return_value = mock_fc_instance

        main()

        from claude_code_hooks_daemon.handlers.stop.hello_world import (
            HelloWorldStopHandler,
        )

        register_calls = mock_fc_instance.register.call_args_list
        handler_types = [type(call[0][0]) for call in register_calls]
        assert HelloWorldStopHandler in handler_types

    @patch("claude_code_hooks_daemon.hooks.stop.FrontController")
    @patch("claude_code_hooks_daemon.hooks.stop.load_config_safe")
    def test_skips_disabled_handlers(self, mock_load_config: Mock, mock_fc_class: Mock) -> None:
        """Handlers with enabled: false are not registered."""
        config = {
            "handlers": {
                "stop": {
                    "auto_continue_stop": {"enabled": False},
                    "task_completion_checker": {"enabled": False},
                }
            },
            "daemon": {},
        }
        mock_load_config.return_value = config
        mock_fc_instance = Mock()
        mock_fc_class.return_value = mock_fc_instance

        main()

        register_calls = mock_fc_instance.register.call_args_list
        assert len(register_calls) == 0

    @patch("claude_code_hooks_daemon.hooks.stop.FrontController")
    @patch("claude_code_hooks_daemon.hooks.stop.load_config_safe")
    def test_runs_controller_dispatcher(self, mock_load_config: Mock, mock_fc_class: Mock) -> None:
        """FrontController.run() is called to process hook input."""
        mock_load_config.return_value = {"handlers": {}, "daemon": {}}
        mock_fc_instance = Mock()
        mock_fc_class.return_value = mock_fc_instance

        main()

        mock_fc_instance.run.assert_called_once()

    @patch("claude_code_hooks_daemon.hooks.stop.FrontController")
    @patch("claude_code_hooks_daemon.hooks.stop.load_config_safe")
    def test_handles_empty_config(self, mock_load_config: Mock, mock_fc_class: Mock) -> None:
        """Empty config doesn't crash - uses defaults."""
        mock_load_config.return_value = {}
        mock_fc_instance = Mock()
        mock_fc_class.return_value = mock_fc_instance

        main()

        mock_fc_instance.run.assert_called_once()

    @patch("claude_code_hooks_daemon.hooks.stop.ConfigLoader")
    @patch("claude_code_hooks_daemon.hooks.stop.FrontController")
    @patch("claude_code_hooks_daemon.hooks.stop.load_config_safe")
    def test_handles_config_find_failure(
        self, mock_load_config: Mock, mock_fc_class: Mock, mock_config_loader: Mock
    ) -> None:
        """Handles FileNotFoundError from ConfigLoader.find_config()."""
        mock_config_loader.find_config.side_effect = FileNotFoundError("Config not found")
        mock_load_config.return_value = {"handlers": {}, "daemon": {}}
        mock_fc_instance = Mock()
        mock_fc_class.return_value = mock_fc_instance

        main()

        # Should fallback and use default config path
        mock_load_config.assert_called_once()
        mock_fc_instance.run.assert_called_once()

    @patch("claude_code_hooks_daemon.hooks.stop.FrontController")
    @patch("claude_code_hooks_daemon.hooks.stop.load_config_safe")
    def test_enable_tags_filters_handlers(
        self, mock_load_config: Mock, mock_fc_class: Mock
    ) -> None:
        """Handlers filtered by enable_tags - only matching handlers registered."""
        config = {
            "handlers": {
                "stop": {
                    "enable_tags": ["terminal"],  # Only handlers with 'terminal' tag
                    "auto_continue_stop": {"enabled": True},
                    "task_completion_checker": {"enabled": True},
                }
            },
            "daemon": {},
        }
        mock_load_config.return_value = config
        mock_fc_instance = Mock()
        mock_fc_class.return_value = mock_fc_instance

        main()

        register_calls = mock_fc_instance.register.call_args_list
        # auto_continue_stop has 'terminal' tag, task_completion_checker doesn't
        assert len(register_calls) == 1
        registered_handler = register_calls[0][0][0]
        assert "terminal" in registered_handler.tags

    @patch("claude_code_hooks_daemon.hooks.stop.FrontController")
    @patch("claude_code_hooks_daemon.hooks.stop.load_config_safe")
    def test_disable_tags_filters_handlers(
        self, mock_load_config: Mock, mock_fc_class: Mock
    ) -> None:
        """Handlers filtered by disable_tags - handlers with disabled tags skipped."""
        config = {
            "handlers": {
                "stop": {
                    "disable_tags": ["terminal"],  # Skip handlers with 'terminal' tag
                    "auto_continue_stop": {"enabled": True},
                    "task_completion_checker": {"enabled": True},
                }
            },
            "daemon": {},
        }
        mock_load_config.return_value = config
        mock_fc_instance = Mock()
        mock_fc_class.return_value = mock_fc_instance

        main()

        register_calls = mock_fc_instance.register.call_args_list
        # auto_continue_stop has 'terminal' tag (should be skipped)
        # task_completion_checker doesn't (should be registered)
        assert len(register_calls) == 1
        registered_handler = register_calls[0][0][0]
        assert "terminal" not in registered_handler.tags
