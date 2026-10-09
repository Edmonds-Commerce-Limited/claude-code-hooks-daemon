"""Tests for the branch_count_advisor SessionStart handler (Plan 00475 Task 4.1).

A work branch is a local ``worktree-*`` branch (CLAUDE/Worktree.md, "Small
Batches"). Tests use real temporary git repositories.
"""

import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.constants import HandlerIDMeta, HandlerTag, HookInputField
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.session_start.branch_count_advisor import (
    DEFAULT_BEHIND_MAIN_THRESHOLD,
    DEFAULT_MAX_OPEN_BRANCHES,
    MAX_BEHIND_CHECKS,
    BranchCountAdvisorHandler,
)

_ROOT = (
    "claude_code_hooks_daemon.handlers.session_start.branch_count_advisor."
    "ProjectContext.project_root"
)


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@example.com",
            "-c",
            "commit.gpgsign=false",
            *args,
        ],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


def _commit(repo: Path, name: str) -> None:
    (repo / name).write_text(name)
    _git(repo, "add", name)
    _git(repo, "commit", "-m", name)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-b", "main")
    _commit(tmp_path, "base")
    return tmp_path


def _session_input(transcript_path: str | None = None) -> dict[str, Any]:
    hook_input: dict[str, Any] = {HookInputField.HOOK_EVENT_NAME: "SessionStart"}
    if transcript_path is not None:
        hook_input[HookInputField.TRANSCRIPT_PATH] = transcript_path
    return hook_input


def _make(max_open: int | None = None, behind: int | None = None) -> BranchCountAdvisorHandler:
    handler = BranchCountAdvisorHandler()
    if max_open is not None:
        handler._max_open_branches = max_open
    if behind is not None:
        handler._behind_main_threshold = behind
    return handler


def _run(repo: Path, handler: BranchCountAdvisorHandler) -> list[str]:
    with patch(_ROOT, return_value=repo):
        result = handler.handle(_session_input())
    assert result.decision == Decision.ALLOW
    return list(result.context)


class TestInit:
    def test_handler_id(self) -> None:
        handler_id = BranchCountAdvisorHandler().handler_id
        assert isinstance(handler_id, HandlerIDMeta)
        assert handler_id.config_key == "branch_count_advisor"

    def test_non_terminal_advisory(self) -> None:
        handler = BranchCountAdvisorHandler()
        assert handler.terminal is False
        assert HandlerTag.ADVISORY in handler.tags

    def test_defaults(self) -> None:
        handler = BranchCountAdvisorHandler()
        assert handler._max_open_branches == DEFAULT_MAX_OPEN_BRANCHES == 3
        assert handler._behind_main_threshold == DEFAULT_BEHIND_MAIN_THRESHOLD


class TestMatches:
    def test_new_session_matches(self) -> None:
        assert BranchCountAdvisorHandler().matches(_session_input()) is True

    def test_resume_session_does_not_match(self, tmp_path: Path) -> None:
        transcript = tmp_path / "t.jsonl"
        transcript.write_text("x" * 200)
        assert BranchCountAdvisorHandler().matches(_session_input(str(transcript))) is False


class TestWithinLimits:
    def test_no_work_branches_is_silent(self, repo: Path) -> None:
        assert _run(repo, _make()) == []

    def test_exactly_the_limit_is_silent(self, repo: Path) -> None:
        for n in range(3):
            _git(repo, "branch", f"worktree-b{n}")
        assert _run(repo, _make()) == []

    def test_non_work_branches_are_not_counted(self, repo: Path) -> None:
        for n in range(6):
            _git(repo, "branch", f"feature-{n}")
        assert _run(repo, _make()) == []


class TestOverLimit:
    def test_four_work_branches_fire_and_name_each(self, repo: Path) -> None:
        for n in range(4):
            _git(repo, "branch", f"worktree-b{n}")
        text = "\n".join(_run(repo, _make()))
        assert "4 open work branches" in text
        assert "limit 3" in text
        for n in range(4):
            assert f"worktree-b{n}" in text

    def test_agent_dispatch_branches_count(self, repo: Path) -> None:
        """Ledger 00474 N379: `isolation: worktree` names its branch `agent-<hex>-<hex>`."""
        agents = [f"agent-a{n:016x}-{n:08x}" for n in range(2)]
        for n in range(2):
            _git(repo, "branch", f"worktree-b{n}")
        for name in agents:
            _git(repo, "branch", name)
        text = "\n".join(_run(repo, _make()))
        assert "4 open work branches" in text
        for name in agents:
            assert name in text

    def test_custom_limit(self, repo: Path) -> None:
        for n in range(2):
            _git(repo, "branch", f"worktree-b{n}")
        text = "\n".join(_run(repo, _make(max_open=1)))
        assert "limit 1" in text

    def test_branch_without_worktree_still_counts(self, repo: Path) -> None:
        # No linked worktree exists for any of these; they count regardless.
        for n in range(4):
            _git(repo, "branch", f"worktree-gone{n}")
        assert _run(repo, _make()) != []


class TestBehindMain:
    def _far_behind(self, repo: Path, commits: int) -> None:
        _git(repo, "branch", "worktree-old")
        for n in range(commits):
            _commit(repo, f"m{n}")

    def test_branch_beyond_threshold_is_named_even_within_count(self, repo: Path) -> None:
        self._far_behind(repo, 5)
        text = "\n".join(_run(repo, _make(behind=3)))
        assert "worktree-old" in text
        assert "5 commits behind" in text

    def test_count_and_staleness_are_both_reported(self, repo: Path) -> None:
        self._far_behind(repo, 5)
        for n in range(3):
            _git(repo, "branch", f"worktree-b{n}")
        text = "\n".join(_run(repo, _make(behind=3)))
        assert "4 open work branches" in text
        assert "5 commits behind" in text

    def test_behind_checks_are_capped_and_the_rest_reported(self, repo: Path) -> None:
        total = MAX_BEHIND_CHECKS + 2
        for n in range(total):
            _git(repo, "branch", f"worktree-b{n:02d}")
        _commit(repo, "m1")
        handler = _make(max_open=total, behind=0)
        with patch.object(handler, "_behind", wraps=handler._behind) as spy:
            text = "\n".join(_run(repo, handler))
        assert spy.call_count == MAX_BEHIND_CHECKS
        assert "2 more work branch(es) not checked" in text
        assert f"worktree-b{MAX_BEHIND_CHECKS:02d}" not in text

    def test_branch_at_threshold_is_silent(self, repo: Path) -> None:
        self._far_behind(repo, 3)
        assert _run(repo, _make(behind=3)) == []

    def test_default_threshold_applies(self, repo: Path) -> None:
        self._far_behind(repo, 2)
        assert _run(repo, _make()) == []


class TestFailOpen:
    def test_not_a_repo_is_silent(self, tmp_path: Path) -> None:
        assert _run(tmp_path, _make()) == []

    def test_no_main_branch_still_counts_but_skips_behind(self, tmp_path: Path) -> None:
        _git(tmp_path, "init", "-b", "trunk")
        _commit(tmp_path, "base")
        for n in range(4):
            _git(tmp_path, "branch", f"worktree-b{n}")
        text = "\n".join(_run(tmp_path, _make()))
        assert "4 open work branches" in text

    def test_unresolvable_default_branch_skips_behind_check(self, repo: Path) -> None:
        _git(repo, "branch", "worktree-old")
        _commit(repo, "m1")
        with patch(
            "claude_code_hooks_daemon.handlers.session_start.branch_count_advisor."
            "git_sync.default_branch",
            return_value="missing",
        ):
            assert _run(repo, _make(behind=0)) == []

    def test_project_context_uninitialised_uses_cwd(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(repo)
        with patch(_ROOT, side_effect=RuntimeError("no context")):
            result = BranchCountAdvisorHandler().handle(_session_input())
        assert result.context == []


class TestGuidance:
    def test_claude_md_names_config_keys(self) -> None:
        text = BranchCountAdvisorHandler().get_claude_md()
        assert text is not None
        assert "max_open_branches" in text
        assert "behind_main_threshold" in text

    def test_acceptance_tests(self) -> None:
        tests = BranchCountAdvisorHandler().get_acceptance_tests()
        assert len(tests) >= 1
