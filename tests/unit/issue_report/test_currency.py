"""The version-currency rule, made mechanical (Plan 00403 Task 3.1).

The owner's rule, verbatim: a reporter "should ensure that they are running the
latest version but can report issues if on an older one and there is no changes
to the relevant system between current version and latest release".

That is two decisions, and only one of them is a judgement call:

``being behind is not itself disqualifying``
    Refusing every report from an older install would be simple and would also
    silence most of the field. What matters is whether the SUBSYSTEM the report
    names has changed since — because if it has not, the defect is still live
    on `main` and the report is as good as one filed from the latest version.

``so the question is answerable from the release notes``
    Notes for the versions in between either mention the named subsystem or
    they do not. When they do, the honest answer is "upgrade first" — the
    reported behaviour may already be gone. When they do not, the report
    proceeds AND records that finding, so a maintainer can see the check ran
    rather than taking the version on trust.
"""

from __future__ import annotations

import pytest

from claude_code_hooks_daemon.issue_report.currency import assess_currency


def _note(version: str, content: str) -> tuple[str, str]:
    return (version, content)


_NOTES = dict(
    [
        _note("3.26.0", "Fixed the pipe blocker's heredoc handling."),
        _note("3.27.0", "Reference repo freshness: new PreToolUse gate."),
        _note("3.28.0", "Docs only."),
    ]
)


class TestOnTheLatestVersion:
    def test_the_report_proceeds(self) -> None:
        verdict = assess_currency(
            installed="3.28.0", latest="3.28.0", subsystem="sed_blocker", notes=_NOTES
        )

        assert verdict.may_report

    def test_nothing_needs_checking(self) -> None:
        verdict = assess_currency(
            installed="3.28.0", latest="3.28.0", subsystem="sed_blocker", notes=_NOTES
        )

        assert verdict.versions_checked == ()


class TestBehindButTheSubsystemIsUntouched:
    def test_the_report_proceeds(self) -> None:
        """Being behind is not disqualifying — a stale subsystem is."""
        verdict = assess_currency(
            installed="3.25.0", latest="3.28.0", subsystem="sed_blocker", notes=_NOTES
        )

        assert verdict.may_report

    def test_the_versions_examined_are_recorded(self) -> None:
        """A maintainer must see the check ran, not take the version on trust."""
        verdict = assess_currency(
            installed="3.25.0", latest="3.28.0", subsystem="sed_blocker", notes=_NOTES
        )

        assert verdict.versions_checked == ("3.26.0", "3.27.0", "3.28.0")

    def test_the_finding_is_stated_for_the_report(self) -> None:
        verdict = assess_currency(
            installed="3.25.0", latest="3.28.0", subsystem="sed_blocker", notes=_NOTES
        )

        assert "sed_blocker" in verdict.detail
        assert "3.28.0" in verdict.detail


class TestBehindAndTheSubsystemChanged:
    def test_the_report_is_refused(self) -> None:
        verdict = assess_currency(
            installed="3.25.0", latest="3.28.0", subsystem="reference_repo", notes=_NOTES
        )

        assert not verdict.may_report

    def test_the_version_that_touched_it_is_named(self) -> None:
        """'Upgrade first' without saying why is advice nobody follows."""
        verdict = assess_currency(
            installed="3.25.0", latest="3.28.0", subsystem="reference_repo", notes=_NOTES
        )

        assert verdict.mentions == ("3.27.0",)
        assert "3.27.0" in verdict.detail

    def test_the_match_ignores_case_and_separators(self) -> None:
        """A handler is written `sed_blocker` in config and 'sed blocker' in prose."""
        notes = {"3.27.0": "Reworked the Pipe Blocker's whitelist."}
        verdict = assess_currency(
            installed="3.26.0", latest="3.27.0", subsystem="pipe_blocker", notes=notes
        )

        assert not verdict.may_report


class TestAheadOfTheLatestRelease:
    def test_an_unreleased_build_may_still_report(self) -> None:
        """A contributor on `main` is ahead of the newest tag, not behind it.

        Refusing them would silence exactly the people best placed to report.
        """
        verdict = assess_currency(
            installed="3.29.0", latest="3.28.0", subsystem="sed_blocker", notes=_NOTES
        )

        assert verdict.may_report

    def test_the_detail_says_so_rather_than_claiming_currency(self) -> None:
        verdict = assess_currency(
            installed="3.29.0", latest="3.28.0", subsystem="sed_blocker", notes=_NOTES
        )

        assert "ahead" in verdict.detail.lower()


class TestTheCheckDegradesHonestly:
    @pytest.mark.parametrize("bad", ["", "not-a-version", "3.x"])
    def test_an_unparseable_installed_version_does_not_raise(self, bad: str) -> None:
        """The caller is a report generator, not a place for an exception."""
        verdict = assess_currency(
            installed=bad, latest="3.28.0", subsystem="sed_blocker", notes=_NOTES
        )

        assert not verdict.may_report

    def test_an_unknown_version_is_reported_as_unknown_not_as_current(self) -> None:
        """'Could not check' and 'checked, fine' must never look the same."""
        verdict = assess_currency(
            installed="", latest="3.28.0", subsystem="sed_blocker", notes=_NOTES
        )

        assert "could not" in verdict.detail.lower()

    def test_missing_release_notes_refuse_rather_than_wave_through(self) -> None:
        """No notes means the question was not answered, not answered 'no'."""
        verdict = assess_currency(
            installed="3.25.0", latest="3.28.0", subsystem="sed_blocker", notes={}
        )

        assert not verdict.may_report
