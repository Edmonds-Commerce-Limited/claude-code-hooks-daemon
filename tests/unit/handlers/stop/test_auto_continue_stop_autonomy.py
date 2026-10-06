"""`auto_continue_stop` gives up its two work-driving parts where autonomy is off (Plan 00498).

Two things in this handler push a session towards work nobody asked it for: the
goal-ledger challenge, which names every In Progress plan a stop must answer for,
and the stand-in cron an `[awaiting-human]` stop must schedule. Both are silent on
a desktop session of a project that allows autonomy in containers only, and
unchanged in a container.

The plain `STOPPING BECAUSE:` rule is NOT part of that: it asks for a reason, not
for more work, so it applies in every environment. Driven through the real chain.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from tests.support.autonomy import pin_container_containers_only, pin_desktop_containers_only

from claude_code_hooks_daemon.config.models import Config, PersistentCronsConfig
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.chain import HandlerChain
from claude_code_hooks_daemon.handlers.stop.auto_continue_stop import AutoContinueStopHandler
from claude_code_hooks_daemon.utils.goal_ledger import LEDGER_FILENAME, GoalLedger

_AWAITING = "STOPPING BECAUSE: [awaiting-human] the owner has to choose between A and B."
_UNEXPLAINED = "Here is the result of the work."
_PLAN = "00274"


def _transcript(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "transcript.jsonl"
    message = {
        "type": "message",
        "message": {"role": "assistant", "content": [{"type": "text", "text": text}]},
    }
    path.write_text(json.dumps(message) + "\n", encoding="utf-8")
    return path


def _ledgered_plan(tmp_path: Path) -> None:
    plan_dir = tmp_path / "CLAUDE" / "Plan"
    folder = plan_dir / f"{_PLAN}-example"
    folder.mkdir(parents=True)
    (folder / "PLAN.md").write_text(
        f"# Plan {_PLAN}\n\n**Status**: In Progress\n", encoding="utf-8"
    )
    GoalLedger(tmp_path / LEDGER_FILENAME).record_emission("s", _PLAN, "goal", plan_dir)


def _stop(tmp_path: Path, text: str, **extra: Any) -> Any:
    handler = AutoContinueStopHandler()
    handler._config_loader = lambda: Config(persistent_crons=PersistentCronsConfig(enabled=True))
    chain = HandlerChain()
    chain.add(handler)
    hook_input = {
        "hook_event_name": "Stop",
        "session_id": "lead",
        "transcript_path": str(_transcript(tmp_path, text)),
        "stop_hook_active": False,
        **extra,
    }
    base = "claude_code_hooks_daemon.handlers.stop.auto_continue_stop.ProjectContext"
    with (
        patch(f"{base}.daemon_untracked_dir", return_value=tmp_path),
        patch(f"{base}.project_root", return_value=tmp_path),
    ):
        return chain.execute(hook_input).result


class TestGoalLedgerChallenge:
    def test_silent_on_a_desktop(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        pin_desktop_containers_only(monkeypatch)
        _ledgered_plan(tmp_path)
        result = _stop(tmp_path, _UNEXPLAINED)
        assert result.decision is Decision.DENY
        assert _PLAN not in result.reason
        assert "GOAL LEDGER" not in result.reason

    def test_the_plain_reason_rule_still_applies_on_a_desktop(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pin_desktop_containers_only(monkeypatch)
        result = _stop(tmp_path, _UNEXPLAINED)
        assert result.decision is Decision.DENY
        assert "STOPPING BECAUSE" in result.reason

    def test_unchanged_in_a_container(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pin_container_containers_only(monkeypatch)
        _ledgered_plan(tmp_path)
        result = _stop(tmp_path, _UNEXPLAINED)
        assert result.decision is Decision.DENY
        assert _PLAN in result.reason
        assert "GOAL LEDGER" in result.reason


class TestStandInCron:
    def test_not_demanded_on_a_desktop(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pin_desktop_containers_only(monkeypatch)
        result = _stop(tmp_path, _AWAITING, session_crons=[])
        assert result.decision is Decision.ALLOW

    def test_still_demanded_in_a_container(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pin_container_containers_only(monkeypatch)
        result = _stop(tmp_path, _AWAITING, session_crons=[])
        assert result.decision is Decision.DENY
        assert "[tick:stand-in]" in result.reason
