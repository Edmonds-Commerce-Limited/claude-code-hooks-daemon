"""Integration test fixtures.

Shared fixtures for integration tests that test handlers through
the full EventRouter/HandlerChain pipeline.
"""

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from claude_code_hooks_daemon.core.chain import ChainExecutionResult
from claude_code_hooks_daemon.core.event import EventType
from claude_code_hooks_daemon.core.handler import Handler
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.core.router import EventRouter


@pytest.fixture()
def project_context(tmp_path: Path) -> Path:
    """Initialize ProjectContext for integration tests.

    Returns the project root path for use in tests.
    """
    project_root = tmp_path / "project"
    claude_dir = project_root / ".claude"
    plan_dir = project_root / "CLAUDE" / "Plan"
    claude_dir.mkdir(parents=True)
    plan_dir.mkdir(parents=True)
    config_path = claude_dir / "hooks-daemon.yaml"
    config_path.write_text("version: 1.0\n")

    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout=str(project_root).encode() + b"\n"),
            MagicMock(
                returncode=0,
                stdout=b"git@github.com:user/test-repo.git\n",
            ),
            MagicMock(returncode=0, stdout=str(project_root).encode() + b"\n"),
        ]
        ProjectContext.initialize(config_path)

    return project_root


@pytest.fixture()
def router() -> EventRouter:
    """Create a fresh EventRouter for testing."""
    return EventRouter()


def make_bash_input(command: str) -> dict[str, Any]:
    """Create a PreToolUse Bash hook input."""
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": command},
    }


def make_write_input(file_path: str, content: str) -> dict[str, Any]:
    """Create a PreToolUse Write hook input."""
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": "Write",
        "tool_input": {"file_path": file_path, "content": content},
    }


def make_edit_input(file_path: str, old_string: str, new_string: str) -> dict[str, Any]:
    """Create a PreToolUse Edit hook input."""
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": "Edit",
        "tool_input": {
            "file_path": file_path,
            "old_string": old_string,
            "new_string": new_string,
        },
    }


def make_read_input(file_path: str) -> dict[str, Any]:
    """Create a PreToolUse Read hook input."""
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": "Read",
        "tool_input": {"file_path": file_path},
    }


def route_single_handler(
    handler: Handler,
    event_type: EventType,
    hook_input: dict[str, Any],
) -> ChainExecutionResult:
    """Route hook_input through a single handler via EventRouter.

    Returns the ChainExecutionResult.
    """
    event_router = EventRouter()
    event_router.register(event_type, handler)
    return event_router.route(event_type, hook_input)
