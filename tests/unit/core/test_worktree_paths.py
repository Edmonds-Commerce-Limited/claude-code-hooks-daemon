"""Unit tests for worktree-aware path classification helpers."""

from __future__ import annotations

from pathlib import Path

from claude_code_hooks_daemon.core.worktree_paths import (
    WORKTREE_DIR_PATTERNS,
    effective_project_relative_path,
    enclosing_checkout,
)


def test_patterns_cover_both_worktree_locations() -> None:
    assert "untracked/worktrees/" in WORKTREE_DIR_PATTERNS
    assert ".claude/worktrees/" in WORKTREE_DIR_PATTERNS


def test_dot_claude_worktree_path_rerooted_to_worktree(tmp_path: Path) -> None:
    abs_path = str(tmp_path / ".claude/worktrees/agent-X/CLAUDE/LLM-UPDATE.md")
    assert effective_project_relative_path(abs_path, tmp_path) == "CLAUDE/LLM-UPDATE.md"


def test_untracked_worktree_path_rerooted_to_worktree(tmp_path: Path) -> None:
    abs_path = str(tmp_path / "untracked/worktrees/agent-Y/CLAUDE/Plan/00001-foo/PLAN.md")
    assert effective_project_relative_path(abs_path, tmp_path) == "CLAUDE/Plan/00001-foo/PLAN.md"


def test_non_worktree_path_relative_to_project_root(tmp_path: Path) -> None:
    abs_path = str(tmp_path / "CLAUDE/LLM-UPDATE.md")
    assert effective_project_relative_path(abs_path, tmp_path) == "CLAUDE/LLM-UPDATE.md"


def test_disallowed_worktree_path_still_rerooted_not_bypassed(tmp_path: Path) -> None:
    # Re-rooting must not become a blanket bypass: a junk location inside a
    # worktree must classify to that same junk location relative to the
    # worktree root (so the caller's allow/block rules still reject it).
    abs_path = str(tmp_path / ".claude/worktrees/agent-Z/random/notes.md")
    assert effective_project_relative_path(abs_path, tmp_path) == "random/notes.md"


def test_path_outside_project_returns_none(tmp_path: Path) -> None:
    abs_path = "/somewhere/totally/else/file.md"
    assert effective_project_relative_path(abs_path, tmp_path) is None


def test_worktree_root_marker_file_itself(tmp_path: Path) -> None:
    # A file directly at the worktree root re-roots to just its own name.
    abs_path = str(tmp_path / ".claude/worktrees/agent-X/README.md")
    assert effective_project_relative_path(abs_path, tmp_path) == "README.md"


class TestEnclosingCheckout:
    """Plan 00461: a guard that prints a remedy needs the checkout ROOT, not
    just the path relative to it, so the command it names acts on that checkout."""

    def test_a_worktree_path_names_the_worktree_root(self, tmp_path: Path) -> None:
        abs_path = tmp_path / "untracked/worktrees/wt-a/CLAUDE/Plan/00001-x/PLAN.md"

        located = enclosing_checkout(str(abs_path), tmp_path)

        assert located is not None
        root, relative = located
        assert root == (tmp_path / "untracked/worktrees/wt-a").resolve()
        assert str(relative) == "CLAUDE/Plan/00001-x/PLAN.md"

    def test_a_main_checkout_path_names_the_project_root(self, tmp_path: Path) -> None:
        located = enclosing_checkout(str(tmp_path / "CLAUDE/Plan/README.md"), tmp_path)

        assert located == (tmp_path.resolve(), Path("CLAUDE/Plan/README.md"))

    def test_outside_the_project_is_none(self, tmp_path: Path) -> None:
        assert enclosing_checkout("/elsewhere/CLAUDE/Plan/x.md", tmp_path) is None

    def test_a_bare_worktree_marker_is_none(self, tmp_path: Path) -> None:
        assert enclosing_checkout(str(tmp_path / "untracked/worktrees/wt-a"), tmp_path) is None

    def test_agrees_with_effective_project_relative_path(self, tmp_path: Path) -> None:
        abs_path = str(tmp_path / ".claude/worktrees/agent-X/CLAUDE/LLM-UPDATE.md")
        located = enclosing_checkout(abs_path, tmp_path)
        assert located is not None
        assert str(located[1]) == effective_project_relative_path(abs_path, tmp_path)
