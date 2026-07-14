"""Tests for the ``journal-dayfile-naming`` EDIT check (Plan 00163).

Validates a journal day-file's basename against ``NNNNN-Journal-YY-MM-DD.md``:
the embedded number must match the enclosing plan, the date must be a real
calendar date, and (when ``today`` is supplied) it must be today or yesterday
(local midnight rollover mid-session is legitimate). Ships ADVISE; honours
``mode: block`` only for this check.
"""

from datetime import date
from pathlib import Path

from claude_code_hooks_daemon.plan_qa.checks import journal_dayfile_naming
from claude_code_hooks_daemon.plan_qa.types import CheckContext, Level, Stage


def _ctx(
    basename: str,
    *,
    plan_number: int = 163,
    today: date | None = date(2026, 7, 14),
    journal_mode: str = "advise",
    journal_enabled: bool = True,
    journal_dir_name: str = "JOURNAL",
) -> CheckContext:
    root = Path("/repo")
    file_path = root / "CLAUDE" / "Plan" / f"{plan_number:05d}-thing" / journal_dir_name / basename
    return CheckContext(
        project_root=root,
        plan_dir_rel="CLAUDE/Plan",
        file_path=file_path,
        file_content="# journal\n",
        file_exists_before=False,
        today=today,
        journal_enabled=journal_enabled,
        journal_mode=journal_mode,
        journal_dir_name=journal_dir_name,
    )


class TestSpec:
    def test_registered_edit_advise(self) -> None:
        spec = journal_dayfile_naming.CHECK
        assert spec.check_id == "journal-dayfile-naming"
        assert spec.stage == Stage.EDIT
        assert spec.level == Level.ADVISE


class TestRun:
    def test_well_formed_name_today_passes(self) -> None:
        assert journal_dayfile_naming.CHECK.run(_ctx("00163-Journal-26-07-14.md")) == []

    def test_yesterday_passes_midnight_rollover(self) -> None:
        # today=07-14; a 07-13 file written just after midnight is legitimate.
        assert journal_dayfile_naming.CHECK.run(_ctx("00163-Journal-26-07-13.md")) == []

    def test_non_journal_file_is_ignored(self) -> None:
        # A PLAN.md edit (not under JOURNAL/) is not this check's concern.
        root = Path("/repo")
        ctx = CheckContext(
            project_root=root,
            plan_dir_rel="CLAUDE/Plan",
            file_path=root / "CLAUDE" / "Plan" / "00163-thing" / "PLAN.md",
            file_content="x",
            journal_enabled=True,
        )
        assert journal_dayfile_naming.CHECK.run(ctx) == []

    def test_malformed_name_advises(self) -> None:
        findings = journal_dayfile_naming.CHECK.run(_ctx("my-journal.md"))
        assert len(findings) == 1
        assert findings[0].level == Level.ADVISE
        assert "NNNNN-Journal-YY-MM-DD.md" in findings[0].remediation

    def test_number_mismatch_advises(self) -> None:
        findings = journal_dayfile_naming.CHECK.run(_ctx("00099-Journal-26-07-14.md"))
        assert len(findings) == 1
        assert "00099" in findings[0].message
        assert "00163" in findings[0].message

    def test_impossible_date_advises(self) -> None:
        findings = journal_dayfile_naming.CHECK.run(_ctx("00163-Journal-26-13-45.md"))
        assert len(findings) == 1
        assert "calendar date" in findings[0].message

    def test_stale_date_advises_when_today_known(self) -> None:
        findings = journal_dayfile_naming.CHECK.run(_ctx("00163-Journal-26-07-01.md"))
        assert len(findings) == 1
        assert "today" in findings[0].message.lower()

    def test_stale_date_not_flagged_when_today_unknown(self) -> None:
        # Without today (e.g. lint CLI), recency cannot be judged; the name is
        # otherwise well-formed, so no finding.
        assert journal_dayfile_naming.CHECK.run(_ctx("00163-Journal-26-07-01.md", today=None)) == []

    def test_block_mode_escalates_level(self) -> None:
        findings = journal_dayfile_naming.CHECK.run(_ctx("bad.md", journal_mode="block"))
        assert findings[0].level == Level.BLOCK

    def test_disabled_journalling_is_ignored(self) -> None:
        assert journal_dayfile_naming.CHECK.run(_ctx("bad.md", journal_enabled=False)) == []
        assert journal_dayfile_naming.CHECK.run(_ctx("bad.md", journal_mode="off")) == []
