"""Tests for the truth-changes loader, formatter, and run-function (Plan 00118).

Truth-changes record statements that were true about working in a project but
became false in a release (replaced by a new truth, or retired). They are loaded
over a version range and reconciled against the project's own docs by the LLM.

Mirrors the proven config_migrations range-loader pattern, minus the user-config
comparison (truth-changes are not compared against anything — they are guidance).
"""

from pathlib import Path

import pytest

from claude_code_hooks_daemon.install.truth_changes import (
    TruthChange,
    TruthChangeManifest,
    format_truth_changes_for_llm,
    list_known_truth_change_versions,
    load_truth_changes_between,
    run_check_truth_changes,
)

# ---------------------------------------------------------------------------
# Fixtures — a temp truth-changes directory with a few version files
# ---------------------------------------------------------------------------


def _write_manifest(directory: Path, version: str, body: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"v{version}.yaml").write_text(body)


@pytest.fixture
def truth_dir(tmp_path: Path) -> Path:
    """A truth-changes dir with v3.16.0 (replacement) and v3.17.0 (removal)."""
    d = tmp_path / "truth-changes"
    _write_manifest(
        d,
        "3.16.0",
        "version: '3.16.0'\n"
        "truth_changes:\n"
        "  - was: Scan the CLAUDE/Plan folder for the highest NNNNN prefix.\n"
        "    now: Read git config --local hooksdaemon.latestPlanNumber and add one.\n",
    )
    _write_manifest(
        d,
        "3.17.0",
        "version: '3.17.0'\n"
        "truth_changes:\n"
        "  - was: The workflow-state-across-compaction subsystem restores state.\n"
        "    now: ~\n",
    )
    # A non-version file that must be ignored by the glob loader
    (d / "README.md").write_text("# docs")
    (d / "vnot-a-version.yaml").write_text("version: 'x'\ntruth_changes: []\n")
    return d


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


class TestTruthChangeManifestParsing:
    def test_from_dict_parses_replacement_entry(self) -> None:
        manifest = TruthChangeManifest.from_dict(
            {
                "version": "3.16.0",
                "truth_changes": [{"was": "old truth", "now": "new truth"}],
            }
        )
        assert manifest.version == "3.16.0"
        assert manifest.changes == [TruthChange(was="old truth", now="new truth")]

    def test_from_dict_treats_null_now_as_removal(self) -> None:
        manifest = TruthChangeManifest.from_dict(
            {"version": "3.17.0", "truth_changes": [{"was": "retired", "now": None}]}
        )
        assert manifest.changes[0].now is None
        assert manifest.changes[0].is_removal is True

    def test_from_dict_treats_missing_now_as_removal(self) -> None:
        manifest = TruthChangeManifest.from_dict(
            {"version": "3.17.0", "truth_changes": [{"was": "retired"}]}
        )
        assert manifest.changes[0].is_removal is True

    def test_replacement_entry_is_not_removal(self) -> None:
        change = TruthChange(was="x", now="y")
        assert change.is_removal is False

    def test_from_dict_handles_empty_truth_changes(self) -> None:
        manifest = TruthChangeManifest.from_dict({"version": "3.18.0", "truth_changes": []})
        assert manifest.changes == []

    def test_from_dict_missing_version_raises(self) -> None:
        with pytest.raises(KeyError):
            TruthChangeManifest.from_dict({"truth_changes": []})

    def test_from_dict_missing_was_raises(self) -> None:
        with pytest.raises(KeyError):
            TruthChangeManifest.from_dict(
                {"version": "3.16.0", "truth_changes": [{"now": "y"}]}
            )


# ---------------------------------------------------------------------------
# Range loading
# ---------------------------------------------------------------------------


class TestLoadTruthChangesBetween:
    def test_loads_inclusive_to_exclusive_from(self, truth_dir: Path) -> None:
        # (3.15.0, 3.17.0] => both 3.16.0 and 3.17.0
        manifests = load_truth_changes_between("3.15.0", "3.17.0", truth_changes_dir=truth_dir)
        assert [m.version for m in manifests] == ["3.16.0", "3.17.0"]

    def test_excludes_from_version_itself(self, truth_dir: Path) -> None:
        # (3.16.0, 3.17.0] => only 3.17.0 (3.16.0 excluded)
        manifests = load_truth_changes_between("3.16.0", "3.17.0", truth_changes_dir=truth_dir)
        assert [m.version for m in manifests] == ["3.17.0"]

    def test_includes_to_version(self, truth_dir: Path) -> None:
        manifests = load_truth_changes_between("3.15.0", "3.16.0", truth_changes_dir=truth_dir)
        assert [m.version for m in manifests] == ["3.16.0"]

    def test_equal_versions_returns_empty(self, truth_dir: Path) -> None:
        assert load_truth_changes_between("3.16.0", "3.16.0", truth_changes_dir=truth_dir) == []

    def test_from_greater_than_to_raises(self, truth_dir: Path) -> None:
        with pytest.raises(ValueError):
            load_truth_changes_between("3.18.0", "3.16.0", truth_changes_dir=truth_dir)

    def test_missing_dir_returns_empty(self, tmp_path: Path) -> None:
        missing = tmp_path / "nope"
        assert load_truth_changes_between("3.0.0", "9.9.9", truth_changes_dir=missing) == []

    def test_ignores_non_version_yaml_files(self, truth_dir: Path) -> None:
        manifests = load_truth_changes_between("0.0.0", "9.9.9", truth_changes_dir=truth_dir)
        versions = [m.version for m in manifests]
        assert "x" not in versions
        assert versions == ["3.16.0", "3.17.0"]

    def test_results_sorted_oldest_first(self, truth_dir: Path) -> None:
        manifests = load_truth_changes_between("0.0.0", "9.9.9", truth_changes_dir=truth_dir)
        assert [m.version for m in manifests] == ["3.16.0", "3.17.0"]


class TestListKnownVersions:
    def test_lists_only_valid_versions_sorted(self, truth_dir: Path) -> None:
        assert list_known_truth_change_versions(truth_changes_dir=truth_dir) == [
            "3.16.0",
            "3.17.0",
        ]

    def test_missing_dir_returns_empty(self, tmp_path: Path) -> None:
        assert list_known_truth_change_versions(truth_changes_dir=tmp_path / "x") == []


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


class TestFormatTruthChangesForLlm:
    def test_no_changes_message(self) -> None:
        text = format_truth_changes_for_llm([], "3.16.0", "3.16.0")
        assert "no" in text.lower()
        assert "3.16.0" in text

    def test_replacement_renders_was_and_now(self, truth_dir: Path) -> None:
        manifests = load_truth_changes_between("3.15.0", "3.16.0", truth_changes_dir=truth_dir)
        text = format_truth_changes_for_llm(manifests, "3.15.0", "3.16.0")
        assert "Scan the CLAUDE/Plan folder" in text
        assert "hooksdaemon.latestPlanNumber" in text
        assert "3.16.0" in text

    def test_removal_entry_signals_remove_all_reference(self, truth_dir: Path) -> None:
        manifests = load_truth_changes_between("3.16.0", "3.17.0", truth_changes_dir=truth_dir)
        text = format_truth_changes_for_llm(manifests, "3.16.0", "3.17.0")
        assert "workflow-state-across-compaction" in text
        assert "remove all reference" in text.lower()


# ---------------------------------------------------------------------------
# Run-function (CLI entrypoint)
# ---------------------------------------------------------------------------


class TestRunCheckTruthChanges:
    def test_text_output_has_changes_flag_and_text(self, truth_dir: Path) -> None:
        result = run_check_truth_changes(
            "3.15.0", "3.17.0", output_format="text", truth_changes_dir=truth_dir
        )
        assert result["has_changes"] is True
        assert result["from_version"] == "3.15.0"
        assert result["to_version"] == "3.17.0"
        assert "hooksdaemon.latestPlanNumber" in result["text"]
        assert len(result["changes"]) == 2

    def test_json_shape_serialises_entries(self, truth_dir: Path) -> None:
        result = run_check_truth_changes(
            "3.15.0", "3.16.0", output_format="json", truth_changes_dir=truth_dir
        )
        assert result["changes"] == [
            {
                "version": "3.16.0",
                "was": "Scan the CLAUDE/Plan folder for the highest NNNNN prefix.",
                "now": "Read git config --local hooksdaemon.latestPlanNumber and add one.",
                "is_removal": False,
            }
        ]

    def test_no_changes_sets_flag_false(self, truth_dir: Path) -> None:
        result = run_check_truth_changes(
            "3.16.0", "3.16.0", output_format="text", truth_changes_dir=truth_dir
        )
        assert result["has_changes"] is False
        assert result["changes"] == []

    def test_invalid_range_raises_value_error(self, truth_dir: Path) -> None:
        with pytest.raises(ValueError):
            run_check_truth_changes(
                "3.18.0", "3.16.0", output_format="text", truth_changes_dir=truth_dir
            )
