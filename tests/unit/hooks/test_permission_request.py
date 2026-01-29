"""Tests for PermissionRequest hook entry point."""

from pathlib import Path
from unittest.mock import Mock, patch

from claude_code_hooks_daemon.hooks.permission_request import (
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
        assert len(handlers) == 1  # auto_approve_reads

    def test_contains_auto_approve_reads_handler(self) -> None:
        """Auto approve reads handler is present."""
        handlers = get_builtin_handlers()

        assert "auto_approve_reads" in handlers

    def test_handler_classes_are_importable(self) -> None:
        """Handler classes can be instantiated."""
        handlers = get_builtin_handlers()

        from claude_code_hooks_daemon.handlers.permission_request.auto_approve_reads import (
            AutoApproveReadsHandler,
        )

        assert handlers["auto_approve_reads"] == AutoApproveReadsHandler


class TestLoadConfigSafe:
    """Test safe configuration loading with fallback."""

    def test_loads_config_when_file_exists(self, tmp_path: Path) -> None:
        """Config loaded successfully when file exists."""
        config_file = tmp_path / "hooks-daemon.yaml"
        config_file.write_text(
            "version: '1.0'\nhandlers:\n  permission_request:\n    auto_approve_reads:\n      enabled: true\n"
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

    @patch("claude_code_hooks_daemon.hooks.permission_request.FrontController")
    @patch("claude_code_hooks_daemon.hooks.permission_request.load_config_safe")
    def test_creates_front_controller_with_correct_event(
        self, mock_load_config: Mock, mock_fc_class: Mock
    ) -> None:
        """FrontController created with PermissionRequest event name."""
        mock_load_config.return_value = {"handlers": {}, "daemon": {}}
        mock_fc_instance = Mock()
        mock_fc_class.return_value = mock_fc_instance

        main()

        mock_fc_class.assert_called_once_with(event_name="PermissionRequest")
        mock_fc_instance.run.assert_called_once()

    @patch("claude_code_hooks_daemon.hooks.permission_request.FrontController")
    @patch("claude_code_hooks_daemon.hooks.permission_request.load_config_safe")
    def test_registers_enabled_builtin_handlers(
        self, mock_load_config: Mock, mock_fc_class: Mock
    ) -> None:
        """Enabled built-in handlers are registered."""
        config = {
            "handlers": {
                "permission_request": {
                    "auto_approve_reads": {"enabled": True, "priority": 50},
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

    @patch("claude_code_hooks_daemon.hooks.permission_request.FrontController")
    @patch("claude_code_hooks_daemon.hooks.permission_request.load_config_safe")
    def test_hello_world_handler_registered_when_enabled(
        self, mock_load_config: Mock, mock_fc_class: Mock
    ) -> None:
        """Hello world handler registered when enable_hello_world_handlers is True."""
        config = {
            "handlers": {"permission_request": {}},
            "daemon": {"enable_hello_world_handlers": True},
        }
        mock_load_config.return_value = config
        mock_fc_instance = Mock()
        mock_fc_class.return_value = mock_fc_instance

        main()

        from claude_code_hooks_daemon.handlers.permission_request.hello_world import (
            HelloWorldPermissionRequestHandler,
        )

        register_calls = mock_fc_instance.register.call_args_list
        handler_types = [type(call[0][0]) for call in register_calls]
        assert HelloWorldPermissionRequestHandler in handler_types

    @patch("claude_code_hooks_daemon.hooks.permission_request.FrontController")
    @patch("claude_code_hooks_daemon.hooks.permission_request.load_config_safe")
    def test_skips_disabled_handlers(self, mock_load_config: Mock, mock_fc_class: Mock) -> None:
        """Handlers with enabled: false are not registered."""
        config = {
            "handlers": {
                "permission_request": {
                    "auto_approve_reads": {"enabled": False},
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

    @patch("claude_code_hooks_daemon.hooks.permission_request.FrontController")
    @patch("claude_code_hooks_daemon.hooks.permission_request.load_config_safe")
    def test_tag_filtering_with_enable_tags(
        self, mock_load_config: Mock, mock_fc_class: Mock
    ) -> None:
        """Only handlers with matching enabled tags are registered."""
        config = {
            "handlers": {
                "permission_request": {
                    "enable_tags": ["automation"],
                }
            },
            "daemon": {},
        }
        mock_load_config.return_value = config
        mock_fc_instance = Mock()
        mock_fc_class.return_value = mock_fc_instance

        main()

        register_calls = mock_fc_instance.register.call_args_list
        assert isinstance(register_calls, list)

    @patch("claude_code_hooks_daemon.hooks.permission_request.FrontController")
    @patch("claude_code_hooks_daemon.hooks.permission_request.load_config_safe")
    def test_runs_controller_dispatcher(self, mock_load_config: Mock, mock_fc_class: Mock) -> None:
        """FrontController.run() is called to process hook input."""
        mock_load_config.return_value = {"handlers": {}, "daemon": {}}
        mock_fc_instance = Mock()
        mock_fc_class.return_value = mock_fc_instance

        main()

        mock_fc_instance.run.assert_called_once()

    @patch("claude_code_hooks_daemon.hooks.permission_request.ConfigLoader")
    @patch("claude_code_hooks_daemon.hooks.permission_request.FrontController")
    @patch("claude_code_hooks_daemon.hooks.permission_request.load_config_safe")
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

    @patch("claude_code_hooks_daemon.hooks.permission_request.FrontController")
    @patch("claude_code_hooks_daemon.hooks.permission_request.load_config_safe")
    def test_enable_tags_filters_handlers(
        self, mock_load_config: Mock, mock_fc_class: Mock
    ) -> None:
        """Handlers filtered by enable_tags - only matching handlers registered."""
        config = {
            "handlers": {
                "permission_request": {
                    "enable_tags": ["workflow"],  # AutoApproveReadsHandler has this tag
                    "auto_approve_reads": {"enabled": True},
                }
            },
            "daemon": {},
        }
        mock_load_config.return_value = config
        mock_fc_instance = Mock()
        mock_fc_class.return_value = mock_fc_instance

        main()

        register_calls = mock_fc_instance.register.call_args_list
        # Handler should be registered (has 'workflow' tag)
        assert len(register_calls) == 1
        registered_handler = register_calls[0][0][0]
        assert "workflow" in registered_handler.tags

    @patch("claude_code_hooks_daemon.hooks.permission_request.FrontController")
    @patch("claude_code_hooks_daemon.hooks.permission_request.load_config_safe")
    def test_disable_tags_filters_handlers(
        self, mock_load_config: Mock, mock_fc_class: Mock
    ) -> None:
        """Handlers filtered by disable_tags - handlers with disabled tags skipped."""
        config = {
            "handlers": {
                "permission_request": {
                    "disable_tags": ["terminal"],  # AutoApproveReadsHandler has this tag
                    "auto_approve_reads": {"enabled": True},
                }
            },
            "daemon": {},
        }
        mock_load_config.return_value = config
        mock_fc_instance = Mock()
        mock_fc_class.return_value = mock_fc_instance

        main()

        register_calls = mock_fc_instance.register.call_args_list
        # Handler should be filtered out by disable_tags (has 'terminal' tag)
        assert len(register_calls) == 0
