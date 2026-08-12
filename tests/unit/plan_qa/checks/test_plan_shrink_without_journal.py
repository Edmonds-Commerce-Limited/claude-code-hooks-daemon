"""Tests for ``plan-shrink-without-journal`` (Plan 00190 Task 3.5).

Hazard 1 of the size design: telling an agent "your plan is too big" invites
DELETION. The correct move is to relocate narrative into ``JOURNAL/``, which
leaves a staged journal entry behind. A commit that shrinks a PLAN.md sharply
with no such entry is the signature of content having been destroyed rather
than moved.

Advisory only — a genuine curation pass that removes obsolete content is
legitimate, and git still has the history either way.
"""

import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.plan_qa.checks.plan_shrink_without_journal import CHECK, CHECK_ID
from claude_code_hooks_daemon.plan_qa.gitfacts import GitFacts
from claude_code_hooks_daemon.plan_qa.types import CheckContext, Level, Stage

_PLAN_DIR_REL = "CLAUDE/Plan"
_HEADER = "# Plan 00200: Widget\n\n**Status**: In Progress\n\n"


def _plan(extra_bytes: int) -> str:
    return _HEADER + ("narrative line about what happened\n" * (extra_bytes // 34))


_BIG_PLAN = _plan(12_000)
_SMALL_PLAN = _plan(1_000)


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
    (plan_dir / "PLAN.md").write_text(_BIG_PLAN)
    (plan_dir / "JOURNAL" / "00200-Journal-26-07-14.md").write_text("# Journal\n\n## 09:00 · a\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "initial")
    return root


def _context(root: Path, **overrides) -> CheckContext:
    return CheckContext(
        project_root=root,
        plan_dir_rel=_PLAN_DIR_REL,
        gitfacts=GitFacts(root),
        journal_grandfather_before=163,
        **overrides,
    )


def _shrink(repo: Path, *, with_journal_entry: bool) -> None:
    (repo / "CLAUDE/Plan/00200-widget/PLAN.md").write_text(_SMALL_PLAN)
    if with_journal_entry:
        day = repo / "CLAUDE/Plan/00200-widget/JOURNAL/00200-Journal-26-07-15.md"
        day.write_text("# Journal\n\n## 10:00 · action\n\nrelocated the narrative here\n")
    _git(repo, "add", "-A")


class TestSpec:
    def test_registered_for_commit_stage_advise(self) -> None:
        assert CHECK.check_id == CHECK_ID
        assert CHECK.stage == Stage.COMMIT
        assert CHECK.level == Level.ADVISE


class TestDetection:
    def test_large_shrink_without_journal_entry_advises(self, repo: Path) -> None:
        _shrink(repo, with_journal_entry=False)
        findings = CHECK.run(_context(repo))
        assert len(findings) == 1
        assert findings[0].level is Level.ADVISE

    def test_large_shrink_with_journal_entry_is_silent(self, repo: Path) -> None:
        """Relocation leaves a staged journal entry — that is the whole signal."""
        _shrink(repo, with_journal_entry=True)
        assert CHECK.run(_context(repo)) == []

    def test_message_names_relocation_not_restoration(self, repo: Path) -> None:
        _shrink(repo, with_journal_entry=False)
        finding = CHECK.run(_context(repo))[0]
        text = f"{finding.message} {finding.remediation}"
        assert "JOURNAL/" in text
        assert "00200" in text


class TestExtractionIntoSupportingDoc:
    """Plan 00211: extraction into a named supporting document is exactly as
    legitimate a relocation as a journal entry — the field report's
    restructure commit shrank PLAN.md by 9,525 bytes while staging three
    brand-new supporting `.md` files, and the check's ONLY reason for not
    flagging it was that a journal entry happened to also be staged. The
    check must not read a pure extraction (no journal entry at all) as
    deletion.
    """

    def test_large_shrink_with_new_supporting_doc_is_silent(self, repo: Path) -> None:
        (repo / "CLAUDE/Plan/00200-widget/PLAN.md").write_text(_SMALL_PLAN)
        (repo / "CLAUDE/Plan/00200-widget/RESEARCH.md").write_text(
            "# Research\n\nextracted findings\n"
        )
        _git(repo, "add", "-A")
        assert CHECK.run(_context(repo)) == []

    def test_shrink_with_neither_journal_entry_nor_supporting_doc_still_flags(
        self, repo: Path
    ) -> None:
        _shrink(repo, with_journal_entry=False)
        assert len(CHECK.run(_context(repo))) == 1

    def test_supporting_doc_nested_in_a_subdirectory_does_not_count(self, repo: Path) -> None:
        """Only DIRECT children of the plan folder are supporting docs —
        matches the report's "in the same plan folder (excluding JOURNAL/)"
        wording; a nested assets/ subfolder is not the plan folder itself."""
        (repo / "CLAUDE/Plan/00200-widget/PLAN.md").write_text(_SMALL_PLAN)
        assets_dir = repo / "CLAUDE/Plan/00200-widget/assets"
        assets_dir.mkdir()
        (assets_dir / "diagram.md").write_text("# Diagram notes\n")
        _git(repo, "add", "-A")
        assert len(CHECK.run(_context(repo))) == 1

    def test_modified_existing_supporting_doc_does_not_count(self, repo: Path) -> None:
        """Only a NEW (Added) supporting doc counts — modifying PLAN.md
        alongside an unrelated pre-existing supporting doc edit is not
        evidence of relocation."""
        (repo / "CLAUDE/Plan/00200-widget/EXISTING.md").write_text("old content\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-m", "seed existing supporting doc")
        (repo / "CLAUDE/Plan/00200-widget/PLAN.md").write_text(_SMALL_PLAN)
        (repo / "CLAUDE/Plan/00200-widget/EXISTING.md").write_text("old content, tweaked\n")
        _git(repo, "add", "-A")
        assert len(CHECK.run(_context(repo))) == 1

    def test_new_plan_md_itself_does_not_count_as_a_supporting_doc(self, repo: Path) -> None:
        """PLAN.md is never its own evidence of relocation, even though it
        is technically staged as part of the shrink."""
        (repo / "CLAUDE/Plan/00200-widget/PLAN.md").write_text(_SMALL_PLAN)
        _git(repo, "add", "-A")
        assert len(CHECK.run(_context(repo))) == 1

    def test_non_markdown_artifact_does_not_count_as_a_supporting_doc(self, repo: Path) -> None:
        """A staged image/log artifact is not a NAMED supporting document —
        only ``.md`` files count."""
        (repo / "CLAUDE/Plan/00200-widget/PLAN.md").write_text(_SMALL_PLAN)
        (repo / "CLAUDE/Plan/00200-widget/diagram.png").write_bytes(b"\x89PNG\r\n")
        _git(repo, "add", "-A")
        assert len(CHECK.run(_context(repo))) == 1

    def test_supporting_doc_in_a_different_plan_folder_does_not_count(self, repo: Path) -> None:
        """A new supporting doc staged for an UNRELATED plan in the same
        commit must not satisfy this plan's relocation check."""
        _shrink(repo, with_journal_entry=False)
        other_folder = repo / "CLAUDE/Plan/00201-other"
        other_folder.mkdir(parents=True)
        (other_folder / "RESEARCH.md").write_text("unrelated findings\n")
        _git(repo, "add", "-A")
        findings = [f for f in CHECK.run(_context(repo)) if "00200" in (f.path or "")]
        assert len(findings) == 1


class TestNoFalsePositives:
    def test_growing_plan_is_silent(self, repo: Path) -> None:
        (repo / "CLAUDE/Plan/00200-widget/PLAN.md").write_text(_plan(20_000))
        _git(repo, "add", "-A")
        assert CHECK.run(_context(repo)) == []

    def test_small_shrink_is_silent(self, repo: Path) -> None:
        """Ordinary editing churn must not trip the guard."""
        (repo / "CLAUDE/Plan/00200-widget/PLAN.md").write_text(_BIG_PLAN[:-200])
        _git(repo, "add", "-A")
        assert CHECK.run(_context(repo)) == []

    def test_new_plan_has_no_head_side_and_is_silent(self, repo: Path) -> None:
        folder = repo / "CLAUDE/Plan/00201-new"
        folder.mkdir()
        (folder / "PLAN.md").write_text(_SMALL_PLAN)
        _git(repo, "add", "-A")
        findings = [f for f in CHECK.run(_context(repo)) if "00201" in (f.path or "")]
        assert findings == []

    def test_no_gitfacts_returns_empty(self) -> None:
        context = CheckContext(project_root=Path("/repo"), plan_dir_rel=_PLAN_DIR_REL)
        assert CHECK.run(context) == []

    def test_grandfathered_plan_is_silent(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        root.mkdir()
        _git(root, "init")
        _git(root, "config", "user.email", "t@e.com")
        _git(root, "config", "user.name", "T")
        folder = root / "CLAUDE" / "Plan" / "00042-old"
        folder.mkdir(parents=True)
        (folder / "PLAN.md").write_text(_BIG_PLAN)
        _git(root, "add", "-A")
        _git(root, "commit", "-m", "initial")
        (folder / "PLAN.md").write_text(_SMALL_PLAN)
        _git(root, "add", "-A")
        assert CHECK.run(_context(root)) == []

    def test_journal_file_shrink_is_not_this_checks_business(self, repo: Path) -> None:
        """Journal shrinkage is journal-append-only's job, not this one."""
        day = repo / "CLAUDE/Plan/00200-widget/JOURNAL/00200-Journal-26-07-14.md"
        day.write_text("# Journal\n")
        _git(repo, "add", "-A")
        assert CHECK.run(_context(repo)) == []
