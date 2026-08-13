"""Tests for the ``journal-dayfile-naming`` EDIT check (Plan 00163).

Validates a journal day-file's basename against ``NNNNN-Journal-YY-MM-DD.md``:
the embedded number must match the enclosing plan and the date must be a real
calendar date. Recency (is the date today?) is NOT this check's concern as of
Plan 00197 — that moved to the dedicated ``journal-dayfile-is-today`` check so
the two checks can never give contradictory advice about one file. Ships
ADVISE; honours ``mode: block``.
"""

from datetime import date
from pathlib import Path

from claude_code_hooks_daemon.plan_qa.checks import journal_dayfile_naming
from claude_code_hooks_daemon.plan_qa.types import CheckContext, Level, Stage

# These tests exercise the edit-time surface. The sweep twin, which applies the
# same grammar to day-files already on disk, is covered by
# tests/unit/plan_qa/checks/test_document_rule_stage_parity.py.
_CHECK = next(spec for spec in journal_dayfile_naming.CHECKS if spec.stage is Stage.EDIT)


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
        spec = _CHECK
        assert spec.check_id == "journal-dayfile-naming"
        assert spec.stage == Stage.EDIT
        assert spec.level == Level.ADVISE


class TestRun:
    def test_well_formed_name_today_passes(self) -> None:
        assert _CHECK.run(_ctx("00163-Journal-26-07-14.md")) == []

    def test_well_formed_past_date_passes_naming(self) -> None:
        # Recency is journal-dayfile-is-today's concern (Plan 00197); a
        # well-formed but stale name is still grammatically clean.
        assert _CHECK.run(_ctx("00163-Journal-26-07-01.md")) == []

    def test_well_formed_future_date_passes_naming(self) -> None:
        assert _CHECK.run(_ctx("00163-Journal-26-12-25.md")) == []

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
        assert _CHECK.run(ctx) == []

    def test_malformed_name_advises(self) -> None:
        findings = _CHECK.run(_ctx("my-journal.md"))
        assert len(findings) == 1
        assert findings[0].level == Level.ADVISE
        assert "NNNNN-Journal-YY-MM-DD.md" in findings[0].remediation

    def test_number_mismatch_advises(self) -> None:
        findings = _CHECK.run(_ctx("00099-Journal-26-07-14.md"))
        assert len(findings) == 1
        assert "00099" in findings[0].message
        assert "00163" in findings[0].message

    def test_impossible_date_advises(self) -> None:
        findings = _CHECK.run(_ctx("00163-Journal-26-13-45.md"))
        assert len(findings) == 1
        assert "calendar date" in findings[0].message

    def test_block_mode_escalates_level(self) -> None:
        findings = _CHECK.run(_ctx("bad.md", journal_mode="block"))
        assert findings[0].level == Level.BLOCK

    def test_disabled_journalling_is_ignored(self) -> None:
        assert _CHECK.run(_ctx("bad.md", journal_enabled=False)) == []
        assert _CHECK.run(_ctx("bad.md", journal_mode="off")) == []
