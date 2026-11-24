"""Plan 00523 Phase 2b: a ``hard_limit`` usage pause is lifted only at its resume time.

A ceiling pause is lifted early when a fresh reading is under the ceiling, or at
once on a host with no ceiling, because then the pause has nothing left to hold
for. A pause recorded for the account's HARD limit holds for a different reason:
every request fails until the reset whatever this host's ceiling says. So none of
the early lift paths (a held prompt re-resolving the ceiling, an early resume tick
reading a fresh snapshot) may lift it, and an early tick must not re-base it into
a ceiling record. At or after ``resume_at`` the ordinary logic applies.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from tests.unit.handlers.user_prompt_submit.test_usage_pause_gate import (
    _NOW,
    _SESSION,
    _config,
    _handler,
    _input,
    _run,
    _snapshot,
    _snapshot_observed,
)

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.handlers.user_prompt_submit.usage_pause_gate import (
    clear_in_session,
)
from claude_code_hooks_daemon.utils import usage_pause_gate as gate
from claude_code_hooks_daemon.utils.usage_pause import (
    CAUSE_CEILING,
    CAUSE_HARD_LIMIT,
    WINDOW_FIVE_HOUR,
    UsagePause,
    read_usage_pause,
    write_usage_pause,
)


def _hard_limit_record(
    tmp_path: Path, *, resume_at: float = _NOW + 3600, cause: str = CAUSE_HARD_LIMIT
) -> UsagePause:
    pause = UsagePause(
        session_id=_SESSION,
        paused_at=min(_NOW - 60, resume_at - 3600),
        resume_at=resume_at,
        window=WINDOW_FIVE_HOUR,
        used_percentage=100.0,
        ceiling=100.0,
        reason="five_hour window at its hard limit",
        cause=cause,
    )
    write_usage_pause(tmp_path, pause)
    return pause


class TestHeldPromptBeforeTheResumeTime:
    def test_a_host_with_no_ceiling_does_not_lift_it(self, tmp_path: Path) -> None:
        _hard_limit_record(tmp_path)
        handler = _handler(tmp_path, config=_config(None))
        result = _run(handler, tmp_path, _input())
        assert result.decision == Decision.DENY
        assert read_usage_pause(tmp_path, _SESSION, now=_NOW) is not None

    def test_a_reading_under_the_ceiling_does_not_lift_it(self, tmp_path: Path) -> None:
        _hard_limit_record(tmp_path)
        handler = _handler(tmp_path, snapshot=_snapshot(five=10.0))
        result = _run(handler, tmp_path, _input())
        assert result.decision == Decision.DENY
        assert read_usage_pause(tmp_path, _SESSION, now=_NOW) is not None

    def test_the_deny_names_the_hard_limit(self, tmp_path: Path) -> None:
        _hard_limit_record(tmp_path)
        result = _run(_handler(tmp_path, config=_config(None)), tmp_path, _input())
        assert "hard limit" in (result.reason or "")

    def test_control_a_ceiling_pause_on_a_host_with_no_ceiling_still_lifts(
        self, tmp_path: Path
    ) -> None:
        _hard_limit_record(tmp_path, cause=CAUSE_CEILING)
        result = _run(_handler(tmp_path, config=_config(None)), tmp_path, _input())
        assert result.decision == Decision.ALLOW
        assert read_usage_pause(tmp_path, _SESSION, now=_NOW) is None


class TestHeldPromptAtTheResumeTime:
    def test_the_first_prompt_at_resume_at_lifts_it(self, tmp_path: Path) -> None:
        _hard_limit_record(tmp_path, resume_at=_NOW)
        result = _run(_handler(tmp_path, config=_config(None)), tmp_path, _input())
        assert result.decision == Decision.ALLOW
        assert read_usage_pause(tmp_path, _SESSION, now=_NOW) is None

    def test_still_over_the_ceiling_at_resume_at_becomes_a_ceiling_pause_with_its_directive(
        self, tmp_path: Path
    ) -> None:
        # The supervisor stops holding at resume_at, so leaving the hard-limit record to
        # deny every prompt through its grace hour would waste each of them; a ceiling
        # pause replaces it, and its directive sets up the resume cron.
        _hard_limit_record(tmp_path, resume_at=_NOW)
        result = _run(_handler(tmp_path, snapshot=_snapshot(five=91.0)), tmp_path, _input())
        assert result.decision == Decision.ALLOW
        assert "USAGE CEILING REACHED" in "\n".join(result.context)
        renewed = read_usage_pause(tmp_path, _SESSION, now=_NOW)
        assert renewed is not None
        assert renewed.cause == CAUSE_CEILING


class TestOwnerEscape:
    def test_the_hard_limit_deny_carries_the_clear_command(self, tmp_path: Path) -> None:
        _hard_limit_record(tmp_path)
        result = _run(_handler(tmp_path, config=_config(None)), tmp_path, _input())
        assert clear_in_session() in (result.reason or "")


class TestEarlyResumeTick:
    def test_a_host_with_no_ceiling_does_not_lift_it(self, tmp_path: Path) -> None:
        _hard_limit_record(tmp_path)
        handler = _handler(tmp_path, config=_config(None))
        result = _run(handler, tmp_path, _input(gate.USAGE_RESUME_PROMPT))
        assert result.decision == Decision.DENY
        assert read_usage_pause(tmp_path, _SESSION, now=_NOW) is not None

    def test_a_fresh_reading_under_the_ceiling_does_not_lift_it(self, tmp_path: Path) -> None:
        _hard_limit_record(tmp_path)
        handler = _handler(tmp_path, snapshot=_snapshot_observed(five=10.0, age=5.0))
        result = _run(handler, tmp_path, _input(gate.USAGE_RESUME_PROMPT))
        assert result.decision == Decision.DENY
        assert read_usage_pause(tmp_path, _SESSION, now=_NOW) is not None

    def test_a_fresh_reading_over_the_ceiling_does_not_rebase_it(self, tmp_path: Path) -> None:
        written = _hard_limit_record(tmp_path)
        handler = _handler(tmp_path, snapshot=_snapshot_observed(seven=95.0, age=5.0))
        result = _run(handler, tmp_path, _input(gate.USAGE_RESUME_PROMPT))
        assert result.decision == Decision.DENY
        assert read_usage_pause(tmp_path, _SESSION, now=_NOW) == written


class TestResumeTickAtTheResumeTime:
    def test_a_due_tick_on_a_host_with_no_ceiling_lifts_it(self, tmp_path: Path) -> None:
        _hard_limit_record(tmp_path, resume_at=_NOW)
        handler = _handler(tmp_path, config=_config(None))
        result = _run(handler, tmp_path, _input(gate.USAGE_RESUME_PROMPT))
        assert result.decision == Decision.ALLOW
        assert read_usage_pause(tmp_path, _SESSION, now=_NOW) is None


class TestRebaseKeepsTheCause:
    def test_a_rebase_never_turns_a_hard_limit_record_into_a_ceiling_one(
        self, tmp_path: Path
    ) -> None:
        record = _hard_limit_record(tmp_path)
        env = gate.PauseEnvironment(clock=lambda: _NOW)
        breach = gate.UsageBreach(WINDOW_FIVE_HOUR, 95.0, 80.0, int(_NOW + 86400))
        with patch.object(ProjectContext, "daemon_untracked_dir", return_value=tmp_path):
            assert gate.rebase_pause(record, [breach], env) is True
        rebased = read_usage_pause(tmp_path, _SESSION, now=_NOW)
        assert rebased is not None
        assert rebased.cause == CAUSE_HARD_LIMIT


class TestHoldPredicate:
    def test_a_hard_limit_record_holds_until_resume_at(self) -> None:
        pause = UsagePause(
            _SESSION, _NOW - 60, _NOW + 60, WINDOW_FIVE_HOUR, 100.0, 100.0, "x", CAUSE_HARD_LIMIT
        )
        assert gate.hard_limit_holds(pause, now=_NOW) is True
        assert gate.hard_limit_holds(pause, now=_NOW + 60) is False

    def test_a_ceiling_record_never_holds_by_this_rule(self) -> None:
        pause = UsagePause(_SESSION, _NOW - 60, _NOW + 60, WINDOW_FIVE_HOUR, 91.0, 80.0, "x")
        assert gate.hard_limit_holds(pause, now=_NOW) is False
