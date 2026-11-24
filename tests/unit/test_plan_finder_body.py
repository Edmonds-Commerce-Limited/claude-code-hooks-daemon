"""``find-plan --body`` searches PLAN.md bodies, archives included (Plan 00636 Task 3.3).

Without ``--body`` the finder matches number, folder name and title only, so a
term that appears only inside a plan's prose finds nothing.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from claude_code_hooks_daemon.daemon.cli import cmd_find_plan
from claude_code_hooks_daemon.plan_finder import find_plans

_TERM = "zebrafish-quarantine"


def _make_plan(plan_dir: Path, folder: str, title: str, body: str) -> None:
    path = plan_dir / folder
    path.mkdir(parents=True)
    (path / "PLAN.md").write_text(
        f"# Plan: {title}\n\n**Status**: Complete\n\n## Overview\n\n{body}\n", encoding="utf-8"
    )


@pytest.fixture
def plan_tree(tmp_path: Path) -> Path:
    plan_dir = tmp_path / "CLAUDE" / "Plan"
    # The term sits far past the header window, in an archived plan.
    _make_plan(
        plan_dir / "Completed",
        "00130-archived-thing",
        "archived thing",
        ("filler line\n" * 400) + f"the {_TERM} rule applies",
    )
    _make_plan(plan_dir, "00200-active-thing", "active thing", "nothing relevant")
    return tmp_path


class TestBodySearch:
    def test_body_only_term_finds_nothing_by_default(self, plan_tree: Path) -> None:
        assert find_plans(plan_tree, "CLAUDE/Plan", _TERM) == []

    def test_body_flag_finds_archived_plan_by_body_text(self, plan_tree: Path) -> None:
        matches = find_plans(plan_tree, "CLAUDE/Plan", _TERM, search_body=True)

        assert [m.number for m in matches] == [130]
        assert "Completed" in matches[0].path

    def test_body_flag_is_case_insensitive(self, plan_tree: Path) -> None:
        matches = find_plans(plan_tree, "CLAUDE/Plan", _TERM.upper(), search_body=True)

        assert [m.number for m in matches] == [130]

    def test_body_flag_still_matches_names(self, plan_tree: Path) -> None:
        matches = find_plans(plan_tree, "CLAUDE/Plan", "active", search_body=True)

        assert [m.number for m in matches] == [200]

    def test_body_flag_with_empty_query_lists_everything(self, plan_tree: Path) -> None:
        matches = find_plans(plan_tree, "CLAUDE/Plan", "", search_body=True)

        assert [m.number for m in matches] == [130, 200]

    def test_unreadable_body_does_not_abort_the_search(self, plan_tree: Path) -> None:
        # A PLAN.md that is a directory cannot be read; the rest must still be found.
        broken = plan_tree / "CLAUDE" / "Plan" / "00300-broken-thing"
        (broken / "PLAN.md").mkdir(parents=True)

        matches = find_plans(plan_tree, "CLAUDE/Plan", _TERM, search_body=True)

        assert [m.number for m in matches] == [130]


class TestCli:
    def _args(self, root: Path, query: list[str], body: bool) -> argparse.Namespace:
        return argparse.Namespace(query=query, project_root=str(root), body=body)

    def test_cli_body_flag_finds_body_only_term(
        self, plan_tree: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = cmd_find_plan(self._args(plan_tree, [_TERM], body=True))

        assert code == 0
        assert "00130" in capsys.readouterr().out

    def test_cli_without_body_flag_finds_nothing(
        self, plan_tree: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = cmd_find_plan(self._args(plan_tree, [_TERM], body=False))

        assert code == 1
        assert "No plan matches" in capsys.readouterr().out
