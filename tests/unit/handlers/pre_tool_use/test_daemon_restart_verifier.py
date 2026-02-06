"""Tests for DaemonRestartVerifier handler."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.handlers.pre_tool_use.daemon_restart_verifier import (
    DaemonRestartVerifierHandler,
)


@pytest.fixture(autouse=True)
def _init_project_context(tmp_path: Path) -> None:
    """Initialize ProjectContext before handler instantiation."""
    project_root = tmp_path / "project"
    claude_dir = project_root / ".claude"
    claude_dir.mkdir(parents=True)
    config_path = claude_dir / "hooks-daemon.yaml"
    config_path.write_text("version: 1.0\n")

    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout=b"/tmp/project\n"),
            MagicMock(returncode=0, stdout=b"git@github.com:user/test-repo.git\n"),
            MagicMock(returncode=0, stdout=b"/tmp/project\n"),
        ]
        ProjectContext.initialize(config_path)


def test_handler_initialization() -> None:
    """Test handler initializes correctly."""
    from claude_code_hooks_daemon.constants import HandlerID, Priority

    handler = DaemonRestartVerifierHandler()
    assert handler.handler_id == HandlerID.DAEMON_RESTART_VERIFIER
    assert handler.priority == Priority.DAEMON_RESTART_VERIFIER
    assert handler.terminal is False  # Advisory, not blocking


def test_matches_git_commit() -> None:
    """Test matches git commit commands."""
    handler = DaemonRestartVerifierHandler()

    hook_input = {
        "tool_name": "Bash",
        "tool_input": {"command": "git commit -m 'test'"},
    }

    with patch(
        "claude_code_hooks_daemon.handlers.pre_tool_use.daemon_restart_verifier.is_hooks_daemon_repo",
        return_value=True,
    ):
        assert handler.matches(hook_input) is True


def test_matches_git_commit_with_options() -> None:
    """Test matches git commit with various options."""
    handler = DaemonRestartVerifierHandler()

    test_cases = [
        "git commit -m 'message'",
        "git commit --amend",
        "git commit -a -m 'message'",
        "git commit --no-verify -m 'test'",
    ]

    with patch(
        "claude_code_hooks_daemon.handlers.pre_tool_use.daemon_restart_verifier.is_hooks_daemon_repo",
        return_value=True,
    ):
        for command in test_cases:
            hook_input = {"tool_name": "Bash", "tool_input": {"command": command}}
            assert handler.matches(hook_input) is True, f"Should match: {command}"


def test_does_not_match_non_commit_commands() -> None:
    """Test does not match non-commit git commands."""
    handler = DaemonRestartVerifierHandler()

    test_cases = [
        "git status",
        "git add .",
        "git push",
        "git log",
        "ls -la",
    ]

    for command in test_cases:
        hook_input = {"tool_name": "Bash", "tool_input": {"command": command}}
        assert handler.matches(hook_input) is False, f"Should not match: {command}"


def test_does_not_match_non_bash_tool() -> None:
    """Test does not match non-Bash tools."""
    handler = DaemonRestartVerifierHandler()

    hook_input = {"tool_name": "Write", "tool_input": {"file_path": "test.py"}}

    assert handler.matches(hook_input) is False


def test_handle_when_not_hooks_daemon_repo() -> None:
    """Test allows commit when not in hooks daemon repo."""
    handler = DaemonRestartVerifierHandler()

    # Mock the workspace root to not be hooks daemon repo
    handler._workspace_root = "/tmp/some_other_project"

    hook_input = {
        "tool_name": "Bash",
        "tool_input": {"command": "git commit -m 'test'"},
    }

    result = handler.handle(hook_input)
    assert result.decision == Decision.ALLOW


def test_get_acceptance_tests() -> None:
    """Test handler provides acceptance tests."""
    handler = DaemonRestartVerifierHandler()

    tests = handler.get_acceptance_tests()

    assert len(tests) > 0
    assert tests[0].title is not None
    assert tests[0].command is not None
    assert tests[0].expected_decision == Decision.ALLOW
