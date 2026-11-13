"""The owned-branch hint on the SessionStart path speaks once per session (Plan 00599).

Defect class: a hint printed from a site that bypasses the once-per-session
state in ``core/ownership``. The static guard below catches the class; the
behaviour tests drive the real handler.
"""

from __future__ import annotations

import os
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.config.models import (
    BranchesConfig,
    ClaudeMdConfig,
    ClaudeMdOwnership,
)
from claude_code_hooks_daemon.constants import HookInputField
from claude_code_hooks_daemon.core import ownership
from claude_code_hooks_daemon.core.ownership import HINT_TEXT, OwnershipHint
from claude_code_hooks_daemon.handlers.session_start import branch_sweep as handler_module
from claude_code_hooks_daemon.handlers.session_start.branch_sweep import BranchSweepHandler

_ROOT = "claude_code_hooks_daemon.handlers.session_start.branch_sweep.ProjectContext.project_root"
_HINT = HINT_TEXT[OwnershipHint.BRANCH_OWNED]
_WIP_CAP = 1


@pytest.fixture(autouse=True)
def _reset() -> Iterator[None]:
    ownership.reset()
    yield
    ownership.reset()


def _git(cwd: Path, *args: str) -> None:
    stamp = f"@{int(time.time())} +0000"
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
        env={**os.environ, "GIT_AUTHOR_DATE": stamp, "GIT_COMMITTER_DATE": stamp},
    )


def _commit(repo: Path, name: str) -> None:
    (repo / name).write_text(name)
    _git(repo, "add", name)
    _git(repo, "commit", "-q", "-m", name)


@pytest.fixture
def busy_repo(tmp_path: Path) -> Path:
    """A merged branch (summary entry) and an open branch at the cap (pool blocker)."""
    _git(tmp_path, "init", "-q", "-b", "main")
    _commit(tmp_path, "base")
    _git(tmp_path, "branch", "done", "main")
    _git(tmp_path, "checkout", "-q", "-b", "open")
    _commit(tmp_path, "open")
    _git(tmp_path, "checkout", "-q", "main")
    return tmp_path


def _handler() -> BranchSweepHandler:
    handler = BranchSweepHandler()
    handler._branches = BranchesConfig.model_validate({"wip": {"cap": _WIP_CAP}})
    return handler


def _hook(session: str) -> dict[str, Any]:
    return {
        HookInputField.HOOK_EVENT_NAME: "SessionStart",
        HookInputField.SESSION_ID: session,
        "source": "startup",
    }


def _text(handler: BranchSweepHandler, repo: Path, session: str) -> str:
    with patch(_ROOT, return_value=repo):
        return "\n".join(handler.handle(_hook(session)).context)


class TestOwnedBranchHintOnce:
    def test_summary_and_pool_report_together_print_it_once(self, busy_repo: Path) -> None:
        ownership.configure(ClaudeMdConfig())
        text = _text(_handler(), busy_repo, "s1")
        assert "BRANCH POOLS" in text
        assert "merged branch is not deleted" in text
        assert text.count(_HINT) == 1

    def test_a_second_session_start_in_the_same_session_prints_none(
        self, busy_repo: Path
    ) -> None:
        ownership.configure(ClaudeMdConfig())
        handler = _handler()
        assert _text(handler, busy_repo, "s1").count(_HINT) == 1
        assert _text(handler, busy_repo, "s1").count(_HINT) == 0

    def test_a_new_session_hears_it_again(self, busy_repo: Path) -> None:
        ownership.configure(ClaudeMdConfig())
        handler = _handler()
        _text(handler, busy_repo, "s1")
        assert _text(handler, busy_repo, "s2").count(_HINT) == 1

    @pytest.mark.parametrize("mode", [ClaudeMdOwnership.OFF, ClaudeMdOwnership.CUSTOM])
    def test_silent_when_not_own(self, busy_repo: Path, mode: ClaudeMdOwnership) -> None:
        text_arg = "Mine except vendor/." if mode == ClaudeMdOwnership.CUSTOM else None
        ownership.configure(ClaudeMdConfig(ownership=mode, ownership_text=text_arg))
        assert _HINT not in _text(_handler(), busy_repo, "s1")


def test_no_handler_reads_hint_text_around_the_once_per_session_gate() -> None:
    """The class detector: handlers get hint text only from ``ownership.hint_once``."""
    handlers_dir = Path(handler_module.__file__).parents[1]
    offenders = [
        str(path.relative_to(handlers_dir))
        for path in handlers_dir.rglob("*.py")
        if "import HINT_TEXT" in path.read_text(encoding="utf-8")
        or " HINT_TEXT," in path.read_text(encoding="utf-8")
    ]
    assert offenders == []
