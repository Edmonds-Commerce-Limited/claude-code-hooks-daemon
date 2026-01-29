#!/usr/bin/env python3
"""
Tests for WorkflowStateRestorationHandler.

Tests workflow state restoration after compaction.
"""

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.session_start.workflow_state_restoration import (
    WorkflowStateRestorationHandler,
)


class TestWorkflowStateRestorationHandler:
    """Tests for WorkflowStateRestorationHandler."""

    @pytest.fixture
    def tmp_workspace(self, tmp_path: Path) -> Path:
        """Create temporary workspace directory."""
        return tmp_path

    @pytest.fixture
    def handler(self, tmp_workspace: Path) -> WorkflowStateRestorationHandler:
        """Create handler instance with test workspace."""
        return WorkflowStateRestorationHandler(workspace_root=tmp_workspace)

    @pytest.fixture
    def session_start_compact_input(self) -> dict[str, Any]:
        """Create sample SessionStart hook input from compact."""
        return {
            "hook_event_name": "SessionStart",
            "source": "compact",
            "session_id": "test-session",
        }

    @pytest.fixture
    def sample_workflow_state(self) -> dict[str, Any]:
        """Create sample workflow state."""
        return {
            "workflow": "SEO Optimization",
            "workflow_type": "custom",
            "phase": {
                "current": 3,
                "total": 10,
                "name": "Content Generation",
                "status": "in_progress",
            },
            "required_reading": ["@CLAUDE/WORKFLOWS/SEO.md", "@.claude/config.yaml"],
            "context": {"plan_number": 66, "plan_name": "066-seo-optimization"},
            "key_reminders": ["Remember to validate schema", "Use custom prompt templates"],
            "created_at": "2026-01-27T12:00:00Z",
        }

    def test_init_creates_handler_with_correct_attributes(
        self, handler: WorkflowStateRestorationHandler
    ) -> None:
        """Handler initializes with correct name and tags."""
        assert handler.name == "workflow-state-restoration"
        assert "workflow" in handler.tags
        assert "state-management" in handler.tags
        assert "advisory" in handler.tags
        assert "non-terminal" in handler.tags
        assert handler.terminal is False

    def test_init_uses_provided_workspace_root(self, tmp_path: Path) -> None:
        """Handler uses provided workspace root."""
        handler = WorkflowStateRestorationHandler(workspace_root=tmp_path)
        assert handler.workspace_root == tmp_path

    def test_init_auto_detects_workspace_root_when_none(self) -> None:
        """Handler auto-detects workspace root when not provided."""
        with patch(
            "claude_code_hooks_daemon.handlers.session_start.workflow_state_restoration.get_workspace_root"
        ) as mock_get_root:
            mock_get_root.return_value = Path("/detected/root")
            handler = WorkflowStateRestorationHandler()
            assert handler.workspace_root == Path("/detected/root")
            mock_get_root.assert_called_once()

    def test_matches_returns_false_for_non_session_start_event(
        self, handler: WorkflowStateRestorationHandler
    ) -> None:
        """Handler does not match non-SessionStart events."""
        input_data = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
        }
        assert handler.matches(input_data) is False

    def test_matches_returns_true_when_source_is_compact(
        self, handler: WorkflowStateRestorationHandler, session_start_compact_input: dict[str, Any]
    ) -> None:
        """Handler matches when source is compact."""
        assert handler.matches(session_start_compact_input) is True

    def test_matches_returns_false_when_source_is_not_compact(
        self, handler: WorkflowStateRestorationHandler
    ) -> None:
        """Handler does not match when source is not compact."""
        input_data = {
            "hook_event_name": "SessionStart",
            "source": "new",
        }
        assert handler.matches(input_data) is False

    def test_matches_returns_false_when_source_missing(
        self, handler: WorkflowStateRestorationHandler
    ) -> None:
        """Handler does not match when source field is missing."""
        input_data = {
            "hook_event_name": "SessionStart",
        }
        assert handler.matches(input_data) is False

    def test_handle_returns_allow_when_no_untracked_directory(
        self, handler: WorkflowStateRestorationHandler, session_start_compact_input: dict[str, Any]
    ) -> None:
        """Handler allows when untracked/workflow-state directory doesn't exist."""
        result = handler.handle(session_start_compact_input)
        assert result.decision == Decision.ALLOW
        assert result.context == []

    def test_handle_returns_allow_when_no_state_files(
        self,
        handler: WorkflowStateRestorationHandler,
        session_start_compact_input: dict[str, Any],
        tmp_workspace: Path,
    ) -> None:
        """Handler allows when no state files exist."""
        untracked_dir = tmp_workspace / "untracked/workflow-state"
        untracked_dir.mkdir(parents=True)

        result = handler.handle(session_start_compact_input)
        assert result.decision == Decision.ALLOW
        assert result.context == []

    def test_handle_restores_workflow_state_with_guidance(
        self,
        handler: WorkflowStateRestorationHandler,
        session_start_compact_input: dict[str, Any],
        tmp_workspace: Path,
        sample_workflow_state: dict[str, Any],
    ) -> None:
        """Handler provides guidance with restored workflow state."""
        # Create state file
        workflow_dir = tmp_workspace / "untracked/workflow-state/seo-optimization"
        workflow_dir.mkdir(parents=True)
        state_file = workflow_dir / "state-seo-optimization-20260127_120000.json"
        with state_file.open("w") as f:
            json.dump(sample_workflow_state, f)

        result = handler.handle(session_start_compact_input)
        assert result.decision == Decision.ALLOW
        assert len(result.context) == 1

        guidance = result.context[0]
        assert "WORKFLOW RESTORED AFTER COMPACTION" in guidance
        assert "SEO Optimization" in guidance
        assert "Phase: 3/10 - Content Generation" in guidance
        assert "@CLAUDE/WORKFLOWS/SEO.md" in guidance
        assert "@.claude/config.yaml" in guidance

    def test_handle_uses_most_recently_updated_state_file(
        self,
        handler: WorkflowStateRestorationHandler,
        session_start_compact_input: dict[str, Any],
        tmp_workspace: Path,
    ) -> None:
        """Handler uses most recently updated state file when multiple exist."""
        workflow_dir = tmp_workspace / "untracked/workflow-state/test-workflow"
        workflow_dir.mkdir(parents=True)

        # Create older state file
        old_state_file = workflow_dir / "state-test-workflow-20260101_120000.json"
        old_state = {"workflow": "Old Workflow", "phase": {"current": 1, "total": 5}}
        with old_state_file.open("w") as f:
            json.dump(old_state, f)

        # Create newer state file in different workflow
        other_dir = tmp_workspace / "untracked/workflow-state/other-workflow"
        other_dir.mkdir(parents=True)
        new_state_file = other_dir / "state-other-workflow-20260127_120000.json"
        new_state = {"workflow": "New Workflow", "phase": {"current": 2, "total": 5}}
        with new_state_file.open("w") as f:
            json.dump(new_state, f)

        # Touch new file to ensure it's newer
        import time

        time.sleep(0.01)
        new_state_file.touch()

        result = handler.handle(session_start_compact_input)
        assert result.decision == Decision.ALLOW
        guidance = result.context[0]
        assert "New Workflow" in guidance
        assert "Old Workflow" not in guidance

    def test_handle_returns_allow_when_state_file_unreadable(
        self,
        handler: WorkflowStateRestorationHandler,
        session_start_compact_input: dict[str, Any],
        tmp_workspace: Path,
    ) -> None:
        """Handler allows when state file cannot be read."""
        workflow_dir = tmp_workspace / "untracked/workflow-state/test-workflow"
        workflow_dir.mkdir(parents=True)
        state_file = workflow_dir / "state-test-workflow-20260127_120000.json"
        state_file.write_text("invalid json {{{")

        result = handler.handle(session_start_compact_input)
        assert result.decision == Decision.ALLOW
        assert result.context == []

    def test_handle_returns_allow_when_state_file_read_permission_error(
        self,
        handler: WorkflowStateRestorationHandler,
        session_start_compact_input: dict[str, Any],
        tmp_workspace: Path,
    ) -> None:
        """Handler allows when state file read raises OSError."""
        workflow_dir = tmp_workspace / "untracked/workflow-state/test-workflow"
        workflow_dir.mkdir(parents=True)
        state_file = workflow_dir / "state-test-workflow-20260127_120000.json"
        state_file.mkdir()  # Make it a directory to cause OSError

        result = handler.handle(session_start_compact_input)
        assert result.decision == Decision.ALLOW
        assert result.context == []

    def test_handle_fails_open_on_exception(
        self,
        handler: WorkflowStateRestorationHandler,
        session_start_compact_input: dict[str, Any],
        tmp_workspace: Path,
    ) -> None:
        """Handler fails open on any exception."""
        # Make untracked/workflow-state a file to cause glob to fail
        untracked_dir = tmp_workspace / "untracked"
        untracked_dir.mkdir()
        workflow_state_dir = untracked_dir / "workflow-state"
        workflow_state_dir.write_text("blocking file")

        result = handler.handle(session_start_compact_input)
        assert result.decision == Decision.ALLOW
        assert result.context == []

    def test_handle_does_not_delete_state_file(
        self,
        handler: WorkflowStateRestorationHandler,
        session_start_compact_input: dict[str, Any],
        tmp_workspace: Path,
        sample_workflow_state: dict[str, Any],
    ) -> None:
        """Handler does not delete state file after restoration."""
        workflow_dir = tmp_workspace / "untracked/workflow-state/seo-optimization"
        workflow_dir.mkdir(parents=True)
        state_file = workflow_dir / "state-seo-optimization-20260127_120000.json"
        with state_file.open("w") as f:
            json.dump(sample_workflow_state, f)

        handler.handle(session_start_compact_input)

        # Verify file still exists
        assert state_file.exists()

    def test_build_guidance_message_includes_workflow_info(
        self, handler: WorkflowStateRestorationHandler, sample_workflow_state: dict[str, Any]
    ) -> None:
        """Guidance message includes workflow information."""
        guidance = handler._build_guidance_message(sample_workflow_state)
        assert "⚠️ WORKFLOW RESTORED AFTER COMPACTION ⚠️" in guidance
        assert "Workflow: SEO Optimization" in guidance
        assert "Type: custom" in guidance
        assert "Phase: 3/10 - Content Generation (in_progress)" in guidance

    def test_build_guidance_message_includes_required_reading(
        self, handler: WorkflowStateRestorationHandler, sample_workflow_state: dict[str, Any]
    ) -> None:
        """Guidance message includes required reading section."""
        guidance = handler._build_guidance_message(sample_workflow_state)
        assert "REQUIRED READING (read ALL now with @ syntax):" in guidance
        assert "@CLAUDE/WORKFLOWS/SEO.md" in guidance
        assert "@.claude/config.yaml" in guidance

    def test_build_guidance_message_includes_key_reminders(
        self, handler: WorkflowStateRestorationHandler, sample_workflow_state: dict[str, Any]
    ) -> None:
        """Guidance message includes key reminders section."""
        guidance = handler._build_guidance_message(sample_workflow_state)
        assert "Key Reminders:" in guidance
        assert "- Remember to validate schema" in guidance
        assert "- Use custom prompt templates" in guidance

    def test_build_guidance_message_includes_context(
        self, handler: WorkflowStateRestorationHandler, sample_workflow_state: dict[str, Any]
    ) -> None:
        """Guidance message includes context section."""
        guidance = handler._build_guidance_message(sample_workflow_state)
        assert "Context:" in guidance
        assert '"plan_number": 66' in guidance
        assert '"plan_name": "066-seo-optimization"' in guidance

    def test_build_guidance_message_includes_action_required(
        self, handler: WorkflowStateRestorationHandler, sample_workflow_state: dict[str, Any]
    ) -> None:
        """Guidance message includes action required section."""
        guidance = handler._build_guidance_message(sample_workflow_state)
        assert "ACTION REQUIRED:" in guidance
        assert "1. Read ALL files listed above using @ syntax" in guidance
        assert "2. Confirm understanding of workflow phase" in guidance
        assert "3. DO NOT proceed with assumptions or hallucinated logic" in guidance

    def test_build_guidance_message_handles_missing_workflow(
        self, handler: WorkflowStateRestorationHandler
    ) -> None:
        """Guidance message handles missing workflow field."""
        state: dict[str, Any] = {}
        guidance = handler._build_guidance_message(state)
        assert "Workflow: Unknown Workflow" in guidance

    def test_build_guidance_message_handles_missing_workflow_type(
        self, handler: WorkflowStateRestorationHandler
    ) -> None:
        """Guidance message handles missing workflow_type field."""
        state: dict[str, Any] = {"workflow": "Test"}
        guidance = handler._build_guidance_message(state)
        assert "Type: custom" in guidance

    def test_build_guidance_message_handles_missing_phase(
        self, handler: WorkflowStateRestorationHandler
    ) -> None:
        """Guidance message handles missing phase field."""
        state: dict[str, Any] = {"workflow": "Test"}
        guidance = handler._build_guidance_message(state)
        assert "Phase: 1/1 - Unknown (in_progress)" in guidance

    def test_build_guidance_message_handles_empty_required_reading(
        self, handler: WorkflowStateRestorationHandler
    ) -> None:
        """Guidance message handles empty required reading list."""
        state: dict[str, Any] = {"workflow": "Test", "required_reading": []}
        guidance = handler._build_guidance_message(state)
        assert "REQUIRED READING" not in guidance

    def test_build_guidance_message_handles_missing_required_reading(
        self, handler: WorkflowStateRestorationHandler
    ) -> None:
        """Guidance message handles missing required_reading field."""
        state: dict[str, Any] = {"workflow": "Test"}
        guidance = handler._build_guidance_message(state)
        assert "REQUIRED READING" not in guidance

    def test_build_guidance_message_handles_empty_key_reminders(
        self, handler: WorkflowStateRestorationHandler
    ) -> None:
        """Guidance message handles empty key reminders list."""
        state: dict[str, Any] = {"workflow": "Test", "key_reminders": []}
        guidance = handler._build_guidance_message(state)
        assert "Key Reminders:" not in guidance

    def test_build_guidance_message_handles_missing_key_reminders(
        self, handler: WorkflowStateRestorationHandler
    ) -> None:
        """Guidance message handles missing key_reminders field."""
        state: dict[str, Any] = {"workflow": "Test"}
        guidance = handler._build_guidance_message(state)
        assert "Key Reminders:" not in guidance

    def test_build_guidance_message_handles_empty_context(
        self, handler: WorkflowStateRestorationHandler
    ) -> None:
        """Guidance message handles empty context dict."""
        state: dict[str, Any] = {"workflow": "Test", "context": {}}
        guidance = handler._build_guidance_message(state)
        assert "Context:" not in guidance

    def test_build_guidance_message_handles_missing_context(
        self, handler: WorkflowStateRestorationHandler
    ) -> None:
        """Guidance message handles missing context field."""
        state: dict[str, Any] = {"workflow": "Test"}
        guidance = handler._build_guidance_message(state)
        assert "Context:" not in guidance

    def test_handle_returns_deny_on_unexpected_exception(
        self, handler: WorkflowStateRestorationHandler, tmp_workspace: Path, monkeypatch: Any
    ) -> None:
        """Should return DENY decision for unexpected exceptions (FAIL FAST)."""
        # Create workflow state directory and file
        workflow_dir = tmp_workspace / "untracked/workflow-state/test-workflow"
        workflow_dir.mkdir(parents=True)

        state = {
            "workflow": "Test Workflow",
            "required_reading": [],
            "key_reminders": [],
            "context": [],
        }
        state_file = workflow_dir / "state-test-workflow-20260127_120000.json"
        state_file.write_text(json.dumps(state))

        # Mock _build_guidance_message to raise an unexpected exception
        def mock_build_guidance(*args: Any, **kwargs: Any) -> str:
            raise RuntimeError("Unexpected error in guidance building")

        monkeypatch.setattr(handler, "_build_guidance_message", mock_build_guidance)

        # Should not raise, should return DENY for unexpected error
        result = handler.handle({})
        assert result.decision == Decision.DENY
        assert "Workflow restoration handler error" in result.reason
        assert "Unexpected error in guidance building" in result.reason
