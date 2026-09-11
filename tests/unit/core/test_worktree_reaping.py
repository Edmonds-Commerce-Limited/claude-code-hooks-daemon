"""What makes an agent worktree safe to remove, decided conservatively.

21 worktrees accumulated in this repo because nothing removes them (Plan
00349). Task 1.1 characterised all 21 and the split drives this predicate:

- **15 clean and strictly behind `main`.** Nothing to lose, trivially reapable.
- **6 with one unlanded commit and one staged file.** Investigated by hand:
  both are accounted for — the commit's work is on `main` under a different
  SHA, and the staged file is a superseded draft of a *gitignored* file. So a
  human can say they are safe.

**The predicate declines those 6 anyway, and that is the point.** Everything
that made them safe came from reading a commit's subject line, checking a plan
folder, and comparing byte counts — judgements a machine cannot make and must
not fake. `git cherry` reports them as unlanded, which from the predicate's
side is indistinguishable from real unlanded work. Unknown ⇒ not reapable;
they get surfaced for a human instead of reaped.

**Plan 00372 found an eighth shape the original 21 never produced: a worktree
with NO history of its own at all**, created moments before the predicate was
asked about it. Every check above passes vacuously — no uncommitted paths, no
commits ahead, no unlanded patches — because a worktree that has just started
looks IDENTICAL to one that finished and went stale. Age and live-process
occupancy are the only signals that tell them apart; see
`TestTheFreshWorktreeGuard` below.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from claude_code_hooks_daemon.core.worktree_reaping import (
    MINIMUM_AGE_SECONDS,
    WorktreeState,
    is_reapable,
    reap_refusal_reason,
)

#: Comfortably clear of the recency window, so every EXISTING test in this
#: file (written before Plan 00372) keeps asserting what it always meant to —
#: this module's age/process axis stays silent unless a test asks otherwise.
_OLD_ENOUGH_SECONDS = MINIMUM_AGE_SECONDS + 1


def _state(
    *,
    name: str = "agent-a01f76f8ba723c1b0-7534cab4",
    uncommitted_paths: tuple[str, ...] = (),
    commits_ahead_of_base: int = 0,
    unlanded_patches: int = 0,
    live_process_pids: tuple[int, ...] = (),
    age_seconds: float | None = _OLD_ENOUGH_SECONDS,
) -> WorktreeState:
    """A clean, fully-merged, long-since-created worktree with nobody in it —
    the only shape that is reapable.
    """
    return WorktreeState(
        name=name,
        path=Path(f"/repo/.claude/worktrees/{name}"),
        branch=name,
        uncommitted_paths=uncommitted_paths,
        commits_ahead_of_base=commits_ahead_of_base,
        unlanded_patches=unlanded_patches,
        live_process_pids=live_process_pids,
        age_seconds=age_seconds,
    )


class TestTheCleanCase:
    def test_a_clean_fully_merged_worktree_is_reapable(self) -> None:
        assert is_reapable(_state())

    def test_being_far_behind_main_is_not_a_reason_to_keep_it(self) -> None:
        """All 15 reapable ones are 249 to 768 commits behind. Behind is stale."""
        assert is_reapable(_state())
        assert reap_refusal_reason(_state()) is None


class TestEverythingElseIsRefused:
    def test_an_uncommitted_file_blocks_it(self) -> None:
        state = _state(uncommitted_paths=(".claude/ccy/CLAUDE.md",))
        assert not is_reapable(state)
        assert ".claude/ccy/CLAUDE.md" in (reap_refusal_reason(state) or "")

    def test_a_staged_file_that_is_gitignored_is_STILL_refused(self) -> None:
        """The six were safe for reasons only a human established.

        Teaching the predicate 'ignored files do not count' would have reaped
        them correctly here and wrongly the first time an agent staged
        something that mattered.
        """
        assert not is_reapable(_state(uncommitted_paths=(".claude/ccy/CLAUDE.md",)))

    def test_a_commit_not_on_the_base_blocks_it(self) -> None:
        state = _state(commits_ahead_of_base=211, unlanded_patches=1)
        assert not is_reapable(state)
        assert "211" in (reap_refusal_reason(state) or "")

    def test_commits_ahead_whose_patches_ALL_landed_are_still_refused(self) -> None:
        """Conservative by construction, and this is where it costs something.

        A rebase makes `main..HEAD` non-empty for work that is fully on `main`.
        The predicate cannot tell that from real divergence, so it refuses.
        """
        assert not is_reapable(_state(commits_ahead_of_base=195, unlanded_patches=0))

    def test_an_unlanded_patch_with_no_commits_ahead_is_refused(self) -> None:
        """Contradictory input is unknown input, and unknown is not reapable."""
        assert not is_reapable(_state(commits_ahead_of_base=0, unlanded_patches=1))

    @pytest.mark.parametrize("ahead", [-1, -100])
    def test_a_nonsensical_count_is_refused_rather_than_trusted(self, ahead: int) -> None:
        """A negative count means the collector failed, not that it is clean."""
        assert not is_reapable(_state(commits_ahead_of_base=ahead))


class TestTheRefusalExplainsItself:
    def test_a_reapable_worktree_has_no_refusal(self) -> None:
        assert reap_refusal_reason(_state()) is None

    def test_the_reason_names_the_worktree(self) -> None:
        state = _state(name="agent-deadbeef-1234", commits_ahead_of_base=3)
        assert "agent-deadbeef-1234" in (reap_refusal_reason(state) or "")

    def test_both_problems_are_reported_not_just_the_first(self) -> None:
        """Fixing one and re-running to discover the other wastes a cycle."""
        state = _state(uncommitted_paths=("a.py",), commits_ahead_of_base=7)
        reason = reap_refusal_reason(state) or ""
        assert "a.py" in reason
        assert "7" in reason


class TestTheRefusalRoutesToWhoeverIsReading:
    """A message that misroutes the work is a defect in the message (Plan 00380).

    The old text said "remove it by hand". Five worktrees — every one with zero
    commits unmerged to main — were handed to the owner across several sessions
    on the strength of that phrase, while no rule blocked their removal at all.
    """

    def test_it_does_not_claim_a_human_is_required(self) -> None:
        reason = reap_refusal_reason(_state(uncommitted_paths=("a.py",))) or ""
        lowered = reason.lower()
        assert "by hand" not in lowered
        assert "need a human" not in lowered
        assert "needs a human" not in lowered

    def test_it_says_removal_is_not_blocked(self) -> None:
        """The false belief was that a hook reserved this to a human."""
        reason = reap_refusal_reason(_state(uncommitted_paths=("a.py",))) or ""
        assert "no hook blocks" in reason

    def test_it_names_the_command_that_removes_the_worktree(self) -> None:
        reason = reap_refusal_reason(_state(uncommitted_paths=("a.py",))) or ""
        assert "git worktree remove --force" in reason

    def test_it_gives_a_test_for_accounted_for_rather_than_the_phrase_alone(self) -> None:
        """ "If the work is accounted for" told the reader nothing checkable."""
        reason = reap_refusal_reason(_state(uncommitted_paths=("a.py",))) or ""
        assert "git log --oneline" in reason

    def test_it_still_says_why_the_command_will_not_decide(self) -> None:
        """The rebase ambiguity is the real reason, and must survive the rewrite."""
        reason = reap_refusal_reason(_state(uncommitted_paths=("a.py",))) or ""
        assert "rebased commit" in reason


class TestTheTwoRealShapesInThisRepo:
    """Vacuity guard: the predicate must actually split this repo's worktrees."""

    def test_the_clean_shape_and_the_dirty_shape_disagree(self) -> None:
        clean = _state()
        dirty = _state(uncommitted_paths=(".claude/ccy/CLAUDE.md",), commits_ahead_of_base=224)
        assert is_reapable(clean) != is_reapable(dirty)


class TestTheFreshWorktreeGuard:
    """A history-free worktree is not evidence it is finished (Plan 00372).

    Reproduces the live incident directly: a worktree created moments earlier
    for an actively-working agent had zero commits, zero uncommitted paths and
    zero unlanded patches — every check above passed vacuously, and the reaper
    listed it as safe to remove.
    """

    def test_a_live_process_inside_it_blocks_it_even_though_everything_else_is_clean(
        self,
    ) -> None:
        state = _state(live_process_pids=(4242,))
        assert not is_reapable(state)
        assert "4242" in (reap_refusal_reason(state) or "")

    def test_multiple_live_pids_are_all_named(self) -> None:
        state = _state(live_process_pids=(111, 222))
        reason = reap_refusal_reason(state) or ""
        assert "111" in reason
        assert "222" in reason

    def test_created_moments_ago_blocks_it_even_though_everything_else_is_clean(self) -> None:
        """Exactly the live incident's shape: fresh, clean, no history."""
        state = _state(age_seconds=3.0)
        assert not is_reapable(state)
        assert "3" in (reap_refusal_reason(state) or "")

    def test_an_unknown_age_is_refused_rather_than_assumed_old(self) -> None:
        """Unknown means not reapable everywhere else in this predicate too."""
        state = _state(age_seconds=None)
        assert not is_reapable(state)

    def test_an_old_clean_worktree_with_nobody_in_it_is_still_reapable(self) -> None:
        """The guard must actually discriminate, not just refuse everything."""
        assert is_reapable(_state(age_seconds=_OLD_ENOUGH_SECONDS, live_process_pids=()))

    def test_being_just_under_the_window_still_blocks_it(self) -> None:
        state = _state(age_seconds=MINIMUM_AGE_SECONDS - 1)
        assert not is_reapable(state)

    def test_being_just_over_the_window_no_longer_blocks_it_on_age_alone(self) -> None:
        state = _state(age_seconds=MINIMUM_AGE_SECONDS + 1)
        assert is_reapable(state)

    def test_a_worktree_with_real_history_still_reports_its_own_problems_too(self) -> None:
        """Reported alongside, not instead of, the existing checks."""
        state = _state(commits_ahead_of_base=5, age_seconds=3.0)
        reason = reap_refusal_reason(state) or ""
        assert "5" in reason
        assert "3" in reason
