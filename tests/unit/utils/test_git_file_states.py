"""Tests for the shared git file-state scan (Plan 00459).

``secret_file_hygiene_checker`` and ``gitignore_safety_checker`` both need to
know, for every path git knows about, whether it is tracked and whether an
ignore rule matches it -- including a TRACKED file an ignore rule matches,
which ``--others`` alone never reports.
"""

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.utils import git_file_states
from claude_code_hooks_daemon.utils.git_file_states import (
    gitignore_negation,
    scan_git_file_states,
    scan_git_file_states_for_event,
    unignore_advice,
)
from claude_code_hooks_daemon.utils.secret_file_matching import protected_among


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
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


class TestForeignTreesArePruned:
    """N289b: an ignored directory that is a virtualenv, a package-manager
    tree or a nested checkout holds files that are not this project's. They
    outnumber the project's own files by orders of magnitude, so judging each
    one is what made the SessionStart sweeps overrun their budget."""

    @pytest.fixture()
    def tree(self, repo: Path) -> Path:
        (repo / ".gitignore").write_text("ignored.txt\n.venv/\nnode_modules/\nscratch/\nvenv-x/\n")
        for name in (".venv/lib/pkg", "node_modules/pkg", "scratch/copy", "venv-x/lib"):
            (repo / name).mkdir(parents=True)
            (repo / name / "mod.py").write_text("x\n")
        (repo / ".venv" / "pyvenv.cfg").write_text("home = /usr\n")
        (repo / "venv-x" / "pyvenv.cfg").write_text("home = /usr\n")
        (repo / "scratch" / "copy" / "own.txt").write_text("x\n")
        return repo

    def test_a_virtualenv_is_not_judged(self, tree: Path) -> None:
        states = scan_git_file_states(tree)
        assert states is not None
        assert not any(p.startswith((".venv/", "venv-x/")) for p in states.all_paths)
        assert not any(p.startswith((".venv/", "venv-x/")) for p in states.ignored_untracked)

    def test_a_package_tree_is_not_judged(self, tree: Path) -> None:
        states = scan_git_file_states(tree)
        assert states is not None
        assert not any(p.startswith("node_modules/") for p in states.all_paths)

    def test_an_ignored_directory_with_no_foreign_marker_is_still_judged(self, tree: Path) -> None:
        """Detection of the project's own files is unchanged."""
        states = scan_git_file_states(tree)
        assert states is not None
        assert "scratch/copy/own.txt" in states.ignored_untracked
        assert "scratch/copy/own.txt" in states.all_paths

    def test_a_nested_package_directory_is_pruned_at_any_depth(self, tree: Path) -> None:
        (tree / "scratch" / "copy" / "node_modules").mkdir()
        (tree / "scratch" / "copy" / "node_modules" / "dep.js").write_text("x\n")
        states = scan_git_file_states(tree)
        assert states is not None
        assert "scratch/copy/node_modules/dep.js" not in states.all_paths

    def test_a_tracked_file_inside_such_a_directory_is_still_judged(self, tree: Path) -> None:
        _git(tree, "add", "-f", "node_modules/pkg/mod.py")
        states = scan_git_file_states(tree)
        assert states is not None
        assert "node_modules/pkg/mod.py" in states.tracked
        assert "node_modules/pkg/mod.py" in states.all_paths

    def test_a_nested_checkout_is_one_entry_not_its_files(self, tree: Path) -> None:
        nested = tree / "scratch" / "checkout"
        nested.mkdir()
        _git(nested, "init")
        (nested / "inner.txt").write_text("x\n")
        states = scan_git_file_states(tree)
        assert states is not None
        assert not any(
            p.startswith("scratch/checkout/") and p != "scratch/checkout/" for p in states.all_paths
        )

    def test_the_visible_files_are_unaffected(self, tree: Path) -> None:
        states = scan_git_file_states(tree)
        assert states is not None
        assert {"visible.txt", "tracked.txt"} <= states.all_paths


class TestScanIsSharedWithinOneEvent:
    """N289b: both SessionStart sweeps scanned the repository and judged every
    path separately. Within ONE event dispatch they now share one scan and one
    protection verdict; a later event rescans, so nothing goes stale."""

    def test_the_same_event_reuses_the_scan(self, repo: Path) -> None:
        event: dict[str, object] = {"hook_event_name": "SessionStart"}
        with patch.object(
            git_file_states, "scan_git_file_states", wraps=git_file_states.scan_git_file_states
        ) as scan:
            first = scan_git_file_states_for_event(repo, event)
            second = scan_git_file_states_for_event(repo, event)
        assert first is second
        assert scan.call_count == 1

    def test_a_new_event_rescans(self, repo: Path) -> None:
        first = scan_git_file_states_for_event(repo, {"hook_event_name": "SessionStart"})
        (repo / "added_later.txt").write_text("x\n")
        second = scan_git_file_states_for_event(repo, {"hook_event_name": "SessionStart"})
        assert first is not second
        assert second is not None
        assert "added_later.txt" in second.all_paths

    def test_another_project_root_is_never_served_the_cached_scan(
        self, repo: Path, tmp_path: Path
    ) -> None:
        other = tmp_path / "other"
        other.mkdir()
        _git(other, "init")
        (other / "only_here.txt").write_text("x\n")
        event: dict[str, object] = {}
        first = scan_git_file_states_for_event(repo, event)
        second = scan_git_file_states_for_event(other, event)
        assert second is not first
        assert second is not None
        assert "only_here.txt" in second.all_paths

    def test_not_a_repository_is_none(self, tmp_path: Path) -> None:
        assert scan_git_file_states_for_event(tmp_path, {}) is None


class TestProtectedRelpaths:
    PATTERNS = ("*.tok*",)

    def test_names_the_protected_paths_in_order(self, repo: Path) -> None:
        (repo / "a.tok").write_text("x\n")
        (repo / "sub" / "b.tok2").write_text("x\n")
        states = scan_git_file_states(repo)
        assert states is not None
        assert states.protected_relpaths(repo, self.PATTERNS) == ["a.tok", "sub/b.tok2"]

    def test_is_computed_once_per_pattern_set(self, repo: Path) -> None:
        (repo / "a.tok").write_text("x\n")
        states = scan_git_file_states(repo)
        assert states is not None
        with patch(
            "claude_code_hooks_daemon.utils.git_file_states.protected_among",
            wraps=protected_among,
        ) as judged:
            states.protected_relpaths(repo, self.PATTERNS)
            states.protected_relpaths(repo, self.PATTERNS)
            states.protected_relpaths(repo, ("*.other*",))
        assert judged.call_count == 2


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
