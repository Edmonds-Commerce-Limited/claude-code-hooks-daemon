"""The every-tool-call branch pool pressure advisory (Plan 00619 Task 1.3).

Context only: it never denies and never changes what any guard decides. Very
strong pressure shows on every tool call; warn and strong show once per session.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tests.support.ladder_repo import add_open_branches, git, init_repo

from claude_code_hooks_daemon.config.models import BranchesConfig, BranchWipConfig
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.branch_ladder import LadderThrottle, PressureCache
from claude_code_hooks_daemon.handlers.pre_tool_use.branch_pool_pressure_advisor import (
    BranchPoolPressureAdvisorHandler,
)

CONFIG = BranchesConfig(wip=BranchWipConfig(cap=10, creation_grace=2, count_remote=False))
TOOL: dict[str, Any] = {"session_id": "s1", "tool_name": "Read", "tool_input": {"file_path": "/x"}}


def _repo(tmp_path: Path, open_count: int) -> Path:
    root = init_repo(tmp_path)
    add_open_branches(root, open_count)
    return root


def _handler(root: Path) -> BranchPoolPressureAdvisorHandler:
    handler = BranchPoolPressureAdvisorHandler()
    handler._branches = CONFIG
    handler._project_root_override = root
    handler._throttle = LadderThrottle()
    handler._cache = PressureCache(ttl=0.0)
    return handler


class TestToolHandler:
    def test_very_strong_shows_on_every_tool_call(self, tmp_path: Path) -> None:
        handler = _handler(_repo(tmp_path, 11))
        for _ in range(4):
            assert handler.matches(TOOL) is True
            result = handler.handle(TOOL)
            assert result.decision == Decision.ALLOW
            assert "11 of 12" in "\n".join(result.context or [])

    def test_silent_below_the_warn_level(self, tmp_path: Path) -> None:
        assert _handler(_repo(tmp_path, 3)).matches(TOOL) is False

    def test_warn_shows_once_per_session(self, tmp_path: Path) -> None:
        handler = _handler(_repo(tmp_path, 9))
        assert handler.matches(TOOL) is True
        assert handler.matches(TOOL) is False

    def test_never_terminal_and_never_denies(self, tmp_path: Path) -> None:
        handler = _handler(_repo(tmp_path, 12))
        assert handler.terminal is False
        assert handler.matches(TOOL) is True
        assert handler.handle(TOOL).decision == Decision.ALLOW

    def test_a_pool_that_drops_below_silences_it(self, tmp_path: Path) -> None:
        root = _repo(tmp_path, 11)
        handler = _handler(root)
        assert handler.matches(TOOL) is True
        for index in range(7, 11):
            git(root, "update-ref", "-d", f"refs/heads/work-{index:02d}")
        assert handler.matches(TOOL) is False

    def test_silent_outside_a_repository(self, tmp_path: Path) -> None:
        handler = BranchPoolPressureAdvisorHandler()
        handler._branches = CONFIG
        handler._project_root_override = tmp_path / "nowhere"
        assert handler.matches(TOOL) is False
