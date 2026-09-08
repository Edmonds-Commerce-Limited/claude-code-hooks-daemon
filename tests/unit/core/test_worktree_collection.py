"""Reading worktree state out of git, with failures that stay refusals.

`is_reapable` is only as safe as what it is fed. The collector's job is to turn
git's output into a `WorktreeState`, and its one hard requirement is that a git
call it could not complete must produce a state the predicate REFUSES — never a
state that happens to look clean. A collector that reported "0 commits ahead"
when `rev-list` failed would turn an unreadable worktree into a deletable one
(Plan 00349).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from claude_code_hooks_daemon.core.worktree_reaping import (
    UNKNOWN_COUNT,
    collect_worktree_states,
    is_reapable,
)

_LISTING = """worktree /repo
HEAD abc123
branch refs/heads/main

worktree /repo/.claude/worktrees/agent-aaa-111
HEAD def456
branch refs/heads/agent-aaa-111

worktree /repo/untracked/worktrees/agent-bbb-222
HEAD 789abc
branch refs/heads/agent-bbb-222
"""


def _ok(stdout: str) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], 0, stdout, "")


def _fail(stderr: str = "boom") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], 1, "", stderr)


class _FakeGit:
    """Answers by subcommand, so tests state intent rather than argv order."""

    def __init__(self, **answers: subprocess.CompletedProcess[str]) -> None:
        self._answers = answers
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, cwd: Path, *args: str, **_: object) -> subprocess.CompletedProcess[str]:
        self.calls.append(args)
        if args[0] == "worktree":
            return self._answers.get("listing", _ok(_LISTING))
        if args[0] == "status":
            return self._answers.get("status", _ok(""))
        if args[0] == "rev-list":
            return self._answers.get("rev_list", _ok("0\n"))
        if args[0] == "cherry":
            return self._answers.get("cherry", _ok(""))
        raise AssertionError(f"unexpected git call: {args}")


class TestWhichWorktreesAreCollected:
    def test_the_main_checkout_is_not_one_of_them(self) -> None:
        """`/repo` itself is in the listing and must never be a reap candidate."""
        states = collect_worktree_states(Path("/repo"), "main", run_fn=_FakeGit())
        assert [s.name for s in states] == ["agent-aaa-111", "agent-bbb-222"]

    def test_both_sanctioned_worktree_locations_are_read(self) -> None:
        """`.claude/worktrees/` and `untracked/worktrees/` are both in use."""
        states = collect_worktree_states(Path("/repo"), "main", run_fn=_FakeGit())
        assert len(states) == 2

    def test_an_unlistable_repo_yields_nothing_rather_than_guessing(self) -> None:
        git = _FakeGit(listing=_fail("not a git repository"))
        assert collect_worktree_states(Path("/repo"), "main", run_fn=git) == ()


class TestTheCleanReading:
    def test_a_clean_worktree_collects_as_reapable(self) -> None:
        states = collect_worktree_states(Path("/repo"), "main", run_fn=_FakeGit())
        assert all(is_reapable(state) for state in states)

    def test_status_lines_become_paths_without_their_status_prefix(self) -> None:
        git = _FakeGit(status=_ok("A  .claude/ccy/CLAUDE.md\n?? untracked.txt\n"))
        state = collect_worktree_states(Path("/repo"), "main", run_fn=git)[0]
        assert state.uncommitted_paths == (".claude/ccy/CLAUDE.md", "untracked.txt")

    def test_counts_are_read_from_git_not_inferred(self) -> None:
        git = _FakeGit(rev_list=_ok("211\n"), cherry=_ok("+ 1d49da27 subject\n- aaa other\n"))
        state = collect_worktree_states(Path("/repo"), "main", run_fn=git)[0]
        assert state.commits_ahead_of_base == 211
        assert state.unlanded_patches == 1

    def test_a_cherry_line_marked_minus_is_a_landed_patch(self) -> None:
        """`-` means git found an equivalent patch on the base."""
        git = _FakeGit(cherry=_ok("- aaa landed\n- bbb landed\n"))
        state = collect_worktree_states(Path("/repo"), "main", run_fn=git)[0]
        assert state.unlanded_patches == 0


class TestAFailedGitCallIsNeverReadAsClean:
    """The one property that makes the collector safe to act on."""

    def test_a_failed_status_refuses(self) -> None:
        git = _FakeGit(status=_fail())
        state = collect_worktree_states(Path("/repo"), "main", run_fn=git)[0]
        assert not is_reapable(state)

    def test_a_failed_rev_list_refuses(self) -> None:
        git = _FakeGit(rev_list=_fail())
        state = collect_worktree_states(Path("/repo"), "main", run_fn=git)[0]
        assert not is_reapable(state)
        assert state.commits_ahead_of_base == UNKNOWN_COUNT

    def test_a_failed_cherry_refuses(self) -> None:
        git = _FakeGit(cherry=_fail())
        state = collect_worktree_states(Path("/repo"), "main", run_fn=git)[0]
        assert not is_reapable(state)
        assert state.unlanded_patches == UNKNOWN_COUNT

    def test_unparseable_count_output_refuses(self) -> None:
        """git exited 0 but said something no integer can be read out of."""
        git = _FakeGit(rev_list=_ok("not a number\n"))
        state = collect_worktree_states(Path("/repo"), "main", run_fn=git)[0]
        assert not is_reapable(state)

    def test_the_unknown_sentinel_is_negative_so_it_can_never_look_clean(self) -> None:
        assert UNKNOWN_COUNT < 0


class TestAgainstThisRepository:
    """A real run, reading only — this repo carries the worktrees in question."""

    def test_it_classifies_without_removing_anything(self) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        states = collect_worktree_states(repo_root, "main")
        assert states, "no worktrees found; this test is vacuous if that is wrong"
        assert all(state.name.startswith("agent-") for state in states)
        assert repo_root.is_dir()
