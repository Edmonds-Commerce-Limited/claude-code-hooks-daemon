"""Integration tests for Session lifecycle handlers.

Tests: WorkflowStateRestorationHandler, YoloContainerDetectionHandler,
       CleanupHandler, WorkflowStatePreCompactHandler
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.core import Decision
from tests.integration.handlers.conftest import (
    make_pre_compact_input,
    make_session_end_input,
    make_session_start_input,
)


# ---------------------------------------------------------------------------
# WorkflowStateRestorationHandler
# ---------------------------------------------------------------------------
class TestWorkflowStateRestorationHandler:
    """Integration tests for WorkflowStateRestorationHandler."""

    @pytest.fixture()
    def handler(self, tmp_path: Any) -> Any:
        from claude_code_hooks_daemon.handlers.session_start.workflow_state_restoration import (
            WorkflowStateRestorationHandler,
        )

        return WorkflowStateRestorationHandler(workspace_root=tmp_path)

    def test_matches_compact_source(self, handler: Any) -> None:
        hook_input = make_session_start_input(source="compact")
        assert handler.matches(hook_input) is True

    def test_ignores_user_source(self, handler: Any) -> None:
        hook_input = make_session_start_input(source="user")
        assert handler.matches(hook_input) is False

    def test_restores_state_from_file(self, handler: Any, tmp_path: Any) -> None:
        # Create workflow state file
        state_dir = tmp_path / "untracked" / "workflow-state" / "test-workflow"
        state_dir.mkdir(parents=True)
        state_file = state_dir / "state-test-workflow-12345.json"
        state = {
            "workflow": "Test Workflow",
            "workflow_type": "plan",
            "phase": {"current": 2, "total": 3, "name": "Implementation", "status": "in_progress"},
            "required_reading": ["@CLAUDE/Plan/001/PLAN.md"],
            "context": {"plan_id": "001"},
            "key_reminders": ["Follow TDD"],
        }
        state_file.write_text(json.dumps(state))

        hook_input = make_session_start_input(source="compact")
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW
        assert result.context is not None
        assert len(result.context) > 0
        assert "Test Workflow" in result.context[0]

    def test_allows_when_no_state_files(self, handler: Any) -> None:
        hook_input = make_session_start_input(source="compact")
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW

    def test_handles_corrupt_state_file(self, handler: Any, tmp_path: Any) -> None:
        state_dir = tmp_path / "untracked" / "workflow-state" / "test"
        state_dir.mkdir(parents=True)
        state_file = state_dir / "state-test-12345.json"
        state_file.write_text("not valid json{{{")

        hook_input = make_session_start_input(source="compact")
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW


# ---------------------------------------------------------------------------
# YoloContainerDetectionHandler
# ---------------------------------------------------------------------------
class TestYoloContainerDetectionHandler:
    """Integration tests for YoloContainerDetectionHandler."""

    @pytest.fixture()
    def handler(self) -> Any:
        from claude_code_hooks_daemon.handlers.session_start.yolo_container_detection import (
            YoloContainerDetectionHandler,
        )

        return YoloContainerDetectionHandler()

    def test_matches_yolo_environment(self, handler: Any) -> None:
        hook_input = {
            "hook_event_name": "SessionStart",
            "source": "user",
        }
        # Simulate YOLO environment with environment variables
        with patch.dict("os.environ", {"CLAUDECODE": "1", "CLAUDE_CODE_ENTRYPOINT": "cli"}):
            if handler.matches(hook_input):
                result = handler.handle(hook_input)
                assert result.decision == Decision.ALLOW
                assert result.context is not None

    def test_ignores_non_session_start(self, handler: Any) -> None:
        hook_input = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
        }
        assert handler.matches(hook_input) is False

    def test_does_not_match_non_yolo(self, handler: Any) -> None:
        hook_input = {
            "hook_event_name": "SessionStart",
            "source": "user",
        }
        # Clear YOLO indicators to ensure low confidence score
        env_overrides = {
            "CLAUDECODE": "",
            "CLAUDE_CODE_ENTRYPOINT": "",
            "DEVCONTAINER": "",
            "IS_SANDBOX": "",
            "container": "",
        }
        with patch.dict("os.environ", env_overrides, clear=False):
            # With low confidence score, should not match
            handler.config["min_confidence_score"] = 100
            assert handler.matches(hook_input) is False

    def test_handler_is_non_terminal(self, handler: Any) -> None:
        assert handler.terminal is False

    def test_null_input_not_matched(self, handler: Any) -> None:
        # Pass None typed as Any to test null safety
        null_input: Any = None
        assert handler.matches(null_input) is False


# ---------------------------------------------------------------------------
# CleanupHandler
# ---------------------------------------------------------------------------
class TestCleanupHandler:
    """Integration tests for CleanupHandler (SessionEnd)."""

    @pytest.fixture()
    def handler(self) -> Any:
        from claude_code_hooks_daemon.handlers.session_end.cleanup_handler import (
            CleanupHandler,
        )

        return CleanupHandler()

    def test_matches_session_end(self, handler: Any) -> None:
        hook_input = make_session_end_input()
        assert handler.matches(hook_input) is True

    def test_handle_returns_allow(self, handler: Any) -> None:
        hook_input = make_session_end_input()
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW

    def test_handler_is_non_terminal(self, handler: Any) -> None:
        assert handler.terminal is False


# ---------------------------------------------------------------------------
# WorkflowStatePreCompactHandler
# ---------------------------------------------------------------------------
class TestWorkflowStatePreCompactHandler:
    """Integration tests for WorkflowStatePreCompactHandler."""

    @pytest.fixture()
    def handler(self, tmp_path: Any) -> Any:
        from claude_code_hooks_daemon.handlers.pre_compact.workflow_state_pre_compact import (
            WorkflowStatePreCompactHandler,
        )

        return WorkflowStatePreCompactHandler(workspace_root=tmp_path)

    def test_does_not_match_without_workflow(self, handler: Any) -> None:
        hook_input = make_pre_compact_input()
        # Without CLAUDE.local.md or active plans, no workflow detected
        assert handler.matches(hook_input) is False

    def test_matches_when_workflow_active(self, handler: Any, tmp_path: Any) -> None:
        # Create CLAUDE.local.md with workflow markers
        claude_local = tmp_path / "CLAUDE.local.md"
        claude_local.write_text(
            "# WORKFLOW STATE\nworkflow: Test Plan\nPhase: 2/5 - Implementation\n"
        )

        hook_input = make_pre_compact_input()
        assert handler.matches(hook_input) is True

    def test_handle_returns_allow(self, handler: Any, tmp_path: Any) -> None:
        # Create workflow context so handler processes
        claude_local = tmp_path / "CLAUDE.local.md"
        claude_local.write_text("# WORKFLOW STATE\nworkflow: Test Plan\n")

        hook_input = make_pre_compact_input()
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW

    def test_handle_returns_allow_without_workflow(self, handler: Any) -> None:
        hook_input = make_pre_compact_input()
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW

    def test_handler_is_non_terminal(self, handler: Any) -> None:
        assert handler.terminal is False
