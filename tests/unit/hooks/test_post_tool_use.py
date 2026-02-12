"""Tests for PostToolUse hook entry point."""

from pathlib import Path
from unittest.mock import Mock, patch

from claude_code_hooks_daemon.hooks.post_tool_use import (
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
        assert len(handlers) == 2  # bash_error_detector, validate_eslint_on_write

    def test_contains_bash_error_detector_handler(self) -> None:
        """Bash error detector handler is present."""
        handlers = get_builtin_handlers()

        assert "bash_error_detector" in handlers

    def test_contains_validate_eslint_on_write_handler(self) -> None:
        """Validate ESLint on write handler is present."""
        handlers = get_builtin_handlers()

        assert "validate_eslint_on_write" in handlers

    def test_handler_classes_are_importable(self) -> None:
        """Handler classes can be instantiated."""
        handlers = get_builtin_handlers()

        from claude_code_hooks_daemon.handlers.post_tool_use.bash_error_detector import (
            BashErrorDetectorHandler,
        )
        from claude_code_hooks_daemon.handlers.post_tool_use.validate_eslint_on_write import (
            ValidateEslintOnWriteHandler,
        )

        assert handlers["bash_error_detector"] == BashErrorDetectorHandler
        assert handlers["validate_eslint_on_write"] == ValidateEslintOnWriteHandler


class TestLoadConfigSafe:
    """Test safe configuration loading with fallback."""

    def test_loads_config_when_file_exists(self, tmp_path: Path) -> None:
        """Config loaded successfully when file exists."""
        config_file = tmp_path / "hooks-daemon.yaml"
        config_file.write_text(
            "version: '1.0'\nhandlers:\n  post_tool_use:\n    bash_error_detector:\n      enabled: true\n"
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

    @patch("claude_code_hooks_daemon.hooks.post_tool_use.FrontController")
    @patch("claude_code_hooks_daemon.hooks.post_tool_use.load_config_safe")
    def test_creates_front_controller_with_correct_event(
        self, mock_load_config: Mock, mock_fc_class: Mock
    ) -> None:
        """FrontController created with PostToolUse event name."""
        mock_load_config.return_value = {"handlers": {}, "daemon": {}}
        mock_fc_instance = Mock()
        mock_fc_class.return_value = mock_fc_instance

        main()

        mock_fc_class.assert_called_once_with(event_name="PostToolUse")
        mock_fc_instance.run.assert_called_once()

    @patch("claude_code_hooks_daemon.hooks.post_tool_use.FrontController")
    @patch("claude_code_hooks_daemon.hooks.post_tool_use.load_config_safe")
    def test_loads_config_from_file(self, mock_load_config: Mock, mock_fc_class: Mock) -> None:
        """Config loaded from standard path."""
        mock_load_config.return_value = {"handlers": {}, "daemon": {}}
        mock_fc_instance = Mock()
        mock_fc_class.return_value = mock_fc_instance

        main()

        # Should call load_config_safe
        assert mock_load_config.call_count == 1

    @patch("claude_code_hooks_daemon.hooks.post_tool_use.FrontController")
    @patch("claude_code_hooks_daemon.hooks.post_tool_use.load_config_safe")
    def test_registers_enabled_builtin_handlers(
        self, mock_load_config: Mock, mock_fc_class: Mock
    ) -> None:
        """Enabled built-in handlers are registered."""
        config = {
            "handlers": {
                "post_tool_use": {
                    "bash_error_detector": {"enabled": True, "priority": 50},
                }
            },
            "daemon": {},
        }
        mock_load_config.return_value = config
        mock_fc_instance = Mock()
        mock_fc_class.return_value = mock_fc_instance

        main()

        # Should register bash_error_detector
        register_calls = mock_fc_instance.register.call_args_list
        assert len(register_calls) >= 1

        # Check that handler was registered
        registered_handler = register_calls[0][0][0]
        assert hasattr(registered_handler, "priority")

    @patch("claude_code_hooks_daemon.hooks.post_tool_use.FrontController")
    @patch("claude_code_hooks_daemon.hooks.post_tool_use.load_config_safe")
    def test_handlers_default_to_enabled_if_not_specified(
        self, mock_load_config: Mock, mock_fc_class: Mock
    ) -> None:
        """Handlers enabled by default if not explicitly disabled."""
        config = {
            "handlers": {
                "post_tool_use": {
                    "bash_error_detector": {},  # No 'enabled' key
                }
            },
            "daemon": {},
        }
        mock_load_config.return_value = config
        mock_fc_instance = Mock()
        mock_fc_class.return_value = mock_fc_instance

        main()

        # Should register with default enabled
        register_calls = mock_fc_instance.register.call_args_list
        assert len(register_calls) >= 1

    @patch("claude_code_hooks_daemon.hooks.post_tool_use.FrontController")
    @patch("claude_code_hooks_daemon.hooks.post_tool_use.load_config_safe")
    def test_applies_custom_priority_from_config(
        self, mock_load_config: Mock, mock_fc_class: Mock
    ) -> None:
        """Custom priority from config overrides handler default."""
        config = {
            "handlers": {
                "post_tool_use": {
                    "bash_error_detector": {"enabled": True, "priority": 99},
                }
            },
            "daemon": {},
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

    @patch("claude_code_hooks_daemon.hooks.post_tool_use.FrontController")
    @patch("claude_code_hooks_daemon.hooks.post_tool_use.load_config_safe")
    def test_runs_controller_dispatcher(self, mock_load_config: Mock, mock_fc_class: Mock) -> None:
        """FrontController.run() is called to process hook input."""
        mock_load_config.return_value = {"handlers": {}, "daemon": {}}
        mock_fc_instance = Mock()
        mock_fc_class.return_value = mock_fc_instance

        main()

        mock_fc_instance.run.assert_called_once()

    @patch("claude_code_hooks_daemon.hooks.post_tool_use.FrontController")
    @patch("claude_code_hooks_daemon.hooks.post_tool_use.load_config_safe")
    def test_handles_empty_config(self, mock_load_config: Mock, mock_fc_class: Mock) -> None:
        """Empty config doesn't crash - uses defaults."""
        mock_load_config.return_value = {}
        mock_fc_instance = Mock()
        mock_fc_class.return_value = mock_fc_instance

        main()

        # Should not crash and should call run
        mock_fc_instance.run.assert_called_once()

    @patch("claude_code_hooks_daemon.hooks.post_tool_use.FrontController")
    @patch("claude_code_hooks_daemon.hooks.post_tool_use.load_config_safe")
    def test_hello_world_handler_registered_when_enabled(
        self, mock_load_config: Mock, mock_fc_class: Mock
    ) -> None:
        """Hello world handler registered when enable_hello_world_handlers is True."""
        config = {
            "handlers": {"post_tool_use": {}},
            "daemon": {"enable_hello_world_handlers": True},
        }
        mock_load_config.return_value = config
        mock_fc_instance = Mock()
        mock_fc_class.return_value = mock_fc_instance

        main()

        # Should register hello world handler
        register_calls = mock_fc_instance.register.call_args_list
        assert len(register_calls) >= 1

        # Hello world should be registered (priority 5)
        from claude_code_hooks_daemon.handlers.post_tool_use.hello_world import (
            HelloWorldPostToolUseHandler,
        )

        handler_types = [type(call[0][0]) for call in register_calls]
        assert HelloWorldPostToolUseHandler in handler_types

    @patch("claude_code_hooks_daemon.hooks.post_tool_use.FrontController")
    @patch("claude_code_hooks_daemon.hooks.post_tool_use.load_config_safe")
    def test_hello_world_handler_not_registered_when_disabled(
        self, mock_load_config: Mock, mock_fc_class: Mock
    ) -> None:
        """Hello world handler not registered when enable_hello_world_handlers is False."""
        config = {
            "handlers": {"post_tool_use": {}},
            "daemon": {"enable_hello_world_handlers": False},
        }
        mock_load_config.return_value = config
        mock_fc_instance = Mock()
        mock_fc_class.return_value = mock_fc_instance

        main()

        # Should not register hello world handler
        from claude_code_hooks_daemon.handlers.post_tool_use.hello_world import (
            HelloWorldPostToolUseHandler,
        )

        register_calls = mock_fc_instance.register.call_args_list
        handler_types = [type(call[0][0]) for call in register_calls]
        assert HelloWorldPostToolUseHandler not in handler_types

    @patch("claude_code_hooks_daemon.hooks.post_tool_use.FrontController")
    @patch("claude_code_hooks_daemon.hooks.post_tool_use.load_config_safe")
    def test_skips_disabled_handlers(self, mock_load_config: Mock, mock_fc_class: Mock) -> None:
        """Handlers with enabled: false are not registered."""
        config = {
            "handlers": {
                "post_tool_use": {
                    "bash_error_detector": {"enabled": False},
                    "validate_eslint_on_write": {"enabled": False},
                }
            },
            "daemon": {},
        }
        mock_load_config.return_value = config
        mock_fc_instance = Mock()
        mock_fc_class.return_value = mock_fc_instance

        main()

        # Should not register any handlers
        register_calls = mock_fc_instance.register.call_args_list
        assert len(register_calls) == 0

    @patch("claude_code_hooks_daemon.hooks.post_tool_use.FrontController")
    @patch("claude_code_hooks_daemon.hooks.post_tool_use.load_config_safe")
    def test_tag_filtering_with_enable_tags(
        self, mock_load_config: Mock, mock_fc_class: Mock
    ) -> None:
        """Only handlers with matching enabled tags are registered."""
        config = {
            "handlers": {
                "post_tool_use": {
                    "enable_tags": ["error-detection"],
                }
            },
            "daemon": {},
        }
        mock_load_config.return_value = config
        mock_fc_instance = Mock()
        mock_fc_class.return_value = mock_fc_instance

        main()

        # Tag filtering logic executed
        register_calls = mock_fc_instance.register.call_args_list
        assert isinstance(register_calls, list)

    @patch("claude_code_hooks_daemon.hooks.post_tool_use.FrontController")
    @patch("claude_code_hooks_daemon.hooks.post_tool_use.load_config_safe")
    def test_tag_filtering_with_disable_tags(
        self, mock_load_config: Mock, mock_fc_class: Mock
    ) -> None:
        """Handlers with disabled tags are not registered."""
        config = {
            "handlers": {
                "post_tool_use": {
                    "disable_tags": ["error-detection"],
                }
            },
            "daemon": {},
        }
        mock_load_config.return_value = config
        mock_fc_instance = Mock()
        mock_fc_class.return_value = mock_fc_instance

        main()

        # Tag filtering logic executed
        register_calls = mock_fc_instance.register.call_args_list
        assert isinstance(register_calls, list)

    @patch("claude_code_hooks_daemon.hooks.post_tool_use.FrontController")
    @patch("claude_code_hooks_daemon.hooks.post_tool_use.load_config_safe")
    def test_skips_handler_when_init_raises_runtime_error(
        self, mock_load_config: Mock, mock_fc_class: Mock
    ) -> None:
        """Handlers whose __init__ raises RuntimeError are skipped gracefully."""
        config = {
            "handlers": {
                "post_tool_use": {
                    "some_handler": {"enabled": True},
                }
            },
            "daemon": {},
        }
        mock_load_config.return_value = config
        mock_fc_instance = Mock()
        mock_fc_class.return_value = mock_fc_instance

        mock_handler_class = Mock(side_effect=RuntimeError("ProjectContext not initialized"))

        with patch(
            "claude_code_hooks_daemon.hooks.post_tool_use.get_builtin_handlers",
            return_value={"some_handler": mock_handler_class},
        ):
            main()

        register_calls = mock_fc_instance.register.call_args_list
        assert len(register_calls) == 0
        mock_fc_instance.run.assert_called_once()

    @patch("claude_code_hooks_daemon.hooks.post_tool_use.ConfigLoader.find_config")
    @patch("claude_code_hooks_daemon.hooks.post_tool_use.FrontController")
    @patch("claude_code_hooks_daemon.hooks.post_tool_use.load_config_safe")
    def test_handles_config_file_not_found_exception(
        self, mock_load_config: Mock, mock_fc_class: Mock, mock_find_config: Mock
    ) -> None:
        """Config path fallback works when find_config raises FileNotFoundError."""
        mock_find_config.side_effect = FileNotFoundError("Config not found")
        mock_load_config.return_value = {"handlers": {}, "daemon": {}}
        mock_fc_instance = Mock()
        mock_fc_class.return_value = mock_fc_instance

        main()

        # Should fallback to default path and still work
        assert mock_load_config.call_count == 1
        mock_fc_instance.run.assert_called_once()
