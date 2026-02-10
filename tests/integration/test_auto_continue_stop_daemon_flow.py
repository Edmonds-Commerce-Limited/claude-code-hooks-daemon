"""Integration test: AutoContinueStop through DaemonController flow.

Bug: auto_continue_stop handler is configured and enabled but fails to fire
when Claude asks "Should I proceed with Phase 2?" in production. Unit tests
pass because they feed hook_input dicts directly to the handler, bypassing
the DaemonController's Pydantic model transformation.

Root cause: The handler reads hook_input.get("stop_hook_active", False) but
when Claude Code sends camelCase fields (stopHookActive), Pydantic stores them
as extra fields with original casing. model_dump() then produces "stopHookActive"
NOT "stop_hook_active". The handler's check returns the default False, which is
benign for the first invocation but creates an INFINITE LOOP risk: if
stop_hook_active=true (camelCase: stopHookActive=true), the handler won't detect
it and will keep blocking stops forever.

Additionally, the handler lacks logging, making production failures invisible.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

from claude_code_hooks_daemon.core.event import EventType, HookEvent, HookInput
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.daemon.controller import DaemonController


def _make_transcript(tmp_path: Path, message_text: str) -> Path:
    """Create a transcript JSONL file with an assistant message."""
    transcript_file = tmp_path / "transcript.jsonl"
    assistant_message = {
        "type": "message",
        "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": message_text}],
        },
    }
    transcript_file.write_text(json.dumps(assistant_message) + "\n")
    return transcript_file


def _make_realistic_transcript(tmp_path: Path, assistant_text: str) -> Path:
    """Create a realistic transcript with multiple entry types.

    Real transcripts have tool_use, tool_result, system, and progress entries
    interspersed with assistant messages. The assistant message with the
    confirmation question may NOT be the last line.
    """
    transcript_file = tmp_path / "transcript.jsonl"
    entries = [
        # Earlier user message
        {
            "type": "message",
            "message": {
                "role": "user",
                "content": [{"type": "text", "text": "Implement Phase 1"}],
            },
        },
        # Tool use by assistant
        {
            "type": "message",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "I'll start implementing Phase 1."},
                    {
                        "type": "tool_use",
                        "id": "toolu_01ABC",
                        "name": "Bash",
                        "input": {"command": "echo done"},
                    },
                ],
            },
        },
        # Tool result
        {
            "type": "tool_result",
            "tool_use_id": "toolu_01ABC",
            "content": "done\n",
        },
        # The confirmation question assistant message
        {
            "type": "message",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": assistant_text}],
            },
        },
        # Progress entry (written AFTER assistant message, BEFORE stop)
        {
            "type": "progress",
            "data": {"type": "hook_progress", "hookEvent": "Stop"},
        },
    ]

    with transcript_file.open("w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")

    return transcript_file


def _make_workspace(tmp_path: Path) -> Path:
    """Create a workspace with required dirs and config file."""
    workspace = tmp_path / "workspace"
    claude_dir = workspace / ".claude"
    claude_dir.mkdir(parents=True)
    git_dir = workspace / ".git"
    git_dir.mkdir()
    config_file = claude_dir / "hooks-daemon.yaml"
    config_file.write_text(
        "version: '1.0'\n"
        "daemon:\n"
        "  idle_timeout_seconds: 600\n"
        "  log_level: INFO\n"
        "handlers:\n"
        "  stop:\n"
        "    auto_continue_stop:\n"
        "      enabled: true\n"
        "      priority: 10\n"
        "    task_completion_checker:\n"
        "      enabled: false\n"
    )
    return workspace


def _mock_git_subprocess() -> Any:
    """Create mock for subprocess.run that simulates git commands."""
    return patch(
        "subprocess.run",
        side_effect=[
            Mock(returncode=0, stdout=b"/tmp/test\n"),  # git rev-parse --show-toplevel
            Mock(returncode=0, stdout=b"git@github.com:test/repo.git\n"),  # git remote get-url
            Mock(returncode=0, stdout=b"/tmp/test\n"),  # git rev-parse (again for toplevel)
        ],
    )


class TestAutoContinueStopDaemonFlow:
    """Test auto_continue_stop handler through the full DaemonController path."""

    def teardown_method(self) -> None:
        """Reset ProjectContext after each test."""
        ProjectContext.reset()

    def test_pydantic_model_dump_preserves_transcript_path(self, tmp_path: Path) -> None:
        """Verify model_dump(by_alias=False) preserves transcript_path."""
        transcript_file = _make_transcript(tmp_path, "Should I proceed?")

        raw_hook_input = {
            "hook_event_name": "Stop",
            "stop_hook_active": False,
            "transcript_path": str(transcript_file),
            "session_id": "test-session",
            "cwd": "/workspace",
        }

        hook_input_model = HookInput.model_validate(raw_hook_input)
        dumped = hook_input_model.model_dump(by_alias=False)

        assert (
            "transcript_path" in dumped
        ), f"model_dump(by_alias=False) lost transcript_path! Keys: {list(dumped.keys())}"
        assert dumped["transcript_path"] == str(transcript_file)

    def test_pydantic_model_dump_preserves_stop_hook_active(self) -> None:
        """Verify model_dump preserves stop_hook_active (an extra field)."""
        raw_hook_input = {
            "hook_event_name": "Stop",
            "stop_hook_active": True,
            "session_id": "test-session",
        }

        hook_input_model = HookInput.model_validate(raw_hook_input)
        dumped = hook_input_model.model_dump(by_alias=False)

        assert (
            "stop_hook_active" in dumped
        ), f"model_dump lost stop_hook_active! Keys: {list(dumped.keys())}"
        assert dumped["stop_hook_active"] is True

    def test_camelcase_stop_hook_active_detected_by_handler(self) -> None:
        """Handler detects stopHookActive in BOTH snake_case and camelCase.

        When Claude Code sends stopHookActive (camelCase), Pydantic stores it
        as an extra field with original casing. The handler must check BOTH
        variants to prevent infinite loops.
        """
        from claude_code_hooks_daemon.handlers.stop.auto_continue_stop import (
            AutoContinueStopHandler,
        )

        handler = AutoContinueStopHandler()

        # snake_case: standard check works
        snake_input = {"stop_hook_active": True, "transcript_path": "/some/path"}
        assert (
            handler.matches(snake_input) is False
        ), "snake_case stop_hook_active=True should prevent matching"

        # camelCase: handler must also detect this
        camel_input = {"stopHookActive": True, "transcript_path": "/some/path"}
        assert (
            handler.matches(camel_input) is False
        ), "camelCase stopHookActive=True should prevent matching (infinite loop prevention)"

    def test_full_daemon_controller_stop_event_with_confirmation(self, tmp_path: Path) -> None:
        """Full DaemonController flow: Stop event with confirmation question.

        Simulates: Claude asks "Should I proceed with Phase 2?" -> Stop fires -> handler blocks.
        """
        workspace = _make_workspace(tmp_path)
        transcript_file = _make_transcript(
            tmp_path,
            "**Next Phase**: Phase 2 - Python Config Preservation Engine\n\n"
            "Should I proceed with Phase 2?",
        )

        raw_request = {
            "event": "Stop",
            "hook_input": {
                "hook_event_name": "Stop",
                "stop_hook_active": False,
                "transcript_path": str(transcript_file),
                "session_id": "test-session",
                "cwd": str(workspace),
            },
        }

        controller = DaemonController()
        handler_config = {
            "stop": {
                "auto_continue_stop": {"enabled": True, "priority": 10},
                "task_completion_checker": {"enabled": False},
            }
        }

        with _mock_git_subprocess():
            controller.initialise(
                handler_config=handler_config,
                workspace_root=workspace,
            )

        response = controller.process_request(raw_request)

        assert response.get("decision") == "block", (
            f"Expected 'block' decision but got: {response}. "
            "The auto_continue_stop handler failed to match through the DaemonController flow."
        )
        assert "AUTO-CONTINUE" in response.get("reason", "")

    def test_realistic_transcript_with_mixed_entries(self, tmp_path: Path) -> None:
        """Handler finds assistant message in realistic transcript with mixed entry types.

        Real transcripts have tool_use, tool_result, progress entries after
        the assistant message. The handler must iterate backwards correctly.
        """
        workspace = _make_workspace(tmp_path)
        transcript_file = _make_realistic_transcript(
            tmp_path,
            "Should I proceed with Phase 2?",
        )

        raw_request = {
            "event": "Stop",
            "hook_input": {
                "hook_event_name": "Stop",
                "stop_hook_active": False,
                "transcript_path": str(transcript_file),
                "session_id": "test-session",
                "cwd": str(workspace),
            },
        }

        controller = DaemonController()
        handler_config = {
            "stop": {
                "auto_continue_stop": {"enabled": True, "priority": 10},
                "task_completion_checker": {"enabled": False},
            }
        }

        with _mock_git_subprocess():
            controller.initialise(
                handler_config=handler_config,
                workspace_root=workspace,
            )

        response = controller.process_request(raw_request)

        assert response.get("decision") == "block", (
            f"Expected 'block' but got: {response}. "
            "Handler failed to find assistant message in realistic multi-entry transcript."
        )

    def test_full_daemon_controller_stop_event_without_transcript_path(
        self,
        tmp_path: Path,
    ) -> None:
        """Stop event without transcript_path - handler gracefully doesn't match."""
        workspace = _make_workspace(tmp_path)

        raw_request = {
            "event": "Stop",
            "hook_input": {
                "hook_event_name": "Stop",
                "stop_hook_active": False,
            },
        }

        controller = DaemonController()
        handler_config = {
            "stop": {
                "auto_continue_stop": {"enabled": True, "priority": 10},
                "task_completion_checker": {"enabled": False},
            }
        }

        with _mock_git_subprocess():
            controller.initialise(
                handler_config=handler_config,
                workspace_root=workspace,
            )

        response = controller.process_request(raw_request)
        assert response.get("decision") != "block"

    def test_hook_event_model_validate_stop(self, tmp_path: Path) -> None:
        """HookEvent.model_validate correctly parses Stop events."""
        transcript_file = _make_transcript(tmp_path, "Should I proceed?")

        raw_request = {
            "event": "Stop",
            "hook_input": {
                "hook_event_name": "Stop",
                "stop_hook_active": False,
                "transcript_path": str(transcript_file),
                "session_id": "test-session",
            },
        }

        event = HookEvent.model_validate(raw_request)
        assert event.event_type == EventType.STOP
        assert event.hook_input.transcript_path == str(transcript_file)

        hook_input_dict = event.hook_input.model_dump(by_alias=False)
        assert "transcript_path" in hook_input_dict
        assert hook_input_dict["transcript_path"] == str(transcript_file)
        assert "stop_hook_active" in hook_input_dict
        assert hook_input_dict["stop_hook_active"] is False
