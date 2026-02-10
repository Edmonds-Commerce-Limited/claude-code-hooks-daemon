"""Installation and upgrade validation for client projects."""

from claude_code_hooks_daemon.install.client_validator import (
    ClientInstallValidator,
    ClientValidationError,
    ValidationResult,
)
from claude_code_hooks_daemon.install.config_differ import ConfigDiff, ConfigDiffer
from claude_code_hooks_daemon.install.config_merger import ConfigMerger, MergeConflict, MergeResult
from claude_code_hooks_daemon.install.config_validator import ConfigValidator
from claude_code_hooks_daemon.install.config_validator import (
    ValidationResult as ConfigValidationResult,
)

__all__ = [
    "ClientInstallValidator",
    "ClientValidationError",
    "ConfigDiff",
    "ConfigDiffer",
    "ConfigMerger",
    "ConfigValidationResult",
    "ConfigValidator",
    "MergeConflict",
    "MergeResult",
    "ValidationResult",
]
