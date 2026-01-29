"""Tests for SubagentStop hook entry point."""

from pathlib import Path
from unittest.mock import Mock, patch

from claude_code_hooks_daemon.hooks.subagent_stop import (
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
        assert (
            len(handlers) == 3
        )  # remind_validator, remind_prompt_library, subagent_completion_logger

    def test_contains_all_expected_handlers(self) -> None:
        """All expected handler names are present."""
        handlers = get_builtin_handlers()

        expected = [
            "remind_validator",
            "remind_prompt_library",
            "subagent_completion_logger",
        ]

        for handler_name in expected:
            assert handler_name in handlers

    def test_handler_classes_are_importable(self) -> None:
        """Handler classes can be instantiated."""
        handlers = get_builtin_handlers()

        from claude_code_hooks_daemon.handlers.subagent_stop.remind_prompt_library import (
            RemindPromptLibraryHandler,
        )
        from claude_code_hooks_daemon.handlers.subagent_stop.remind_validator import (
            RemindValidatorHandler,
        )
        from claude_code_hooks_daemon.handlers.subagent_stop.subagent_completion_logger import (
            SubagentCompletionLoggerHandler,
        )

        assert handlers["remind_validator"] == RemindValidatorHandler
        assert handlers["remind_prompt_library"] == RemindPromptLibraryHandler
        assert handlers["subagent_completion_logger"] == SubagentCompletionLoggerHandler


class TestLoadConfigSafe:
    """Test safe configuration loading with fallback."""

    def test_loads_config_when_file_exists(self, tmp_path: Path) -> None:
        """Config loaded successfully when file exists."""
        config_file = tmp_path / "hooks-daemon.yaml"
        config_file.write_text(
            "version: '1.0'\nhandlers:\n  subagent_stop:\n    remind_validator:\n      enabled: true\n"
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

    @patch("claude_code_hooks_daemon.hooks.subagent_stop.FrontController")
    @patch("claude_code_hooks_daemon.hooks.subagent_stop.load_config_safe")
    def test_creates_front_controller_with_correct_event(
        self, mock_load_config: Mock, mock_fc_class: Mock
    ) -> None:
        """FrontController created with SubagentStop event name."""
        mock_load_config.return_value = {"handlers": {}, "daemon": {}}
        mock_fc_instance = Mock()
        mock_fc_class.return_value = mock_fc_instance

        main()

        mock_fc_class.assert_called_once_with(event_name="SubagentStop")
        mock_fc_instance.run.assert_called_once()

    @patch("claude_code_hooks_daemon.hooks.subagent_stop.FrontController")
    @patch("claude_code_hooks_daemon.hooks.subagent_stop.load_config_safe")
    def test_registers_enabled_builtin_handlers(
        self, mock_load_config: Mock, mock_fc_class: Mock
    ) -> None:
        """Enabled built-in handlers are registered."""
        config = {
            "handlers": {
                "subagent_stop": {
                    "remind_validator": {"enabled": True, "priority": 50},
                    "remind_prompt_library": {"enabled": False},
                }
            },
            "daemon": {},
        }
        mock_load_config.return_value = config
        mock_fc_instance = Mock()
        mock_fc_class.return_value = mock_fc_instance

        main()

        # Should register remind_validator and subagent_completion_logger (defaults to enabled)
        # but not remind_prompt_library (disabled)
        register_calls = mock_fc_instance.register.call_args_list
        assert len(register_calls) >= 1

        registered_handler = register_calls[0][0][0]
        assert hasattr(registered_handler, "priority")

    @patch("claude_code_hooks_daemon.hooks.subagent_stop.FrontController")
    @patch("claude_code_hooks_daemon.hooks.subagent_stop.load_config_safe")
    def test_handlers_default_to_enabled_if_not_specified(
        self, mock_load_config: Mock, mock_fc_class: Mock
    ) -> None:
        """Handlers enabled by default if not explicitly disabled."""
        config = {
            "handlers": {
                "subagent_stop": {
                    "remind_validator": {},  # No 'enabled' key
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

    @patch("claude_code_hooks_daemon.hooks.subagent_stop.FrontController")
    @patch("claude_code_hooks_daemon.hooks.subagent_stop.load_config_safe")
    def test_applies_custom_priority_from_config(
        self, mock_load_config: Mock, mock_fc_class: Mock
    ) -> None:
        """Custom priority from config overrides handler default."""
        config = {
            "handlers": {
                "subagent_stop": {
                    "remind_validator": {"enabled": True, "priority": 99},
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

    @patch("claude_code_hooks_daemon.hooks.subagent_stop.FrontController")
    @patch("claude_code_hooks_daemon.hooks.subagent_stop.load_config_safe")
    def test_hello_world_handler_registered_when_enabled(
        self, mock_load_config: Mock, mock_fc_class: Mock
    ) -> None:
        """Hello world handler registered when enable_hello_world_handlers is True."""
        config = {
            "handlers": {"subagent_stop": {}},
            "daemon": {"enable_hello_world_handlers": True},
        }
        mock_load_config.return_value = config
        mock_fc_instance = Mock()
        mock_fc_class.return_value = mock_fc_instance

        main()

        from claude_code_hooks_daemon.handlers.subagent_stop.hello_world import (
            HelloWorldSubagentStopHandler,
        )

        register_calls = mock_fc_instance.register.call_args_list
        handler_types = [type(call[0][0]) for call in register_calls]
        assert HelloWorldSubagentStopHandler in handler_types

    @patch("claude_code_hooks_daemon.hooks.subagent_stop.FrontController")
    @patch("claude_code_hooks_daemon.hooks.subagent_stop.load_config_safe")
    def test_multiple_handlers_registered(
        self, mock_load_config: Mock, mock_fc_class: Mock
    ) -> None:
        """Multiple enabled handlers are all registered."""
        config = {
            "handlers": {
                "subagent_stop": {
                    "remind_validator": {"enabled": True, "priority": 10},
                    "remind_prompt_library": {"enabled": True, "priority": 20},
                    "subagent_completion_logger": {"enabled": True, "priority": 30},
                }
            },
            "daemon": {},
        }
        mock_load_config.return_value = config
        mock_fc_instance = Mock()
        mock_fc_class.return_value = mock_fc_instance

        main()

        register_calls = mock_fc_instance.register.call_args_list
        assert len(register_calls) == 3

        registered_handlers = [call[0][0] for call in register_calls]
        priorities = {type(h).__name__: h.priority for h in registered_handlers}

        assert priorities["RemindValidatorHandler"] == 10
        assert priorities["RemindPromptLibraryHandler"] == 20
        assert priorities["SubagentCompletionLoggerHandler"] == 30

    @patch("claude_code_hooks_daemon.hooks.subagent_stop.FrontController")
    @patch("claude_code_hooks_daemon.hooks.subagent_stop.load_config_safe")
    def test_runs_controller_dispatcher(self, mock_load_config: Mock, mock_fc_class: Mock) -> None:
        """FrontController.run() is called to process hook input."""
        mock_load_config.return_value = {"handlers": {}, "daemon": {}}
        mock_fc_instance = Mock()
        mock_fc_class.return_value = mock_fc_instance

        main()

        mock_fc_instance.run.assert_called_once()

    @patch("claude_code_hooks_daemon.hooks.subagent_stop.FrontController")
    @patch("claude_code_hooks_daemon.hooks.subagent_stop.load_config_safe")
    def test_skips_disabled_handlers(self, mock_load_config: Mock, mock_fc_class: Mock) -> None:
        """Handlers with enabled: false are not registered."""
        config = {
            "handlers": {
                "subagent_stop": {
                    "remind_validator": {"enabled": False},
                    "remind_prompt_library": {"enabled": False},
                    "subagent_completion_logger": {"enabled": False},
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

    @patch("claude_code_hooks_daemon.hooks.subagent_stop.ConfigLoader")
    @patch("claude_code_hooks_daemon.hooks.subagent_stop.FrontController")
    @patch("claude_code_hooks_daemon.hooks.subagent_stop.load_config_safe")
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

    @patch("claude_code_hooks_daemon.hooks.subagent_stop.FrontController")
    @patch("claude_code_hooks_daemon.hooks.subagent_stop.load_config_safe")
    def test_enable_tags_filters_handlers(
        self, mock_load_config: Mock, mock_fc_class: Mock
    ) -> None:
        """Handlers filtered by enable_tags."""
        config = {
            "handlers": {
                "subagent_stop": {
                    "enable_tags": ["workflow"],
                    "remind_validator": {"enabled": True},
                    "subagent_completion_logger": {"enabled": True},
                }
            },
            "daemon": {},
        }
        mock_load_config.return_value = config
        mock_fc_instance = Mock()
        mock_fc_class.return_value = mock_fc_instance

        main()

        register_calls = mock_fc_instance.register.call_args_list
        if len(register_calls) > 0:
            registered_handler = register_calls[0][0][0]
            assert any(tag in registered_handler.tags for tag in ["workflow"])

    @patch("claude_code_hooks_daemon.hooks.subagent_stop.FrontController")
    @patch("claude_code_hooks_daemon.hooks.subagent_stop.load_config_safe")
    def test_disable_tags_filters_handlers(
        self, mock_load_config: Mock, mock_fc_class: Mock
    ) -> None:
        """Handlers filtered by disable_tags."""
        config = {
            "handlers": {
                "subagent_stop": {
                    "disable_tags": ["workflow"],
                    "remind_validator": {"enabled": True},
                }
            },
            "daemon": {},
        }
        mock_load_config.return_value = config
        mock_fc_instance = Mock()
        mock_fc_class.return_value = mock_fc_instance

        main()

        register_calls = mock_fc_instance.register.call_args_list
        # remind_validator has 'workflow' tag so should be filtered out
        assert len(register_calls) == 0
