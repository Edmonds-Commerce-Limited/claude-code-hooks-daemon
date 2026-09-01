"""Config validator for merged configuration files.

Uses Pydantic Config.model_validate() to validate merged configs and
provides structured results with user-friendly guidance for fixing issues.

Used during upgrades after config merge to ensure the result is valid.
"""

from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from claude_code_hooks_daemon.config.models import Config
from claude_code_hooks_daemon.config.validator import (
    ConfigValidator as _BusinessRuleValidator,
)


@dataclass
class ValidationResult:
    """Result of config validation.

    Attributes:
        valid: Whether the config passed validation
        errors: List of error messages
        warnings: List of warning messages (non-fatal)
    """

    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def guidance(self) -> str:
        """Generate user-friendly guidance for fixing validation errors.

        Returns:
            Human-readable guidance string, empty if config is valid.
        """
        if self.valid:
            return ""

        lines: list[str] = []
        lines.append("Config validation failed. Please fix the following issues:")
        lines.append("")

        for i, error in enumerate(self.errors, 1):
            lines.append(f"  {i}. {error}")

        if self.warnings:
            lines.append("")
            lines.append("Warnings (non-blocking):")
            for warning in self.warnings:
                lines.append(f"  - {warning}")

        lines.append("")
        lines.append("Hint: Compare your config against the example config:")
        lines.append("  .claude/hooks-daemon.yaml.example")

        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary.

        Returns:
            Dictionary representation.
        """
        return {
            "valid": self.valid,
            "errors": self.errors,
            "warnings": self.warnings,
            "guidance": self.guidance,
        }


class ConfigValidator:
    """Validates merged configuration using Pydantic Config model.

    Wraps Config.model_validate() and converts Pydantic ValidationErrors
    into structured, user-friendly ValidationResult objects.
    """

    def validate(self, config: dict[str, Any]) -> ValidationResult:
        """Validate a configuration dictionary against the Pydantic schema.

        Args:
            config: Configuration dictionary to validate

        Returns:
            ValidationResult with errors and warnings
        """
        if not isinstance(config, dict):
            return ValidationResult(
                valid=False,
                errors=["Configuration must be a dictionary, got: " + type(config).__name__],
            )

        try:
            Config.model_validate(config)
        except ValidationError as e:
            errors = self._extract_errors(e)
            return ValidationResult(valid=False, errors=errors)
        except Exception as e:
            return ValidationResult(
                valid=False,
                errors=[f"Unexpected validation error: {e}"],
            )

        # Plan 00304: the Pydantic schema check above is necessary but not
        # sufficient -- it cannot see hand-written business rules like the
        # Plan 00300 removed-`monorepo_subproject_patterns` hard cutover, so
        # this CLI used to report `valid: true` for a config the daemon's OWN
        # startup path (`config.validator.ConfigValidator.validate`) degrades
        # on -- a real-repo canary caught exactly that divergence. Reuse the
        # SAME check here (not the whole startup validator, which additionally
        # requires top-level `version`/`daemon`/`handlers` sections this
        # merged-config validator intentionally treats as optional/defaulted).
        try:
            business_rule_errors = _BusinessRuleValidator.validate_business_rules(config)
        except Exception as e:
            return ValidationResult(
                valid=False,
                errors=[f"Unexpected validation error: {e}"],
            )
        if business_rule_errors:
            return ValidationResult(valid=False, errors=business_rule_errors)

        return ValidationResult(valid=True)

    def _extract_errors(self, validation_error: ValidationError) -> list[str]:
        """Extract human-readable error messages from Pydantic ValidationError.

        Args:
            validation_error: Pydantic ValidationError to extract errors from

        Returns:
            List of human-readable error strings
        """
        errors: list[str] = []

        for error in validation_error.errors():
            location = " -> ".join(str(loc) for loc in error["loc"])
            message = error["msg"]
            error_type = error["type"]

            if location:
                errors.append(f"{location}: {message} (type: {error_type})")
            else:
                errors.append(f"{message} (type: {error_type})")

        return errors
