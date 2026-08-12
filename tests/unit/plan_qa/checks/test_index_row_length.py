"""Tests for ``index-row-length`` (Plan 00218).

The plan index is the entry point to every plan, and a row a reader must
scroll horizontally to finish is not an index row — it is a paragraph that
duplicates the linked ``PLAN.md`` and then goes stale.

Two things these tests pin down, because both are how the rule could quietly
become wrong:

- **The limit has ONE definition.** Everything here reads
  ``DEFAULT_INDEX_ROW_MAX_CHARS``; a literal 500 in this file would recreate
  the drift the constant exists to remove.
- **Only a WORSENING edit blocks**, exactly as ``plan-doc-size`` tiers.
  An index that somehow acquired a long row must stay editable — including by
  the edit that fixes it.
"""

from pathlib import Path

from claude_code_hooks_daemon.plan_qa.checks.index_row_length import CHECK_ID, CHECKS
from claude_code_hooks_daemon.plan_qa.readme_index import ReadmeIndex
from claude_code_hooks_daemon.plan_qa.types import (
    DEFAULT_INDEX_ROW_MAX_CHARS,
    CheckContext,
    Level,
    Stage,
)

_ROOT = Path("/repo")
_PLAN_DIR_REL = "CLAUDE/Plan"
_INDEX_REL = f"{_PLAN_DIR_REL}/README.md"

_LIMIT = DEFAULT_INDEX_ROW_MAX_CHARS

_EDIT_CHECK = next(spec for spec in CHECKS if spec.stage is Stage.EDIT)
_COMMIT_CHECK = next(spec for spec in CHECKS if spec.stage is Stage.COMMIT)
_SWEEP_CHECK = next(spec for spec in CHECKS if spec.stage is Stage.SWEEP)


def _row(length: int) -> str:
    """An index-shaped row of exactly ``length`` characters."""
    prefix = "- [00218: thing](00218-thing/PLAN.md) - In Progress ("
    suffix = ")"
    padding = length - len(prefix) - len(suffix)
    assert padding >= 0, "requested row shorter than the fixed row scaffolding"
    return prefix + "x" * padding + suffix


def _index(*rows: str) -> str:
    return "# Plans Index\n\n## Active Plans\n\n" + "\n\n".join(rows) + "\n"


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
        """The fast loop is only closed if every surface can see the rule."""
        assert {spec.stage for spec in CHECKS} == {Stage.EDIT, Stage.COMMIT, Stage.SWEEP}

    def test_every_spec_shares_one_check_id(self):
        assert {spec.check_id for spec in CHECKS} == {CHECK_ID}

    def test_declared_level_matches_the_batch_guard_strictness(self):
        """The integration test FAILS the suite; a declared ADVISE would be weaker.

        The surface MODE may still downgrade this at runtime (``commit_gate_mode:
        warn``), which is a deliberate project-wide rollout posture — but the
        declaration must not be the thing that weakens it.
        """
        assert {spec.level for spec in CHECKS} == {Level.BLOCK}


class TestScope:
    def test_plan_document_is_not_this_check(self):
        """``plan-doc-size`` owns PLAN.md; this check owns the index only."""
        content = _index(_row(_LIMIT + 1))
        context = _edit_context(content, rel_path=f"{_PLAN_DIR_REL}/00218-thing/PLAN.md")
        assert _EDIT_CHECK.run(context) == []

    def test_readme_inside_a_plan_folder_is_a_supporting_doc(self):
        content = _index(_row(_LIMIT + 1))
        context = _edit_context(content, rel_path=f"{_PLAN_DIR_REL}/00218-thing/README.md")
        assert _EDIT_CHECK.run(context) == []

    def test_journal_dayfile_is_never_bounded(self):
        content = _index(_row(_LIMIT + 1))
        context = _edit_context(
            content,
            rel_path=f"{_PLAN_DIR_REL}/00218-thing/JOURNAL/00218-Journal-26-08-12.md",
        )
        assert _EDIT_CHECK.run(context) == []

    def test_file_outside_the_plan_directory_is_ignored(self):
        content = _index(_row(_LIMIT + 1))
        context = _edit_context(content, rel_path="docs/README.md")
        assert _EDIT_CHECK.run(context) == []

    def test_context_without_a_file_is_ignored(self):
        assert _EDIT_CHECK.run(CheckContext(project_root=_ROOT, plan_dir_rel=_PLAN_DIR_REL)) == []


class TestEditBoundary:
    def test_row_exactly_at_the_limit_is_allowed(self):
        """Rule shape is ``>`` not ``>=``, matching the batch guard exactly."""
        content = _index(_row(_LIMIT))
        assert _EDIT_CHECK.run(_edit_context(content)) == []

    def test_row_one_over_the_limit_is_flagged(self):
        content = _index(_row(_LIMIT + 1))
        findings = _EDIT_CHECK.run(_edit_context(content))
        assert [finding.check_id for finding in findings] == [CHECK_ID]

    def test_clean_index_is_silent(self):
        content = _index(_row(120), _row(300), _row(_LIMIT))
        assert _EDIT_CHECK.run(_edit_context(content)) == []


class TestEditWorsening:
    def test_creating_an_index_with_a_long_row_blocks(self):
        content = _index(_row(_LIMIT + 50))
        findings = _EDIT_CHECK.run(_edit_context(content))
        assert [finding.level for finding in findings] == [Level.BLOCK]

    def test_adding_a_long_row_to_a_clean_index_blocks(self):
        before = _index(_row(200))
        after = _index(_row(200), _row(_LIMIT + 1))
        findings = _EDIT_CHECK.run(_edit_context(after, content_before=before))
        assert [finding.level for finding in findings] == [Level.BLOCK]

    def test_adding_a_second_long_row_blocks(self):
        before = _index(_row(_LIMIT + 10))
        after = _index(_row(_LIMIT + 10), _row(_LIMIT + 5))
        findings = _EDIT_CHECK.run(_edit_context(after, content_before=before))
        assert [finding.level for finding in findings] == [Level.BLOCK]

    def test_lengthening_an_existing_long_row_blocks(self):
        before = _index(_row(_LIMIT + 10))
        after = _index(_row(_LIMIT + 40))
        findings = _EDIT_CHECK.run(_edit_context(after, content_before=before))
        assert [finding.level for finding in findings] == [Level.BLOCK]

    def test_block_message_names_the_line_and_its_length(self):
        content = _index(_row(_LIMIT + 7))
        findings = _EDIT_CHECK.run(_edit_context(content))
        assert str(_LIMIT + 7) in findings[0].message
        assert str(_LIMIT) in findings[0].message

    def test_message_agrees_in_number(self):
        """A block message that misuses grammar reads as a bug in the guard."""
        one = _EDIT_CHECK.run(_edit_context(_index(_row(_LIMIT + 1))))
        assert "1 line in the plan index exceeds" in one[0].message
        two = _EDIT_CHECK.run(_edit_context(_index(_row(_LIMIT + 1), _row(_LIMIT + 2))))
        assert "2 lines in the plan index exceed " in two[0].message


class TestEditNeverTrapsTheFile:
    """An oversized index must always remain editable, including to fix it."""

    def test_unrelated_edit_leaving_offenders_unchanged_only_advises(self):
        before = _index(_row(_LIMIT + 10), _row(100))
        after = _index(_row(_LIMIT + 10), _row(140))
        findings = _EDIT_CHECK.run(_edit_context(after, content_before=before))
        assert [finding.level for finding in findings] == [Level.ADVISE]

    def test_shrinking_an_offender_that_is_still_over_only_advises(self):
        before = _index(_row(_LIMIT + 90))
        after = _index(_row(_LIMIT + 10))
        findings = _EDIT_CHECK.run(_edit_context(after, content_before=before))
        assert [finding.level for finding in findings] == [Level.ADVISE]

    def test_removing_one_of_two_offenders_only_advises(self):
        before = _index(_row(_LIMIT + 10), _row(_LIMIT + 20))
        after = _index(_row(_LIMIT + 20))
        findings = _EDIT_CHECK.run(_edit_context(after, content_before=before))
        assert [finding.level for finding in findings] == [Level.ADVISE]

    def test_fixing_the_last_offender_is_silent(self):
        before = _index(_row(_LIMIT + 10))
        after = _index(_row(_LIMIT))
        assert _EDIT_CHECK.run(_edit_context(after, content_before=before)) == []


class TestTreeStages:
    """COMMIT and SWEEP see the whole file, so they have no before/after tier."""

    def test_commit_flags_a_long_line(self):
        findings = _COMMIT_CHECK.run(_tree_context(_index(_row(_LIMIT + 1))))
        assert [finding.check_id for finding in findings] == [CHECK_ID]

    def test_sweep_flags_a_long_line(self):
        findings = _SWEEP_CHECK.run(_tree_context(_index(_row(_LIMIT + 1))))
        assert [finding.check_id for finding in findings] == [CHECK_ID]

    def test_commit_and_sweep_agree(self):
        context = _tree_context(_index(_row(_LIMIT + 1)))
        assert _COMMIT_CHECK.run(context) == _SWEEP_CHECK.run(context)

    def test_clean_index_is_silent(self):
        assert _COMMIT_CHECK.run(_tree_context(_index(_row(_LIMIT)))) == []

    def test_absent_readme_is_silent(self):
        assert _COMMIT_CHECK.run(_tree_context(None)) == []

    def test_all_offenders_are_reported_not_just_the_first(self):
        content = _index(_row(_LIMIT + 1), _row(200), _row(_LIMIT + 2))
        findings = _COMMIT_CHECK.run(_tree_context(content))
        assert str(_LIMIT + 1) in findings[0].message
        assert str(_LIMIT + 2) in findings[0].message

    def test_finding_points_at_the_index(self):
        findings = _COMMIT_CHECK.run(_tree_context(_index(_row(_LIMIT + 1))))
        assert findings[0].path == _INDEX_REL


class TestDefinitionMatchesTheBatchGuard:
    """The fast and batch guards must agree on what a violation IS.

    The batch guard measures EVERY line, not only parsed index rows. A long
    prose paragraph in an index is the same navigability failure as a long row,
    and a narrower fast rule would silently pass what the suite then fails on.
    """

    def test_long_prose_line_is_flagged_even_though_it_parses_as_no_row(self):
        prose = "x" * (_LIMIT + 1)
        assert ReadmeIndex.parse(prose).rows == ()
        findings = _COMMIT_CHECK.run(_tree_context(f"# Plans Index\n\n{prose}\n"))
        assert [finding.check_id for finding in findings] == [CHECK_ID]

    def test_long_statistics_bullet_is_flagged(self):
        stats = "- **Total Plans Created**: 218 " + "x" * _LIMIT
        text = f"# Plans Index\n\n## Plan Statistics\n\n{stats}\n"
        findings = _COMMIT_CHECK.run(_tree_context(text))
        assert [finding.check_id for finding in findings] == [CHECK_ID]
