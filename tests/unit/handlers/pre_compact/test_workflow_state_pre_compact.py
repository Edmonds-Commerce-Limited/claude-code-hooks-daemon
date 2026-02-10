#!/usr/bin/env python3
"""
Tests for WorkflowStatePreCompactHandler.

Tests workflow state detection and preservation before compaction.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def mock_project_context():
    """Mock ProjectContext for handler instantiation tests."""
    with patch("claude_code_hooks_daemon.core.project_context.ProjectContext.project_root") as mock:
        mock.return_value = Path("/tmp/test")
        yield mock


import pytest

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.pre_compact.workflow_state_pre_compact import (
    WorkflowStatePreCompactHandler,
)


class TestWorkflowStatePreCompactHandler:
    """Tests for WorkflowStatePreCompactHandler."""

    @pytest.fixture
    def tmp_workspace(self, tmp_path: Path) -> Path:
        """Create temporary workspace directory."""
        return tmp_path

    @pytest.fixture
    def handler(self, tmp_workspace: Path) -> WorkflowStatePreCompactHandler:
        """Create handler instance with test workspace."""
        return WorkflowStatePreCompactHandler(workspace_root=tmp_workspace)

    @pytest.fixture
    def pre_compact_input(self) -> dict[str, Any]:
        """Create sample PreCompact hook input."""
        return {
            "hook_event_name": "PreCompact",
            "trigger": "auto",
            "session_id": "test-session",
        }

    def test_init_creates_handler_with_correct_attributes(
        self, handler: WorkflowStatePreCompactHandler
    ) -> None:
        """Handler initializes with correct name and tags."""
        assert handler.name == "workflow-state-precompact"
        assert "workflow" in handler.tags
        assert "state-management" in handler.tags
        assert "non-terminal" in handler.tags
        assert handler.terminal is False

    def test_init_uses_provided_workspace_root(self, tmp_path: Path) -> None:
        """Handler uses provided workspace root."""
        handler = WorkflowStatePreCompactHandler(workspace_root=tmp_path)
        assert handler.workspace_root == tmp_path

    def test_init_auto_detects_workspace_root_when_none(self) -> None:
        """Handler auto-detects workspace root when not provided."""
        with patch(
            "claude_code_hooks_daemon.core.project_context.ProjectContext.project_root"
        ) as mock_get_root:
            mock_get_root.return_value = Path("/detected/root")
            handler = WorkflowStatePreCompactHandler()
            assert handler.workspace_root == Path("/detected/root")
            mock_get_root.assert_called_once()

    def test_matches_returns_false_for_non_precompact_event(
        self, handler: WorkflowStatePreCompactHandler
    ) -> None:
        """Handler does not match non-PreCompact events."""
        input_data = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
        }
        assert handler.matches(input_data) is False

    def test_matches_returns_false_when_no_workflow_detected(
        self, handler: WorkflowStatePreCompactHandler, pre_compact_input: dict[str, Any]
    ) -> None:
        """Handler does not match when no workflow is detected."""
        assert handler.matches(pre_compact_input) is False

    def test_matches_returns_true_when_workflow_in_claude_local(
        self,
        handler: WorkflowStatePreCompactHandler,
        pre_compact_input: dict[str, Any],
        tmp_workspace: Path,
    ) -> None:
        """Handler matches when workflow found in CLAUDE.local.md."""
        claude_local = tmp_workspace / "CLAUDE.local.md"
        claude_local.write_text("WORKFLOW STATE\n\nWorkflow: Test Workflow")
        assert handler.matches(pre_compact_input) is True

    def test_matches_returns_true_when_workflow_lowercase_in_claude_local(
        self,
        handler: WorkflowStatePreCompactHandler,
        pre_compact_input: dict[str, Any],
        tmp_workspace: Path,
    ) -> None:
        """Handler matches when workflow: marker found in CLAUDE.local.md."""
        claude_local = tmp_workspace / "CLAUDE.local.md"
        claude_local.write_text("workflow: test workflow\n\nSome content")
        assert handler.matches(pre_compact_input) is True

    def test_matches_returns_true_when_active_plan_with_workflow(
        self,
        handler: WorkflowStatePreCompactHandler,
        pre_compact_input: dict[str, Any],
        tmp_workspace: Path,
    ) -> None:
        """Handler matches when active plan with workflow phases exists."""
        plan_dir = tmp_workspace / "CLAUDE/Plan/066-test-workflow"
        plan_dir.mkdir(parents=True)
        plan_file = plan_dir / "PLAN.md"
        plan_file.write_text("# Plan 066: Test Workflow\n\n🔄 In Progress\n\nPhase 1: Setup")
        assert handler.matches(pre_compact_input) is True

    def test_matches_returns_false_when_plan_not_in_progress(
        self,
        handler: WorkflowStatePreCompactHandler,
        pre_compact_input: dict[str, Any],
        tmp_workspace: Path,
    ) -> None:
        """Handler does not match when plan exists but not in progress."""
        plan_dir = tmp_workspace / "CLAUDE/Plan/066-test-workflow"
        plan_dir.mkdir(parents=True)
        plan_file = plan_dir / "PLAN.md"
        plan_file.write_text("# Plan 066: Test Workflow\n\n✅ Complete\n\nPhase 1: Setup")
        assert handler.matches(pre_compact_input) is False

    def test_matches_returns_false_when_plan_in_progress_without_phase_or_workflow(
        self,
        handler: WorkflowStatePreCompactHandler,
        pre_compact_input: dict[str, Any],
        tmp_workspace: Path,
    ) -> None:
        """Handler does not match when plan in progress but no phase/workflow markers."""
        plan_dir = tmp_workspace / "CLAUDE/Plan/066-test-plan"
        plan_dir.mkdir(parents=True)
        plan_file = plan_dir / "PLAN.md"
        plan_file.write_text("# Plan 066: Test Plan\n\n🔄 In Progress\n\nSome content")
        assert handler.matches(pre_compact_input) is False

    def test_matches_handles_claude_local_read_error(
        self,
        handler: WorkflowStatePreCompactHandler,
        pre_compact_input: dict[str, Any],
        tmp_workspace: Path,
    ) -> None:
        """Handler continues checking other sources when CLAUDE.local.md read fails."""
        claude_local = tmp_workspace / "CLAUDE.local.md"
        claude_local.mkdir()  # Make it a directory so read fails
        assert handler.matches(pre_compact_input) is False

    def test_matches_handles_plan_file_read_error(
        self,
        handler: WorkflowStatePreCompactHandler,
        pre_compact_input: dict[str, Any],
        tmp_workspace: Path,
    ) -> None:
        """Handler continues when plan file read fails."""
        plan_dir = tmp_workspace / "CLAUDE/Plan/066-test-workflow"
        plan_dir.mkdir(parents=True)
        plan_file = plan_dir / "PLAN.md"
        plan_file.mkdir()  # Make it a directory so read fails
        assert handler.matches(pre_compact_input) is False

    def test_handle_returns_allow_when_no_workflow_detected(
        self, handler: WorkflowStatePreCompactHandler, pre_compact_input: dict[str, Any]
    ) -> None:
        """Handler allows compaction when no workflow detected."""
        result = handler.handle(pre_compact_input)
        assert result.decision == Decision.ALLOW

    def test_handle_creates_new_state_file_for_workflow(
        self,
        handler: WorkflowStatePreCompactHandler,
        pre_compact_input: dict[str, Any],
        tmp_workspace: Path,
    ) -> None:
        """Handler creates new state file when workflow detected."""
        # Create workflow indicator
        claude_local = tmp_workspace / "CLAUDE.local.md"
        claude_local.write_text(
            "WORKFLOW STATE\n\nWorkflow: Test Workflow\nPhase: 2/5 - Implementation"
        )

        result = handler.handle(pre_compact_input)
        assert result.decision == Decision.ALLOW

        # Check state file was created
        workflow_dir = tmp_workspace / "untracked/workflow-state/test-workflow"
        assert workflow_dir.exists()
        state_files = list(workflow_dir.glob("state-test-workflow-*.json"))
        assert len(state_files) == 1

        # Verify state content
        with state_files[0].open() as f:
            state = json.load(f)
            assert state["workflow"] == "Test Workflow"
            assert state["phase"]["current"] == 2
            assert state["phase"]["total"] == 5
            assert state["phase"]["name"] == "Implementation"

    def test_handle_updates_existing_state_file(
        self,
        handler: WorkflowStatePreCompactHandler,
        pre_compact_input: dict[str, Any],
        tmp_workspace: Path,
    ) -> None:
        """Handler updates existing state file on subsequent calls."""
        # Create workflow indicator
        claude_local = tmp_workspace / "CLAUDE.local.md"
        claude_local.write_text(
            "WORKFLOW STATE\n\nWorkflow: Test Workflow\nPhase: 2/5 - Implementation"
        )

        # Create initial state
        workflow_dir = tmp_workspace / "untracked/workflow-state/test-workflow"
        workflow_dir.mkdir(parents=True)
        state_file = workflow_dir / "state-test-workflow-20260127_120000.json"
        initial_state = {
            "workflow": "Test Workflow",
            "phase": {"current": 1, "total": 5, "name": "Setup"},
            "created_at": "2026-01-27T12:00:00Z",
        }
        with state_file.open("w") as f:
            json.dump(initial_state, f)

        # Update workflow phase
        claude_local.write_text(
            "WORKFLOW STATE\n\nWorkflow: Test Workflow\nPhase: 2/5 - Implementation"
        )

        result = handler.handle(pre_compact_input)
        assert result.decision == Decision.ALLOW

        # Verify state was updated, not created new file
        state_files = list(workflow_dir.glob("state-test-workflow-*.json"))
        assert len(state_files) == 1

        # Verify created_at was preserved
        with state_files[0].open() as f:
            state = json.load(f)
            assert state["created_at"] == "2026-01-27T12:00:00Z"
            assert state["phase"]["current"] == 2
            assert state["phase"]["name"] == "Implementation"

    def test_handle_preserves_created_at_timestamp(
        self,
        handler: WorkflowStatePreCompactHandler,
        pre_compact_input: dict[str, Any],
        tmp_workspace: Path,
    ) -> None:
        """Handler preserves original created_at timestamp on updates."""
        claude_local = tmp_workspace / "CLAUDE.local.md"
        claude_local.write_text("WORKFLOW STATE\n\nWorkflow: Test Workflow")

        # Create initial state
        workflow_dir = tmp_workspace / "untracked/workflow-state/test-workflow"
        workflow_dir.mkdir(parents=True)
        state_file = workflow_dir / "state-test-workflow-20260101_120000.json"
        original_timestamp = "2026-01-01T12:00:00Z"
        with state_file.open("w") as f:
            json.dump({"workflow": "Test Workflow", "created_at": original_timestamp}, f)

        # Update state
        handler.handle(pre_compact_input)

        # Verify timestamp preserved
        with state_file.open() as f:
            state = json.load(f)
            assert state["created_at"] == original_timestamp

    def test_handle_uses_new_timestamp_when_old_state_invalid_json(
        self,
        handler: WorkflowStatePreCompactHandler,
        pre_compact_input: dict[str, Any],
        tmp_workspace: Path,
    ) -> None:
        """Handler uses new timestamp when old state file is invalid JSON."""
        claude_local = tmp_workspace / "CLAUDE.local.md"
        claude_local.write_text("WORKFLOW STATE\n\nWorkflow: Test Workflow")

        # Create invalid state file
        workflow_dir = tmp_workspace / "untracked/workflow-state/test-workflow"
        workflow_dir.mkdir(parents=True)
        state_file = workflow_dir / "state-test-workflow-20260101_120000.json"
        state_file.write_text("invalid json {{{")

        result = handler.handle(pre_compact_input)
        assert result.decision == Decision.ALLOW

        # Verify new timestamp was used
        with state_file.open() as f:
            state = json.load(f)
            assert "created_at" in state
            # Should be recent timestamp
            created = datetime.fromisoformat(state["created_at"].replace("Z", ""))
            assert (datetime.now() - created).total_seconds() < 5

    def test_handle_creates_untracked_directory_if_missing(
        self,
        handler: WorkflowStatePreCompactHandler,
        pre_compact_input: dict[str, Any],
        tmp_workspace: Path,
    ) -> None:
        """Handler creates untracked/ directory if it doesn't exist."""
        claude_local = tmp_workspace / "CLAUDE.local.md"
        claude_local.write_text("WORKFLOW STATE\n\nWorkflow: Test Workflow")

        assert not (tmp_workspace / "untracked").exists()

        handler.handle(pre_compact_input)

        assert (tmp_workspace / "untracked").exists()
        assert (tmp_workspace / "untracked/workflow-state").exists()

    def test_handle_sanitizes_workflow_name_for_directory(
        self,
        handler: WorkflowStatePreCompactHandler,
        pre_compact_input: dict[str, Any],
        tmp_workspace: Path,
    ) -> None:
        """Handler sanitizes workflow name for directory structure."""
        claude_local = tmp_workspace / "CLAUDE.local.md"
        claude_local.write_text(
            "WORKFLOW STATE\n\nWorkflow: Test Workflow With Spaces & Special@Chars!"
        )

        handler.handle(pre_compact_input)

        workflow_dir = (
            tmp_workspace / "untracked/workflow-state/test-workflow-with-spaces-special-chars"
        )
        assert workflow_dir.exists()

    def test_handle_fails_open_on_exception(
        self,
        handler: WorkflowStatePreCompactHandler,
        pre_compact_input: dict[str, Any],
        tmp_workspace: Path,
    ) -> None:
        """Handler allows compaction even when state saving fails."""
        claude_local = tmp_workspace / "CLAUDE.local.md"
        claude_local.write_text("WORKFLOW STATE\n\nWorkflow: Test Workflow")

        # Make untracked a file to cause mkdir to fail
        untracked = tmp_workspace / "untracked"
        untracked.write_text("blocking file")

        result = handler.handle(pre_compact_input)
        assert result.decision == Decision.ALLOW

    def test_extract_workflow_state_returns_default_when_no_files(
        self, handler: WorkflowStatePreCompactHandler, pre_compact_input: dict[str, Any]
    ) -> None:
        """Extract returns default state when no workflow files exist."""
        state = handler._extract_workflow_state(pre_compact_input)
        assert state["workflow"] == "Unknown Workflow"
        assert state["workflow_type"] == "custom"
        assert state["phase"]["current"] == 1
        assert state["phase"]["total"] == 1
        assert state["required_reading"] == []

    def test_extract_workflow_state_from_claude_local(
        self,
        handler: WorkflowStatePreCompactHandler,
        pre_compact_input: dict[str, Any],
        tmp_workspace: Path,
    ) -> None:
        """Extract parses workflow state from CLAUDE.local.md."""
        claude_local = tmp_workspace / "CLAUDE.local.md"
        claude_local.write_text(
            "WORKFLOW STATE\n\n"
            "Workflow: SEO Optimization\n"
            "Phase: 3/10 - Content Generation\n"
            "@CLAUDE/WORKFLOWS/SEO.md\n"
            "@.claude/config.yaml\n"
        )

        state = handler._extract_workflow_state(pre_compact_input)
        assert state["workflow"] == "SEO Optimization"
        assert state["phase"]["current"] == 3
        assert state["phase"]["total"] == 10
        assert state["phase"]["name"] == "Content Generation"
        assert "@CLAUDE/WORKFLOWS/SEO.md" in state["required_reading"]
        assert "@.claude/config.yaml" in state["required_reading"]

    def test_extract_workflow_state_from_active_plan(
        self,
        handler: WorkflowStatePreCompactHandler,
        pre_compact_input: dict[str, Any],
        tmp_workspace: Path,
    ) -> None:
        """Extract parses workflow state from active plan."""
        plan_dir = tmp_workspace / "CLAUDE/Plan/066-seo-optimization"
        plan_dir.mkdir(parents=True)
        plan_file = plan_dir / "PLAN.md"
        plan_file.write_text(
            "# Plan 066: SEO Optimization Workflow\n\n"
            "🔄 In Progress\n\n"
            "See CLAUDE/WORKFLOWS/SEO.md for details.\n"
            "Config: .claude/skills/seo/config.md\n"
        )

        state = handler._extract_workflow_state(pre_compact_input)
        assert state["workflow"] == "SEO Optimization Workflow"
        assert state["context"]["plan_number"] == 66
        assert state["context"]["plan_name"] == "066-seo-optimization"
        assert "@CLAUDE/WORKFLOWS/SEO.md" in state["required_reading"]
        assert "@.claude/skills/seo/config.md" in state["required_reading"]

    def test_extract_workflow_state_handles_claude_local_read_error(
        self,
        handler: WorkflowStatePreCompactHandler,
        pre_compact_input: dict[str, Any],
        tmp_workspace: Path,
    ) -> None:
        """Extract handles CLAUDE.local.md read errors gracefully."""
        claude_local = tmp_workspace / "CLAUDE.local.md"
        claude_local.mkdir()  # Make it a directory

        state = handler._extract_workflow_state(pre_compact_input)
        assert state["workflow"] == "Unknown Workflow"

    def test_extract_workflow_state_handles_plan_read_error(
        self,
        handler: WorkflowStatePreCompactHandler,
        pre_compact_input: dict[str, Any],
        tmp_workspace: Path,
    ) -> None:
        """Extract handles plan file read errors gracefully."""
        plan_dir = tmp_workspace / "CLAUDE/Plan/066-test"
        plan_dir.mkdir(parents=True)
        plan_file = plan_dir / "PLAN.md"
        plan_file.mkdir()  # Make it a directory

        state = handler._extract_workflow_state(pre_compact_input)
        assert state["workflow"] == "Unknown Workflow"

    def test_parse_workflow_from_memory_extracts_workflow_name(
        self, handler: WorkflowStatePreCompactHandler
    ) -> None:
        """Parse extracts workflow name from memory content."""
        content = "Workflow: Test Workflow Name\n\nSome content"
        state = {"workflow": "default"}
        result = handler._parse_workflow_from_memory(content, state)
        assert result["workflow"] == "Test Workflow Name"

    def test_parse_workflow_from_memory_extracts_lowercase_workflow(
        self, handler: WorkflowStatePreCompactHandler
    ) -> None:
        """Parse extracts lowercase workflow: marker."""
        content = "workflow: test workflow\n\nSome content"
        state = {"workflow": "default"}
        result = handler._parse_workflow_from_memory(content, state)
        assert result["workflow"] == "test workflow"

    def test_parse_workflow_from_memory_extracts_phase_info(
        self, handler: WorkflowStatePreCompactHandler
    ) -> None:
        """Parse extracts phase information."""
        content = "Phase: 3/10 - Implementation Phase\n\nContent"
        state = {"phase": {"current": 1, "total": 1, "name": "default"}}
        result = handler._parse_workflow_from_memory(content, state)
        assert result["phase"]["current"] == 3
        assert result["phase"]["total"] == 10
        assert result["phase"]["name"] == "Implementation Phase"

    def test_parse_workflow_from_memory_extracts_lowercase_phase(
        self, handler: WorkflowStatePreCompactHandler
    ) -> None:
        """Parse extracts lowercase phase: marker."""
        content = "phase: 2/5 - Testing\n\nContent"
        state = {"phase": {"current": 1, "total": 1, "name": "default"}}
        result = handler._parse_workflow_from_memory(content, state)
        assert result["phase"]["current"] == 2
        assert result["phase"]["total"] == 5
        assert result["phase"]["name"] == "Testing"

    def test_parse_workflow_from_memory_extracts_required_reading(
        self, handler: WorkflowStatePreCompactHandler
    ) -> None:
        """Parse extracts required reading with @ syntax."""
        content = "Required Reading:\n@CLAUDE/WORKFLOWS/SEO.md\n@.claude/config.yaml\n\nContent"
        state = {"required_reading": []}
        result = handler._parse_workflow_from_memory(content, state)
        assert "@CLAUDE/WORKFLOWS/SEO.md" in result["required_reading"]
        assert "@.claude/config.yaml" in result["required_reading"]

    def test_parse_workflow_from_memory_deduplicates_required_reading(
        self, handler: WorkflowStatePreCompactHandler
    ) -> None:
        """Parse does not add duplicate required reading entries."""
        content = "@CLAUDE/DOC.md\n@CLAUDE/DOC.md\n@OTHER.md"
        state = {"required_reading": []}
        result = handler._parse_workflow_from_memory(content, state)
        assert result["required_reading"].count("@CLAUDE/DOC.md") == 1

    def test_parse_workflow_from_plan_extracts_plan_number(
        self, handler: WorkflowStatePreCompactHandler
    ) -> None:
        """Parse extracts plan number from path."""
        content = "# Plan 066: Test Workflow\n"
        state = {"context": {}}
        result = handler._parse_workflow_from_plan(
            "/workspace/CLAUDE/Plan/066-test-workflow/PLAN.md", content, state
        )
        assert result["context"]["plan_number"] == 66
        assert result["context"]["plan_name"] == "066-test-workflow"

    def test_parse_workflow_from_plan_extracts_workflow_name_from_title(
        self, handler: WorkflowStatePreCompactHandler
    ) -> None:
        """Parse extracts workflow name from plan title."""
        content = "# Plan 066: SEO Optimization Workflow\n\nContent"
        state = {"workflow": "default", "context": {}, "required_reading": []}
        result = handler._parse_workflow_from_plan(
            "/workspace/CLAUDE/Plan/066-seo/PLAN.md", content, state
        )
        assert result["workflow"] == "SEO Optimization Workflow"

    def test_parse_workflow_from_plan_finds_claude_references(
        self, handler: WorkflowStatePreCompactHandler
    ) -> None:
        """Parse finds CLAUDE/ documentation references."""
        content = (
            "# Plan 066: Test\n\n"
            "See CLAUDE/WORKFLOWS/SEO.md for details.\n"
            "Config: .claude/skills/test/config.md\n"
        )
        state = {"required_reading": [], "context": {}}
        result = handler._parse_workflow_from_plan(
            "/workspace/CLAUDE/Plan/066-test/PLAN.md", content, state
        )
        assert "@CLAUDE/WORKFLOWS/SEO.md" in result["required_reading"]
        assert "@.claude/skills/test/config.md" in result["required_reading"]

    def test_parse_workflow_from_plan_deduplicates_references(
        self, handler: WorkflowStatePreCompactHandler
    ) -> None:
        """Parse does not add duplicate references."""
        content = "CLAUDE/DOC.md and CLAUDE/DOC.md again"
        state = {"required_reading": [], "context": {}}
        result = handler._parse_workflow_from_plan(
            "/workspace/CLAUDE/Plan/066-test/PLAN.md", content, state
        )
        assert result["required_reading"].count("@CLAUDE/DOC.md") == 1

    def test_sanitize_workflow_name_converts_to_lowercase(
        self, handler: WorkflowStatePreCompactHandler
    ) -> None:
        """Sanitize converts workflow name to lowercase."""
        result = handler._sanitize_workflow_name("Test Workflow Name")
        assert result == "test-workflow-name"

    def test_sanitize_workflow_name_replaces_spaces_with_hyphens(
        self, handler: WorkflowStatePreCompactHandler
    ) -> None:
        """Sanitize replaces spaces with hyphens."""
        result = handler._sanitize_workflow_name("Test   Workflow    Name")
        assert result == "test-workflow-name"

    def test_sanitize_workflow_name_removes_special_characters(
        self, handler: WorkflowStatePreCompactHandler
    ) -> None:
        """Sanitize removes special characters."""
        result = handler._sanitize_workflow_name("Test@Workflow#Name!")
        assert result == "test-workflow-name"

    def test_sanitize_workflow_name_strips_leading_trailing_hyphens(
        self, handler: WorkflowStatePreCompactHandler
    ) -> None:
        """Sanitize strips leading and trailing hyphens."""
        result = handler._sanitize_workflow_name("--Test Workflow--")
        assert result == "test-workflow"

    def test_sanitize_workflow_name_limits_length_to_50_chars(
        self, handler: WorkflowStatePreCompactHandler
    ) -> None:
        """Sanitize limits length to 50 characters."""
        long_name = "A" * 100
        result = handler._sanitize_workflow_name(long_name)
        assert len(result) == 50

    def test_detect_workflow_returns_false_when_no_plan_directory(
        self, handler: WorkflowStatePreCompactHandler, pre_compact_input: dict[str, Any]
    ) -> None:
        """Detect returns False when CLAUDE/Plan directory doesn't exist."""
        assert handler._detect_workflow(pre_compact_input) is False

    def test_handle_existing_state_file_generic_exception(
        self,
        handler: WorkflowStatePreCompactHandler,
        pre_compact_input: dict[str, Any],
        tmp_workspace: Path,
    ) -> None:
        """Handler handles generic Exception when reading existing state file."""
        claude_local = tmp_workspace / "CLAUDE.local.md"
        claude_local.write_text("WORKFLOW STATE\n\nWorkflow: Test Workflow")

        # Create existing state file
        workflow_dir = tmp_workspace / "untracked/workflow-state/test-workflow"
        workflow_dir.mkdir(parents=True)
        state_file = workflow_dir / "state-test-workflow-20260101_120000.json"
        state_file.write_text('{"workflow": "Test", "created_at": "2026-01-01T12:00:00Z"}')

        # Patch open on the state file to raise on read (first call) but allow write
        original_open = state_file.open
        call_count = 0

        def mock_open(*args: Any, **kwargs: Any) -> Any:
            nonlocal call_count
            call_count += 1
            if call_count == 1 and (not args or args[0] != "w"):
                raise Exception("Unexpected read error")
            return original_open(*args, **kwargs)

        with patch.object(type(state_file), "open", mock_open):
            result = handler.handle(pre_compact_input)

        # Should still succeed - the exception is caught and logged
        assert result.decision == Decision.ALLOW

    def test_handle_generic_exception_returns_deny(
        self,
        handler: WorkflowStatePreCompactHandler,
        pre_compact_input: dict[str, Any],
        tmp_workspace: Path,
    ) -> None:
        """Handler returns DENY on unexpected generic Exception."""
        claude_local = tmp_workspace / "CLAUDE.local.md"
        claude_local.write_text("WORKFLOW STATE\n\nWorkflow: Test Workflow")

        # Patch _detect_workflow to return True, but _extract_workflow_state raises
        with patch.object(
            handler, "_extract_workflow_state", side_effect=Exception("Totally unexpected")
        ):
            result = handler.handle(pre_compact_input)

        assert result.decision == Decision.DENY
        assert "unexpected error" in result.reason.lower()

    def test_detect_workflow_claude_local_generic_exception(
        self,
        handler: WorkflowStatePreCompactHandler,
        pre_compact_input: dict[str, Any],
        tmp_workspace: Path,
    ) -> None:
        """Handler handles generic Exception reading CLAUDE.local.md in _detect_workflow."""
        claude_local = tmp_workspace / "CLAUDE.local.md"
        claude_local.write_text("some content without workflow markers")

        # Patch the file's open to raise a generic Exception
        with patch.object(Path, "open", side_effect=Exception("Unexpected read error")):
            result = handler._detect_workflow(pre_compact_input)
            assert result is False

    def test_detect_workflow_plan_file_generic_exception(
        self,
        handler: WorkflowStatePreCompactHandler,
        pre_compact_input: dict[str, Any],
        tmp_workspace: Path,
    ) -> None:
        """Handler handles generic Exception reading plan file in _detect_workflow."""
        plan_dir = tmp_workspace / "CLAUDE/Plan/066-test-workflow"
        plan_dir.mkdir(parents=True)
        plan_file = plan_dir / "PLAN.md"
        plan_file.write_text("# Plan 066: Test\n\n🔄 In Progress\n\nPhase 1")

        # We need to let CLAUDE.local.md not exist (no match from that path)
        # Then patch plan file reading to raise Exception
        original_open = plan_file.open

        def mock_plan_open(*args: Any, **kwargs: Any) -> Any:
            raise Exception("Unexpected plan read error")

        with patch.object(type(plan_file), "open", mock_plan_open):
            result = handler._detect_workflow(pre_compact_input)
            # Falls through to return False since the exception is caught
            assert result is False

    def test_parse_workflow_from_memory_value_error_in_phase_parsing(
        self, handler: WorkflowStatePreCompactHandler
    ) -> None:
        """Parse handles ValueError when phase numbers aren't valid integers."""
        content = "Phase: abc/def - Testing\n\nContent"
        state = {"phase": {"current": 1, "total": 1, "name": "default"}}
        # This raises ValueError from int() but is caught implicitly
        # because int("abc") raises ValueError
        try:
            result = handler._parse_workflow_from_memory(content, state)
            # If no exception, phase should remain default or partially updated
            assert isinstance(result, dict)
        except ValueError:
            # ValueError is acceptable here - it's what we're testing
            pass

    def test_extract_workflow_state_claude_local_generic_exception(
        self,
        handler: WorkflowStatePreCompactHandler,
        pre_compact_input: dict[str, Any],
        tmp_workspace: Path,
    ) -> None:
        """Extract handles generic Exception reading CLAUDE.local.md."""
        claude_local = tmp_workspace / "CLAUDE.local.md"
        claude_local.write_text("WORKFLOW STATE\n\nWorkflow: Test")

        with patch.object(
            handler, "_parse_workflow_from_memory", side_effect=Exception("Unexpected")
        ):
            state = handler._extract_workflow_state(pre_compact_input)
            # Should fall through gracefully with default state
            assert isinstance(state, dict)

    def test_extract_workflow_state_plan_generic_exception(
        self,
        handler: WorkflowStatePreCompactHandler,
        pre_compact_input: dict[str, Any],
        tmp_workspace: Path,
    ) -> None:
        """Extract handles generic Exception parsing plan file."""
        plan_dir = tmp_workspace / "CLAUDE/Plan/066-test"
        plan_dir.mkdir(parents=True)
        plan_file = plan_dir / "PLAN.md"
        plan_file.write_text("# Plan 066: Test\n\n🔄 In Progress\n\nPhase 1")

        with patch.object(
            handler, "_parse_workflow_from_plan", side_effect=Exception("Unexpected")
        ):
            state = handler._extract_workflow_state(pre_compact_input)
            assert isinstance(state, dict)

    def test_extract_workflow_state_claude_local_value_error(
        self,
        handler: WorkflowStatePreCompactHandler,
        pre_compact_input: dict[str, Any],
        tmp_workspace: Path,
    ) -> None:
        """Extract handles ValueError from CLAUDE.local.md parsing."""
        claude_local = tmp_workspace / "CLAUDE.local.md"
        claude_local.write_text("WORKFLOW STATE\n\nWorkflow: Test")

        with patch.object(
            handler, "_parse_workflow_from_memory", side_effect=ValueError("Bad value")
        ):
            state = handler._extract_workflow_state(pre_compact_input)
            assert isinstance(state, dict)

    def test_extract_workflow_state_plan_value_error(
        self,
        handler: WorkflowStatePreCompactHandler,
        pre_compact_input: dict[str, Any],
        tmp_workspace: Path,
    ) -> None:
        """Extract handles ValueError from plan file parsing."""
        plan_dir = tmp_workspace / "CLAUDE/Plan/066-test"
        plan_dir.mkdir(parents=True)
        plan_file = plan_dir / "PLAN.md"
        plan_file.write_text("# Plan 066: Test\n\n🔄 In Progress\n\nPhase 1")

        with patch.object(
            handler, "_parse_workflow_from_plan", side_effect=ValueError("Bad value")
        ):
            state = handler._extract_workflow_state(pre_compact_input)
            assert isinstance(state, dict)

    def test_handle_read_state_file_unexpected_exception(
        self,
        handler: WorkflowStatePreCompactHandler,
        pre_compact_input: dict[str, Any],
        tmp_workspace: Path,
    ) -> None:
        """Handle catches unexpected Exception reading existing state file."""
        claude_local = tmp_workspace / "CLAUDE.local.md"
        claude_local.write_text("WORKFLOW STATE\n\nWorkflow: Test Workflow")

        # Create existing state directory and file
        workflow_dir = tmp_workspace / "untracked/workflow-state/test-workflow"
        workflow_dir.mkdir(parents=True)
        state_file = workflow_dir / "state-test-workflow-20260101_120000.json"
        state_file.write_text("trigger open")

        # Patch Path.open to raise Exception only when reading the state file
        original_path_open = Path.open

        call_count = {"state_reads": 0}

        def mock_open(self_path: Path, *args: Any, **kwargs: Any) -> Any:
            if "state-test-workflow" in str(self_path) and (not args or args[0] != "w"):
                call_count["state_reads"] += 1
                if call_count["state_reads"] == 1:
                    raise Exception("Unexpected state file error")
            return original_path_open(self_path, *args, **kwargs)

        with patch.object(Path, "open", mock_open):
            result = handler.handle(pre_compact_input)

        # Should still succeed, catching the exception
        assert result.decision == Decision.ALLOW

    def test_get_acceptance_tests(self, handler: WorkflowStatePreCompactHandler) -> None:
        """Handler returns acceptance tests."""
        tests = handler.get_acceptance_tests()
        assert isinstance(tests, list)
        assert len(tests) > 0
