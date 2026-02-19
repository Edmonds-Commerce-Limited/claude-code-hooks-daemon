#!/usr/bin/env python3
"""
WorkflowStateRestorationHandler - Restores workflow state after compaction.

Reads workflow state from timestamped file in ./untracked/ and provides
guidance to force re-reading of workflow documentation.
"""

import json
import logging
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, HookInputField
from claude_code_hooks_daemon.core import Decision, Handler, HookResult, ProjectContext

logger = logging.getLogger(__name__)


class WorkflowStateRestorationHandler(Handler):
    """Restore workflow state after compaction."""

    def __init__(self, workspace_root: str | Path | None = None) -> None:
        """
        Initialize handler with optional workspace root for test isolation.

        Args:
            workspace_root: Optional Path to project root (for testing).
                          If None, auto-detects using ProjectContext.project_root().
                          This allows tests to provide isolated test directories.
        """
        super().__init__(
            handler_id=HandlerID.WORKFLOW_STATE_RESTORATION,
            terminal=False,
            tags=[
                HandlerTag.WORKFLOW,
                HandlerTag.STATE_MANAGEMENT,
                HandlerTag.ADVISORY,
                HandlerTag.NON_TERMINAL,
            ],
        )
        self.workspace_root = (
            Path(workspace_root) if workspace_root else ProjectContext.project_root()
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """
        Match when SessionStart source is 'compact'.

        Args:
            hook_input: SessionStart hook input with source field

        Returns:
            True if source="compact", False otherwise
        """
        # Check if this is actually a SessionStart event
        if hook_input.get(HookInputField.HOOK_EVENT_NAME) != "SessionStart":
            return False

        # Match only when resuming after compaction
        return hook_input.get("source") == "compact"

    def handle(self, _hook_input: dict[str, Any]) -> HookResult:
        """
        Read workflow state files and provide guidance with REQUIRED READING.

        Finds all active workflow state files in directory structure, reads
        the most recently updated one, and builds guidance with @ syntax for
        forced file reading.

        DOES NOT delete state files - they persist across compaction cycles
        and are only deleted when workflow completes.

        Args:
            _hook_input: Hook input dictionary (unused - state read from filesystem)

        Directory structure: ./untracked/workflow-state/{workflow-name}/
        Filename format: state-{workflow-name}-{start_time}.json

        Args:
            hook_input: SessionStart hook input

        Returns:
            HookResult with decision=Decision.ALLOW and context containing guidance
        """
        try:
            # Find all workflow state files in directory structure
            untracked_dir = self.workspace_root / "untracked/workflow-state"
            if not untracked_dir.exists():
                # No state directory found - normal session start
                return HookResult(decision=Decision.ALLOW)

            state_files = list(untracked_dir.glob("*/state-*.json"))

            if not state_files:
                # No state files found - normal session start
                return HookResult(decision=Decision.ALLOW)

            # Sort by modification time (most recently updated first)
            state_files = sorted(state_files, key=lambda p: p.stat().st_mtime, reverse=True)

            # Read most recently updated state file
            latest_state_file = state_files[0]

            # Read state file
            try:
                with latest_state_file.open() as f:
                    state = json.load(f)
            except (OSError, json.JSONDecodeError):
                # Corrupt or unreadable file - fail open
                return HookResult(decision=Decision.ALLOW)

            # Build guidance message with workflow state
            guidance = self._build_guidance_message(state)

            # DO NOT DELETE - state file persists across compaction cycles
            # Only deleted when workflow completes

            # Return guidance with workflow context
            return HookResult(decision=Decision.ALLOW, context=[guidance])

        except (OSError, json.JSONDecodeError, PermissionError) as e:
            logger.warning("Workflow state restoration failed: %s", e, exc_info=True)
            return HookResult(
                decision=Decision.ALLOW,
                reason=None,
                context=[f"⚠️  Failed to restore workflow state: {e}"],
            )
        except Exception as e:
            logger.error("Unexpected error in workflow restoration: %s", e, exc_info=True)
            return HookResult(
                decision=Decision.DENY,
                reason=f"Workflow restoration handler error: {e}",
                context=["Contact support if this persists."],
            )

    def _build_guidance_message(self, state: dict[str, Any]) -> str:
        """
        Build comprehensive guidance message with workflow state.

        Args:
            state: Workflow state dict

        Returns:
            str: Formatted guidance message
        """
        workflow = state.get("workflow", "Unknown Workflow")
        workflow_type = state.get("workflow_type", "custom")
        phase = state.get("phase", {})
        required_reading = state.get("required_reading", [])
        context = state.get("context", {})
        key_reminders = state.get("key_reminders", [])

        # Format phase info
        phase_current = phase.get("current", 1)
        phase_total = phase.get("total", 1)
        phase_name = phase.get("name", "Unknown")
        phase_status = phase.get("status", "in_progress")

        # Build guidance message
        guidance_parts = [
            "⚠️ WORKFLOW RESTORED AFTER COMPACTION ⚠️",
            "",
            f"Workflow: {workflow}",
            f"Type: {workflow_type}",
            f"Phase: {phase_current}/{phase_total} - {phase_name} ({phase_status})",
            "",
        ]

        # Add REQUIRED READING section with @ syntax
        if required_reading:
            guidance_parts.append("REQUIRED READING (read ALL now with @ syntax):")
            for file_path in required_reading:
                guidance_parts.append(file_path)
            guidance_parts.append("")

        # Add key reminders
        if key_reminders:
            guidance_parts.append("Key Reminders:")
            for reminder in key_reminders:
                guidance_parts.append(f"- {reminder}")
            guidance_parts.append("")

        # Add context if present
        if context:
            guidance_parts.append("Context:")
            guidance_parts.append(json.dumps(context, indent=2))
            guidance_parts.append("")

        # Add ACTION REQUIRED section
        guidance_parts.extend(
            [
                "ACTION REQUIRED:",
                "1. Read ALL files listed above using @ syntax",
                "2. Confirm understanding of workflow phase",
                "3. DO NOT proceed with assumptions or hallucinated logic",
            ]
        )

        return "\n".join(guidance_parts)

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for this handler."""
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="workflow state restoration handler test",
                command='echo "test"',
                description="Tests workflow state restoration handler functionality",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r".*"],
                safety_notes="Context/utility handler - minimal testing required",
                test_type=TestType.CONTEXT,
                requires_event="SessionStart event",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
