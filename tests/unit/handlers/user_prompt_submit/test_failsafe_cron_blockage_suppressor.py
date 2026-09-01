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

from claude_code_hooks_daemon.constants import HandlerID, Priority
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
