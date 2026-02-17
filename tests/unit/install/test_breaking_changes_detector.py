"""Tests for breaking_changes_detector module."""

from pathlib import Path

import pytest

from claude_code_hooks_daemon.install.breaking_changes_detector import (
    BreakingChange,
    BreakingChangesDetector,
    ChangeType,
)


@pytest.fixture
def sample_changelog_with_markers(tmp_path: Path) -> Path:
    """Create a sample CHANGELOG.md with HTML comment markers."""
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("""# Changelog

## [2.13.0] - 2026-02-17

### Added
- New feature X

### Removed
<!--BREAKING: handler:validate_sitemap:removed-->
- **validate_sitemap handler**: Removed project-specific PostToolUse handler
<!--BREAKING: handler:remind_validator:removed-->
- **remind_validator handler**: Removed project-specific SubagentStop handler

## [2.12.0] - 2026-02-12

### Changed
<!--BREAKING: handler:tdd_enforcement:renamed:tdd-->
- **TDD Enforcement Handler**: Renamed from `tdd_enforcement` to `tdd` for brevity

## [2.11.0] - 2026-02-10

### Added
- Regular feature (no breaking change)
""")
    return changelog


@pytest.fixture
def sample_changelog_no_markers(tmp_path: Path) -> Path:
    """Create a CHANGELOG.md without breaking change markers."""
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("""# Changelog

## [2.13.0] - 2026-02-17

### Added
- New feature X

### Fixed
- Bug fix Y
""")
    return changelog


class TestBreakingChange:
    """Tests for BreakingChange dataclass."""

    def test_breaking_change_initialization(self) -> None:
        """BreakingChange can be initialized with all fields."""
        change = BreakingChange(
            version="2.13.0",
            change_type=ChangeType.HANDLER_REMOVED,
            handler_name="validate_sitemap",
            description="Removed project-specific handler",
            migration_hint="See upgrade guide for migration path",
        )

        assert change.version == "2.13.0"
        assert change.change_type == ChangeType.HANDLER_REMOVED
        assert change.handler_name == "validate_sitemap"
        assert change.description == "Removed project-specific handler"
        assert change.migration_hint == "See upgrade guide for migration path"

    def test_breaking_change_to_dict(self) -> None:
        """BreakingChange can be serialized to dict."""
        change = BreakingChange(
            version="2.13.0",
            change_type=ChangeType.HANDLER_REMOVED,
            handler_name="validate_sitemap",
            description="Removed handler",
        )

        result = change.to_dict()

        assert result["version"] == "2.13.0"
        assert result["change_type"] == "handler_removed"
        assert result["handler_name"] == "validate_sitemap"
        assert result["description"] == "Removed handler"
        assert result["migration_hint"] is None


class TestBreakingChangesDetector:
    """Tests for BreakingChangesDetector."""

    def test_parse_changelog_with_markers(self, sample_changelog_with_markers: Path) -> None:
        """Detector parses breaking change markers from CHANGELOG.md."""
        detector = BreakingChangesDetector(sample_changelog_with_markers)
        changes = detector.get_breaking_changes()

        assert len(changes) == 3

        # Check removed handlers
        removed = [c for c in changes if c.change_type == ChangeType.HANDLER_REMOVED]
        assert len(removed) == 2
        assert {c.handler_name for c in removed} == {
            "validate_sitemap",
            "remind_validator",
        }

        # Check renamed handler
        renamed = [c for c in changes if c.change_type == ChangeType.HANDLER_RENAMED]
        assert len(renamed) == 1
        assert renamed[0].handler_name == "tdd_enforcement"
        assert renamed[0].new_name == "tdd"

    def test_parse_changelog_no_markers(self, sample_changelog_no_markers: Path) -> None:
        """Detector returns empty list when no breaking change markers found."""
        detector = BreakingChangesDetector(sample_changelog_no_markers)
        changes = detector.get_breaking_changes()

        assert len(changes) == 0

    def test_get_changes_for_handler_removed(self, sample_changelog_with_markers: Path) -> None:
        """get_changes_for_handler returns changes for specific handler."""
        detector = BreakingChangesDetector(sample_changelog_with_markers)
        changes = detector.get_changes_for_handler("validate_sitemap")

        assert len(changes) == 1
        assert changes[0].handler_name == "validate_sitemap"
        assert changes[0].change_type == ChangeType.HANDLER_REMOVED

    def test_get_changes_for_handler_renamed(self, sample_changelog_with_markers: Path) -> None:
        """get_changes_for_handler returns rename changes."""
        detector = BreakingChangesDetector(sample_changelog_with_markers)
        changes = detector.get_changes_for_handler("tdd_enforcement")

        assert len(changes) == 1
        assert changes[0].handler_name == "tdd_enforcement"
        assert changes[0].change_type == ChangeType.HANDLER_RENAMED
        assert changes[0].new_name == "tdd"

    def test_get_changes_for_handler_not_found(self, sample_changelog_with_markers: Path) -> None:
        """get_changes_for_handler returns empty list for unknown handler."""
        detector = BreakingChangesDetector(sample_changelog_with_markers)
        changes = detector.get_changes_for_handler("unknown_handler")

        assert len(changes) == 0

    def test_get_changes_in_version_range(self, sample_changelog_with_markers: Path) -> None:
        """get_changes_in_version_range filters by version."""
        detector = BreakingChangesDetector(sample_changelog_with_markers)

        # Get changes in v2.13.0 only
        changes = detector.get_changes_in_version_range("2.13.0", "2.13.0")
        assert len(changes) == 2
        assert all(c.version == "2.13.0" for c in changes)

        # Get changes in v2.12.0 only
        changes = detector.get_changes_in_version_range("2.12.0", "2.12.0")
        assert len(changes) == 1
        assert changes[0].version == "2.12.0"

        # Get all changes from 2.12.0 to 2.13.0
        changes = detector.get_changes_in_version_range("2.12.0", "2.13.0")
        assert len(changes) == 3

    def test_marker_format_validation(self, tmp_path: Path) -> None:
        """Detector handles various marker formats correctly."""
        changelog = tmp_path / "CHANGELOG.md"
        changelog.write_text("""# Changelog

## [2.13.0] - 2026-02-17

### Removed
<!--BREAKING: handler:validate_sitemap:removed-->
- Handler removed

### Changed
<!--BREAKING: handler:old_name:renamed:new_name-->
- Handler renamed

### Added
<!--BREAKING: config:new_required_field:added-->
- Config change (not implemented yet, should be ignored)
""")

        detector = BreakingChangesDetector(changelog)
        changes = detector.get_breaking_changes()

        # Should parse removed and renamed, ignore config type
        assert len(changes) == 2
        types = {c.change_type for c in changes}
        assert ChangeType.HANDLER_REMOVED in types
        assert ChangeType.HANDLER_RENAMED in types

    def test_generate_warnings_for_removed_handlers(
        self, sample_changelog_with_markers: Path
    ) -> None:
        """generate_warnings creates user-friendly messages for removed handlers."""
        detector = BreakingChangesDetector(sample_changelog_with_markers)

        removed_handlers = ["validate_sitemap", "remind_validator"]
        warnings = detector.generate_warnings(removed_handlers=removed_handlers)

        assert len(warnings) == 2
        assert any("validate_sitemap" in w and "removed" in w.lower() for w in warnings)
        assert any("remind_validator" in w and "removed" in w.lower() for w in warnings)

    def test_generate_warnings_for_renamed_handlers(
        self, sample_changelog_with_markers: Path
    ) -> None:
        """generate_warnings suggests new names for renamed handlers."""
        detector = BreakingChangesDetector(sample_changelog_with_markers)

        renamed_handlers = {"tdd_enforcement": "tdd"}
        warnings = detector.generate_warnings(renamed_handlers=renamed_handlers)

        assert len(warnings) == 1
        assert "tdd_enforcement" in warnings[0]
        assert "renamed" in warnings[0].lower()
        assert "tdd" in warnings[0]

    def test_generate_warnings_no_matches(self, sample_changelog_with_markers: Path) -> None:
        """generate_warnings returns empty list when no matches found."""
        detector = BreakingChangesDetector(sample_changelog_with_markers)

        warnings = detector.generate_warnings(removed_handlers=["unknown_handler"])

        assert len(warnings) == 0

    def test_changelog_file_not_found(self, tmp_path: Path) -> None:
        """Detector raises error if CHANGELOG.md doesn't exist."""
        non_existent = tmp_path / "CHANGELOG.md"

        with pytest.raises(FileNotFoundError):
            BreakingChangesDetector(non_existent)

    def test_to_dict_serialization(self, sample_changelog_with_markers: Path) -> None:
        """Detector can serialize all changes to dict for JSON output."""
        detector = BreakingChangesDetector(sample_changelog_with_markers)
        changes = detector.get_breaking_changes()

        result = [c.to_dict() for c in changes]

        assert len(result) == 3
        assert all(isinstance(c, dict) for c in result)
        assert all("version" in c and "change_type" in c for c in result)
