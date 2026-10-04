"""Recursive searches and the capped tree scan, seen through the guard.

Ledger 00483 N130 (a tree past the old 5000-file cap was answered as clean) and
00474 N348 (a scan that cannot finish is denied under its own rule, not allowed
and not reported as a finding).
"""

import subprocess  # nosec B404 - fixed git argv in a tmp repository
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use import secret_file_guard as guard_module
from claude_code_hooks_daemon.handlers.pre_tool_use.secret_file_guard import (
    SecretFileGuardHandler,
)
from claude_code_hooks_daemon.utils import protected_tree_scan

# Assembled so this file never spells a protected name itself.
_PROTECTED_NAME = "key." + "sec" + "ret"


@pytest.fixture()
def project(tmp_path: Path) -> Iterator[Path]:
    root = tmp_path / "project"
    root.mkdir()
    with patch.object(guard_module, "resolve_project_root", return_value=str(root)):
        yield root


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True
    )  # nosec B603 B607


def _populate(directory: Path, count: int) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for index in range(count):
        (directory / f"f{index:05d}.txt").write_text("x\n")


def _bash(root: Path, command: str) -> dict[str, Any]:
    return {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(root)}


def _grep(root: Path, path: Path) -> dict[str, Any]:
    return {
        "tool_name": "Grep",
        "tool_input": {"path": str(path), "pattern": "x"},
        "cwd": str(root),
    }


def _reason(hook_input: dict[str, Any]) -> str | None:
    """The deny reason, or None when the call is allowed."""
    handler = SecretFileGuardHandler()
    if not handler.matches(hook_input):
        return None
    result = handler.handle(hook_input)
    assert result.decision == Decision.DENY
    return result.reason or ""


class TestAScanPastTheCapIsDeniedAsIncomplete:
    @pytest.fixture()
    def past_cap(self, project: Path) -> Iterator[Path]:
        _populate(project, 30)
        with patch.object(protected_tree_scan, "TREE_SCAN_MAX_ENTRIES", 10):
            yield project

    def test_the_grep_tool_over_the_tree(self, past_cap: Path) -> None:
        reason = _reason(_grep(past_cap, past_cap))
        assert reason is not None
        assert RuleID.SECRET_SCAN_INCOMPLETE in reason
        assert RuleID.SECRET_READ not in reason
        assert "10 entries" in reason
        assert "no protected path was found" in reason

    @pytest.mark.parametrize("command", ["grep -r x .", "grep -rn x ./", "ack x"])
    def test_a_bash_recursive_search_over_the_tree(self, past_cap: Path, command: str) -> None:
        reason = _reason(_bash(past_cap, command))
        assert reason is not None
        assert RuleID.SECRET_SCAN_INCOMPLETE in reason
        assert RuleID.SECRET_BASH_MENTION not in reason

    def test_the_reason_offers_the_tool_specific_way_out(self, past_cap: Path) -> None:
        reason = _reason(_bash(past_cap, "grep -r x ."))
        assert reason is not None
        assert "rg" in reason
        assert "--exclude-dir" in reason

    def test_a_scan_that_timed_out_says_so(self, project: Path) -> None:
        with patch.object(protected_tree_scan, "find_protected_in_tree", side_effect=TimeoutError):
            reason = _reason(_grep(project, project))
        assert reason is not None
        assert RuleID.SECRET_SCAN_INCOMPLETE in reason
        assert "deadline" in reason


class TestATreeAboveTheOldCapIsStillJudged:
    def test_the_grep_tool_finds_a_protected_file_after_five_thousand_clean_ones(
        self, project: Path
    ) -> None:
        _populate(project / "a", 5500)
        (project / "zdeep" / "inner").mkdir(parents=True)
        (project / "zdeep" / "inner" / _PROTECTED_NAME).write_text("x\n")
        reason = _reason(_grep(project, project))
        assert reason is not None
        assert RuleID.SECRET_READ in reason

    def test_the_grep_tool_allows_a_big_clean_tree(self, project: Path) -> None:
        _populate(project / "a", 5500)
        assert _reason(_grep(project, project)) is None

    def test_git_grep_finds_a_tracked_protected_file_listed_after_position_six_thousand(
        self, project: Path
    ) -> None:
        _git(project, "init", "-q")
        _populate(project / "a", 6000)
        (project / "z").mkdir()
        (project / "z" / _PROTECTED_NAME).write_text("x\n")
        _git(project, "add", "-A")
        reason = _reason(_bash(project, "git grep needle"))
        assert reason is not None
        assert RuleID.SECRET_READ in reason

    def test_a_bare_glob_of_twenty_thousand_paths_with_no_hit_is_allowed(
        self, project: Path
    ) -> None:
        _populate(project / "big", 20_000)
        assert _reason(_bash(project, "cat big/*")) is None

    def test_a_bare_glob_still_finds_a_protected_file_among_many(self, project: Path) -> None:
        _populate(project / "big", 3000)
        (project / "big" / _PROTECTED_NAME).write_text("x\n")
        reason = _reason(_bash(project, "cat big/*"))
        assert reason is not None
        assert RuleID.SECRET_BASH_MENTION in reason


class TestRgReadsGitsNonIgnoredSet:
    def test_a_big_ignored_directory_and_a_clean_tracked_set_is_allowed(
        self, project: Path
    ) -> None:
        _git(project, "init", "-q")
        (project / ".gitignore").write_text("bulk/\n")
        (project / "plain.txt").write_text("x\n")
        _populate(project / "bulk", 300)
        (project / "bulk" / _PROTECTED_NAME).write_text("x\n")
        _git(project, "add", ".gitignore", "plain.txt")
        with patch.object(protected_tree_scan, "TREE_SCAN_MAX_ENTRIES", 50):
            assert _reason(_bash(project, "rg x .")) is None
            reason = _reason(_bash(project, "grep -r x ."))
        assert reason is not None
        assert RuleID.SECRET_SCAN_INCOMPLETE in reason

    def test_rg_without_a_root_over_the_same_tree_is_allowed(self, project: Path) -> None:
        _git(project, "init", "-q")
        (project / ".gitignore").write_text("bulk/\n")
        (project / "plain.txt").write_text("x\n")
        _populate(project / "bulk", 300)
        _git(project, "add", ".gitignore", "plain.txt")
        with patch.object(protected_tree_scan, "TREE_SCAN_MAX_ENTRIES", 50):
            assert _reason(_bash(project, "rg x")) is None


class TestTheDeadlineReachesTheScan:
    def test_the_grep_tool_and_a_bash_search_both_pass_one(self, project: Path) -> None:
        seen: list[float | None] = []

        def _scan(*_args: object, **kwargs: Any) -> None:
            seen.append(kwargs.get("deadline"))

        with patch.object(protected_tree_scan, "find_protected_in_tree", _scan):
            _reason(_grep(project, project))
            _reason(_bash(project, "grep -r x ."))
        assert len(seen) == 2
        assert all(deadline is not None for deadline in seen)
