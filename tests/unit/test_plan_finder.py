"""Finding a plan BY NAME, across the whole tree (ledger 00413 N7).

`plan_number_helper` denies a folder scan of the plan directory, and it is
right to: such a scan misses everything archived under `Completed/`, so it can
answer "not found" about a plan that exists. The gap it leaves is that there is
then no sanctioned way to answer "where is the Jobs plan" at all — the deny
message's whole remedy is the next plan NUMBER, which answers a different
question.

So this finder exists to make the guard's refusal affordable. Its one
non-negotiable property is the one the guard complains about: it MUST see
archived plans.

It reads the FILESYSTEM rather than README.md's index. The index is the more
convenient substrate and is normally complete, but a plan missing a row would
be invisible to a reader who had been told the search covers everything — the
exact failure the guard exists to prevent, reintroduced one layer up.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from claude_code_hooks_daemon.plan_finder import find_plans

_PLAN_BODY = """# Plan {number}: {title}

**Status**: {status}
**Created**: 2026-09-15

## Overview

Some prose.
"""


def _make_plan(plan_dir: Path, folder: str, number: str, title: str, status: str) -> Path:
    folder_path = plan_dir / folder
    folder_path.mkdir(parents=True)
    (folder_path / "PLAN.md").write_text(
        _PLAN_BODY.format(number=number, title=title, status=status), encoding="utf-8"
    )
    return folder_path


@pytest.fixture
def plan_tree(tmp_path: Path) -> Path:
    """An active plan, an archived plan, and a decoy."""
    plan_dir = tmp_path / "CLAUDE" / "Plan"
    _make_plan(plan_dir, "00412-jobs-recurring-work", "00412", "jobs recurring work", "Not Started")
    _make_plan(
        plan_dir / "Completed",
        "00130-plan-scaffolding-script",
        "00130",
        "plan scaffolding script",
        "Complete",
    )
    _make_plan(plan_dir, "00413-niggles-ledger", "00413", "niggles ledger", "In Progress")
    return tmp_path


class TestTheArchiveIsSearched:
    """The property the guard's own deny message is about."""

    def test_an_archived_plan_is_found(self, plan_tree: Path) -> None:
        """The whole point. A folder scan would miss this one."""
        matches = find_plans(plan_tree, "CLAUDE/Plan", "scaffolding")

        assert [m.number for m in matches] == [130]

    def test_an_archived_plan_reports_its_real_path(self, plan_tree: Path) -> None:
        """A path under Completed/ must be returned as such, not normalised away."""
        matches = find_plans(plan_tree, "CLAUDE/Plan", "scaffolding")

        assert "Completed" in matches[0].path

    def test_active_and_archived_are_returned_together(self, plan_tree: Path) -> None:
        """A query matching both must not silently prefer one tree."""
        matches = find_plans(plan_tree, "CLAUDE/Plan", "plan")

        assert {m.number for m in matches} == {130, 412, 413}


class TestMatching:
    def test_matches_the_folder_slug(self, plan_tree: Path) -> None:
        matches = find_plans(plan_tree, "CLAUDE/Plan", "jobs")

        assert [m.number for m in matches] == [412]

    def test_matching_is_case_insensitive(self, plan_tree: Path) -> None:
        matches = find_plans(plan_tree, "CLAUDE/Plan", "JOBS")

        assert [m.number for m in matches] == [412]

    def test_a_bare_number_finds_that_plan(self, plan_tree: Path) -> None:
        """`find-plan 412` is the shape a reader reaches for first."""
        matches = find_plans(plan_tree, "CLAUDE/Plan", "412")

        assert [m.number for m in matches] == [412]

    def test_a_zero_padded_number_finds_that_plan(self, plan_tree: Path) -> None:
        matches = find_plans(plan_tree, "CLAUDE/Plan", "00412")

        assert [m.number for m in matches] == [412]

    def test_no_match_returns_empty_rather_than_raising(self, plan_tree: Path) -> None:
        assert find_plans(plan_tree, "CLAUDE/Plan", "nothing-matches-this") == []

    def test_results_are_ordered_by_number(self, plan_tree: Path) -> None:
        """A stable order makes the output scannable and diffable."""
        matches = find_plans(plan_tree, "CLAUDE/Plan", "plan")

        assert [m.number for m in matches] == sorted(m.number for m in matches)


class TestWhatEachMatchCarries:
    def test_the_status_is_read_from_the_plan(self, plan_tree: Path) -> None:
        """Status is why a reader is looking: is this live or finished?"""
        matches = find_plans(plan_tree, "CLAUDE/Plan", "niggles")

        assert matches[0].status == "In Progress"

    def test_the_title_is_read_from_the_heading(self, plan_tree: Path) -> None:
        matches = find_plans(plan_tree, "CLAUDE/Plan", "niggles")

        assert "niggles ledger" in (matches[0].title or "")

    def test_a_plan_with_no_status_line_still_resolves(self, tmp_path: Path) -> None:
        """A malformed plan must be FOUND, not hidden.

        Hiding it would make the finder lie in exactly the way the folder scan
        does — reporting absence for something present.
        """
        plan_dir = tmp_path / "CLAUDE" / "Plan"
        folder = plan_dir / "00099-broken"
        folder.mkdir(parents=True)
        (folder / "PLAN.md").write_text("no heading, no status\n", encoding="utf-8")

        matches = find_plans(tmp_path, "CLAUDE/Plan", "broken")

        assert [m.number for m in matches] == [99]
        assert matches[0].status is None


class TestDegenerateTrees:
    def test_a_missing_plan_directory_returns_empty(self, tmp_path: Path) -> None:
        """A project with no plans yet must not raise."""
        assert find_plans(tmp_path, "CLAUDE/Plan", "anything") == []

    def test_a_folder_without_a_plan_document_is_skipped(self, tmp_path: Path) -> None:
        """`Completed/` itself, `JOURNAL/`, and stray folders are not plans."""
        plan_dir = tmp_path / "CLAUDE" / "Plan"
        (plan_dir / "00500-no-plan-md").mkdir(parents=True)

        assert find_plans(tmp_path, "CLAUDE/Plan", "no-plan") == []

    def test_an_unnumbered_folder_is_skipped(self, tmp_path: Path) -> None:
        """Only NNNNN-name folders are plans; templates and tooling are not."""
        plan_dir = tmp_path / "CLAUDE" / "Plan"
        folder = plan_dir / "upgrade-template"
        folder.mkdir(parents=True)
        (folder / "PLAN.md").write_text("# Template\n", encoding="utf-8")

        assert find_plans(tmp_path, "CLAUDE/Plan", "template") == []

    def test_an_empty_query_returns_every_plan(self, plan_tree: Path) -> None:
        """Listing the whole tree is a legitimate use, and is what `ls` was for."""
        matches = find_plans(plan_tree, "CLAUDE/Plan", "")

        assert len(matches) == 3
