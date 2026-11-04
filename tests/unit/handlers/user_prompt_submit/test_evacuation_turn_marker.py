"""Tests for the evacuation turn marker (Plan 00558 Task 4.5)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, Priority
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.evacuation import evacuations
from claude_code_hooks_daemon.core.evacuation_turns import (
    record_evacuations,
    recorded_evacuations,
)
from claude_code_hooks_daemon.handlers.user_prompt_submit.evacuation_turn_marker import (
    EvacuationTurnMarkerHandler,
)


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=T", "-c", "user.email=t@example.invalid", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


def _prompt(**extra: Any) -> dict[str, Any]:
    return {"session_id": "s1", "prompt": "go", **extra}


def test_identity() -> None:
    marker = EvacuationTurnMarkerHandler()
    assert marker.handler_id == HandlerID.EVACUATION_TURN_MARKER
    assert marker.priority == Priority.EVACUATION_TURN_MARKER
    assert marker.terminal is False


def test_prompt_expires_main_thread_records(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _git(tmp_path, "init", "-b", "main", str(repo))
    (repo / "f").write_text("x")
    _git(repo, "add", "f")
    _git(repo, "commit", "-m", "base")
    untracked = tmp_path / "u"
    marker = EvacuationTurnMarkerHandler()
    marker._untracked_override = untracked
    marker.handle(_prompt())
    works = evacuations(f"git -C {repo} diff >{tmp_path}/p.patch", repo)
    record_evacuations(untracked, "s1", None, works)
    assert recorded_evacuations(untracked, "s1", None) != []
    result = marker.handle(_prompt())
    assert result.decision == Decision.ALLOW
    assert recorded_evacuations(untracked, "s1", None) == []


def test_no_session_does_not_match() -> None:
    assert EvacuationTurnMarkerHandler().matches({"prompt": "x"}) is False
    assert EvacuationTurnMarkerHandler().matches(_prompt()) is True
