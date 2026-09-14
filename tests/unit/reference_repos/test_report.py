"""One renderer, three surfaces (Plan 00401 Task 1.5).

The SessionStart sweep, the PreToolUse backstop and the CLI all describe the
same repos. If each wrote its own wording they would drift, and drift here is
worse than ugly: an agent blocked by one sentence and then handed a different
sentence by the CLI cannot tell whether it is looking at the same problem.

So the rendering lives in one place, and these tests pin the parts a reader
acts on — which repo, what is wrong, and the exact command that fixes it. The
remediation command is load-bearing twice over: it is the instruction, and
Phase 4 must exempt it from interception, because a handler that blocks its own
remedy makes itself impossible to satisfy.
"""

from __future__ import annotations

from pathlib import Path

from claude_code_hooks_daemon.reference_repos.model import Checkability, RepoState
from claude_code_hooks_daemon.reference_repos.report import (
    NOT_VERIFIED_HEADLINE,
    UNCONFIRMED_HEADLINE,
    remediation_command,
    repo_line,
    report_lines,
    unconfirmed_note,
)

_ROOT = Path("/workspace")
_ALPHA = Path("/workspace/untracked/repos/alpha")


def _state(
    *,
    path: Path = _ALPHA,
    checkability: Checkability = Checkability.CHECKABLE,
    branch: str | None = "main",
    default_branch: str | None = "main",
    behind: int = 0,
    ahead: int = 0,
    dirty: bool = False,
    fetch_failed: bool = False,
) -> RepoState:
    return RepoState(
        path=path,
        checkability=checkability,
        branch=branch,
        default_branch=default_branch,
        upstream="origin/main",
        behind=behind,
        ahead=ahead,
        dirty=dirty,
        fetch_failed=fetch_failed,
    )


class TestASingleRepoLine:
    def test_the_line_names_the_repo_relative_to_the_project(self) -> None:
        """An absolute container path is noise; the relative one is recognisable."""
        line = repo_line(_state(behind=2), project_root=_ROOT)

        assert "untracked/repos/alpha" in line
        assert "/workspace/untracked" not in line

    def test_an_absolute_path_is_used_when_it_is_outside_the_project(self) -> None:
        """A configured root can point anywhere; the path must stay unambiguous."""
        outside = Path("/srv/shared/repos/beta")

        line = repo_line(_state(path=outside, behind=1), project_root=_ROOT)

        assert str(outside) in line

    def test_a_behind_repo_says_how_far_behind(self) -> None:
        line = repo_line(_state(behind=7), project_root=_ROOT)

        assert "7" in line
        assert "behind" in line.lower()

    def test_an_off_default_branch_repo_names_both_branches(self) -> None:
        """Knowing it is wrong is useless without knowing what it should be."""
        line = repo_line(_state(branch="wip", default_branch="main"), project_root=_ROOT)

        assert "wip" in line
        assert "main" in line

    def test_a_current_repo_reads_as_up_to_date(self) -> None:
        line = repo_line(_state(), project_root=_ROOT)

        assert "up to date" in line.lower()

    def test_a_failed_fetch_qualifies_everything_after_it(self) -> None:
        """Stated first, because the counts beside it came from stale refs.

        Without this the line reads "up to date" for a repo whose remote could
        not be reached at all — which is what this repo's own canary produced.
        """
        line = repo_line(_state(fetch_failed=True), project_root=_ROOT)

        assert "last fetch failed" in line
        assert "up to date" not in line

    def test_a_missing_upstream_name_falls_back_rather_than_printing_none(self) -> None:
        """Reachable from a cache: the schema permits a null upstream.

        The inspector never produces CHECKABLE with no upstream, but a cached
        payload can carry one, and rendering the word "None" at a reader is how
        a report loses their trust.
        """
        state = RepoState(
            path=_ALPHA,
            checkability=Checkability.CHECKABLE,
            branch="main",
            default_branch="main",
            upstream=None,
            behind=2,
            ahead=0,
            dirty=False,
        )

        line = repo_line(state, project_root=_ROOT)

        assert "None" not in line
        assert "upstream" in line

    def test_an_uncheckable_repo_states_why_rather_than_claiming_staleness(self) -> None:
        line = repo_line(_state(checkability=Checkability.NO_REMOTE), project_root=_ROOT)

        assert "no remote" in line.lower()
        assert "behind" not in line.lower()


class TestRemediation:
    def test_a_behind_repo_gets_a_runnable_pull_command_naming_the_repo(self) -> None:
        command = remediation_command(_state(behind=3))

        assert command is not None
        assert str(_ALPHA) in command
        assert "pull" in command

    def test_the_pull_is_fast_forward_only(self) -> None:
        """A plain pull can merge; the remedy must not invent history."""
        command = remediation_command(_state(behind=3))

        assert command is not None
        assert "--ff-only" in command

    def test_an_off_default_branch_repo_is_told_to_switch(self) -> None:
        command = remediation_command(_state(branch="wip", default_branch="main"))

        assert command is not None
        assert "checkout main" in command or "switch main" in command

    def test_a_dirty_repo_is_not_told_to_pull(self) -> None:
        """Pulling over uncommitted work is the outcome the plan forbids."""
        command = remediation_command(_state(behind=3, dirty=True))

        assert command is None or "pull" not in command

    def test_a_current_repo_needs_no_command(self) -> None:
        assert remediation_command(_state()) is None

    def test_an_uncheckable_repo_needs_no_command(self) -> None:
        assert remediation_command(_state(checkability=Checkability.NO_UPSTREAM)) is None


class TestTheWholeReport:
    def test_repos_needing_attention_are_listed(self) -> None:
        stale = _state(behind=4)
        lines = report_lines([stale], project_root=_ROOT)

        assert any("alpha" in line for line in lines)

    def test_an_all_clear_says_so_in_one_line_rather_than_listing_everything(self) -> None:
        """A clean report a reader must scroll is a report they stop reading."""
        lines = report_lines(
            [_state(), _state(path=Path("/workspace/untracked/repos/b"))], project_root=_ROOT
        )

        assert len(lines) == 1
        assert "up to date" in lines[0].lower()

    def test_no_governed_repos_produces_nothing_at_all(self) -> None:
        """Silence is correct for a project that has not adopted the convention."""
        assert report_lines([], project_root=_ROOT) == []

    def test_a_sweep_that_confirmed_nothing_never_claims_an_all_clear(self) -> None:
        """The offline machine. Every fetch failed, so every count came off disk.

        "All 2 up to date" here would be the exact false comfort this package
        exists to prevent — a confident sentence about repos nothing checked.
        """
        lines = report_lines(
            [
                _state(fetch_failed=True),
                _state(path=Path("/workspace/untracked/repos/b"), fetch_failed=True),
            ],
            project_root=_ROOT,
        )

        assert lines == ["📚  reference repos: 2 governed, none verifiable"]

    def test_not_verified_is_reported_distinctly_from_stale(self) -> None:
        """These demand different things and must never read the same.

        Stale means "this is out of date"; not-verified means "nobody knows".
        Collapsing them would either cry wolf or give false comfort.
        """
        lines = report_lines(None, project_root=_ROOT)

        assert lines
        assert NOT_VERIFIED_HEADLINE in lines[0]

    def test_a_repo_with_no_safe_remedy_is_listed_without_a_fix_line(self) -> None:
        """A dirty, behind repo needs a human — so no command is offered.

        Printing a `fix:` line here would be worse than printing none: every
        mechanical remedy moves a tree holding uncommitted work, which is the
        outcome the plan forbids outright.
        """
        lines = report_lines([_state(behind=2, dirty=True)], project_root=_ROOT)

        body = "\n".join(lines)
        assert "alpha" in body
        assert "fix:" not in body

    def test_the_listing_can_be_bounded_so_session_start_cannot_flood(self) -> None:
        """SessionStart shows several advisories; one must not push the rest away.

        The bound lives here rather than in the handler so the CLI can stay
        unbounded — a report you asked for should show everything, a report that
        interrupts you should not.
        """
        many = [
            _state(path=Path(f"/workspace/untracked/repos/r{index}"), behind=1)
            for index in range(25)
        ]

        lines = report_lines(many, project_root=_ROOT, max_listed=10)

        listed = [line for line in lines if line.lstrip().startswith("- ")]
        assert len(listed) == 10
        assert any("15 more" in line for line in lines)

    def test_an_unbounded_report_lists_every_repo(self) -> None:
        many = [
            _state(path=Path(f"/workspace/untracked/repos/r{index}"), behind=1)
            for index in range(25)
        ]

        lines = report_lines(many, project_root=_ROOT)

        listed = [line for line in lines if line.lstrip().startswith("- ")]
        assert len(listed) == 25
        assert not any("more" in line for line in lines)

    def test_the_total_is_still_stated_when_the_listing_is_bounded(self) -> None:
        """A truncated list that hides the true count understates the problem."""
        many = [
            _state(path=Path(f"/workspace/untracked/repos/r{index}"), behind=1)
            for index in range(25)
        ]

        lines = report_lines(many, project_root=_ROOT, max_listed=3)

        assert "25" in lines[0]

    def test_a_mixed_report_lists_only_what_needs_attention(self) -> None:
        """The uncheckable canary must not appear; that is what keeps it usable."""
        lines = report_lines(
            [
                _state(behind=2),
                _state(
                    path=Path("/workspace/untracked/repos/canary"),
                    checkability=Checkability.NO_UPSTREAM,
                ),
                _state(path=Path("/workspace/untracked/repos/fine")),
            ],
            project_root=_ROOT,
        )

        body = "\n".join(lines)
        assert "alpha" in body
        assert "canary" not in body
        assert "fine" not in body


class TestTheUnconfirmedNote:
    """The third answer, distinct from both "up to date" and "stale".

    A repo can be perfectly current and still be one nobody CONFIRMED: the
    remote was unreachable, or there is no remote to reach. That is not a
    problem to fix, so it never demands attention and never blocks — but a
    reader about to reason from the contents deserves to know it, and the
    sweep's report deliberately stays silent about it.
    """

    def test_a_confirmed_repo_produces_no_note(self) -> None:
        assert unconfirmed_note(_state(), project_root=_ROOT) is None

    def test_a_confirmed_repo_that_is_merely_stale_produces_no_note(self) -> None:
        """Stale is a DIFFERENT answer, and the gate says that one itself."""
        assert unconfirmed_note(_state(behind=4), project_root=_ROOT) is None

    def test_a_failed_fetch_produces_a_note(self) -> None:
        note = unconfirmed_note(_state(fetch_failed=True), project_root=_ROOT)

        assert note is not None
        assert UNCONFIRMED_HEADLINE in note

    def test_the_note_names_the_repo_the_way_every_other_surface_does(self) -> None:
        note = unconfirmed_note(_state(fetch_failed=True), project_root=_ROOT)

        assert note is not None
        assert "untracked/repos/alpha" in note

    def test_the_note_carries_the_reason_rather_than_a_bare_headline(self) -> None:
        """'Could not be confirmed' with no 'why' is a puzzle, not a report."""
        note = unconfirmed_note(_state(fetch_failed=True), project_root=_ROOT)

        assert note is not None
        assert repo_line(_state(fetch_failed=True), project_root=_ROOT) in note

    def test_an_uncheckable_repo_produces_a_note_too(self) -> None:
        """No remote is also 'nobody confirmed this', by a different route."""
        note = unconfirmed_note(_state(checkability=Checkability.NO_REMOTE), project_root=_ROOT)

        assert note is not None
        assert "no remote configured" in note

    def test_the_note_never_reads_as_an_instruction_to_fix_the_repo(self) -> None:
        """There is nothing to fix. Advice to fix it would be advice to nowhere."""
        note = unconfirmed_note(_state(checkability=Checkability.NO_REMOTE), project_root=_ROOT)

        assert note is not None
        assert "fix:" not in note

    def test_the_note_does_not_reuse_the_nobody_swept_headline(self) -> None:
        """Two different facts must not arrive wearing the same sentence."""
        note = unconfirmed_note(_state(fetch_failed=True), project_root=_ROOT)

        assert note is not None
        assert NOT_VERIFIED_HEADLINE not in note
