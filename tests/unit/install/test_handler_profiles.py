"""Tests for handler profile application."""

import textwrap
from pathlib import Path

import pytest
import yaml

from claude_code_hooks_daemon.install.config_differ import ConfigDiffer
from claude_code_hooks_daemon.install.config_merger import ConfigMerger
from claude_code_hooks_daemon.install.handler_profiles import (
    PROFILES,
    all_profile_handler_names,
    apply_profile,
    config_handler_names,
    get_profile_names,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
SHIPPED_EXAMPLE_CONFIG = REPO_ROOT / ".claude" / "hooks-daemon.yaml.example"


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


class TestProfileSeedSurvivesUpgrade:
    """A profile is a one-shot SEED of the user's config at fresh-install time.

    After ``apply_profile`` flips ``enabled: false`` to ``enabled: true`` in the
    yaml, that yaml is the single source of truth thereafter. Profiles are NOT
    re-applied on upgrade (the upgrade path has zero profile references by
    design). These tests prove the seed survives the production upgrade
    config-merge: a profile-enabled handler stays enabled even though the new
    version's example default still ships it ``enabled: false``.
    """

    @pytest.fixture
    def seeded_yaml(self, tmp_path: Path) -> Path:
        """A yaml seeded by the 'recommended' profile at install time."""
        content = textwrap.dedent("""\
            handlers:
              pre_tool_use:
                qa_suppression:        # Blocks QA suppression comments
                  enabled: false       # Enable for strict code quality
                  priority: 30
                tdd_enforcement:       # Enforces test-first development
                  enabled: false       # Enable for strict TDD
                  priority: 35
        """)
        config_path = tmp_path / "hooks-daemon.yaml"
        config_path.write_text(content)
        apply_profile(config_path, "recommended")
        return config_path

    def test_seeded_handlers_preserved_through_upgrade_merge(self, seeded_yaml: Path) -> None:
        """Profile-seeded enabled:true survives upgrade against a disabled default.

        Simulates the upgrade path: diff the user's seeded config against the
        NEW version's default (which still ships the handler disabled), then
        merge. The seed must win — the merged config keeps enabled:true.
        """
        user_config = yaml.safe_load(seeded_yaml.read_text())

        # Next version's example default still ships these handlers disabled
        # (the example never carries a profile's choices).
        new_default_config = {
            "handlers": {
                "pre_tool_use": {
                    "qa_suppression": {"enabled": False, "priority": 30},
                    "tdd_enforcement": {"enabled": False, "priority": 35},
                }
            }
        }

        diff = ConfigDiffer().diff(user_config, new_default_config)
        result = ConfigMerger().merge(new_default_config, diff)

        merged_pre = result.merged_config["handlers"]["pre_tool_use"]
        assert merged_pre["qa_suppression"]["enabled"] is True
        assert merged_pre["tdd_enforcement"]["enabled"] is True

    def test_seed_is_detected_as_user_customization(self, seeded_yaml: Path) -> None:
        """The seed registers as a changed_option so the merge preserves it."""
        user_config = yaml.safe_load(seeded_yaml.read_text())
        new_default_config = {
            "handlers": {
                "pre_tool_use": {
                    "qa_suppression": {"enabled": False, "priority": 30},
                    "tdd_enforcement": {"enabled": False, "priority": 35},
                }
            }
        }

        diff = ConfigDiffer().diff(user_config, new_default_config)

        pre_changes = diff.changed_options.get("pre_tool_use", {})
        assert "qa_suppression" in pre_changes
        assert "tdd_enforcement" in pre_changes


class TestProfileHandlerListIntegrity:
    """F-PROFLIST: the hardcoded profile lists must stay in sync with config.

    A handler name that exists in NO config silently no-ops (regex never
    matches), so a rename/typo would quietly drop a handler from a profile.
    """

    def test_every_profile_handler_exists_in_shipped_example(self) -> None:
        """Each profile handler name MUST be a key in the shipped example config."""
        assert (
            SHIPPED_EXAMPLE_CONFIG.is_file()
        ), f"shipped example config missing: {SHIPPED_EXAMPLE_CONFIG}"
        declared = config_handler_names(SHIPPED_EXAMPLE_CONFIG.read_text())
        unknown = sorted(all_profile_handler_names() - declared)
        assert not unknown, (
            "profile lists reference handlers absent from the shipped example "
            f"config (rename/typo?): {unknown}"
        )

    def test_config_handler_names_extracts_keys(self) -> None:
        """config_handler_names returns handler keys across event types."""
        content = textwrap.dedent("""\
            handlers:
              pre_tool_use:
                destructive_git:
                  enabled: true
              stop:
                task_completion_checker:
                  enabled: false
        """)
        assert config_handler_names(content) == {
            "destructive_git",
            "task_completion_checker",
        }

    def test_config_handler_names_handles_malformed(self) -> None:
        """Non-mapping / handler-less content yields an empty set, not a crash."""
        assert config_handler_names("- just\n- a\n- list\n") == set()
        assert config_handler_names("daemon:\n  log_level: INFO\n") == set()

    def test_apply_profile_warns_on_handler_absent_from_config(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A profile handler not declared in the config logs a warning naming it."""
        content = textwrap.dedent("""\
            handlers:
              pre_tool_use:
                qa_suppression:
                  enabled: false
        """)
        config_path = tmp_path / "hooks-daemon.yaml"
        config_path.write_text(content)

        with caplog.at_level("WARNING"):
            apply_profile(config_path, "recommended")

        # tdd_enforcement is in 'recommended' but absent from this config.
        assert any(
            "tdd_enforcement" in rec.message for rec in caplog.records
        ), f"expected a warning naming the absent handler, got: {caplog.records!r}"
