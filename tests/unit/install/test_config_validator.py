"""Tests for ConfigValidator - validates merged config using Pydantic models.

TDD: These tests are written FIRST, before the implementation.
"""

from typing import Any

from claude_code_hooks_daemon.install.config_validator import ConfigValidator, ValidationResult


class TestValidationResult:
    """Test ValidationResult dataclass."""

    def test_valid_result(self) -> None:
        """ValidationResult with no errors is valid."""
        result = ValidationResult(valid=True, errors=[], warnings=[])
        assert result.valid is True
        assert result.errors == []
        assert result.warnings == []

    def test_invalid_result(self) -> None:
        """ValidationResult with errors is invalid."""
        result = ValidationResult(
            valid=False,
            errors=["Missing required field 'daemon'"],
            warnings=[],
        )
        assert result.valid is False
        assert len(result.errors) == 1

    def test_to_dict(self) -> None:
        """ValidationResult can be serialized to dict."""
        result = ValidationResult(
            valid=True,
            errors=[],
            warnings=["Handler 'old_handler' is deprecated"],
        )
        d = result.to_dict()
        assert d["valid"] is True
        assert d["errors"] == []
        assert len(d["warnings"]) == 1

    def test_guidance_property_empty_when_valid(self) -> None:
        """Guidance is empty for valid configs."""
        result = ValidationResult(valid=True, errors=[], warnings=[])
        assert result.guidance == ""

    def test_guidance_property_with_errors(self) -> None:
        """Guidance provides human-readable text for errors."""
        result = ValidationResult(
            valid=False,
            errors=["Invalid value for daemon.log_level: 'TRACE'"],
            warnings=[],
        )
        guidance = result.guidance
        assert "Invalid value for daemon.log_level" in guidance


class TestConfigValidatorInit:
    """Test ConfigValidator initialization."""

    def test_creates_instance(self) -> None:
        """ConfigValidator can be instantiated."""
        validator = ConfigValidator()
        assert validator is not None


class TestConfigValidatorValidate:
    """Test ConfigValidator.validate() method."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.validator = ConfigValidator()

    def test_valid_minimal_config(self) -> None:
        """Minimal valid config passes validation."""
        config = {
            "version": "2.0",
            "daemon": {"log_level": "INFO"},
            "handlers": {},
        }
        result = self.validator.validate(config)
        assert result.valid is True

    def test_valid_full_config(self) -> None:
        """Full config with handlers passes validation."""
        config = {
            "version": "2.0",
            "daemon": {
                "log_level": "INFO",
                "idle_timeout_seconds": 600,
            },
            "handlers": {"pre_tool_use": {"destructive_git": {"enabled": True, "priority": 10}}},
        }
        result = self.validator.validate(config)
        assert result.valid is True

    def test_invalid_version_format(self) -> None:
        """Invalid version format is caught."""
        config = {
            "version": "abc",
            "daemon": {},
            "handlers": {},
        }
        result = self.validator.validate(config)
        assert result.valid is False
        assert any("version" in e.lower() for e in result.errors)

    def test_invalid_log_level(self) -> None:
        """Invalid log level is caught."""
        config = {
            "version": "2.0",
            "daemon": {"log_level": "TRACE"},
            "handlers": {},
        }
        result = self.validator.validate(config)
        assert result.valid is False
        assert any("log_level" in e.lower() for e in result.errors)

    def test_invalid_idle_timeout(self) -> None:
        """Invalid idle_timeout_seconds is caught (must be >= 1)."""
        config = {
            "version": "2.0",
            "daemon": {"idle_timeout_seconds": 0},
            "handlers": {},
        }
        result = self.validator.validate(config)
        assert result.valid is False

    def test_invalid_handler_extra_field(self) -> None:
        """Handler with extra field is caught (HandlerConfig extra=forbid)."""
        config = {
            "version": "2.0",
            "daemon": {},
            "handlers": {
                "pre_tool_use": {
                    "destructive_git": {
                        "enabled": True,
                        "priority": 10,
                        "nonexistent_field": "value",
                    }
                }
            },
        }
        result = self.validator.validate(config)
        assert result.valid is False

    def test_empty_config(self) -> None:
        """Empty config uses defaults and passes."""
        config: dict[str, object] = {}
        result = self.validator.validate(config)
        assert result.valid is True

    def test_none_values_handled(self) -> None:
        """Config with None values is handled gracefully."""
        config = {
            "version": "2.0",
            "daemon": None,
            "handlers": {},
        }
        result = self.validator.validate(config)
        # Pydantic may accept None for optional or may fail - either way no crash
        assert isinstance(result, ValidationResult)

    def test_non_dict_input(self) -> None:
        """Non-dict input produces validation error."""
        bad_input: Any = "not a dict"
        result = self.validator.validate(bad_input)
        assert result.valid is False
        assert len(result.errors) > 0

    def test_valid_config_with_plugins(self) -> None:
        """Config with valid plugin section passes."""
        config = {
            "version": "2.0",
            "daemon": {},
            "handlers": {},
            "plugins": {
                "paths": [],
                "plugins": [
                    {
                        "path": ".claude/handlers/my_plugin.py",
                        "event_type": "pre_tool_use",
                        "enabled": True,
                    }
                ],
            },
        }
        result = self.validator.validate(config)
        assert result.valid is True

    def test_validation_result_includes_field_path(self) -> None:
        """Error messages include the field path for easy debugging."""
        config = {
            "version": "2.0",
            "daemon": {"request_timeout_seconds": 999},
            "handlers": {},
        }
        result = self.validator.validate(config)
        assert result.valid is False
        # Error should mention the field
        error_text = " ".join(result.errors).lower()
        assert "request_timeout" in error_text or "timeout" in error_text


class TestValidationResultGuidanceWithWarnings:
    """Test guidance output with warnings."""

    def test_guidance_includes_warnings(self) -> None:
        """Guidance includes warnings section when warnings exist."""
        result = ValidationResult(
            valid=False,
            errors=["Field X is invalid"],
            warnings=["Handler Y is deprecated"],
        )
        guidance = result.guidance
        assert "Warnings" in guidance
        assert "Handler Y is deprecated" in guidance
        assert "Field X is invalid" in guidance
        assert ".claude/hooks-daemon.yaml.example" in guidance
