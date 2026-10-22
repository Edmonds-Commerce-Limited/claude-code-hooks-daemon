"""A usage pause that survived a daemon restart is stated through the REAL chain order.

``usage_pause_gate`` (priority 9, terminal) denies every prompt while a pause is
held, so ``focus_mode_trigger`` (priority 41) never sees those prompts, and the
one prompt the gate allows while the pause continues is the resume tick that
finds usage still over the ceiling -- which re-starts the pause with a fresh
``paused_at``. A test that calls the statement function alone cannot see that;
this one runs both real handlers in one ``HandlerChain``.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

import pytest
from tests.support.autonomy import pin_session_modes

from claude_code_hooks_daemon.config.models import Config, HostConfig, UsageCeilingConfig
from claude_code_hooks_daemon.constants.modes import DaemonMode, ModeConstant
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.chain import HandlerChain
from claude_code_hooks_daemon.core.usage_snapshot import UsageSnapshot, UsageWindow
from claude_code_hooks_daemon.handlers.user_prompt_submit.focus_mode_trigger import (
    FocusModeTriggerHandler,
)
from claude_code_hooks_daemon.handlers.user_prompt_submit.usage_pause_gate import (
    UsagePauseGateHandler,
)
from claude_code_hooks_daemon.utils import usage_pause
from claude_code_hooks_daemon.utils.usage_pause_gate import USAGE_RESUME_PROMPT

_SESSION = "sess-paused"
_HOST = "runner"
_TRIGGER = "claude_code_hooks_daemon.handlers.user_prompt_submit.focus_mode_trigger"
_GATE = "claude_code_hooks_daemon.handlers.user_prompt_submit.usage_pause_gate"
_REASON = "five_hour window at 91% (ceiling 80%)"


def _gate(now: float, used: float) -> UsagePauseGateHandler:
    gate = UsagePauseGateHandler()
    gate._clock = time.time
    gate._config_loader = lambda: Config(
        hosts={_HOST: HostConfig(usage_ceiling=UsageCeilingConfig(max_used_percent=80.0))}
    )
    window = UsageWindow(used, int(now + 3 * 3600), now)
    gate._usage_loader = lambda _now: UsageSnapshot(five_hour=window, seven_day=None)
    return gate


def _input(prompt: str) -> dict[str, Any]:
    return {
        "hook_event_name": "UserPromptSubmit",
        "prompt": prompt,
        "session_id": _SESSION,
        "hooks_daemon_hostname": _HOST,
    }


@pytest.fixture
def restarted_while_paused(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Mock]:
    """A due pause recorded BEFORE the daemon (and so the registry) loaded."""
    now = time.time()
    usage_pause.write_usage_pause(
        tmp_path,
        usage_pause.UsagePause(
            session_id=_SESSION,
            paused_at=now - 7200,
            resume_at=now - 30,
            window=usage_pause.WINDOW_FIVE_HOUR,
            used_percentage=91.0,
            ceiling=80.0,
            reason=_REASON,
        ),
    )
    pin_session_modes(monkeypatch, tmp_path)
    controller = Mock()
    controller.get_mode.return_value = {ModeConstant.KEY_MODE: DaemonMode.DEFAULT.value}
    with patch(f"{_TRIGGER}.get_controller", return_value=controller):
        yield controller


def _chain(used: float) -> HandlerChain:
    chain = HandlerChain()
    chain.add(_gate(time.time(), used))
    chain.add(FocusModeTriggerHandler())
    return chain


def _mode_lines(context: list[str]) -> list[str]:
    return [line for line in context if line.startswith("SESSION MODE:")]


class TestARestartedPausedSession:
    def test_a_held_prompt_never_reaches_the_trigger(self, restarted_while_paused: Mock) -> None:
        execution = _chain(used=91.0).execute(_input("carry on"))
        assert execution.result.decision is Decision.DENY
        assert FocusModeTriggerHandler().name not in execution.handlers_executed

    def test_the_still_over_tick_states_the_surviving_pause_once(
        self, restarted_while_paused: Mock
    ) -> None:
        execution = _chain(used=91.0).execute(_input(USAGE_RESUME_PROMPT))
        assert execution.result.decision is Decision.ALLOW
        assert any("STILL OVER" in line for line in execution.result.context)
        [line] = _mode_lines(execution.result.context)
        assert f"usage-paused ({_REASON}) survived a daemon restart and still applies" in line

    def test_unattended_is_named_beside_the_surviving_pause(
        self, restarted_while_paused: Mock
    ) -> None:
        restarted_while_paused.get_mode.return_value = {
            ModeConstant.KEY_MODE: DaemonMode.UNATTENDED.value
        }
        execution = _chain(used=91.0).execute(_input(USAGE_RESUME_PROMPT))
        [line] = _mode_lines(execution.result.context)
        assert "the daemon is in unattended mode" in line

    def test_the_next_allowed_prompt_does_not_state_it_again(
        self, restarted_while_paused: Mock
    ) -> None:
        _chain(used=91.0).execute(_input(USAGE_RESUME_PROMPT))
        later = _chain(used=10.0).execute(_input(USAGE_RESUME_PROMPT))
        assert _mode_lines(later.result.context) == []

    def test_an_unusable_registry_is_stated_beside_the_directive(
        self, restarted_while_paused: Mock, caplog: pytest.LogCaptureFixture
    ) -> None:
        with (
            patch(f"{_GATE}.get_data_layer", side_effect=OSError("disk gone")),
            caplog.at_level(logging.WARNING),
        ):
            result = _gate(time.time(), 91.0).handle(_input(USAGE_RESUME_PROMPT))
        assert result.decision is Decision.ALLOW
        assert any("STILL OVER" in line for line in result.context)
        [line] = _mode_lines(result.context)
        assert "could not read" in line
        assert "disk gone" in line
        assert "disk gone" in caplog.text

    def test_a_lift_does_not_claim_the_pause_still_applies(
        self, restarted_while_paused: Mock
    ) -> None:
        execution = _chain(used=10.0).execute(_input(USAGE_RESUME_PROMPT))
        assert execution.result.decision is Decision.ALLOW
        assert not any("survived a daemon restart" in line for line in execution.result.context)
