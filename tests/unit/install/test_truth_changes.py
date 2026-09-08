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
    SurfacedTruthChange,
    TruthChange,
    TruthChangeManifest,
    collapse_superseded,
    format_truth_changes_for_llm,
    list_known_truth_change_versions,
    load_truth_changes_between,
    run_check_truth_changes,
)

_REAL_TRUTH_CHANGES_DIR = (
    Path(__file__).resolve().parents[3] / "CLAUDE" / "UPGRADES" / "truth-changes"
)
_ID_PLAN_CREATION = "plan-creation"
_ID_PLAN_SIZE_REMEDIES = "plan-size-remedies"

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
            TruthChangeManifest.from_dict({"version": "3.16.0", "truth_changes": [{"now": "y"}]})


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
# Supersession — collapse by truth key (Plan 00329 Phase 1, Plan 00362 D13)
# ---------------------------------------------------------------------------


@pytest.fixture
def chain_dir(tmp_path: Path) -> Path:
    """A truth-changes dir where one keyed truth is revised across three releases.

    v3.23.0 / v3.25.0 / v3.26.0 all carry ``id: plan-creation``; v3.24.0 carries
    an un-keyed entry between them; v3.26.0 also carries a second, unrelated
    un-keyed entry whose text is a verbatim repeat of v3.24.0's.
    """
    d = tmp_path / "truth-changes"
    _write_manifest(
        d,
        "3.23.0",
        "version: '3.23.0'\n"
        "truth_changes:\n"
        f"  - id: {_ID_PLAN_CREATION}\n"
        "    was: Create the plan folder by hand.\n"
        "    now: Run mkplan.bash; it is installer-deployed.\n",
    )
    _write_manifest(
        d,
        "3.24.0",
        "version: '3.24.0'\n"
        "truth_changes:\n"
        "  - was: Untracked memory writes are allowed.\n"
        "    now: Untracked memory writes are blocked.\n",
    )
    _write_manifest(
        d,
        "3.25.0",
        "version: '3.25.0'\n"
        "truth_changes:\n"
        f"  - id: {_ID_PLAN_CREATION}\n"
        "    was: Run mkplan.bash; it is installer-deployed.\n"
        "    now: Run mkplan.bash; it is deployed from the config SSoT.\n",
    )
    _write_manifest(
        d,
        "3.26.0",
        "version: '3.26.0'\n"
        "truth_changes:\n"
        f"  - id: {_ID_PLAN_CREATION}\n"
        "    was: Run mkplan.bash; it is deployed from the config SSoT.\n"
        "    now: Run mkplan.bash; the plan workflow is opt-in and defaults to false.\n"
        "  - was: Untracked memory writes are allowed.\n"
        "    now: Untracked memory writes are blocked.\n",
    )
    return d


class TestTruthChangeIdParsing:
    def test_from_dict_parses_optional_id(self) -> None:
        manifest = TruthChangeManifest.from_dict(
            {
                "version": "3.23.0",
                "truth_changes": [{"id": "plan-creation", "was": "a", "now": "b"}],
            }
        )
        assert manifest.changes[0].id == "plan-creation"

    def test_from_dict_defaults_id_to_none(self) -> None:
        manifest = TruthChangeManifest.from_dict(
            {"version": "3.23.0", "truth_changes": [{"was": "a", "now": "b"}]}
        )
        assert manifest.changes[0].id is None

    def test_from_dict_rejects_duplicate_id_within_one_manifest(self) -> None:
        with pytest.raises(ValueError, match="plan-creation"):
            TruthChangeManifest.from_dict(
                {
                    "version": "3.23.0",
                    "truth_changes": [
                        {"id": "plan-creation", "was": "a", "now": "b"},
                        {"id": "plan-creation", "was": "c", "now": "d"},
                    ],
                }
            )

    def test_from_dict_rejects_blank_id(self) -> None:
        with pytest.raises(ValueError, match="id"):
            TruthChangeManifest.from_dict(
                {"version": "3.23.0", "truth_changes": [{"id": "  ", "was": "a", "now": "b"}]}
            )


class TestCollapseSuperseded:
    def test_keyed_chain_collapses_to_highest_version(self, chain_dir: Path) -> None:
        manifests = load_truth_changes_between("3.22.0", "3.26.0", truth_changes_dir=chain_dir)
        surfaced = collapse_superseded(manifests)
        keyed = [s for s in surfaced if s.change.id == _ID_PLAN_CREATION]
        assert len(keyed) == 1
        assert keyed[0].version == "3.26.0"
        assert keyed[0].change.now is not None
        assert "opt-in" in keyed[0].change.now
        assert keyed[0].superseded_versions == ["3.23.0", "3.25.0"]

    def test_unkeyed_entries_are_never_collapsed_even_when_identical(self, chain_dir: Path) -> None:
        manifests = load_truth_changes_between("3.22.0", "3.26.0", truth_changes_dir=chain_dir)
        surfaced = collapse_superseded(manifests)
        unkeyed = [s for s in surfaced if s.change.id is None]
        assert [s.version for s in unkeyed] == ["3.24.0", "3.26.0"]
        assert all(s.superseded_versions == [] for s in unkeyed)

    def test_partial_range_surfaces_the_highest_version_in_range(self, chain_dir: Path) -> None:
        # (3.22.0, 3.25.0] — v3.26.0 is outside the range, so v3.25.0 is current.
        manifests = load_truth_changes_between("3.22.0", "3.25.0", truth_changes_dir=chain_dir)
        keyed = [s for s in collapse_superseded(manifests) if s.change.id == _ID_PLAN_CREATION]
        assert keyed[0].version == "3.25.0"
        assert keyed[0].superseded_versions == ["3.23.0"]

    def test_single_keyed_entry_has_empty_trail(self, chain_dir: Path) -> None:
        manifests = load_truth_changes_between("3.25.0", "3.26.0", truth_changes_dir=chain_dir)
        keyed = [s for s in collapse_superseded(manifests) if s.change.id == _ID_PLAN_CREATION]
        assert keyed[0].superseded_versions == []

    def test_surfaced_entries_keep_version_order(self, chain_dir: Path) -> None:
        manifests = load_truth_changes_between("3.22.0", "3.26.0", truth_changes_dir=chain_dir)
        versions = [s.version for s in collapse_superseded(manifests)]
        assert versions == sorted(versions, key=lambda v: tuple(int(x) for x in v.split(".")))

    def test_keyed_removal_as_latest_is_surfaced_as_removal(self) -> None:
        manifests = [
            TruthChangeManifest("3.1.0", [TruthChange(was="a", now="b", id="k")]),
            TruthChangeManifest("3.2.0", [TruthChange(was="b", now=None, id="k")]),
        ]
        surfaced = collapse_superseded(manifests)
        assert surfaced == [
            SurfacedTruthChange(
                version="3.2.0",
                change=TruthChange(was="b", now=None, id="k"),
                superseded_versions=["3.1.0"],
            )
        ]
        assert surfaced[0].change.is_removal is True


class TestFormatterSupersession:
    def test_superseded_now_never_appears_in_text(self, chain_dir: Path) -> None:
        manifests = load_truth_changes_between("3.22.0", "3.26.0", truth_changes_dir=chain_dir)
        text = format_truth_changes_for_llm(manifests, "3.22.0", "3.26.0")
        assert "NOW: Run mkplan.bash; it is installer-deployed." not in text
        assert "NOW: Run mkplan.bash; it is deployed from the config SSoT." not in text
        assert "NOW: Run mkplan.bash; the plan workflow is opt-in and defaults to false." in text

    def test_collapsed_entry_carries_revised_in_trail(self, chain_dir: Path) -> None:
        manifests = load_truth_changes_between("3.22.0", "3.26.0", truth_changes_dir=chain_dir)
        text = format_truth_changes_for_llm(manifests, "3.22.0", "3.26.0")
        assert "(v3.26.0, revised in v3.23.0, v3.25.0)" in text
        assert "(v3.23.0)" not in text
        assert "(v3.25.0)" not in text

    def test_uncollapsed_entry_carries_no_trail(self, chain_dir: Path) -> None:
        manifests = load_truth_changes_between("3.22.0", "3.26.0", truth_changes_dir=chain_dir)
        text = format_truth_changes_for_llm(manifests, "3.22.0", "3.26.0")
        assert "(v3.24.0) WAS:" in text

    def test_header_explains_the_trail_when_any_entry_collapsed(self, chain_dir: Path) -> None:
        manifests = load_truth_changes_between("3.22.0", "3.26.0", truth_changes_dir=chain_dir)
        text = format_truth_changes_for_llm(manifests, "3.22.0", "3.26.0")
        assert "revised in" in text.split("•")[0]

    def test_json_changes_are_collapsed_and_carry_trail(self, chain_dir: Path) -> None:
        result = run_check_truth_changes(
            "3.22.0", "3.26.0", output_format="json", truth_changes_dir=chain_dir
        )
        keyed = [c for c in result["changes"] if c["id"] == _ID_PLAN_CREATION]
        assert len(keyed) == 1
        assert keyed[0]["version"] == "3.26.0"
        assert keyed[0]["superseded_versions"] == ["3.23.0", "3.25.0"]
        assert len(result["changes"]) == 3


class TestRealManifestCorpus:
    """The shipped manifests, not fixtures: the defect was measured on them."""

    def _full_span(self) -> list[TruthChangeManifest]:
        assert _REAL_TRUTH_CHANGES_DIR.is_dir()
        return load_truth_changes_between(
            "0.0.0", "999.0.0", truth_changes_dir=_REAL_TRUTH_CHANGES_DIR
        )

    def test_no_id_appears_twice_in_surfaced_output(self) -> None:
        ids = [s.change.id for s in collapse_superseded(self._full_span()) if s.change.id]
        assert len(ids) == len(set(ids)), sorted(i for i in ids if ids.count(i) > 1)

    def test_no_id_appears_twice_in_text_output(self) -> None:
        manifests = self._full_span()
        text = format_truth_changes_for_llm(manifests, "0.0.0", "999.0.0")
        for manifest in manifests:
            for change in manifest.changes:
                if change.id:
                    assert text.count(f"[{change.id}]") == 1, change.id

    def test_plan_creation_truth_is_surfaced_once_as_v3_26_0(self) -> None:
        surfaced = [
            s for s in collapse_superseded(self._full_span()) if s.change.id == _ID_PLAN_CREATION
        ]
        assert [s.version for s in surfaced] == ["3.26.0"]
        assert surfaced[0].superseded_versions == ["3.23.0", "3.25.0"]
        assert surfaced[0].change.now is not None
        assert "OPT-IN" in surfaced[0].change.now

    def test_plan_size_remedies_truth_is_surfaced_once_as_v3_53_0(self) -> None:
        surfaced = [
            s
            for s in collapse_superseded(self._full_span())
            if s.change.id == _ID_PLAN_SIZE_REMEDIES
        ]
        assert [s.version for s in surfaced] == ["3.53.0"]
        assert surfaced[0].superseded_versions == ["3.50.0"]

    def test_superseded_plan_creation_instructions_never_reach_the_text(self) -> None:
        text = format_truth_changes_for_llm(self._full_span(), "0.0.0", "999.0.0")
        assert "It is distributed by the installer, takes a" not in text
        assert "It is now deployed from the config single" not in text
        assert "Deletion is NOT a remedy" not in text

    def test_every_id_is_a_kebab_case_slug(self) -> None:
        for manifest in self._full_span():
            for change in manifest.changes:
                if change.id is not None:
                    assert change.id == change.id.strip().lower(), (manifest.version, change.id)
                    assert " " not in change.id, (manifest.version, change.id)


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
                "id": None,
                "superseded_versions": [],
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
