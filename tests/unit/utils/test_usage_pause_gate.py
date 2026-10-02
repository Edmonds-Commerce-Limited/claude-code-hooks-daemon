"""Plan 00479 Phase 4: the shared usage-pause logic every gate handler reads.

One module answers "is this session paused?", "which windows are over the
ceiling?" and "when does the resume cron fire?", so the UserPromptSubmit,
PreToolUse and Stop gates and every handler that stands down while paused
cannot disagree.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.config.models import Config, HostConfig, UsageCeilingConfig
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.core.usage_snapshot import UsageSnapshot, UsageWindow
from claude_code_hooks_daemon.utils import usage_pause_gate as gate
from claude_code_hooks_daemon.utils.cron_tick import TickKind, classify_tick
from claude_code_hooks_daemon.utils.host_usage_ceiling import HostUsageCeiling
from claude_code_hooks_daemon.utils.usage_pause import (
    WINDOW_FIVE_HOUR,
    WINDOW_SEVEN_DAY,
    UsagePause,
    read_usage_pause,
    write_usage_pause,
)

_SESSION = "sess-1"
_NOW = 1_790_000_000.0
_FIVE_RESET = int(_NOW + 3 * 3600)
_SEVEN_RESET = int(_NOW + 3 * 86400)


def _window(pct: float, resets_at: int) -> UsageWindow:
    return UsageWindow(used_percentage=pct, resets_at=resets_at, observed_at=_NOW)


def _snapshot(five: float | None = None, seven: float | None = None) -> UsageSnapshot:
    return UsageSnapshot(
        five_hour=_window(five, _FIVE_RESET) if five is not None else None,
        seven_day=_window(seven, _SEVEN_RESET) if seven is not None else None,
    )


def _ceiling(five: float | None = 80.0, seven: float | None = 80.0) -> HostUsageCeiling:
    return HostUsageCeiling(five_hour=five, seven_day=seven, matched_labels=("h",))


class TestFindBreaches:
    def test_a_window_at_the_ceiling_is_a_breach(self) -> None:
        breaches = gate.find_breaches(_snapshot(five=80.0), _ceiling())
        assert [b.window for b in breaches] == [WINDOW_FIVE_HOUR]
        assert breaches[0].used_percentage == 80.0
        assert breaches[0].ceiling == 80.0
        assert breaches[0].resets_at == _FIVE_RESET

    def test_a_window_below_the_ceiling_is_not(self) -> None:
        assert gate.find_breaches(_snapshot(five=79.9, seven=10.0), _ceiling()) == []

    def test_both_windows_can_breach(self) -> None:
        breaches = gate.find_breaches(_snapshot(five=95.0, seven=85.0), _ceiling())
        assert [b.window for b in breaches] == [WINDOW_FIVE_HOUR, WINDOW_SEVEN_DAY]

    def test_a_window_without_a_ceiling_never_breaches(self) -> None:
        assert gate.find_breaches(_snapshot(five=99.0), _ceiling(five=None)) == []

    def test_no_snapshot_never_breaches(self) -> None:
        assert gate.find_breaches(None, _ceiling()) == []

    def test_an_absent_window_never_breaches(self) -> None:
        assert gate.find_breaches(_snapshot(five=None, seven=None), _ceiling()) == []


class TestSessionCeiling:
    def _config(self) -> Config:
        return Config(
            hosts={"runner": HostConfig(usage_ceiling=UsageCeilingConfig(max_used_percent=80))}
        )

    def test_a_matching_host_gets_its_ceiling(self) -> None:
        ceiling = gate.session_ceiling(self._config(), {"hooks_daemon_hostname": "runner"})
        assert ceiling.five_hour == 80.0
        assert ceiling.seven_day == 80.0

    def test_an_unknown_host_has_no_ceiling(self) -> None:
        ceiling = gate.session_ceiling(self._config(), {"hooks_daemon_hostname": "elsewhere"})
        assert ceiling.five_hour is None
        assert ceiling.seven_day is None

    def test_no_hosts_configured_has_no_ceiling(self) -> None:
        ceiling = gate.session_ceiling(Config(), {"hooks_daemon_hostname": "runner"})
        assert (ceiling.five_hour, ceiling.seven_day) == (None, None)


class TestResumeAt:
    def test_is_the_latest_reset_among_breaches_plus_the_margin(self) -> None:
        breaches = gate.find_breaches(_snapshot(five=95.0, seven=85.0), _ceiling())
        assert gate.resume_at_for(breaches) == _SEVEN_RESET + gate.RESUME_MARGIN_SECONDS

    def test_a_single_breach(self) -> None:
        breaches = gate.find_breaches(_snapshot(five=95.0), _ceiling())
        assert gate.resume_at_for(breaches) == _FIVE_RESET + gate.RESUME_MARGIN_SECONDS

    def test_no_breach_is_an_error(self) -> None:
        with pytest.raises(ValueError):
            gate.resume_at_for([])

    def test_the_margin_is_two_minutes(self) -> None:
        assert gate.RESUME_MARGIN_SECONDS == 120.0


class TestBuildPause:
    def test_names_the_window_that_sets_the_resume_time(self) -> None:
        breaches = gate.find_breaches(_snapshot(five=95.0, seven=85.0), _ceiling())
        pause = gate.build_pause(_SESSION, breaches, now=_NOW)
        assert pause.window == WINDOW_SEVEN_DAY
        assert pause.used_percentage == 85.0
        assert pause.ceiling == 80.0
        assert pause.resume_at == _SEVEN_RESET + gate.RESUME_MARGIN_SECONDS
        assert pause.paused_at == _NOW
        assert pause.session_id == _SESSION
        assert "five_hour" in pause.reason and "seven_day" in pause.reason

    def test_refuses_no_breach(self) -> None:
        with pytest.raises(ValueError):
            gate.build_pause(_SESSION, [], now=_NOW)


class TestResumeSchedule:
    def test_one_shot_cron_pinned_to_the_minute_in_the_given_zone(self) -> None:
        resume = datetime(2026, 10, 2, 15, 2, 0, tzinfo=UTC).timestamp()
        schedule = gate.resume_schedule(resume, tz=UTC)
        assert schedule.cron == "2 15 2 10 *"
        assert schedule.local_text == "2026-10-02 15:02 UTC"
        assert schedule.utc_text == "2026-10-02 15:02 UTC"

    def test_a_partial_minute_rounds_up_so_it_never_fires_early(self) -> None:
        resume = datetime(2026, 10, 2, 15, 2, 1, tzinfo=UTC).timestamp()
        assert gate.resume_schedule(resume, tz=UTC).cron == "3 15 2 10 *"

    def test_the_cron_is_expressed_in_local_time_and_utc_is_stated_beside_it(self) -> None:
        zone = timezone(timedelta(hours=10), "AEST")
        resume = datetime(2026, 10, 2, 23, 30, 0, tzinfo=UTC).timestamp()
        schedule = gate.resume_schedule(resume, tz=zone)
        assert schedule.cron == "30 9 3 10 *"  # 09:30 on 3 October, local
        assert schedule.local_text == "2026-10-03 09:30 AEST"
        assert schedule.utc_text == "2026-10-02 23:30 UTC"

    def test_the_hhmm_for_the_status_line(self) -> None:
        zone = timezone(timedelta(hours=10), "AEST")
        resume = datetime(2026, 10, 2, 23, 30, 0, tzinfo=UTC).timestamp()
        assert gate.resume_schedule(resume, tz=zone).hhmm == "09:30"


class TestResumePrompt:
    def test_the_prompt_is_recognised_as_the_usage_resume_tick(self) -> None:
        tick = classify_tick(gate.USAGE_RESUME_PROMPT)
        assert tick is not None
        assert tick.kind is TickKind.USAGE_RESUME

    def test_the_sentinel_is_the_first_line(self) -> None:
        assert gate.USAGE_RESUME_PROMPT.splitlines()[0] == "[tick:usage-resume]"

    def test_is_resume_tick_reads_the_prompt(self) -> None:
        assert gate.is_resume_tick({"prompt": gate.USAGE_RESUME_PROMPT}) is True
        assert gate.is_resume_tick({"prompt": "[tick:failsafe]\nx"}) is False
        assert gate.is_resume_tick({"prompt": 3}) is False
        assert gate.is_resume_tick({}) is False


class TestPausedPredicate:
    def _record(self, tmp_path: Path, *, resume_at: float = _NOW + 3600) -> None:
        write_usage_pause(
            tmp_path,
            UsagePause(
                session_id=_SESSION,
                paused_at=min(_NOW - 10, resume_at - 3600),
                resume_at=resume_at,
                window=WINDOW_FIVE_HOUR,
                used_percentage=91.0,
                ceiling=90.0,
                reason="five_hour window at 91% (ceiling 90%)",
            ),
        )

    def test_paused_while_a_live_record_exists(self, tmp_path: Path) -> None:
        self._record(tmp_path)
        with patch.object(ProjectContext, "daemon_untracked_dir", return_value=tmp_path):
            assert gate.is_usage_paused(_SESSION, now=_NOW) is True

    def test_other_session_is_not_paused(self, tmp_path: Path) -> None:
        self._record(tmp_path)
        with patch.object(ProjectContext, "daemon_untracked_dir", return_value=tmp_path):
            assert gate.is_usage_paused("other", now=_NOW) is False

    def test_an_expired_record_is_not_a_pause(self, tmp_path: Path) -> None:
        self._record(tmp_path, resume_at=_NOW - 7200)
        with patch.object(ProjectContext, "daemon_untracked_dir", return_value=tmp_path):
            assert gate.is_usage_paused(_SESSION, now=_NOW) is False

    def test_no_project_context_is_not_a_pause(self) -> None:
        with patch.object(ProjectContext, "daemon_untracked_dir", side_effect=RuntimeError("x")):
            assert gate.is_usage_paused(_SESSION, now=_NOW) is False

    def test_empty_session_is_not_a_pause(self, tmp_path: Path) -> None:
        with patch.object(ProjectContext, "daemon_untracked_dir", return_value=tmp_path):
            assert gate.is_usage_paused("", now=_NOW) is False

    def test_the_hook_input_form_reads_the_session_id(self, tmp_path: Path) -> None:
        self._record(tmp_path)
        with patch.object(ProjectContext, "daemon_untracked_dir", return_value=tmp_path):
            assert gate.hook_is_usage_paused({"session_id": _SESSION}, now=_NOW) is True
            assert gate.hook_is_usage_paused({}, now=_NOW) is False

    def test_active_pause_returns_the_record(self, tmp_path: Path) -> None:
        self._record(tmp_path)
        with patch.object(ProjectContext, "daemon_untracked_dir", return_value=tmp_path):
            pause = gate.active_usage_pause(_SESSION, now=_NOW)
        assert pause is not None
        assert pause.window == WINDOW_FIVE_HOUR
        assert read_usage_pause(tmp_path, _SESSION, now=_NOW) == pause


class TestDirectives:
    def _pause(self) -> UsagePause:
        return UsagePause(
            session_id=_SESSION,
            paused_at=_NOW,
            resume_at=float(_FIVE_RESET + 120),
            window=WINDOW_FIVE_HOUR,
            used_percentage=91.4,
            ceiling=90.0,
            reason="five_hour window at 91% (ceiling 90%)",
        )

    def test_entry_directive_names_window_percentage_ceiling_and_resume_time(self) -> None:
        text = gate.render_pause_directive(self._pause(), tz=UTC)
        assert "five_hour" in text
        assert "91%" in text  # rounded DOWN, as the status line does
        assert "90%" in text
        assert "UTC" in text

    def test_entry_directive_orders_the_cron_steps(self) -> None:
        text = gate.render_pause_directive(self._pause(), tz=UTC)
        assert text.index("CronList") < text.index("CronDelete") < text.index("CronCreate")
        assert "recurring: false" in text
        assert "[tick:usage-resume]" in text
        assert "STOPPING BECAUSE" in text

    def test_entry_directive_refuses_the_triggering_request(self) -> None:
        assert "Do NOT act on" in gate.render_pause_directive(self._pause(), tz=UTC)

    def test_entry_directive_embeds_the_exact_cron_expression(self) -> None:
        pause = self._pause()
        schedule = gate.resume_schedule(pause.resume_at, tz=UTC)
        assert schedule.cron in gate.render_pause_directive(pause, tz=UTC)

    def test_repeat_directive_states_what_is_wrong(self) -> None:
        text = gate.render_stop_directive(self._pause(), found=3, tz=UTC)
        assert "3 crons" in text
        assert "exactly ONE" in text

    def test_resume_directive_reestablishes_and_continues(self) -> None:
        text = gate.render_resume_lifted_directive()
        assert "CronList" in text
        assert "persistent_cron" in text or "declared" in text
        assert "continue" in text.lower()

    def test_still_over_directive_schedules_the_next_resume(self) -> None:
        text = gate.render_still_over_directive(self._pause(), tz=UTC)
        assert "still" in text.lower()
        assert "CronCreate" in text
        assert "[tick:usage-resume]" in text


class TestOnlyCronToolsAreAllowedWhilePaused:
    @pytest.mark.parametrize("tool", ["CronList", "CronDelete", "CronCreate"])
    def test_cron_tools_pass(self, tool: str) -> None:
        assert gate.tool_allowed_while_paused(tool) is True

    @pytest.mark.parametrize("tool", ["Bash", "Read", "Write", "Task", "ScheduleWakeup", "", None])
    def test_everything_else_is_refused(self, tool: str | None) -> None:
        assert gate.tool_allowed_while_paused(tool) is False


class TestToolSearchIsAllowed:
    """Plan 00479 C1: CronCreate/CronDelete/CronList are DEFERRED tools.

    ``CLAUDE/Plan/Completed/00293-tool-inventory-disable-and-token-savings/
    RESEARCH-context-fat.md:382`` lists them among the deferred built-ins whose schema
    loads only via ToolSearch, so a paused session that cannot call ToolSearch cannot
    call them either.
    """

    def test_tool_search_passes(self) -> None:
        assert gate.tool_allowed_while_paused("ToolSearch") is True

    def test_the_directives_tell_the_model_to_load_the_cron_tools(self) -> None:
        pause = UsagePause(
            session_id=_SESSION,
            paused_at=_NOW,
            resume_at=float(_FIVE_RESET + 120),
            window=WINDOW_FIVE_HOUR,
            used_percentage=91.0,
            ceiling=90.0,
            reason="r",
        )
        assert "ToolSearch" in gate.render_pause_directive(pause, tz=UTC)
        assert "ToolSearch" in gate.render_stop_directive(pause, found=0, tz=UTC)


class TestAnyReadErrorFailsOpen:
    """Plan 00479 M1."""

    @pytest.mark.parametrize("error", [PermissionError("x"), OSError("y"), ValueError("z")])
    def test_a_read_that_raises_is_not_a_pause(
        self, error: Exception, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        with (
            patch.object(ProjectContext, "daemon_untracked_dir", return_value=tmp_path),
            patch.object(gate, "read_usage_pause", side_effect=error),
            caplog.at_level("WARNING"),
        ):
            assert gate.is_usage_paused(_SESSION, now=_NOW) is False
            assert gate.hook_is_usage_paused({"session_id": _SESSION}, now=_NOW) is False
        assert "usage_pause_gate" in caplog.text

    def test_a_runtime_error_resolving_the_directory_is_not_a_pause(self) -> None:
        with patch.object(ProjectContext, "daemon_untracked_dir", side_effect=RuntimeError("x")):
            assert gate.is_usage_paused(_SESSION, now=_NOW) is False


class TestResumeLead:
    def test_a_resume_time_far_enough_away_is_worth_pausing_for(self) -> None:
        assert gate.resume_is_far_enough(_NOW + gate.MIN_RESUME_LEAD_SECONDS, now=_NOW) is True

    def test_a_resume_time_inside_the_lead_is_not(self) -> None:
        assert gate.resume_is_far_enough(_NOW + gate.MIN_RESUME_LEAD_SECONDS - 1, now=_NOW) is False

    def test_a_resume_time_already_past_is_not(self) -> None:
        assert gate.resume_is_far_enough(_NOW - 5, now=_NOW) is False


class TestScheduleVerification:
    """Plan 00479 M2: a pinned minute that has passed next matches a year later."""

    _RESUME = datetime(2026, 10, 2, 15, 2, 0, tzinfo=UTC).timestamp()
    _BEFORE = datetime(2026, 10, 2, 12, 0, 0, tzinfo=UTC).timestamp()

    def test_the_cron_built_for_the_resume_time_verifies(self) -> None:
        cron = gate.resume_schedule(self._RESUME, tz=UTC).cron
        assert gate.schedule_fires_in_window(cron, now=self._BEFORE, resume_at=self._RESUME, tz=UTC)

    def test_a_minute_that_has_passed_fires_next_year_and_fails(self) -> None:
        cron = gate.resume_schedule(self._RESUME, tz=UTC).cron
        late = self._RESUME + 60
        assert not gate.schedule_fires_in_window(cron, now=late, resume_at=self._RESUME, tz=UTC)

    def test_a_recurring_expression_is_not_the_pinned_one_shot(self) -> None:
        assert not gate.schedule_fires_in_window(
            "*/5 * * * *", now=self._BEFORE, resume_at=self._RESUME, tz=UTC
        )

    @pytest.mark.parametrize("cron", ["", "garbage", "1 2 3 4", "99 25 40 13 *", "2 15 30 2 *"])
    def test_unparseable_or_impossible_expressions_fail(self, cron: str) -> None:
        assert not gate.schedule_fires_in_window(
            cron, now=self._BEFORE, resume_at=self._RESUME, tz=UTC
        )

    def test_a_fire_up_to_a_day_after_the_resume_time_is_accepted(self) -> None:
        cron = gate.resume_schedule(self._RESUME + 86400, tz=UTC).cron
        assert gate.schedule_fires_in_window(cron, now=self._BEFORE, resume_at=self._RESUME, tz=UTC)

    def test_a_fire_more_than_a_day_after_the_resume_time_fails(self) -> None:
        cron = gate.resume_schedule(self._RESUME + 86400 + 120, tz=UTC).cron
        assert not gate.schedule_fires_in_window(
            cron, now=self._BEFORE, resume_at=self._RESUME, tz=UTC
        )

    def test_the_zone_is_part_of_the_check(self) -> None:
        # 05:02 on the 2nd in UTC-10 is already past in UTC, so UTC reads it a year on.
        zone = timezone(timedelta(hours=-10), "HST")
        cron = gate.resume_schedule(self._RESUME, tz=zone).cron
        assert gate.schedule_fires_in_window(
            cron, now=self._BEFORE, resume_at=self._RESUME, tz=zone
        )
        assert not gate.schedule_fires_in_window(
            cron, now=self._BEFORE, resume_at=self._RESUME, tz=UTC
        )


class TestTimeZoneIsStatedInTheDirective:
    def test_the_directive_names_the_zone_and_offset(self) -> None:
        zone = timezone(timedelta(hours=10), "AEST")
        pause = UsagePause(
            session_id=_SESSION,
            paused_at=_NOW,
            resume_at=float(_FIVE_RESET + 120),
            window=WINDOW_FIVE_HOUR,
            used_percentage=91.0,
            ceiling=90.0,
            reason="r",
        )
        text = gate.render_pause_directive(pause, tz=zone)
        assert "AEST" in text
        assert "+10:00" in text
        assert "date" in text  # tells the model to cross-check the session's own clock


class TestSharedFailsafeSchedule:
    def test_one_constant_serves_both_advisories(self) -> None:
        from claude_code_hooks_daemon.handlers.session_start import failsafe_cron_session_advisor
        from claude_code_hooks_daemon.utils.cron_enforcement import FAILSAFE_CRON_SCHEDULE_HINT

        assert FAILSAFE_CRON_SCHEDULE_HINT in "\n".join(failsafe_cron_session_advisor._GUIDANCE)
        assert FAILSAFE_CRON_SCHEDULE_HINT in gate.render_resume_lifted_directive(
            failsafe_prompt="[tick:failsafe]\nx"
        )


class TestStartPause:
    """The shared entry used by the prompt, tool and stop gates."""

    def _config(self) -> Config:
        return Config(
            hosts={"runner": HostConfig(usage_ceiling=UsageCeilingConfig(max_used_percent=80))}
        )

    def _env(self, snapshot: UsageSnapshot | None, now: float = _NOW) -> gate.PauseEnvironment:
        return gate.PauseEnvironment(
            clock=lambda: now,
            config_loader=self._config,
            usage_loader=lambda _now: snapshot,
            tz=UTC,
        )

    def _input(self, session: str = _SESSION) -> dict[str, Any]:
        return {"session_id": session, "hooks_daemon_hostname": "runner"}

    def test_enters_and_records(self, tmp_path: Path) -> None:
        with patch.object(ProjectContext, "daemon_untracked_dir", return_value=tmp_path):
            pause = gate.try_start_pause(self._input(), self._env(_snapshot(five=95.0)))
            assert pause is not None
            assert read_usage_pause(tmp_path, _SESSION, now=_NOW) == pause

    def test_no_session_id_never_pauses(self, tmp_path: Path) -> None:
        with patch.object(ProjectContext, "daemon_untracked_dir", return_value=tmp_path):
            assert gate.try_start_pause(self._input(""), self._env(_snapshot(five=95.0))) is None
            assert list(tmp_path.rglob("*.usage-paused")) == []

    def test_below_the_ceiling_never_pauses(self, tmp_path: Path) -> None:
        with patch.object(ProjectContext, "daemon_untracked_dir", return_value=tmp_path):
            assert gate.try_start_pause(self._input(), self._env(_snapshot(five=10.0))) is None

    def test_a_reset_inside_the_lead_never_pauses(self, tmp_path: Path) -> None:
        near = UsageSnapshot(five_hour=_window(95.0, int(_NOW + 30)), seven_day=None)
        with patch.object(ProjectContext, "daemon_untracked_dir", return_value=tmp_path):
            assert gate.try_start_pause(self._input(), self._env(near)) is None
            assert list(tmp_path.rglob("*.usage-paused")) == []

    def test_a_usage_loader_that_raises_oserror_fails_open(self, tmp_path: Path) -> None:
        def boom(_now: float) -> UsageSnapshot | None:
            raise OSError("disk")

        env = gate.PauseEnvironment(
            clock=lambda: _NOW, config_loader=self._config, usage_loader=boom, tz=UTC
        )
        with patch.object(ProjectContext, "daemon_untracked_dir", return_value=tmp_path):
            assert gate.try_start_pause(self._input(), env) is None

    def test_a_failed_write_fails_open(self, tmp_path: Path) -> None:
        with (
            patch.object(ProjectContext, "daemon_untracked_dir", return_value=tmp_path),
            patch.object(gate, "write_usage_pause", side_effect=OSError("full")),
        ):
            assert gate.try_start_pause(self._input(), self._env(_snapshot(five=95.0))) is None


class TestClearPause:
    def test_reports_success(self, tmp_path: Path) -> None:
        with patch.object(ProjectContext, "daemon_untracked_dir", return_value=tmp_path):
            assert gate.clear_pause(_SESSION) is True

    def test_reports_a_failed_removal(self, tmp_path: Path) -> None:
        with (
            patch.object(ProjectContext, "daemon_untracked_dir", return_value=tmp_path),
            patch.object(gate, "clear_usage_pause", side_effect=OSError("denied")),
        ):
            assert gate.clear_pause(_SESSION) is False

    def test_the_unrecorded_lift_note_does_not_claim_a_lift(self) -> None:
        text = gate.render_lift_not_recorded_note(expires_at=_NOW + 3600, tz=UTC)
        assert "NOT" in text
        assert "LIFTED" not in text
