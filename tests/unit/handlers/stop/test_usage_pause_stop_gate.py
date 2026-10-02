"""Tests for UsagePauseStopGateHandler (Plan 00479 Task 4.3).

A paused session may stop only once its ``session_crons`` holds exactly ONE cron,
the usage-resume cron, and that cron's schedule really fires around the resume
time. Otherwise the directive is repeated, as ``cron_stop_enforcer`` does for
declared crons. The gate also ENTERS the pause (review M3) and reads the record
once per Stop (review minor 6).
"""

from __future__ import annotations

from datetime import UTC
from pathlib import Path
from typing import Any
from unittest.mock import patch

from claude_code_hooks_daemon.config.models import Config, HostConfig, UsageCeilingConfig
from claude_code_hooks_daemon.constants import HandlerID, Priority
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.core.usage_snapshot import UsageSnapshot, UsageWindow
from claude_code_hooks_daemon.handlers.stop.usage_pause_stop_gate import (
    UsagePauseStopGateHandler,
)
from claude_code_hooks_daemon.utils.usage_pause import (
    WINDOW_FIVE_HOUR,
    UsagePause,
    read_usage_pause,
    write_usage_pause,
)
from claude_code_hooks_daemon.utils.usage_pause_gate import (
    USAGE_RESUME_PROMPT,
    PauseEnvironment,
    resume_schedule,
)

_SESSION = "sess-1"
_NOW = 1_790_000_000.0  # fixed clock; every record is relative to it


def _env(
    *, snapshot: UsageSnapshot | None = None, config: Config | None = None
) -> PauseEnvironment:
    return PauseEnvironment(
        clock=lambda: _NOW,
        config_loader=lambda: config if config is not None else Config(),
        usage_loader=lambda _now: snapshot,
        tz=UTC,
    )


def _record(tmp_path: Path, *, session: str = _SESSION, resume_in: float = 3600.0) -> UsagePause:
    pause = UsagePause(
        session_id=session,
        paused_at=_NOW - 60,
        resume_at=_NOW + resume_in,
        window=WINDOW_FIVE_HOUR,
        used_percentage=91.0,
        ceiling=80.0,
        reason="five_hour window at 91% (ceiling 80%)",
    )
    write_usage_pause(tmp_path, pause)
    return pause


def _resume_cron(pause: UsagePause, prompt: str = USAGE_RESUME_PROMPT) -> dict[str, Any]:
    return {
        "id": "c1",
        "schedule": resume_schedule(pause.resume_at, tz=UTC).cron,
        "recurring": False,
        "prompt": prompt,
    }


def _cron(prompt: str, cron_id: str = "c2", schedule: str = "47 * * * *") -> dict[str, Any]:
    return {"id": cron_id, "schedule": schedule, "recurring": False, "prompt": prompt}


def _stop(
    crons: list[dict[str, Any]] | None, *, active: bool = False, session: str = _SESSION
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "hook_event_name": "Stop",
        "session_id": session,
        "stop_hook_active": active,
        "hooks_daemon_hostname": "runner",
    }
    if crons is not None:
        payload["session_crons"] = crons
    return payload


def _decide(tmp_path: Path, hook_input: dict[str, Any], env: PauseEnvironment | None = None) -> Any:
    handler = UsagePauseStopGateHandler()
    handler._env = env or _env()
    with patch.object(ProjectContext, "daemon_untracked_dir", return_value=tmp_path):
        if not handler.matches(hook_input):
            return None
        return handler.handle(hook_input)


class TestInit:
    def test_identity_and_priority(self) -> None:
        handler = UsagePauseStopGateHandler()
        assert handler.name == HandlerID.USAGE_PAUSE_STOP_GATE.display_name
        assert handler.priority == Priority.USAGE_PAUSE_STOP_GATE

    def test_runs_before_the_terminal_catch_all_and_does_not_shadow_it(self) -> None:
        handler = UsagePauseStopGateHandler()
        assert handler.terminal is False
        assert handler.priority < Priority.CRON_STOP_ENFORCER


class TestPaused:
    def test_exactly_the_resume_cron_allows_the_stop(self, tmp_path: Path) -> None:
        pause = _record(tmp_path)
        result = _decide(tmp_path, _stop([_resume_cron(pause)]))
        assert result is not None
        assert result.decision == Decision.ALLOW

    def test_a_truncated_resume_prompt_still_counts(self, tmp_path: Path) -> None:
        pause = _record(tmp_path)
        prompt = USAGE_RESUME_PROMPT + " ... [+1200 chars]"
        result = _decide(tmp_path, _stop([_resume_cron(pause, prompt)]))
        assert result is not None
        assert result.decision == Decision.ALLOW

    def test_no_crons_at_all_is_refused(self, tmp_path: Path) -> None:
        _record(tmp_path)
        result = _decide(tmp_path, _stop([]))
        assert result.decision == Decision.DENY
        assert "0 crons" in result.reason
        assert "CronCreate" in result.reason

    def test_extra_crons_alongside_the_resume_cron_are_refused(self, tmp_path: Path) -> None:
        pause = _record(tmp_path)
        crons = [_resume_cron(pause), _cron("[tick:failsafe]\nx")]
        result = _decide(tmp_path, _stop(crons))
        assert result.decision == Decision.DENY
        assert "2 crons" in result.reason
        assert "CronDelete" in result.reason

    def test_one_cron_that_is_not_the_resume_cron_is_refused(self, tmp_path: Path) -> None:
        _record(tmp_path)
        result = _decide(tmp_path, _stop([_cron("[tick:failsafe]\nx")]))
        assert result.decision == Decision.DENY
        assert "1 cron," in result.reason

    def test_two_resume_crons_are_refused(self, tmp_path: Path) -> None:
        pause = _record(tmp_path)
        crons = [_resume_cron(pause), {**_resume_cron(pause), "id": "c2"}]
        assert _decide(tmp_path, _stop(crons)).decision == Decision.DENY

    def test_absent_session_crons_is_no_information_and_allows(self, tmp_path: Path) -> None:
        _record(tmp_path)
        result = _decide(tmp_path, _stop(None))
        assert result.decision == Decision.ALLOW

    def test_re_entry_allows_so_the_session_is_never_trapped(
        self, tmp_path: Path, caplog: Any
    ) -> None:
        _record(tmp_path)
        with caplog.at_level("WARNING"):
            result = _decide(tmp_path, _stop([], active=True))
        assert result.decision == Decision.ALLOW
        assert "usage pause" in caplog.text.lower()

    def test_the_deny_names_the_resume_cron_expression(self, tmp_path: Path) -> None:
        _record(tmp_path)
        result = _decide(tmp_path, _stop([]))
        assert "recurring: false" in result.reason
        assert "[tick:usage-resume]" in result.reason


class TestResumeCronScheduleIsVerified:
    """Review M2: the one cron left must actually fire in (now, resume_at + 1 day]."""

    def test_a_stale_pinned_minute_is_refused_and_says_why(self, tmp_path: Path) -> None:
        pause = _record(tmp_path)
        stale = resume_schedule(_NOW - 7200, tz=UTC).cron  # that minute fires next year
        cron = {**_resume_cron(pause), "schedule": stale}
        result = _decide(tmp_path, _stop([cron]))
        assert result.decision == Decision.DENY
        assert "schedule" in result.reason.lower()
        assert "1 cron," in result.reason

    def test_a_recurring_expression_is_refused(self, tmp_path: Path) -> None:
        pause = _record(tmp_path)
        cron = {**_resume_cron(pause), "schedule": "*/5 * * * *"}
        assert _decide(tmp_path, _stop([cron])).decision == Decision.DENY

    def test_a_cron_far_after_the_resume_is_refused(self, tmp_path: Path) -> None:
        pause = _record(tmp_path)
        cron = {**_resume_cron(pause), "schedule": resume_schedule(_NOW + 3 * 86400, tz=UTC).cron}
        assert _decide(tmp_path, _stop([cron])).decision == Decision.DENY

    def test_a_zone_mismatch_is_refused(self, tmp_path: Path) -> None:
        from datetime import timedelta, timezone

        pause = _record(tmp_path)
        wrong_zone = resume_schedule(pause.resume_at, tz=timezone(timedelta(hours=-10))).cron
        cron = {**_resume_cron(pause), "schedule": wrong_zone}
        assert _decide(tmp_path, _stop([cron])).decision == Decision.DENY

    def test_the_repeat_does_not_trap_on_re_entry(self, tmp_path: Path) -> None:
        pause = _record(tmp_path)
        cron = {**_resume_cron(pause), "schedule": "*/5 * * * *"}
        assert _decide(tmp_path, _stop([cron], active=True)).decision == Decision.ALLOW

    def test_a_resume_that_is_now_imminent_lifts_instead_of_repeating(self, tmp_path: Path) -> None:
        """The cron minute has passed and the window is about to reset: no pointless loop."""
        _record(tmp_path, resume_in=120.0)
        result = _decide(tmp_path, _stop([]))
        assert result.decision == Decision.ALLOW
        assert read_usage_pause(tmp_path, _SESSION, now=_NOW) is None


class TestEntryFromTheStopGate:
    """Review M3: the Stop gate enters the pause too and re-delivers the directive."""

    def _over(self, five: float = 95.0) -> tuple[Config, UsageSnapshot]:
        config = Config(
            hosts={"runner": HostConfig(usage_ceiling=UsageCeilingConfig(max_used_percent=80))}
        )
        return config, UsageSnapshot(
            five_hour=UsageWindow(five, int(_NOW + 3 * 3600), _NOW), seven_day=None
        )

    def test_crossing_the_ceiling_pauses_and_delivers_the_directive(self, tmp_path: Path) -> None:
        config, snapshot = self._over()
        result = _decide(tmp_path, _stop([]), _env(snapshot=snapshot, config=config))
        assert result.decision == Decision.DENY
        assert "USAGE CEILING REACHED" in result.reason
        assert "CronCreate" in result.reason
        assert read_usage_pause(tmp_path, _SESSION, now=_NOW) is not None

    def test_below_the_ceiling_it_stays_inert(self, tmp_path: Path) -> None:
        config, snapshot = self._over(five=10.0)
        assert _decide(tmp_path, _stop([]), _env(snapshot=snapshot, config=config)) is None

    def test_no_ceiling_for_the_host_stays_inert(self, tmp_path: Path) -> None:
        _, snapshot = self._over()
        assert _decide(tmp_path, _stop([]), _env(snapshot=snapshot)) is None

    def test_entry_denies_even_on_re_entry_because_the_directive_was_never_seen(
        self, tmp_path: Path
    ) -> None:
        config, snapshot = self._over()
        result = _decide(tmp_path, _stop([], active=True), _env(snapshot=snapshot, config=config))
        assert result.decision == Decision.DENY

    def test_no_session_id_never_pauses(self, tmp_path: Path) -> None:
        config, snapshot = self._over()
        hook = _stop([])
        hook["session_id"] = ""
        assert _decide(tmp_path, hook, _env(snapshot=snapshot, config=config)) is None


class TestReadsTheRecordOncePerStop:
    def test_one_read_across_matches_and_handle(self, tmp_path: Path) -> None:
        pause = _record(tmp_path)
        handler = UsagePauseStopGateHandler()
        handler._env = _env()
        hook = _stop([_resume_cron(pause)])
        with (
            patch.object(ProjectContext, "daemon_untracked_dir", return_value=tmp_path),
            patch(
                "claude_code_hooks_daemon.utils.usage_pause_gate.read_usage_pause",
                wraps=read_usage_pause,
            ) as reader,
        ):
            assert handler.matches(hook) is True
            assert handler.handle(hook).decision == Decision.ALLOW
        assert reader.call_count == 1


class TestNotPaused:
    def test_does_not_match(self, tmp_path: Path) -> None:
        assert _decide(tmp_path, _stop([])) is None

    def test_other_session_does_not_match(self, tmp_path: Path) -> None:
        _record(tmp_path, session="someone-else")
        assert _decide(tmp_path, _stop([])) is None

    def test_no_project_context_fails_open(self) -> None:
        handler = UsagePauseStopGateHandler()
        handler._env = _env()
        with patch.object(ProjectContext, "daemon_untracked_dir", side_effect=RuntimeError("x")):
            assert handler.matches(_stop([])) is False

    def test_a_read_error_fails_open(self, tmp_path: Path) -> None:
        _record(tmp_path)
        handler = UsagePauseStopGateHandler()
        handler._env = _env()
        with (
            patch.object(ProjectContext, "daemon_untracked_dir", return_value=tmp_path),
            patch.object(Path, "read_text", side_effect=PermissionError("denied")),
        ):
            assert handler.matches(_stop([])) is False


class TestMetadata:
    def test_rule(self) -> None:
        assert [r.rule_id for r in UsagePauseStopGateHandler().get_rules()] == [
            "R-USAGE-PAUSE-STOP"
        ]

    def test_acceptance_tests_declare_what_the_harness_cannot_drive(self) -> None:
        tests = UsagePauseStopGateHandler().get_acceptance_tests()
        denies = [t for t in tests if t.expected_decision == Decision.DENY]
        allows = [t for t in tests if t.expected_decision == Decision.ALLOW]
        assert denies and allows
        assert all(t.harness_cannot_produce for t in denies)
        assert not any(t.harness_cannot_produce for t in allows)

    def test_guidance_is_resident(self) -> None:
        text = UsagePauseStopGateHandler().get_claude_md()
        assert text is not None
        assert "usage_pause_stop_gate" in text
