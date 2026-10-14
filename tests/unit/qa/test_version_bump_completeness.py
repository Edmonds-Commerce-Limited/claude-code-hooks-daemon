"""Every file that carries the release version is registered, and agrees (Plan 00451).

The version-bump procedure used to be a prose list; a file missing from it was
found only when an unrelated gate went red (``docs_qa``, the supervisor test,
``uv lock --check``). This module is the single home of that list:
``VERSION_DECLARATIONS`` maps each version-carrying file to the pattern that
extracts the version it declares. Two checks use it:

* every registered file declares the version in ``version.py``;
* no OTHER tracked file contains that version string, so a new file that
  starts carrying the version fails here until it is registered.

The scan helpers take the repository root and the version as arguments so the
self-tests below can prove, on a throwaway repository, that each check fails
when the defect is present.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from claude_code_hooks_daemon.version import __version__

_REPO_ROOT = Path(__file__).resolve().parents[3]

#: path (repo-relative) -> regex whose group 1 is the version the file declares.
VERSION_DECLARATIONS: dict[str, str] = {
    "pyproject.toml": r'^version = "([^"]+)"',
    "src/claude_code_hooks_daemon/version.py": r'^__version__ = "([^"]+)"',
    "README.md": r"badge/version-([0-9][^-]*)-",
    ".claude/ccy/claude-supervise.py": r'^__version__ = "([^"]+)"',
    ".claude/HOOKS-DAEMON.md": r"\(v([0-9][^)]*)\) by `generate-docs`",
    "uv.lock": r'^name = "claude-code-hooks-daemon"\nversion = "([^"]+)"',
}

#: Trees that legitimately mention many versions, or fixture data in tests.
_IGNORED_PREFIXES: tuple[str, ...] = (
    "CHANGELOG.md",
    "RELEASES/",
    "CLAUDE/UPGRADES/",
    "CLAUDE/Plan/",
    "tests/",
)

#: Tracked files that mention the version without declaring it.
_INCIDENTAL_MENTIONS: frozenset[str] = frozenset(
    {
        "CLAUDE/LLM-UPDATE.md",  # prose naming versions to avoid
        "CLAUDE/development/claude-code-versions.yaml",  # one entry per release
    }
)


def _tracked_files(root: Path) -> list[str]:
    """Return the repo-relative paths git tracks under ``root``."""
    listed = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    return [p for p in listed.stdout.split("\0") if p]


def declared_version_mismatches(root: Path, version: str) -> list[str]:
    """Return one message per registered file not declaring ``version``."""
    problems: list[str] = []
    for rel, pattern in VERSION_DECLARATIONS.items():
        path = root / rel
        if not path.is_file():
            problems.append(f"{rel}: registered but missing")
            continue
        match = re.search(pattern, path.read_text(encoding="utf-8"), re.MULTILINE)
        if match is None:
            problems.append(f"{rel}: no version declaration matches {pattern!r}")
        elif match.group(1) != version:
            problems.append(f"{rel}: declares {match.group(1)}, expected {version}")
    return problems


def unregistered_version_carriers(root: Path, version: str) -> list[str]:
    """Return tracked files containing ``version`` that are not registered."""
    token = re.compile(rf"(?<![\d.]){re.escape(version)}(?!\d|\.\d)")
    found: list[str] = []
    for rel in _tracked_files(root):
        if rel in VERSION_DECLARATIONS or rel in _INCIDENTAL_MENTIONS:
            continue
        if rel.startswith(_IGNORED_PREFIXES):
            continue
        try:
            text = (root / rel).read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # binary or unreadable: cannot declare a version in text
        if token.search(text):
            found.append(rel)
    return found


class TestRepositoryVersionBump:
    """The real repository: nothing carries a version the release is not bumping."""

    def test_every_registered_file_declares_the_current_version(self) -> None:
        assert declared_version_mismatches(_REPO_ROOT, __version__) == []

    def test_no_unregistered_file_carries_the_current_version(self) -> None:
        assert unregistered_version_carriers(_REPO_ROOT, __version__) == [], (
            "A tracked file contains the current version but is not in "
            "VERSION_DECLARATIONS (or _INCIDENTAL_MENTIONS if it only mentions it). "
            "Register it so the version bump covers it."
        )


_OLD_VERSION = "1.0.0"
_SAMPLES: dict[str, str] = {
    "pyproject.toml": 'version = "{v}"\n',
    "src/claude_code_hooks_daemon/version.py": '__version__ = "{v}"\n',
    "README.md": "![Version](https://img.shields.io/badge/version-{v}-blue)\n",
    ".claude/ccy/claude-supervise.py": '__version__ = "{v}"\n',
    ".claude/HOOKS-DAEMON.md": "> Generated (v{v}) by `generate-docs`.\n",
    "uv.lock": 'name = "claude-code-hooks-daemon"\nversion = "{v}"\n',
}


def _make_repo(tmp_path: Path, version: str, overrides: dict[str, str] | None = None) -> Path:
    """Create a git repo with every registered file declaring ``version``."""
    files = {**_SAMPLES, **(overrides or {})}
    for rel, template in files.items():
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(template.format(v=version), encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    return tmp_path


class TestChecksAreNotVacuous:
    """Each check fails on a repository that has the defect."""

    def test_clean_repo_passes_both_checks(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path, "9.9.9")
        assert declared_version_mismatches(repo, "9.9.9") == []
        assert unregistered_version_carriers(repo, "9.9.9") == []

    def test_a_file_pinned_at_an_old_version_is_reported(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path, "9.9.9")
        (repo / "uv.lock").write_text(_SAMPLES["uv.lock"].format(v=_OLD_VERSION), encoding="utf-8")
        assert declared_version_mismatches(repo, "9.9.9") == [
            f"uv.lock: declares {_OLD_VERSION}, expected 9.9.9"
        ]

    def test_a_missing_declaration_is_reported(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path, "9.9.9")
        (repo / "README.md").write_text("no badge here\n", encoding="utf-8")
        (problem,) = declared_version_mismatches(repo, "9.9.9")
        assert problem.startswith("README.md: no version declaration")

    def test_an_unregistered_new_carrier_is_reported(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path, "9.9.9")
        (repo / "docs").mkdir()
        (repo / "docs" / "new.txt").write_text("release 9.9.9\n", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
        assert unregistered_version_carriers(repo, "9.9.9") == ["docs/new.txt"]

    def test_historical_trees_and_other_versions_are_not_reported(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path, "9.9.9")
        (repo / "CLAUDE" / "Plan").mkdir(parents=True)
        (repo / "CLAUDE" / "Plan" / "p.md").write_text("9.9.9\n", encoding="utf-8")
        (repo / "other.txt").write_text("9.9.90 and 19.9.9 and 9.9.9.1\n", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
        assert unregistered_version_carriers(repo, "9.9.9") == []
