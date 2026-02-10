"""Comprehensive tests for config.models module.

Tests all Pydantic models, validation, serialization, and configuration loading.
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from pydantic import ValidationError

from claude_code_hooks_daemon.config.models import (
    Config,
    DaemonConfig,
    EventHandlersConfig,
    HandlerConfig,
    HandlersConfig,
    LogLevel,
    PluginConfig,
    PluginsConfig,
)
from claude_code_hooks_daemon.constants import EventID


class TestLogLevel:
    """Tests for LogLevel enum."""

    def test_all_values_are_valid(self) -> None:
        """All LogLevel values are valid strings."""
        assert LogLevel.DEBUG == "DEBUG"
        assert LogLevel.INFO == "INFO"
        assert LogLevel.WARNING == "WARNING"
        assert LogLevel.ERROR == "ERROR"
        assert LogLevel.CRITICAL == "CRITICAL"

    def test_can_iterate_values(self) -> None:
        """Can iterate over all LogLevel values."""
        values = list(LogLevel)
        assert len(values) == 5
        assert LogLevel.DEBUG in values


class TestHandlerConfig:
    """Tests for HandlerConfig model."""

    def test_default_values(self) -> None:
        """HandlerConfig has correct defaults."""
        config = HandlerConfig()
        assert config.enabled is True
        assert config.priority is None
        assert config.options == {}

    def test_can_set_values(self) -> None:
        """Can set all HandlerConfig fields."""
        config = HandlerConfig(
            enabled=False,
            priority=42,
            options={"key": "value"},
        )
        assert config.enabled is False
        assert config.priority == 42
        assert config.options == {"key": "value"}

    def test_extra_fields_forbidden(self) -> None:
        """HandlerConfig FORBIDS extra fields - use options dict instead."""
        with pytest.raises(ValueError, match="Extra inputs are not permitted"):
            HandlerConfig.model_validate(
                {
                    "enabled": True,
                    "priority": 10,
                    "custom_field": "custom_value",  # Should fail - extra field
                }
            )

    def test_model_validate_from_dict(self) -> None:
        """Can validate HandlerConfig from dict."""
        data = {"enabled": False, "priority": 99}
        config = HandlerConfig.model_validate(data)
        assert config.enabled is False
        assert config.priority == 99

    def test_options_default_factory(self) -> None:
        """Options dict is created fresh for each instance."""
        config1 = HandlerConfig()
        config2 = HandlerConfig()
        config1.options["key"] = "value"
        assert "key" not in config2.options


class TestEventHandlersConfig:
    """Tests for EventHandlersConfig model."""

    def test_get_handler_returns_default_for_missing(self) -> None:
        """get_handler returns default HandlerConfig for missing handler."""
        config = EventHandlersConfig()
        handler_config = config.get_handler("nonexistent")
        assert isinstance(handler_config, HandlerConfig)
        assert handler_config.enabled is True
        assert handler_config.priority is None

    def test_get_handler_returns_config_from_dict(self) -> None:
        """get_handler returns HandlerConfig from dict attribute."""
        config = EventHandlersConfig.model_validate(
            {
                "my_handler": {"enabled": False, "priority": 20},
            }
        )
        handler_config = config.get_handler("my_handler")
        assert isinstance(handler_config, HandlerConfig)
        assert handler_config.enabled is False
        assert handler_config.priority == 20

    def test_get_handler_returns_existing_config(self) -> None:
        """get_handler returns existing HandlerConfig instance."""
        handler_config = HandlerConfig(enabled=False, priority=30)
        config = EventHandlersConfig()
        config.test_handler = handler_config

        retrieved = config.get_handler("test_handler")
        assert retrieved is handler_config

    def test_get_handler_handles_none_value(self) -> None:
        """get_handler returns default when attribute is None."""
        config = EventHandlersConfig()
        config.handler = None
        handler_config = config.get_handler("handler")
        assert isinstance(handler_config, HandlerConfig)
        assert handler_config.enabled is True

    def test_get_handler_handles_invalid_type(self) -> None:
        """get_handler returns default for invalid attribute type."""
        config = EventHandlersConfig()
        config.handler = "invalid"
        handler_config = config.get_handler("handler")
        assert isinstance(handler_config, HandlerConfig)

    def test_extra_fields_allowed(self) -> None:
        """EventHandlersConfig allows extra fields."""
        config = EventHandlersConfig.model_validate(
            {
                "handler1": {"enabled": True},
                "handler2": {"priority": 50},
            }
        )
        assert hasattr(config, "handler1")
        assert hasattr(config, "handler2")


class TestHandlersConfig:
    """Tests for HandlersConfig model."""

    def test_default_values(self) -> None:
        """HandlersConfig has empty dicts for all event types."""
        config = HandlersConfig()
        assert config.pre_tool_use == {}
        assert config.post_tool_use == {}
        assert config.session_start == {}
        assert config.session_end == {}
        assert config.pre_compact == {}
        assert config.user_prompt_submit == {}
        assert config.permission_request == {}
        assert config.notification == {}
        assert config.stop == {}
        assert config.subagent_stop == {}

    def test_coerce_handler_configs_preserves_tag_filters(self) -> None:
        """Validator preserves enable_tags and disable_tags."""
        config = HandlersConfig.model_validate(
            {
                "pre_tool_use": {
                    "enable_tags": ["tag1", "tag2"],
                    "disable_tags": ["tag3"],
                    "handler1": {"enabled": True},
                }
            }
        )
        assert config.pre_tool_use["enable_tags"] == ["tag1", "tag2"]
        assert config.pre_tool_use["disable_tags"] == ["tag3"]
        assert isinstance(config.pre_tool_use["handler1"], HandlerConfig)

    def test_coerce_handler_configs_converts_dicts(self) -> None:
        """Validator converts dict configs to HandlerConfig."""
        config = HandlersConfig.model_validate(
            {
                "post_tool_use": {
                    "my_handler": {"enabled": False, "priority": 10},
                }
            }
        )
        handler_config = config.post_tool_use["my_handler"]
        assert isinstance(handler_config, HandlerConfig)
        assert handler_config.enabled is False
        assert handler_config.priority == 10

    def test_coerce_handler_configs_handles_none(self) -> None:
        """Validator handles None values."""
        config = HandlersConfig.model_validate({"pre_tool_use": None})
        assert config.pre_tool_use == {}

    def test_coerce_handler_configs_preserves_handler_config(self) -> None:
        """Validator preserves existing HandlerConfig instances."""
        handler_config = HandlerConfig(enabled=False)
        config = HandlersConfig.model_validate(
            {
                "session_start": {
                    "handler1": handler_config,
                }
            }
        )
        assert config.session_start["handler1"] is handler_config

    def test_coerce_handler_configs_handles_non_dict_non_handler_config(self) -> None:
        """Validator creates default HandlerConfig for non-dict, non-HandlerConfig values."""
        # This tests line 114 in models.py - the else branch
        config = HandlersConfig.model_validate(
            {
                "pre_tool_use": {
                    "handler_with_string": "enabled",  # Not a dict or HandlerConfig
                }
            }
        )
        handler_config = config.pre_tool_use["handler_with_string"]
        assert isinstance(handler_config, HandlerConfig)
        assert handler_config.enabled is True  # Default value
        assert handler_config.priority is None  # Default value

    def test_get_enable_tags_returns_list(self) -> None:
        """get_enable_tags returns list when specified."""
        config = HandlersConfig.model_validate(
            {
                "pre_tool_use": {
                    "enable_tags": ["qa", "safety"],
                }
            }
        )
        tags = config.get_enable_tags("pre_tool_use")
        assert tags == ["qa", "safety"]

    def test_get_enable_tags_returns_none_when_missing(self) -> None:
        """get_enable_tags returns None when not specified."""
        config = HandlersConfig()
        tags = config.get_enable_tags("pre_tool_use")
        assert tags is None

    def test_get_enable_tags_handles_invalid_event_type(self) -> None:
        """get_enable_tags handles invalid event type."""
        config = HandlersConfig()
        tags = config.get_enable_tags("invalid_event")
        assert tags is None

    def test_get_disable_tags_returns_list(self) -> None:
        """get_disable_tags returns list when specified."""
        config = HandlersConfig.model_validate(
            {
                "post_tool_use": {
                    "disable_tags": ["test", "debug"],
                }
            }
        )
        tags = config.get_disable_tags("post_tool_use")
        assert tags == ["test", "debug"]

    def test_get_disable_tags_returns_empty_list_when_missing(self) -> None:
        """get_disable_tags returns empty list when not specified."""
        config = HandlersConfig()
        tags = config.get_disable_tags("pre_tool_use")
        assert tags == []

    def test_get_disable_tags_handles_invalid_event_type(self) -> None:
        """get_disable_tags handles invalid event type."""
        config = HandlersConfig()
        tags = config.get_disable_tags("invalid_event")
        assert tags == []

    def test_get_handler_config_returns_config(self) -> None:
        """get_handler_config returns handler configuration."""
        config = HandlersConfig.model_validate(
            {
                "pre_tool_use": {
                    "my_handler": {"enabled": False, "priority": 25},
                }
            }
        )
        handler_config = config.get_handler_config("pre_tool_use", "my_handler")
        assert isinstance(handler_config, HandlerConfig)
        assert handler_config.enabled is False
        assert handler_config.priority == 25

    def test_get_handler_config_returns_default_for_missing(self) -> None:
        """get_handler_config returns default for missing handler."""
        config = HandlersConfig()
        handler_config = config.get_handler_config("pre_tool_use", "missing")
        assert isinstance(handler_config, HandlerConfig)
        assert handler_config.enabled is True

    def test_get_handler_config_ignores_tag_filter_keys(self) -> None:
        """get_handler_config returns default for tag filter keys."""
        config = HandlersConfig.model_validate(
            {
                "pre_tool_use": {
                    "enable_tags": ["qa"],
                    "disable_tags": ["test"],
                }
            }
        )
        enable_config = config.get_handler_config("pre_tool_use", "enable_tags")
        disable_config = config.get_handler_config("pre_tool_use", "disable_tags")
        assert isinstance(enable_config, HandlerConfig)
        assert isinstance(disable_config, HandlerConfig)

    def test_get_handler_config_converts_dict(self) -> None:
        """get_handler_config converts dict to HandlerConfig."""
        config = HandlersConfig()
        config.pre_tool_use = {"handler": {"enabled": False}}
        handler_config = config.get_handler_config("pre_tool_use", "handler")
        assert isinstance(handler_config, HandlerConfig)
        assert handler_config.enabled is False

    def test_get_handler_config_returns_existing_instance(self) -> None:
        """get_handler_config returns existing HandlerConfig instance."""
        existing = HandlerConfig(priority=99)
        config = HandlersConfig()
        config.pre_tool_use = {"handler": existing}
        handler_config = config.get_handler_config("pre_tool_use", "handler")
        assert handler_config is existing

    def test_get_handler_config_handles_invalid_type(self) -> None:
        """get_handler_config returns default for invalid handler_config type."""
        config = HandlersConfig()
        config.pre_tool_use = {"handler": "invalid_string"}
        handler_config = config.get_handler_config("pre_tool_use", "handler")
        assert isinstance(handler_config, HandlerConfig)
        assert handler_config.enabled is True
        assert handler_config.priority is None


class TestPluginConfig:
    """Tests for PluginConfig model."""

    def test_required_fields(self) -> None:
        """PluginConfig requires path and event_type fields."""
        # Missing both path and event_type
        with pytest.raises(ValidationError):
            PluginConfig.model_validate({})

        # Missing event_type
        with pytest.raises(ValidationError):
            PluginConfig.model_validate({"path": "/path/to/plugin"})

        # Missing path
        with pytest.raises(ValidationError):
            PluginConfig.model_validate({"event_type": "pre_tool_use"})

    def test_default_values(self) -> None:
        """PluginConfig has correct defaults for optional fields."""
        config = PluginConfig(path="/path/to/plugin", event_type=EventID.PRE_TOOL_USE.config_key)
        assert config.path == "/path/to/plugin"
        assert config.event_type == EventID.PRE_TOOL_USE.config_key
        assert config.handlers is None
        assert config.enabled is True

    def test_can_set_all_fields(self) -> None:
        """Can set all PluginConfig fields."""
        config = PluginConfig(
            path="/custom/path",
            event_type=EventID.POST_TOOL_USE.config_key,
            handlers=["Handler1", "Handler2"],
            enabled=False,
        )
        assert config.path == "/custom/path"
        assert config.event_type == EventID.POST_TOOL_USE.config_key
        assert config.handlers == ["Handler1", "Handler2"]
        assert config.enabled is False

    def test_event_type_valid_values(self) -> None:
        """event_type accepts all valid event type values."""
        valid_event_types = [
            "pre_tool_use",
            "post_tool_use",
            "session_start",
            "session_end",
            "pre_compact",
            "user_prompt_submit",
            "permission_request",
            "notification",
            "stop",
            "subagent_stop",
            "status_line",
        ]

        for event_type in valid_event_types:
            config = PluginConfig(path="/path", event_type=event_type)
            assert config.event_type == event_type

    def test_event_type_invalid_values_rejected(self) -> None:
        """event_type rejects invalid values."""
        invalid_event_types = [
            "invalid_event",
            "PreToolUse",  # PascalCase not allowed (config uses snake_case)
            "pre-tool-use",  # kebab-case not allowed
            "",
            "PRE_TOOL_USE",  # SCREAMING_SNAKE_CASE not allowed
            "random",
        ]

        for event_type in invalid_event_types:
            with pytest.raises(ValidationError, match="event_type"):
                PluginConfig(path="/path", event_type=event_type)

    def test_extra_fields_allowed(self) -> None:
        """PluginConfig allows extra fields."""
        config = PluginConfig.model_validate(
            {
                "path": "/path",
                "event_type": EventID.PRE_TOOL_USE.config_key,
                "custom_field": "value",
            }
        )
        assert config.path == "/path"
        assert config.event_type == EventID.PRE_TOOL_USE.config_key


class TestPluginsConfig:
    """Tests for PluginsConfig model."""

    def test_default_values(self) -> None:
        """PluginsConfig has correct defaults."""
        config = PluginsConfig()
        assert config.paths == []
        assert config.plugins == []

    def test_can_set_paths(self) -> None:
        """Can set plugin search paths."""
        config = PluginsConfig(paths=["/path1", "/path2"])
        assert config.paths == ["/path1", "/path2"]

    def test_can_set_plugins(self) -> None:
        """Can set plugin configurations."""
        config = PluginsConfig(
            plugins=[
                PluginConfig(path="/plugin1", event_type=EventID.PRE_TOOL_USE.config_key),
                PluginConfig(
                    path="/plugin2", event_type=EventID.POST_TOOL_USE.config_key, enabled=False
                ),
            ]
        )
        assert len(config.plugins) == 2
        assert config.plugins[0].path == "/plugin1"
        assert config.plugins[0].event_type == EventID.PRE_TOOL_USE.config_key
        assert config.plugins[1].enabled is False
        assert config.plugins[1].event_type == EventID.POST_TOOL_USE.config_key

    def test_validates_plugin_list(self) -> None:
        """Validates plugin list items."""
        config = PluginsConfig.model_validate(
            {
                "plugins": [
                    {"path": "/plugin1", "event_type": EventID.PRE_TOOL_USE.config_key},
                    {
                        "path": "/plugin2",
                        "event_type": EventID.SESSION_START.config_key,
                        "handlers": ["Handler1"],
                    },
                ]
            }
        )
        assert len(config.plugins) == 2
        assert isinstance(config.plugins[0], PluginConfig)
        assert config.plugins[0].event_type == EventID.PRE_TOOL_USE.config_key
        assert config.plugins[1].handlers == ["Handler1"]
        assert config.plugins[1].event_type == EventID.SESSION_START.config_key


class TestDaemonConfig:
    """Tests for DaemonConfig model."""

    def test_default_values(self) -> None:
        """DaemonConfig has correct defaults."""
        config = DaemonConfig()
        assert config.idle_timeout_seconds == 600
        assert config.log_level == LogLevel.INFO
        assert config.socket_path is None
        assert config.pid_file_path is None
        assert config.log_buffer_size == 1000
        assert config.request_timeout_seconds == 30
        assert config.self_install_mode is False
        assert config.enable_hello_world_handlers is False

    def test_can_set_all_fields(self) -> None:
        """Can set all DaemonConfig fields."""
        config = DaemonConfig(
            idle_timeout_seconds=300,
            log_level=LogLevel.DEBUG,
            socket_path="/custom/socket.sock",
            pid_file_path="/custom/pid.file",
            log_buffer_size=500,
            request_timeout_seconds=60,
            self_install_mode=True,
            enable_hello_world_handlers=True,
        )
        assert config.idle_timeout_seconds == 300
        assert config.log_level == LogLevel.DEBUG
        assert config.socket_path == "/custom/socket.sock"
        assert config.pid_file_path == "/custom/pid.file"
        assert config.log_buffer_size == 500
        assert config.request_timeout_seconds == 60
        assert config.self_install_mode is True
        assert config.enable_hello_world_handlers is True

    def test_idle_timeout_must_be_positive(self) -> None:
        """idle_timeout_seconds must be >= 1."""
        with pytest.raises(ValidationError):
            DaemonConfig(idle_timeout_seconds=0)
        with pytest.raises(ValidationError):
            DaemonConfig(idle_timeout_seconds=-1)

    def test_log_buffer_size_constraints(self) -> None:
        """log_buffer_size must be between 100 and 100000."""
        with pytest.raises(ValidationError):
            DaemonConfig(log_buffer_size=99)
        with pytest.raises(ValidationError):
            DaemonConfig(log_buffer_size=100001)

        config = DaemonConfig(log_buffer_size=100)
        assert config.log_buffer_size == 100
        config = DaemonConfig(log_buffer_size=100000)
        assert config.log_buffer_size == 100000

    def test_request_timeout_constraints(self) -> None:
        """request_timeout_seconds must be between 1 and 300."""
        with pytest.raises(ValidationError):
            DaemonConfig(request_timeout_seconds=0)
        with pytest.raises(ValidationError):
            DaemonConfig(request_timeout_seconds=301)

        config = DaemonConfig(request_timeout_seconds=1)
        assert config.request_timeout_seconds == 1
        config = DaemonConfig(request_timeout_seconds=300)
        assert config.request_timeout_seconds == 300

    def test_get_socket_path_returns_custom(self) -> None:
        """get_socket_path returns custom path when set."""
        config = DaemonConfig(socket_path="/custom/socket.sock")
        result = config.get_socket_path(Path("/workspace"))
        assert result == Path("/custom/socket.sock")

    @patch.object(Path, "mkdir")
    def test_get_socket_path_generates_default(self, _mock_mkdir) -> None:
        """get_socket_path generates default path when not set."""
        config = DaemonConfig()
        workspace = Path("/test/workspace")
        result = config.get_socket_path(workspace)
        assert isinstance(result, Path)
        assert str(result).endswith(".sock")

    def test_get_pid_file_path_returns_custom(self) -> None:
        """get_pid_file_path returns custom path when set."""
        config = DaemonConfig(pid_file_path="/custom/daemon.pid")
        result = config.get_pid_file_path(Path("/workspace"))
        assert result == Path("/custom/daemon.pid")

    @patch.object(Path, "mkdir")
    def test_get_pid_file_path_generates_default(self, _mock_mkdir) -> None:
        """get_pid_file_path generates default path when not set."""
        config = DaemonConfig()
        workspace = Path("/test/workspace")
        result = config.get_pid_file_path(workspace)
        assert isinstance(result, Path)
        assert "pid" in str(result).lower()


class TestConfig:
    """Tests for root Config model."""

    def test_default_values(self) -> None:
        """Config has correct defaults."""
        config = Config()
        assert config.version == "2.0"
        assert isinstance(config.daemon, DaemonConfig)
        assert isinstance(config.handlers, HandlersConfig)
        assert isinstance(config.plugins, PluginsConfig)

    def test_version_pattern_validation(self) -> None:
        """version must match X.Y pattern."""
        config = Config(version="1.0")
        assert config.version == "1.0"

        config = Config(version="2.1")
        assert config.version == "2.1"

        with pytest.raises(ValidationError):
            Config(version="1")

        with pytest.raises(ValidationError):
            Config(version="1.0.0")

        with pytest.raises(ValidationError):
            Config(version="invalid")

    def test_migrate_legacy_settings(self) -> None:
        """Migrates legacy settings.logging_level to daemon.log_level."""
        config = Config.model_validate(
            {
                "version": "1.0",
                "settings": {"logging_level": "DEBUG"},
            }
        )
        assert config.daemon.log_level == LogLevel.DEBUG

    def test_settings_excluded_from_export(self) -> None:
        """settings field is excluded from model_dump."""
        config = Config.model_validate(
            {
                "version": "1.0",
                "settings": {"logging_level": "WARNING"},
            }
        )
        dumped = config.model_dump()
        assert "settings" not in dumped

    def test_load_yaml_file(self, tmp_path: Path) -> None:
        """Can load configuration from YAML file."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
version: "2.0"
daemon:
  idle_timeout_seconds: 300
  log_level: DEBUG
handlers:
  pre_tool_use:
    my_handler:
      enabled: false
      priority: 50
""")

        config = Config.load(config_file)
        assert config.version == "2.0"
        assert config.daemon.idle_timeout_seconds == 300
        assert config.daemon.log_level == LogLevel.DEBUG

    def test_load_json_file(self, tmp_path: Path) -> None:
        """Can load configuration from JSON file."""
        config_file = tmp_path / "config.json"
        config_file.write_text(
            json.dumps(
                {
                    "version": "2.0",
                    "daemon": {
                        "idle_timeout_seconds": 450,
                        "log_level": "WARNING",
                    },
                }
            )
        )

        config = Config.load(config_file)
        assert config.version == "2.0"
        assert config.daemon.idle_timeout_seconds == 450
        assert config.daemon.log_level == LogLevel.WARNING

    def test_load_raises_on_missing_file(self, tmp_path: Path) -> None:
        """load raises FileNotFoundError for missing file."""
        missing_file = tmp_path / "missing.yaml"
        with pytest.raises(FileNotFoundError, match="Configuration file not found"):
            Config.load(missing_file)

    def test_load_raises_on_unsupported_format(self, tmp_path: Path) -> None:
        """load raises ValueError for unsupported file format."""
        txt_file = tmp_path / "config.txt"
        txt_file.write_text("version: 2.0")

        with pytest.raises(ValueError, match="Unsupported format"):
            Config.load(txt_file)

    def test_load_or_default_loads_existing_file(self, tmp_path: Path) -> None:
        """load_or_default loads file when it exists."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("version: '2.0'\ndaemon:\n  log_level: ERROR")

        config = Config.load_or_default(config_file)
        assert config.daemon.log_level == LogLevel.ERROR

    def test_load_or_default_returns_defaults_for_missing_file(self, tmp_path: Path) -> None:
        """load_or_default returns defaults when file doesn't exist."""
        missing_file = tmp_path / "missing.yaml"
        config = Config.load_or_default(missing_file)
        assert config.version == "2.0"
        assert config.daemon.idle_timeout_seconds == 600

    def test_load_or_default_returns_defaults_when_path_is_none(self) -> None:
        """load_or_default returns defaults when path is None."""
        config = Config.load_or_default(None)
        assert config.version == "2.0"
        assert isinstance(config.daemon, DaemonConfig)

    def test_find_and_load_finds_config_in_current_dir(self, tmp_path: Path) -> None:
        """find_and_load finds config in current directory."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        config_file = claude_dir / "hooks-daemon.yaml"
        config_file.write_text("version: '2.0'\ndaemon:\n  log_level: CRITICAL")

        config = Config.find_and_load(tmp_path)
        assert config.daemon.log_level == LogLevel.CRITICAL

    def test_find_and_load_searches_parent_directories(self, tmp_path: Path) -> None:
        """find_and_load searches parent directories."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        config_file = claude_dir / "hooks-daemon.yml"
        config_file.write_text("version: '2.0'\ndaemon:\n  idle_timeout_seconds: 123")

        subdir = tmp_path / "sub1" / "sub2"
        subdir.mkdir(parents=True)

        config = Config.find_and_load(subdir)
        assert config.daemon.idle_timeout_seconds == 123

    def test_find_and_load_returns_default_when_not_found(self, tmp_path: Path) -> None:
        """find_and_load returns defaults when no config found."""
        config = Config.find_and_load(tmp_path)
        assert config.version == "2.0"
        assert config.daemon.idle_timeout_seconds == 600

    def test_to_yaml_serializes_config(self) -> None:
        """to_yaml serializes config to YAML string."""
        config = Config(
            version="2.0",
            daemon=DaemonConfig(idle_timeout_seconds=100, log_level=LogLevel.DEBUG),
        )
        yaml_str = config.to_yaml()

        parsed = yaml.safe_load(yaml_str)
        # Note: exclude_unset means only explicitly set fields are included
        assert parsed.get("version") == "2.0"
        assert parsed["daemon"]["idle_timeout_seconds"] == 100
        # LogLevel enum is serialized as string by Pydantic
        assert "log_level" in parsed["daemon"]

    def test_to_yaml_excludes_none_and_unset(self) -> None:
        """to_yaml excludes None and unset values."""
        config = Config()
        yaml_str = config.to_yaml()

        parsed = yaml.safe_load(yaml_str)
        # Empty dict or minimal content when nothing is set
        # (exclude_unset=True means defaults aren't serialized)
        assert parsed is not None or parsed == {}
        assert isinstance(parsed, dict)

    def test_save_yaml_file(self, tmp_path: Path) -> None:
        """save writes YAML file."""
        config = Config(
            version="2.0",
            daemon=DaemonConfig(idle_timeout_seconds=200),
        )

        config_file = tmp_path / "output.yaml"
        config.save(config_file)

        assert config_file.exists()
        loaded = Config.load(config_file)
        assert loaded.daemon.idle_timeout_seconds == 200

    def test_save_json_file(self, tmp_path: Path) -> None:
        """save writes JSON file."""
        config = Config(
            version="2.0",
            daemon=DaemonConfig(log_level=LogLevel.ERROR),
        )

        config_file = tmp_path / "output.json"
        config.save(config_file)

        assert config_file.exists()
        loaded = Config.load(config_file)
        assert loaded.daemon.log_level == LogLevel.ERROR

    def test_save_creates_parent_directories(self, tmp_path: Path) -> None:
        """save creates parent directories if they don't exist."""
        config = Config()
        config_file = tmp_path / "subdir1" / "subdir2" / "config.yaml"

        config.save(config_file)

        assert config_file.exists()
        assert config_file.parent.exists()

    def test_save_raises_on_unsupported_format(self, tmp_path: Path) -> None:
        """save raises ValueError for unsupported format."""
        config = Config()
        txt_file = tmp_path / "config.txt"

        with pytest.raises(ValueError, match="Unsupported format"):
            config.save(txt_file)

    def test_get_handler_config(self) -> None:
        """get_handler_config delegates to handlers."""
        config = Config(
            handlers=HandlersConfig.model_validate(
                {
                    "pre_tool_use": {
                        "test_handler": {"enabled": False, "priority": 99},
                    }
                }
            )
        )

        handler_config = config.get_handler_config("pre_tool_use", "test_handler")
        assert handler_config.enabled is False
        assert handler_config.priority == 99

    def test_complete_config_roundtrip(self, tmp_path: Path) -> None:
        """Complete config can be saved and loaded."""
        original = Config(
            version="2.0",
            daemon=DaemonConfig(
                idle_timeout_seconds=300,
                log_level=LogLevel.DEBUG,
                log_buffer_size=500,
            ),
            handlers=HandlersConfig.model_validate(
                {
                    "pre_tool_use": {
                        "enable_tags": ["qa"],
                        "handler1": {"enabled": False},
                    },
                    "post_tool_use": {
                        "handler2": {"priority": 50},
                    },
                }
            ),
            plugins=PluginsConfig(
                paths=["/path1", "/path2"],
                plugins=[
                    PluginConfig(path="/plugin1", event_type="pre_tool_use", handlers=["Handler1"]),
                ],
            ),
        )

        config_file = tmp_path / "config.yaml"
        original.save(config_file)

        loaded = Config.load(config_file)

        assert loaded.version == original.version
        assert loaded.daemon.idle_timeout_seconds == 300
        assert loaded.daemon.log_level == LogLevel.DEBUG
        assert loaded.plugins.paths == ["/path1", "/path2"]
        assert len(loaded.plugins.plugins) == 1
