"""Plan 00479 Phase 4: the shared usage-pause logic every gate handler reads.

One module answers "is this session paused?", "which windows are over the
ceiling?" and "when does the resume cron fire?", so the UserPromptSubmit,
PreToolUse and Stop gates and every handler that stands down while paused
cannot disagree.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.config.models import Config, HostConfig, UsageCeilingConfig
from claude_code_hooks_daemon.constants.tools import SUBAGENT_DISPATCH_TOOL_NAMES
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
    write_usage_override,
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


class TestResumeCron:
    """Round 4 R3-2: the resume cron names no clock time, so no time zone can misplace it."""

    def test_the_schedule_is_every_ten_minutes(self) -> None:
        assert gate.RESUME_CRON_SCHEDULE == "*/10 * * * *"

    def test_the_schedule_pins_no_hour_day_or_month(self) -> None:
        minute, hour, day, month, weekday = gate.RESUME_CRON_SCHEDULE.split()
        assert (hour, day, month, weekday) == ("*", "*", "*", "*")
        assert minute.startswith("*/")

    def test_zone_dependent_schedule_maths_is_gone(self) -> None:
        for name in ("resume_schedule", "schedule_fires_in_window", "ResumeSchedule"):
            assert not hasattr(gate, name), name
        assert not hasattr(gate.PauseEnvironment(), "tz")

    def test_resume_time_text_is_utc_whatever_the_host_zone(self) -> None:
        resume = datetime(2026, 10, 2, 23, 30, 0, tzinfo=UTC).timestamp()
        assert gate.resume_time_text(resume) == "2026-10-02 23:30 UTC"

    @pytest.mark.parametrize(
        ("schedule", "expected"),
        [
            ("*/10 * * * *", True),
            ("  */10  *  * * *  ", True),
            ("*/5 * * * *", False),
            ("2 15 2 10 *", False),
            ("", False),
        ],
    )
    def test_only_the_resume_schedule_is_the_resume_schedule(
        self, schedule: str, expected: bool
    ) -> None:
        assert gate.is_resume_schedule(schedule) is expected

    @pytest.mark.parametrize(("now", "due"), [(_NOW - 1, False), (_NOW, True), (_NOW + 600, True)])
    def test_a_resume_tick_is_due_at_and_after_the_resume_time(self, now: float, due: bool) -> None:
        pause = UsagePause(
            session_id=_SESSION,
            paused_at=_NOW - 60,
            resume_at=_NOW,
            window=WINDOW_FIVE_HOUR,
            used_percentage=91.0,
            ceiling=80.0,
            reason="r",
        )
        assert gate.resume_is_due(pause, now=now) is due


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
        text = gate.render_pause_directive(self._pause())
        assert "five_hour" in text
        assert "91%" in text  # rounded DOWN, as the status line does
        assert "90%" in text
        assert gate.resume_time_text(self._pause().resume_at) in text

    def test_entry_directive_orders_the_cron_steps(self) -> None:
        text = gate.render_pause_directive(self._pause())
        assert text.index("CronList") < text.index("CronDelete") < text.index("CronCreate")
        assert "recurring: true" in text
        assert "recurring: false" not in text
        assert "[tick:usage-resume]" in text
        assert "STOPPING BECAUSE" in text

    def test_entry_directive_refuses_the_triggering_request(self) -> None:
        assert "Do NOT act on" in gate.render_pause_directive(self._pause())

    def test_entry_directive_embeds_the_zone_free_cron_expression(self) -> None:
        text = gate.render_pause_directive(self._pause())
        assert f"`{gate.RESUME_CRON_SCHEDULE}`" in text
        assert "does not say" not in text  # no hedging about which zone CronCreate reads

    def test_repeat_directive_states_what_is_wrong(self) -> None:
        text = gate.render_stop_directive(self._pause(), found=3)
        assert "3 crons" in text
        assert "exactly ONE" in text

    def test_resume_directive_reestablishes_and_continues(self) -> None:
        text = gate.render_resume_lifted_directive()
        assert "CronList" in text
        assert "persistent_cron" in text or "declared" in text
        assert "continue" in text.lower()

    def test_lift_directive_deletes_the_recurring_resume_cron_first(self) -> None:
        """Round 4 R3-2: it fires every ten minutes, so it must not outlive the pause."""
        text = gate.render_resume_lifted_directive()
        assert "[tick:usage-resume]" in text
        assert "CronDelete" in text
        assert "one-shot" not in text
        assert text.index("CronDelete") < text.index("Re-establish")

    def test_still_over_directive_keeps_the_resume_cron_and_names_the_new_time(self) -> None:
        text = gate.render_still_over_directive(self._pause())
        assert "still" in text.lower()
        assert gate.resume_time_text(self._pause().resume_at) in text
        # The recurring resume cron is already in place: a second one would fire twice.
        assert "Do NOT create another" in text
        assert "[tick:usage-resume]" not in text  # no prompt to paste: nothing to create


class TestOnlyCronToolsAreAllowedWhilePaused:
    @pytest.mark.parametrize("tool", ["CronList", "CronDelete", "CronCreate"])
    def test_cron_tools_pass(self, tool: str) -> None:
        assert gate.tool_allowed_while_paused(tool) is True

    @pytest.mark.parametrize("tool", ["Bash", "Read", "Write", "ScheduleWakeup", "", None])
    def test_everything_else_is_refused(self, tool: str | None) -> None:
        assert gate.tool_allowed_while_paused(tool) is False


class TestNewSubagentsAreRefusedWhilePaused:
    """Round 4 R3-1: running subagents finish, but none may START while paused."""

    @pytest.mark.parametrize("tool", sorted(SUBAGENT_DISPATCH_TOOL_NAMES))
    def test_every_dispatch_tool_name_is_off_the_allow_list(self, tool: str) -> None:
        assert tool not in gate.PAUSE_ALLOWED_TOOLS
        assert gate.tool_allowed_while_paused(tool) is False

    @pytest.mark.parametrize("tool", ["SendMessage", "TaskStop"])
    def test_winding_up_running_subagents_is_allowed(self, tool: str) -> None:
        assert tool in gate.PAUSE_ALLOWED_TOOLS
        assert gate.tool_allowed_while_paused(tool) is True


class TestPauseDirectiveWindsUpSubagents:
    """Round 4 R3-1: the main agent winds subagents up; it does not rug-pull working ones."""

    def _text(self) -> str:
        return gate.render_pause_directive(_a_pause_for_directives())

    def test_no_new_subagents(self) -> None:
        assert "do not start new subagents" in self._text().lower()

    def test_running_ones_finish_and_may_be_asked_to_wrap_up(self) -> None:
        text = self._text()
        assert "let running subagents finish" in text.lower()
        assert "SendMessage" in text

    def test_idle_or_finished_teammates_are_stopped_but_working_ones_are_not_killed(self) -> None:
        text = self._text()
        assert "TaskStop" in text
        assert "idle or finished" in text
        assert "do not stop one that is still working" in text.lower()

    def test_the_still_over_directive_does_not_repeat_it(self) -> None:
        assert "Subagents:" not in gate.render_still_over_directive(_a_pause_for_directives())


def _a_pause_for_directives() -> UsagePause:
    return UsagePause(
        session_id=_SESSION,
        paused_at=_NOW,
        resume_at=float(_FIVE_RESET + 120),
        window=WINDOW_FIVE_HOUR,
        used_percentage=91.4,
        ceiling=90.0,
        reason="five_hour window at 91% (ceiling 90%)",
    )


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
        assert "ToolSearch" in gate.render_pause_directive(pause)
        assert "ToolSearch" in gate.render_stop_directive(pause, found=0)


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


class TestResumeTime:
    """Round 4 R3-5: no floor, no renewal. Ticks before ``resume_at`` are dropped for free."""

    def _breach_resetting_in(self, seconds: float) -> list[gate.UsageBreach]:
        window = _window(95.0, int(_NOW + seconds))
        return gate.find_breaches(UsageSnapshot(five_hour=window, seven_day=None), _ceiling())

    def test_a_reset_seconds_away_still_builds_a_pause_a_margin_ahead(self) -> None:
        pause = gate.build_pause(_SESSION, self._breach_resetting_in(5), now=_NOW)
        assert pause.resume_at == _NOW + 5 + gate.RESUME_MARGIN_SECONDS

    def test_a_distant_reset_is_not_moved(self) -> None:
        pause = gate.build_pause(_SESSION, self._breach_resetting_in(3 * 3600), now=_NOW)
        assert pause.resume_at == _FIVE_RESET + gate.RESUME_MARGIN_SECONDS

    def test_the_floor_and_renewal_are_gone(self) -> None:
        for name in ("refresh_resume", "renew_pause", "MAX_FIRE_AFTER_RESUME_SECONDS"):
            assert not hasattr(gate, name), name


def _a_pause() -> UsagePause:
    return UsagePause(
        session_id=_SESSION,
        paused_at=_NOW,
        resume_at=float(_FIVE_RESET + 120),
        window=WINDOW_FIVE_HOUR,
        used_percentage=91.0,
        ceiling=90.0,
        reason="r",
    )


class TestEveryToolTheDirectiveNamesIsAllowedWhilePaused:
    """Round 2 N1: a step the tool gate would halt strands the session with no cron."""

    def _tool_names_in(self, text: str) -> set[str]:
        import re

        from claude_code_hooks_daemon.constants.tools import ToolName

        names = {
            value
            for key, value in vars(ToolName).items()
            if not key.startswith("_") and isinstance(value, str)
        }
        words = set(re.findall(r"[A-Za-z]+", text))
        return names & words

    @pytest.mark.parametrize(
        "render",
        [
            lambda: gate.render_pause_directive(_a_pause()),
            lambda: gate.render_stop_directive(_a_pause(), found=2, problem="p"),
            lambda: gate.render_still_over_directive(_a_pause()),
        ],
        ids=["entry", "stop", "still-over"],
    )
    def test_only_allowed_tools_are_named(self, render: Any) -> None:
        named = self._tool_names_in(render())
        assert named, "the directive should name the cron tools"
        assert named <= gate.PAUSE_ALLOWED_TOOLS, named - gate.PAUSE_ALLOWED_TOOLS


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

    @pytest.mark.parametrize(
        "synthetic",
        [
            {"synthetic_source": "test-probe"},
            {"synthetic_source": "manual-probe"},
            {"session_id": "socket-stdin-test"},
            {"session_id": "playbook-probe-123"},
        ],
    )
    def test_synthetic_traffic_never_pauses(
        self, tmp_path: Path, synthetic: dict[str, Any]
    ) -> None:
        """A probe is not a session spending the account's usage (ledger N377)."""
        with patch.object(ProjectContext, "daemon_untracked_dir", return_value=tmp_path):
            hook_input = {**self._input(), **synthetic}
            assert gate.try_start_pause(hook_input, self._env(_snapshot(five=95.0))) is None
            assert list(tmp_path.rglob("*.usage-paused")) == []

    def test_below_the_ceiling_never_pauses(self, tmp_path: Path) -> None:
        with patch.object(ProjectContext, "daemon_untracked_dir", return_value=tmp_path):
            assert gate.try_start_pause(self._input(), self._env(_snapshot(five=10.0))) is None

    def test_a_reset_seconds_away_still_pauses_with_a_future_resume(self, tmp_path: Path) -> None:
        near = UsageSnapshot(five_hour=_window(95.0, int(_NOW + 30)), seven_day=None)
        with patch.object(ProjectContext, "daemon_untracked_dir", return_value=tmp_path):
            pause = gate.try_start_pause(self._input(), self._env(near))
        assert pause is not None
        assert pause.resume_at >= _NOW + gate.RESUME_MARGIN_SECONDS

    def test_a_record_that_cannot_be_read_back_is_no_pause(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Round 2 N3: written but unreadable must not become a stop/deny loop."""
        real_read = Path.read_text

        def unreadable_record(self: Path, *args: Any, **kwargs: Any) -> str:
            if self.name.endswith(".usage-paused"):
                raise PermissionError("denied")
            return real_read(self, *args, **kwargs)

        with (
            patch.object(ProjectContext, "daemon_untracked_dir", return_value=tmp_path),
            patch.object(Path, "read_text", unreadable_record),
            caplog.at_level("WARNING"),
        ):
            assert gate.try_start_pause(self._input(), self._env(_snapshot(five=95.0))) is None
        assert "read back" in caplog.text
        assert list(tmp_path.rglob("*.usage-paused")) == []  # the unreadable record is removed

    def test_a_record_that_reads_back_different_is_no_pause(self, tmp_path: Path) -> None:
        other = UsagePause(
            session_id=_SESSION,
            paused_at=_NOW - 5,
            resume_at=_NOW + 99_999,
            window=WINDOW_FIVE_HOUR,
            used_percentage=1.0,
            ceiling=80.0,
            reason="someone else",
        )
        with (
            patch.object(ProjectContext, "daemon_untracked_dir", return_value=tmp_path),
            patch.object(gate, "read_usage_pause", return_value=other),
        ):
            assert gate.try_start_pause(self._input(), self._env(_snapshot(five=95.0))) is None

    def test_an_owner_override_stops_any_pause_starting(self, tmp_path: Path) -> None:
        with patch.object(ProjectContext, "daemon_untracked_dir", return_value=tmp_path):
            write_usage_override(tmp_path, _SESSION, until=_NOW + 3600, now=_NOW)
            assert gate.try_start_pause(self._input(), self._env(_snapshot(five=95.0))) is None
            assert list(tmp_path.rglob("*.usage-paused")) == []

    def test_an_expired_override_no_longer_applies(self, tmp_path: Path) -> None:
        with patch.object(ProjectContext, "daemon_untracked_dir", return_value=tmp_path):
            write_usage_override(tmp_path, _SESSION, until=_NOW + 10, now=_NOW)
            later = self._env(_snapshot(five=95.0), now=_NOW + 11)
            assert gate.try_start_pause(self._input(), later) is not None

    def test_another_sessions_override_does_not_apply(self, tmp_path: Path) -> None:
        with patch.object(ProjectContext, "daemon_untracked_dir", return_value=tmp_path):
            write_usage_override(tmp_path, "someone-else", until=_NOW + 3600, now=_NOW)
            assert gate.try_start_pause(self._input(), self._env(_snapshot(five=95.0))) is not None

    def test_an_unreadable_override_fails_toward_not_pausing(self, tmp_path: Path) -> None:
        with patch.object(ProjectContext, "daemon_untracked_dir", return_value=tmp_path):
            write_usage_override(tmp_path, _SESSION, until=_NOW + 3600, now=_NOW)
            with patch.object(Path, "read_text", side_effect=PermissionError("denied")):
                assert gate.try_start_pause(self._input(), self._env(_snapshot(five=95.0))) is None

    def test_a_usage_loader_that_raises_oserror_fails_open(self, tmp_path: Path) -> None:
        def boom(_now: float) -> UsageSnapshot | None:
            raise OSError("disk")

        env = gate.PauseEnvironment(
            clock=lambda: _NOW, config_loader=self._config, usage_loader=boom
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
        text = gate.render_lift_not_recorded_note(expires_at=_NOW + 3600)
        assert "NOT" in text
        assert "LIFTED" not in text
