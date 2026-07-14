"""Tests for the journal-completion-entry COMMIT check (Plan 00163 P3)."""

import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.plan_qa.checks.journal_completion_entry import CHECK
from claude_code_hooks_daemon.plan_qa.gitfacts import GitFacts
from claude_code_hooks_daemon.plan_qa.types import CheckContext, Level, Stage

_PLAN_DIR_REL = "CLAUDE/Plan"

_PLAN_IN_PROGRESS = "# Plan 00200: Widget\n\n**Status**: In Progress\n\n## Tasks\n\n- [x] ✅ done\n"
_PLAN_COMPLETE = "# Plan 00200: Widget\n\n**Status**: Complete\n\n## Tasks\n\n- [x] ✅ done\n"
_JOURNAL_DAY1 = "# Journal\n\n## 09:00 · action\n\nstart\n"


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
    (plan_dir / "PLAN.md").write_text(_PLAN_IN_PROGRESS)
    (plan_dir / "JOURNAL" / "00200-Journal-26-07-14.md").write_text(_JOURNAL_DAY1)
    (root / "CLAUDE" / "Plan" / "Completed").mkdir()
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "initial")
    return root


def _context(
    root: Path,
    *,
    journal_enabled: bool = True,
    journal_mode: str = "advise",
    journal_enforce_on_completion: bool = True,
    journal_grandfather_before: int = 163,
) -> CheckContext:
    return CheckContext(
        project_root=root,
        plan_dir_rel=_PLAN_DIR_REL,
        gitfacts=GitFacts(root),
        journal_enabled=journal_enabled,
        journal_mode=journal_mode,
        journal_enforce_on_completion=journal_enforce_on_completion,
        journal_grandfather_before=journal_grandfather_before,
    )


def _complete_via_move(repo: Path) -> None:
    """Stage a terminal flip: move folder to Completed/ and flip status."""
    _git(repo, "mv", "CLAUDE/Plan/00200-widget", "CLAUDE/Plan/Completed/00200-widget")
    (repo / "CLAUDE/Plan/Completed/00200-widget/PLAN.md").write_text(_PLAN_COMPLETE)
    _git(repo, "add", "-A")


class TestSpec:
    def test_registered_for_commit_stage_advise(self) -> None:
        assert CHECK.check_id == "journal-completion-entry"
        assert CHECK.stage == Stage.COMMIT
        assert CHECK.level == Level.ADVISE
        assert CHECK.sins == ()


class TestScope:
    def test_no_gitfacts_returns_empty(self) -> None:
        context = CheckContext(
            project_root=Path("/repo"),
            plan_dir_rel=_PLAN_DIR_REL,
            journal_enforce_on_completion=True,
        )
        assert CHECK.run(context) == []

    def test_enforce_off_returns_empty(self, repo: Path) -> None:
        _complete_via_move(repo)
        context = _context(repo, journal_enforce_on_completion=False)
        # Opt-in gate off (the default) → never fires.
        assert CHECK.run(context) == []

    def test_journalling_disabled_returns_empty(self, repo: Path) -> None:
        _complete_via_move(repo)
        context = _context(repo, journal_enabled=False)
        assert CHECK.run(context) == []

    def test_non_terminal_edit_is_clean(self, repo: Path) -> None:
        (repo / "CLAUDE/Plan/00200-widget/PLAN.md").write_text(
            _PLAN_IN_PROGRESS + "\n- [ ] ⬜ another task\n"
        )
        _git(repo, "add", "-A")
        context = _context(repo)
        # Real PLAN.md change, but still In Progress → not a completion.
        assert CHECK.run(context) == []

    def test_deleted_plan_md_is_clean(self, repo: Path) -> None:
        _git(repo, "rm", "CLAUDE/Plan/00200-widget/PLAN.md")
        context = _context(repo)
        # A staged deletion has no index content → not a terminal flip.
        assert CHECK.run(context) == []


class TestFindings:
    def test_completion_without_closing_entry_advises(self, repo: Path) -> None:
        _complete_via_move(repo)
        context = _context(repo)
        findings = CHECK.run(context)
        assert len(findings) == 1
        assert findings[0].check_id == "journal-completion-entry"
        assert findings[0].level == Level.ADVISE
        assert "00200" in findings[0].message

    def test_completion_with_new_dayfile_entry_is_clean(self, repo: Path) -> None:
        _git(repo, "mv", "CLAUDE/Plan/00200-widget", "CLAUDE/Plan/Completed/00200-widget")
        (repo / "CLAUDE/Plan/Completed/00200-widget/PLAN.md").write_text(_PLAN_COMPLETE)
        (repo / "CLAUDE/Plan/Completed/00200-widget/JOURNAL/00200-Journal-26-07-15.md").write_text(
            "# Journal\n\n## 16:00 · handoff\n\nplan complete\n"
        )
        _git(repo, "add", "-A")
        context = _context(repo)
        assert CHECK.run(context) == []

    def test_completion_with_appended_entry_to_moved_dayfile_is_clean(self, repo: Path) -> None:
        _git(repo, "mv", "CLAUDE/Plan/00200-widget", "CLAUDE/Plan/Completed/00200-widget")
        (repo / "CLAUDE/Plan/Completed/00200-widget/PLAN.md").write_text(_PLAN_COMPLETE)
        moved_day = repo / "CLAUDE/Plan/Completed/00200-widget/JOURNAL/00200-Journal-26-07-14.md"
        moved_day.write_text(moved_day.read_text() + "\n## 16:00 · handoff\n\nplan complete\n")
        _git(repo, "add", "-A")
        context = _context(repo)
        # An appended entry to a day-file that also moved shows as a rename with
        # changed content — that IS a real closing entry, so no nag.
        assert CHECK.run(context) == []

    def test_grandfathered_plan_returns_empty(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        root.mkdir()
        _git(root, "init")
        _git(root, "config", "user.email", "t@e.com")
        _git(root, "config", "user.name", "T")
        legacy = root / "CLAUDE" / "Plan" / "00042-legacy"
        legacy.mkdir(parents=True)
        legacy.joinpath("PLAN.md").write_text(_PLAN_IN_PROGRESS.replace("00200", "00042"))
        (root / "CLAUDE" / "Plan" / "Completed").mkdir()
        _git(root, "add", "-A")
        _git(root, "commit", "-m", "initial")
        _git(root, "mv", "CLAUDE/Plan/00042-legacy", "CLAUDE/Plan/Completed/00042-legacy")
        (root / "CLAUDE/Plan/Completed/00042-legacy/PLAN.md").write_text(
            _PLAN_COMPLETE.replace("00200", "00042")
        )
        _git(root, "add", "-A")
        context = _context(root)
        assert CHECK.run(context) == []
