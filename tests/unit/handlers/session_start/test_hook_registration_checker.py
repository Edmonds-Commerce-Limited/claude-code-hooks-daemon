"""Tests for HookRegistrationCheckerHandler."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.handlers.session_start.hook_registration_checker import (
    HookRegistrationCheckerHandler,
)


def _session_start_input(transcript_path: str | None = None) -> dict[str, Any]:
    """Build a minimal SessionStart hook_input."""
    hook_input: dict[str, Any] = {"hook_event_name": "SessionStart"}
    if transcript_path is not None:
        hook_input["transcript_path"] = transcript_path
    return hook_input


def _build_valid_settings() -> dict[str, Any]:
    """Build a settings.json dict with all hooks properly registered."""
    from claude_code_hooks_daemon.utils.hook_registration import HOOK_EVENTS_IN_SETTINGS

    hooks: dict[str, Any] = {}
    for json_key, bash_key in HOOK_EVENTS_IN_SETTINGS.items():
        hooks[json_key] = [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": f'"$CLAUDE_PROJECT_DIR"/.claude/hooks/{bash_key}',
                        "timeout": 60,
                    }
                ]
            }
        ]
    return {"hooks": hooks}


class TestHookRegistrationCheckerInit:
    """Handler initialisation tests."""

    @pytest.fixture()
    def handler(self) -> HookRegistrationCheckerHandler:
        return HookRegistrationCheckerHandler()

    def test_init_sets_correct_name(self, handler: HookRegistrationCheckerHandler) -> None:
        assert handler.name == "hook-registration-checker"

    def test_init_sets_correct_priority(self, handler: HookRegistrationCheckerHandler) -> None:
        assert handler.priority == 51

    def test_init_sets_terminal_false(self, handler: HookRegistrationCheckerHandler) -> None:
        assert handler.terminal is False

    def test_init_sets_config_key(self, handler: HookRegistrationCheckerHandler) -> None:
        assert handler.config_key == "hook_registration_checker"


class TestHookRegistrationCheckerMatches:
    """matches() tests."""

    @pytest.fixture()
    def handler(self) -> HookRegistrationCheckerHandler:
        return HookRegistrationCheckerHandler()

    def test_matches_new_session_returns_true(
        self, handler: HookRegistrationCheckerHandler
    ) -> None:
        hook_input = _session_start_input()
        assert handler.matches(hook_input) is True

    def test_matches_resume_session_returns_false(
        self, handler: HookRegistrationCheckerHandler, tmp_path: Path
    ) -> None:
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text("x" * 200)
        hook_input = _session_start_input(str(transcript))
        assert handler.matches(hook_input) is False

    def test_matches_small_transcript_returns_true(
        self, handler: HookRegistrationCheckerHandler, tmp_path: Path
    ) -> None:
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text("{}")
        hook_input = _session_start_input(str(transcript))
        assert handler.matches(hook_input) is True

    def test_matches_nonexistent_transcript_returns_true(
        self, handler: HookRegistrationCheckerHandler
    ) -> None:
        hook_input = _session_start_input("/nonexistent/path.jsonl")
        assert handler.matches(hook_input) is True


class TestHookRegistrationCheckerHandle:
    """handle() tests."""

    @pytest.fixture()
    def handler(self) -> HookRegistrationCheckerHandler:
        return HookRegistrationCheckerHandler()

    def test_all_hooks_present_no_duplicates(
        self, handler: HookRegistrationCheckerHandler, tmp_path: Path
    ) -> None:
        """All hooks registered, no local duplicates -> clean result."""
        settings_path = tmp_path / ".claude" / "settings.json"
        settings_path.parent.mkdir(parents=True)
        settings_path.write_text(json.dumps(_build_valid_settings()))

        local_path = tmp_path / ".claude" / "settings.local.json"
        local_path.write_text(json.dumps({"permissions": {}}))

        with patch.object(handler, "_get_project_root", return_value=tmp_path):
            result = handler.handle(_session_start_input())

        assert result.decision.value == "allow"
        # Should have a "passed" message in context
        context_text = "\n".join(result.context)
        assert "passed" in context_text.lower() or "ok" in context_text.lower()

    def test_missing_hooks_reported(
        self, handler: HookRegistrationCheckerHandler, tmp_path: Path
    ) -> None:
        """Missing hooks should be reported in context."""
        settings = _build_valid_settings()
        del settings["hooks"]["Stop"]
        del settings["hooks"]["PreToolUse"]

        settings_path = tmp_path / ".claude" / "settings.json"
        settings_path.parent.mkdir(parents=True)
        settings_path.write_text(json.dumps(settings))

        with patch.object(handler, "_get_project_root", return_value=tmp_path):
            result = handler.handle(_session_start_input())

        assert result.decision.value == "allow"
        context_text = "\n".join(result.context)
        assert "Stop" in context_text
        assert "PreToolUse" in context_text

    def test_duplicate_hooks_reported(
        self, handler: HookRegistrationCheckerHandler, tmp_path: Path
    ) -> None:
        """Duplicate hooks in settings.local.json should be reported."""
        settings_path = tmp_path / ".claude" / "settings.json"
        settings_path.parent.mkdir(parents=True)
        settings_path.write_text(json.dumps(_build_valid_settings()))

        local_settings = {
            "hooks": {
                "Stop": [{"hooks": [{"type": "command", "command": ".claude/hooks/stop"}]}],
            }
        }
        local_path = tmp_path / ".claude" / "settings.local.json"
        local_path.write_text(json.dumps(local_settings))

        with patch.object(handler, "_get_project_root", return_value=tmp_path):
            result = handler.handle(_session_start_input())

        assert result.decision.value == "allow"
        context_text = "\n".join(result.context)
        assert "Duplicate" in context_text or "duplicate" in context_text
        assert "Stop" in context_text

    def test_wrong_command_reported(
        self, handler: HookRegistrationCheckerHandler, tmp_path: Path
    ) -> None:
        """Wrong hook command paths should be reported."""
        settings = _build_valid_settings()
        settings["hooks"]["Stop"] = [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": '"$CLAUDE_PROJECT_DIR"/.claude/hooks/wrong-script',
                    }
                ]
            }
        ]

        settings_path = tmp_path / ".claude" / "settings.json"
        settings_path.parent.mkdir(parents=True)
        settings_path.write_text(json.dumps(settings))

        with patch.object(handler, "_get_project_root", return_value=tmp_path):
            result = handler.handle(_session_start_input())

        assert result.decision.value == "allow"
        context_text = "\n".join(result.context)
        assert "Stop" in context_text
        assert "wrong-script" in context_text

    def test_no_settings_file_graceful(
        self, handler: HookRegistrationCheckerHandler, tmp_path: Path
    ) -> None:
        """Missing settings.json should return empty context gracefully."""
        with patch.object(handler, "_get_project_root", return_value=tmp_path):
            result = handler.handle(_session_start_input())

        assert result.decision.value == "allow"

    def test_no_local_settings_file_ok(
        self, handler: HookRegistrationCheckerHandler, tmp_path: Path
    ) -> None:
        """Missing settings.local.json is normal — no duplicate warnings."""
        settings_path = tmp_path / ".claude" / "settings.json"
        settings_path.parent.mkdir(parents=True)
        settings_path.write_text(json.dumps(_build_valid_settings()))
        # No settings.local.json

        with patch.object(handler, "_get_project_root", return_value=tmp_path):
            result = handler.handle(_session_start_input())

        assert result.decision.value == "allow"
        context_text = "\n".join(result.context)
        assert "duplicate" not in context_text.lower()

    def test_no_project_root_graceful(self, handler: HookRegistrationCheckerHandler) -> None:
        """If project root cannot be determined, return gracefully."""
        with patch.object(handler, "_get_project_root", return_value=None):
            result = handler.handle(_session_start_input())

        assert result.decision.value == "allow"
        assert result.context == []


class TestHookRegistrationCheckerClaudeMd:
    """get_claude_md() tests."""

    def test_returns_none(self) -> None:
        """No CLAUDE.md guidance needed for a startup check."""
        handler = HookRegistrationCheckerHandler()
        assert handler.get_claude_md() is None


class TestHookRegistrationCheckerAcceptanceTests:
    """get_acceptance_tests() tests."""

    def test_returns_list(self) -> None:
        handler = HookRegistrationCheckerHandler()
        tests = handler.get_acceptance_tests()
        assert isinstance(tests, list)
        assert len(tests) >= 1
