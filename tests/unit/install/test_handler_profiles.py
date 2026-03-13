"""Tests for handler profile application."""

import textwrap
from pathlib import Path

import pytest

from claude_code_hooks_daemon.install.handler_profiles import (
    PROFILES,
    apply_profile,
    get_profile_names,
)


class TestProfileDefinitions:
    """Tests for profile data definitions."""

    def test_three_profiles_defined(self) -> None:
        """Three profiles: minimal, recommended, strict."""
        assert get_profile_names() == ["minimal", "recommended", "strict"]

    def test_minimal_enables_nothing(self) -> None:
        """Minimal profile enables no additional handlers (base config as-is)."""
        assert PROFILES["minimal"] == []

    def test_recommended_includes_quality_handlers(self) -> None:
        """Recommended profile enables code quality handlers."""
        rec = PROFILES["recommended"]
        assert "qa_suppression" in rec
        assert "tdd_enforcement" in rec
        assert "lint_on_edit" in rec

    def test_recommended_includes_plan_handlers(self) -> None:
        """Recommended profile enables plan workflow handlers."""
        rec = PROFILES["recommended"]
        for handler in [
            "plan_number_helper",
            "validate_plan_number",
            "plan_time_estimates",
            "plan_workflow",
            "plan_completion_advisor",
            "markdown_organization",
        ]:
            assert handler in rec, f"Missing plan handler: {handler}"

    def test_strict_is_superset_of_recommended(self) -> None:
        """Strict profile includes all recommended handlers plus more."""
        rec_set = set(PROFILES["recommended"])
        strict_set = set(PROFILES["strict"])
        assert rec_set.issubset(strict_set)
        assert len(strict_set) > len(rec_set)


class TestApplyProfile:
    """Tests for apply_profile() yaml modification."""

    @pytest.fixture
    def sample_yaml(self, tmp_path: Path) -> Path:
        """Create a sample hooks-daemon.yaml for testing."""
        content = textwrap.dedent("""\
            handlers:
              pre_tool_use:
                destructive_git:       # Blocks git reset --hard
                  enabled: true
                  priority: 10

                qa_suppression:        # Blocks QA suppression comments
                  enabled: false       # Enable for strict code quality
                  priority: 30

                tdd_enforcement:       # Enforces test-first development
                  enabled: false       # Enable for strict TDD
                  priority: 32

                plan_number_helper:    # Provides correct next plan number
                  enabled: false       # Enable when using CLAUDE/Plan/
                  priority: 33

              post_tool_use:
                lint_on_edit:              # Language-aware lint validation
                  enabled: false           # Enable for automatic lint
                  priority: 25

              stop:
                task_completion_checker:  # Checks for task completion
                  enabled: false           # Enable if using task management
                  priority: 20
        """)
        config_path = tmp_path / "hooks-daemon.yaml"
        config_path.write_text(content)
        return config_path

    def test_minimal_changes_nothing(self, sample_yaml: Path) -> None:
        """Minimal profile leaves config unchanged."""
        original = sample_yaml.read_text()
        apply_profile(sample_yaml, "minimal")
        assert sample_yaml.read_text() == original

    def test_recommended_enables_handlers(self, sample_yaml: Path) -> None:
        """Recommended profile enables quality and plan handlers."""
        apply_profile(sample_yaml, "recommended")
        content = sample_yaml.read_text()
        # qa_suppression should now be enabled
        assert "qa_suppression:" in content
        # Find the enabled line after qa_suppression
        lines = content.split("\n")
        for i, line in enumerate(lines):
            if "qa_suppression:" in line:
                # Next line with 'enabled' should be true
                for j in range(i + 1, min(i + 3, len(lines))):
                    if "enabled:" in lines[j]:
                        assert "true" in lines[j]
                        break
                break

    def test_preserves_comments(self, sample_yaml: Path) -> None:
        """Profile application preserves yaml comments."""
        apply_profile(sample_yaml, "recommended")
        content = sample_yaml.read_text()
        assert "# Blocks QA suppression comments" in content
        assert "# Blocks git reset --hard" in content

    def test_preserves_already_enabled(self, sample_yaml: Path) -> None:
        """Already-enabled handlers stay enabled."""
        apply_profile(sample_yaml, "recommended")
        content = sample_yaml.read_text()
        lines = content.split("\n")
        for i, line in enumerate(lines):
            if "destructive_git:" in line:
                for j in range(i + 1, min(i + 3, len(lines))):
                    if "enabled:" in lines[j]:
                        assert "true" in lines[j]
                        break
                break

    def test_invalid_profile_raises(self, sample_yaml: Path) -> None:
        """Invalid profile name raises ValueError."""
        with pytest.raises(ValueError, match="Unknown handler profile"):
            apply_profile(sample_yaml, "nonexistent")

    def test_strict_enables_all(self, sample_yaml: Path) -> None:
        """Strict profile enables all handlers in the file."""
        apply_profile(sample_yaml, "strict")
        content = sample_yaml.read_text()
        # Every 'enabled:' line should be true
        for line in content.split("\n"):
            if "enabled:" in line and not line.strip().startswith("#"):
                assert "true" in line, f"Handler not enabled: {line.strip()}"

    def test_returns_count_of_changes(self, sample_yaml: Path) -> None:
        """apply_profile returns the number of handlers toggled."""
        count = apply_profile(sample_yaml, "recommended")
        # qa_suppression, tdd_enforcement, plan_number_helper, lint_on_edit,
        # task_completion_checker = 5 handlers toggled in sample
        assert count >= 4
