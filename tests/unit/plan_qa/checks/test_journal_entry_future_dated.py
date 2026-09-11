"""A journal entry must not be timestamped ahead of the clock (Plan 00377 N9).

The defect this closes was self-inflicted and went unnoticed for an hour:
entries in a live day-file ran ~70 minutes ahead of real time because the
timestamps were estimated rather than read. `journal-entry-ordering` could not
see it — the entries were internally monotonic — and `journal-append-only`
could not either, since nothing was rewritten. A run of entries that is
consistently wrong satisfies both.

Only the FUTURE direction is a defect. Writing up something that happened
earlier is ordinary and stays silent; claiming a time that has not arrived yet
cannot be anything but wrong.
"""

from datetime import date, datetime
from pathlib import Path

import pytest

from claude_code_hooks_daemon.plan_qa.checks import journal_entry_future_dated as check
from claude_code_hooks_daemon.plan_qa.types import CheckContext, Level, Stage

_PREAMBLE = (
    "# Plan 00377 — Journal 26-09-11\n"
    "\n"
    "> **Append-only activity log**.\n"
    ">\n"
    "> ```\n"
    "> ## HH:MM · category · REF   — optional short title\n"
    "> ```\n"
    "\n"
)


def _entry(time: str, title: str = "thing") -> str:
    return f"## {time} · action · — — {title}\n\nBody text.\n\n"


def _ctx(
    body: str,
    *,
    journal_mode: str = "advise",
    journal_enabled: bool = True,
    dayfile_date: str = "26-09-11",
) -> CheckContext:
    root = Path("/repo")
    name = f"00377-Journal-{dayfile_date}.md"
    return CheckContext(
        project_root=root,
        plan_dir_rel="CLAUDE/Plan",
        file_path=root / "CLAUDE" / "Plan" / "00377-thing" / "JOURNAL" / name,
        file_content=body,
        file_exists_before=True,
        today=date(2026, 9, 11),
        journal_enabled=journal_enabled,
        journal_mode=journal_mode,
        journal_dir_name="JOURNAL",
    )


@pytest.fixture(autouse=True)
def _clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the wall clock to 14:00 on the day-file's date."""
    monkeypatch.setattr(check, "_now", lambda: datetime(2026, 9, 11, 14, 0))


def _ids(context: CheckContext) -> list[str]:
    return [finding.check_id for finding in check.CHECKS[0].run(context)]


class TestSpec:
    def test_registered_at_edit_only_as_advise(self) -> None:
        """Deliberately NOT dual-registered, unlike journal-entry-ordering.

        A sweep could only report day-files nobody is permitted to rewrite —
        the timestamps are wrong and the record is append-only — and a
        permanently unfixable finding trains readers to skim the check. At EDIT
        time the entry has not landed yet, so it is trivially correctable.
        """
        assert len(check.CHECKS) == 1
        assert check.CHECKS[0].stage is Stage.EDIT
        assert check.CHECKS[0].level is Level.ADVISE
        assert check.CHECKS[0].check_id == "journal-entry-future-dated"


class TestTheFutureIsADefect:
    def test_an_entry_ahead_of_the_clock_is_reported(self) -> None:
        body = _PREAMBLE + _entry("13:00") + _entry("16:44")
        assert _ids(_ctx(body)) == ["journal-entry-future-dated"]

    def test_the_message_names_the_offending_time(self) -> None:
        body = _PREAMBLE + _entry("16:44")
        finding = check.CHECKS[0].run(_ctx(body))[0]
        assert "16:44" in finding.message

    def test_only_the_latest_entry_needs_to_be_ahead(self) -> None:
        """Ordering is another check's job; this one judges the clock."""
        body = _PREAMBLE + _entry("16:44") + _entry("13:00")
        assert _ids(_ctx(body)) == ["journal-entry-future-dated"]


class TestWhatIsNotADefect:
    def test_an_entry_at_the_current_time_is_silent(self) -> None:
        assert _ids(_ctx(_PREAMBLE + _entry("14:00"))) == []

    def test_an_earlier_entry_is_silent(self) -> None:
        """Writing up something that already happened is ordinary."""
        assert _ids(_ctx(_PREAMBLE + _entry("09:15"))) == []

    def test_a_small_overshoot_is_tolerated(self) -> None:
        """A generous threshold absorbs clock skew and a slow write."""
        assert _ids(_ctx(_PREAMBLE + _entry("14:20"))) == []

    def test_a_previous_days_dayfile_is_silent(self) -> None:
        """Appending to yesterday's file is behind the clock by a whole day."""
        assert _ids(_ctx(_PREAMBLE + _entry("23:50"), dayfile_date="26-09-10")) == []

    def test_the_blockquoted_grammar_is_not_an_entry(self) -> None:
        assert _ids(_ctx(_PREAMBLE)) == []

    def test_a_file_with_no_entries_is_silent(self) -> None:
        assert _ids(_ctx(_PREAMBLE + "Prose with no headings.\n")) == []


class TestPolicy:
    def test_silent_when_journalling_is_disabled(self) -> None:
        body = _PREAMBLE + _entry("16:44")
        assert _ids(_ctx(body, journal_enabled=False)) == []

    def test_block_mode_raises_the_level(self) -> None:
        body = _PREAMBLE + _entry("16:44")
        finding = check.CHECKS[0].run(_ctx(body, journal_mode="block"))[0]
        assert finding.level is Level.BLOCK
