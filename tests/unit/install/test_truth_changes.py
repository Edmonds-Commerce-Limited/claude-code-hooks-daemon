"""Tests for the truth-changes loader, formatter, and run-function (Plan 00118).

Truth-changes record statements that were true about working in a project but
became false in a release (replaced by a new truth, or retired). They are loaded
over a version range and reconciled against the project's own docs by the LLM.

Mirrors the proven config_migrations range-loader pattern, minus the user-config
comparison (truth-changes are not compared against anything — they are guidance).
"""

from pathlib import Path

import pytest

from claude_code_hooks_daemon.install.report_offload import SUMMARY_MAX_BYTES
from claude_code_hooks_daemon.install.truth_changes import (
    UNASSIGNED_CHUNK_KEY,
    ReportChunk,
    SurfacedTruthChange,
    TruthChange,
    TruthChangeManifest,
    chunk_by_topic,
    collapse_superseded,
    format_bounded_summary,
    format_chunk_for_subagent,
    format_truth_changes_for_llm,
    list_known_truth_change_versions,
    load_truth_changes_between,
    run_check_truth_changes,
    write_truth_changes_report,
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
                "topic": None,
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


# ---------------------------------------------------------------------------
# Plan 00329: topic chunks, file offload, and the stdout bound
# ---------------------------------------------------------------------------


@pytest.fixture
def topic_dir(tmp_path: Path) -> Path:
    """Entries across two releases carrying topics, a bare id, and nothing.

    v3.30.0: two ``plan-workflow`` entries and one bare-``id`` entry.
    v3.31.0: one ``daemon-cli`` entry, one more ``plan-workflow`` entry, one
    entry with neither key, and a second link of the bare-id chain.
    """
    d = tmp_path / "truth-changes"
    _write_manifest(
        d,
        "3.30.0",
        "version: '3.30.0'\n"
        "truth_changes:\n"
        "  - topic: plan-workflow\n"
        "    was: Plans are numbered by scanning the folder.\n"
        "    now: Plans are numbered from the git counter.\n"
        "  - topic: plan-workflow\n"
        "    was: Notes go in a Notes section.\n"
        "    now: Notes go in JOURNAL/.\n"
        "  - id: venv-layout\n"
        "    was: The venv lives at untracked/venv/.\n"
        "    now: The venv is fingerprint-keyed.\n",
    )
    _write_manifest(
        d,
        "3.31.0",
        "version: '3.31.0'\n"
        "truth_changes:\n"
        "  - topic: daemon-cli\n"
        "    was: Run the CLI via $PYTHON.\n"
        "    now: Run the CLI via bin/hooks-daemon.\n"
        "  - topic: plan-workflow\n"
        "    was: Time estimates are allowed in plans.\n"
        "    now: Time estimates are blocked in plans.\n"
        "  - was: A truth with neither key.\n"
        "    now: Its replacement.\n"
        "  - id: venv-layout\n"
        "    was: The venv is fingerprint-keyed.\n"
        "    now: The venv is fingerprint-keyed under the daemon dir.\n",
    )
    return d


class TestTopicParsing:
    def test_from_dict_parses_optional_topic(self) -> None:
        manifest = TruthChangeManifest.from_dict(
            {
                "version": "3.30.0",
                "truth_changes": [{"topic": "plan-workflow", "was": "a", "now": "b"}],
            }
        )
        assert manifest.changes[0].topic == "plan-workflow"

    def test_from_dict_defaults_topic_to_none(self) -> None:
        manifest = TruthChangeManifest.from_dict(
            {"version": "3.30.0", "truth_changes": [{"was": "a", "now": "b"}]}
        )
        assert manifest.changes[0].topic is None

    def test_from_dict_rejects_blank_topic(self) -> None:
        with pytest.raises(ValueError, match="topic"):
            TruthChangeManifest.from_dict(
                {"version": "3.30.0", "truth_changes": [{"topic": "  ", "was": "a", "now": "b"}]}
            )

    def test_topic_and_id_may_coexist(self) -> None:
        manifest = TruthChangeManifest.from_dict(
            {
                "version": "3.30.0",
                "truth_changes": [{"topic": "t", "id": "i", "was": "a", "now": "b"}],
            }
        )
        assert (manifest.changes[0].topic, manifest.changes[0].id) == ("t", "i")


class TestChunkByTopic:
    def _chunks(self, topic_dir: Path) -> list[ReportChunk]:
        manifests = load_truth_changes_between("3.29.0", "3.31.0", truth_changes_dir=topic_dir)
        return chunk_by_topic(collapse_superseded(manifests))

    def test_every_surfaced_entry_lands_in_exactly_one_chunk(self, topic_dir: Path) -> None:
        manifests = load_truth_changes_between("3.29.0", "3.31.0", truth_changes_dir=topic_dir)
        surfaced = collapse_superseded(manifests)
        chunks = chunk_by_topic(surfaced)
        placed = [entry for chunk in chunks for entry in chunk.entries]
        assert sorted(e.change.was for e in placed) == sorted(e.change.was for e in surfaced)
        assert len(placed) == len(surfaced)

    def test_chunk_keys_are_unique(self, topic_dir: Path) -> None:
        keys = [chunk.key for chunk in self._chunks(topic_dir)]
        assert len(keys) == len(set(keys))

    def test_entries_sharing_a_topic_share_one_chunk_across_releases(self, topic_dir: Path) -> None:
        by_key = {chunk.key: chunk for chunk in self._chunks(topic_dir)}
        assert [e.version for e in by_key["plan-workflow"].entries] == [
            "3.30.0",
            "3.30.0",
            "3.31.0",
        ]

    def test_keyed_entry_without_topic_is_its_own_chunk_keyed_by_id(self, topic_dir: Path) -> None:
        by_key = {chunk.key: chunk for chunk in self._chunks(topic_dir)}
        assert [e.change.id for e in by_key["venv-layout"].entries] == ["venv-layout"]
        assert by_key["venv-layout"].sequential is False

    def test_chunking_happens_after_collapsing(self, topic_dir: Path) -> None:
        by_key = {chunk.key: chunk for chunk in self._chunks(topic_dir)}
        links = by_key["venv-layout"].entries
        assert [e.version for e in links] == ["3.31.0"]
        assert links[0].superseded_versions == ["3.30.0"]

    def test_entry_with_neither_key_goes_to_the_sequential_chunk_last(
        self, topic_dir: Path
    ) -> None:
        chunks = self._chunks(topic_dir)
        assert chunks[-1].key == UNASSIGNED_CHUNK_KEY
        assert chunks[-1].sequential is True
        assert [e.change.was for e in chunks[-1].entries] == ["A truth with neither key."]
        assert all(chunk.sequential is False for chunk in chunks[:-1])

    def test_chunk_order_is_first_appearance_in_version_order(self, topic_dir: Path) -> None:
        # The collapsed venv-layout chain sits where its LAST link was, so it
        # appears after daemon-cli, which v3.31.0 lists first.
        assert [c.key for c in self._chunks(topic_dir)] == [
            "plan-workflow",
            "daemon-cli",
            "venv-layout",
            UNASSIGNED_CHUNK_KEY,
        ]

    def test_no_entries_means_no_chunks(self) -> None:
        assert chunk_by_topic([]) == []


class TestFormatChunkForSubagent:
    def test_chunk_text_is_self_contained(self, topic_dir: Path) -> None:
        manifests = load_truth_changes_between("3.29.0", "3.31.0", truth_changes_dir=topic_dir)
        chunks = chunk_by_topic(collapse_superseded(manifests))
        text = format_chunk_for_subagent(chunks[0], "3.29.0", "3.31.0")
        # names itself, carries the rules, its entries, and the return contract
        assert "plan-workflow" in text
        assert "never .claude/hooks-daemon/" in text
        assert "Plans are numbered from the git counter." in text
        assert "Time estimates are blocked in plans." in text
        assert "Run the CLI via bin/hooks-daemon." not in text
        assert "files you changed" in text
        assert "not the entries" in text

    def test_sequential_chunk_says_why_it_runs_alone(self, topic_dir: Path) -> None:
        manifests = load_truth_changes_between("3.29.0", "3.31.0", truth_changes_dir=topic_dir)
        chunks = chunk_by_topic(collapse_superseded(manifests))
        text = format_chunk_for_subagent(chunks[-1], "3.29.0", "3.31.0")
        assert "SEQUENTIAL" in text
        assert "after" in text


class TestWriteTruthChangesReport:
    def test_writes_full_report_and_one_file_per_chunk(
        self, topic_dir: Path, tmp_path: Path
    ) -> None:
        manifests = load_truth_changes_between("3.29.0", "3.31.0", truth_changes_dir=topic_dir)
        files = write_truth_changes_report(manifests, "3.29.0", "3.31.0", tmp_path / "out")
        assert files.report_path == tmp_path / "out" / "v3.29.0-to-v3.31.0" / "REPORT.md"
        full = files.report_path.read_text(encoding="utf-8")
        assert format_truth_changes_for_llm(manifests, "3.29.0", "3.31.0") in full
        assert [p.name for _, p in files.chunk_paths] == [
            "chunk-01-plan-workflow.md",
            "chunk-02-daemon-cli.md",
            "chunk-03-venv-layout.md",
            f"chunk-04-{UNASSIGNED_CHUNK_KEY}.md",
        ]
        for chunk, path in files.chunk_paths:
            assert path.read_text(encoding="utf-8") == format_chunk_for_subagent(
                chunk, "3.29.0", "3.31.0"
            )

    def test_full_report_indexes_the_chunk_files(self, topic_dir: Path, tmp_path: Path) -> None:
        manifests = load_truth_changes_between("3.29.0", "3.31.0", truth_changes_dir=topic_dir)
        files = write_truth_changes_report(manifests, "3.29.0", "3.31.0", tmp_path)
        full = files.report_path.read_text(encoding="utf-8")
        for _, path in files.chunk_paths:
            assert str(path) in full

    def test_stale_chunk_files_from_a_previous_run_are_removed(
        self, topic_dir: Path, tmp_path: Path
    ) -> None:
        target = tmp_path / "v3.29.0-to-v3.31.0"
        target.mkdir()
        stale = target / "chunk-09-gone.md"
        stale.write_text("stale")
        manifests = load_truth_changes_between("3.29.0", "3.31.0", truth_changes_dir=topic_dir)
        write_truth_changes_report(manifests, "3.29.0", "3.31.0", tmp_path)
        assert not stale.exists()


class TestBoundedSummary:
    def _summary(self, truth_changes_dir: Path, out: Path, frm: str, to: str) -> str:
        manifests = load_truth_changes_between(frm, to, truth_changes_dir=truth_changes_dir)
        files = write_truth_changes_report(manifests, frm, to, out)
        return format_bounded_summary(manifests, frm, to, files)

    def test_summary_names_counts_report_path_and_every_chunk(
        self, topic_dir: Path, tmp_path: Path
    ) -> None:
        text = self._summary(topic_dir, tmp_path, "3.29.0", "3.31.0")
        assert "Truth-Changes to reconcile: v3.29.0 → v3.31.0" in text
        assert "6 truths" in text  # 7 raw entries, one superseded link collapsed
        assert "7 entries" in text
        assert str(tmp_path / "v3.29.0-to-v3.31.0" / "REPORT.md") in text
        assert "chunk-01-plan-workflow.md" in text
        assert f"chunk-04-{UNASSIGNED_CHUNK_KEY}.md" in text
        assert "SEQUENTIAL" in text
        assert "files it changed" in text

    def test_summary_carries_no_entry_text(self, topic_dir: Path, tmp_path: Path) -> None:
        text = self._summary(topic_dir, tmp_path, "3.29.0", "3.31.0")
        assert "Plans are numbered from the git counter." not in text
        assert "WAS:" not in text

    def test_full_span_of_the_real_corpus_is_under_the_bound(self, tmp_path: Path) -> None:
        text = self._summary(_REAL_TRUTH_CHANGES_DIR, tmp_path, "0.0.0", "999.0.0")
        assert len(text.encode("utf-8")) <= SUMMARY_MAX_BYTES

    def test_bound_holds_when_a_new_manifest_is_added_to_the_corpus(self, tmp_path: Path) -> None:
        # Task 4.1: the regression that lets this defect return is a release
        # quietly adding entries. Copy the real corpus, add a release with
        # forty entries over forty NEW topics, and the summary still fits.
        corpus = tmp_path / "corpus"
        corpus.mkdir()
        for manifest_file in _REAL_TRUTH_CHANGES_DIR.glob("v*.yaml"):
            (corpus / manifest_file.name).write_text(manifest_file.read_text(encoding="utf-8"))
        entries = "".join(
            f"  - topic: new-area-{i:02d}\n    was: Old truth {i}.\n    now: New truth {i}.\n"
            for i in range(40)
        )
        _write_manifest(corpus, "999.0.0", f"version: '999.0.0'\ntruth_changes:\n{entries}")
        text = self._summary(corpus, tmp_path / "out", "0.0.0", "999.0.0")
        assert len(text.encode("utf-8")) <= SUMMARY_MAX_BYTES
        assert "New truth 0." not in text

    def test_bound_holds_for_an_absurd_number_of_topics(self, tmp_path: Path) -> None:
        d = tmp_path / "truth-changes"
        entries = "".join(
            f"  - topic: topic-{i:03d}\n    was: Old {i}.\n    now: New {i}.\n" for i in range(400)
        )
        _write_manifest(d, "9.0.0", f"version: '9.0.0'\ntruth_changes:\n{entries}")
        text = self._summary(d, tmp_path / "out", "8.0.0", "9.0.0")
        assert len(text.encode("utf-8")) <= SUMMARY_MAX_BYTES
        assert "more chunks" in text
        assert "REPORT.md" in text


class TestRealCorpusTopics:
    """Every shipped entry is assigned, so parallel dispatch is real, not a fallback."""

    def _chunks(self) -> list[ReportChunk]:
        manifests = load_truth_changes_between(
            "0.0.0", "999.0.0", truth_changes_dir=_REAL_TRUTH_CHANGES_DIR
        )
        return chunk_by_topic(collapse_superseded(manifests))

    def test_no_entry_is_unassigned(self) -> None:
        keys = [chunk.key for chunk in self._chunks()]
        assert UNASSIGNED_CHUNK_KEY not in keys

    def test_chunks_partition_the_surfaced_entries(self) -> None:
        manifests = load_truth_changes_between(
            "0.0.0", "999.0.0", truth_changes_dir=_REAL_TRUTH_CHANGES_DIR
        )
        surfaced = collapse_superseded(manifests)
        chunks = self._chunks()
        assert sum(len(c.entries) for c in chunks) == len(surfaced)
        assert len({c.key for c in chunks}) == len(chunks)

    def test_every_topic_is_a_kebab_case_slug(self) -> None:
        for chunk in self._chunks():
            assert chunk.key == chunk.key.strip().lower(), chunk.key
            assert " " not in chunk.key and "_" not in chunk.key, chunk.key

    def test_keyed_truths_carry_a_topic_so_a_chain_is_not_its_own_chunk(self) -> None:
        for chunk in self._chunks():
            for entry in chunk.entries:
                if entry.change.id is not None:
                    assert entry.change.topic is not None, entry.change.id


class TestRunCheckTruthChangesOffload:
    def test_report_dir_bounds_the_text_and_returns_the_paths(
        self, topic_dir: Path, tmp_path: Path
    ) -> None:
        result = run_check_truth_changes(
            "3.29.0",
            "3.31.0",
            output_format="text",
            truth_changes_dir=topic_dir,
            report_dir=tmp_path / "reports",
        )
        assert result["has_changes"] is True
        assert len(result["text"].encode("utf-8")) <= SUMMARY_MAX_BYTES
        assert "WAS:" not in result["text"]
        report_path = Path(result["report_path"])
        assert report_path.is_file()
        assert [c["key"] for c in result["chunks"]] == [
            "plan-workflow",
            "daemon-cli",
            "venv-layout",
            UNASSIGNED_CHUNK_KEY,
        ]
        assert [c["entry_count"] for c in result["chunks"]] == [3, 1, 1, 1]
        assert [c["sequential"] for c in result["chunks"]] == [False, False, False, True]
        assert all(Path(c["path"]).is_file() for c in result["chunks"])

    def test_json_format_also_writes_the_files(self, topic_dir: Path, tmp_path: Path) -> None:
        result = run_check_truth_changes(
            "3.29.0",
            "3.31.0",
            output_format="json",
            truth_changes_dir=topic_dir,
            report_dir=tmp_path,
        )
        assert Path(result["report_path"]).is_file()
        assert len(result["changes"]) == 6
        assert "text" not in result

    def test_without_report_dir_the_full_report_is_the_text(
        self, topic_dir: Path, tmp_path: Path
    ) -> None:
        result = run_check_truth_changes(
            "3.29.0", "3.31.0", output_format="text", truth_changes_dir=topic_dir
        )
        assert "WAS:" in result["text"]
        assert result["report_path"] is None
        assert result["chunks"] == []
        assert not list(tmp_path.glob("**/v3.29.0-to-v3.31.0"))

    def test_no_changes_writes_nothing(self, topic_dir: Path, tmp_path: Path) -> None:
        result = run_check_truth_changes(
            "3.31.0",
            "3.31.0",
            output_format="text",
            truth_changes_dir=topic_dir,
            report_dir=tmp_path / "reports",
        )
        assert result["has_changes"] is False
        assert result["report_path"] is None
        assert not (tmp_path / "reports").exists()

    def test_json_changes_carry_topic(self, topic_dir: Path) -> None:
        result = run_check_truth_changes(
            "3.29.0", "3.30.0", output_format="json", truth_changes_dir=topic_dir
        )
        assert result["changes"][0]["topic"] == "plan-workflow"
        assert result["changes"][2]["topic"] is None
