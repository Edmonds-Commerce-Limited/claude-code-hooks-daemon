"""The every-prompt branch pool pressure advisory (Plan 00619 Task 1.3).

Context only: it never holds a prompt. Very strong pressure shows on every prompt;
warn and strong show once per session.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tests.support.ladder_repo import add_open_branches, git, init_repo

from claude_code_hooks_daemon.config.models import BranchesConfig, BranchWipConfig
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.branch_ladder import LadderThrottle, PressureCache
from claude_code_hooks_daemon.handlers.user_prompt_submit.branch_pool_pressure_prompt import (
    BranchPoolPressurePromptHandler,
)

CONFIG = BranchesConfig(wip=BranchWipConfig(cap=10, creation_grace=2, count_remote=False))
PROMPT: dict[str, Any] = {"session_id": "s1", "prompt": "hello"}


def _repo(tmp_path: Path, open_count: int) -> Path:
    root = init_repo(tmp_path)
    add_open_branches(root, open_count)
    return root


def _handler(tmp_path: Path, open_count: int) -> BranchPoolPressurePromptHandler:
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    git(root, "commit", "-q", "--allow-empty", "-m", "root")
    tree = git(root, "rev-parse", "main^{tree}")
    for index in range(open_count):
        sha = git(root, "commit-tree", tree, "-p", "main", "-m", f"w{index}")
        git(root, "update-ref", f"refs/heads/work-{index:02d}", sha)
    handler = BranchPoolPressurePromptHandler()
    handler._branches = CONFIG
    handler._project_root_override = root
    handler._throttle = LadderThrottle()
    handler._cache = PressureCache(ttl=0.0)
    return handler


class TestPromptHandler:
    def test_silent_below_the_warn_level(self, tmp_path: Path) -> None:
        assert _handler(tmp_path, 7).matches(PROMPT) is False

    def test_very_strong_shows_on_every_prompt(self, tmp_path: Path) -> None:
        handler = _handler(tmp_path, 11)
        for _ in range(4):
            assert handler.matches(PROMPT) is True
            result = handler.handle(PROMPT)
            assert result.decision == Decision.ALLOW
            assert "11 of 12" in "\n".join(result.context or [])

    def test_warn_shows_once_per_session(self, tmp_path: Path) -> None:
        handler = _handler(tmp_path, 8)
        assert handler.matches(PROMPT) is True
        assert handler.matches(PROMPT) is False
        assert handler.matches({**PROMPT, "session_id": "s2"}) is True

    def test_never_terminal(self) -> None:
        assert BranchPoolPressurePromptHandler().terminal is False

    def test_silent_outside_a_repository(self, tmp_path: Path) -> None:
        handler = BranchPoolPressurePromptHandler()
        handler._branches = CONFIG
        handler._project_root_override = tmp_path / "nowhere"
        assert handler.matches(PROMPT) is False
