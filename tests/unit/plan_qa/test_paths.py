"""Tests for the plan-file classifier (Plan 00190 Phase 2).

One SSoT classifier decides what kind of file an edit targets. Every scope
predicate in the plan QA catalogue derives from it, so no rule can leak from
plan documents onto journal files or vice versa.
"""

from pathlib import Path

import pytest

from claude_code_hooks_daemon.plan_qa.paths import (
    PlanFileKind,
    classify,
    is_journal_file,
)
from claude_code_hooks_daemon.plan_qa.types import CheckContext

PROJECT_ROOT = Path("/repo")
PLAN_DIR_REL = "CLAUDE/Plan"


def _context(**overrides):
    return CheckContext(project_root=PROJECT_ROOT, plan_dir_rel=PLAN_DIR_REL, **overrides)


def _classify(rel_path: str, **overrides):
    return classify(PROJECT_ROOT / rel_path, _context(**overrides))


class TestPlanDocuments:
    def test_plan_md_in_plan_folder(self):
        result = _classify("CLAUDE/Plan/00190-thing/PLAN.md")
        assert result.kind is PlanFileKind.PLAN_DOCUMENT
        assert result.plan_number == 190
        assert result.plan_folder == "00190-thing"
        assert result.in_archive is False

    def test_plan_md_in_archive(self):
        result = _classify("CLAUDE/Plan/Completed/00042-thing/PLAN.md")
        assert result.kind is PlanFileKind.PLAN_DOCUMENT
        assert result.plan_number == 42
        assert result.in_archive is True

    def test_plan_md_in_cancelled_archive(self):
        result = _classify("CLAUDE/Plan/Cancelled/00007-thing/PLAN.md")
        assert result.in_archive is True

    def test_unnumbered_folder_has_no_number(self):
        result = _classify("CLAUDE/Plan/scratch/PLAN.md")
        assert result.kind is PlanFileKind.PLAN_DOCUMENT
        assert result.plan_number is None


class TestJournalPrecedence:
    """The journal test MUST run before the PLAN.md filename test.

    Otherwise a file at ``JOURNAL/PLAN.md`` satisfies both predicates and
    receives plan rules AND journal rules — the dual-classification defect
    this classifier exists to make structurally impossible.
    """

    def test_plan_md_inside_journal_is_not_a_plan_document(self):
        result = _classify("CLAUDE/Plan/00190-thing/JOURNAL/PLAN.md")
        assert result.kind is not PlanFileKind.PLAN_DOCUMENT
        assert result.is_journal is True

    def test_dayfile_is_recognised(self):
        result = _classify("CLAUDE/Plan/00190-thing/JOURNAL/00190-Journal-26-07-31.md")
        assert result.kind is PlanFileKind.JOURNAL_DAYFILE
        assert result.plan_number == 190
        assert result.is_journal is True

    def test_non_dayfile_markdown_in_journal_is_still_journal(self):
        result = _classify("CLAUDE/Plan/00190-thing/JOURNAL/notes.md")
        assert result.kind is PlanFileKind.JOURNAL_OTHER
        assert result.is_journal is True

    def test_nested_below_journal_is_still_journal(self):
        result = _classify("CLAUDE/Plan/00190-thing/JOURNAL/sub/PLAN.md")
        assert result.is_journal is True
        assert result.kind is not PlanFileKind.PLAN_DOCUMENT

    def test_journal_dir_name_is_configurable(self):
        result = _classify(
            "CLAUDE/Plan/00190-thing/LOG/00190-Journal-26-07-31.md",
            journal_dir_name="LOG",
        )
        assert result.kind is PlanFileKind.JOURNAL_DAYFILE

    @pytest.mark.parametrize(
        "journal_overrides",
        [
            {"journal_enabled": False},
            {"journal_mode": "off"},
            {"journal_enabled": False, "journal_mode": "off"},
        ],
    )
    def test_classification_is_config_independent(self, journal_overrides):
        """Decision 5: turning journalling off must NOT re-apply plan rules.

        A config-dependent predicate would silently reclassify every journal
        file as plan material the moment journalling was disabled.
        """
        result = _classify(
            "CLAUDE/Plan/00190-thing/JOURNAL/00190-Journal-26-07-31.md",
            **journal_overrides,
        )
        assert result.kind is PlanFileKind.JOURNAL_DAYFILE
        assert result.is_journal is True


class TestOtherPlanFiles:
    def test_plan_index_readme(self):
        result = _classify("CLAUDE/Plan/README.md")
        assert result.kind is PlanFileKind.PLAN_INDEX

    def test_supporting_doc_in_plan_folder(self):
        result = _classify("CLAUDE/Plan/00190-thing/RESEARCH.md")
        assert result.kind is PlanFileKind.SUPPORTING_DOC
        assert result.plan_number == 190

    def test_readme_inside_a_plan_folder_is_a_supporting_doc(self):
        result = _classify("CLAUDE/Plan/00190-thing/README.md")
        assert result.kind is PlanFileKind.SUPPORTING_DOC


class TestOutside:
    @pytest.mark.parametrize(
        "rel_path",
        [
            "src/module.py",
            "CLAUDE/PlanWorkflow.md",  # sibling of the plan dir, not inside it
            "docs/PLAN.md",
            "CLAUDE/Plan/00190-thing/assets/diagram.png",  # not markdown
        ],
    )
    def test_outside_the_plan_scope(self, rel_path):
        assert _classify(rel_path).kind is PlanFileKind.OUTSIDE

    def test_outside_files_are_not_journal(self):
        assert _classify("src/module.py").is_journal is False


class TestExhaustiveness:
    """Every kind must be reachable, and every file gets exactly one kind."""

    SAMPLES = {
        PlanFileKind.PLAN_DOCUMENT: "CLAUDE/Plan/00190-thing/PLAN.md",
        PlanFileKind.PLAN_INDEX: "CLAUDE/Plan/README.md",
        PlanFileKind.JOURNAL_DAYFILE: "CLAUDE/Plan/00190-t/JOURNAL/00190-Journal-26-07-31.md",
        PlanFileKind.JOURNAL_OTHER: "CLAUDE/Plan/00190-thing/JOURNAL/notes.md",
        PlanFileKind.SUPPORTING_DOC: "CLAUDE/Plan/00190-thing/RESEARCH.md",
        PlanFileKind.OUTSIDE: "src/module.py",
    }

    def test_every_kind_is_reachable(self):
        assert set(self.SAMPLES) == set(PlanFileKind)

    @pytest.mark.parametrize("kind,rel_path", sorted(SAMPLES.items(), key=lambda kv: kv[0].value))
    def test_sample_classifies_to_its_kind(self, kind, rel_path):
        assert _classify(rel_path).kind is kind

    def test_journal_kinds_and_plan_kinds_are_disjoint(self):
        for kind, rel_path in self.SAMPLES.items():
            result = _classify(rel_path)
            plan_ruled = kind in (PlanFileKind.PLAN_DOCUMENT, PlanFileKind.SUPPORTING_DOC)
            assert not (result.is_journal and plan_ruled)


class TestIsJournalFile:
    """Path-only predicate for handlers that have no CheckContext.

    Handlers previously exempted journals by day-file NAME alone, so a file
    inside ``JOURNAL/`` with a non-conforming name (a typo'd date, or
    ``notes.md``) still received plan-document rules — a plan rule leaking
    onto journal territory.
    """

    @pytest.mark.parametrize(
        "rel_path",
        [
            "CLAUDE/Plan/00190-thing/JOURNAL/00190-Journal-26-07-31.md",
            "CLAUDE/Plan/00190-thing/JOURNAL/notes.md",  # location, not name
            "CLAUDE/Plan/00190-thing/JOURNAL/00190-Journal-BADDATE.md",
            "CLAUDE/Plan/00190-thing/JOURNAL/sub/deep.md",
            "CLAUDE/Plan/Completed/00042-t/JOURNAL/notes.md",
            # A correctly-named day-file counts even if misplaced.
            "CLAUDE/Plan/00190-thing/00190-Journal-26-07-31.md",
        ],
    )
    def test_journal_files(self, rel_path):
        assert is_journal_file(PROJECT_ROOT / rel_path) is True

    @pytest.mark.parametrize(
        "rel_path",
        [
            "CLAUDE/Plan/00190-thing/PLAN.md",
            "CLAUDE/Plan/00190-thing/RESEARCH.md",
            "CLAUDE/Plan/README.md",
            "src/module.py",
            # "JOURNAL" as the FILE name is not a journal directory.
            "CLAUDE/Plan/00190-thing/JOURNAL.md",
        ],
    )
    def test_non_journal_files(self, rel_path):
        assert is_journal_file(PROJECT_ROOT / rel_path) is False

    def test_custom_journal_dir_name(self):
        path = PROJECT_ROOT / "CLAUDE/Plan/00190-thing/LOG/notes.md"
        assert is_journal_file(path, journal_dir_name="LOG") is True
        assert is_journal_file(path) is False

    def test_agrees_with_classify_on_every_sample(self):
        """The two consumers of the journal rule must never disagree."""
        for rel_path in TestExhaustiveness.SAMPLES.values():
            classified = _classify(rel_path)
            if classified.kind is PlanFileKind.OUTSIDE:
                continue
            assert classified.is_journal == is_journal_file(PROJECT_ROOT / rel_path)
