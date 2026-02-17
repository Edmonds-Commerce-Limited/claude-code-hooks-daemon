"""Tests for upgrade_compatibility module."""

from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.install.upgrade_compatibility import (
    CompatibilityChecker,
    CompatibilityReport,
    CompatibilityStatus,
    HandlerCompatibility,
)


@pytest.fixture
def sample_user_config() -> dict[str, Any]:
    """Sample user config with various handlers."""
    return {
        "version": "1.0",
        "daemon": {"idle_timeout_seconds": 600, "log_level": "INFO"},
        "handlers": {
            "pre_tool_use": {
                "destructive_git": {"enabled": True, "priority": 10},
                "validate_sitemap": {"enabled": True, "priority": 50},  # Removed in v2.11
                "tdd_enforcement": {"enabled": True, "priority": 30},  # Renamed to "tdd" in v2.12
                "unknown_handler": {"enabled": True, "priority": 40},  # Never existed
            },
            "post_tool_use": {
                "git_context": {"enabled": True, "priority": 50},
            },
        },
    }


@pytest.fixture
def sample_changelog(tmp_path: Path) -> Path:
    """Create sample CHANGELOG.md with breaking changes."""
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("""# Changelog

## [2.12.0] - 2026-02-12

### Changed
<!--BREAKING: handler:tdd_enforcement:renamed:tdd-->
- TDD handler renamed

## [2.11.0] - 2026-02-10

### Removed
<!--BREAKING: handler:validate_sitemap:removed-->
- validate_sitemap handler removed
""")
    return changelog


class TestHandlerCompatibility:
    """Tests for HandlerCompatibility dataclass."""

    def test_handler_compatibility_initialization(self) -> None:
        """HandlerCompatibility can be initialized with all fields."""
        compat = HandlerCompatibility(
            handler_name="destructive_git",
            event_type="pre_tool_use",
            status=CompatibilityStatus.COMPATIBLE,
            message="Handler is compatible",
        )

        assert compat.handler_name == "destructive_git"
        assert compat.event_type == "pre_tool_use"
        assert compat.status == CompatibilityStatus.COMPATIBLE
        assert compat.message == "Handler is compatible"

    def test_handler_compatibility_to_dict(self) -> None:
        """HandlerCompatibility can be serialized to dict."""
        compat = HandlerCompatibility(
            handler_name="validate_sitemap",
            event_type="pre_tool_use",
            status=CompatibilityStatus.REMOVED,
            message="Handler was removed",
            suggested_action="Remove from config",
        )

        result = compat.to_dict()

        assert result["handler_name"] == "validate_sitemap"
        assert result["status"] == "removed"
        assert result["message"] == "Handler was removed"
        assert result["suggested_action"] == "Remove from config"


class TestCompatibilityReport:
    """Tests for CompatibilityReport dataclass."""

    def test_compatibility_report_initialization(self) -> None:
        """CompatibilityReport can be initialized with handler checks."""
        handlers = [
            HandlerCompatibility(
                "destructive_git", "pre_tool_use", CompatibilityStatus.COMPATIBLE, "OK"
            ),
            HandlerCompatibility(
                "validate_sitemap",
                "pre_tool_use",
                CompatibilityStatus.REMOVED,
                "Removed",
            ),
        ]

        report = CompatibilityReport(
            handlers=handlers,
            current_version="2.10.0",
            target_version="2.13.0",
        )

        assert len(report.handlers) == 2
        assert report.current_version == "2.10.0"
        assert report.target_version == "2.13.0"

    def test_compatibility_report_is_compatible(self) -> None:
        """Report correctly identifies overall compatibility status."""
        # All compatible
        handlers_ok = [
            HandlerCompatibility("handler1", "pre_tool_use", CompatibilityStatus.COMPATIBLE, "OK"),
            HandlerCompatibility("handler2", "pre_tool_use", CompatibilityStatus.COMPATIBLE, "OK"),
        ]
        report_ok = CompatibilityReport(handlers_ok, "2.10.0", "2.13.0")
        assert report_ok.is_compatible is True

        # Has incompatible handlers
        handlers_bad = [
            HandlerCompatibility("handler1", "pre_tool_use", CompatibilityStatus.COMPATIBLE, "OK"),
            HandlerCompatibility(
                "handler2", "pre_tool_use", CompatibilityStatus.REMOVED, "Removed"
            ),
        ]
        report_bad = CompatibilityReport(handlers_bad, "2.10.0", "2.13.0")
        assert report_bad.is_compatible is False

    def test_compatibility_report_categorization(self) -> None:
        """Report correctly categorizes handlers by status."""
        handlers = [
            HandlerCompatibility("handler1", "pre_tool_use", CompatibilityStatus.COMPATIBLE, "OK"),
            HandlerCompatibility(
                "handler2", "pre_tool_use", CompatibilityStatus.REMOVED, "Removed"
            ),
            HandlerCompatibility(
                "handler3", "pre_tool_use", CompatibilityStatus.RENAMED, "Renamed"
            ),
            HandlerCompatibility(
                "handler4", "pre_tool_use", CompatibilityStatus.WARNING, "Warning"
            ),
        ]

        report = CompatibilityReport(handlers, "2.10.0", "2.13.0")

        compatible = report.get_handlers_by_status(CompatibilityStatus.COMPATIBLE)
        assert len(compatible) == 1
        assert compatible[0].handler_name == "handler1"

        removed = report.get_handlers_by_status(CompatibilityStatus.REMOVED)
        assert len(removed) == 1
        assert removed[0].handler_name == "handler2"

        renamed = report.get_handlers_by_status(CompatibilityStatus.RENAMED)
        assert len(renamed) == 1
        assert renamed[0].handler_name == "handler3"

    def test_compatibility_report_to_dict(self) -> None:
        """Report can be serialized to dict for JSON output."""
        handlers = [
            HandlerCompatibility("handler1", "pre_tool_use", CompatibilityStatus.COMPATIBLE, "OK"),
        ]
        report = CompatibilityReport(handlers, "2.10.0", "2.13.0")

        result = report.to_dict()

        assert result["current_version"] == "2.10.0"
        assert result["target_version"] == "2.13.0"
        assert result["is_compatible"] is True
        assert len(result["handlers"]) == 1


class TestCompatibilityChecker:
    """Tests for CompatibilityChecker."""

    def test_check_compatibility_all_compatible(self, sample_changelog: Path) -> None:
        """Checker reports all compatible when handlers exist in target."""
        user_config = {
            "version": "1.0",
            "daemon": {"idle_timeout_seconds": 600, "log_level": "INFO"},
            "handlers": {
                "pre_tool_use": {
                    "destructive_git": {"enabled": True, "priority": 10},
                },
            },
        }

        checker = CompatibilityChecker(
            changelog_path=sample_changelog,
            current_version="2.10.0",
            target_version="2.13.0",
        )

        report = checker.check_compatibility(user_config)

        assert report.is_compatible is True
        assert len(report.handlers) == 1
        assert report.handlers[0].status == CompatibilityStatus.COMPATIBLE

    def test_check_compatibility_removed_handler(self, sample_changelog: Path) -> None:
        """Checker detects removed handlers from CHANGELOG."""
        user_config = {
            "version": "1.0",
            "daemon": {"idle_timeout_seconds": 600, "log_level": "INFO"},
            "handlers": {
                "pre_tool_use": {
                    "validate_sitemap": {"enabled": True, "priority": 50},
                },
            },
        }

        checker = CompatibilityChecker(
            changelog_path=sample_changelog,
            current_version="2.10.0",
            target_version="2.13.0",
        )

        report = checker.check_compatibility(user_config)

        assert report.is_compatible is False
        assert len(report.handlers) == 1
        assert report.handlers[0].status == CompatibilityStatus.REMOVED
        assert report.handlers[0].handler_name == "validate_sitemap"
        assert "removed" in report.handlers[0].message.lower()

    def test_check_compatibility_renamed_handler(self, sample_changelog: Path) -> None:
        """Checker detects renamed handlers from CHANGELOG."""
        user_config = {
            "version": "1.0",
            "daemon": {"idle_timeout_seconds": 600, "log_level": "INFO"},
            "handlers": {
                "pre_tool_use": {
                    "tdd_enforcement": {"enabled": True, "priority": 30},
                },
            },
        }

        checker = CompatibilityChecker(
            changelog_path=sample_changelog,
            current_version="2.10.0",
            target_version="2.13.0",
        )

        report = checker.check_compatibility(user_config)

        assert report.is_compatible is False
        assert len(report.handlers) == 1
        assert report.handlers[0].status == CompatibilityStatus.RENAMED
        assert report.handlers[0].handler_name == "tdd_enforcement"
        assert "tdd" in report.handlers[0].message  # Should mention new name

    def test_check_compatibility_multiple_issues(
        self, sample_user_config: dict[str, Any], sample_changelog: Path
    ) -> None:
        """Checker handles config with multiple compatibility issues."""
        checker = CompatibilityChecker(
            changelog_path=sample_changelog,
            current_version="2.10.0",
            target_version="2.13.0",
        )

        report = checker.check_compatibility(sample_user_config)

        assert report.is_compatible is False

        # Should have 5 handlers checked (4 from pre_tool_use + 1 from post_tool_use)
        assert len(report.handlers) == 5

        # destructive_git should be compatible
        destructive = [h for h in report.handlers if h.handler_name == "destructive_git"]
        assert len(destructive) == 1
        assert destructive[0].status == CompatibilityStatus.COMPATIBLE

        # validate_sitemap should be removed
        validate = [h for h in report.handlers if h.handler_name == "validate_sitemap"]
        assert len(validate) == 1
        assert validate[0].status == CompatibilityStatus.REMOVED

        # tdd_enforcement should be renamed
        tdd = [h for h in report.handlers if h.handler_name == "tdd_enforcement"]
        assert len(tdd) == 1
        assert tdd[0].status == CompatibilityStatus.RENAMED

        # unknown_handler should be warning (typo or unknown)
        unknown = [h for h in report.handlers if h.handler_name == "unknown_handler"]
        assert len(unknown) == 1
        assert unknown[0].status == CompatibilityStatus.WARNING

    def test_generate_user_friendly_report(
        self, sample_user_config: dict[str, Any], sample_changelog: Path
    ) -> None:
        """Checker generates human-readable report text."""
        checker = CompatibilityChecker(
            changelog_path=sample_changelog,
            current_version="2.10.0",
            target_version="2.13.0",
        )

        report = checker.check_compatibility(sample_user_config)
        report_text = checker.generate_user_friendly_report(report)

        # Should contain version info
        assert "2.10.0" in report_text
        assert "2.13.0" in report_text

        # Should mention incompatible handlers
        assert "validate_sitemap" in report_text
        assert "tdd_enforcement" in report_text

        # Should contain upgrade guide suggestions
        assert "CLAUDE/UPGRADES" in report_text or "upgrade guide" in report_text.lower()

    def test_suggest_upgrade_guides(self, sample_changelog: Path, tmp_path: Path) -> None:
        """Checker suggests relevant upgrade guides for version range."""
        # Create mock upgrade guides in daemon_dir/CLAUDE/UPGRADES/v2/
        daemon_dir = tmp_path / "daemon"
        upgrades_dir = daemon_dir / "CLAUDE" / "UPGRADES" / "v2"
        upgrades_dir.mkdir(parents=True)

        (upgrades_dir / "v2.10-to-v2.11").mkdir()
        (upgrades_dir / "v2.10-to-v2.11" / "v2.10-to-v2.11.md").touch()

        (upgrades_dir / "v2.11-to-v2.12").mkdir()
        (upgrades_dir / "v2.11-to-v2.12" / "v2.11-to-v2.12.md").touch()

        (upgrades_dir / "v2.12-to-v2.13").mkdir()
        (upgrades_dir / "v2.12-to-v2.13" / "v2.12-to-v2.13.md").touch()

        checker = CompatibilityChecker(
            changelog_path=sample_changelog,
            current_version="2.10.0",
            target_version="2.13.0",
        )

        guides = checker.suggest_upgrade_guides(daemon_dir)

        # Should suggest all intermediate guides
        assert len(guides) == 3
        assert any("v2.10-to-v2.11" in str(g) for g in guides)
        assert any("v2.11-to-v2.12" in str(g) for g in guides)
        assert any("v2.12-to-v2.13" in str(g) for g in guides)

    def test_empty_config_handlers(self, sample_changelog: Path) -> None:
        """Checker handles config with no handlers gracefully."""
        user_config = {
            "version": "1.0",
            "daemon": {"idle_timeout_seconds": 600, "log_level": "INFO"},
            "handlers": {},
        }

        checker = CompatibilityChecker(
            changelog_path=sample_changelog,
            current_version="2.10.0",
            target_version="2.13.0",
        )

        report = checker.check_compatibility(user_config)

        assert report.is_compatible is True
        assert len(report.handlers) == 0
