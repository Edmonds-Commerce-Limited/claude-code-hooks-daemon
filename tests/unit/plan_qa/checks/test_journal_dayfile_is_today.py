"""Tests for the ``journal-dayfile-is-today`` EDIT check (Plan 00197).

A journal day-file edit whose embedded date is not EXACTLY today is BLOCKED
by default — the "yesterday is fine" tolerance that ``journal-dayfile-naming``
grants is exactly the agent confusion this check closes (a session that spans
midnight should start today's day-file, not keep appending to yesterday's).
Grammar/calendar-validity/plan-number problems remain
``journal-dayfile-naming``'s job; this check only judges recency of an
otherwise well-formed name.
"""

import subprocess
from datetime import date
from pathlib import Path

import pytest

from claude_code_hooks_daemon.plan_qa.checks import all_checks, journal_dayfile_is_today
from claude_code_hooks_daemon.plan_qa.gitfacts import GitFacts
from claude_code_hooks_daemon.plan_qa.types import CheckContext, Finding, Level, Stage
from tests.support.git_fixtures import git_setup_timeout


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
        spec = journal_dayfile_is_today.EDIT_CHECK
        assert spec.check_id == "journal-dayfile-is-today"
        assert spec.stage == Stage.EDIT
        assert spec.level == Level.BLOCK


class TestRun:
    def test_todays_dayfile_passes(self) -> None:
        assert journal_dayfile_is_today.EDIT_CHECK.run(_ctx("00197-Journal-26-08-07.md")) == []

    def test_yesterday_is_blocked(self) -> None:
        # Unlike journal-dayfile-naming, yesterday is NOT tolerated here.
        findings = journal_dayfile_is_today.EDIT_CHECK.run(_ctx("00197-Journal-26-08-06.md"))
        assert len(findings) == 1
        assert findings[0].level == Level.BLOCK
        assert "today" in findings[0].message.lower()

    def test_future_date_is_blocked(self) -> None:
        findings = journal_dayfile_is_today.EDIT_CHECK.run(_ctx("00197-Journal-26-08-08.md"))
        assert len(findings) == 1
        assert findings[0].level == Level.BLOCK

    def test_far_past_date_is_blocked(self) -> None:
        findings = journal_dayfile_is_today.EDIT_CHECK.run(_ctx("00197-Journal-26-01-01.md"))
        assert len(findings) == 1
        assert findings[0].level == Level.BLOCK

    def test_remediation_names_exact_todays_filename(self) -> None:
        findings = journal_dayfile_is_today.EDIT_CHECK.run(_ctx("00197-Journal-26-08-06.md"))
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
        findings = journal_dayfile_is_today.EDIT_CHECK.run(ctx)
        assert len(findings) == 1
        assert "NNNNN-Journal-YY-MM-DD.md" in findings[0].remediation

    def test_creating_todays_dayfile_passes(self) -> None:
        # file_exists_before=False (a creation) with today's date is clean.
        assert journal_dayfile_is_today.EDIT_CHECK.run(_ctx("00197-Journal-26-08-07.md")) == []

    def test_non_journal_file_is_ignored(self) -> None:
        root = Path("/repo")
        ctx = CheckContext(
            project_root=root,
            plan_dir_rel="CLAUDE/Plan",
            file_path=root / "CLAUDE" / "Plan" / "00197-thing" / "PLAN.md",
            file_content="x",
            journal_enabled=True,
        )
        assert journal_dayfile_is_today.EDIT_CHECK.run(ctx) == []

    def test_malformed_name_defers_to_naming_check(self) -> None:
        # journal-dayfile-naming owns grammar problems; this check must not
        # crash or double-report an unparseable name.
        assert journal_dayfile_is_today.EDIT_CHECK.run(_ctx("my-journal.md")) == []

    def test_impossible_calendar_date_defers_to_naming_check(self) -> None:
        assert journal_dayfile_is_today.EDIT_CHECK.run(_ctx("00197-Journal-26-13-45.md")) == []

    def test_today_unknown_fails_open(self) -> None:
        # e.g. the `plan-qa --lint` CLI path never supplies today — blocking
        # on missing clock information would be worse than the bug.
        assert (
            journal_dayfile_is_today.EDIT_CHECK.run(_ctx("00197-Journal-26-01-01.md", today=None))
            == []
        )

    def test_legacy_allowlisted_plan_only_advises(self) -> None:
        findings = journal_dayfile_is_today.EDIT_CHECK.run(
            _ctx("00197-Journal-26-08-06.md", legacy_plan_allowlist=frozenset({197}))
        )
        assert len(findings) == 1
        assert findings[0].level == Level.ADVISE

    def test_advise_mode_never_blocks(self) -> None:
        findings = journal_dayfile_is_today.EDIT_CHECK.run(
            _ctx("00197-Journal-26-08-06.md", today_only_mode="advise")
        )
        assert len(findings) == 1
        assert findings[0].level == Level.ADVISE

    def test_off_mode_disables_check(self) -> None:
        assert (
            journal_dayfile_is_today.EDIT_CHECK.run(
                _ctx("00197-Journal-26-08-06.md", today_only_mode="off")
            )
            == []
        )

    def test_disabled_journalling_is_ignored(self) -> None:
        assert (
            journal_dayfile_is_today.EDIT_CHECK.run(
                _ctx("00197-Journal-26-08-06.md", journal_enabled=False)
            )
            == []
        )
        assert (
            journal_dayfile_is_today.EDIT_CHECK.run(
                _ctx("00197-Journal-26-08-06.md", journal_mode="off")
            )
            == []
        )


_ENTRY_FOLDER = "2026-08-06"
_ENTRY_NAME = "093015Z-action-0a1b2c.md"
_ENTRY_BODY = "## 09:30 · action · — — thing\n\nBody.\n"


def _existing_ctx(
    *,
    entry_file: bool = True,
    before: str = _ENTRY_BODY,
    after: str = _ENTRY_BODY + "\nMore.\n",
    today_only_mode: str = "block",
    legacy_plan_allowlist: frozenset[int] = frozenset(),
) -> CheckContext:
    root = Path("/repo")
    journal = root / "CLAUDE" / "Plan" / "00197-thing" / "JOURNAL"
    file_path = (
        journal / _ENTRY_FOLDER / _ENTRY_NAME
        if entry_file
        else journal / "00197-Journal-26-08-07.md"
    )
    return CheckContext(
        project_root=root,
        plan_dir_rel="CLAUDE/Plan",
        file_path=file_path,
        file_content=after,
        file_content_before=before,
        file_exists_before=True,
        today=date(2026, 8, 7),
        journal_enabled=True,
        journal_mode="advise",
        journal_dir_name="JOURNAL",
        journal_today_only_mode=today_only_mode,
        legacy_plan_allowlist=legacy_plan_allowlist,
    )


def _edit_run(context: CheckContext) -> list[str]:
    return [finding.check_id for finding in journal_dayfile_is_today.EDIT_CHECK.run(context)]


@pytest.fixture
def _no_head(monkeypatch: pytest.MonkeyPatch) -> None:
    """No committed copy: the file is not tracked at HEAD."""
    monkeypatch.setattr(journal_dayfile_is_today, "_head_text", lambda _context, _rel: None)


class TestRegistration:
    def test_edit_and_commit_halves(self) -> None:
        stages = [spec.stage for spec in journal_dayfile_is_today.CHECKS]
        assert stages == [Stage.EDIT, Stage.COMMIT]
        assert {spec.check_id for spec in journal_dayfile_is_today.CHECKS} == {
            "journal-dayfile-is-today"
        }

    def test_the_commit_half_is_in_the_catalogue(self) -> None:
        assert journal_dayfile_is_today.COMMIT_CHECK in all_checks()


@pytest.mark.usefixtures("_no_head")
class TestAnExistingJournalFileIsClosed:
    """Plan 00543: a legacy day-file is closed and an entry file is immutable.

    New entries are new files, so any write to a journal file that already
    exists is a rewrite of the record, today's date or not.
    """

    def test_editing_an_existing_entry_file_is_blocked(self) -> None:
        findings = journal_dayfile_is_today.EDIT_CHECK.run(_existing_ctx())
        assert len(findings) == 1
        assert findings[0].level is Level.BLOCK
        assert _ENTRY_NAME in findings[0].message

    def test_appending_to_todays_legacy_dayfile_is_blocked(self) -> None:
        assert _edit_run(_existing_ctx(entry_file=False)) == ["journal-dayfile-is-today"]

    def test_a_no_op_write_is_clean(self) -> None:
        assert _edit_run(_existing_ctx(after=_ENTRY_BODY)) == []

    def test_removing_only_conflict_markers_is_clean(self) -> None:
        """Parity with plan_journal_guard: both sides' entries survive."""
        conflicted = f"<<<<<<< HEAD\n{_ENTRY_BODY}=======\n{_ENTRY_BODY}>>>>>>> other\n"
        assert _edit_run(_existing_ctx(before=conflicted, after=_ENTRY_BODY + _ENTRY_BODY)) == []

    def test_legacy_allowlisted_plan_only_advises(self) -> None:
        findings = journal_dayfile_is_today.EDIT_CHECK.run(
            _existing_ctx(legacy_plan_allowlist=frozenset({197}))
        )
        assert [finding.level for finding in findings] == [Level.ADVISE]

    def test_advise_mode_never_blocks(self) -> None:
        findings = journal_dayfile_is_today.EDIT_CHECK.run(_existing_ctx(today_only_mode="advise"))
        assert [finding.level for finding in findings] == [Level.ADVISE]

    def test_off_mode_disables_it(self) -> None:
        assert _edit_run(_existing_ctx(today_only_mode="off")) == []


def test_restoring_the_committed_bytes_is_clean(monkeypatch: pytest.MonkeyPatch) -> None:
    """Parity with plan_journal_guard: a restore to HEAD can only undo a change."""
    monkeypatch.setattr(journal_dayfile_is_today, "_head_text", lambda _context, _rel: _ENTRY_BODY)
    assert _edit_run(_existing_ctx(before=_ENTRY_BODY + "stray\n", after=_ENTRY_BODY)) == []


class TestCreatingAnEntryFile:
    def test_creating_an_entry_file_is_clean_whatever_its_folder(self) -> None:
        """The scaffolder names the folder from the UTC clock; creation is the one route."""
        root = Path("/repo")
        context = CheckContext(
            project_root=root,
            plan_dir_rel="CLAUDE/Plan",
            file_path=root
            / "CLAUDE"
            / "Plan"
            / "00197-thing"
            / "JOURNAL"
            / _ENTRY_FOLDER
            / _ENTRY_NAME,
            file_content=_ENTRY_BODY,
            file_exists_before=False,
            today=date(2026, 8, 7),
            journal_enabled=True,
            journal_mode="advise",
            journal_dir_name="JOURNAL",
            journal_today_only_mode="block",
        )
        assert _edit_run(context) == []


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        check=True,
        timeout=git_setup_timeout(),
    )


_REPO_JOURNAL = "CLAUDE/Plan/00197-thing/JOURNAL"
_REPO_ENTRY = f"{_REPO_JOURNAL}/{_ENTRY_FOLDER}/{_ENTRY_NAME}"
_REPO_DAYFILE = f"{_REPO_JOURNAL}/00197-Journal-26-08-06.md"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test User")
    (root / _REPO_ENTRY).parent.mkdir(parents=True)
    (root / _REPO_ENTRY).write_text(_ENTRY_BODY)
    (root / _REPO_DAYFILE).write_text("# Journal\n\n## 09:00 · action\n\nstart\n")
    (root / "CLAUDE/Plan/00197-thing/PLAN.md").write_text("# Plan 00197: thing\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "initial")
    return root


def _commit_run(root: Path, *, today_only_mode: str = "block") -> list[Finding]:
    context = CheckContext(
        project_root=root,
        plan_dir_rel="CLAUDE/Plan",
        gitfacts=GitFacts(root),
        journal_enabled=True,
        journal_mode="advise",
        journal_dir_name="JOURNAL",
        journal_today_only_mode=today_only_mode,
    )
    return journal_dayfile_is_today.COMMIT_CHECK.run(context)


class TestCommitHalf:
    """The gate a Bash write reaches: what the EDIT half never sees."""

    def test_no_gitfacts_is_silent(self) -> None:
        context = CheckContext(project_root=Path("/repo"), plan_dir_rel="CLAUDE/Plan")
        assert journal_dayfile_is_today.COMMIT_CHECK.run(context) == []

    def test_a_modified_entry_file_is_blocked(self, repo: Path) -> None:
        (repo / _REPO_ENTRY).write_text(_ENTRY_BODY + "rewritten\n")
        _git(repo, "add", "-A")
        findings = _commit_run(repo)
        assert [(finding.path, finding.level) for finding in findings] == [
            (_REPO_ENTRY, Level.BLOCK)
        ]

    def test_a_deleted_entry_file_is_blocked(self, repo: Path) -> None:
        _git(repo, "rm", "-q", _REPO_ENTRY)
        assert [finding.path for finding in _commit_run(repo)] == [_REPO_ENTRY]

    def test_a_new_entry_file_is_clean(self, repo: Path) -> None:
        new = repo / _REPO_JOURNAL / _ENTRY_FOLDER / "101500Z-action-abcdef.md"
        new.write_text("## 10:15 · action · — — next\n\nBody.\n")
        _git(repo, "add", "-A")
        assert _commit_run(repo) == []

    def test_a_pure_rename_is_clean(self, repo: Path) -> None:
        """Archiving a plan moves its entry files without changing a byte."""
        _git(repo, "mv", "CLAUDE/Plan/00197-thing", "CLAUDE/Plan/00197-moved")
        assert _commit_run(repo) == []

    def test_a_rename_with_changed_content_is_blocked(self, repo: Path) -> None:
        _git(repo, "mv", "CLAUDE/Plan/00197-thing", "CLAUDE/Plan/00197-moved")
        moved = repo / "CLAUDE/Plan/00197-moved/JOURNAL" / _ENTRY_FOLDER / _ENTRY_NAME
        moved.write_text(_ENTRY_BODY + "rewritten\n")
        _git(repo, "add", "-A")
        assert len(_commit_run(repo)) == 1

    def test_a_modified_legacy_dayfile_is_left_to_the_guard(self, repo: Path) -> None:
        (repo / _REPO_DAYFILE).write_text("# Journal\n\n## 09:00 · action\n\nstart\n\nmore\n")
        _git(repo, "add", "-A")
        assert _commit_run(repo) == []

    def test_off_mode_is_silent(self, repo: Path) -> None:
        _git(repo, "rm", "-q", _REPO_ENTRY)
        assert _commit_run(repo, today_only_mode="off") == []
