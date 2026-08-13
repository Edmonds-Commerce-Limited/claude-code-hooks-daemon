"""Tests for SuggestStatusLineHandler."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.handlers.session_start import SuggestStatusLineHandler

# is_resume_session is a shared utility (utils/session_helpers.py); patch it
# where this module imports it. Edge-case coverage for the function itself
# lives in tests/unit/utils/test_session_helpers.py.
_IS_RESUME_SESSION = (
    "claude_code_hooks_daemon.handlers.session_start.suggest_statusline.is_resume_session"
)


class TestSuggestStatusLineHandler:
    """Tests for SuggestStatusLineHandler."""

    @pytest.fixture
    def handler(self) -> SuggestStatusLineHandler:
        """Create handler instance."""
        return SuggestStatusLineHandler()

    def test_handler_properties(self, handler: SuggestStatusLineHandler) -> None:
        """Test handler has correct properties."""
        assert handler.name == "suggest-statusline"
        assert handler.priority == 55
        assert handler.terminal is False
        assert "advisory" in handler.tags
        assert "workflow" in handler.tags
        assert "statusline" in handler.tags

    def test_matches_new_session_no_statusline(self, handler: SuggestStatusLineHandler) -> None:
        """Handler matches on new sessions when status line is not configured."""
        with (
            patch(_IS_RESUME_SESSION, return_value=False),
            patch.object(handler, "_is_statusline_configured", return_value=False),
        ):
            assert handler.matches({}) is True

    def test_matches_returns_false_on_resume_session(
        self, handler: SuggestStatusLineHandler
    ) -> None:
        """Handler does not match on resumed sessions."""
        with patch(_IS_RESUME_SESSION, return_value=True):
            assert handler.matches({}) is False

    def test_matches_returns_false_when_statusline_configured(
        self, handler: SuggestStatusLineHandler
    ) -> None:
        """Handler does not match when status line is already configured."""
        with (
            patch(_IS_RESUME_SESSION, return_value=False),
            patch.object(handler, "_is_statusline_configured", return_value=True),
        ):
            assert handler.matches({}) is False

    def test_handle_returns_suggestion(self, handler: SuggestStatusLineHandler) -> None:
        """Test handler returns status line setup suggestion."""
        result = handler.handle({})

        assert result.decision == "allow"
        assert len(result.context) > 0

        # Check for key elements in suggestion
        context_text = "\n".join(result.context)
        assert "Status Line Available" in context_text
        assert ".claude/settings.json" in context_text
        assert "statusLine" in context_text
        assert ".claude/hooks/status-line" in context_text

    def test_suggestion_includes_example_config(self, handler: SuggestStatusLineHandler) -> None:
        """Test suggestion includes example JSON configuration."""
        result = handler.handle({})

        context_text = "\n".join(result.context)
        assert "```json" in context_text
        assert '"type": "command"' in context_text
        assert '"command": ".claude/hooks/status-line"' in context_text

    def test_suggestion_includes_refresh_interval(self, handler: SuggestStatusLineHandler) -> None:
        """The example config recommends refreshInterval and explains why.

        Plan 00158 Phase 3: without a timer the status line freezes while the
        session is idle, so the clock stalls and the multithread indicator
        (🧵 Y/X) under-counts idle sibling threads.
        """
        result = handler.handle({})

        context_text = "\n".join(result.context)
        assert '"refreshInterval"' in context_text
        assert "refreshInterval" in context_text
        assert "🧵" in context_text

    def test_suggestion_describes_features(self, handler: SuggestStatusLineHandler) -> None:
        """Test suggestion describes what status line shows."""
        result = handler.handle({})

        context_text = "\n".join(result.context)
        assert "model name" in context_text
        assert "context usage" in context_text
        assert "git branch" in context_text
        assert "daemon health" in context_text

    def test_matches_returns_false_for_resume_session(
        self, handler: SuggestStatusLineHandler, tmp_path: "Path"
    ) -> None:
        """matches returns False when session is a resume (large transcript)."""
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text("x" * 200)
        hook_input = {"transcript_path": str(transcript)}
        assert handler.matches(hook_input) is False

    def test_matches_returns_false_when_statusline_configured_with_settings_file(
        self, handler: SuggestStatusLineHandler, tmp_path: "Path", monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """matches returns False when statusline is already configured."""
        import json

        config_dir = tmp_path / ".claude"
        config_dir.mkdir()
        settings_file = config_dir / "settings.json"
        settings_file.write_text(json.dumps({"statusLine": {"type": "command"}}))

        monkeypatch.setattr(
            "claude_code_hooks_daemon.handlers.session_start.suggest_statusline.ProjectContext.config_dir",
            staticmethod(lambda: config_dir),
        )
        assert handler.matches({}) is False

    def test_get_acceptance_tests_returns_non_empty(
        self, handler: SuggestStatusLineHandler
    ) -> None:
        """get_acceptance_tests returns a non-empty list."""
        tests = handler.get_acceptance_tests()
        assert isinstance(tests, list)
        assert len(tests) > 0


class TestSuggestionDecay:
    """A suggestion that repeats forever stops being a suggestion (Plan 00234).

    This was the only "decide once" advisory in the SessionStart cohort with no
    backoff of any kind. A project that looked at the status line and chose not
    to use it got the same pitch at the top of every new session, for ever —
    and silence is the only way a user can express "no thanks", because there
    is nothing to configure when you have declined.

    So the pitch is finite: after ``_MAX_SUGGESTIONS`` unheeded showings it
    goes quiet. Acting on it silences it immediately via the existing
    ``statusLine``-configured check.
    """

    @pytest.fixture
    def handler(self, tmp_path: Path) -> SuggestStatusLineHandler:
        h = SuggestStatusLineHandler()
        state = tmp_path / "statusline_suggestion_state.json"
        h._state_file_override = state
        return h

    def _show(self, handler: SuggestStatusLineHandler) -> bool:
        """One session: does it suggest, and record the showing if so."""
        with (
            patch(_IS_RESUME_SESSION, return_value=False),
            patch.object(handler, "_is_statusline_configured", return_value=False),
        ):
            if not handler.matches({}):
                return False
            handler.handle({})
            return True

    def test_suggests_on_the_first_session(self, handler: SuggestStatusLineHandler) -> None:
        assert self._show(handler) is True

    def test_stops_after_the_maximum_number_of_showings(
        self, handler: SuggestStatusLineHandler
    ) -> None:
        from claude_code_hooks_daemon.handlers.session_start.suggest_statusline import (
            _MAX_SUGGESTIONS,
        )

        shown = [self._show(handler) for _ in range(_MAX_SUGGESTIONS + 3)]

        assert shown[:_MAX_SUGGESTIONS] == [True] * _MAX_SUGGESTIONS
        assert not any(shown[_MAX_SUGGESTIONS:])

    def test_count_survives_a_new_handler_instance(self, tmp_path: Path) -> None:
        """The daemon restarts; the user's disinterest does not reset with it.

        In-memory state would make the cap meaningless — a restart every few
        hours would re-open the pitch indefinitely.
        """
        from claude_code_hooks_daemon.handlers.session_start.suggest_statusline import (
            _MAX_SUGGESTIONS,
        )

        state = tmp_path / "statusline_suggestion_state.json"
        for _ in range(_MAX_SUGGESTIONS):
            handler = SuggestStatusLineHandler()
            handler._state_file_override = state
            assert self._show(handler) is True

        fresh = SuggestStatusLineHandler()
        fresh._state_file_override = state
        assert self._show(fresh) is False

    def test_unreadable_state_file_still_suggests(self, handler: SuggestStatusLineHandler) -> None:
        """Fail OPEN: a broken counter must not silently disable the advisory.

        The counter exists to reduce noise, not to gate correctness, so a
        corrupt file degrades to "suggest" rather than "stay silent for ever"
        — a silent handler is indistinguishable from a working one.
        """
        state = handler._state_file_override
        state.write_text("{ not json")

        assert self._show(handler) is True


class TestIsStatusLineConfigured:
    """Tests for _is_statusline_configured private method."""

    @pytest.fixture
    def handler(self) -> SuggestStatusLineHandler:
        """Create handler instance."""
        return SuggestStatusLineHandler()

    def test_settings_file_does_not_exist(
        self, handler: SuggestStatusLineHandler, tmp_path: Path
    ) -> None:
        """Returns False when settings.json does not exist."""
        with patch(
            "claude_code_hooks_daemon.handlers.session_start.suggest_statusline.ProjectContext.config_dir",
            return_value=tmp_path,
        ):
            assert handler._is_statusline_configured() is False

    def test_settings_file_has_statusline(
        self, handler: SuggestStatusLineHandler, tmp_path: Path
    ) -> None:
        """Returns True when settings.json contains statusLine key."""
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(json.dumps({"statusLine": {"type": "command"}}))
        with patch(
            "claude_code_hooks_daemon.handlers.session_start.suggest_statusline.ProjectContext.config_dir",
            return_value=tmp_path,
        ):
            assert handler._is_statusline_configured() is True

    def test_settings_file_without_statusline(
        self, handler: SuggestStatusLineHandler, tmp_path: Path
    ) -> None:
        """Returns False when settings.json does not contain statusLine key."""
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(json.dumps({"hooks": {}}))
        with patch(
            "claude_code_hooks_daemon.handlers.session_start.suggest_statusline.ProjectContext.config_dir",
            return_value=tmp_path,
        ):
            assert handler._is_statusline_configured() is False

    def test_invalid_json_returns_false(
        self, handler: SuggestStatusLineHandler, tmp_path: Path
    ) -> None:
        """Returns False when settings.json contains invalid JSON."""
        settings_file = tmp_path / "settings.json"
        settings_file.write_text("not valid json {{{")
        with patch(
            "claude_code_hooks_daemon.handlers.session_start.suggest_statusline.ProjectContext.config_dir",
            return_value=tmp_path,
        ):
            assert handler._is_statusline_configured() is False

    def test_runtime_error_returns_false(self, handler: SuggestStatusLineHandler) -> None:
        """Returns False when ProjectContext.config_dir raises RuntimeError."""
        with patch(
            "claude_code_hooks_daemon.handlers.session_start.suggest_statusline.ProjectContext.config_dir",
            side_effect=RuntimeError("no project"),
        ):
            assert handler._is_statusline_configured() is False
