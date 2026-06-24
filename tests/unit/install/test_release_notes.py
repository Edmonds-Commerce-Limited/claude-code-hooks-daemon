"""Unit tests for the release_notes module (Plan 00141).

The module loads per-version release notes from the daemon's ``RELEASES/``
directory by exact version, version range, latest, or listing. It mirrors the
``truth_changes`` / ``config_migrations`` range-loader pattern.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from claude_code_hooks_daemon.install.release_notes import (
    ReleaseNote,
    list_known_release_versions,
    load_release_note,
    load_release_notes_between,
    run_release_notes,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def releases_dir(tmp_path: Path) -> Path:
    """A RELEASES/ dir with three real release files plus noise to ignore."""
    base = tmp_path / "RELEASES"
    base.mkdir()
    files = {
        "v3.20.0.md": "# v3.20.0\n\nNotes for 3.20.0\n",
        "v3.21.0.md": "# v3.21.0\n\nNotes for 3.21.0\n",
        "v3.27.0.md": "# v3.27.0\n\nNotes for 3.27.0\n",
    }
    for name, content in files.items():
        (base / name).write_text(content)
    # Noise that must be ignored by the version pattern.
    (base / "README.md").write_text("not a release\n")
    (base / "vX.Y.Z.md").write_text("template placeholder\n")
    (base / "v3.20.md").write_text("two-component, ignore\n")
    (base / "notes.txt").write_text("ignore\n")
    return base


# ---------------------------------------------------------------------------
# list_known_release_versions
# ---------------------------------------------------------------------------


def test_list_known_release_versions_sorted_and_filtered(releases_dir: Path) -> None:
    assert list_known_release_versions(releases_dir=releases_dir) == [
        "3.20.0",
        "3.21.0",
        "3.27.0",
    ]


def test_list_known_release_versions_missing_dir(tmp_path: Path) -> None:
    assert list_known_release_versions(releases_dir=tmp_path / "nope") == []


# ---------------------------------------------------------------------------
# load_release_note
# ---------------------------------------------------------------------------


def test_load_release_note_hit(releases_dir: Path) -> None:
    note = load_release_note("3.21.0", releases_dir=releases_dir)
    assert isinstance(note, ReleaseNote)
    assert note.version == "3.21.0"
    assert "Notes for 3.21.0" in note.content
    assert note.path.endswith("v3.21.0.md")


def test_load_release_note_miss(releases_dir: Path) -> None:
    assert load_release_note("9.9.9", releases_dir=releases_dir) is None


def test_load_release_note_missing_dir(tmp_path: Path) -> None:
    assert load_release_note("3.21.0", releases_dir=tmp_path / "nope") is None


# ---------------------------------------------------------------------------
# load_release_notes_between  (from excluded, to included)
# ---------------------------------------------------------------------------


def test_load_release_notes_between_excludes_from_includes_to(releases_dir: Path) -> None:
    notes = load_release_notes_between("3.20.0", "3.27.0", releases_dir=releases_dir)
    assert [n.version for n in notes] == ["3.21.0", "3.27.0"]


def test_load_release_notes_between_equal_returns_empty(releases_dir: Path) -> None:
    assert load_release_notes_between("3.21.0", "3.21.0", releases_dir=releases_dir) == []


def test_load_release_notes_between_from_gt_to_raises(releases_dir: Path) -> None:
    with pytest.raises(ValueError, match="must be <="):
        load_release_notes_between("3.27.0", "3.20.0", releases_dir=releases_dir)


# ---------------------------------------------------------------------------
# _parse_version edge case via public surface
# ---------------------------------------------------------------------------


def test_invalid_version_string_raises(releases_dir: Path) -> None:
    with pytest.raises(ValueError, match="Invalid version"):
        load_release_notes_between("not.a.version", "3.27.0", releases_dir=releases_dir)


# ---------------------------------------------------------------------------
# run_release_notes
# ---------------------------------------------------------------------------


def test_run_release_notes_specific_version(releases_dir: Path) -> None:
    result = run_release_notes(version="3.21.0", releases_dir=releases_dir)
    assert result["found"] is True
    assert result["mode"] == "version"
    assert result["notes"][0]["version"] == "3.21.0"
    assert "Notes for 3.21.0" in result["text"]


def test_run_release_notes_missing_version_not_found(releases_dir: Path) -> None:
    result = run_release_notes(version="9.9.9", releases_dir=releases_dir)
    assert result["found"] is False
    assert result["notes"] == []
    assert "9.9.9" in result["text"]


def test_run_release_notes_defaults_to_current_version(releases_dir: Path) -> None:
    result = run_release_notes(current_version="3.27.0", releases_dir=releases_dir)
    assert result["mode"] == "current"
    assert result["found"] is True
    assert result["notes"][0]["version"] == "3.27.0"


def test_run_release_notes_list(releases_dir: Path) -> None:
    result = run_release_notes(list_versions=True, releases_dir=releases_dir)
    assert result["mode"] == "list"
    assert result["versions"] == ["3.20.0", "3.21.0", "3.27.0"]
    assert result["found"] is True
    assert "3.27.0" in result["text"]


def test_run_release_notes_latest(releases_dir: Path) -> None:
    result = run_release_notes(latest=True, releases_dir=releases_dir)
    assert result["mode"] == "latest"
    assert result["found"] is True
    assert result["notes"][0]["version"] == "3.27.0"


def test_run_release_notes_latest_empty_dir(tmp_path: Path) -> None:
    result = run_release_notes(latest=True, releases_dir=tmp_path / "nope")
    assert result["found"] is False


def test_run_release_notes_range(releases_dir: Path) -> None:
    result = run_release_notes(
        from_version="3.20.0", to_version="3.27.0", releases_dir=releases_dir
    )
    assert result["mode"] == "range"
    assert result["versions"] == ["3.21.0", "3.27.0"]
    assert result["found"] is True
    assert "Notes for 3.21.0" in result["text"]
    assert "Notes for 3.27.0" in result["text"]


def test_run_release_notes_range_requires_both_bounds(releases_dir: Path) -> None:
    with pytest.raises(ValueError, match="both --from and --to"):
        run_release_notes(from_version="3.20.0", releases_dir=releases_dir)


def test_run_release_notes_range_from_gt_to_raises(releases_dir: Path) -> None:
    with pytest.raises(ValueError, match="must be <="):
        run_release_notes(from_version="3.27.0", to_version="3.20.0", releases_dir=releases_dir)


def test_run_release_notes_json_format_omits_text(releases_dir: Path) -> None:
    result = run_release_notes(version="3.21.0", output_format="json", releases_dir=releases_dir)
    assert "text" not in result
    assert result["found"] is True
    assert result["notes"][0]["content"].startswith("# v3.21.0")


def test_run_release_notes_no_target_and_no_current(releases_dir: Path) -> None:
    # With nothing to resolve a target, it is a clean not-found, not a crash.
    result = run_release_notes(releases_dir=releases_dir)
    assert result["found"] is False


def test_default_releases_dir_resolves_to_real_repo_releases() -> None:
    # No override -> resolves the bundled RELEASES/ dir relative to the package.
    # The daemon always ships per-version release files, so this is non-empty.
    versions = list_known_release_versions()
    assert versions, "default RELEASES dir resolution returned no versions"
    assert all(v.count(".") == 2 for v in versions)
