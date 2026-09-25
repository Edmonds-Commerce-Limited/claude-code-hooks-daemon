"""Tests for ``archival-links-resolve`` (Plan 00408 Task 3.2b).

Archiving a plan moves it one directory deeper, so every relative link it makes
shifts by one level. Archiving 00406 and 00407 turned four ``../00408-…`` links
and two ``../Completed/00405-…`` links dead, and ``docs-qa --sweep`` reported the
corpus clean: archived plans are outside its scope, deliberately, because an
archived plan is a record. The archival commit is the one moment the record is
still being written, so that is where this check runs.
"""

from pathlib import Path
from unittest.mock import create_autospec

from claude_code_hooks_daemon.plan_qa.checks.archival_links_resolve import CHECK, CHECK_ID
from claude_code_hooks_daemon.plan_qa.gitfacts import GitFacts, StagedChange
from claude_code_hooks_daemon.plan_qa.types import CheckContext, Level, Stage

_PLAN = "CLAUDE/Plan"
_OLD = f"{_PLAN}/00406-archived-now/PLAN.md"
_NEW = f"{_PLAN}/Completed/00406-archived-now/PLAN.md"


def _write(root: Path, rel: str, text: str = "# x\n") -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _context(
    root: Path, moves: dict[str, str], texts: dict[str, str], *, extra: tuple[str, ...] = ()
) -> CheckContext:
    for new, text in texts.items():
        _write(root, new, text)
    gitfacts = create_autospec(GitFacts, instance=True)
    changes = [StagedChange(status="R100", path=new, old_path=old) for old, new in moves.items()]
    changes += [StagedChange(status="M", path=path, old_path=None) for path in extra]
    gitfacts.staged_changes.return_value = tuple(changes)
    gitfacts.staged_file_text.side_effect = lambda path: texts.get(path)
    return CheckContext(project_root=root, plan_dir_rel=_PLAN, gitfacts=gitfacts)


def _tree(root: Path) -> None:
    _write(root, f"{_PLAN}/00408-still-live/PLAN.md")
    _write(root, f"{_PLAN}/Completed/00405-archived-earlier/PLAN.md")


class TestRegistration:
    def test_commit_only(self) -> None:
        assert CHECK.stage is Stage.COMMIT
        assert CHECK.check_id == CHECK_ID


class TestAMoveThatBreaksALink:
    def test_a_link_to_a_live_sibling_is_reported_with_its_repoint(self, tmp_path: Path) -> None:
        _tree(tmp_path)
        text = "See [live](../00408-still-live/PLAN.md#tasks).\n"
        findings = CHECK.run(_context(tmp_path, {_OLD: _NEW}, {_NEW: text}))

        assert [finding.level for finding in findings] == [Level.BLOCK]
        assert "../00408-still-live/PLAN.md#tasks" in findings[0].message
        assert "../../00408-still-live/PLAN.md#tasks" in findings[0].remediation
        assert findings[0].path == _NEW

    def test_a_link_into_the_archive_is_reported_with_its_repoint(self, tmp_path: Path) -> None:
        _tree(tmp_path)
        text = "Was [old](../Completed/00405-archived-earlier/PLAN.md).\n"
        findings = CHECK.run(_context(tmp_path, {_OLD: _NEW}, {_NEW: text}))

        assert len(findings) == 1
        assert "`../00405-archived-earlier/PLAN.md`" in findings[0].remediation


class TestWhatIsLeftAlone:
    def test_a_link_that_still_resolves_is_silent(self, tmp_path: Path) -> None:
        _tree(tmp_path)
        text = "[x](https://example.test) [y](#local) [z](/CLAUDE/Plan/00408-still-live/PLAN.md)\n"

        assert CHECK.run(_context(tmp_path, {_OLD: _NEW}, {_NEW: text})) == []

    def test_two_plans_archived_together_still_reach_each_other(self, tmp_path: Path) -> None:
        """Both moved one level down, so the relative link between them holds."""
        _tree(tmp_path)
        other_old = f"{_PLAN}/00407-archived-with-it/PLAN.md"
        other_new = f"{_PLAN}/Completed/00407-archived-with-it/PLAN.md"
        texts = {_NEW: "[sib](../00407-archived-with-it/PLAN.md)\n", other_new: "# 407\n"}

        assert CHECK.run(_context(tmp_path, {_OLD: _NEW, other_old: other_new}, texts)) == []

    def test_a_link_already_dead_before_the_move_is_not_blamed_on_it(self, tmp_path: Path) -> None:
        _tree(tmp_path)
        text = "[gone](../00001-never-existed/PLAN.md)\n"
        findings = CHECK.run(_context(tmp_path, {_OLD: _NEW}, {_NEW: text}))

        assert [finding.level for finding in findings] == [Level.ADVISE]

    def test_a_journal_day_file_is_append_only_and_skipped(self, tmp_path: Path) -> None:
        _tree(tmp_path)
        old = f"{_PLAN}/00406-archived-now/JOURNAL/00406-Journal-26-09-14.md"
        new = f"{_PLAN}/Completed/00406-archived-now/JOURNAL/00406-Journal-26-09-14.md"
        text = "[live](../../00408-still-live/PLAN.md)\n"

        assert CHECK.run(_context(tmp_path, {old: new}, {new: text})) == []

    def test_an_edit_in_place_is_not_an_archival(self, tmp_path: Path) -> None:
        _tree(tmp_path)

        assert CHECK.run(_context(tmp_path, {}, {}, extra=(_NEW,))) == []

    def test_no_gitfacts_is_silent(self, tmp_path: Path) -> None:
        assert CHECK.run(CheckContext(project_root=tmp_path, plan_dir_rel=_PLAN)) == []
