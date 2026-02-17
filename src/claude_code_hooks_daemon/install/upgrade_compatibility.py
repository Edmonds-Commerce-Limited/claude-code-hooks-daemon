"""Upgrade compatibility checker for config validation.

Checks if handlers in user config are compatible with target version by:
1. Detecting removed handlers from CHANGELOG.md breaking changes
2. Detecting renamed handlers from CHANGELOG.md
3. Validating handler names exist in target version
4. Generating user-friendly compatibility reports

Example Usage:
    checker = CompatibilityChecker(
        changelog_path=Path("CHANGELOG.md"),
        current_version="2.10.0",
        target_version="2.13.0"
    )
    report = checker.check_compatibility(user_config)
    if not report.is_compatible:
        print(checker.generate_user_friendly_report(report))
"""

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.config.validator import ConfigValidator
from claude_code_hooks_daemon.install.breaking_changes_detector import (
    BreakingChangesDetector,
    ChangeType,
)


class CompatibilityStatus(Enum):
    """Handler compatibility status."""

    COMPATIBLE = "compatible"
    REMOVED = "removed"
    RENAMED = "renamed"
    WARNING = "warning"  # Unknown handler (typo or doesn't exist)


@dataclass
class HandlerCompatibility:
    """Compatibility check result for a single handler.

    Attributes:
        handler_name: Handler name from user config
        event_type: Event type (pre_tool_use, post_tool_use, etc.)
        status: Compatibility status
        message: Human-readable explanation
        suggested_action: Optional suggested fix
        new_name: New handler name (for renames only)
    """

    handler_name: str
    event_type: str
    status: CompatibilityStatus
    message: str
    suggested_action: str | None = None
    new_name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary for JSON output.

        Returns:
            Dictionary representation
        """
        return {
            "handler_name": self.handler_name,
            "event_type": self.event_type,
            "status": self.status.value,
            "message": self.message,
            "suggested_action": self.suggested_action,
            "new_name": self.new_name,
        }


@dataclass
class CompatibilityReport:
    """Complete compatibility report for user config.

    Attributes:
        handlers: List of handler compatibility checks
        current_version: User's current version
        target_version: Target upgrade version
    """

    handlers: list[HandlerCompatibility]
    current_version: str
    target_version: str

    @property
    def is_compatible(self) -> bool:
        """Return True if all handlers are compatible.

        Returns:
            True if no removed/renamed/warning handlers found
        """
        incompatible_statuses = {
            CompatibilityStatus.REMOVED,
            CompatibilityStatus.RENAMED,
            CompatibilityStatus.WARNING,
        }
        return not any(h.status in incompatible_statuses for h in self.handlers)

    def get_handlers_by_status(self, status: CompatibilityStatus) -> list[HandlerCompatibility]:
        """Get all handlers with a specific status.

        Args:
            status: Status to filter by

        Returns:
            List of handlers with matching status
        """
        return [h for h in self.handlers if h.status == status]

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary for JSON output.

        Returns:
            Dictionary representation
        """
        return {
            "current_version": self.current_version,
            "target_version": self.target_version,
            "is_compatible": self.is_compatible,
            "handlers": [h.to_dict() for h in self.handlers],
        }


class CompatibilityChecker:
    """Checks config compatibility for upgrades.

    Validates user config against target version by checking:
    - Removed handlers (from CHANGELOG breaking changes)
    - Renamed handlers (from CHANGELOG breaking changes)
    - Handler existence in target version (via ConfigValidator)
    """

    def __init__(
        self,
        changelog_path: Path,
        current_version: str,
        target_version: str,
    ) -> None:
        """Initialize compatibility checker.

        Args:
            changelog_path: Path to CHANGELOG.md
            current_version: User's current version (e.g., "2.10.0")
            target_version: Target upgrade version (e.g., "2.13.0")
        """
        self.changelog_path = changelog_path
        self.current_version = current_version
        self.target_version = target_version
        self.breaking_changes = BreakingChangesDetector(changelog_path)

    def check_compatibility(self, user_config: dict[str, Any]) -> CompatibilityReport:
        """Check if user config is compatible with target version.

        Args:
            user_config: User's current configuration dict

        Returns:
            CompatibilityReport with per-handler checks
        """
        handlers_section = user_config.get("handlers", {})
        handler_checks: list[HandlerCompatibility] = []

        # Get breaking changes in version range
        breaking_changes = self.breaking_changes.get_changes_in_version_range(
            self.current_version, self.target_version
        )

        # Build lookup for removed/renamed handlers
        removed_handlers = {
            c.handler_name for c in breaking_changes if c.change_type == ChangeType.HANDLER_REMOVED
        }
        renamed_handlers = {
            c.handler_name: c.new_name
            for c in breaking_changes
            if c.change_type == ChangeType.HANDLER_RENAMED and c.new_name
        }

        # Check each handler in user config
        for event_type, handlers in handlers_section.items():
            if not isinstance(handlers, dict):
                continue

            # Get available handlers for this event type (in target version)
            available_handlers = ConfigValidator.get_available_handlers(event_type)

            for handler_name in handlers:
                compat = self._check_handler(
                    handler_name=handler_name,
                    event_type=event_type,
                    removed_handlers=removed_handlers,
                    renamed_handlers=renamed_handlers,
                    available_handlers=available_handlers,
                )
                handler_checks.append(compat)

        return CompatibilityReport(
            handlers=handler_checks,
            current_version=self.current_version,
            target_version=self.target_version,
        )

    def _check_handler(
        self,
        handler_name: str,
        event_type: str,
        removed_handlers: set[str],
        renamed_handlers: dict[str, str],
        available_handlers: set[str],
    ) -> HandlerCompatibility:
        """Check compatibility for a single handler.

        Args:
            handler_name: Handler name to check
            event_type: Event type
            removed_handlers: Set of known removed handler names
            renamed_handlers: Dict of renamed handlers (old -> new)
            available_handlers: Set of available handlers in target version

        Returns:
            HandlerCompatibility result
        """
        # Check if handler was removed
        if handler_name in removed_handlers:
            changes = self.breaking_changes.get_changes_for_handler(handler_name)
            migration_hint = (
                changes[0].migration_hint if changes and changes[0].migration_hint else None
            )
            return HandlerCompatibility(
                handler_name=handler_name,
                event_type=event_type,
                status=CompatibilityStatus.REMOVED,
                message=f"Handler '{handler_name}' was removed in v{self.target_version}",
                suggested_action=migration_hint,
            )

        # Check if handler was renamed
        if handler_name in renamed_handlers:
            new_name = renamed_handlers[handler_name]
            return HandlerCompatibility(
                handler_name=handler_name,
                event_type=event_type,
                status=CompatibilityStatus.RENAMED,
                message=f"Handler '{handler_name}' was renamed to '{new_name}' in v{self.target_version}",
                suggested_action=f"Update config to use '{new_name}' instead",
                new_name=new_name,
            )

        # Check if handler exists in target version
        if handler_name not in available_handlers:
            return HandlerCompatibility(
                handler_name=handler_name,
                event_type=event_type,
                status=CompatibilityStatus.WARNING,
                message=f"Handler '{handler_name}' not found in target version (possible typo or removed without marker)",
                suggested_action="Verify handler name is correct or remove from config",
            )

        # Handler is compatible
        return HandlerCompatibility(
            handler_name=handler_name,
            event_type=event_type,
            status=CompatibilityStatus.COMPATIBLE,
            message=f"Handler '{handler_name}' is compatible with v{self.target_version}",
        )

    def generate_user_friendly_report(self, report: CompatibilityReport) -> str:
        """Generate human-readable compatibility report text.

        Args:
            report: CompatibilityReport to format

        Returns:
            Formatted report text with colors and suggestions
        """
        lines: list[str] = []

        lines.append("=" * 70)
        lines.append("UPGRADE COMPATIBILITY REPORT")
        lines.append("=" * 70)
        lines.append("")
        lines.append(f"Current Version: {report.current_version}")
        lines.append(f"Target Version:  {report.target_version}")
        lines.append("")

        if report.is_compatible:
            lines.append("✅ All handlers are compatible with target version")
            lines.append("")
            return "\n".join(lines)

        lines.append("⚠️  INCOMPATIBILITIES DETECTED")
        lines.append("")

        # Group handlers by status
        removed = report.get_handlers_by_status(CompatibilityStatus.REMOVED)
        renamed = report.get_handlers_by_status(CompatibilityStatus.RENAMED)
        warnings = report.get_handlers_by_status(CompatibilityStatus.WARNING)

        if removed:
            lines.append("REMOVED HANDLERS:")
            lines.append("-" * 70)
            for handler in removed:
                lines.append(f"  ❌ {handler.event_type}.{handler.handler_name}")
                lines.append(f"      {handler.message}")
                if handler.suggested_action:
                    lines.append(f"      → {handler.suggested_action}")
                lines.append("")

        if renamed:
            lines.append("RENAMED HANDLERS:")
            lines.append("-" * 70)
            for handler in renamed:
                lines.append(f"  🔄 {handler.event_type}.{handler.handler_name}")
                lines.append(f"      {handler.message}")
                if handler.suggested_action:
                    lines.append(f"      → {handler.suggested_action}")
                lines.append("")

        if warnings:
            lines.append("UNKNOWN HANDLERS:")
            lines.append("-" * 70)
            for handler in warnings:
                lines.append(f"  ⚠️  {handler.event_type}.{handler.handler_name}")
                lines.append(f"      {handler.message}")
                if handler.suggested_action:
                    lines.append(f"      → {handler.suggested_action}")
                lines.append("")

        lines.append("REQUIRED ACTIONS:")
        lines.append("-" * 70)
        lines.append("1. Review upgrade guides for breaking changes")
        lines.append("2. Update or remove incompatible handlers from config")
        lines.append("3. Re-run upgrade after fixing config issues")
        lines.append("")
        lines.append("Upgrade guides: CLAUDE/UPGRADES/v2/")
        lines.append("")

        return "\n".join(lines)

    def suggest_upgrade_guides(self, daemon_dir: Path) -> list[Path]:
        """Suggest relevant upgrade guides for version range.

        Args:
            daemon_dir: Path to daemon installation directory

        Returns:
            List of upgrade guide paths to read
        """
        upgrades_dir = daemon_dir / "CLAUDE" / "UPGRADES" / "v2"

        if not upgrades_dir.exists():
            return []

        # Parse version numbers
        current_parts = self.current_version.split(".")
        target_parts = self.target_version.split(".")

        current_minor = int(current_parts[1])
        target_minor = int(target_parts[1])

        guides: list[Path] = []

        # Find all intermediate upgrade guides
        for minor in range(current_minor, target_minor + 1):
            next_minor = minor + 1
            guide_dir = upgrades_dir / f"v2.{minor}-to-v2.{next_minor}"
            if guide_dir.exists():
                # Look for main guide file
                guide_file = guide_dir / f"v2.{minor}-to-v2.{next_minor}.md"
                if guide_file.exists():
                    guides.append(guide_file)

        return guides
