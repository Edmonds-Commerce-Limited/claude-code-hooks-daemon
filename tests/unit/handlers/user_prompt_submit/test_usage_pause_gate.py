"""Tests for UsagePauseGateHandler (Plan 00479 Tasks 4.1, 4.6, 4.7).

The UserPromptSubmit gate pauses a session whose host usage ceiling is reached.
``decision: "block"`` shows its reason to the USER and never adds it to the
model's context, so the directive that makes the model replace its crons is
delivered as ``additionalContext`` on an ALLOWED prompt; every later prompt
while the pause holds (cron tick, supervisor message, anything) is blocked
before it reaches the model, except the one-shot resume cron.

Every test uses an isolated tmp dir for the pause record and injects the usage
snapshot, so nothing here touches a live daemon's snapshot or a real session.
"""

from __future__ import annotations

import logging
from datetime import UTC
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.config.models import (
    Config,
    HostConfig,
    PersistentCronConfig,
    PersistentCronsConfig,
    UsageCeilingConfig,
)
from claude_code_hooks_daemon.constants import HandlerID, Priority
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.core.usage_snapshot import UsageSnapshot, UsageWindow
from claude_code_hooks_daemon.handlers.post_tool_use.recovery_cron_advisor import (
    CANONICAL_CRON_PROMPT,
)
from claude_code_hooks_daemon.handlers.user_prompt_submit.usage_pause_gate import (
    UsagePauseGateHandler,
)
from claude_code_hooks_daemon.utils import usage_pause_gate as gate
from claude_code_hooks_daemon.utils.usage_pause import (
    WINDOW_FIVE_HOUR,
    UsagePause,
    read_usage_pause,
    write_usage_pause,
)

_SESSION = "sess-1"
_HOST = "runner"
_NOW = 1_790_000_000.0
_FIVE_RESET = int(_NOW + 3 * 3600)
_SEVEN_RESET = int(_NOW + 3 * 86400)


def _config(
    limit: float | None = 80.0, *, jobs: list[PersistentCronConfig] | None = None
) -> Config:
    hosts = (
        {_HOST: HostConfig(usage_ceiling=UsageCeilingConfig(max_used_percent=limit))}
        if limit is not None
        else {}
    )
    return Config(
        hosts=hosts,
        persistent_crons=PersistentCronsConfig(enabled=bool(jobs), jobs=jobs or []),
    )


def _snapshot(five: float | None = None, seven: float | None = None) -> UsageSnapshot:
    return UsageSnapshot(
        five_hour=UsageWindow(five, _FIVE_RESET, _NOW) if five is not None else None,
        seven_day=UsageWindow(seven, _SEVEN_RESET, _NOW) if seven is not None else None,
    )


def _handler(
    tmp_path: Path,
    *,
    config: Config | None = None,
    snapshot: UsageSnapshot | None = None,
) -> UsagePauseGateHandler:
    handler = UsagePauseGateHandler()
    handler._clock = lambda: _NOW
    handler._config_loader = lambda: config if config is not None else _config()
    handler._usage_loader = lambda now: snapshot
    handler._tz = UTC
    return handler


def _input(prompt: str = "please do the next thing", session: str = _SESSION) -> dict[str, Any]:
    return {
        "prompt": prompt,
        "session_id": session,
        "hooks_daemon_hostname": _HOST,
    }


def _run(handler: UsagePauseGateHandler, tmp_path: Path, hook_input: dict[str, Any]) -> Any:
    with patch.object(ProjectContext, "daemon_untracked_dir", return_value=tmp_path):
        assert handler.matches(hook_input) is True
        return handler.handle(hook_input)


def _record(tmp_path: Path, *, session: str = _SESSION, resume_at: float = _NOW + 3600) -> None:
    write_usage_pause(
        tmp_path,
        UsagePause(
            session_id=session,
            paused_at=min(_NOW - 60, resume_at - 3600),
            resume_at=resume_at,
            window=WINDOW_FIVE_HOUR,
            used_percentage=91.0,
            ceiling=80.0,
            reason="five_hour window at 91% (ceiling 80%)",
        ),
    )


class TestInit:
    def test_identity_and_priority(self) -> None:
        handler = UsagePauseGateHandler()
        assert handler.name == HandlerID.USAGE_PAUSE_GATE.display_name
        assert handler.priority == Priority.USAGE_PAUSE_GATE

    def test_terminal_so_a_held_prompt_reaches_no_later_handler(self) -> None:
        """Only a DENY ends the chain (an ALLOW never does, core/chain.py), so the
        entry and lift directives, which ride on ALLOWs, are unaffected."""
        assert UsagePauseGateHandler().terminal is True


class TestDataSafety:
    """Task 4.7: missing data never pauses a session, and a debug line says why."""

    def test_no_ceiling_for_the_host(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        handler = _handler(tmp_path, config=_config(None), snapshot=_snapshot(five=99.0))
        with caplog.at_level(logging.DEBUG):
            result = _run(handler, tmp_path, _input())
        assert result.decision == Decision.ALLOW
        assert read_usage_pause(tmp_path, _SESSION, now=_NOW) is None
        assert "no usage ceiling" in caplog.text

    def test_unknown_hostname(self, tmp_path: Path) -> None:
        handler = _handler(tmp_path, snapshot=_snapshot(five=99.0))
        hook_input = _input()
        hook_input["hooks_daemon_hostname"] = "somewhere-else"
        result = _run(handler, tmp_path, hook_input)
        assert result.decision == Decision.ALLOW
        assert read_usage_pause(tmp_path, _SESSION, now=_NOW) is None

    def test_no_snapshot(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        handler = _handler(tmp_path, snapshot=None)
        with caplog.at_level(logging.DEBUG):
            result = _run(handler, tmp_path, _input())
        assert result.decision == Decision.ALLOW
        assert read_usage_pause(tmp_path, _SESSION, now=_NOW) is None
        assert "no usage snapshot" in caplog.text

    def test_snapshot_with_no_windows(self, tmp_path: Path) -> None:
        handler = _handler(tmp_path, snapshot=_snapshot())
        assert _run(handler, tmp_path, _input()).decision == Decision.ALLOW
        assert read_usage_pause(tmp_path, _SESSION, now=_NOW) is None

    def test_below_the_ceiling(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        handler = _handler(tmp_path, snapshot=_snapshot(five=79.9, seven=10.0))
        with caplog.at_level(logging.DEBUG):
            result = _run(handler, tmp_path, _input())
        assert result.decision == Decision.ALLOW
        assert not result.context
        assert read_usage_pause(tmp_path, _SESSION, now=_NOW) is None
        assert "below" in caplog.text

    def test_no_project_context_fails_open(self) -> None:
        handler = UsagePauseGateHandler()
        handler._clock = lambda: _NOW
        handler._config_loader = lambda: _config()
        handler._usage_loader = lambda now: _snapshot(five=99.0)
        with patch.object(ProjectContext, "daemon_untracked_dir", side_effect=RuntimeError("x")):
            result = handler.handle(_input())
        assert result.decision == Decision.ALLOW
        assert not result.context

    def test_a_failed_record_write_fails_open(self, tmp_path: Path) -> None:
        handler = _handler(tmp_path, snapshot=_snapshot(five=99.0))
        with patch(
            "claude_code_hooks_daemon.utils.usage_pause_gate.write_usage_pause",
            side_effect=OSError("disk full"),
        ):
            result = _run(handler, tmp_path, _input())
        assert result.decision == Decision.ALLOW
        assert not result.context


class TestEntry:
    """Task 4.1: reaching the ceiling records the pause and delivers the directive."""

    def test_at_the_ceiling_the_pause_is_recorded(self, tmp_path: Path) -> None:
        handler = _handler(tmp_path, snapshot=_snapshot(five=80.0))
        _run(handler, tmp_path, _input())
        pause = read_usage_pause(tmp_path, _SESSION, now=_NOW)
        assert pause is not None
        assert pause.window == WINDOW_FIVE_HOUR
        assert pause.resume_at == _FIVE_RESET + gate.RESUME_MARGIN_SECONDS
        assert pause.ceiling == 80.0

    def test_the_directive_rides_on_an_allowed_prompt(self, tmp_path: Path) -> None:
        handler = _handler(tmp_path, snapshot=_snapshot(five=91.4))
        result = _run(handler, tmp_path, _input())
        assert result.decision == Decision.ALLOW
        text = "\n".join(result.context)
        assert "five_hour" in text
        assert "91%" in text
        assert "80%" in text
        assert "CronList" in text and "CronDelete" in text and "CronCreate" in text
        assert "[tick:usage-resume]" in text
        assert "Do NOT act on" in text

    def test_the_resume_time_is_the_latest_reset_among_breached_windows(
        self, tmp_path: Path
    ) -> None:
        handler = _handler(tmp_path, snapshot=_snapshot(five=95.0, seven=85.0))
        _run(handler, tmp_path, _input())
        pause = read_usage_pause(tmp_path, _SESSION, now=_NOW)
        assert pause is not None
        assert pause.resume_at == _SEVEN_RESET + gate.RESUME_MARGIN_SECONDS

    def test_a_cron_tick_that_trips_the_ceiling_also_gets_the_directive(
        self, tmp_path: Path
    ) -> None:
        handler = _handler(tmp_path, snapshot=_snapshot(five=95.0))
        result = _run(handler, tmp_path, _input(CANONICAL_CRON_PROMPT))
        assert result.decision == Decision.ALLOW
        assert "CronCreate" in "\n".join(result.context)


class TestWhilePaused:
    def test_an_ordinary_prompt_is_blocked_before_the_model(self, tmp_path: Path) -> None:
        _record(tmp_path)
        handler = _handler(tmp_path, snapshot=_snapshot(five=91.0))
        result = _run(handler, tmp_path, _input("please do the next thing"))
        assert result.decision == Decision.DENY
        assert result.reason is not None
        assert "paused" in result.reason.lower()

    def test_a_failsafe_cron_tick_is_blocked(self, tmp_path: Path) -> None:
        _record(tmp_path)
        handler = _handler(tmp_path, snapshot=_snapshot(five=91.0))
        assert _run(handler, tmp_path, _input(CANONICAL_CRON_PROMPT)).decision == Decision.DENY

    def test_a_declared_job_tick_is_blocked(self, tmp_path: Path) -> None:
        _record(tmp_path)
        handler = _handler(tmp_path, snapshot=_snapshot(five=91.0))
        assert _run(handler, tmp_path, _input("[tick:job:x]\nwork")).decision == Decision.DENY

    def test_the_block_reason_names_the_resume_time(self, tmp_path: Path) -> None:
        _record(tmp_path, resume_at=_NOW + 3600)
        handler = _handler(tmp_path, snapshot=_snapshot(five=91.0))
        result = _run(handler, tmp_path, _input())
        schedule = gate.resume_schedule(_NOW + 3600, tz=UTC)
        assert result.reason is not None
        assert schedule.hhmm in result.reason

    def test_another_session_is_not_blocked(self, tmp_path: Path) -> None:
        _record(tmp_path, session="someone-else")
        handler = _handler(tmp_path, snapshot=None)
        assert _run(handler, tmp_path, _input()).decision == Decision.ALLOW

    def test_an_expired_record_no_longer_blocks(self, tmp_path: Path) -> None:
        _record(tmp_path, resume_at=_NOW - 7200)
        handler = _handler(tmp_path, snapshot=None)
        assert _run(handler, tmp_path, _input()).decision == Decision.ALLOW


class TestResume:
    """Task 4.6: the resume cron's tick re-reads usage."""

    def test_below_the_ceiling_lifts_the_pause(self, tmp_path: Path) -> None:
        _record(tmp_path)
        handler = _handler(tmp_path, snapshot=_snapshot(five=10.0))
        result = _run(handler, tmp_path, _input(gate.USAGE_RESUME_PROMPT))
        assert result.decision == Decision.ALLOW
        assert read_usage_pause(tmp_path, _SESSION, now=_NOW) is None
        text = "\n".join(result.context)
        assert "PAUSE LIFTED" in text
        assert "CronList" in text
        assert "continue" in text.lower()

    def test_a_window_past_its_reset_reads_as_absent_so_the_pause_lifts(
        self, tmp_path: Path
    ) -> None:
        _record(tmp_path)
        handler = _handler(tmp_path, snapshot=None)
        result = _run(handler, tmp_path, _input(gate.USAGE_RESUME_PROMPT))
        assert result.decision == Decision.ALLOW
        assert read_usage_pause(tmp_path, _SESSION, now=_NOW) is None
        assert "PAUSE LIFTED" in "\n".join(result.context)

    def test_still_over_refreshes_the_pause_and_asks_for_the_next_resume_cron(
        self, tmp_path: Path
    ) -> None:
        _record(tmp_path, resume_at=_NOW + 10)
        handler = _handler(tmp_path, snapshot=_snapshot(five=30.0, seven=85.0))
        result = _run(handler, tmp_path, _input(gate.USAGE_RESUME_PROMPT))
        assert result.decision == Decision.ALLOW
        pause = read_usage_pause(tmp_path, _SESSION, now=_NOW)
        assert pause is not None
        assert pause.resume_at == _SEVEN_RESET + gate.RESUME_MARGIN_SECONDS
        text = "\n".join(result.context)
        assert "STILL OVER" in text
        assert "[tick:usage-resume]" in text

    def test_a_resume_tick_with_no_record_still_lifts_when_under(self, tmp_path: Path) -> None:
        handler = _handler(tmp_path, snapshot=_snapshot(five=10.0))
        result = _run(handler, tmp_path, _input(gate.USAGE_RESUME_PROMPT))
        assert result.decision == Decision.ALLOW
        assert "PAUSE LIFTED" in "\n".join(result.context)

    def test_a_resume_tick_with_no_ceiling_configured_lifts(self, tmp_path: Path) -> None:
        _record(tmp_path)
        handler = _handler(tmp_path, config=_config(None), snapshot=_snapshot(five=99.0))
        result = _run(handler, tmp_path, _input(gate.USAGE_RESUME_PROMPT))
        assert "PAUSE LIFTED" in "\n".join(result.context)
        assert read_usage_pause(tmp_path, _SESSION, now=_NOW) is None

    def test_the_lift_directive_carries_the_declared_jobs(self, tmp_path: Path) -> None:
        job = PersistentCronConfig(
            id="issue-sdlc", schedule="*/20 * * * *", prompt="Run the issue loop."
        )
        handler = _handler(tmp_path, config=_config(jobs=[job]), snapshot=_snapshot(five=10.0))
        result = _run(handler, tmp_path, _input(gate.USAGE_RESUME_PROMPT))
        text = "\n".join(result.context)
        assert "issue-sdlc" in text
        assert "*/20 * * * *" in text
        assert "[tick:job:issue-sdlc]" in text

    def test_the_lift_directive_carries_the_failsafe_cron_when_none_is_declared(
        self, tmp_path: Path
    ) -> None:
        handler = _handler(tmp_path, snapshot=_snapshot(five=10.0))
        result = _run(handler, tmp_path, _input(gate.USAGE_RESUME_PROMPT))
        assert "[tick:failsafe]" in "\n".join(result.context)

    def test_a_failed_clear_does_not_claim_a_lift(self, tmp_path: Path) -> None:
        _record(tmp_path)
        handler = _handler(tmp_path, snapshot=_snapshot(five=10.0))
        with patch(
            "claude_code_hooks_daemon.utils.usage_pause_gate.clear_usage_pause",
            side_effect=OSError("denied"),
        ):
            result = _run(handler, tmp_path, _input(gate.USAGE_RESUME_PROMPT))
        assert result.decision == Decision.ALLOW
        text = "\n".join(result.context)
        assert "LIFTED" not in text
        assert "NOT lifted" in text

    def test_a_window_resetting_inside_the_lead_lifts_instead_of_pausing_again(
        self, tmp_path: Path
    ) -> None:
        _record(tmp_path)
        near = UsageSnapshot(five_hour=UsageWindow(95.0, int(_NOW + 30), _NOW), seven_day=None)
        handler = _handler(tmp_path, snapshot=near)
        result = _run(handler, tmp_path, _input(gate.USAGE_RESUME_PROMPT))
        assert "PAUSE LIFTED" in "\n".join(result.context)
        assert read_usage_pause(tmp_path, _SESSION, now=_NOW) is None


class TestHeldPromptReResolvesTheCeiling:
    """Plan 00479 C2(a): a held prompt re-checks the ceiling, so the owner is never
    locked out by a stale record."""

    def test_a_host_that_no_longer_has_a_ceiling_lifts_the_pause(self, tmp_path: Path) -> None:
        _record(tmp_path)
        handler = _handler(tmp_path, config=_config(None), snapshot=_snapshot(five=99.0))
        result = _run(handler, tmp_path, _input("an owner prompt"))
        assert result.decision == Decision.ALLOW
        assert "PAUSE LIFTED" in "\n".join(result.context)
        assert read_usage_pause(tmp_path, _SESSION, now=_NOW) is None

    def test_usage_below_the_ceiling_lifts_the_pause(self, tmp_path: Path) -> None:
        _record(tmp_path)
        handler = _handler(tmp_path, snapshot=_snapshot(five=5.0))
        result = _run(handler, tmp_path, _input("an owner prompt"))
        assert result.decision == Decision.ALLOW
        assert read_usage_pause(tmp_path, _SESSION, now=_NOW) is None

    def test_a_window_past_its_reset_reads_absent_and_lifts_the_pause(self, tmp_path: Path) -> None:
        _record(tmp_path)
        handler = _handler(tmp_path, snapshot=None)
        result = _run(handler, tmp_path, _input("an owner prompt"))
        assert result.decision == Decision.ALLOW
        assert read_usage_pause(tmp_path, _SESSION, now=_NOW) is None

    def test_still_over_holds_the_prompt(self, tmp_path: Path) -> None:
        _record(tmp_path)
        handler = _handler(tmp_path, snapshot=_snapshot(five=91.0))
        assert _run(handler, tmp_path, _input("an owner prompt")).decision == Decision.DENY
        assert read_usage_pause(tmp_path, _SESSION, now=_NOW) is not None

    def test_a_failed_clear_on_the_hold_path_does_not_claim_a_lift(self, tmp_path: Path) -> None:
        _record(tmp_path)
        handler = _handler(tmp_path, config=_config(None), snapshot=None)
        with patch(
            "claude_code_hooks_daemon.utils.usage_pause_gate.clear_usage_pause",
            side_effect=OSError("denied"),
        ):
            result = _run(handler, tmp_path, _input("an owner prompt"))
        text = "\n".join(result.context)
        assert "LIFTED" not in text
        assert "NOT lifted" in text


class TestNoSessionId:
    """Plan 00479 minor 1: no session id never pauses and never holds."""

    def test_never_pauses(self, tmp_path: Path) -> None:
        handler = _handler(tmp_path, snapshot=_snapshot(five=99.0))
        hook_input = _input()
        del hook_input["session_id"]
        result = _run(handler, tmp_path, hook_input)
        assert result.decision == Decision.ALLOW
        assert not result.context
        assert list(tmp_path.rglob("*.usage-paused")) == []

    def test_never_holds(self, tmp_path: Path) -> None:
        _record(tmp_path, session="unknown")
        handler = _handler(tmp_path, snapshot=_snapshot(five=99.0))
        hook_input = _input()
        del hook_input["session_id"]
        assert _run(handler, tmp_path, hook_input).decision == Decision.ALLOW


class TestEntryNearReset:
    def test_a_reset_inside_the_lead_is_not_worth_pausing_for(self, tmp_path: Path) -> None:
        near = UsageSnapshot(five_hour=UsageWindow(95.0, int(_NOW + 30), _NOW), seven_day=None)
        handler = _handler(tmp_path, snapshot=near)
        result = _run(handler, tmp_path, _input())
        assert result.decision == Decision.ALLOW
        assert not result.context
        assert read_usage_pause(tmp_path, _SESSION, now=_NOW) is None


class TestOwnerEscapeIsDocumented:
    """Plan 00479 C2(c): the rule says what actually lifts a pause."""

    def test_the_rule_names_the_cli_and_not_a_config_edit(self) -> None:
        rule = UsagePauseGateHandler().get_rules()[0]
        assert "usage-pause clear" in rule.verbose
        assert "restart the daemon" not in rule.verbose

    def test_the_hold_reason_names_the_cli(self, tmp_path: Path) -> None:
        _record(tmp_path)
        handler = _handler(tmp_path, snapshot=_snapshot(five=91.0))
        result = _run(handler, tmp_path, _input("an owner prompt"))
        assert result.reason is not None
        assert "usage-pause clear" in result.reason


class TestRules:
    def test_the_block_has_a_rule_for_explain_rule(self) -> None:
        rules = UsagePauseGateHandler().get_rules()
        assert [rule.rule_id for rule in rules] == ["R-USAGE-PAUSE-PROMPT"]

    def test_acceptance_tests_are_declared(self) -> None:
        assert UsagePauseGateHandler().get_acceptance_tests()

    def test_guidance_is_resident(self) -> None:
        text = UsagePauseGateHandler().get_claude_md()
        assert text is not None
        assert "usage_pause_gate" in text
