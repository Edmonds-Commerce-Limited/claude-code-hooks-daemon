"""Tests for the ``journal-dayfile-is-today`` EDIT check (Plan 00197).

A journal day-file edit whose embedded date is not EXACTLY today is BLOCKED
by default — the "yesterday is fine" tolerance that ``journal-dayfile-naming``
grants is exactly the agent confusion this check closes (a session that spans
midnight should start today's day-file, not keep appending to yesterday's).
Grammar/calendar-validity/plan-number problems remain
``journal-dayfile-naming``'s job; this check only judges recency of an
otherwise well-formed name.
"""

from datetime import date
from pathlib import Path

from claude_code_hooks_daemon.plan_qa.checks import journal_dayfile_is_today
from claude_code_hooks_daemon.plan_qa.types import CheckContext, Level, Stage


def _ctx(
    basename: str,
    *,
    plan_number: int = 197,
    today: date | None = date(2026, 8, 7),
    today_only_mode: str = "block",
    journal_mode: str = "advise",
    journal_enabled: bool = True,
    journal_dir_name: str = "JOURNAL",
    legacy_plan_allowlist: frozenset[int] = frozenset(),
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
        journal_today_only_mode=today_only_mode,
        legacy_plan_allowlist=legacy_plan_allowlist,
    )


class TestSpec:
    def test_registered_edit_block(self) -> None:
        spec = journal_dayfile_is_today.CHECK
        assert spec.check_id == "journal-dayfile-is-today"
        assert spec.stage == Stage.EDIT
        assert spec.level == Level.BLOCK


class TestRun:
    def test_todays_dayfile_passes(self) -> None:
        assert journal_dayfile_is_today.CHECK.run(_ctx("00197-Journal-26-08-07.md")) == []

    def test_yesterday_is_blocked(self) -> None:
        # Unlike journal-dayfile-naming, yesterday is NOT tolerated here.
        findings = journal_dayfile_is_today.CHECK.run(_ctx("00197-Journal-26-08-06.md"))
        assert len(findings) == 1
        assert findings[0].level == Level.BLOCK
        assert "today" in findings[0].message.lower()

    def test_future_date_is_blocked(self) -> None:
        findings = journal_dayfile_is_today.CHECK.run(_ctx("00197-Journal-26-08-08.md"))
        assert len(findings) == 1
        assert findings[0].level == Level.BLOCK

    def test_far_past_date_is_blocked(self) -> None:
        findings = journal_dayfile_is_today.CHECK.run(_ctx("00197-Journal-26-01-01.md"))
        assert len(findings) == 1
        assert findings[0].level == Level.BLOCK

    def test_remediation_names_exact_todays_filename(self) -> None:
        findings = journal_dayfile_is_today.CHECK.run(_ctx("00197-Journal-26-08-06.md"))
        assert "00197-Journal-26-08-07.md" in findings[0].remediation

    def test_remediation_without_plan_number_is_generic(self) -> None:
        # A journal dir with no numbered enclosing plan folder can't offer an
        # exact filename — degrade gracefully instead of crashing.
        root = Path("/repo")
        ctx = CheckContext(
            project_root=root,
            plan_dir_rel="CLAUDE/Plan",
            file_path=root
            / "CLAUDE"
            / "Plan"
            / "not-numbered"
            / "JOURNAL"
            / "00197-Journal-26-08-06.md",
            file_content="# journal\n",
            file_exists_before=False,
            today=date(2026, 8, 7),
            journal_enabled=True,
            journal_mode="advise",
            journal_today_only_mode="block",
        )
        findings = journal_dayfile_is_today.CHECK.run(ctx)
        assert len(findings) == 1
        assert "NNNNN-Journal-YY-MM-DD.md" in findings[0].remediation

    def test_creating_todays_dayfile_passes(self) -> None:
        # file_exists_before=False (a creation) with today's date is clean.
        assert journal_dayfile_is_today.CHECK.run(_ctx("00197-Journal-26-08-07.md")) == []

    def test_non_journal_file_is_ignored(self) -> None:
        root = Path("/repo")
        ctx = CheckContext(
            project_root=root,
            plan_dir_rel="CLAUDE/Plan",
            file_path=root / "CLAUDE" / "Plan" / "00197-thing" / "PLAN.md",
            file_content="x",
            journal_enabled=True,
        )
        assert journal_dayfile_is_today.CHECK.run(ctx) == []

    def test_malformed_name_defers_to_naming_check(self) -> None:
        # journal-dayfile-naming owns grammar problems; this check must not
        # crash or double-report an unparseable name.
        assert journal_dayfile_is_today.CHECK.run(_ctx("my-journal.md")) == []

    def test_impossible_calendar_date_defers_to_naming_check(self) -> None:
        assert journal_dayfile_is_today.CHECK.run(_ctx("00197-Journal-26-13-45.md")) == []

    def test_today_unknown_fails_open(self) -> None:
        # e.g. the `plan-qa --lint` CLI path never supplies today — blocking
        # on missing clock information would be worse than the bug.
        assert (
            journal_dayfile_is_today.CHECK.run(_ctx("00197-Journal-26-01-01.md", today=None)) == []
        )

    def test_legacy_allowlisted_plan_only_advises(self) -> None:
        findings = journal_dayfile_is_today.CHECK.run(
            _ctx("00197-Journal-26-08-06.md", legacy_plan_allowlist=frozenset({197}))
        )
        assert len(findings) == 1
        assert findings[0].level == Level.ADVISE

    def test_advise_mode_never_blocks(self) -> None:
        findings = journal_dayfile_is_today.CHECK.run(
            _ctx("00197-Journal-26-08-06.md", today_only_mode="advise")
        )
        assert len(findings) == 1
        assert findings[0].level == Level.ADVISE

    def test_off_mode_disables_check(self) -> None:
        assert (
            journal_dayfile_is_today.CHECK.run(
                _ctx("00197-Journal-26-08-06.md", today_only_mode="off")
            )
            == []
        )

    def test_disabled_journalling_is_ignored(self) -> None:
        assert (
            journal_dayfile_is_today.CHECK.run(
                _ctx("00197-Journal-26-08-06.md", journal_enabled=False)
            )
            == []
        )
        assert (
            journal_dayfile_is_today.CHECK.run(
                _ctx("00197-Journal-26-08-06.md", journal_mode="off")
            )
            == []
        )
