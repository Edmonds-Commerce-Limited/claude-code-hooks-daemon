"""An `[awaiting-human]` stop must leave a one-off stand-in cron (Plan 00470 Task 5.2).

Driven through the real `HandlerChain`, so the main-thread scope gate is part of
what is under test.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from tests.support.autonomy import (
    awaiting_human_entry,
    focus_entry,
    pin_desktop_containers_only,
    pin_session_modes,
)

from claude_code_hooks_daemon.config.models import Config, PersistentCronsConfig
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.chain import HandlerChain
from claude_code_hooks_daemon.core.session_mode_registry import SessionModeRegistry
from claude_code_hooks_daemon.handlers.stop.auto_continue_stop import AutoContinueStopHandler
from claude_code_hooks_daemon.handlers.user_prompt_submit.failsafe_cron_blockage_suppressor import (
    FailsafeCronBlockageSuppressorHandler,
)
from claude_code_hooks_daemon.utils.session_modes import ModeLabel
from claude_code_hooks_daemon.utils.session_signal_paths import SIGNAL_SUBDIR
from claude_code_hooks_daemon.utils.stand_in_cron import stand_in_prompt

_AWAITING = "STOPPING BECAUSE: [awaiting-human] the owner has to choose between A and B."
_ORDINARY = "STOPPING BECAUSE: all tasks complete."
_SUBAGENT_ID = "agent_01H9XQK2M4N7P"
_ENABLED = Config(persistent_crons=PersistentCronsConfig(enabled=True))
_STAND_IN_CRON = {
    "id": "s1",
    "schedule": "15 12 6 10 *",
    "prompt": stand_in_prompt(),
    "recurring": False,
}


def _transcript(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "transcript.jsonl"
    message = {
        "type": "message",
        "message": {"role": "assistant", "content": [{"type": "text", "text": text}]},
    }
    path.write_text(json.dumps(message) + "\n", encoding="utf-8")
    return path


def _registry(untracked: Path) -> SessionModeRegistry:
    """A fresh read of the session-modes files the stop wrote under ``untracked``."""
    registry = SessionModeRegistry(untracked / SIGNAL_SUBDIR)
    registry.load()
    return registry


def _handler(config: Config = _ENABLED) -> AutoContinueStopHandler:
    handler = AutoContinueStopHandler()
    handler._config_loader = lambda: config
    return handler


def _stop(
    tmp_path: Path,
    text: str = _AWAITING,
    *,
    handler: AutoContinueStopHandler | None = None,
    **extra: Any,
) -> Any:
    chain = HandlerChain()
    chain.add(handler or _handler())
    hook_input = {
        "hook_event_name": "Stop",
        "session_id": "lead",
        "transcript_path": str(_transcript(tmp_path, text)),
        "stop_hook_active": False,
        **extra,
    }
    with patch(
        "claude_code_hooks_daemon.handlers.stop.auto_continue_stop."
        "ProjectContext.daemon_untracked_dir",
        return_value=tmp_path,
    ):
        return chain.execute(hook_input).result


class TestAwaitingHumanStopNeedsAStandIn:
    def test_blocked_without_a_stand_in_cron(self, tmp_path: Path) -> None:
        result = _stop(tmp_path, session_crons=[])
        assert result.decision is Decision.DENY
        assert "CronCreate" in result.reason
        assert "recurring: false" in result.reason
        assert "[tick:stand-in]" in result.reason

    def test_allowed_with_the_stand_in_cron(self, tmp_path: Path) -> None:
        result = _stop(tmp_path, session_crons=[_STAND_IN_CRON])
        assert result.decision is Decision.ALLOW

    def test_the_marker_is_still_armed_when_blocked(self, tmp_path: Path) -> None:
        _stop(tmp_path, session_crons=[])
        assert _registry(tmp_path).policy("lead").is_blocked

    def test_absent_session_crons_is_no_information(self, tmp_path: Path) -> None:
        assert _stop(tmp_path).decision is Decision.ALLOW

    def test_an_ordinary_stop_needs_no_stand_in(self, tmp_path: Path) -> None:
        assert _stop(tmp_path, _ORDINARY, session_crons=[]).decision is Decision.ALLOW

    def test_the_delay_option_reaches_the_instruction(self, tmp_path: Path) -> None:
        handler = _handler()
        handler._stand_in_delay_hours = 1.5
        result = _stop(tmp_path, handler=handler, session_crons=[])
        assert "1.5 hours" in result.reason

    def test_inert_while_persistent_crons_is_off(self, tmp_path: Path) -> None:
        result = _stop(tmp_path, handler=_handler(Config()), session_crons=[])
        assert result.decision is Decision.ALLOW


_REAL_STOP_LINE = "STOPPING BECAUSE: background QA is still running."
_PASTE_FOR_ANOTHER_SESSION = "STOPPING BECAUSE: [awaiting-human] pick A or B."


class TestOnlyTheStopsOwnDeclarationCounts:
    """N365: a token inside a fence or quoted copy-paste is not this stop's declaration."""

    @pytest.mark.parametrize(
        "quoted",
        [
            f"```\n{_PASTE_FOR_ANOTHER_SESSION}\n```",
            f"```text\n{_PASTE_FOR_ANOTHER_SESSION}\n```",
            f"~~~\n{_PASTE_FOR_ANOTHER_SESSION}\n~~~",
            f"> {_PASTE_FOR_ANOTHER_SESSION}",
            f"    {_PASTE_FOR_ANOTHER_SESSION}",
            "```\nneed user input\n```",
        ],
        ids=["fence", "fence-lang", "tilde-fence", "blockquote", "indented", "older-phrasing"],
    )
    def test_a_quoted_declaration_demands_no_stand_in(self, tmp_path: Path, quoted: str) -> None:
        text = f"Paste this into the other session:\n\n{quoted}\n\n{_REAL_STOP_LINE}"
        result = _stop(tmp_path, text, session_crons=[])
        assert result.decision is Decision.ALLOW
        assert not _registry(tmp_path).policy("lead").is_blocked

    def test_a_fence_before_the_real_declaration_does_not_hide_it(self, tmp_path: Path) -> None:
        text = f"```\nexample\n```\n\n{_AWAITING}"
        result = _stop(tmp_path, text, session_crons=[])
        assert result.decision is Decision.DENY
        assert "[tick:stand-in]" in result.reason

    def test_an_older_phrasing_in_the_stop_line_still_declares(self, tmp_path: Path) -> None:
        text = "```\nx\n```\nSTOPPING BECAUSE: need user input on A or B."
        result = _stop(tmp_path, text, session_crons=[])
        assert result.decision is Decision.DENY


class TestMainThreadOnly:
    def test_a_sub_agent_stop_is_never_required_to_schedule_one(self, tmp_path: Path) -> None:
        result = _stop(tmp_path, session_crons=[], agent_id=_SUBAGENT_ID)
        assert result.decision is not Decision.DENY or "stand-in" not in (result.reason or "")
        assert not _registry(tmp_path).policy("lead").is_blocked


class TestDelayOption:
    def test_default_is_three_hours(self) -> None:
        assert AutoContinueStopHandler()._stand_in_delay_hours == 3.0

    @pytest.mark.parametrize("bad", [0, -2, 24, "3", True, None])
    def test_invalid_values_are_refused(self, bad: object) -> None:
        handler = AutoContinueStopHandler()
        with pytest.raises(ValueError, match="stand_in_delay_hours"):
            handler._stand_in_delay_hours = bad

    def test_a_valid_value_is_kept(self) -> None:
        handler = AutoContinueStopHandler()
        handler._stand_in_delay_hours = 2
        assert handler._stand_in_delay_hours == 2.0


class TestTheStandInTickIsNotSuppressed:
    """It must fire precisely while the session is blocked on the human."""

    @pytest.fixture
    def registry(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> SessionModeRegistry:
        return pin_session_modes(monkeypatch, tmp_path, awaiting_human_entry("lead"))

    def _tick(self, prompt: str) -> Decision:
        handler = FailsafeCronBlockageSuppressorHandler()
        handler._config_loader = lambda: Config()
        return handler.handle({"prompt": prompt, "session_id": "lead"}).decision

    def test_delivered_while_awaiting_human(self, registry: SessionModeRegistry) -> None:
        assert self._tick(stand_in_prompt()) is Decision.ALLOW

    def test_the_mode_survives_it(self, registry: SessionModeRegistry) -> None:
        self._tick(stand_in_prompt())
        assert registry.policy("lead").is_blocked

    def test_sensitivity_a_declared_tick_is_still_dropped(
        self, registry: SessionModeRegistry
    ) -> None:
        assert self._tick("[tick:job:other]\nbody") is Decision.DENY


class TestTheStandInIsOnlyDemandedWhereAutonomyRuns:
    """Plan 00501 Task 2.2: the stand-in deny follows the autonomy verdict."""

    def test_after_the_stop_the_registry_holds_awaiting_human_and_the_deny_fires(
        self, tmp_path: Path
    ) -> None:
        result = _stop(tmp_path, session_crons=[])
        assert result.decision is Decision.DENY
        assert "[tick:stand-in]" in result.reason
        assert _registry(tmp_path).policy("lead").labels == (ModeLabel.AWAITING_HUMAN,)

    def test_a_desktop_containers_only_stop_is_not_asked_for_one(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        pin_desktop_containers_only(monkeypatch)
        pin_session_modes(monkeypatch, tmp_path)
        result = _stop(tmp_path, session_crons=[])
        assert result.decision is not Decision.DENY or "stand-in" not in (result.reason or "")

    def test_a_stop_under_focus_is_not_asked_for_one(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        pin_session_modes(monkeypatch, tmp_path, focus_entry("lead"))
        result = _stop(tmp_path, session_crons=[])
        assert result.decision is not Decision.DENY or "stand-in" not in (result.reason or "")
