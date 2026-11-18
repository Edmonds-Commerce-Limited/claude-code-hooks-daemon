"""The every-prompt branch pool pressure advisory (Plan 00619 Task 1.3).

Context only: it never holds a prompt. Very strong pressure shows on every prompt;
warn and strong show once per session.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.config.models import BranchesConfig, BranchWipConfig
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.branch_ladder import LadderThrottle, PressureCache
from claude_code_hooks_daemon.handlers.user_prompt_submit.branch_pool_pressure_prompt import (
    BranchPoolPressurePromptHandler,
)

CONFIG = BranchesConfig(wip=BranchWipConfig(cap=10, creation_grace=2, count_remote=False))
PROMPT: dict[str, Any] = {"session_id": "s1", "prompt": "hello"}


def _git(repo: Path, *args: str) -> str:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
    }
    return subprocess.run(
        ["git", "-C", str(repo), "-c", "commit.gpgsign=false", *args],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    ).stdout.strip()


def _handler(tmp_path: Path, open_count: int) -> BranchPoolPressurePromptHandler:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "commit", "-q", "--allow-empty", "-m", "root")
    tree = _git(root, "rev-parse", "main^{tree}")
    for index in range(open_count):
        sha = _git(root, "commit-tree", tree, "-p", "main", "-m", f"w{index}")
        _git(root, "update-ref", f"refs/heads/work-{index:02d}", sha)
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
