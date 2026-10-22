"""Focus mode through the cron-tick suppressor (Plan 00501 Task 3.2, ruling 04).

While a session is focused, a declared ``persistent_crons`` tick is dropped
before the model (even a job that runs while awaiting the human), the watchdog
tick is delivered, and the failsafe tick is delivered with one prepended line
naming the focus task. Another session's focus changes nothing.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Final
from unittest.mock import patch

import pytest
from tests.support.autonomy import focus_entry, pin_session_modes

from claude_code_hooks_daemon.config.models import (
    Config,
    PersistentCronConfig,
    PersistentCronsConfig,
)
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.session_mode_registry import SessionModeRegistry
from claude_code_hooks_daemon.handlers.post_tool_use.background_process_tracker import (
    watchdog_cron_prompt,
)
from claude_code_hooks_daemon.handlers.post_tool_use.recovery_cron_advisor import (
    CANONICAL_CRON_PROMPT,
)
from claude_code_hooks_daemon.handlers.user_prompt_submit.failsafe_cron_blockage_suppressor import (
    FailsafeCronBlockageSuppressorHandler,
)
from claude_code_hooks_daemon.utils.cron_enforcement import declared_tick_prompt

_SESSION: Final[str] = "sess-focus"
_TASK: Final[str] = "fix the parser"
_OWED_PATCH_TARGET: Final[str] = (
    "claude_code_hooks_daemon.handlers.user_prompt_submit."
    "failsafe_cron_blockage_suppressor.FailsafeCronBlockageSuppressorHandler._work_is_owed"
)
_JOB: Final[PersistentCronConfig] = PersistentCronConfig(
    id="issue-sdlc", schedule="23 * * * *", prompt="Run the issue loop."
)
_FOCUS_LINE: Final[str] = f"focus mode: the active task is {_TASK}; other plans are out of scope"


@pytest.fixture(autouse=True)
def registry(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> SessionModeRegistry:
    return pin_session_modes(monkeypatch, tmp_path, focus_entry(_SESSION, _TASK))


def _handler(*, runs_while_awaiting_human: bool = False) -> FailsafeCronBlockageSuppressorHandler:
    job = _JOB.model_copy(update={"runs_while_awaiting_human": runs_while_awaiting_human})
    handler = FailsafeCronBlockageSuppressorHandler()
    handler._config_loader = lambda: Config(
        persistent_crons=PersistentCronsConfig(enabled=True, jobs=[job])
    )
    return handler


def _input(prompt: str, session_id: str = _SESSION) -> dict[str, Any]:
    return {"prompt": prompt, "session_id": session_id}


class TestFailsafeTick:
    @pytest.mark.parametrize("owed", [True, False, None])
    def test_delivered_with_the_focus_line(self, owed: bool | None) -> None:
        with patch(_OWED_PATCH_TARGET, return_value=owed):
            result = _handler().handle(_input(CANONICAL_CRON_PROMPT))
        assert result.decision is Decision.ALLOW
        assert result.context == [_FOCUS_LINE]

    def test_another_sessions_focus_adds_no_line(self) -> None:
        with patch(_OWED_PATCH_TARGET, return_value=True):
            result = _handler().handle(_input(CANONICAL_CRON_PROMPT, "sess-other"))
        assert result.decision is Decision.ALLOW
        assert result.context == []


class TestDeclaredTick:
    def test_dropped_and_names_focus(self) -> None:
        result = _handler().handle(_input(declared_tick_prompt(_JOB)))
        assert result.decision is Decision.DENY
        assert result.rule == RuleID.DECLARED_CRON_SUPPRESSED
        assert _TASK in (result.reason or "")

    def test_dropped_even_for_a_job_that_runs_while_awaiting_human(self) -> None:
        result = _handler(runs_while_awaiting_human=True).handle(_input(declared_tick_prompt(_JOB)))
        assert result.decision is Decision.DENY

    def test_delivered_for_another_session(self) -> None:
        result = _handler().handle(_input(declared_tick_prompt(_JOB), "sess-other"))
        assert result.decision is Decision.ALLOW


class TestWatchdogTick:
    def test_delivered_unchanged(self) -> None:
        result = _handler().handle(_input(watchdog_cron_prompt()))
        assert result.decision is Decision.ALLOW
        assert result.context == []
