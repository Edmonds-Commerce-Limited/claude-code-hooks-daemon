"""Tests for PreCompact hook entry point."""

from pathlib import Path
from unittest.mock import Mock, patch

from claude_code_hooks_daemon.hooks.pre_compact import (
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
        assert len(handlers) == 2  # transcript_archiver and workflow_state_pre_compact

    def test_contains_all_expected_handlers(self) -> None:
        """All expected handler names are present."""
        handlers = get_builtin_handlers()

        expected = [
            "transcript_archiver",
            "workflow_state_pre_compact",
        ]

        for handler_name in expected:
            assert handler_name in handlers

    def test_handler_classes_are_importable(self) -> None:
        """Handler classes can be instantiated."""
        handlers = get_builtin_handlers()

        from claude_code_hooks_daemon.handlers.pre_compact.transcript_archiver import (
            TranscriptArchiverHandler,
        )
        from claude_code_hooks_daemon.handlers.pre_compact.workflow_state_pre_compact import (
            WorkflowStatePreCompactHandler,
        )

        assert handlers["transcript_archiver"] == TranscriptArchiverHandler
        assert handlers["workflow_state_pre_compact"] == WorkflowStatePreCompactHandler


class TestLoadConfigSafe:
    """Test safe configuration loading with fallback."""

    def test_loads_config_when_file_exists(self, tmp_path: Path) -> None:
        """Config loaded successfully when file exists."""
        config_file = tmp_path / "hooks-daemon.yaml"
        config_file.write_text(
            "version: '1.0'\nhandlers:\n  pre_compact:\n    transcript_archiver:\n      enabled: true\n"
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

    @patch("claude_code_hooks_daemon.hooks.pre_compact.FrontController")
    @patch("claude_code_hooks_daemon.hooks.pre_compact.load_config_safe")
    def test_creates_front_controller_with_correct_event(
        self, mock_load_config: Mock, mock_fc_class: Mock
    ) -> None:
        """FrontController created with PreCompact event name."""
        mock_load_config.return_value = {"handlers": {}, "daemon": {}}
        mock_fc_instance = Mock()
        mock_fc_class.return_value = mock_fc_instance

        main()

        mock_fc_class.assert_called_once_with(event_name="PreCompact")
        mock_fc_instance.run.assert_called_once()

    @patch("claude_code_hooks_daemon.hooks.pre_compact.FrontController")
    @patch("claude_code_hooks_daemon.hooks.pre_compact.load_config_safe")
    def test_registers_enabled_builtin_handlers(
        self, mock_load_config: Mock, mock_fc_class: Mock
    ) -> None:
        """Enabled built-in handlers are registered."""
        config = {
            "handlers": {
                "pre_compact": {
                    "transcript_archiver": {"enabled": True, "priority": 50},
                    "workflow_state_pre_compact": {"enabled": False},
                }
            },
            "daemon": {},
        }
        mock_load_config.return_value = config
        mock_fc_instance = Mock()
        mock_fc_class.return_value = mock_fc_instance

        main()

        # Should register transcript_archiver but not workflow_state_pre_compact
        register_calls = mock_fc_instance.register.call_args_list
        assert len(register_calls) >= 1

        registered_handler = register_calls[0][0][0]
        assert hasattr(registered_handler, "priority")

    @patch("claude_code_hooks_daemon.hooks.pre_compact.FrontController")
    @patch("claude_code_hooks_daemon.hooks.pre_compact.load_config_safe")
    def test_handlers_default_to_enabled_if_not_specified(
        self, mock_load_config: Mock, mock_fc_class: Mock
    ) -> None:
        """Handlers enabled by default if not explicitly disabled."""
        config = {
            "handlers": {
                "pre_compact": {
                    "transcript_archiver": {},  # No 'enabled' key
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

    @patch("claude_code_hooks_daemon.hooks.pre_compact.FrontController")
    @patch("claude_code_hooks_daemon.hooks.pre_compact.load_config_safe")
    def test_applies_custom_priority_from_config(
        self, mock_load_config: Mock, mock_fc_class: Mock
    ) -> None:
        """Custom priority from config overrides handler default."""
        config = {
            "handlers": {
                "pre_compact": {
                    "transcript_archiver": {"enabled": True, "priority": 99},
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

    @patch("claude_code_hooks_daemon.hooks.pre_compact.FrontController")
    @patch("claude_code_hooks_daemon.hooks.pre_compact.load_config_safe")
    def test_hello_world_handler_registered_when_enabled(
        self, mock_load_config: Mock, mock_fc_class: Mock
    ) -> None:
        """Hello world handler registered when enable_hello_world_handlers is True."""
        config = {
            "handlers": {"pre_compact": {}},
            "daemon": {"enable_hello_world_handlers": True},
        }
        mock_load_config.return_value = config
        mock_fc_instance = Mock()
        mock_fc_class.return_value = mock_fc_instance

        main()

        from claude_code_hooks_daemon.handlers.pre_compact.hello_world import (
            HelloWorldPreCompactHandler,
        )

        register_calls = mock_fc_instance.register.call_args_list
        handler_types = [type(call[0][0]) for call in register_calls]
        assert HelloWorldPreCompactHandler in handler_types

    @patch("claude_code_hooks_daemon.hooks.pre_compact.FrontController")
    @patch("claude_code_hooks_daemon.hooks.pre_compact.load_config_safe")
    def test_multiple_handlers_registered(
        self, mock_load_config: Mock, mock_fc_class: Mock
    ) -> None:
        """Multiple enabled handlers are all registered."""
        config = {
            "handlers": {
                "pre_compact": {
                    "transcript_archiver": {"enabled": True, "priority": 10},
                    "workflow_state_pre_compact": {"enabled": True, "priority": 20},
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

        registered_handlers = [call[0][0] for call in register_calls]
        priorities = {type(h).__name__: h.priority for h in registered_handlers}

        assert priorities["TranscriptArchiverHandler"] == 10
        assert priorities["WorkflowStatePreCompactHandler"] == 20

    @patch("claude_code_hooks_daemon.hooks.pre_compact.FrontController")
    @patch("claude_code_hooks_daemon.hooks.pre_compact.load_config_safe")
    def test_runs_controller_dispatcher(self, mock_load_config: Mock, mock_fc_class: Mock) -> None:
        """FrontController.run() is called to process hook input."""
        mock_load_config.return_value = {"handlers": {}, "daemon": {}}
        mock_fc_instance = Mock()
        mock_fc_class.return_value = mock_fc_instance

        main()

        mock_fc_instance.run.assert_called_once()

    @patch("claude_code_hooks_daemon.hooks.pre_compact.FrontController")
    @patch("claude_code_hooks_daemon.hooks.pre_compact.load_config_safe")
    def test_tag_filtering_with_disable_tags(
        self, mock_load_config: Mock, mock_fc_class: Mock
    ) -> None:
        """Handlers with disabled tags are not registered."""
        config = {
            "handlers": {
                "pre_compact": {
                    "disable_tags": ["archiving"],
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
