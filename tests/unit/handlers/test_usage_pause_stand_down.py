"""Plan 00479 Tasks 4.3 and 4.4: handlers that force continuation or re-arm crons stand down.

All of them read the ONE predicate, ``utils.usage_pause_gate.is_usage_paused``,
rather than ``cron_pause`` (see that module's docstring for why). Each case runs
the handler against a payload it matches when NOT paused (the control) and then
with a live pause record, so a regression cannot pass vacuously.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.config.models import (
    Config,
    PersistentCronConfig,
    PersistentCronsConfig,
)
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.handlers.post_tool_use.recovery_cron_advisor import (
    RecoveryCronAdvisorHandler,
)
from claude_code_hooks_daemon.handlers.session_start.failsafe_cron_session_advisor import (
    FailsafeCronSessionAdvisorHandler,
)
from claude_code_hooks_daemon.handlers.session_start.persistent_cron_assertor import (
    PersistentCronAssertorHandler,
)
from claude_code_hooks_daemon.handlers.stop.auto_continue_stop import AutoContinueStopHandler
from claude_code_hooks_daemon.handlers.stop.cron_stop_enforcer import CronStopEnforcerHandler
from claude_code_hooks_daemon.handlers.subagent_stop.cron_subagent_stop_enforcer import (
    CronSubagentStopEnforcerHandler,
)
from claude_code_hooks_daemon.utils.usage_pause import (
    WINDOW_FIVE_HOUR,
    UsagePause,
    write_usage_pause,
)

_SESSION = "sess-1"
_JOB = PersistentCronConfig(id="j", schedule="*/20 * * * *", prompt="do the thing")
_CONFIG = Config(persistent_crons=PersistentCronsConfig(enabled=True, jobs=[_JOB]))


def _record(tmp_path: Path, *, session: str = _SESSION) -> None:
    now = time.time()
    write_usage_pause(
        tmp_path,
        UsagePause(
            session_id=session,
            paused_at=now - 60,
            resume_at=now + 3600,
            window=WINDOW_FIVE_HOUR,
            used_percentage=91.0,
            ceiling=80.0,
            reason="five_hour window at 91% (ceiling 80%)",
        ),
    )


@contextmanager
def _context(tmp_path: Path) -> Iterator[None]:
    with patch.object(ProjectContext, "daemon_untracked_dir", return_value=tmp_path):
        yield


def _cron_stop_enforcer(monkeypatch: pytest.MonkeyPatch) -> CronStopEnforcerHandler:
    handler = CronStopEnforcerHandler()
    monkeypatch.setattr(handler, "_load_config", lambda: _CONFIG)
    return handler


def _cron_subagent_stop_enforcer(
    monkeypatch: pytest.MonkeyPatch,
) -> CronSubagentStopEnforcerHandler:
    handler = CronSubagentStopEnforcerHandler()
    monkeypatch.setattr(handler, "_load_config", lambda: _CONFIG)
    return handler


def _persistent_cron_assertor(monkeypatch: pytest.MonkeyPatch) -> PersistentCronAssertorHandler:
    handler = PersistentCronAssertorHandler()
    monkeypatch.setattr(handler, "_load_config", lambda: _CONFIG)
    return handler


def _failsafe_session_advisor(monkeypatch: pytest.MonkeyPatch) -> FailsafeCronSessionAdvisorHandler:
    handler = FailsafeCronSessionAdvisorHandler()
    monkeypatch.setattr(handler, "_load_config", lambda: Config())
    return handler


_STOP: dict[str, Any] = {"hook_event_name": "Stop", "session_id": _SESSION, "session_crons": []}
_SUBAGENT_STOP: dict[str, Any] = {
    "hook_event_name": "SubagentStop",
    "session_id": _SESSION,
    "session_crons": [],
}
_SESSION_START: dict[str, Any] = {
    "hook_event_name": "SessionStart",
    "session_id": _SESSION,
    "source": "startup",
}
_POST_COMPACT_START: dict[str, Any] = {
    "hook_event_name": "SessionStart",
    "session_id": _SESSION,
    "source": "compact",
}

_CASES: list[tuple[str, Callable[[pytest.MonkeyPatch], Any], dict[str, Any]]] = [
    ("cron_stop_enforcer", _cron_stop_enforcer, _STOP),
    ("cron_subagent_stop_enforcer", _cron_subagent_stop_enforcer, _SUBAGENT_STOP),
    ("persistent_cron_assertor", _persistent_cron_assertor, _SESSION_START),
    ("persistent_cron_assertor post-compact", _persistent_cron_assertor, _POST_COMPACT_START),
    ("failsafe_cron_session_advisor", _failsafe_session_advisor, _SESSION_START),
    ("failsafe_cron_session_advisor post-compact", _failsafe_session_advisor, _POST_COMPACT_START),
    ("auto_continue_stop", lambda _mp: AutoContinueStopHandler(), _STOP),
]


@pytest.mark.parametrize(("label", "factory", "payload"), _CASES, ids=[c[0] for c in _CASES])
class TestStandsDownWhilePaused:
    def test_control_matches_when_not_paused(
        self,
        label: str,
        factory: Callable[[pytest.MonkeyPatch], Any],
        payload: dict[str, Any],
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        handler = factory(monkeypatch)
        with _context(tmp_path):
            assert handler.matches(dict(payload)) is True, label

    def test_does_not_match_while_paused(
        self,
        label: str,
        factory: Callable[[pytest.MonkeyPatch], Any],
        payload: dict[str, Any],
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _record(tmp_path)
        handler = factory(monkeypatch)
        with _context(tmp_path):
            assert handler.matches(dict(payload)) is False, label

    def test_another_sessions_pause_changes_nothing(
        self,
        label: str,
        factory: Callable[[pytest.MonkeyPatch], Any],
        payload: dict[str, Any],
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _record(tmp_path, session="someone-else")
        handler = factory(monkeypatch)
        with _context(tmp_path):
            assert handler.matches(dict(payload)) is True, label


class TestRecoveryCronAdvisor:
    """A PostToolUse plan write is unreachable while paused (the tool gate), but the
    advisor also stands down itself, so a project with the tool gate off is still quiet."""

    def test_stands_down_while_paused(self, tmp_path: Path) -> None:
        _record(tmp_path)
        handler = RecoveryCronAdvisorHandler()
        payload = {
            "hook_event_name": "PostToolUse",
            "session_id": _SESSION,
            "tool_name": "Write",
            "tool_input": {"file_path": "/x/CLAUDE/Plan/00001-x/PLAN.md", "content": "x"},
        }
        with _context(tmp_path):
            assert handler.matches(payload) is False
