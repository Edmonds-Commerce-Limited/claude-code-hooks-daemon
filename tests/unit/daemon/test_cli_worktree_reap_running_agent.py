"""``worktree-reap`` leaves a worktree or branch a live agent owns alone.

Same flaw class as ``branch-sweep --clean``: a ``running`` work-queue record or a
git lock marks the worktree (and its branch) as a live agent's.
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.core import agent_ownership
from claude_code_hooks_daemon.core.agent_ownership import RunningHolds
from claude_code_hooks_daemon.daemon.cli import cmd_worktree_reap

_LISTING = """worktree /repo
HEAD aaa
branch refs/heads/main

worktree /repo/.claude/worktrees/agent-live
HEAD aaa
branch refs/heads/agent-live

worktree /repo/.claude/worktrees/agent-locked
HEAD aaa
branch refs/heads/agent-locked
locked
"""


def _fake(cwd: Path, *args: str, **_: object) -> subprocess.CompletedProcess[str]:
    if args[:2] == ("worktree", "list"):
        return subprocess.CompletedProcess([], 0, _LISTING, "")
    if args[0] == "branch" and "--merged" in args:
        return subprocess.CompletedProcess(
            [], 0, "refs/heads/main\nrefs/heads/agent-live\nrefs/heads/agent-q\n", ""
        )
    if args[0] == "branch" and "--list" in args:
        return subprocess.CompletedProcess(
            [], 0, "refs/heads/main\nrefs/heads/agent-live\nrefs/heads/agent-q\n", ""
        )
    if args[0] == "config":
        return subprocess.CompletedProcess([], 1, "", "")
    return subprocess.CompletedProcess([], 0, "", "")


def _run(**overrides: object) -> int:
    defaults: dict[str, object] = {
        "project_root": "/repo",
        "base_branch": "main",
        "reap": False,
        "only": None,
        "reap_branches": False,
    }
    defaults.update(overrides)
    return cmd_worktree_reap(
        argparse.Namespace(**defaults),
        run_fn=_fake,
        age_fn=lambda _p: 999_999.0,
        process_cwds_fn=lambda: {},
    )


@pytest.fixture
def running(monkeypatch: pytest.MonkeyPatch) -> None:
    holds = RunningHolds(branches=frozenset({"agent-live", "agent-q"}), worktrees=frozenset())
    monkeypatch.setattr(agent_ownership, "running_holds", lambda _untracked: holds)


def test_a_running_queue_worktree_is_kept(
    running: None, capsys: pytest.CaptureFixture[str]
) -> None:
    _run(reap=True)
    out = capsys.readouterr().out
    line = next(line for line in out.splitlines() if "agent-live" in line)
    assert line.startswith("KEEP")
    assert "running" in line


def test_a_locked_worktree_is_kept(capsys: pytest.CaptureFixture[str]) -> None:
    _run(reap=True)
    out = capsys.readouterr().out
    line = next(line for line in out.splitlines() if "agent-locked" in line)
    assert line.startswith("KEEP")
    assert "locked" in line


def test_a_running_queue_orphan_branch_is_not_pruned(
    running: None, capsys: pytest.CaptureFixture[str]
) -> None:
    _run(reap_branches=True)
    out = capsys.readouterr().out
    line = next(line for line in out.splitlines() if "agent-q" in line)
    assert not line.startswith("PRUNED")
    assert "running" in line
