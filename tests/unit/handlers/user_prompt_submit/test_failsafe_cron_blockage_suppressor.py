"""Tests for FailsafeCronBlockageSuppressorHandler (Plan 00298).

Short-circuits a delivered failsafe-cron tick, before the model ever sees it,
when the session is stably blocked only on human input (a marker recorded by
auto_continue_stop.AutoContinueStopHandler). Fail-open throughout: no marker,
a marker for a different session, an expired marker, or missing project
context must all ALLOW the tick through unchanged.
"""

from pathlib import Path
from typing import Any
from unittest.mock import patch

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.post_tool_use.recovery_cron_advisor import (
    _CANONICAL_CRON_PROMPT,
)
from claude_code_hooks_daemon.handlers.user_prompt_submit.failsafe_cron_blockage_suppressor import (
    FailsafeCronBlockageSuppressorHandler,
)
from claude_code_hooks_daemon.utils.blockage_marker import (
    MARKER_FILENAME,
    read_marker,
    write_marker,
)
from claude_code_hooks_daemon.utils.cron_cadence import (
    CADENCE_FILENAME,
    CadenceState,
    read_cadence,
    write_cadence,
)

_OWED_PATCH_TARGET = (
    "claude_code_hooks_daemon.handlers.user_prompt_submit."
    "failsafe_cron_blockage_suppressor.FailsafeCronBlockageSuppressorHandler._work_is_owed"
)

_DAEMON_UNTRACKED_DIR_PATCH_TARGET = (
    "claude_code_hooks_daemon.handlers.user_prompt_submit."
    "failsafe_cron_blockage_suppressor.ProjectContext.daemon_untracked_dir"
)


def _cron_hook_input(session_id: str = "sess-1") -> dict[str, Any]:
    return {"prompt": _CANONICAL_CRON_PROMPT, "session_id": session_id}


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
    def test_no_marker_allows(self, tmp_path: Path) -> None:
        handler = FailsafeCronBlockageSuppressorHandler()
        with patch(_DAEMON_UNTRACKED_DIR_PATCH_TARGET, return_value=tmp_path):
            result = handler.handle(_cron_hook_input())
        assert result.decision == Decision.ALLOW

    def test_valid_marker_for_same_session_suppresses(self, tmp_path: Path) -> None:
        write_marker(tmp_path / MARKER_FILENAME, "sess-1", now=1000.0)
        handler = FailsafeCronBlockageSuppressorHandler()
        handler._clock = lambda: 1100.0  # within default 24h expiry
        with patch(_DAEMON_UNTRACKED_DIR_PATCH_TARGET, return_value=tmp_path):
            result = handler.handle(_cron_hook_input("sess-1"))
        assert result.decision == Decision.DENY
        assert result.reason

    def test_marker_for_different_session_allows(self, tmp_path: Path) -> None:
        write_marker(tmp_path / MARKER_FILENAME, "sess-1", now=1000.0)
        handler = FailsafeCronBlockageSuppressorHandler()
        handler._clock = lambda: 1100.0
        with patch(_DAEMON_UNTRACKED_DIR_PATCH_TARGET, return_value=tmp_path):
            result = handler.handle(_cron_hook_input("sess-2"))
        assert result.decision == Decision.ALLOW

    def test_expired_marker_allows(self, tmp_path: Path) -> None:
        write_marker(tmp_path / MARKER_FILENAME, "sess-1", now=0.0)
        handler = FailsafeCronBlockageSuppressorHandler()
        handler._expiry_hours = 24.0
        handler._clock = lambda: (24.0 * 3600.0) + 1.0  # just past expiry
        with patch(_DAEMON_UNTRACKED_DIR_PATCH_TARGET, return_value=tmp_path):
            result = handler.handle(_cron_hook_input("sess-1"))
        assert result.decision == Decision.ALLOW

    def test_configured_expiry_is_honoured(self, tmp_path: Path) -> None:
        write_marker(tmp_path / MARKER_FILENAME, "sess-1", now=0.0)
        handler = FailsafeCronBlockageSuppressorHandler()
        handler._expiry_hours = 1.0
        handler._clock = lambda: 3601.0  # 1 second past a 1h expiry
        with patch(_DAEMON_UNTRACKED_DIR_PATCH_TARGET, return_value=tmp_path):
            result = handler.handle(_cron_hook_input("sess-1"))
        assert result.decision == Decision.ALLOW

    def test_corrupt_marker_allows(self, tmp_path: Path) -> None:
        (tmp_path / MARKER_FILENAME).write_text("{not json", encoding="utf-8")
        handler = FailsafeCronBlockageSuppressorHandler()
        with patch(_DAEMON_UNTRACKED_DIR_PATCH_TARGET, return_value=tmp_path):
            result = handler.handle(_cron_hook_input())
        assert result.decision == Decision.ALLOW

    def test_no_project_context_allows(self) -> None:
        handler = FailsafeCronBlockageSuppressorHandler()
        with patch(
            _DAEMON_UNTRACKED_DIR_PATCH_TARGET, side_effect=RuntimeError("no project context")
        ):
            result = handler.handle(_cron_hook_input())
        assert result.decision == Decision.ALLOW

    def test_missing_session_id_falls_back_to_unknown_bucket(self, tmp_path: Path) -> None:
        """A hook input with no session_id resolves to the same 'unknown'
        fallback the writer side would use, so a marker recorded under that
        bucket still suppresses -- this pins the fallback is a real value
        used consistently, not a magic unconditional bypass."""
        write_marker(tmp_path / MARKER_FILENAME, "unknown", now=1000.0)
        handler = FailsafeCronBlockageSuppressorHandler()
        handler._clock = lambda: 1000.0
        with patch(_DAEMON_UNTRACKED_DIR_PATCH_TARGET, return_value=tmp_path):
            result = handler.handle({"prompt": _CANONICAL_CRON_PROMPT})
        assert result.decision == Decision.DENY

    def test_real_prompt_with_valid_marker_clears_it_and_allows(self, tmp_path: Path) -> None:
        """A genuine (non-cron) user prompt is the owner replying -- the
        marker must be removed immediately rather than waiting up to
        expiry_hours to lapse on its own."""
        marker_path = tmp_path / MARKER_FILENAME
        write_marker(marker_path, "sess-1", now=1000.0)
        handler = FailsafeCronBlockageSuppressorHandler()
        handler._clock = lambda: 1100.0
        with patch(_DAEMON_UNTRACKED_DIR_PATCH_TARGET, return_value=tmp_path):
            result = handler.handle(_real_hook_input("sess-1"))
        assert result.decision == Decision.ALLOW
        assert not marker_path.exists()
        assert read_marker(marker_path) is None

    def test_real_prompt_then_cron_tick_is_allowed_through(self, tmp_path: Path) -> None:
        """After a real prompt clears the marker, a subsequent cron tick for
        the same session must no longer be suppressed."""
        marker_path = tmp_path / MARKER_FILENAME
        write_marker(marker_path, "sess-1", now=1000.0)
        handler = FailsafeCronBlockageSuppressorHandler()
        handler._clock = lambda: 1100.0
        with patch(_DAEMON_UNTRACKED_DIR_PATCH_TARGET, return_value=tmp_path):
            real_result = handler.handle(_real_hook_input("sess-1"))
            cron_result = handler.handle(_cron_hook_input("sess-1"))
        assert real_result.decision == Decision.ALLOW
        assert cron_result.decision == Decision.ALLOW

    def test_cron_prompt_with_valid_marker_is_still_denied(self, tmp_path: Path) -> None:
        """Regression: widening matches()/handle() for real prompts must not
        change the suppression behaviour for an actual cron tick."""
        write_marker(tmp_path / MARKER_FILENAME, "sess-1", now=1000.0)
        handler = FailsafeCronBlockageSuppressorHandler()
        handler._clock = lambda: 1100.0
        with patch(_DAEMON_UNTRACKED_DIR_PATCH_TARGET, return_value=tmp_path):
            result = handler.handle(_cron_hook_input("sess-1"))
        assert result.decision == Decision.DENY

    def test_real_prompt_clear_failure_still_allows(self, tmp_path: Path) -> None:
        """clear_marker() is fail-open (Plan 00298 contract): an unlink
        error must never block the real prompt it was riding along with.
        Patches Path.unlink (not clear_marker itself) so this exercises the
        real fail-open path, not a mocked-away one."""
        marker_path = tmp_path / MARKER_FILENAME
        write_marker(marker_path, "sess-1", now=1000.0)
        handler = FailsafeCronBlockageSuppressorHandler()
        handler._clock = lambda: 1100.0
        with (
            patch(_DAEMON_UNTRACKED_DIR_PATCH_TARGET, return_value=tmp_path),
            patch.object(Path, "unlink", side_effect=OSError("boom")),
        ):
            result = handler.handle(_real_hook_input("sess-1"))
        assert result.decision == Decision.ALLOW

    def test_real_prompt_with_no_marker_allows(self, tmp_path: Path) -> None:
        handler = FailsafeCronBlockageSuppressorHandler()
        with patch(_DAEMON_UNTRACKED_DIR_PATCH_TARGET, return_value=tmp_path):
            result = handler.handle(_real_hook_input("sess-1"))
        assert result.decision == Decision.ALLOW


class TestMatchesWithMarker:
    def test_matches_real_prompt_when_marker_exists(self, tmp_path: Path) -> None:
        write_marker(tmp_path / MARKER_FILENAME, "sess-1", now=1000.0)
        handler = FailsafeCronBlockageSuppressorHandler()
        with patch(_DAEMON_UNTRACKED_DIR_PATCH_TARGET, return_value=tmp_path):
            assert handler.matches(_real_hook_input("sess-1")) is True

    def test_does_not_match_real_prompt_when_no_marker(self, tmp_path: Path) -> None:
        handler = FailsafeCronBlockageSuppressorHandler()
        with patch(_DAEMON_UNTRACKED_DIR_PATCH_TARGET, return_value=tmp_path):
            assert handler.matches(_real_hook_input("sess-1")) is False

    def test_does_not_match_real_prompt_when_no_project_context(self) -> None:
        handler = FailsafeCronBlockageSuppressorHandler()
        with patch(
            _DAEMON_UNTRACKED_DIR_PATCH_TARGET, side_effect=RuntimeError("no project context")
        ):
            assert handler.matches(_real_hook_input("sess-1")) is False


def _backoff_handler() -> FailsafeCronBlockageSuppressorHandler:
    """A handler with a fixed clock, for the Phase 4 cadence tests."""
    handler = FailsafeCronBlockageSuppressorHandler()
    handler._clock = lambda: 1000.0
    return handler


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

    def test_owed_work_allows_the_tick(self, tmp_path: Path) -> None:
        handler = _backoff_handler()
        with (
            patch(_DAEMON_UNTRACKED_DIR_PATCH_TARGET, return_value=tmp_path),
            patch(_OWED_PATCH_TARGET, return_value=True),
        ):
            result = handler.handle(_cron_hook_input("sess-1"))
        assert result.decision == Decision.ALLOW

    def test_owed_work_resets_an_accumulated_backoff(self, tmp_path: Path) -> None:
        handler = _backoff_handler()
        with patch(_DAEMON_UNTRACKED_DIR_PATCH_TARGET, return_value=tmp_path):
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

    def test_unknown_owed_state_allows_every_tick(self, tmp_path: Path) -> None:
        handler = _backoff_handler()
        with (
            patch(_DAEMON_UNTRACKED_DIR_PATCH_TARGET, return_value=tmp_path),
            patch(_OWED_PATCH_TARGET, return_value=None),
        ):
            decisions = [handler.handle(_cron_hook_input("sess-1")).decision for _ in range(6)]
        assert decisions == [Decision.ALLOW] * 6


class TestRowFourNothingOwedNothingDeclaredBacksOff:
    """Backed off, never silent."""

    def test_ticks_thin_out_but_never_stop(self, tmp_path: Path) -> None:
        handler = _backoff_handler()
        with (
            patch(_DAEMON_UNTRACKED_DIR_PATCH_TARGET, return_value=tmp_path),
            patch(_OWED_PATCH_TARGET, return_value=False),
        ):
            decisions = [handler.handle(_cron_hook_input("sess-1")).decision for _ in range(12)]
        delivered = [i + 1 for i, d in enumerate(decisions) if d == Decision.ALLOW]
        # hourly, then every 2h, then every 4h and no sparser (MAX_CADENCE_HOURS)
        assert delivered == [1, 3, 7, 11]

    def test_a_real_prompt_resets_the_cadence(self, tmp_path: Path) -> None:
        handler = _backoff_handler()
        with patch(_DAEMON_UNTRACKED_DIR_PATCH_TARGET, return_value=tmp_path):
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
        self, tmp_path: Path
    ) -> None:
        write_marker(tmp_path / MARKER_FILENAME, "sess-1", now=1000.0)
        handler = _backoff_handler()
        with (
            patch(_DAEMON_UNTRACKED_DIR_PATCH_TARGET, return_value=tmp_path),
            patch(_OWED_PATCH_TARGET, return_value=True),
        ):
            decisions = [handler.handle(_cron_hook_input("sess-1")).decision for _ in range(12)]
        delivered = [i + 1 for i, d in enumerate(decisions) if d == Decision.ALLOW]
        assert delivered == [1, 3, 7, 11]


class TestMatchesSeesTheResetOpportunity:
    """Task 4.3 is dead code unless matches() widens.

    In row 4 ("nothing owed, nothing declared") there is by definition no
    MARKER, so the existing ``marker_path.exists()`` fallback returns False for
    a real user prompt -- handle() never runs and the cadence is never reset.
    The failure is invisible: ticks simply stay sparse after the owner returns.
    """

    def test_real_prompt_matches_when_only_a_cadence_file_exists(self, tmp_path: Path) -> None:
        write_cadence(tmp_path / CADENCE_FILENAME, CadenceState("sess-1", 1, 2))
        handler = FailsafeCronBlockageSuppressorHandler()
        with patch(_DAEMON_UNTRACKED_DIR_PATCH_TARGET, return_value=tmp_path):
            assert handler.matches(_real_hook_input("sess-1")) is True

    def test_real_prompt_still_does_not_match_when_neither_file_exists(
        self, tmp_path: Path
    ) -> None:
        handler = FailsafeCronBlockageSuppressorHandler()
        with patch(_DAEMON_UNTRACKED_DIR_PATCH_TARGET, return_value=tmp_path):
            assert handler.matches(_real_hook_input("sess-1")) is False


class TestCadenceFailsOpen:
    def test_an_unreadable_cadence_file_allows(self, tmp_path: Path) -> None:
        (tmp_path / CADENCE_FILENAME).write_text("{not json", encoding="utf-8")
        handler = _backoff_handler()
        with (
            patch(_DAEMON_UNTRACKED_DIR_PATCH_TARGET, return_value=tmp_path),
            patch(_OWED_PATCH_TARGET, return_value=False),
        ):
            result = handler.handle(_cron_hook_input("sess-1"))
        assert result.decision == Decision.ALLOW

    def test_a_raising_ledger_consult_allows(self, tmp_path: Path) -> None:
        """_work_is_owed swallows its own errors and returns None, but if a new
        failure mode ever escaped it, the tick must still get through."""
        handler = _backoff_handler()
        with (
            patch(_DAEMON_UNTRACKED_DIR_PATCH_TARGET, return_value=tmp_path),
            patch(_OWED_PATCH_TARGET, side_effect=OSError("boom")),
        ):
            result = handler.handle(_cron_hook_input("sess-1"))
        assert result.decision == Decision.ALLOW
