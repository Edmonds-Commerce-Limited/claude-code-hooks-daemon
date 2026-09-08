"""One version parser for every install-time range loader (Plan 00362 Task 2.2, D11).

Plan 00291 Task 2.1: the tag form ``v3.62.0`` is the only form this project's
own documentation hands to the upgrade path (``git describe --tags`` always
emits the prefix, and every RELEASES page prints the literal ``v`` argument),
yet the truth-changes, config-migrations and release-notes loaders each had a
private ``_parse_version`` that split on ``.`` and cast to ``int``, so the
prefix raised ``ValueError``. ``breaking_changes_detector.parse_version`` was
fixed on its own; this module is the shared parser the other three now use,
so the fix cannot drift apart again.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from claude_code_hooks_daemon.install import breaking_changes_detector
from claude_code_hooks_daemon.install.config_migrations import load_manifests_between
from claude_code_hooks_daemon.install.release_notes import load_release_notes_between
from claude_code_hooks_daemon.install.truth_changes import (
    load_truth_changes_between,
    run_check_truth_changes,
)
from claude_code_hooks_daemon.install.version_parse import parse_version_tuple


class TestParseVersionTuple:
    def test_bare_version_parses(self) -> None:
        assert parse_version_tuple("3.62.0") == (3, 62, 0)

    def test_lowercase_v_prefix_is_stripped(self) -> None:
        assert parse_version_tuple("v3.62.0") == (3, 62, 0)

    def test_uppercase_v_prefix_is_stripped(self) -> None:
        assert parse_version_tuple("V3.62.0") == (3, 62, 0)

    def test_double_digit_component_survives_the_strip(self) -> None:
        assert parse_version_tuple("v10.4.0") == (10, 4, 0)

    def test_prefix_and_bare_compare_equal(self) -> None:
        assert parse_version_tuple("v3.41.0") == parse_version_tuple("3.41.0")

    def test_only_the_prefix_is_forgiven(self) -> None:
        with pytest.raises(ValueError, match="Invalid version string"):
            parse_version_tuple("vv3.62.0")

    def test_malformed_component_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="Invalid version string"):
            parse_version_tuple("v3.x.0")

    def test_empty_string_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="Invalid version string"):
            parse_version_tuple("")

    def test_breaking_changes_detector_shares_the_parser(self) -> None:
        """The already-fixed sibling must be built on the same function, so a
        future change to prefix handling lands in one place."""
        assert breaking_changes_detector.parse_version("v3.62.0") == parse_version_tuple("v3.62.0")
        with pytest.raises(ValueError, match="three components"):
            breaking_changes_detector.parse_version("v3.62")


def _write_yaml(directory: Path, version: str, body: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"v{version}.yaml").write_text(body)


@pytest.fixture
def truth_dir(tmp_path: Path) -> Path:
    d = tmp_path / "truth-changes"
    _write_yaml(
        d,
        "3.50.0",
        "version: '3.50.0'\ntruth_changes:\n  - was: old truth\n    now: new truth\n",
    )
    return d


@pytest.fixture
def manifests_dir(tmp_path: Path) -> Path:
    d = tmp_path / "config-changes"
    _write_yaml(
        d,
        "3.50.0",
        'version: "3.50.0"\ndate: "2026-01-01"\nbreaking: false\n'
        "config_changes:\n  added: []\n  renamed: []\n  removed: []\n  changed: []\n",
    )
    return d


@pytest.fixture
def releases_dir(tmp_path: Path) -> Path:
    d = tmp_path / "RELEASES"
    d.mkdir()
    (d / "v3.50.0.md").write_text("# v3.50.0\n\nnotes\n")
    return d


class TestTruthChangesAcceptTheTagForm:
    def test_v_prefixed_range_loads(self, truth_dir: Path) -> None:
        manifests = load_truth_changes_between("v3.41.0", "v3.62.1", truth_changes_dir=truth_dir)
        assert [m.version for m in manifests] == ["3.50.0"]

    def test_mixed_spellings_agree(self, truth_dir: Path) -> None:
        bare = load_truth_changes_between("3.41.0", "3.62.1", truth_changes_dir=truth_dir)
        tagged = load_truth_changes_between("v3.41.0", "3.62.1", truth_changes_dir=truth_dir)
        assert [m.version for m in bare] == [m.version for m in tagged]

    def test_run_check_truth_changes_accepts_the_tag_form(self, truth_dir: Path) -> None:
        result = run_check_truth_changes("v3.41.0", "v3.62.1", truth_changes_dir=truth_dir)
        assert result["has_changes"] is True


class TestConfigMigrationsAcceptTheTagForm:
    def test_v_prefixed_range_loads(self, manifests_dir: Path) -> None:
        manifests = load_manifests_between("v3.41.0", "v3.62.1", manifests_dir=manifests_dir)
        assert [m.version for m in manifests] == ["3.50.0"]


class TestReleaseNotesAcceptTheTagForm:
    def test_v_prefixed_range_loads(self, releases_dir: Path) -> None:
        notes = load_release_notes_between("v3.41.0", "v3.62.1", releases_dir=releases_dir)
        assert [n.version for n in notes] == ["3.50.0"]
