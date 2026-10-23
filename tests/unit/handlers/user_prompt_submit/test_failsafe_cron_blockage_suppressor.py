"""Tests for FailsafeCronBlockageSuppressorHandler (Plan 00298).

Short-circuits a delivered failsafe-cron tick, before the model ever sees it,
when the session is stably blocked only on human input: a BLOCKED mode in the
session-modes registry (Plan 00501 Task 2.2), entered by
auto_continue_stop.AutoContinueStopHandler. Fail-open throughout: no mode, a
mode of a different session, an expired mode, an unreadable registry or missing
project context must all ALLOW the tick through unchanged.
"""

import logging
import time
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from tests.support.autonomy import awaiting_human_entry, focus_entry, pin_session_modes

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.session_mode_log import TransitionAction
from claude_code_hooks_daemon.core.session_mode_registry import SessionModeRegistry
from claude_code_hooks_daemon.handlers.post_tool_use.recovery_cron_advisor import (
    CANONICAL_CRON_PROMPT,
)
from claude_code_hooks_daemon.handlers.user_prompt_submit.failsafe_cron_blockage_suppressor import (
    FailsafeCronBlockageSuppressorHandler,
)
from claude_code_hooks_daemon.utils.cron_cadence import (
    CADENCE_FILENAME,
    CadenceState,
    read_cadence,
    write_cadence,
)
from claude_code_hooks_daemon.utils.session_modes import (
    DECLARED_BLOCKED_TTL_SECONDS,
    BlockReason,
    ModeSource,
    SessionMode,
    SessionModeEntry,
    declared_blocked_entry,
)

_OWED_PATCH_TARGET = (
    "claude_code_hooks_daemon.handlers.user_prompt_submit."
    "failsafe_cron_blockage_suppressor.FailsafeCronBlockageSuppressorHandler._work_is_owed"
)

_DAEMON_UNTRACKED_DIR_PATCH_TARGET = (
    "claude_code_hooks_daemon.handlers.user_prompt_submit."
    "failsafe_cron_blockage_suppressor.ProjectContext.daemon_untracked_dir"
)


@pytest.fixture(autouse=True)
def registry(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> SessionModeRegistry:
    """The session-modes registry the handler reads, empty until a test enters a mode."""
    return pin_session_modes(monkeypatch, tmp_path)


def _declare(registry: SessionModeRegistry, session_id: str = "sess-1") -> None:
    registry.enter(awaiting_human_entry(session_id))


def _blocked(registry: SessionModeRegistry, session_id: str = "sess-1") -> bool:
    return registry.policy(session_id).is_blocked


def _goal_blocked_entry(session_id: str) -> SessionModeEntry:
    now = time.time()
    return SessionModeEntry(
        mode=SessionMode.BLOCKED,
        session_id=session_id,
        entered_at=now,
        expires_at=now + 3600.0,
        source=ModeSource.DETECTOR,
        reason=BlockReason.GOAL_LOOP,
    )


def _cron_hook_input(session_id: str = "sess-1") -> dict[str, Any]:
    return {"prompt": CANONICAL_CRON_PROMPT, "session_id": session_id}


def _real_hook_input(
    session_id: str = "sess-1", prompt: str = "please fix the bug"
) -> dict[str, Any]:
    return {"prompt": prompt, "session_id": session_id}


class TestInit:
    def test_config_key_and_priority(self) -> None:
        handler = FailsafeCronBlockageSuppressorHandler()
        assert handler.name == HandlerID.FAILSAFE_CRON_BLOCKAGE_SUPPRESSOR.display_name
        assert handler.priority == Priority.FAILSAFE_CRON_BLOCKAGE_SUPPRESSOR

    def test_not_terminal(self) -> None:
        """Must NOT be terminal: idle_housekeeping_advisory and
        standing_authorisations also key off the same canonical cron prompt
        and must still run on a non-suppressed tick. A non-terminal DENY
        survives later handlers regardless (core/router.py)."""
        handler = FailsafeCronBlockageSuppressorHandler()
        assert handler.terminal is False


class TestMatches:
    def test_matches_canonical_cron_prompt(self) -> None:
        handler = FailsafeCronBlockageSuppressorHandler()
        assert handler.matches(_cron_hook_input()) is True

    def test_does_not_match_ordinary_prompt(self) -> None:
        handler = FailsafeCronBlockageSuppressorHandler()
        assert handler.matches({"prompt": "please fix the bug", "session_id": "sess-1"}) is False

    def test_does_not_match_missing_prompt(self) -> None:
        handler = FailsafeCronBlockageSuppressorHandler()
        assert handler.matches({"session_id": "sess-1"}) is False

    def test_does_not_match_non_string_prompt(self) -> None:
        handler = FailsafeCronBlockageSuppressorHandler()
        assert handler.matches({"prompt": 123, "session_id": "sess-1"}) is False


class TestHandle:
    def test_no_mode_allows(self) -> None:
        result = FailsafeCronBlockageSuppressorHandler().handle(_cron_hook_input())
        assert result.decision == Decision.ALLOW

    def test_blocked_mode_for_same_session_suppresses(self, registry: SessionModeRegistry) -> None:
        _declare(registry)
        result = FailsafeCronBlockageSuppressorHandler().handle(_cron_hook_input("sess-1"))
        assert result.decision == Decision.DENY
        assert result.reason

    def test_goal_blocked_mode_suppresses_too(self, registry: SessionModeRegistry) -> None:
        """Both BLOCKED reasons are one family (ruling 03), so both drop the tick."""
        registry.enter(_goal_blocked_entry("sess-1"))
        with patch(_OWED_PATCH_TARGET, return_value=False):
            result = FailsafeCronBlockageSuppressorHandler().handle(_cron_hook_input("sess-1"))
        assert result.decision == Decision.DENY

    def test_blocked_mode_for_different_session_allows(self, registry: SessionModeRegistry) -> None:
        _declare(registry, "sess-1")
        result = FailsafeCronBlockageSuppressorHandler().handle(_cron_hook_input("sess-2"))
        assert result.decision == Decision.ALLOW

    def test_expired_mode_allows(self, registry: SessionModeRegistry) -> None:
        recorded = time.time() - DECLARED_BLOCKED_TTL_SECONDS - 1.0
        registry.enter(declared_blocked_entry("sess-1", entered_at=recorded))
        result = FailsafeCronBlockageSuppressorHandler().handle(_cron_hook_input("sess-1"))
        assert result.decision == Decision.ALLOW

    def test_expiry_is_the_shared_ttl_not_an_option(self) -> None:
        """Expiry lives in the registry entry now (Task 2.2), so the option is gone."""
        assert not hasattr(FailsafeCronBlockageSuppressorHandler(), "_expiry_hours")

    def test_a_focus_mode_alone_does_not_suppress_the_failsafe(
        self, registry: SessionModeRegistry
    ) -> None:
        """Focus delivers the failsafe tick (naming the task is Task 3.2's)."""
        registry.enter(focus_entry("sess-1"))
        with patch(_OWED_PATCH_TARGET, return_value=True):
            result = FailsafeCronBlockageSuppressorHandler().handle(_cron_hook_input("sess-1"))
        assert result.decision == Decision.ALLOW

    def test_an_unreadable_registry_allows_and_warns(
        self, registry: SessionModeRegistry, caplog: pytest.LogCaptureFixture
    ) -> None:
        with (
            patch.object(registry, "policy", side_effect=OSError("disk gone")),
            caplog.at_level(logging.WARNING),
        ):
            result = FailsafeCronBlockageSuppressorHandler().handle(_cron_hook_input())
        assert result.decision == Decision.ALLOW
        assert "disk gone" in caplog.text

    def test_no_project_context_allows(self) -> None:
        handler = FailsafeCronBlockageSuppressorHandler()
        with patch(
            _DAEMON_UNTRACKED_DIR_PATCH_TARGET, side_effect=RuntimeError("no project context")
        ):
            result = handler.handle(_cron_hook_input())
        assert result.decision == Decision.ALLOW

    def test_missing_session_id_falls_back_to_unknown_bucket(
        self, registry: SessionModeRegistry
    ) -> None:
        """A hook input with no session_id resolves to the same 'unknown'
        fallback the writer side would use, so a mode recorded under that
        bucket still suppresses -- this pins the fallback is a real value
        used consistently, not a magic unconditional bypass."""
        _declare(registry, "unknown")
        result = FailsafeCronBlockageSuppressorHandler().handle({"prompt": CANONICAL_CRON_PROMPT})
        assert result.decision == Decision.DENY

    def test_real_prompt_clears_the_blocked_mode_and_allows(
        self, registry: SessionModeRegistry
    ) -> None:
        """A genuine (non-cron) user prompt is the owner replying -- the
        mode must end immediately rather than waiting for its expiry."""
        _declare(registry)
        result = FailsafeCronBlockageSuppressorHandler().handle(_real_hook_input("sess-1"))
        assert result.decision == Decision.ALLOW
        assert not _blocked(registry)

    def test_real_prompt_clears_goal_blocked_too(self, registry: SessionModeRegistry) -> None:
        registry.enter(_goal_blocked_entry("sess-1"))
        FailsafeCronBlockageSuppressorHandler().handle(_real_hook_input("sess-1"))
        assert not _blocked(registry)

    def test_real_prompt_exit_from_goal_loop_block_is_logged_with_its_cause(
        self, registry: SessionModeRegistry
    ) -> None:
        """The human-prompt exit of a goal-loop block lands in the transition log
        as an EXIT naming the human prompt as the cause."""
        registry.enter(_goal_blocked_entry("sess-1"))
        FailsafeCronBlockageSuppressorHandler().handle(_real_hook_input("sess-1"))
        log = registry.transition_log
        assert log is not None
        exits = [
            t for t in log.recent(10, session_id="sess-1") if t.action == TransitionAction.EXIT
        ]
        assert len(exits) == 1
        assert "a prompt the human typed in this session" in exits[0].evidence

    def test_real_prompt_leaves_focus_alone(self, registry: SessionModeRegistry) -> None:
        """Only the BLOCKED family ends on a reply; focus has its own off switch."""
        registry.enter(focus_entry("sess-1"))
        _declare(registry)
        FailsafeCronBlockageSuppressorHandler().handle(_real_hook_input("sess-1"))
        assert registry.policy("sess-1").focus_task is not None

    def test_real_prompt_then_cron_tick_is_allowed_through(
        self, registry: SessionModeRegistry
    ) -> None:
        """After a real prompt clears the mode, a subsequent cron tick for
        the same session must no longer be suppressed."""
        _declare(registry)
        handler = FailsafeCronBlockageSuppressorHandler()
        real_result = handler.handle(_real_hook_input("sess-1"))
        cron_result = handler.handle(_cron_hook_input("sess-1"))
        assert real_result.decision == Decision.ALLOW
        assert cron_result.decision == Decision.ALLOW

    def test_real_prompt_clear_failure_still_allows_and_warns(
        self, registry: SessionModeRegistry, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Ending the mode is fail-open: a write error must never block the
        real prompt it was riding along with, and it is logged loudly."""
        _declare(registry)
        with (
            patch.object(registry, "exit", side_effect=OSError("boom")),
            caplog.at_level(logging.WARNING),
        ):
            result = FailsafeCronBlockageSuppressorHandler().handle(_real_hook_input("sess-1"))
        assert result.decision == Decision.ALLOW
        assert "boom" in caplog.text

    def test_real_prompt_with_no_mode_allows(self) -> None:
        result = FailsafeCronBlockageSuppressorHandler().handle(_real_hook_input("sess-1"))
        assert result.decision == Decision.ALLOW


class TestMatchesWithABlockedMode:
    def test_matches_real_prompt_when_the_session_is_blocked(
        self, registry: SessionModeRegistry
    ) -> None:
        _declare(registry)
        assert FailsafeCronBlockageSuppressorHandler().matches(_real_hook_input("sess-1")) is True

    def test_does_not_match_real_prompt_of_another_session(
        self, registry: SessionModeRegistry
    ) -> None:
        _declare(registry, "sess-2")
        assert FailsafeCronBlockageSuppressorHandler().matches(_real_hook_input("sess-1")) is False

    def test_does_not_match_real_prompt_when_no_mode(self) -> None:
        assert FailsafeCronBlockageSuppressorHandler().matches(_real_hook_input("sess-1")) is False

    def test_does_not_match_real_prompt_when_no_project_context(self) -> None:
        handler = FailsafeCronBlockageSuppressorHandler()
        with patch(
            _DAEMON_UNTRACKED_DIR_PATCH_TARGET, side_effect=RuntimeError("no project context")
        ):
            assert handler.matches(_real_hook_input("sess-1")) is False


class TestPlanningTagIsPresent:
    """Plan 00337 Task 4.5.

    The tag is the ONLY route by which the registry injects
    ``track_plans_in_project``. Without it the handler silently reads None and
    resolves the DEFAULT plan directory, so a project that configured a
    different one would find "nothing owed" -- the direction that withdraws the
    safety net. Asserted here because that failure is invisible at runtime: the
    attribute is self-defaulted, so the missing injection does not raise.
    """

    def test_handler_carries_the_planning_tag(self) -> None:
        assert HandlerTag.PLANNING in FailsafeCronBlockageSuppressorHandler().tags

    def test_track_plans_in_project_self_defaults(self) -> None:
        """The injection block does not run when plan_workflow is None, so the
        attribute must exist before the registry ever touches it."""
        assert FailsafeCronBlockageSuppressorHandler()._track_plans_in_project is None


class TestRowOneWorkOwedIsNeverBackedOff:
    """Work owed, nothing declared: the case the cron exists for.

    Every tick must be delivered, and any accumulated backoff discarded.
    """

    def test_owed_work_allows_the_tick(self) -> None:
        with patch(_OWED_PATCH_TARGET, return_value=True):
            result = FailsafeCronBlockageSuppressorHandler().handle(_cron_hook_input("sess-1"))
        assert result.decision == Decision.ALLOW

    def test_owed_work_resets_an_accumulated_backoff(self, tmp_path: Path) -> None:
        handler = FailsafeCronBlockageSuppressorHandler()
        with patch(_OWED_PATCH_TARGET, return_value=False):
            for _ in range(4):
                handler.handle(_cron_hook_input("sess-1"))
        assert read_cadence(tmp_path / CADENCE_FILENAME) is not None
        with patch(_OWED_PATCH_TARGET, return_value=True):
            result = handler.handle(_cron_hook_input("sess-1"))
        assert result.decision == Decision.ALLOW
        assert read_cadence(tmp_path / CADENCE_FILENAME) is None


class TestUndeterminablePlanDirBehavesLikeRowOne:
    """A plan directory that cannot be resolved must NOT read as "nothing
    owed". It is a third value, and it ticks -- otherwise a mis-resolved
    directory silently withdraws the safety net."""

    def test_unknown_owed_state_allows_every_tick(self) -> None:
        handler = FailsafeCronBlockageSuppressorHandler()
        with patch(_OWED_PATCH_TARGET, return_value=None):
            decisions = [handler.handle(_cron_hook_input("sess-1")).decision for _ in range(6)]
        assert decisions == [Decision.ALLOW] * 6


class TestRowFourNothingOwedNothingDeclaredBacksOff:
    """Backed off, never silent."""

    def test_ticks_thin_out_but_never_stop(self) -> None:
        handler = FailsafeCronBlockageSuppressorHandler()
        with patch(_OWED_PATCH_TARGET, return_value=False):
            decisions = [handler.handle(_cron_hook_input("sess-1")).decision for _ in range(12)]
        delivered = [i + 1 for i, d in enumerate(decisions) if d == Decision.ALLOW]
        # hourly, then every 2h, then every 4h and no sparser (MAX_CADENCE_HOURS)
        assert delivered == [1, 3, 7, 11]

    def test_a_real_prompt_resets_the_cadence(self, tmp_path: Path) -> None:
        handler = FailsafeCronBlockageSuppressorHandler()
        with patch(_OWED_PATCH_TARGET, return_value=False):
            for _ in range(6):
                handler.handle(_cron_hook_input("sess-1"))
        handler.handle(_real_hook_input("sess-1"))
        assert read_cadence(tmp_path / CADENCE_FILENAME) is None
        with patch(_OWED_PATCH_TARGET, return_value=False):
            first_after_reset = handler.handle(_cron_hook_input("sess-1"))
        assert first_after_reset.decision == Decision.ALLOW


class TestRowTwoDeclaredAndOwedBacksOffRatherThanSuppressing:
    """Declared, but work IS owed. Full suppression would be unsafe (there is
    real work), hourly would be wasteful (the agent says it is blocked), so
    this row backs off rather than taking either extreme."""

    def test_declared_with_owed_work_thins_out_instead_of_denying_every_tick(
        self, registry: SessionModeRegistry
    ) -> None:
        _declare(registry)
        handler = FailsafeCronBlockageSuppressorHandler()
        with patch(_OWED_PATCH_TARGET, return_value=True):
            decisions = [handler.handle(_cron_hook_input("sess-1")).decision for _ in range(12)]
        delivered = [i + 1 for i, d in enumerate(decisions) if d == Decision.ALLOW]
        assert delivered == [1, 3, 7, 11]


class TestMatchesSeesTheResetOpportunity:
    """Task 4.3 is dead code unless matches() widens.

    In row 4 ("nothing owed, nothing declared") there is by definition no
    BLOCKED mode, so a mode-only test would return False for a real user
    prompt -- handle() never runs and the cadence is never reset. The failure
    is invisible: ticks simply stay sparse after the owner returns.
    """

    def test_real_prompt_matches_when_only_a_cadence_file_exists(self, tmp_path: Path) -> None:
        write_cadence(tmp_path / CADENCE_FILENAME, CadenceState("sess-1", 1, 2))
        assert FailsafeCronBlockageSuppressorHandler().matches(_real_hook_input("sess-1")) is True

    def test_real_prompt_still_does_not_match_when_neither_exists(self) -> None:
        assert FailsafeCronBlockageSuppressorHandler().matches(_real_hook_input("sess-1")) is False


class TestCadenceFailsOpen:
    def test_an_unreadable_cadence_file_allows(self, tmp_path: Path) -> None:
        (tmp_path / CADENCE_FILENAME).write_text("{not json", encoding="utf-8")
        with patch(_OWED_PATCH_TARGET, return_value=False):
            result = FailsafeCronBlockageSuppressorHandler().handle(_cron_hook_input("sess-1"))
        assert result.decision == Decision.ALLOW

    def test_a_raising_ledger_consult_allows(self) -> None:
        """_work_is_owed swallows its own errors and returns None, but if a new
        failure mode ever escaped it, the tick must still get through."""
        with patch(_OWED_PATCH_TARGET, side_effect=OSError("boom")):
            result = FailsafeCronBlockageSuppressorHandler().handle(_cron_hook_input("sess-1"))
        assert result.decision == Decision.ALLOW


class TestOnlyTheSameSessionsHumanClears:
    """Plan 00501 Task 2.1 (ledger N378): only a genuine human prompt in the
    SAME session clears the awaiting-human declaration."""

    def test_a_prompt_in_another_session_leaves_the_mode(
        self, registry: SessionModeRegistry
    ) -> None:
        _declare(registry)
        handler = FailsafeCronBlockageSuppressorHandler()
        result = handler.handle(_real_hook_input("sess-2"))
        tick = handler.handle(_cron_hook_input("sess-1"))
        assert result.decision == Decision.ALLOW
        assert _blocked(registry)
        assert tick.decision == Decision.DENY

    def test_a_line_the_supervisor_typed_leaves_the_mode(
        self, registry: SessionModeRegistry
    ) -> None:
        _declare(registry)
        handler = FailsafeCronBlockageSuppressorHandler()
        supervisor_line = "🤖 [ccy-supervisor 12:00] continue"
        result = handler.handle(_real_hook_input("sess-1", prompt=supervisor_line))
        tick = handler.handle(_cron_hook_input("sess-1"))
        assert result.decision == Decision.ALLOW
        assert _blocked(registry)
        assert tick.decision == Decision.DENY

    def test_the_same_sessions_human_still_clears(self, registry: SessionModeRegistry) -> None:
        _declare(registry)
        result = FailsafeCronBlockageSuppressorHandler().handle(_real_hook_input("sess-1"))
        assert result.decision == Decision.ALLOW
        assert not _blocked(registry)

    def test_a_supervisor_line_does_not_reset_the_cadence(self, tmp_path: Path) -> None:
        cadence_path = tmp_path / CADENCE_FILENAME
        write_cadence(
            cadence_path,
            CadenceState(session_id="sess-1", dropped_since_allowed=1, cadence_hours=4),
        )
        FailsafeCronBlockageSuppressorHandler().handle(
            _real_hook_input("sess-1", prompt="🤖 [ccy-supervisor 12:00] continue")
        )
        assert read_cadence(cadence_path) is not None

    def test_a_prompt_in_another_session_keeps_the_cadence(self, tmp_path: Path) -> None:
        cadence_path = tmp_path / CADENCE_FILENAME
        write_cadence(
            cadence_path,
            CadenceState(session_id="sess-1", dropped_since_allowed=1, cadence_hours=4),
        )
        FailsafeCronBlockageSuppressorHandler().handle(_real_hook_input("sess-2"))
        assert read_cadence(cadence_path) is not None
