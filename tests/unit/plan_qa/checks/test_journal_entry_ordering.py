"""Tests for ``journal-entry-ordering`` (Plan 00377 N1).

A journal day-file's preamble states the grammar "times increase down the
file", and nothing enforced it. Measured: a day-file whose entries ran
12:49 -> 12:58 -> 13:00 -> 12:50 passed ``plan-qa --sweep`` with 0 findings.
``journal-append-only`` caught the EDIT that displaced the entry, so the gap
was specifically in the sweep — hence the dual registration here.

Out-of-order entries matter because the journal's whole contract is that the
next agent's entry point is the LAST entry of the newest day-file. If the last
entry is not the latest one, that contract silently stops holding.
"""

from datetime import date
from pathlib import Path

import pytest

from claude_code_hooks_daemon.plan_qa.checks import journal_entry_ordering
from claude_code_hooks_daemon.plan_qa.types import CheckContext, Level, Stage

_EDIT = next(spec for spec in journal_entry_ordering.CHECKS if spec.stage is Stage.EDIT)
_SWEEP = next(spec for spec in journal_entry_ordering.CHECKS if spec.stage is Stage.SWEEP)

_PREAMBLE = (
    "# Plan 00377 — Journal 26-09-11\n"
    "\n"
    "> **Append-only activity log**.\n"
    ">\n"
    "> ```\n"
    "> ## HH:MM · category · REF   — optional short title\n"
    "> ```\n"
    ">\n"
    "> - `HH:MM` local 24h; times increase down the file.\n"
    "\n"
)


def _entry(time: str, title: str = "thing") -> str:
    return f"## {time} · action · — — {title}\n\nBody text.\n\n"


def _ctx(
    body: str,
    *,
    plan_number: int = 377,
    journal_mode: str = "advise",
    journal_enabled: bool = True,
) -> CheckContext:
    root = Path("/repo")
    name = f"{plan_number:05d}-Journal-26-09-11.md"
    file_path = root / "CLAUDE" / "Plan" / f"{plan_number:05d}-thing" / "JOURNAL" / name
    return CheckContext(
        project_root=root,
        plan_dir_rel="CLAUDE/Plan",
        file_path=file_path,
        file_content=body,
        file_exists_before=True,
        today=date(2026, 9, 11),
        journal_enabled=journal_enabled,
        journal_mode=journal_mode,
        journal_dir_name="JOURNAL",
    )


class TestSpec:
    def test_registered_at_both_stages_as_advise(self) -> None:
        assert _EDIT.check_id == "journal-entry-ordering"
        assert _SWEEP.check_id == "journal-entry-ordering"
        assert _EDIT.level == Level.ADVISE
        assert _SWEEP.level == Level.ADVISE


class TestOrdering:
    def test_ascending_times_pass(self) -> None:
        body = _PREAMBLE + _entry("09:00") + _entry("12:49") + _entry("13:00")
        assert _EDIT.run(_ctx(body)) == []

    def test_equal_times_pass(self) -> None:
        """Two entries in the same minute is ordinary, not a defect."""
        body = _PREAMBLE + _entry("12:49") + _entry("12:49") + _entry("13:00")
        assert _EDIT.run(_ctx(body)) == []

    def test_a_single_entry_passes(self) -> None:
        assert _EDIT.run(_ctx(_PREAMBLE + _entry("12:49"))) == []

    def test_no_entries_passes(self) -> None:
        assert _EDIT.run(_ctx(_PREAMBLE)) == []

    def test_the_measured_regression_is_caught(self) -> None:
        """The exact sequence that passed the sweep with 0 findings."""
        body = (
            _PREAMBLE
            + _entry("12:49", "thought")
            + _entry("12:58", "finding")
            + _entry("13:00", "finding")
            + _entry("12:50", "session crons")
        )
        findings = _EDIT.run(_ctx(body))
        assert len(findings) == 1
        assert findings[0].check_id == "journal-entry-ordering"

    def test_the_message_names_both_times(self) -> None:
        body = _PREAMBLE + _entry("13:00") + _entry("12:50")
        message = _EDIT.run(_ctx(body))[0].message
        assert "12:50" in message
        assert "13:00" in message


class TestWhatIsNotAnEntry:
    def test_a_heading_inside_a_fence_is_not_an_entry(self) -> None:
        """Journals embed fenced logs; a heading in one is quoted text."""
        body = (
            _PREAMBLE
            + _entry("09:00")
            + "## 13:00 · action · — — real\n\n"
            + "```\n## 08:00 · action · — — quoted from elsewhere\n```\n\n"
        )
        assert _EDIT.run(_ctx(body)) == []

    def test_the_blockquoted_grammar_example_is_not_an_entry(self) -> None:
        """`> ## HH:MM` in the preamble must never count."""
        assert _EDIT.run(_ctx(_PREAMBLE + _entry("09:00"))) == []

    def test_a_heading_without_a_time_is_ignored(self) -> None:
        body = _PREAMBLE + _entry("09:00") + "## Notes\n\nfree text\n\n" + _entry("10:00")
        assert _EDIT.run(_ctx(body)) == []


class TestPolicy:
    def test_block_mode_raises_the_level(self) -> None:
        body = _PREAMBLE + _entry("13:00") + _entry("12:50")
        findings = _EDIT.run(_ctx(body, journal_mode="block"))
        assert findings[0].level == Level.BLOCK

    def test_journalling_disabled_is_a_no_match(self) -> None:
        body = _PREAMBLE + _entry("13:00") + _entry("12:50")
        assert _EDIT.run(_ctx(body, journal_enabled=False)) == []

    def test_a_non_journal_file_is_ignored(self) -> None:
        root = Path("/repo")
        ctx = CheckContext(
            project_root=root,
            plan_dir_rel="CLAUDE/Plan",
            file_path=root / "CLAUDE" / "Plan" / "00377-thing" / "PLAN.md",
            file_content=_PREAMBLE + _entry("13:00") + _entry("12:50"),
            file_exists_before=True,
            today=date(2026, 9, 11),
            journal_enabled=True,
            journal_mode="advise",
            journal_dir_name="JOURNAL",
        )
        assert _EDIT.run(ctx) == []


def _sweep_check_ids(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    *,
    dayfile_date: date | None = None,
    archived: bool = False,
) -> list[str]:
    """Build a one-plan tree with an out-of-order day-file and sweep it."""
    import argparse
    import json
    import subprocess

    from claude_code_hooks_daemon.constants.timeout import Timeout
    from claude_code_hooks_daemon.daemon.cli import cmd_plan_qa

    root = tmp_path / "repo"
    plan_dir = root / "CLAUDE" / "Plan"
    (plan_dir / "Completed").mkdir(parents=True)
    (plan_dir / "Cancelled").mkdir()
    (root / ".claude").mkdir()
    (root / ".claude" / "hooks-daemon.yaml").write_text("plan_workflow:\n  enabled: true\n")

    parent = plan_dir / "Completed" if archived else plan_dir
    folder = parent / "00001-first"
    folder.mkdir()
    status = "Complete" if archived else "In Progress"
    (folder / "PLAN.md").write_text(
        f"# Plan 00001: first\n\n**Status**: {status}\n\n- [ ] ⬜ **Task 1.1**: x\n"
    )
    journal = folder / "JOURNAL"
    journal.mkdir()
    stamp = dayfile_date or date.today()
    (journal / f"00001-Journal-{stamp:%y-%m-%d}.md").write_text(
        _PREAMBLE + _entry("13:00") + _entry("12:50")
    )
    (plan_dir / "README.md").write_text(
        "# Plans Index\n\n## Active Plans\n\n" f"- [00001: first](00001-first/PLAN.md) - {status}\n"
    )
    subprocess.run(
        ["git", "init", str(root)],
        capture_output=True,
        check=True,
        timeout=Timeout.GIT_CONTEXT,
    )

    cmd_plan_qa(
        argparse.Namespace(
            project_root=root,
            sweep=True,
            check_staged=False,
            lint=None,
            json_output=True,
        )
    )
    return [f["check_id"] for f in json.loads(capsys.readouterr().out)]


class TestTheSweepSeesItToo:
    """N1 was specifically a SWEEP gap — the edit-time half already worked."""

    def test_an_out_of_order_dayfile_on_disk_is_reported(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert "journal-entry-ordering" in _sweep_check_ids(tmp_path, capsys)


class TestTheSweepsDeliberateBlindSpots:
    """Both exclusions are design decisions, not oversights — guard them.

    Each exists because the finding would be one nobody may act on, and a
    permanently unfixable finding trains readers to ignore the whole check.
    """

    def test_a_pre_cutoff_dayfile_is_grandfathered(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """No backfill: a file written before the rule could not have complied.

        The journals on disk when this shipped had the narrative order right
        and the CLOCK READINGS wrong, so the only available "fix" was inventing
        timestamps in an append-only record.
        """
        ids = _sweep_check_ids(tmp_path, capsys, dayfile_date=date(2026, 7, 14))
        assert "journal-entry-ordering" not in ids

    def test_an_archived_plans_journal_is_not_swept(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """`archive-immutability` forbids the edit that would fix it."""
        ids = _sweep_check_ids(tmp_path, capsys, archived=True)
        assert "journal-entry-ordering" not in ids
