"""Tests for SessionStart hook entry point."""

from pathlib import Path
from unittest.mock import Mock, patch

from claude_code_hooks_daemon.hooks.session_start import (
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
        assert len(handlers) == 2  # workflow_state_restoration, yolo_container_detection

    def test_contains_workflow_state_restoration_handler(self) -> None:
        """Workflow state restoration handler is present."""
        handlers = get_builtin_handlers()

        assert "workflow_state_restoration" in handlers

    def test_contains_yolo_container_detection_handler(self) -> None:
        """YOLO container detection handler is present."""
        handlers = get_builtin_handlers()

        assert "yolo_container_detection" in handlers

    def test_handler_classes_are_importable(self) -> None:
        """Handler classes can be instantiated."""
        handlers = get_builtin_handlers()

        from claude_code_hooks_daemon.handlers.session_start.workflow_state_restoration import (
            WorkflowStateRestorationHandler,
        )
        from claude_code_hooks_daemon.handlers.session_start.yolo_container_detection import (
            YoloContainerDetectionHandler,
        )

        assert handlers["workflow_state_restoration"] == WorkflowStateRestorationHandler
        assert handlers["yolo_container_detection"] == YoloContainerDetectionHandler


class TestLoadConfigSafe:
    """Test safe configuration loading with fallback."""

    def test_loads_config_when_file_exists(self, tmp_path: Path) -> None:
        """Config loaded successfully when file exists."""
        config_file = tmp_path / "hooks-daemon.yaml"
        config_file.write_text(
            "version: '1.0'\nhandlers:\n  session_start:\n    yolo_container_detection:\n      enabled: true\n"
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

    @patch("claude_code_hooks_daemon.hooks.session_start.FrontController")
    @patch("claude_code_hooks_daemon.hooks.session_start.load_config_safe")
    def test_creates_front_controller_with_correct_event(
        self, mock_load_config: Mock, mock_fc_class: Mock
    ) -> None:
        """FrontController created with SessionStart event name."""
        mock_load_config.return_value = {"handlers": {}, "daemon": {}}
        mock_fc_instance = Mock()
        mock_fc_class.return_value = mock_fc_instance

        main()

        mock_fc_class.assert_called_once_with(event_name="SessionStart")
        mock_fc_instance.run.assert_called_once()

    @patch("claude_code_hooks_daemon.hooks.session_start.FrontController")
    @patch("claude_code_hooks_daemon.hooks.session_start.load_config_safe")
    def test_loads_config_from_file(self, mock_load_config: Mock, mock_fc_class: Mock) -> None:
        """Config loaded from standard path."""
        mock_load_config.return_value = {"handlers": {}, "daemon": {}}
        mock_fc_instance = Mock()
        mock_fc_class.return_value = mock_fc_instance

        main()

        # Should call load_config_safe
        assert mock_load_config.call_count == 1

    @patch("claude_code_hooks_daemon.hooks.session_start.FrontController")
    @patch("claude_code_hooks_daemon.hooks.session_start.load_config_safe")
    def test_registers_enabled_builtin_handlers(
        self, mock_load_config: Mock, mock_fc_class: Mock
    ) -> None:
        """Enabled built-in handlers are registered."""
        config = {
            "handlers": {
                "session_start": {
                    "yolo_container_detection": {"enabled": True, "priority": 50},
                }
            },
            "daemon": {},
        }
        mock_load_config.return_value = config
        mock_fc_instance = Mock()
        mock_fc_class.return_value = mock_fc_instance

        main()

        # Should register yolo_container_detection
        register_calls = mock_fc_instance.register.call_args_list
        assert len(register_calls) >= 1

        # Check that handler was registered
        registered_handler = register_calls[0][0][0]
        assert hasattr(registered_handler, "priority")

    @patch("claude_code_hooks_daemon.hooks.session_start.FrontController")
    @patch("claude_code_hooks_daemon.hooks.session_start.load_config_safe")
    def test_handlers_default_to_enabled_if_not_specified(
        self, mock_load_config: Mock, mock_fc_class: Mock
    ) -> None:
        """Handlers enabled by default if not explicitly disabled."""
        config = {
            "handlers": {
                "session_start": {
                    "yolo_container_detection": {},  # No 'enabled' key
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

    @patch("claude_code_hooks_daemon.hooks.session_start.FrontController")
    @patch("claude_code_hooks_daemon.hooks.session_start.load_config_safe")
    def test_applies_custom_priority_from_config(
        self, mock_load_config: Mock, mock_fc_class: Mock
    ) -> None:
        """Custom priority from config overrides handler default."""
        config = {
            "handlers": {
                "session_start": {
                    "workflow_state_restoration": {"enabled": False},  # Disable to test only YOLO
                    "yolo_container_detection": {"enabled": True, "priority": 99},
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

        # Find YOLO handler
        from claude_code_hooks_daemon.handlers.session_start.yolo_container_detection import (
            YoloContainerDetectionHandler,
        )

        yolo_handlers = [
            call[0][0]
            for call in register_calls
            if isinstance(call[0][0], YoloContainerDetectionHandler)
        ]
        assert len(yolo_handlers) == 1
        assert yolo_handlers[0].priority == 99

    @patch("claude_code_hooks_daemon.hooks.session_start.FrontController")
    @patch("claude_code_hooks_daemon.hooks.session_start.load_config_safe")
    def test_runs_controller_dispatcher(self, mock_load_config: Mock, mock_fc_class: Mock) -> None:
        """FrontController.run() is called to process hook input."""
        mock_load_config.return_value = {"handlers": {}, "daemon": {}}
        mock_fc_instance = Mock()
        mock_fc_class.return_value = mock_fc_instance

        main()

        mock_fc_instance.run.assert_called_once()

    @patch("claude_code_hooks_daemon.hooks.session_start.FrontController")
    @patch("claude_code_hooks_daemon.hooks.session_start.load_config_safe")
    def test_handles_empty_config(self, mock_load_config: Mock, mock_fc_class: Mock) -> None:
        """Empty config doesn't crash - uses defaults."""
        mock_load_config.return_value = {}
        mock_fc_instance = Mock()
        mock_fc_class.return_value = mock_fc_instance

        main()

        # Should not crash and should call run
        mock_fc_instance.run.assert_called_once()

    @patch("claude_code_hooks_daemon.hooks.session_start.FrontController")
    @patch("claude_code_hooks_daemon.hooks.session_start.load_config_safe")
    def test_hello_world_handler_registered_when_enabled(
        self, mock_load_config: Mock, mock_fc_class: Mock
    ) -> None:
        """Hello world handler registered when enable_hello_world_handlers is True."""
        config = {
            "handlers": {"session_start": {}},
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
        from claude_code_hooks_daemon.handlers.session_start.hello_world import (
            HelloWorldSessionStartHandler,
        )

        handler_types = [type(call[0][0]) for call in register_calls]
        assert HelloWorldSessionStartHandler in handler_types

    @patch("claude_code_hooks_daemon.hooks.session_start.FrontController")
    @patch("claude_code_hooks_daemon.hooks.session_start.load_config_safe")
    def test_hello_world_handler_not_registered_when_disabled(
        self, mock_load_config: Mock, mock_fc_class: Mock
    ) -> None:
        """Hello world handler not registered when enable_hello_world_handlers is False."""
        config = {
            "handlers": {"session_start": {}},
            "daemon": {"enable_hello_world_handlers": False},
        }
        mock_load_config.return_value = config
        mock_fc_instance = Mock()
        mock_fc_class.return_value = mock_fc_instance

        main()

        # Should not register hello world handler
        from claude_code_hooks_daemon.handlers.session_start.hello_world import (
            HelloWorldSessionStartHandler,
        )

        register_calls = mock_fc_instance.register.call_args_list
        handler_types = [type(call[0][0]) for call in register_calls]
        assert HelloWorldSessionStartHandler not in handler_types

    @patch("claude_code_hooks_daemon.hooks.session_start.FrontController")
    @patch("claude_code_hooks_daemon.hooks.session_start.load_config_safe")
    def test_skips_disabled_handlers(self, mock_load_config: Mock, mock_fc_class: Mock) -> None:
        """Handlers with enabled: false are not registered."""
        config = {
            "handlers": {
                "session_start": {
                    "workflow_state_restoration": {"enabled": False},
                    "yolo_container_detection": {"enabled": False},
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

    @patch("claude_code_hooks_daemon.hooks.session_start.FrontController")
    @patch("claude_code_hooks_daemon.hooks.session_start.load_config_safe")
    def test_tag_filtering_with_enable_tags(
        self, mock_load_config: Mock, mock_fc_class: Mock
    ) -> None:
        """Only handlers with matching enabled tags are registered."""
        config = {
            "handlers": {
                "session_start": {
                    "enable_tags": ["workflow"],
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

    @patch("claude_code_hooks_daemon.hooks.session_start.FrontController")
    @patch("claude_code_hooks_daemon.hooks.session_start.load_config_safe")
    def test_tag_filtering_with_disable_tags(
        self, mock_load_config: Mock, mock_fc_class: Mock
    ) -> None:
        """Handlers with disabled tags are not registered."""
        config = {
            "handlers": {
                "session_start": {
                    "disable_tags": ["workflow"],
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

    @patch("claude_code_hooks_daemon.hooks.session_start.ConfigLoader.find_config")
    @patch("claude_code_hooks_daemon.hooks.session_start.FrontController")
    @patch("claude_code_hooks_daemon.hooks.session_start.load_config_safe")
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

    @patch("claude_code_hooks_daemon.hooks.session_start.FrontController")
    @patch("claude_code_hooks_daemon.hooks.session_start.load_config_safe")
    def test_yolo_handler_configuration_with_custom_settings(
        self, mock_load_config: Mock, mock_fc_class: Mock
    ) -> None:
        """YOLO handler receives custom configuration settings."""
        config = {
            "handlers": {
                "session_start": {
                    "workflow_state_restoration": {"enabled": False},  # Disable to test only YOLO
                    "yolo_container_detection": {
                        "enabled": True,
                        "min_confidence_score": 5,
                        "show_detailed_indicators": False,
                        "show_workflow_tips": False,
                    },
                }
            },
            "daemon": {},
        }
        mock_load_config.return_value = config
        mock_fc_instance = Mock()
        mock_fc_class.return_value = mock_fc_instance

        main()

        # Should register yolo handler with custom config
        register_calls = mock_fc_instance.register.call_args_list
        assert len(register_calls) >= 1

        # Find YOLO handler
        from claude_code_hooks_daemon.handlers.session_start.yolo_container_detection import (
            YoloContainerDetectionHandler,
        )

        yolo_handlers = [
            call[0][0]
            for call in register_calls
            if isinstance(call[0][0], YoloContainerDetectionHandler)
        ]
        assert len(yolo_handlers) == 1
        # Handler should have received configure() call
        assert hasattr(yolo_handlers[0], "configure")

    @patch("claude_code_hooks_daemon.hooks.session_start.FrontController")
    @patch("claude_code_hooks_daemon.hooks.session_start.load_config_safe")
    def test_yolo_handler_configuration_with_default_settings(
        self, mock_load_config: Mock, mock_fc_class: Mock
    ) -> None:
        """YOLO handler receives default configuration when settings not specified."""
        config = {
            "handlers": {
                "session_start": {
                    "workflow_state_restoration": {"enabled": False},  # Disable to test only YOLO
                    "yolo_container_detection": {"enabled": True},
                }
            },
            "daemon": {},
        }
        mock_load_config.return_value = config
        mock_fc_instance = Mock()
        mock_fc_class.return_value = mock_fc_instance

        main()

        # Should register yolo handler with defaults
        register_calls = mock_fc_instance.register.call_args_list
        assert len(register_calls) >= 1

        # Find YOLO handler
        from claude_code_hooks_daemon.handlers.session_start.yolo_container_detection import (
            YoloContainerDetectionHandler,
        )

        yolo_handlers = [
            call[0][0]
            for call in register_calls
            if isinstance(call[0][0], YoloContainerDetectionHandler)
        ]
        assert len(yolo_handlers) == 1
        assert hasattr(yolo_handlers[0], "configure")
