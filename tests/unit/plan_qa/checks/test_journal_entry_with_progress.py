"""Tests for the journal-entry-with-progress COMMIT check (Plan 00163 P3)."""

import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.plan_qa.checks.journal_entry_with_progress import CHECK
from claude_code_hooks_daemon.plan_qa.gitfacts import GitFacts
from claude_code_hooks_daemon.plan_qa.types import CheckContext, Level, Stage

_PLAN_DIR_REL = "CLAUDE/Plan"

_PLAN_ONE_TASK = (
    "# Plan 00200: Widget\n\n**Status**: In Progress\n\n"
    "## Tasks\n\n- [ ] ⬜ **Task 1.1**: do a thing\n"
)
_PLAN_TASK_TICKED = (
    "# Plan 00200: Widget\n\n**Status**: In Progress\n\n"
    "## Tasks\n\n- [x] ✅ **Task 1.1**: do a thing\n"
)
_PLAN_PROSE_ONLY_EDIT = (
    "# Plan 00200: Widget — revised title\n\n**Status**: In Progress\n\n"
    "## Tasks\n\n- [ ] ⬜ **Task 1.1**: do a thing\n"
)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        check=True,
        timeout=Timeout.GIT_CONTEXT,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test User")
    plan_dir = root / "CLAUDE" / "Plan" / "00200-widget"
    (plan_dir / "JOURNAL").mkdir(parents=True)
    (plan_dir / "PLAN.md").write_text(_PLAN_ONE_TASK)
    (plan_dir / "JOURNAL" / "00200-Journal-26-07-14.md").write_text(
        "# Journal\n\n## 09:00 · action\n\nstart\n"
    )
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "initial")
    return root


def _context(
    root: Path,
    *,
    journal_enabled: bool = True,
    journal_mode: str = "advise",
    journal_grandfather_before: int = 163,
) -> CheckContext:
    return CheckContext(
        project_root=root,
        plan_dir_rel=_PLAN_DIR_REL,
        gitfacts=GitFacts(root),
        journal_enabled=journal_enabled,
        journal_mode=journal_mode,
        journal_grandfather_before=journal_grandfather_before,
    )


class TestSpec:
    def test_registered_for_commit_stage_advise(self) -> None:
        assert CHECK.check_id == "journal-entry-with-progress"
        assert CHECK.stage == Stage.COMMIT
        assert CHECK.level == Level.ADVISE
        assert CHECK.sins == ()


class TestScope:
    def test_no_gitfacts_returns_empty(self) -> None:
        context = CheckContext(project_root=Path("/repo"), plan_dir_rel=_PLAN_DIR_REL)
        assert CHECK.run(context) == []

    def test_journalling_disabled_returns_empty(self, repo: Path) -> None:
        (repo / "CLAUDE/Plan/00200-widget/PLAN.md").write_text(_PLAN_TASK_TICKED)
        _git(repo, "add", "-A")
        context = _context(repo, journal_enabled=False)
        assert CHECK.run(context) == []

    def test_journal_mode_off_returns_empty(self, repo: Path) -> None:
        (repo / "CLAUDE/Plan/00200-widget/PLAN.md").write_text(_PLAN_TASK_TICKED)
        _git(repo, "add", "-A")
        context = _context(repo, journal_mode="off")
        assert CHECK.run(context) == []

    def test_grandfathered_plan_returns_empty(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        root.mkdir()
        _git(root, "init")
        _git(root, "config", "user.email", "t@e.com")
        _git(root, "config", "user.name", "T")
        legacy = root / "CLAUDE" / "Plan" / "00042-legacy"
        legacy.mkdir(parents=True)
        legacy.joinpath("PLAN.md").write_text(_PLAN_ONE_TASK.replace("00200", "00042"))
        _git(root, "add", "-A")
        _git(root, "commit", "-m", "initial")
        legacy.joinpath("PLAN.md").write_text(_PLAN_TASK_TICKED.replace("00200", "00042"))
        _git(root, "add", "-A")
        context = _context(root)
        # Plan 42 < grandfather_before(163) → never nagged.
        assert CHECK.run(context) == []

    def test_prose_only_edit_is_clean(self, repo: Path) -> None:
        (repo / "CLAUDE/Plan/00200-widget/PLAN.md").write_text(_PLAN_PROSE_ONLY_EDIT)
        _git(repo, "add", "-A")
        context = _context(repo)
        # Tasks unchanged → not a progress edit → no nag.
        assert CHECK.run(context) == []


class TestFindings:
    def test_task_change_without_journal_entry_advises(self, repo: Path) -> None:
        (repo / "CLAUDE/Plan/00200-widget/PLAN.md").write_text(_PLAN_TASK_TICKED)
        _git(repo, "add", "-A")
        context = _context(repo)
        findings = CHECK.run(context)
        assert len(findings) == 1
        assert findings[0].check_id == "journal-entry-with-progress"
        assert findings[0].level == Level.ADVISE
        assert "00200" in findings[0].message

    def test_task_change_with_new_journal_entry_is_clean(self, repo: Path) -> None:
        (repo / "CLAUDE/Plan/00200-widget/PLAN.md").write_text(_PLAN_TASK_TICKED)
        (repo / "CLAUDE/Plan/00200-widget/JOURNAL/00200-Journal-26-07-15.md").write_text(
            "# Journal\n\n## 10:00 · action\n\nticked task 1.1\n"
        )
        _git(repo, "add", "-A")
        context = _context(repo)
        assert CHECK.run(context) == []

    def test_task_change_with_appended_journal_entry_is_clean(self, repo: Path) -> None:
        (repo / "CLAUDE/Plan/00200-widget/PLAN.md").write_text(_PLAN_TASK_TICKED)
        day = repo / "CLAUDE/Plan/00200-widget/JOURNAL/00200-Journal-26-07-14.md"
        day.write_text(day.read_text() + "\n## 10:00 · action\n\nticked task 1.1\n")
        _git(repo, "add", "-A")
        context = _context(repo)
        assert CHECK.run(context) == []

    def test_unrelated_deletion_staged_alongside_is_ignored(self, repo: Path) -> None:
        # A non-A/M staged change (a deletion) must be skipped, not crash.
        (repo / "CLAUDE/Plan/00200-widget/PLAN.md").write_text(_PLAN_TASK_TICKED)
        (repo / "CLAUDE/Plan/00200-widget/JOURNAL/00200-Journal-26-07-15.md").write_text(
            "# Journal\n\n## 10:00 · action\n\nticked\n"
        )
        _git(repo, "rm", "CLAUDE/Plan/00200-widget/JOURNAL/00200-Journal-26-07-14.md")
        _git(repo, "add", "-A")
        context = _context(repo)
        # Task change + a fresh journal entry staged → clean despite the deletion.
        assert CHECK.run(context) == []

    def test_new_plan_with_tasks_and_no_journal_advises(self, repo: Path) -> None:
        newplan = repo / "CLAUDE/Plan/00201-new"
        newplan.mkdir()
        newplan.joinpath("PLAN.md").write_text(_PLAN_ONE_TASK.replace("00200", "00201"))
        _git(repo, "add", "-A")
        context = _context(repo)
        findings = CHECK.run(context)
        assert [f.message for f in findings if "00201" in f.message]
