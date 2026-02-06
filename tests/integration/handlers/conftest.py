"""Shared fixtures for handler integration tests.

Provides hook_input factory functions and ProjectContext initialization.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.core.project_context import ProjectContext


@pytest.fixture(autouse=True)
def _init_project_context(tmp_path: Any) -> Any:
    """Initialize ProjectContext with a temporary directory for all tests."""
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    untracked = tmp_path / "untracked"
    untracked.mkdir()

    with patch.object(ProjectContext, "project_root", return_value=tmp_path):
        with patch.object(ProjectContext, "config_dir", return_value=claude_dir):
            with patch.object(
                ProjectContext, "daemon_untracked_dir", return_value=untracked
            ):
                with patch.object(
                    ProjectContext, "git_repo_name", return_value="test-repo"
                ):
                    yield


def make_bash_hook_input(command: str) -> dict[str, Any]:
    """Create a PreToolUse hook_input for a Bash command."""
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": command},
    }


def make_write_hook_input(
    file_path: str, content: str = ""
) -> dict[str, Any]:
    """Create a PreToolUse hook_input for a Write operation."""
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": "Write",
        "tool_input": {"file_path": file_path, "content": content},
    }


def make_edit_hook_input(
    file_path: str, old_string: str = "", new_string: str = ""
) -> dict[str, Any]:
    """Create a PreToolUse hook_input for an Edit operation."""
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": "Edit",
        "tool_input": {
            "file_path": file_path,
            "old_string": old_string,
            "new_string": new_string,
        },
    }


def make_post_tool_bash_input(
    command: str,
    stdout: str = "",
    stderr: str = "",
    interrupted: bool = False,
) -> dict[str, Any]:
    """Create a PostToolUse hook_input for a Bash command."""
    return {
        "hook_event_name": "PostToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "tool_response": {
            "stdout": stdout,
            "stderr": stderr,
            "interrupted": interrupted,
        },
    }


def make_post_tool_write_input(file_path: str) -> dict[str, Any]:
    """Create a PostToolUse hook_input for a Write operation."""
    return {
        "hook_event_name": "PostToolUse",
        "tool_name": "Write",
        "tool_input": {"file_path": file_path, "content": "some content"},
    }


def make_session_start_input(source: str = "user") -> dict[str, Any]:
    """Create a SessionStart hook_input."""
    return {
        "hook_event_name": "SessionStart",
        "source": source,
    }


def make_session_end_input() -> dict[str, Any]:
    """Create a SessionEnd hook_input."""
    return {"hook_event_name": "SessionEnd"}


def make_pre_compact_input() -> dict[str, Any]:
    """Create a PreCompact hook_input."""
    return {
        "hook_event_name": "PreCompact",
        "trigger": "context_limit",
        "session_id": "test-session-123",
    }


def make_stop_input(
    stop_hook_active: bool = False,
    transcript_path: str = "",
) -> dict[str, Any]:
    """Create a Stop hook_input."""
    return {
        "hook_event_name": "Stop",
        "stop_hook_active": stop_hook_active,
        "transcript_path": transcript_path,
    }


def make_subagent_stop_input(
    transcript_path: str = "",
    subagent_type: str = "unknown",
) -> dict[str, Any]:
    """Create a SubagentStop hook_input."""
    return {
        "hook_event_name": "SubagentStop",
        "transcript_path": transcript_path,
        "subagent_type": subagent_type,
    }


def make_permission_request_input(
    permission_type: str, resource: str = ""
) -> dict[str, Any]:
    """Create a PermissionRequest hook_input."""
    return {
        "hook_event_name": "PermissionRequest",
        "permission_type": permission_type,
        "resource": resource,
    }


def make_notification_input(
    title: str = "Test", message: str = "Test notification"
) -> dict[str, Any]:
    """Create a Notification hook_input."""
    return {
        "hook_event_name": "Notification",
        "title": title,
        "message": message,
    }


def make_user_prompt_submit_input(prompt: str = "Hello") -> dict[str, Any]:
    """Create a UserPromptSubmit hook_input."""
    return {
        "hook_event_name": "UserPromptSubmit",
        "prompt": prompt,
    }


def make_status_line_input(
    model_display_name: str = "Claude Sonnet 4.5",
    model_id: str = "claude-sonnet-4-5-20250929",
    used_percentage: float = 25.0,
    cwd: str = "/workspace",
) -> dict[str, Any]:
    """Create a StatusLine hook_input."""
    return {
        "hook_event_name": "StatusLine",
        "model": {
            "display_name": model_display_name,
            "id": model_id,
        },
        "context_window": {
            "used_percentage": used_percentage,
        },
        "workspace": {
            "current_dir": cwd,
            "project_dir": cwd,
        },
    }


def make_web_search_input(query: str) -> dict[str, Any]:
    """Create a PreToolUse hook_input for a WebSearch operation."""
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": "WebSearch",
        "tool_input": {"query": query},
    }
