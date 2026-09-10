"""Removing a worktree, with git as the second and third safety net.

The predicate decides; git is asked to disagree. `git worktree remove` without
`--force` refuses a dirty worktree, and `git branch -d` (never `-D`) refuses an
unmerged branch — so if `is_reapable` were ever wrong, two independent checks
still stand between it and lost work. That layering is the point: a reap path
whose only safety is the predicate has one bug between it and a deletion
(Plan 00349).

Task 2.3's other half is here too: removing a worktree and leaving its branch
behind only moves the clutter from `git worktree list` to `git branch`.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from claude_code_hooks_daemon.core.worktree_reaping import WorktreeState, reap_worktree

_Completed = subprocess.CompletedProcess[str]


def _ok(stdout: str = "") -> _Completed:
    return subprocess.CompletedProcess([], 0, stdout, "")


def _fail(stderr: str) -> _Completed:
    return subprocess.CompletedProcess([], 1, "", stderr)


def _clean_state(
    name: str = "agent-aaa-111",
    *,
    path: Path | None = None,
    branch: str | None = "agent-aaa-111",
) -> WorktreeState:
    return WorktreeState(
        name=name,
        path=path if path is not None else Path(f"/repo/.claude/worktrees/{name}"),
        branch=branch,
        uncommitted_paths=(),
        commits_ahead_of_base=0,
        unlanded_patches=0,
    )


def _dirty_state(name: str = "agent-bbb-222") -> WorktreeState:
    return WorktreeState(
        name=name,
        path=Path(f"/repo/.claude/worktrees/{name}"),
        branch=name,
        uncommitted_paths=("x.py",),
        commits_ahead_of_base=3,
        unlanded_patches=1,
    )


class _FakeGit:
    def __init__(self, remove: _Completed | None = None, branch: _Completed | None = None) -> None:
        self.remove = remove if remove is not None else _ok()
        self.branch = branch if branch is not None else _ok()
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, cwd: Path, *args: str, **_: object) -> _Completed:
        self.calls.append(args)
        if args[0] == "worktree":
            return self.remove
        if args[0] == "branch":
            return self.branch
        raise AssertionError(f"unexpected git call: {args}")


class TestAWorktreeThePredicateRefusedIsNeverTouched:
    def test_no_git_command_runs_at_all(self) -> None:
        git = _FakeGit()
        reap_worktree(Path("/repo"), _dirty_state(), run_fn=git)
        assert git.calls == []

    def test_the_outcome_carries_the_refusal_reason(self) -> None:
        outcome = reap_worktree(Path("/repo"), _dirty_state(), run_fn=_FakeGit())
        assert not outcome.removed
        assert "not safe to reap" in outcome.detail


class TestTheHappyPath:
    def test_the_worktree_and_then_the_branch_are_removed(self) -> None:
        git = _FakeGit()
        outcome = reap_worktree(Path("/repo"), _clean_state(), run_fn=git)
        assert outcome.removed
        assert git.calls[0][:2] == ("worktree", "remove")
        assert git.calls[1][0] == "branch"

    def test_removal_is_never_forced(self) -> None:
        """`--force` would delete a dirty worktree the predicate mis-cleared."""
        git = _FakeGit()
        reap_worktree(Path("/repo"), _clean_state(), run_fn=git)
        assert not any("--force" in call or "-f" in call for call in git.calls)

    def test_the_branch_delete_is_lowercase_d(self) -> None:
        """`-D` force-deletes an unmerged branch, and is a blocked operation."""
        git = _FakeGit()
        reap_worktree(Path("/repo"), _clean_state(), run_fn=git)
        branch_call = next(call for call in git.calls if call[0] == "branch")
        assert "-d" in branch_call
        assert "-D" not in branch_call


class TestWhatIsAddressed:
    """The path and the branch both come from the listing, never from the name."""

    def test_the_removal_names_the_path_the_state_carries(self) -> None:
        git = _FakeGit()
        state = _clean_state(path=Path("/repo/untracked/worktrees/agent-aaa-111"))
        reap_worktree(Path("/repo"), state, run_fn=git)
        assert git.calls[0][2] == "/repo/untracked/worktrees/agent-aaa-111"

    def test_the_branch_delete_names_the_attached_branch_not_the_directory(self) -> None:
        git = _FakeGit()
        reap_worktree(Path("/repo"), _clean_state(branch="feature/other"), run_fn=git)
        branch_call = next(call for call in git.calls if call[0] == "branch")
        assert branch_call[-1] == "feature/other"

    def test_the_branch_is_addressed_by_its_bare_name_not_a_qualified_ref(self) -> None:
        """`git branch -d` resolves only inside `refs/heads/` and REJECTS a
        `refs/heads/<name>`-qualified argument outright (Plan 00372, verified
        live) -- unlike `rev-parse`/`cherry`/`merge-base`, which is what
        `branch_ref()`'s tag-ambiguity rationale (Plan 00254) actually covers.
        """
        git = _FakeGit()
        reap_worktree(Path("/repo"), _clean_state(), run_fn=git)
        branch_call = next(call for call in git.calls if call[0] == "branch")
        assert branch_call[-1] == "agent-aaa-111"


class TestTheBranchDeleteAgainstRealGitSemantics:
    """`_FakeGit` above always answers "success" no matter the argv, which is
    exactly why it never caught this: it modelled the call succeeding, not
    the argv real git accepts. `_RealisticFakeGit` mimics the one constraint
    that matters here, confirmed against a real git binary before writing
    this test: `git branch -d refs/heads/<name>` fails with "not found",
    while `git branch -d <name>` succeeds.
    """

    class _RealisticFakeGit:
        def __init__(self) -> None:
            self.calls: list[tuple[str, ...]] = []

        def __call__(self, cwd: Path, *args: str, **_: object) -> _Completed:
            self.calls.append(args)
            if args[0] == "worktree":
                return _ok()
            if args[0] == "branch":
                target = args[-1]
                if target.startswith("refs/heads/"):
                    return _fail(f"error: branch '{target}' not found.")
                return _ok()
            raise AssertionError(f"unexpected git call: {args}")

    def test_the_live_incident_is_fixed(self) -> None:
        """Exact live observation this reproduces: `REAPED removed ..., but
        git kept the branch worktree-plan-00367: error: branch
        'refs/heads/worktree-plan-00367' not found.` -- self-contradicting,
        since "kept" and "not found" cannot both be true, and the delete
        never had a chance to succeed because it was never asked correctly.
        """
        git = self._RealisticFakeGit()
        outcome = reap_worktree(Path("/repo"), _clean_state(), run_fn=git)
        assert outcome.removed
        assert outcome.branch_removed
        assert (
            outcome.detail
            == "removed /repo/.claude/worktrees/agent-aaa-111 and its branch agent-aaa-111"
        )

    def test_the_failure_message_never_contradicts_itself(self) -> None:
        git = self._RealisticFakeGit()
        outcome = reap_worktree(Path("/repo"), _clean_state(), run_fn=git)
        assert "not found" not in outcome.detail
        assert "kept" not in outcome.detail

    def test_a_worktree_with_no_branch_gets_no_branch_delete(self) -> None:
        """Deleting by directory name could hit an unrelated same-named branch."""
        git = _FakeGit()
        outcome = reap_worktree(Path("/repo"), _clean_state(branch=None), run_fn=git)
        assert outcome.removed
        assert not outcome.branch_removed
        assert not any(call[0] == "branch" for call in git.calls)
        assert "no branch" in outcome.detail


class TestGitOverrulingThePredicate:
    def test_a_refused_removal_is_reported_not_retried_with_force(self) -> None:
        git = _FakeGit(remove=_fail("contains modified or untracked files"))
        outcome = reap_worktree(Path("/repo"), _clean_state(), run_fn=git)
        assert not outcome.removed
        assert "modified or untracked" in outcome.detail
        assert len(git.calls) == 1, "it must not go on to touch the branch"

    def test_a_refused_branch_delete_still_counts_the_worktree_as_removed(self) -> None:
        """The expensive part succeeded; the leftover branch is reported."""
        git = _FakeGit(branch=_fail("not fully merged"))
        outcome = reap_worktree(Path("/repo"), _clean_state(), run_fn=git)
        assert outcome.removed
        assert not outcome.branch_removed
        assert "not fully merged" in outcome.detail


class TestTheDryRun:
    def test_a_dry_run_runs_no_git_command(self) -> None:
        git = _FakeGit()
        outcome = reap_worktree(Path("/repo"), _clean_state(), run_fn=git, dry_run=True)
        assert git.calls == []
        assert not outcome.removed
        assert "would remove" in outcome.detail.lower()

    def test_a_dry_run_names_the_real_path_and_branch(self) -> None:
        outcome = reap_worktree(
            Path("/repo"),
            _clean_state(path=Path("/repo/untracked/worktrees/agent-aaa-111"), branch="wip/x"),
            run_fn=_FakeGit(),
            dry_run=True,
        )
        assert "/repo/untracked/worktrees/agent-aaa-111" in outcome.detail
        assert "wip/x" in outcome.detail

    def test_a_dry_run_of_a_refused_worktree_still_explains_the_refusal(self) -> None:
        outcome = reap_worktree(Path("/repo"), _dirty_state(), run_fn=_FakeGit(), dry_run=True)
        assert "not safe to reap" in outcome.detail
