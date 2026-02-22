"""Integration tests for config migration system.

Tests against real manifest files in CLAUDE/UPGRADES/config-changes/
and the real project config at .claude/hooks-daemon.yaml.

These tests validate:
- All 19 real manifests can be loaded without errors
- Known breaking versions are correctly flagged
- Advisory generation against the real project config
- CLI command `check-config-migrations` works end-to-end
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from claude_code_hooks_daemon.install.config_migrations import (
    generate_migration_advisory,
    list_known_versions,
    load_manifest,
    load_manifests_between,
)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).parent.parent.parent
_MANIFESTS_DIR = _PROJECT_ROOT / "CLAUDE" / "UPGRADES" / "config-changes"
_PROJECT_CONFIG = _PROJECT_ROOT / ".claude" / "hooks-daemon.yaml"
_PYTHON = sys.executable


# ---------------------------------------------------------------------------
# Real manifest loading tests
# ---------------------------------------------------------------------------


class TestRealManifestsExist:
    """Verify the real manifest files can all be loaded without errors."""

    def test_manifests_dir_exists(self) -> None:
        assert _MANIFESTS_DIR.exists(), f"Manifests directory missing: {_MANIFESTS_DIR}"

    def test_minimum_version_count(self) -> None:
        versions = list_known_versions(manifests_dir=_MANIFESTS_DIR)
        # We have 19 manifests from v2.2.0 to v2.15.2
        assert (
            len(versions) >= 19
        ), f"Expected at least 19 versions, got {len(versions)}: {versions}"

    def test_versions_are_sorted_correctly(self) -> None:
        versions = list_known_versions(manifests_dir=_MANIFESTS_DIR)
        # Numeric sort: 2.10.0 must come after 2.9.0
        parsed = [tuple(int(x) for x in v.split(".")) for v in versions]
        assert parsed == sorted(parsed), f"Versions not in numeric order: {versions}"

    def test_earliest_version_is_2_2_0(self) -> None:
        versions = list_known_versions(manifests_dir=_MANIFESTS_DIR)
        assert versions[0] == "2.2.0"

    def test_latest_version_is_at_least_2_15_2(self) -> None:
        versions = list_known_versions(manifests_dir=_MANIFESTS_DIR)
        last = tuple(int(x) for x in versions[-1].split("."))
        assert last >= (2, 15, 2)

    def test_all_manifests_parse_without_error(self) -> None:
        versions = list_known_versions(manifests_dir=_MANIFESTS_DIR)
        errors: list[str] = []
        for version in versions:
            try:
                manifest = load_manifest(version, manifests_dir=_MANIFESTS_DIR)
                if manifest is None:
                    errors.append(f"v{version}: load_manifest returned None")
                else:
                    assert manifest.version == version, f"v{version}: version mismatch"
            except Exception as exc:
                errors.append(f"v{version}: {exc}")
        assert not errors, "Manifest parse errors:\n" + "\n".join(errors)


# ---------------------------------------------------------------------------
# Known breaking versions
# ---------------------------------------------------------------------------


class TestKnownBreakingVersions:
    """Verify known breaking versions are correctly flagged in manifests."""

    @pytest.mark.parametrize("version", ["2.3.0", "2.9.0", "2.11.0"])
    def test_known_breaking_version(self, version: str) -> None:
        manifest = load_manifest(version, manifests_dir=_MANIFESTS_DIR)
        assert manifest is not None, f"v{version} manifest missing"
        assert manifest.breaking is True, f"v{version} should be marked breaking=True"

    @pytest.mark.parametrize(
        "version",
        [
            "2.2.0",
            "2.4.0",
            "2.5.0",
            "2.10.0",
            "2.12.0",
            "2.15.0",
        ],
    )
    def test_non_breaking_versions(self, version: str) -> None:
        manifest = load_manifest(version, manifests_dir=_MANIFESTS_DIR)
        if manifest is not None:
            assert manifest.breaking is False, f"v{version} unexpectedly marked breaking=True"


# ---------------------------------------------------------------------------
# Known config changes
# ---------------------------------------------------------------------------


class TestKnownConfigChanges:
    """Verify specific known config changes appear in the correct manifests."""

    def test_v2_9_0_has_qa_suppression_added(self) -> None:
        manifest = load_manifest("2.9.0", manifests_dir=_MANIFESTS_DIR)
        assert manifest is not None
        added_keys = [e.key for e in manifest.config_changes.added]
        assert any(
            "qa_suppression" in k for k in added_keys
        ), f"qa_suppression not in v2.9.0 added keys: {added_keys}"

    def test_v2_9_0_removes_old_per_language_handlers(self) -> None:
        manifest = load_manifest("2.9.0", manifests_dir=_MANIFESTS_DIR)
        assert manifest is not None
        removed_keys = [e.key for e in manifest.config_changes.removed]
        # eslint_disable was replaced by qa_suppression
        assert any(
            "eslint_disable" in k or "python_qa" in k for k in removed_keys
        ), f"Expected removed per-language handlers in v2.9.0: {removed_keys}"

    def test_v2_12_0_has_lint_on_edit_added(self) -> None:
        manifest = load_manifest("2.12.0", manifests_dir=_MANIFESTS_DIR)
        assert manifest is not None
        added_keys = [e.key for e in manifest.config_changes.added]
        assert any(
            "lint_on_edit" in k for k in added_keys
        ), f"lint_on_edit not in v2.12.0 added keys: {added_keys}"

    def test_v2_15_0_has_error_hiding_blocker(self) -> None:
        manifest = load_manifest("2.15.0", manifests_dir=_MANIFESTS_DIR)
        assert manifest is not None
        added_keys = [e.key for e in manifest.config_changes.added]
        assert any(
            "error_hiding" in k for k in added_keys
        ), f"error_hiding_blocker not in v2.15.0 added keys: {added_keys}"


# ---------------------------------------------------------------------------
# Advisory generation with real manifests
# ---------------------------------------------------------------------------


class TestAdvisoryWithRealManifests:
    """Verify advisory generation works correctly with real manifest data."""

    def test_full_range_advisory_generates_without_error(self, tmp_path: Path) -> None:
        """Advisory for full version range should not crash."""
        config = tmp_path / "hooks-daemon.yaml"
        config.write_text("handlers: {}\ndaemon: {}\n")
        advisory = generate_migration_advisory(
            from_version="2.2.0",
            to_version="2.15.2",
            user_config_path=config,
            manifests_dir=_MANIFESTS_DIR,
        )
        assert advisory.from_version == "2.2.0"
        assert advisory.to_version == "2.15.2"

    def test_empty_config_gets_suggestions_for_full_range(self, tmp_path: Path) -> None:
        """An empty config should receive suggestions for all added options."""
        config = tmp_path / "hooks-daemon.yaml"
        config.write_text("handlers: {}\ndaemon: {}\n")
        advisory = generate_migration_advisory(
            from_version="2.2.0",
            to_version="2.15.2",
            user_config_path=config,
            manifests_dir=_MANIFESTS_DIR,
        )
        # With empty config and full range, there should be many suggestions
        assert (
            len(advisory.suggestions) > 0
        ), "Expected suggestions for empty config over full range"

    def test_v2_9_0_range_suggests_qa_suppression_replacement(self, tmp_path: Path) -> None:
        """Config missing qa_suppression should get a suggestion after 2.8.0→2.9.0.

        eslint_disable was removed in v2.9.0 (not renamed), so it appears in the
        removed list, not renamed. Removed keys generate no warnings in the advisory —
        only renamed-old-key detections do. The relevant signal is the suggestion for
        qa_suppression (the new unified replacement).
        """
        old_config: dict = {
            "handlers": {
                "pre_tool_use": {
                    "eslint_disable": {"enabled": True},
                }
            }
        }
        config = tmp_path / "hooks-daemon.yaml"
        config.write_text(yaml.dump(old_config))
        advisory = generate_migration_advisory(
            from_version="2.8.0",
            to_version="2.9.0",
            user_config_path=config,
            manifests_dir=_MANIFESTS_DIR,
        )
        # qa_suppression is the new handler that replaces eslint_disable → should suggest it
        suggestion_keys = [s.key for s in advisory.suggestions]
        assert any(
            "qa_suppression" in k for k in suggestion_keys
        ), f"Expected suggestion for qa_suppression, got: {suggestion_keys}"

    def test_no_manifests_for_same_version_range(self) -> None:
        """Upgrading from/to same version should produce no manifests."""
        manifests = load_manifests_between("2.15.2", "2.15.2", manifests_dir=_MANIFESTS_DIR)
        assert manifests == []

    @pytest.mark.skipif(
        not _PROJECT_CONFIG.exists(),
        reason="Project config not found at .claude/hooks-daemon.yaml",
    )
    def test_real_project_config_advisory_does_not_crash(self) -> None:
        """Advisory against real project config should succeed without exceptions."""
        advisory = generate_migration_advisory(
            from_version="2.2.0",
            to_version="2.15.2",
            user_config_path=_PROJECT_CONFIG,
            manifests_dir=_MANIFESTS_DIR,
        )
        assert advisory is not None
        # The real project config has most handlers → verify it runs without error
        assert isinstance(advisory.suggestions, list)
        assert isinstance(advisory.warnings, list)


# ---------------------------------------------------------------------------
# CLI command integration test
# ---------------------------------------------------------------------------


def _run_check_config_cli(
    from_version: str,
    to_version: str,
    config_path: Path,
) -> subprocess.CompletedProcess[str]:
    """Run check-config-migrations CLI in a subprocess against the project root."""
    return subprocess.run(
        [
            _PYTHON,
            "-m",
            "claude_code_hooks_daemon.daemon.cli",
            "check-config-migrations",
            "--from",
            from_version,
            "--to",
            to_version,
            "--config",
            str(config_path),
        ],
        capture_output=True,
        text=True,
        cwd=str(_PROJECT_ROOT),
    )


class TestCheckConfigMigrationsCLI:
    """Verify the check-config-migrations CLI command works end-to-end."""

    def test_cli_exits_0_for_same_version(self, tmp_path: Path) -> None:
        config = tmp_path / "hooks-daemon.yaml"
        config.write_text("handlers: {}\ndaemon: {}\n")
        result = _run_check_config_cli("2.15.2", "2.15.2", config)
        assert result.returncode == 0, f"stderr: {result.stderr}"

    def test_cli_exits_1_when_suggestions_exist(self, tmp_path: Path) -> None:
        """Empty config upgrading from 2.8.0 to 2.9.0 should produce suggestions."""
        config = tmp_path / "hooks-daemon.yaml"
        config.write_text("handlers: {}\ndaemon: {}\n")
        result = _run_check_config_cli("2.8.0", "2.9.0", config)
        assert result.returncode == 1, (
            f"Expected exit 1 (suggestions), got {result.returncode}. "
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_cli_output_contains_version_range_header(self, tmp_path: Path) -> None:
        config = tmp_path / "hooks-daemon.yaml"
        config.write_text("handlers: {}\ndaemon: {}\n")
        result = _run_check_config_cli("2.8.0", "2.9.0", config)
        combined = result.stdout + result.stderr
        assert (
            "2.8.0" in combined and "2.9.0" in combined
        ), f"Version range not in output: {combined}"

    def test_cli_output_contains_suggestion_for_new_handler(self, tmp_path: Path) -> None:
        """Output should name the new option added in the version range."""
        config = tmp_path / "hooks-daemon.yaml"
        config.write_text("handlers: {}\ndaemon: {}\n")
        result = _run_check_config_cli("2.8.0", "2.9.0", config)
        assert (
            "qa_suppression" in result.stdout or "qa_suppression" in result.stderr
        ), f"qa_suppression not found in output:\n{result.stdout}\n{result.stderr}"

    def test_cli_does_not_crash_for_late_patch_range(self, tmp_path: Path) -> None:
        """CLI should exit cleanly for any valid version range."""
        config = tmp_path / "hooks-daemon.yaml"
        config.write_text("handlers: {}\ndaemon: {}\n")
        result = _run_check_config_cli("2.15.1", "2.15.2", config)
        # Exit 0 if no suggestions, 1 if suggestions exist — both are valid here
        assert result.returncode in (
            0,
            1,
        ), f"CLI crashed with code {result.returncode}:\n{result.stderr}"

    def test_cli_invalid_version_format_exits_nonzero(self, tmp_path: Path) -> None:
        """Passing a non-version string should produce a non-zero exit code."""
        config = tmp_path / "hooks-daemon.yaml"
        config.write_text("handlers: {}\n")
        result = subprocess.run(
            [
                _PYTHON,
                "-m",
                "claude_code_hooks_daemon.daemon.cli",
                "check-config-migrations",
                "--from",
                "not-a-version",
                "--to",
                "2.15.2",
                "--config",
                str(config),
            ],
            capture_output=True,
            text=True,
            cwd=str(_PROJECT_ROOT),
        )
        assert (
            result.returncode != 0
        ), f"Expected non-zero exit for invalid version, got 0. stdout: {result.stdout}"

    @pytest.mark.skipif(
        not _PROJECT_CONFIG.exists(),
        reason="Project config not found at .claude/hooks-daemon.yaml",
    )
    def test_cli_with_real_project_config(self) -> None:
        """CLI should succeed with real project config (may have exit 0 or 1)."""
        result = _run_check_config_cli("2.2.0", "2.15.2", _PROJECT_CONFIG)
        assert result.returncode in (
            0,
            1,
        ), f"CLI failed with exit {result.returncode}:\n{result.stderr}"
        # Output should always include the version range header
        combined = result.stdout + result.stderr
        assert "2.2.0" in combined and "2.15.2" in combined
