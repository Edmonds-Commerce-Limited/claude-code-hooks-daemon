"""Tests for version check handler.

Tests version checking on new sessions with 1-day cache.
"""

import json
import subprocess
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from claude_code_hooks_daemon.constants import HandlerID, Priority
from claude_code_hooks_daemon.core.hook_result import Decision
from claude_code_hooks_daemon.handlers.session_start.version_check import VersionCheckHandler


@pytest.fixture
def handler() -> VersionCheckHandler:
    """Create handler instance."""
    return VersionCheckHandler()


@pytest.fixture
def new_session_input(tmp_path: Path) -> dict:
    """SessionStart input for new session (no transcript)."""
    return {
        "hook_event_name": "SessionStart",
        "session_id": "test-session-123",
        "transcript_path": str(tmp_path / "nonexistent.jsonl"),
        "cwd": "/workspace",
    }


@pytest.fixture
def resume_session_input(tmp_path: Path) -> dict:
    """SessionStart input for resumed session (transcript exists with content)."""
    transcript = tmp_path / "resume.jsonl"
    transcript.write_text("A" * 200)  # >100 bytes = resume
    return {
        "hook_event_name": "SessionStart",
        "session_id": "test-session-456",
        "transcript_path": str(transcript),
        "cwd": "/workspace",
    }


def test_handler_initialization(handler: VersionCheckHandler) -> None:
    """Test handler is initialized correctly."""
    assert handler.handler_id == HandlerID.VERSION_CHECK
    assert handler.priority == Priority.VERSION_CHECK
    assert handler.terminal is False


def test_matches_new_session(handler: VersionCheckHandler, new_session_input: dict) -> None:
    """Handler matches new SessionStart events."""
    assert handler.matches(new_session_input) is True


def test_matches_resume_session_returns_false(
    handler: VersionCheckHandler, resume_session_input: dict
) -> None:
    """Handler does NOT match resumed sessions."""
    assert handler.matches(resume_session_input) is False


def test_matches_other_events_returns_false(handler: VersionCheckHandler) -> None:
    """Handler does not match non-SessionStart events."""
    hook_input = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
    }
    assert handler.matches(hook_input) is False


def test_matches_disabled_returns_false(
    handler: VersionCheckHandler, new_session_input: dict
) -> None:
    """Handler does not match when disabled."""
    handler.configure({"enabled": False})
    assert handler.matches(new_session_input) is False


def test_is_resume_session_detects_empty_transcript(
    handler: VersionCheckHandler, tmp_path: Path
) -> None:
    """Empty transcript file is NOT a resume."""
    transcript = tmp_path / "empty.jsonl"
    transcript.write_text("")

    hook_input = {"transcript_path": str(transcript)}
    assert handler._is_resume_session(hook_input) is False


def test_is_resume_session_detects_small_transcript(
    handler: VersionCheckHandler, tmp_path: Path
) -> None:
    """Small transcript (<100 bytes) is NOT a resume."""
    transcript = tmp_path / "small.jsonl"
    transcript.write_text("A" * 50)

    hook_input = {"transcript_path": str(transcript)}
    assert handler._is_resume_session(hook_input) is False


def test_is_resume_session_detects_large_transcript(
    handler: VersionCheckHandler, tmp_path: Path
) -> None:
    """Large transcript (>100 bytes) IS a resume."""
    transcript = tmp_path / "large.jsonl"
    transcript.write_text("A" * 200)

    hook_input = {"transcript_path": str(transcript)}
    assert handler._is_resume_session(hook_input) is True


def test_is_resume_session_handles_missing_transcript(
    handler: VersionCheckHandler,
) -> None:
    """Missing transcript is NOT a resume."""
    hook_input = {"transcript_path": "/nonexistent/path.jsonl"}
    assert handler._is_resume_session(hook_input) is False


def test_is_resume_session_handles_no_path(handler: VersionCheckHandler) -> None:
    """No transcript_path field is NOT a resume."""
    hook_input: dict = {}
    assert handler._is_resume_session(hook_input) is False


def test_compare_versions_detects_outdated(handler: VersionCheckHandler) -> None:
    """Version comparison detects outdated versions."""
    assert handler._compare_versions("2.6.1", "2.7.0") is True
    assert handler._compare_versions("2.6.0", "2.6.1") is True
    assert handler._compare_versions("1.9.9", "2.0.0") is True


def test_compare_versions_detects_up_to_date(handler: VersionCheckHandler) -> None:
    """Version comparison detects up-to-date versions."""
    assert handler._compare_versions("2.7.0", "2.7.0") is False
    assert handler._compare_versions("2.7.1", "2.7.0") is False
    assert handler._compare_versions("3.0.0", "2.9.9") is False


def test_compare_versions_handles_different_lengths(
    handler: VersionCheckHandler,
) -> None:
    """Version comparison handles different length version strings."""
    assert handler._compare_versions("2.6", "2.6.1") is True
    assert handler._compare_versions("2.6.1", "2.6") is False


def test_compare_versions_handles_invalid_versions(
    handler: VersionCheckHandler,
) -> None:
    """Version comparison returns False on parse errors."""
    assert handler._compare_versions("invalid", "2.7.0") is False
    assert handler._compare_versions("2.7.0", "invalid") is False


def test_cache_validity_fresh_cache(handler: VersionCheckHandler, tmp_path: Path) -> None:
    """Cache is valid when recent."""
    cache_file = tmp_path / "cache.json"
    cache_data = {
        "cached_at": time.time(),
        "current_version": "2.6.1",
        "latest_version": "2.6.1",
        "is_outdated": False,
    }
    cache_file.write_text(json.dumps(cache_data))

    assert handler._is_cache_valid(cache_file) is True


def test_cache_validity_expired_cache(handler: VersionCheckHandler, tmp_path: Path) -> None:
    """Cache is invalid when expired."""
    cache_file = tmp_path / "cache.json"
    cache_data = {
        "cached_at": time.time() - (25 * 3600),  # 25 hours ago
        "current_version": "2.6.1",
        "latest_version": "2.6.1",
        "is_outdated": False,
    }
    cache_file.write_text(json.dumps(cache_data))

    assert handler._is_cache_valid(cache_file) is False


def test_cache_validity_missing_cache(handler: VersionCheckHandler, tmp_path: Path) -> None:
    """Cache is invalid when file doesn't exist."""
    cache_file = tmp_path / "nonexistent.json"
    assert handler._is_cache_valid(cache_file) is False


def test_cache_validity_malformed_cache(handler: VersionCheckHandler, tmp_path: Path) -> None:
    """Cache is invalid when malformed."""
    cache_file = tmp_path / "bad.json"
    cache_file.write_text("not valid json")

    assert handler._is_cache_valid(cache_file) is False


@patch("claude_code_hooks_daemon.handlers.session_start.version_check.__version__", "2.6.1")
@patch("claude_code_hooks_daemon.handlers.session_start.version_check.subprocess.run")
def test_handle_returns_upgrade_notice_when_outdated(
    mock_run: MagicMock,
    handler: VersionCheckHandler,
    new_session_input: dict,
    tmp_path: Path,
) -> None:
    """Handler returns upgrade notice when version is outdated."""
    # Mock git ls-remote response
    mock_run.return_value = MagicMock(
        returncode=0,
        stdout="abc123\trefs/tags/v2.7.0\n",
    )

    # Use tmp_path for cache
    with patch.object(handler, "_get_cache_file", return_value=tmp_path / "cache.json"):
        result = handler.handle(new_session_input)

    assert result.decision == Decision.ALLOW
    assert result.context is not None
    assert len(result.context) > 0
    assert "update available" in result.context[0].lower()
    assert "2.7.0" in result.context[0]


@patch("claude_code_hooks_daemon.handlers.session_start.version_check.__version__", "2.7.0")
@patch("claude_code_hooks_daemon.handlers.session_start.version_check.subprocess.run")
def test_handle_returns_no_context_when_up_to_date(
    mock_run: MagicMock,
    handler: VersionCheckHandler,
    new_session_input: dict,
    tmp_path: Path,
) -> None:
    """Handler returns no context when version is up-to-date."""
    # Mock git ls-remote response
    mock_run.return_value = MagicMock(
        returncode=0,
        stdout="abc123\trefs/tags/v2.7.0\n",
    )

    # Use tmp_path for cache
    with patch.object(handler, "_get_cache_file", return_value=tmp_path / "cache.json"):
        result = handler.handle(new_session_input)

    assert result.decision == Decision.ALLOW
    assert result.context == []


@patch("claude_code_hooks_daemon.handlers.session_start.version_check.subprocess.run")
def test_handle_uses_cache_when_valid(
    mock_run: MagicMock,
    handler: VersionCheckHandler,
    new_session_input: dict,
    tmp_path: Path,
) -> None:
    """Handler uses cache and doesn't call git when cache is valid."""
    # Create valid cache showing we're up-to-date
    cache_file = tmp_path / "cache.json"
    cache_data = {
        "cached_at": time.time(),
        "current_version": "2.7.0",
        "latest_version": "2.7.0",
        "is_outdated": False,
    }
    cache_file.write_text(json.dumps(cache_data))

    with patch.object(handler, "_get_cache_file", return_value=cache_file):
        result = handler.handle(new_session_input)

    # Should not have called git
    mock_run.assert_not_called()

    assert result.decision == Decision.ALLOW
    assert result.context == []


@patch("claude_code_hooks_daemon.handlers.session_start.version_check.subprocess.run")
def test_handle_writes_cache_after_check(
    mock_run: MagicMock,
    handler: VersionCheckHandler,
    new_session_input: dict,
    tmp_path: Path,
) -> None:
    """Handler writes cache after checking version."""
    # Mock git ls-remote response
    mock_run.return_value = MagicMock(
        returncode=0,
        stdout="abc123\trefs/tags/v2.7.0\n",
    )

    cache_file = tmp_path / "cache.json"
    with patch.object(handler, "_get_cache_file", return_value=cache_file):
        handler.handle(new_session_input)

    # Cache should be written
    assert cache_file.exists()
    cache_data = json.loads(cache_file.read_text())
    assert "cached_at" in cache_data
    assert "current_version" in cache_data
    assert "latest_version" in cache_data
    assert "is_outdated" in cache_data


@patch("claude_code_hooks_daemon.handlers.session_start.version_check.subprocess.run")
def test_handle_fails_silently_on_git_error(
    mock_run: MagicMock,
    handler: VersionCheckHandler,
    new_session_input: dict,
    tmp_path: Path,
) -> None:
    """Handler fails silently when git command fails."""
    # Mock git failure
    mock_run.return_value = MagicMock(
        returncode=1,
        stderr="fatal: unable to access repository",
    )

    with patch.object(handler, "_get_cache_file", return_value=tmp_path / "cache.json"):
        result = handler.handle(new_session_input)

    assert result.decision == Decision.ALLOW
    assert result.context == []


def test_handle_catches_unexpected_exception(
    handler: VersionCheckHandler,
    new_session_input: dict,
) -> None:
    """Handler catches unexpected exceptions in handle() and returns ALLOW."""
    with patch.object(handler, "_get_cache_file", side_effect=ValueError("unexpected")):
        result = handler.handle(new_session_input)

    assert result.decision == Decision.ALLOW
    assert result.context == []


def test_get_cache_file_fallback_on_project_context_error(
    handler: VersionCheckHandler,
) -> None:
    """_get_cache_file falls back when ProjectContext raises."""
    with patch(
        "claude_code_hooks_daemon.handlers.session_start.version_check.ProjectContext.daemon_untracked_dir",
        side_effect=RuntimeError("no project"),
    ):
        cache_file = handler._get_cache_file()

    assert cache_file.name == "version_check_cache.json"
    assert "untracked" in str(cache_file)


def test_get_cached_result_returns_none_on_error(
    handler: VersionCheckHandler, tmp_path: Path
) -> None:
    """_get_cached_result returns None on malformed JSON."""
    cache_file = tmp_path / "bad_cache.json"
    cache_file.write_text("not valid json")
    result = handler._get_cached_result(cache_file)
    assert result is None


def test_write_cache_handles_os_error(handler: VersionCheckHandler, tmp_path: Path) -> None:
    """_write_cache handles OSError gracefully."""
    # Use a path that can't be written (directory as file)
    cache_file = tmp_path / "readonly_dir" / "subdir" / "cache.json"
    # Create readonly_dir as a file to cause OSError
    (tmp_path / "readonly_dir").write_text("not a dir")

    # Should not raise
    handler._write_cache(cache_file, {"test": True})


def test_is_resume_session_handles_os_error(handler: VersionCheckHandler) -> None:
    """_is_resume_session returns False on OSError."""
    with patch("claude_code_hooks_daemon.handlers.session_start.version_check.Path") as mock_path:
        mock_path.return_value.exists.side_effect = OSError("permission denied")
        result = handler._is_resume_session({"transcript_path": "/some/path"})
    assert result is False


def test_get_latest_version_skips_empty_lines(handler: VersionCheckHandler) -> None:
    """_get_latest_version skips empty lines in git output."""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="\n\nabc123\trefs/tags/v2.7.0\n",
        )
        version = handler._get_latest_version()
        assert version == "2.7.0"


def test_get_latest_version_returns_none_on_empty_output(handler: VersionCheckHandler) -> None:
    """_get_latest_version returns None when git returns no tags."""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="\n\n",
        )
        version = handler._get_latest_version()
        assert version is None


def test_get_latest_version_parses_git_output(handler: VersionCheckHandler) -> None:
    """_get_latest_version parses git ls-remote output correctly."""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="abc123\trefs/tags/v2.7.0\ndef456\trefs/tags/v2.6.1\n",
        )

        version = handler._get_latest_version()
        assert version == "2.7.0"


def test_get_latest_version_handles_no_v_prefix(handler: VersionCheckHandler) -> None:
    """_get_latest_version handles tags without 'v' prefix."""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="abc123\trefs/tags/2.7.0\n",
        )

        version = handler._get_latest_version()
        assert version == "2.7.0"


def test_get_latest_version_returns_none_on_error(handler: VersionCheckHandler) -> None:
    """_get_latest_version returns None on git error."""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=1,
            stderr="error",
        )

        version = handler._get_latest_version()
        assert version is None


def test_get_latest_version_returns_none_on_timeout(handler: VersionCheckHandler) -> None:
    """_get_latest_version returns None on timeout."""
    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = subprocess.TimeoutExpired("git", 5)

        version = handler._get_latest_version()
        assert version is None
