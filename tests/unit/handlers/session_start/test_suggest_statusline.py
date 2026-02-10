"""Tests for SuggestStatusLineHandler."""

from pathlib import Path

import pytest

from claude_code_hooks_daemon.handlers.session_start import SuggestStatusLineHandler


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

    def test_matches_always_returns_true(self, handler: SuggestStatusLineHandler) -> None:
        """Handler should always match for session start events."""
        assert handler.matches({}) is True
        assert handler.matches({"session_id": "test"}) is True

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

    def test_suggestion_describes_features(self, handler: SuggestStatusLineHandler) -> None:
        """Test suggestion describes what status line shows."""
        result = handler.handle({})

        context_text = "\n".join(result.context)
        assert "model name" in context_text
        assert "context usage" in context_text
        assert "git branch" in context_text
        assert "daemon health" in context_text

    def test_is_resume_session_with_large_file(
        self, handler: SuggestStatusLineHandler, tmp_path: "Path"
    ) -> None:
        """_is_resume_session returns True for transcript file >100 bytes."""
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text("x" * 200)
        hook_input = {"transcript_path": str(transcript)}
        assert handler._is_resume_session(hook_input) is True

    def test_is_resume_session_with_small_file(
        self, handler: SuggestStatusLineHandler, tmp_path: "Path"
    ) -> None:
        """_is_resume_session returns False for transcript file <=100 bytes."""
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text("x" * 50)
        hook_input = {"transcript_path": str(transcript)}
        assert handler._is_resume_session(hook_input) is False

    def test_is_resume_session_no_transcript_path(self, handler: SuggestStatusLineHandler) -> None:
        """_is_resume_session returns False when no transcript_path."""
        assert handler._is_resume_session({}) is False

    def test_is_resume_session_nonexistent_file(self, handler: SuggestStatusLineHandler) -> None:
        """_is_resume_session returns False for nonexistent file."""
        hook_input = {"transcript_path": "/nonexistent/path.jsonl"}
        assert handler._is_resume_session(hook_input) is False

    def test_is_resume_session_oserror(
        self, handler: SuggestStatusLineHandler, tmp_path: "Path", monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """_is_resume_session returns False on OSError from stat."""
        import pathlib

        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text("x" * 200)

        original_stat = pathlib.Path.stat

        def mock_stat(self_path, *args, **kwargs):
            if self_path == transcript:
                raise OSError("Permission denied")
            return original_stat(self_path, *args, **kwargs)

        monkeypatch.setattr(pathlib.Path, "stat", mock_stat)
        hook_input = {"transcript_path": str(transcript)}
        assert handler._is_resume_session(hook_input) is False

    def test_is_statusline_configured_true(
        self, handler: SuggestStatusLineHandler, tmp_path: "Path", monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """_is_statusline_configured returns True when settings has statusLine."""
        import json

        config_dir = tmp_path / ".claude"
        config_dir.mkdir()
        settings_file = config_dir / "settings.json"
        settings_file.write_text(json.dumps({"statusLine": {"type": "command"}}))

        monkeypatch.setattr(
            "claude_code_hooks_daemon.handlers.session_start.suggest_statusline.ProjectContext.config_dir",
            staticmethod(lambda: config_dir),
        )
        assert handler._is_statusline_configured() is True

    def test_is_statusline_configured_false_no_key(
        self, handler: SuggestStatusLineHandler, tmp_path: "Path", monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """_is_statusline_configured returns False when statusLine not in settings."""
        import json

        config_dir = tmp_path / ".claude"
        config_dir.mkdir()
        settings_file = config_dir / "settings.json"
        settings_file.write_text(json.dumps({"other_key": "value"}))

        monkeypatch.setattr(
            "claude_code_hooks_daemon.handlers.session_start.suggest_statusline.ProjectContext.config_dir",
            staticmethod(lambda: config_dir),
        )
        assert handler._is_statusline_configured() is False

    def test_is_statusline_configured_json_decode_error(
        self, handler: SuggestStatusLineHandler, tmp_path: "Path", monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """_is_statusline_configured returns False on JSONDecodeError."""
        config_dir = tmp_path / ".claude"
        config_dir.mkdir()
        settings_file = config_dir / "settings.json"
        settings_file.write_text("not valid json{{{")

        monkeypatch.setattr(
            "claude_code_hooks_daemon.handlers.session_start.suggest_statusline.ProjectContext.config_dir",
            staticmethod(lambda: config_dir),
        )
        assert handler._is_statusline_configured() is False

    def test_is_statusline_configured_no_settings_file(
        self, handler: SuggestStatusLineHandler, tmp_path: "Path", monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """_is_statusline_configured returns False when settings.json does not exist."""
        config_dir = tmp_path / ".claude"
        config_dir.mkdir()

        monkeypatch.setattr(
            "claude_code_hooks_daemon.handlers.session_start.suggest_statusline.ProjectContext.config_dir",
            staticmethod(lambda: config_dir),
        )
        assert handler._is_statusline_configured() is False

    def test_matches_returns_false_for_resume_session(
        self, handler: SuggestStatusLineHandler, tmp_path: "Path"
    ) -> None:
        """matches returns False when session is a resume (large transcript)."""
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text("x" * 200)
        hook_input = {"transcript_path": str(transcript)}
        assert handler.matches(hook_input) is False

    def test_matches_returns_false_when_statusline_configured(
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
