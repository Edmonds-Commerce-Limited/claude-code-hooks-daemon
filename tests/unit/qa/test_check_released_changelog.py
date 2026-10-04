"""Tests for the released-CHANGELOG-section immutability check (Plan 00474 N343)."""

import importlib.util
import subprocess  # nosec B404 - git fixtures
import sys
from pathlib import Path
from types import ModuleType

import pytest

_CHECKER = Path(__file__).resolve().parents[3] / "scripts" / "qa" / "check_released_changelog.py"

_HEADER = "# Changelog\n\n"
_RELEASED = "## [1.0.0] - 2026-01-01\n\n### Added\n\n- first thing\n\n"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_released_changelog", _CHECKER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _git(root: Path, *args: str) -> None:
    subprocess.run(  # nosec B603 B607 - fixed git argv in a tmp repo
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=root,
        check=True,
        capture_output=True,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repo whose CHANGELOG has one released, tagged section."""
    _git(tmp_path, "init", "-q")
    (tmp_path / "CHANGELOG.md").write_text(_HEADER + _RELEASED, encoding="utf-8")
    _git(tmp_path, "add", "CHANGELOG.md")
    _git(tmp_path, "commit", "-q", "-m", "release")
    _git(tmp_path, "tag", "v1.0.0")
    return tmp_path


def test_untouched_changelog_passes(repo: Path) -> None:
    assert _load().find_violations(repo) == []


def test_new_unreleased_section_is_allowed(repo: Path) -> None:
    new = _HEADER + "## [1.1.0] - 2026-02-01\n\n- new\n\n" + _RELEASED
    (repo / "CHANGELOG.md").write_text(new, encoding="utf-8")
    assert _load().find_violations(repo) == []


def test_edit_inside_released_section_fails_and_names_destination(repo: Path) -> None:
    edited = _HEADER + _RELEASED + "- sneaky note\n"
    (repo / "CHANGELOG.md").write_text(edited, encoding="utf-8")
    violations = _load().find_violations(repo)
    assert [v["rule"] for v in violations] == ["released-changelog-section-edited"]
    assert "1.0.0" in violations[0]["message"]
    assert "CLAUDE/UPGRADES/UNRELEASED/release-notes/" in violations[0]["message"]


def test_section_without_tag_may_change(repo: Path) -> None:
    text = _HEADER + "## [2.0.0] - 2026-03-01\n\n- a\n\n" + _RELEASED
    (repo / "CHANGELOG.md").write_text(text, encoding="utf-8")
    _git(repo, "commit", "-q", "-am", "wip")
    (repo / "CHANGELOG.md").write_text(text + "", encoding="utf-8")
    assert _load().find_violations(repo) == []
