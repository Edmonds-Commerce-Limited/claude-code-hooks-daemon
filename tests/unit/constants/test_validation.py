"""Tests for validation limit constants.

Tests that all validation limits are properly defined and have
reasonable values for their intended use.
"""

from claude_code_hooks_daemon.constants.validation import ValidationLimit


class TestLogBufferLimits:
    """Tests for log buffer size limits."""

    def test_log_buffer_limits(self) -> None:
        """Test log buffer size limit constants."""
        assert ValidationLimit.LOG_BUFFER_MIN == 100
        assert ValidationLimit.LOG_BUFFER_MAX == 100_000
        assert ValidationLimit.LOG_BUFFER_DEFAULT == 1_000

    def test_log_buffer_range_is_valid(self) -> None:
        """Test that log buffer min < default < max."""
        assert ValidationLimit.LOG_BUFFER_MIN < ValidationLimit.LOG_BUFFER_DEFAULT
        assert ValidationLimit.LOG_BUFFER_DEFAULT < ValidationLimit.LOG_BUFFER_MAX

    def test_log_buffer_default_is_reasonable(self) -> None:
        """Test that default log buffer size is reasonable."""
        # Default should be at least 10x minimum
        assert ValidationLimit.LOG_BUFFER_DEFAULT >= ValidationLimit.LOG_BUFFER_MIN * 10
        # Default should be at most 1/10th of maximum
        assert ValidationLimit.LOG_BUFFER_DEFAULT <= ValidationLimit.LOG_BUFFER_MAX / 10


class TestTimeoutLimits:
    """Tests for timeout limits."""

    def test_request_timeout_limits(self) -> None:
        """Test request timeout limit constants."""
        assert ValidationLimit.REQUEST_TIMEOUT_MIN == 1
        assert ValidationLimit.REQUEST_TIMEOUT_MAX == 300
        assert ValidationLimit.REQUEST_TIMEOUT_DEFAULT == 30

    def test_idle_timeout_limits(self) -> None:
        """Test idle timeout limit constants."""
        assert ValidationLimit.IDLE_TIMEOUT_MIN == 1
        assert ValidationLimit.IDLE_TIMEOUT_MAX == 86_400  # 24 hours
        assert ValidationLimit.IDLE_TIMEOUT_DEFAULT == 600  # 10 minutes

    def test_timeout_ranges_are_valid(self) -> None:
        """Test that timeout min < default < max for all timeouts."""
        # Request timeout
        assert ValidationLimit.REQUEST_TIMEOUT_MIN < ValidationLimit.REQUEST_TIMEOUT_DEFAULT
        assert ValidationLimit.REQUEST_TIMEOUT_DEFAULT < ValidationLimit.REQUEST_TIMEOUT_MAX

        # Idle timeout
        assert ValidationLimit.IDLE_TIMEOUT_MIN < ValidationLimit.IDLE_TIMEOUT_DEFAULT
        assert ValidationLimit.IDLE_TIMEOUT_DEFAULT < ValidationLimit.IDLE_TIMEOUT_MAX

    def test_timeout_minimums_are_positive(self) -> None:
        """Test that all timeout minimums are positive."""
        assert ValidationLimit.REQUEST_TIMEOUT_MIN > 0
        assert ValidationLimit.IDLE_TIMEOUT_MIN > 0


class TestPriorityLimits:
    """Tests for handler priority limits."""

    def test_priority_limits(self) -> None:
        """Test priority limit constants."""
        assert ValidationLimit.PRIORITY_MIN == 0
        assert ValidationLimit.PRIORITY_MAX == 100
        assert ValidationLimit.PRIORITY_DEFAULT == 50

    def test_priority_range_is_valid(self) -> None:
        """Test that priority min <= default <= max."""
        assert ValidationLimit.PRIORITY_MIN <= ValidationLimit.PRIORITY_DEFAULT
        assert ValidationLimit.PRIORITY_DEFAULT <= ValidationLimit.PRIORITY_MAX

    def test_priority_default_is_midpoint(self) -> None:
        """Test that default priority is at the midpoint."""
        expected_midpoint = (ValidationLimit.PRIORITY_MIN + ValidationLimit.PRIORITY_MAX) // 2
        assert expected_midpoint == ValidationLimit.PRIORITY_DEFAULT


class TestHandlerLimits:
    """Tests for handler-related limits."""

    def test_handler_name_length_limits(self) -> None:
        """Test handler name length limits."""
        assert ValidationLimit.HANDLER_NAME_MIN_LENGTH == 3
        assert ValidationLimit.HANDLER_NAME_MAX_LENGTH == 100

    def test_handler_name_length_range_is_valid(self) -> None:
        """Test that handler name min < max."""
        assert ValidationLimit.HANDLER_NAME_MIN_LENGTH < ValidationLimit.HANDLER_NAME_MAX_LENGTH


class TestConfigLimits:
    """Tests for config-related limits."""

    def test_config_version_limits(self) -> None:
        """Test config version limits."""
        assert ValidationLimit.CONFIG_VERSION_MIN_MAJOR == 1
        assert ValidationLimit.CONFIG_VERSION_MAX_MAJOR == 10

    def test_config_version_range_is_valid(self) -> None:
        """Test that config version min < max."""
        assert ValidationLimit.CONFIG_VERSION_MIN_MAJOR < ValidationLimit.CONFIG_VERSION_MAX_MAJOR


class TestPluginLimits:
    """Tests for plugin-related limits."""

    def test_plugin_limits(self) -> None:
        """Test plugin limit constants."""
        assert ValidationLimit.MAX_PLUGINS == 100
        assert ValidationLimit.MAX_PLUGIN_DIRS == 10

    def test_plugin_limits_are_positive(self) -> None:
        """Test that plugin limits are positive."""
        assert ValidationLimit.MAX_PLUGINS > 0
        assert ValidationLimit.MAX_PLUGIN_DIRS > 0


class TestPathLimits:
    """Tests for path-related limits."""

    def test_path_length_limits(self) -> None:
        """Test path length limit constants."""
        assert ValidationLimit.MAX_PATH_LENGTH == 4096
        assert ValidationLimit.MAX_SOCKET_PATH_LENGTH == 108

    def test_socket_path_limit_is_realistic(self) -> None:
        """Test that socket path limit matches Unix socket limit."""
        # Unix socket path limit is 108 bytes on most systems
        assert ValidationLimit.MAX_SOCKET_PATH_LENGTH == 108

    def test_path_limits_are_positive(self) -> None:
        """Test that path limits are positive."""
        assert ValidationLimit.MAX_PATH_LENGTH > 0
        assert ValidationLimit.MAX_SOCKET_PATH_LENGTH > 0


class TestTagLimits:
    """Tests for handler tag limits."""

    def test_tag_limits(self) -> None:
        """Test handler tag limit constants."""
        assert ValidationLimit.MAX_TAGS_PER_HANDLER == 20
        assert ValidationLimit.MAX_TAG_LENGTH == 50

    def test_tag_limits_are_reasonable(self) -> None:
        """Test that tag limits are reasonable."""
        assert ValidationLimit.MAX_TAGS_PER_HANDLER >= 5  # At least 5 tags per handler
        assert ValidationLimit.MAX_TAG_LENGTH >= 20  # At least 20 chars per tag


class TestValidationLimitTypes:
    """Tests for validation limit types."""

    def test_all_limits_are_integers(self) -> None:
        """Test that all validation limits are integers."""
        for key, value in vars(ValidationLimit).items():
            if not key.startswith("_"):
                assert isinstance(value, int), f"{key} should be an integer"

    def test_all_limits_are_positive(self) -> None:
        """Test that all validation limits are non-negative."""
        for key, value in vars(ValidationLimit).items():
            if not key.startswith("_") and isinstance(value, int):
                assert value >= 0, f"{key}={value} should be non-negative"


class TestValidationLimitExport:
    """Tests for module exports."""

    def test_all_exports(self) -> None:
        """Test that __all__ contains expected exports."""
        from claude_code_hooks_daemon.constants import validation

        assert hasattr(validation, "__all__")
        assert "ValidationLimit" in validation.__all__

    def test_validation_limit_importable_from_constants(self) -> None:
        """Test that ValidationLimit can be imported from constants package."""
        from claude_code_hooks_daemon.constants import (
            ValidationLimit as ImportedValidationLimit,
        )

        assert ImportedValidationLimit.LOG_BUFFER_DEFAULT == 1_000
        assert ImportedValidationLimit.PRIORITY_DEFAULT == 50


class TestValidationUsagePatterns:
    """Tests for validation limit usage patterns."""

    def test_pydantic_field_pattern(self) -> None:
        """Test usage pattern with Pydantic Field validation."""
        # Simulate Pydantic Field usage
        min_val = ValidationLimit.LOG_BUFFER_MIN
        max_val = ValidationLimit.LOG_BUFFER_MAX
        default = ValidationLimit.LOG_BUFFER_DEFAULT

        # Test that default is within range
        assert min_val <= default <= max_val

    def test_validation_check_pattern(self) -> None:
        """Test usage pattern for validation checks."""
        value = 500

        # Simulate validation check
        is_valid = ValidationLimit.LOG_BUFFER_MIN <= value <= ValidationLimit.LOG_BUFFER_MAX
        assert is_valid is True

        # Test invalid value
        invalid_value = 50
        is_valid = ValidationLimit.LOG_BUFFER_MIN <= invalid_value <= ValidationLimit.LOG_BUFFER_MAX
        assert is_valid is False


class TestLimitRelationships:
    """Tests for relationships between related limits."""

    def test_timeout_limits_relationship(self) -> None:
        """Test that timeout limits have appropriate relationships."""
        # Request timeout should be less than idle timeout
        assert ValidationLimit.REQUEST_TIMEOUT_MAX < ValidationLimit.IDLE_TIMEOUT_DEFAULT

    def test_buffer_size_is_reasonable_for_timeouts(self) -> None:
        """Test that buffer size is reasonable for timeout durations."""
        # At idle timeout, we shouldn't overflow buffer
        # Assuming ~1 log entry per second max
        max_entries_at_idle = ValidationLimit.IDLE_TIMEOUT_DEFAULT
        assert max_entries_at_idle <= ValidationLimit.LOG_BUFFER_DEFAULT
