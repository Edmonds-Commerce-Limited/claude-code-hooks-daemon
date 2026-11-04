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

import pytest

from claude_code_hooks_daemon.config.models import BranchesConfig
from claude_code_hooks_daemon.core import worktree_reaping
from claude_code_hooks_daemon.core.branch_records import write_creator
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
    """The branch LISTING must read full refs (Plan 00254): `:short` yields the
    shortest UNAMBIGUOUS name, so a branch sharing its name with a tag comes
    back as `heads/<name>` and every membership test silently goes false.

    The DELETE itself is a different command with a different constraint —
    see `TestTheDeleteAgainstRealGitSemantics` below, corrected in Plan 00372.
    """

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

    def test_the_delete_addresses_the_branch_by_its_bare_name(self) -> None:
        """`git branch -d` resolves only inside `refs/heads/` and REJECTS an
        already-qualified `refs/heads/<name>` argument outright — verified
        live (Plan 00372). The bare name is unambiguous FOR THIS COMMAND: it
        cannot resolve a same-named tag, because `branch -d` never looks
        outside `refs/heads/` in the first place.
        """
        git = _FakeGit()
        orphans = {b.name: b for b in collect_orphaned_branches(Path("/repo"), "main", run_fn=git)}
        prune_branch(Path("/repo"), orphans["agent-orphan-2"], run_fn=git)
        assert git.deletions == [("branch", "-d", "agent-orphan-2")]


class TestTheDeleteAgainstRealGitSemantics:
    """`_FakeGit` above always answers "success" no matter the argv, so it
    never caught the live bug: `git branch -d refs/heads/<name>` genuinely
    fails with "not found", confirmed against a real git binary (Plan 00372).
    """

    class _RealisticFakeGit:
        def __init__(
            self, listing: str = _ALL_AGENT_BRANCHES, merged: str = _MERGED_AGENT_BRANCHES
        ) -> None:
            self.calls: list[tuple[str, ...]] = []
            self._listing = listing
            self._merged = merged

        def __call__(self, cwd: Path, *args: str, **_: object) -> subprocess.CompletedProcess[str]:
            self.calls.append(args)
            if args[0] == "worktree":
                return _ok(_LISTING)
            if args[0] == "branch" and "--merged" in args:
                return _ok(self._merged)
            if args[0] == "branch" and "-d" in args:
                target = args[-1]
                if target.startswith("refs/heads/"):
                    return _fail(f"error: branch '{target}' not found.")
                return _ok("")
            if args[0] == "branch":
                return _ok(self._listing)
            raise AssertionError(f"unexpected git call: {args}")

    def test_the_merged_orphan_is_actually_deleted(self) -> None:
        git = self._RealisticFakeGit()
        orphans = {b.name: b for b in collect_orphaned_branches(Path("/repo"), "main", run_fn=git)}
        outcome = prune_branch(Path("/repo"), orphans["agent-orphan-2"], run_fn=git)
        assert outcome.deleted
        assert outcome.detail == "deleted branch agent-orphan-2"


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


class TestWorktreeCreateNamesAreEligible:
    """Orphan pruning covers the ``worktree_create`` ``<slug>-<8 hex>`` names as
    well as ``agent-*`` (Plan 00558 Task 3.2, DESIGN.md section 8)."""

    _MIXED = (
        "refs/heads/agent-orphan-2\nrefs/heads/fix-auth-1a2b3c4d\n"
        "refs/heads/feature-x\nrefs/heads/main\n"
    )

    def test_a_worktree_create_name_is_an_orphan_and_a_hand_name_is_not(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            worktree_reaping, "creator_route", lambda _repo, _name: "worktree_create"
        )
        git = _FakeGit(branches=_ok(self._MIXED), merged=_ok("refs/heads/fix-auth-1a2b3c4d\n"))
        orphans = collect_orphaned_branches(Path("/repo"), "main", run_fn=git)
        found = {b.name: b.merged_into_base for b in orphans}
        assert found == {"agent-orphan-2": False, "fix-auth-1a2b3c4d": True}


class TestOnlyRecordedWorktreeCreateBranchesArePrunable:
    """A `<slug>-<8 hex>` shape alone must never make an ordinary branch prunable."""

    @staticmethod
    def _repo(tmp_path: Path, names: list[str]) -> Path:
        def git(*args: str) -> None:
            subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

        git("init", "-q", "-b", "main")
        git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "i")
        for name in names:
            git("branch", name)
        return tmp_path

    def test_ordinary_names_with_the_hex_shape_are_not_candidates(self, tmp_path: Path) -> None:
        repo = self._repo(tmp_path, ["release-20261104", "hotfix-cafebabe"])
        assert collect_orphaned_branches(repo, "main", config=BranchesConfig()) == ()

    def test_a_recorded_worktree_create_branch_is_a_candidate(self, tmp_path: Path) -> None:
        repo = self._repo(tmp_path, ["fix-thing-0123abcd"])
        assert write_creator(repo, "fix-thing-0123abcd", "s:", "worktree_create")
        found = collect_orphaned_branches(repo, "main", config=BranchesConfig())
        assert [b.name for b in found] == ["fix-thing-0123abcd"]

    def test_a_protected_name_is_never_a_candidate_even_when_recorded(self, tmp_path: Path) -> None:
        repo = self._repo(tmp_path, ["keep-0123abcd", "line-0123abcd"])
        for name in ("keep-0123abcd", "line-0123abcd"):
            assert write_creator(repo, name, "s:", "worktree_create")
        config = BranchesConfig(protected_names=["keep-*"], integration_lines=["line-*"])
        assert collect_orphaned_branches(repo, "main", config=config) == ()
