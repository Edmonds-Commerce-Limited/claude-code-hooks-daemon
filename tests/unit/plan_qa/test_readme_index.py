"""Tests for plan_qa.readme_index — ReadmeIndex parser (Plan 00144, Task 1.3).

Grounded in TWO real formats: this repo's ``CLAUDE/Plan/README.md`` (category
subsections, linkless bold rows, bullet-list statistics) and the installer's
starter template (``install/plan_workflow.py``). Must survive mdformat-gfm.
"""

from pathlib import Path

from claude_code_hooks_daemon.plan_qa.readme_index import (
    ReadmeIndex,
    ReadmeRow,
    ReadmeSection,
)
from claude_code_hooks_daemon.utils.markdown_format import format_markdown_text

REALISTIC_README = """\
# Plans Index

Intro prose with a [stray link](../PlanWorkflow.md) that is not a row.

## Active Plans

### Category One

- [00144: Plan QA System](00144-plan-qa-system/PLAN.md) - In Progress

  - Detail bullet that must NOT parse as a row, even though it mentions
    [00042: something](00042-x/PLAN.md) in passing

- [00100 (v3): Venv SSOT Consolidation](00100-venv-ssot-consolidation/PLAN.md) - In Progress (Residue Scope)

### Category Two

- [00108: Nuanced AskUserQuestion Blocker](00108-question-blocker-nuanced/PLAN.md) - Not Started

## Completed Plans

- [00143: Loud Alert](Completed/00143-loud-alert/PLAN.md) - Complete

- **00008** - Complete (row without a link — sin B7)

## Blocked / On Hold Plans

- **00032, 00034, 00035** - On hold pending upstream fix

## Cancelled Plans

- [00044: Acceptance Testing Skill](Completed/00044-acceptance-testing-skill/PLAN.md) - Cancelled

## Plan Statistics

- **Total Plans Created**: 144
- **Completed**: 116 (1 with reduced scope, 4 already-shipped)
- **Active**: 6 (various)
- **On Hold**: 3 (blocked upstream)
- **Cancelled/Abandoned**: 6 (details)
- **Last reconciled by**: Plan 00144 creation

## Quick Links

- [PlanWorkflow.md](../PlanWorkflow.md) - Planning workflow
"""

TEMPLATE_README = """\
# Plans Index

## Active Plans

_No active plans yet._

## Completed Plans

_No completed plans yet._

## Statistics

- **Total**: 0
- **Active**: 0
- **Completed**: 0
"""


class TestReadmeRows:
    def test_parses_linked_rows_with_section(self) -> None:
        index = ReadmeIndex.parse(REALISTIC_README)
        row = index.rows_for(144)[0]
        assert row.section == ReadmeSection.ACTIVE
        assert row.title == "Plan QA System"
        assert row.link == "00144-plan-qa-system/PLAN.md"
        assert row.status_text == "In Progress"

    def test_subsections_inherit_parent_section(self) -> None:
        index = ReadmeIndex.parse(REALISTIC_README)
        assert index.rows_for(108)[0].section == ReadmeSection.ACTIVE

    def test_title_decoration_after_number_is_kept(self) -> None:
        index = ReadmeIndex.parse(REALISTIC_README)
        row = index.rows_for(100)[0]
        assert row.title == "(v3): Venv SSOT Consolidation"
        assert row.status_text == "In Progress (Residue Scope)"

    def test_completed_and_cancelled_sections(self) -> None:
        index = ReadmeIndex.parse(REALISTIC_README)
        assert index.rows_for(143)[0].section == ReadmeSection.COMPLETED
        assert index.rows_for(44)[0].section == ReadmeSection.CANCELLED

    def test_linkless_bold_row_detected(self) -> None:
        index = ReadmeIndex.parse(REALISTIC_README)
        row = index.rows_for(8)[0]
        assert row.link is None
        assert row.section == ReadmeSection.COMPLETED
        assert row.numbers == (8,)

    def test_multi_number_blocked_row(self) -> None:
        index = ReadmeIndex.parse(REALISTIC_README)
        row = index.rows_for(34)[0]
        assert row.numbers == (32, 34, 35)
        assert row.section == ReadmeSection.BLOCKED

    def test_indented_detail_bullets_are_not_rows(self) -> None:
        index = ReadmeIndex.parse(REALISTIC_README)
        assert index.rows_for(42) == ()

    def test_intro_and_quick_links_are_not_rows(self) -> None:
        index = ReadmeIndex.parse(REALISTIC_README)
        numbers = index.numbers()
        assert numbers == frozenset({144, 100, 108, 143, 8, 32, 34, 35, 44})

    def test_rows_for_unknown_number_is_empty(self) -> None:
        index = ReadmeIndex.parse(REALISTIC_README)
        assert index.rows_for(999) == ()

    def test_row_is_frozen_dataclass(self) -> None:
        row = ReadmeIndex.parse(REALISTIC_README).rows[0]
        assert isinstance(row, ReadmeRow)


class TestReadmeStats:
    def test_parses_leading_integers(self) -> None:
        index = ReadmeIndex.parse(REALISTIC_README)
        assert index.stats["Total Plans Created"] == 144
        assert index.stats["Completed"] == 116
        assert index.stats["Active"] == 6
        assert index.stats["On Hold"] == 3
        assert index.stats["Cancelled/Abandoned"] == 6

    def test_non_numeric_stat_lines_skipped(self) -> None:
        index = ReadmeIndex.parse(REALISTIC_README)
        assert "Last reconciled by" not in index.stats

    def test_template_readme_parses(self) -> None:
        index = ReadmeIndex.parse(TEMPLATE_README)
        assert index.rows == ()
        assert index.stats == {"Total": 0, "Active": 0, "Completed": 0}


class TestMdformatRoundTrip:
    def test_realistic_readme_round_trip(self) -> None:
        raw = ReadmeIndex.parse(REALISTIC_README)
        formatted = ReadmeIndex.parse(format_markdown_text(REALISTIC_README))
        assert formatted.numbers() == raw.numbers()
        assert formatted.stats == raw.stats
        assert formatted.rows_for(144)[0].status_text == "In Progress"

    def test_real_repo_readme_parses(self) -> None:
        # Live dogfooding fixture: this repo's actual plan index.
        readme = Path(__file__).parents[3] / "CLAUDE/Plan/README.md"
        index = ReadmeIndex.parse(readme.read_text())
        assert 144 in index.numbers()
        assert index.stats["Total Plans Created"] >= 144
        sections = {row.section for row in index.rows}
        assert ReadmeSection.ACTIVE in sections
        assert ReadmeSection.COMPLETED in sections
