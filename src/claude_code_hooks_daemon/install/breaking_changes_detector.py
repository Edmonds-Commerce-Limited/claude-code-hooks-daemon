"""Breaking changes detector for CHANGELOG.md parsing.

Parses CHANGELOG.md for breaking change markers (HTML comments) and generates
user-friendly warnings for config incompatibilities during upgrades.

Marker Format:
    <!--BREAKING: handler:name:action-->
    <!--BREAKING: handler:old_name:renamed:new_name-->

Example Usage:
    detector = BreakingChangesDetector(changelog_path)
    changes = detector.get_breaking_changes()
    warnings = detector.generate_warnings(removed_handlers=["validate_sitemap"])
"""

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any


class ChangeType(Enum):
    """Type of breaking change."""

    HANDLER_REMOVED = "handler_removed"
    HANDLER_RENAMED = "handler_renamed"
    CONFIG_CHANGED = "config_changed"  # Not implemented yet


@dataclass
class BreakingChange:
    """Represents a breaking change detected in CHANGELOG.md.

    Attributes:
        version: Version where change occurred (e.g., "2.13.0")
        change_type: Type of breaking change
        handler_name: Name of affected handler
        description: Human-readable description of the change
        migration_hint: Optional migration guidance
        new_name: New handler name (for renames only)
    """

    version: str
    change_type: ChangeType
    handler_name: str
    description: str
    migration_hint: str | None = None
    new_name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary for JSON output.

        Returns:
            Dictionary representation of breaking change
        """
        return {
            "version": self.version,
            "change_type": self.change_type.value,
            "handler_name": self.handler_name,
            "description": self.description,
            "migration_hint": self.migration_hint,
            "new_name": self.new_name,
        }


class BreakingChangesDetector:
    """Detects breaking changes from CHANGELOG.md markers.

    Parses CHANGELOG.md for HTML comment markers indicating breaking changes:
        <!--BREAKING: handler:name:removed-->
        <!--BREAKING: handler:old_name:renamed:new_name-->

    Provides methods to query changes by handler name, version range, and
    generate user-friendly warnings for detected incompatibilities.
    """

    # Regex patterns for parsing
    _VERSION_PATTERN = re.compile(r"^##\s+\[(\d+\.\d+\.\d+)\]")
    _MARKER_PATTERN = re.compile(r"<!--BREAKING:\s*handler:([^:]+):([^:]+)(?::([^>]+))?-->")

    def __init__(self, changelog_path: Path) -> None:
        """Initialize detector with CHANGELOG.md path.

        Args:
            changelog_path: Path to CHANGELOG.md file

        Raises:
            FileNotFoundError: If CHANGELOG.md doesn't exist
        """
        if not changelog_path.exists():
            raise FileNotFoundError(f"CHANGELOG.md not found: {changelog_path}")

        self.changelog_path = changelog_path
        self._changes: list[BreakingChange] = []
        self._parse_changelog()

    def _parse_changelog(self) -> None:
        """Parse CHANGELOG.md and extract breaking change markers."""
        content = self.changelog_path.read_text()
        lines = content.splitlines()

        current_version: str | None = None

        for line in lines:
            # Check for version header
            version_match = self._VERSION_PATTERN.match(line)
            if version_match:
                current_version = version_match.group(1)
                continue

            # Check for breaking change marker
            marker_match = self._MARKER_PATTERN.search(line)
            if marker_match and current_version:
                handler_name = marker_match.group(1)
                action = marker_match.group(2)
                extra = marker_match.group(3)

                # Parse action type
                if action == "removed":
                    change = BreakingChange(
                        version=current_version,
                        change_type=ChangeType.HANDLER_REMOVED,
                        handler_name=handler_name,
                        description=f"Handler '{handler_name}' was removed in v{current_version}",
                        migration_hint=f"See CLAUDE/UPGRADES/v2/v{current_version[0]}.{int(current_version.split('.')[1]) - 1}-to-v{current_version}/ for migration guide",
                    )
                    self._changes.append(change)

                elif action == "renamed" and extra:
                    new_name = extra
                    change = BreakingChange(
                        version=current_version,
                        change_type=ChangeType.HANDLER_RENAMED,
                        handler_name=handler_name,
                        new_name=new_name,
                        description=f"Handler '{handler_name}' was renamed to '{new_name}' in v{current_version}",
                        migration_hint=f"Update your config to use '{new_name}' instead of '{handler_name}'",
                    )
                    self._changes.append(change)

    def get_breaking_changes(self) -> list[BreakingChange]:
        """Get all detected breaking changes.

        Returns:
            List of all breaking changes found in CHANGELOG.md
        """
        return self._changes.copy()

    def get_changes_for_handler(self, handler_name: str) -> list[BreakingChange]:
        """Get breaking changes for a specific handler.

        Args:
            handler_name: Handler name to query

        Returns:
            List of breaking changes affecting this handler
        """
        return [c for c in self._changes if c.handler_name == handler_name]

    def get_changes_in_version_range(
        self, from_version: str, to_version: str
    ) -> list[BreakingChange]:
        """Get breaking changes within a version range (inclusive).

        Args:
            from_version: Starting version (e.g., "2.12.0")
            to_version: Ending version (e.g., "2.13.0")

        Returns:
            List of breaking changes in the version range
        """

        def version_tuple(v: str) -> tuple[int, int, int]:
            parts = v.split(".")
            return (int(parts[0]), int(parts[1]), int(parts[2]))

        from_tuple = version_tuple(from_version)
        to_tuple = version_tuple(to_version)

        result = []
        for change in self._changes:
            change_tuple = version_tuple(change.version)
            if from_tuple <= change_tuple <= to_tuple:
                result.append(change)

        return result

    def generate_warnings(
        self,
        removed_handlers: list[str] | None = None,
        renamed_handlers: dict[str, str] | None = None,
    ) -> list[str]:
        """Generate user-friendly warnings for detected config issues.

        Args:
            removed_handlers: List of handler names that were removed
            renamed_handlers: Dict mapping old names to new names

        Returns:
            List of formatted warning messages
        """
        warnings: list[str] = []

        # Generate warnings for removed handlers
        if removed_handlers:
            for handler_name in removed_handlers:
                changes = self.get_changes_for_handler(handler_name)
                for change in changes:
                    if change.change_type == ChangeType.HANDLER_REMOVED:
                        warning = f"⚠️  Handler '{handler_name}' was removed in v{change.version}"
                        if change.migration_hint:
                            warning += f"\n    → {change.migration_hint}"
                        warnings.append(warning)

        # Generate warnings for renamed handlers
        if renamed_handlers:
            for old_name, new_name in renamed_handlers.items():
                changes = self.get_changes_for_handler(old_name)
                for change in changes:
                    if (
                        change.change_type == ChangeType.HANDLER_RENAMED
                        and change.new_name == new_name
                    ):
                        warning = f"🔄 Handler '{old_name}' was renamed to '{new_name}' in v{change.version}"
                        if change.migration_hint:
                            warning += f"\n    → {change.migration_hint}"
                        warnings.append(warning)

        return warnings
