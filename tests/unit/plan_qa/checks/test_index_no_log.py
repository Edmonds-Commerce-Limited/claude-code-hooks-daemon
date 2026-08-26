"""Tests for ``index-no-log`` (advisory).

The plan index states current truth only — it is a pointer table, not a
changelog. Twice it re-grew a stacked reconciliation LEDGER of log-grammar
lines ("- **Before that**: ..." entries recording successive historical
recounts). The byte ceiling (``plan-doc-size``'s sibling exemption for the
index does not even apply the size tiers to it) eventually catches the bulk,
but only as a symptom — this check catches the SHAPE: a bullet written in
log/ledger grammar rather than as current truth.

This mirrors ``index-row-length`` in structure: same three surfaces (EDIT,
COMMIT, SWEEP), same ``PlanFileKind.PLAN_INDEX`` scoping, but a fixed
ADVISE severity everywhere (Plan 00218's worsening/tiering machinery does not
apply — a ledger line is a shape problem, not a size problem, so there is no
grow/shrink axis to tier on).
"""

from pathlib import Path

from claude_code_hooks_daemon.plan_qa.checks.index_no_log import CHECK_ID, CHECKS
from claude_code_hooks_daemon.plan_qa.readme_index import ReadmeIndex
from claude_code_hooks_daemon.plan_qa.types import CheckContext, Level, Stage

_ROOT = Path("/repo")
_PLAN_DIR_REL = "CLAUDE/Plan"
_INDEX_REL = f"{_PLAN_DIR_REL}/README.md"

_EDIT_CHECK = next(spec for spec in CHECKS if spec.stage is Stage.EDIT)
_COMMIT_CHECK = next(spec for spec in CHECKS if spec.stage is Stage.COMMIT)
_SWEEP_CHECK = next(spec for spec in CHECKS if spec.stage is Stage.SWEEP)

_CLEAN_INDEX = (
    "# Plans Index\n\n## Plan Statistics\n\n"
    "- **Total Plans Created**: 272\n\n"
    "- **Last reconciled at**: the Plan 00272 creation. The index carries NO "
    "reconciliation history — it states current truth only; every earlier "
    "recount is in git, and per-plan narrative belongs in that plan's "
    "`JOURNAL/`.\n"
)

_LEDGER_LINE = (
    "- **Before that**: 38 root, 218 `Completed/`, 6 `Cancelled/`, "
    "261 distinct numbers against a counter of 271.\n"
)

_PRIOR_TO_LINE = "- **Prior to that**: 37 root, 217 `Completed/`.\n"
_PREVIOUSLY_LINE = "- **Previously**: 36 root, 216 `Completed/`.\n"
_DATED_LINE = "- **2026-08-12**: 35 root, 215 `Completed/`.\n"


def _edit_context(
    content: str,
    *,
    rel_path: str = _INDEX_REL,
    content_before: str | None = None,
) -> CheckContext:
    return CheckContext(
        project_root=_ROOT,
        plan_dir_rel=_PLAN_DIR_REL,
        file_path=_ROOT / rel_path,
        file_content=content,
        file_content_before=content_before,
        file_exists_before=content_before is not None,
    )


def _tree_context(readme_text: str | None) -> CheckContext:
    return CheckContext(
        project_root=_ROOT,
        plan_dir_rel=_PLAN_DIR_REL,
        readme=None if readme_text is None else ReadmeIndex.parse(readme_text),
    )


class TestRegistration:
    def test_registered_on_all_three_surfaces(self):
        assert {spec.stage for spec in CHECKS} == {Stage.EDIT, Stage.COMMIT, Stage.SWEEP}

    def test_every_spec_shares_one_check_id(self):
        assert {spec.check_id for spec in CHECKS} == {CHECK_ID}

    def test_declared_level_is_advise_everywhere(self):
        assert {spec.level for spec in CHECKS} == {Level.ADVISE}


class TestScope:
    def test_plan_document_is_not_this_check(self):
        content = _CLEAN_INDEX + _LEDGER_LINE
        context = _edit_context(content, rel_path=f"{_PLAN_DIR_REL}/00218-thing/PLAN.md")
        assert _EDIT_CHECK.run(context) == []

    def test_readme_inside_a_plan_folder_is_a_supporting_doc(self):
        content = _CLEAN_INDEX + _LEDGER_LINE
        context = _edit_context(content, rel_path=f"{_PLAN_DIR_REL}/00218-thing/README.md")
        assert _EDIT_CHECK.run(context) == []

    def test_file_outside_the_plan_directory_is_ignored(self):
        content = _CLEAN_INDEX + _LEDGER_LINE
        context = _edit_context(content, rel_path="docs/README.md")
        assert _EDIT_CHECK.run(context) == []

    def test_context_without_a_file_is_ignored(self):
        assert _EDIT_CHECK.run(CheckContext(project_root=_ROOT, plan_dir_rel=_PLAN_DIR_REL)) == []


class TestCleanIndex:
    def test_clean_index_is_silent_on_edit(self):
        assert _EDIT_CHECK.run(_edit_context(_CLEAN_INDEX)) == []

    def test_clean_index_is_silent_on_commit(self):
        assert _COMMIT_CHECK.run(_tree_context(_CLEAN_INDEX)) == []

    def test_clean_index_is_silent_on_sweep(self):
        assert _SWEEP_CHECK.run(_tree_context(_CLEAN_INDEX)) == []

    def test_last_reconciled_at_line_is_not_flagged(self):
        """The one current-truth summary line must never be mistaken for a ledger."""
        content = "# Plans Index\n\n" + _CLEAN_INDEX.split("## Plan Statistics\n\n")[1]
        assert _EDIT_CHECK.run(_edit_context(content)) == []

    def test_absent_readme_is_silent(self):
        assert _COMMIT_CHECK.run(_tree_context(None)) == []


class TestLedgerLinesFlagged:
    def test_before_that_line_is_flagged(self):
        content = _CLEAN_INDEX + _LEDGER_LINE
        findings = _EDIT_CHECK.run(_edit_context(content))
        assert [finding.check_id for finding in findings] == [CHECK_ID]
        assert [finding.level for finding in findings] == [Level.ADVISE]

    def test_prior_to_that_line_is_flagged(self):
        content = _CLEAN_INDEX + _PRIOR_TO_LINE
        findings = _EDIT_CHECK.run(_edit_context(content))
        assert [finding.check_id for finding in findings] == [CHECK_ID]

    def test_previously_line_is_flagged(self):
        content = _CLEAN_INDEX + _PREVIOUSLY_LINE
        findings = _EDIT_CHECK.run(_edit_context(content))
        assert [finding.check_id for finding in findings] == [CHECK_ID]

    def test_dated_bold_line_is_flagged(self):
        content = _CLEAN_INDEX + _DATED_LINE
        findings = _EDIT_CHECK.run(_edit_context(content))
        assert [finding.check_id for finding in findings] == [CHECK_ID]

    def test_multiple_ledger_lines_are_all_named(self):
        content = _CLEAN_INDEX + _LEDGER_LINE + _PRIOR_TO_LINE + _PREVIOUSLY_LINE
        findings = _EDIT_CHECK.run(_edit_context(content))
        assert len(findings) == 1
        assert "3" in findings[0].message
        assert "Before that" in findings[0].message
        assert "Prior to that" in findings[0].message
        assert "Previously" in findings[0].message

    def test_message_agrees_in_number_singular(self):
        content = _CLEAN_INDEX + _LEDGER_LINE
        findings = _EDIT_CHECK.run(_edit_context(content))
        assert "1 line" in findings[0].message

    def test_message_agrees_in_number_plural(self):
        content = _CLEAN_INDEX + _LEDGER_LINE + _PRIOR_TO_LINE
        findings = _EDIT_CHECK.run(_edit_context(content))
        assert "2 lines" in findings[0].message


class TestEditNeverBlocks:
    """Advisory only — an edit that keeps or adds ledger lines never blocks."""

    def test_adding_a_ledger_line_only_advises(self):
        before = _CLEAN_INDEX
        after = _CLEAN_INDEX + _LEDGER_LINE
        findings = _EDIT_CHECK.run(_edit_context(after, content_before=before))
        assert [finding.level for finding in findings] == [Level.ADVISE]


class TestTreeStages:
    def test_commit_flags_a_ledger_line(self):
        content = _CLEAN_INDEX + _LEDGER_LINE
        findings = _COMMIT_CHECK.run(_tree_context(content))
        assert [finding.check_id for finding in findings] == [CHECK_ID]
        assert [finding.level for finding in findings] == [Level.ADVISE]

    def test_sweep_flags_a_ledger_line(self):
        content = _CLEAN_INDEX + _LEDGER_LINE
        findings = _SWEEP_CHECK.run(_tree_context(content))
        assert [finding.check_id for finding in findings] == [CHECK_ID]

    def test_commit_and_sweep_agree(self):
        context = _tree_context(_CLEAN_INDEX + _LEDGER_LINE)
        assert _COMMIT_CHECK.run(context) == _SWEEP_CHECK.run(context)

    def test_finding_points_at_the_index(self):
        findings = _COMMIT_CHECK.run(_tree_context(_CLEAN_INDEX + _LEDGER_LINE))
        assert findings[0].path == _INDEX_REL
