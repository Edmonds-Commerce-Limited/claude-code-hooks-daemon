"""The state a governed reference repo can be in (Plan 00401 Task 1.2).

``RepoState`` holds FACTS and the predicates derivable from them; it holds no
enforcement policy, because three surfaces consume it and only one of them
blocks. Putting "should this deny a read?" here would bake the PreToolUse
handler's mode into a value object the CLI and the SessionStart sweep also use.

Two safety invariants from the plan live here rather than in any caller, so no
caller can forget them:

- **Un-checkable never demands attention.** No remote, no upstream, a detached
  HEAD — reported once, then out of the way. This is what keeps a deliberately
  unreachable canary clone usable instead of permanently noisy.
- **Dirty, ahead or diverged is never safe to pull.** Report only. A pull that
  touches a repo carrying local work is the one outcome worse than staleness.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from claude_code_hooks_daemon.reference_repos.model import Checkability, RepoState

_REPO = Path("/workspace/untracked/repos/alpha")

_UNCHECKABLE = [
    Checkability.NOT_A_REPO,
    Checkability.NO_REMOTE,
    Checkability.DETACHED_HEAD,
    Checkability.NO_UPSTREAM,
]


def _state(
    *,
    checkability: Checkability = Checkability.CHECKABLE,
    branch: str | None = "main",
    default_branch: str | None = "main",
    upstream: str | None = "origin/main",
    behind: int = 0,
    ahead: int = 0,
    dirty: bool = False,
    path: Path = _REPO,
) -> RepoState:
    """A checkable, clean, up-to-date repo on its default branch."""
    return RepoState(
        path=path,
        checkability=checkability,
        branch=branch,
        default_branch=default_branch,
        upstream=upstream,
        behind=behind,
        ahead=ahead,
        dirty=dirty,
    )


class TestCheckability:
    def test_a_fully_configured_repo_is_checkable(self) -> None:
        assert _state().checkable is True

    @pytest.mark.parametrize("checkability", _UNCHECKABLE)
    def test_every_other_classification_is_not_checkable(self, checkability: Checkability) -> None:
        assert _state(checkability=checkability).checkable is False

    def test_every_classification_carries_a_human_reason(self) -> None:
        """A classification a report cannot explain is one a reader ignores."""
        for checkability in Checkability:
            assert _state(checkability=checkability).reason.strip()

    def test_each_classification_explains_itself_distinctly(self) -> None:
        """Two states sharing one sentence cannot be told apart in a report."""
        reasons = {_state(checkability=c).reason for c in Checkability}

        assert len(reasons) == len(list(Checkability))


class TestUncheckableNeverDemandsAttention:
    """The invariant that keeps an unreachable clone from becoming permanent noise."""

    @pytest.mark.parametrize("checkability", _UNCHECKABLE)
    def test_an_uncheckable_repo_never_needs_attention_however_bad_it_looks(
        self, checkability: Checkability
    ) -> None:
        """Even behind, dirty and off-branch at once, it must stay quiet.

        The canary clone in this project points at an invalid origin BY DESIGN.
        If un-checkable could demand attention, every session would open with a
        complaint nobody can act on, and the real reports would be skipped.
        """
        state = _state(
            checkability=checkability,
            behind=99,
            ahead=3,
            dirty=True,
            branch="some-feature",
            default_branch="main",
        )

        assert state.needs_attention is False

    @pytest.mark.parametrize("checkability", _UNCHECKABLE)
    def test_an_uncheckable_repo_is_never_safe_to_pull(self, checkability: Checkability) -> None:
        assert _state(checkability=checkability, behind=5).safe_to_pull is False


class TestStaleness:
    def test_a_repo_behind_its_upstream_is_behind(self) -> None:
        assert _state(behind=4).is_behind is True

    def test_a_repo_level_with_its_upstream_is_not_behind(self) -> None:
        assert _state(behind=0).is_behind is False

    def test_being_behind_demands_attention(self) -> None:
        """This is the defect the whole plan exists for."""
        assert _state(behind=1).needs_attention is True

    def test_an_up_to_date_repo_on_its_default_branch_demands_nothing(self) -> None:
        assert _state().needs_attention is False

    def test_a_repo_with_local_commits_is_ahead(self) -> None:
        assert _state(ahead=2).is_ahead is True

    def test_divergence_needs_both_directions(self) -> None:
        """Reports distinguish the three cases, so the predicate must too.

        Behind alone is pullable; ahead alone is someone's local work; both at
        once needs a human, and calling that merely "behind" would send a reader
        to a fast-forward that cannot succeed.
        """
        assert _state(behind=3, ahead=2).is_diverged is True
        assert _state(behind=3, ahead=0).is_diverged is False
        assert _state(behind=0, ahead=2).is_diverged is False
        assert _state(behind=0, ahead=0).is_diverged is False


class TestBranchPosition:
    def test_a_repo_on_its_default_branch_is_on_the_default_branch(self) -> None:
        assert _state(branch="main", default_branch="main").is_on_default_branch is True

    def test_a_repo_on_a_feature_branch_is_not(self) -> None:
        assert _state(branch="wip", default_branch="main").is_on_default_branch is False

    def test_being_off_the_default_branch_demands_attention(self) -> None:
        """The owner asked for this to be reported alongside staleness.

        Reading a reference repo parked on someone's half-finished branch is the
        same failure as reading a stale one: the source is not what the agent
        believes it is.
        """
        assert _state(branch="wip", default_branch="main").needs_attention is True

    def test_an_unknown_default_branch_is_not_treated_as_a_mismatch(self) -> None:
        """Unknown is not the same as wrong, and must not manufacture a report."""
        state = _state(branch="main", default_branch=None)

        assert state.is_on_default_branch is True
        assert state.needs_attention is False


class TestSafeToPull:
    """Mirrors the refusal branches already proven in git_upstream_checker."""

    def test_clean_behind_and_not_ahead_is_safe(self) -> None:
        assert _state(behind=3, ahead=0, dirty=False).safe_to_pull is True

    def test_a_dirty_tree_is_never_pulled(self) -> None:
        assert _state(behind=3, dirty=True).safe_to_pull is False

    def test_a_repo_ahead_of_its_upstream_is_never_pulled(self) -> None:
        """Local commits mean a fast-forward is not what the user wants."""
        assert _state(behind=0, ahead=2).safe_to_pull is False

    def test_a_diverged_repo_is_never_pulled(self) -> None:
        assert _state(behind=3, ahead=2).safe_to_pull is False

    def test_a_repo_that_is_already_current_has_nothing_to_pull(self) -> None:
        """Not unsafe — simply nothing to do, and a pull would be pointless work."""
        assert _state(behind=0, ahead=0, dirty=False).safe_to_pull is False


class TestValueSemantics:
    def test_the_state_is_frozen(self) -> None:
        """A cached state handed to three consumers must not be mutable."""
        state = _state()
        # Indirected through a variable: ruff's B010 rejects a constant
        # setattr, and a direct assignment would not type-check against a
        # frozen dataclass -- but the runtime refusal is the thing under test.
        mutated_field = "behind"

        with pytest.raises(AttributeError):
            setattr(state, mutated_field, 5)

    def test_two_identical_states_compare_equal(self) -> None:
        assert _state() == _state()
