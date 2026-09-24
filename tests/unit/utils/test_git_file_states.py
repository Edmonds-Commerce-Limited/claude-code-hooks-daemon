"""Tests for the shared git file-state scan (Plan 00459).

``secret_file_hygiene_checker`` and ``gitignore_safety_checker`` both need to
know, for every path git knows about, whether it is tracked and whether an
ignore rule matches it -- including a TRACKED file an ignore rule matches,
which ``--others`` alone never reports.
"""

import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.utils.git_file_states import (
    gitignore_negation,
    scan_git_file_states,
    unignore_advice,
)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(  # nosec B603 B607 - trusted git binary, fixed argv, test fixture only
        ["git", "-C", str(repo), *args],
        capture_output=True,
        check=True,
        timeout=Timeout.GIT_CONTEXT,
    )


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "sub").mkdir(parents=True)
    _git(root, "init")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "T")
    (root / "tracked.txt").write_text("x\n")
    (root / "sub" / "tracked_ignored.txt").write_text("x\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "initial")
    (root / ".gitignore").write_text("tracked_ignored.txt\nignored.txt\n")
    (root / "ignored.txt").write_text("x\n")
    (root / "visible.txt").write_text("x\n")
    return root


class TestScanGitFileStates:
    def test_tracked(self, repo: Path) -> None:
        states = scan_git_file_states(repo)
        assert states is not None
        assert "tracked.txt" in states.tracked
        assert "sub/tracked_ignored.txt" in states.tracked
        assert "visible.txt" not in states.tracked

    def test_untracked_ignored(self, repo: Path) -> None:
        states = scan_git_file_states(repo)
        assert states is not None
        assert states.ignored_untracked == frozenset({"ignored.txt"})

    def test_tracked_file_matched_by_an_ignore_rule(self, repo: Path) -> None:
        states = scan_git_file_states(repo)
        assert states is not None
        assert states.ignored_tracked == frozenset({"sub/tracked_ignored.txt"})
        assert states.is_ignored("sub/tracked_ignored.txt")
        assert states.is_ignored("ignored.txt")
        assert not states.is_ignored("tracked.txt")

    def test_negation_un_ignores(self, repo: Path) -> None:
        (repo / ".gitignore").write_text("tracked_ignored.txt\n!/sub/tracked_ignored.txt\n")
        states = scan_git_file_states(repo)
        assert states is not None
        assert not states.is_ignored("sub/tracked_ignored.txt")

    def test_all_paths_is_every_state(self, repo: Path) -> None:
        states = scan_git_file_states(repo)
        assert states is not None
        assert {"tracked.txt", "ignored.txt", "visible.txt", ".gitignore"} <= states.all_paths

    def test_not_a_repository(self, tmp_path: Path) -> None:
        plain = tmp_path / "plain"
        plain.mkdir()
        assert scan_git_file_states(plain) is None


class TestGitignoreNegation:
    def test_anchored_at_the_root(self) -> None:
        assert gitignore_negation("a/b.yml") == "!/a/b.yml"
        assert gitignore_negation("b.yml") == "!/b.yml"

    def test_glob_characters_are_escaped(self) -> None:
        assert gitignore_negation("a/[x]*?.yml") == "!/a/\\[x]\\*\\?.yml"

    def test_trailing_space_is_escaped(self) -> None:
        assert gitignore_negation("a.yml ") == "!/a.yml\\ "

    def test_the_line_really_un_ignores_the_file(self, repo: Path) -> None:
        """Proven against git itself, not against our reading of the rules."""
        name = "odd [name]*.txt"
        (repo / name).write_text("x\n")
        (repo / ".gitignore").write_text(f"*.txt\n{gitignore_negation(name)}\n")
        states = scan_git_file_states(repo)
        assert states is not None
        assert not states.is_ignored(name)
        assert states.is_ignored("ignored.txt")

    def test_unignore_advice_names_the_line_and_the_directory_limit(self) -> None:
        advice = unignore_advice("a/b.yml")
        assert "`!/a/b.yml`" in advice
        assert "git check-ignore -v a/b.yml" in advice
        assert "DIRECTORY" in advice
