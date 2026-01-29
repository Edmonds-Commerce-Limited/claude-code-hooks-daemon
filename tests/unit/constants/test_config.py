"""Tests for configuration key constants.

Tests that all config key constants are properly defined and match
the actual keys used in YAML configuration files.
"""


from claude_code_hooks_daemon.constants.config import ConfigKey


class TestTopLevelConfigKeys:
    """Tests for top-level configuration keys."""

    def test_top_level_keys(self) -> None:
        """Test top-level config structure keys."""
        assert ConfigKey.VERSION == "version"
        assert ConfigKey.DAEMON == "daemon"
        assert ConfigKey.HANDLERS == "handlers"
        assert ConfigKey.PLUGINS == "plugins"


class TestHandlerConfigKeys:
    """Tests for handler-specific configuration keys."""

    def test_handler_basic_keys(self) -> None:
        """Test basic handler config keys."""
        assert ConfigKey.ENABLED == "enabled"
        assert ConfigKey.PRIORITY == "priority"
        assert ConfigKey.OPTIONS == "options"

    def test_handler_tag_keys(self) -> None:
        """Test handler tag filtering keys."""
        assert ConfigKey.ENABLE_TAGS == "enable_tags"
        assert ConfigKey.DISABLE_TAGS == "disable_tags"

    def test_handler_dependency_keys(self) -> None:
        """Test handler dependency keys."""
        assert ConfigKey.SHARES_OPTIONS_WITH == "shares_options_with"
        assert ConfigKey.DEPENDS_ON == "depends_on"


class TestDaemonConfigKeys:
    """Tests for daemon configuration keys."""

    def test_daemon_timeout_keys(self) -> None:
        """Test daemon timeout config keys."""
        assert ConfigKey.IDLE_TIMEOUT_SECONDS == "idle_timeout_seconds"
        assert ConfigKey.REQUEST_TIMEOUT_SECONDS == "request_timeout_seconds"

    def test_daemon_path_keys(self) -> None:
        """Test daemon path config keys."""
        assert ConfigKey.SOCKET_PATH == "socket_path"
        assert ConfigKey.PID_FILE_PATH == "pid_file_path"

    def test_daemon_logging_keys(self) -> None:
        """Test daemon logging config keys."""
        assert ConfigKey.LOG_LEVEL == "log_level"
        assert ConfigKey.LOG_BUFFER_SIZE == "log_buffer_size"

    def test_daemon_mode_keys(self) -> None:
        """Test daemon mode config keys."""
        assert ConfigKey.SELF_INSTALL_MODE == "self_install_mode"
        assert ConfigKey.ENABLE_HELLO_WORLD_HANDLERS == "enable_hello_world_handlers"
        assert ConfigKey.INPUT_VALIDATION == "input_validation"


class TestPluginConfigKeys:
    """Tests for plugin configuration keys."""

    def test_plugin_keys(self) -> None:
        """Test plugin config keys."""
        assert ConfigKey.PLUGIN_DIRS == "plugin_dirs"
        assert ConfigKey.AUTO_LOAD == "auto_load"


class TestCommonOptionKeys:
    """Tests for common handler option keys."""

    def test_common_option_keys(self) -> None:
        """Test common option keys used across handlers."""
        assert ConfigKey.STRICT_MODE == "strict_mode"
        assert ConfigKey.DRY_RUN == "dry_run"
        assert ConfigKey.VERBOSE == "verbose"
        assert ConfigKey.THRESHOLD == "threshold"
        assert ConfigKey.PATTERN == "pattern"
        assert ConfigKey.EXCLUDE == "exclude"
        assert ConfigKey.INCLUDE == "include"


class TestConfigKeyNaming:
    """Tests for config key naming conventions."""

    def test_all_keys_use_snake_case(self) -> None:
        """Test that all config keys use snake_case format."""
        for key, value in vars(ConfigKey).items():
            if not key.startswith("_") and isinstance(value, str):
                # Should be lowercase with underscores
                assert value.islower() or "_" in value, f"{key}={value} not snake_case"
                assert " " not in value, f"{key}={value} contains spaces"
                assert "-" not in value, f"{key}={value} uses hyphens (should be underscores)"

    def test_no_duplicate_values(self) -> None:
        """Test that there are no duplicate config key values."""
        key_values = [
            value
            for key, value in vars(ConfigKey).items()
            if not key.startswith("_") and isinstance(value, str)
        ]
        duplicates = [v for v in key_values if key_values.count(v) > 1]
        assert len(duplicates) == 0, f"Duplicate config keys: {duplicates}"

    def test_all_keys_are_strings(self) -> None:
        """Test that all config key constants are strings."""
        for key, value in vars(ConfigKey).items():
            if not key.startswith("_"):
                assert isinstance(value, str), f"{key} should be a string"


class TestConfigKeyUsagePatterns:
    """Tests for config key usage patterns."""

    def test_top_level_access_pattern(self) -> None:
        """Test common pattern for top-level config access."""
        config = {
            ConfigKey.VERSION: "1.0",
            ConfigKey.DAEMON: {},
            ConfigKey.HANDLERS: {},
        }
        assert ConfigKey.VERSION in config
        assert config[ConfigKey.VERSION] == "1.0"

    def test_handler_config_access_pattern(self) -> None:
        """Test common pattern for handler config access."""
        handler_config = {
            ConfigKey.ENABLED: True,
            ConfigKey.PRIORITY: 50,
            ConfigKey.OPTIONS: {},
        }
        assert handler_config[ConfigKey.ENABLED] is True
        assert handler_config[ConfigKey.PRIORITY] == 50

    def test_daemon_config_access_pattern(self) -> None:
        """Test common pattern for daemon config access."""
        daemon_config = {
            ConfigKey.IDLE_TIMEOUT_SECONDS: 600,
            ConfigKey.LOG_LEVEL: "INFO",
        }
        assert daemon_config[ConfigKey.IDLE_TIMEOUT_SECONDS] == 600
        assert daemon_config[ConfigKey.LOG_LEVEL] == "INFO"

    def test_options_dict_access_pattern(self) -> None:
        """Test common pattern for handler options access."""
        options = {
            ConfigKey.STRICT_MODE: True,
            ConfigKey.PATTERN: r"\.py$",
        }
        assert options.get(ConfigKey.STRICT_MODE) is True
        assert options.get(ConfigKey.PATTERN) == r"\.py$"


class TestCriticalConfigKeys:
    """Tests for critical configuration keys."""

    def test_required_handler_keys(self) -> None:
        """Test keys that are required for handler config."""
        # These are the most commonly used handler config keys
        assert ConfigKey.ENABLED == "enabled"
        assert ConfigKey.PRIORITY == "priority"
        assert ConfigKey.OPTIONS == "options"

    def test_required_daemon_keys(self) -> None:
        """Test keys that are required for daemon config."""
        # These are critical daemon config keys
        assert ConfigKey.IDLE_TIMEOUT_SECONDS == "idle_timeout_seconds"
        assert ConfigKey.LOG_LEVEL == "log_level"


class TestConfigKeyExport:
    """Tests for module exports."""

    def test_all_exports(self) -> None:
        """Test that __all__ contains expected exports."""
        from claude_code_hooks_daemon.constants import config

        assert hasattr(config, "__all__")
        assert "ConfigKey" in config.__all__

    def test_config_key_importable_from_constants(self) -> None:
        """Test that ConfigKey can be imported from constants package."""
        from claude_code_hooks_daemon.constants import ConfigKey as ImportedConfigKey

        assert ImportedConfigKey.ENABLED == "enabled"
        assert ImportedConfigKey.DAEMON == "daemon"


class TestConfigKeyGroups:
    """Tests for logical groupings of config keys."""

    def test_handler_keys_group(self) -> None:
        """Test that all handler-related keys are defined."""
        handler_keys = [
            ConfigKey.ENABLED,
            ConfigKey.PRIORITY,
            ConfigKey.OPTIONS,
            ConfigKey.ENABLE_TAGS,
            ConfigKey.DISABLE_TAGS,
            ConfigKey.SHARES_OPTIONS_WITH,
            ConfigKey.DEPENDS_ON,
        ]
        assert len(handler_keys) == 7
        assert all(isinstance(key, str) for key in handler_keys)

    def test_daemon_keys_group(self) -> None:
        """Test that all daemon-related keys are defined."""
        daemon_keys = [
            ConfigKey.IDLE_TIMEOUT_SECONDS,
            ConfigKey.LOG_LEVEL,
            ConfigKey.SOCKET_PATH,
            ConfigKey.PID_FILE_PATH,
            ConfigKey.LOG_BUFFER_SIZE,
            ConfigKey.REQUEST_TIMEOUT_SECONDS,
            ConfigKey.SELF_INSTALL_MODE,
            ConfigKey.ENABLE_HELLO_WORLD_HANDLERS,
            ConfigKey.INPUT_VALIDATION,
        ]
        assert len(daemon_keys) == 9
        assert all(isinstance(key, str) for key in daemon_keys)
