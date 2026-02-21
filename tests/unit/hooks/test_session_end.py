"""Tests for SessionEnd hook entry point."""

from pathlib import Path
from unittest.mock import Mock, patch

from claude_code_hooks_daemon.hooks.session_end import (
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
        assert len(handlers) == 1  # cleanup_handler

    def test_contains_cleanup_handler(self) -> None:
        """Cleanup handler is present."""
        handlers = get_builtin_handlers()

        assert "cleanup_handler" in handlers

    def test_handler_classes_are_importable(self) -> None:
        """Handler classes can be instantiated."""
        handlers = get_builtin_handlers()

        from claude_code_hooks_daemon.handlers.session_end.cleanup_handler import (
            CleanupHandler,
        )

        assert handlers["cleanup_handler"] == CleanupHandler


class TestLoadConfigSafe:
    """Test safe configuration loading with fallback."""

    def test_loads_config_when_file_exists(self, tmp_path: Path) -> None:
        """Config loaded successfully when file exists."""
        config_file = tmp_path / "hooks-daemon.yaml"
        config_file.write_text(
            "version: '1.0'\nhandlers:\n  session_end:\n    cleanup_handler:\n      enabled: true\n"
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

    @patch("claude_code_hooks_daemon.hooks.session_end.FrontController")
    @patch("claude_code_hooks_daemon.hooks.session_end.load_config_safe")
    def test_creates_front_controller_with_correct_event(
        self, mock_load_config: Mock, mock_fc_class: Mock
    ) -> None:
        """FrontController created with SessionEnd event name."""
        mock_load_config.return_value = {"handlers": {}, "daemon": {}}
        mock_fc_instance = Mock()
        mock_fc_class.return_value = mock_fc_instance

        main()

        mock_fc_class.assert_called_once_with(event_name="SessionEnd")
        mock_fc_instance.run.assert_called_once()

    @patch("claude_code_hooks_daemon.hooks.session_end.FrontController")
    @patch("claude_code_hooks_daemon.hooks.session_end.load_config_safe")
    def test_registers_enabled_builtin_handlers(
        self, mock_load_config: Mock, mock_fc_class: Mock
    ) -> None:
        """Enabled built-in handlers are registered."""
        config = {
            "handlers": {
                "session_end": {
                    "cleanup_handler": {"enabled": True, "priority": 50},
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

        registered_handler = register_calls[0][0][0]
        assert hasattr(registered_handler, "priority")
        assert registered_handler.priority == 50

    @patch("claude_code_hooks_daemon.hooks.session_end.FrontController")
    @patch("claude_code_hooks_daemon.hooks.session_end.load_config_safe")
    def test_handlers_default_to_enabled_if_not_specified(
        self, mock_load_config: Mock, mock_fc_class: Mock
    ) -> None:
        """Handlers enabled by default if not explicitly disabled."""
        config = {
            "handlers": {
                "session_end": {
                    "cleanup_handler": {},  # No 'enabled' key
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

    @patch("claude_code_hooks_daemon.hooks.session_end.FrontController")
    @patch("claude_code_hooks_daemon.hooks.session_end.load_config_safe")
    def test_applies_custom_priority_from_config(
        self, mock_load_config: Mock, mock_fc_class: Mock
    ) -> None:
        """Custom priority from config overrides handler default."""
        config = {
            "handlers": {
                "session_end": {
                    "cleanup_handler": {"enabled": True, "priority": 99},
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

        registered_handler = register_calls[0][0][0]
        assert registered_handler.priority == 99

    @patch("claude_code_hooks_daemon.hooks.session_end.FrontController")
    @patch("claude_code_hooks_daemon.hooks.session_end.load_config_safe")
    def test_hello_world_handler_registered_when_enabled(
        self, mock_load_config: Mock, mock_fc_class: Mock
    ) -> None:
        """Hello world handler registered when enable_hello_world_handlers is True."""
        config = {
            "handlers": {"session_end": {}},
            "daemon": {"enable_hello_world_handlers": True},
        }
        mock_load_config.return_value = config
        mock_fc_instance = Mock()
        mock_fc_class.return_value = mock_fc_instance

        main()

        from claude_code_hooks_daemon.handlers.session_end.hello_world import (
            HelloWorldSessionEndHandler,
        )

        register_calls = mock_fc_instance.register.call_args_list
        handler_types = [type(call[0][0]) for call in register_calls]
        assert HelloWorldSessionEndHandler in handler_types

    @patch("claude_code_hooks_daemon.hooks.session_end.FrontController")
    @patch("claude_code_hooks_daemon.hooks.session_end.load_config_safe")
    def test_skips_disabled_handlers(self, mock_load_config: Mock, mock_fc_class: Mock) -> None:
        """Handlers with enabled: false are not registered."""
        config = {
            "handlers": {
                "session_end": {
                    "cleanup_handler": {"enabled": False},
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

    @patch("claude_code_hooks_daemon.hooks.session_end.FrontController")
    @patch("claude_code_hooks_daemon.hooks.session_end.load_config_safe")
    def test_runs_controller_dispatcher(self, mock_load_config: Mock, mock_fc_class: Mock) -> None:
        """FrontController.run() is called to process hook input."""
        mock_load_config.return_value = {"handlers": {}, "daemon": {}}
        mock_fc_instance = Mock()
        mock_fc_class.return_value = mock_fc_instance

        main()

        mock_fc_instance.run.assert_called_once()

    @patch("claude_code_hooks_daemon.hooks.session_end.FrontController")
    @patch("claude_code_hooks_daemon.hooks.session_end.load_config_safe")
    def test_handles_empty_config(self, mock_load_config: Mock, mock_fc_class: Mock) -> None:
        """Empty config doesn't crash - uses defaults."""
        mock_load_config.return_value = {}
        mock_fc_instance = Mock()
        mock_fc_class.return_value = mock_fc_instance

        main()

        mock_fc_instance.run.assert_called_once()

    @patch("claude_code_hooks_daemon.hooks.session_end.ConfigLoader.find_config")
    @patch("claude_code_hooks_daemon.hooks.session_end.FrontController")
    @patch("claude_code_hooks_daemon.hooks.session_end.load_config_safe")
    def test_handles_config_not_found(
        self, mock_load_config: Mock, mock_fc_class: Mock, mock_find_config: Mock
    ) -> None:
        """When config file not found, uses default path."""
        mock_find_config.side_effect = FileNotFoundError("Config not found")
        mock_load_config.return_value = {"handlers": {}, "daemon": {}}
        mock_fc_instance = Mock()
        mock_fc_class.return_value = mock_fc_instance

        main()

        # Should call load_config_safe with default path
        expected_path = Path(".claude/hooks-daemon.yaml")
        mock_load_config.assert_called_once_with(expected_path)

    @patch("claude_code_hooks_daemon.hooks.session_end.FrontController")
    @patch("claude_code_hooks_daemon.hooks.session_end.load_config_safe")
    def test_tag_filtering_with_enable_tags(
        self, mock_load_config: Mock, mock_fc_class: Mock
    ) -> None:
        """Handlers filtered by enable_tags."""
        config = {
            "handlers": {
                "session_end": {
                    "enable_tags": ["cleanup"],  # Only handlers with 'cleanup' tag
                    "cleanup_handler": {"enabled": True},
                }
            },
            "daemon": {},
        }
        mock_load_config.return_value = config
        mock_fc_instance = Mock()
        mock_fc_class.return_value = mock_fc_instance

        main()

        # Handler should be registered or skipped based on tags
        # CleanupHandler doesn't have 'cleanup' tag by default, so it should be skipped
        # The actual behavior depends on CleanupHandler's tags

    @patch("claude_code_hooks_daemon.hooks.session_end.FrontController")
    @patch("claude_code_hooks_daemon.hooks.session_end.load_config_safe")
    def test_tag_filtering_with_disable_tags(
        self, mock_load_config: Mock, mock_fc_class: Mock
    ) -> None:
        """Handlers filtered by disable_tags."""
        config = {
            "handlers": {
                "session_end": {
                    "disable_tags": ["test"],  # Skip handlers with 'test' tag
                    "cleanup_handler": {"enabled": True},
                }
            },
            "daemon": {},
        }
        mock_load_config.return_value = config
        mock_fc_instance = Mock()
        mock_fc_class.return_value = mock_fc_instance

        main()

        # Handler should be registered or skipped based on tags
        # The actual behavior depends on CleanupHandler's tags

    @patch("claude_code_hooks_daemon.hooks.session_end.FrontController")
    @patch("claude_code_hooks_daemon.hooks.session_end.load_config_safe")
    def test_skips_handler_when_init_raises_runtime_error(
        self, mock_load_config: Mock, mock_fc_class: Mock
    ) -> None:
        """Handlers whose __init__ raises RuntimeError are skipped gracefully."""
        config = {
            "handlers": {
                "session_end": {
                    "cleanup_handler": {"enabled": True},
                }
            },
            "daemon": {},
        }
        mock_load_config.return_value = config
        mock_fc_instance = Mock()
        mock_fc_class.return_value = mock_fc_instance

        mock_handler_class = Mock(side_effect=RuntimeError("ProjectContext not initialized"))
        mock_handler_class.__name__ = "MockSessionEndHandler"

        with patch(
            "claude_code_hooks_daemon.hooks.session_end.get_builtin_handlers",
            return_value={"cleanup_handler": mock_handler_class},
        ):
            main()

        # Handler should be skipped, no register calls
        register_calls = mock_fc_instance.register.call_args_list
        assert len(register_calls) == 0
        mock_fc_instance.run.assert_called_once()

    @patch("claude_code_hooks_daemon.hooks.session_end.ConfigLoader")
    @patch("claude_code_hooks_daemon.hooks.session_end.FrontController")
    @patch("claude_code_hooks_daemon.hooks.session_end.load_config_safe")
    def test_handles_config_find_failure(
        self, mock_load_config: Mock, mock_fc_class: Mock, mock_config_loader: Mock
    ) -> None:
        """Handles FileNotFoundError from ConfigLoader.find_config()."""
        mock_config_loader.find_config.side_effect = FileNotFoundError("Config not found")
        mock_load_config.return_value = {"handlers": {}, "daemon": {}}
        mock_fc_instance = Mock()
        mock_fc_class.return_value = mock_fc_instance

        main()

        mock_load_config.assert_called_once()
        mock_fc_instance.run.assert_called_once()
