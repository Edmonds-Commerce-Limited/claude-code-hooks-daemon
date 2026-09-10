"""A branch whose worktree has already gone is invisible to the reaper.

`collect_worktree_states` enumerates candidates from `git worktree list`, so the
only branch it can ever see is one that still has a worktree attached. Reaping
Plan 00349's 21 worktrees removed 15 branches with them and left three `agent-*`
branches behind that no worktree points at — each 0 commits ahead of `main`, and
none of them in that reap's output (Plan 00352).

The safety argument here is genuinely weaker than the worktree one, and that is
the point rather than an oversight: an orphaned branch has no working tree, so
there is no uncommitted state to lose, and `git branch -d` already refuses
anything not fully merged. Two independent checks, same as the worktree path.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from claude_code_hooks_daemon.core.worktree_reaping import (
    OrphanedBranch,
    collect_orphaned_branches,
    prune_branch,
)

_LISTING = """worktree /repo
HEAD abc123
branch refs/heads/main

worktree /repo/.claude/worktrees/agent-attached-1
HEAD def456
branch refs/heads/agent-attached-1
"""

# Full refs, because that is what `--format=%(refname)` yields and what this
# code must ask for. `%(refname:short)` returns the shortest UNAMBIGUOUS name,
# so a branch shadowed by a same-named tag comes back as `heads/<name>` — a
# string no git command accepts, which breaks every membership test and every
# `git branch -d` built from it (Plan 00254, reproduced: a tag shadowing a
# branch got the branch force-deleted while it held the only copy of a file).
_ALL_AGENT_BRANCHES = (
    "refs/heads/agent-attached-1\nrefs/heads/agent-orphan-2\nrefs/heads/agent-orphan-3\n"
)
_MERGED_AGENT_BRANCHES = "refs/heads/agent-attached-1\nrefs/heads/agent-orphan-2\n"


def _ok(stdout: str) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], 0, stdout, "")


def _fail(stderr: str = "boom") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], 1, "", stderr)


class _FakeGit:
    """A repo with one attached agent branch and two orphans, one unmerged."""

    def __init__(self, **overrides: subprocess.CompletedProcess[str]) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.overrides = overrides

    def __call__(self, cwd: Path, *args: str, **_: object) -> subprocess.CompletedProcess[str]:
        self.calls.append(args)
        if args[0] == "worktree":
            return self.overrides.get("worktree", _ok(_LISTING))
        if args[0] == "branch" and "--merged" in args:
            return self.overrides.get("merged", _ok(_MERGED_AGENT_BRANCHES))
        if args[0] == "branch" and "-d" in args:
            return self.overrides.get("delete", _ok(""))
        if args[0] == "branch":
            return self.overrides.get("branches", _ok(_ALL_AGENT_BRANCHES))
        raise AssertionError(f"unexpected git call: {args}")

    @property
    def deletions(self) -> list[tuple[str, ...]]:
        return [call for call in self.calls if call[0] == "branch" and "-d" in call]


class TestWhatCountsAsOrphaned:
    def test_a_branch_with_a_worktree_is_not_orphaned(self) -> None:
        names = [
            b.name for b in collect_orphaned_branches(Path("/repo"), "main", run_fn=_FakeGit())
        ]
        assert "agent-attached-1" not in names

    def test_the_two_without_worktrees_are(self) -> None:
        names = [
            b.name for b in collect_orphaned_branches(Path("/repo"), "main", run_fn=_FakeGit())
        ]
        assert names == ["agent-orphan-2", "agent-orphan-3"]

    def test_merge_status_is_recorded_per_branch(self) -> None:
        found = {
            b.name: b.merged_into_base
            for b in collect_orphaned_branches(Path("/repo"), "main", run_fn=_FakeGit())
        }
        assert found == {"agent-orphan-2": True, "agent-orphan-3": False}


class TestAmbiguousNamesCannotSlipThrough:
    """A same-named tag must not be able to redirect a delete (Plan 00254)."""

    def test_the_listing_asks_for_the_full_refname(self) -> None:
        git = _FakeGit()
        collect_orphaned_branches(Path("/repo"), "main", run_fn=git)
        formats = [arg for call in git.calls for arg in call if arg.startswith("--format=")]
        assert formats
        assert all(
            fmt == "--format=%(refname)" for fmt in formats
        ), f"`:short` yields the shortest UNAMBIGUOUS name, not a branch name: {formats}"

    def test_the_reported_name_is_the_bare_branch(self) -> None:
        found = collect_orphaned_branches(Path("/repo"), "main", run_fn=_FakeGit())
        assert [b.name for b in found] == ["agent-orphan-2", "agent-orphan-3"]

    def test_the_delete_addresses_the_branch_unambiguously(self) -> None:
        """`git branch -d agent-orphan-2` could resolve a tag of that name."""
        git = _FakeGit()
        orphans = {b.name: b for b in collect_orphaned_branches(Path("/repo"), "main", run_fn=git)}
        prune_branch(Path("/repo"), orphans["agent-orphan-2"], run_fn=git)
        assert git.deletions == [("branch", "-d", "refs/heads/agent-orphan-2")]


class TestAFailedGitCallIsNeverReadAsSafe:
    def test_an_unreadable_worktree_listing_yields_no_candidates(self) -> None:
        """Without the listing, every branch would look orphaned."""
        git = _FakeGit(worktree=_fail())
        assert collect_orphaned_branches(Path("/repo"), "main", run_fn=git) == ()

    def test_an_unreadable_branch_list_yields_no_candidates(self) -> None:
        git = _FakeGit(branches=_fail())
        assert collect_orphaned_branches(Path("/repo"), "main", run_fn=git) == ()

    def test_an_unreadable_merged_list_makes_every_branch_unmerged(self) -> None:
        """Unknown merge status must refuse, not default to safe."""
        git = _FakeGit(merged=_fail())
        found = collect_orphaned_branches(Path("/repo"), "main", run_fn=git)
        assert found
        assert not any(branch.merged_into_base for branch in found)


class TestPruning:
    @staticmethod
    def _orphans(git: _FakeGit) -> dict[str, OrphanedBranch]:
        return {b.name: b for b in collect_orphaned_branches(Path("/repo"), "main", run_fn=git)}

    def test_a_dry_run_deletes_nothing(self) -> None:
        git = _FakeGit()
        prune_branch(Path("/repo"), self._orphans(git)["agent-orphan-2"], run_fn=git, dry_run=True)
        assert git.deletions == []

    def test_a_dry_run_still_says_what_it_would_do(self) -> None:
        git = _FakeGit()
        outcome = prune_branch(
            Path("/repo"), self._orphans(git)["agent-orphan-2"], run_fn=git, dry_run=True
        )
        assert not outcome.deleted
        assert "agent-orphan-2" in outcome.detail

    def test_a_merged_branch_is_deleted_with_lowercase_d(self) -> None:
        """`-D` would override git's own refusal, which is the second net."""
        git = _FakeGit()
        outcome = prune_branch(Path("/repo"), self._orphans(git)["agent-orphan-2"], run_fn=git)
        assert outcome.deleted
        assert len(git.deletions) == 1
        assert "-D" not in git.deletions[0]

    def test_an_unmerged_branch_gets_no_git_command_at_all(self) -> None:
        git = _FakeGit()
        outcome = prune_branch(Path("/repo"), self._orphans(git)["agent-orphan-3"], run_fn=git)
        assert not outcome.deleted
        assert git.deletions == []

    def test_the_refusal_says_why(self) -> None:
        git = _FakeGit()
        outcome = prune_branch(Path("/repo"), self._orphans(git)["agent-orphan-3"], run_fn=git)
        assert "not fully merged" in outcome.detail

    def test_a_git_refusal_is_reported_not_retried(self) -> None:
        """If git disagrees with the predicate, git wins."""
        git = _FakeGit(delete=_fail("error: branch is not fully merged"))
        outcome = prune_branch(Path("/repo"), self._orphans(git)["agent-orphan-2"], run_fn=git)
        assert not outcome.deleted
        assert "not fully merged" in outcome.detail
        assert not any("-D" in call for call in git.calls)
