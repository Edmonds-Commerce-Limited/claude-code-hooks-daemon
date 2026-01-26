#!/usr/bin/env python3
"""
WorkflowStatePreCompactHandler - Preserves workflow state before compaction.

Detects formal workflows and saves state to timestamped file in ./untracked/
for restoration after compaction.
"""

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.core import Decision, Handler, HookResult
from claude_code_hooks_daemon.core.utils import get_workspace_root


class WorkflowStatePreCompactHandler(Handler):
    """Detect and preserve workflow state before compaction."""

    def __init__(self, workspace_root: str | Path | None = None) -> None:
        """
        Initialize handler with optional workspace root for test isolation.

        Args:
            workspace_root: Optional Path to project root (for testing).
                          If None, auto-detects using get_workspace_root().
                          This allows tests to provide isolated test directories.
        """
        super().__init__(name="workflow-state-precompact")
        self.workspace_root = Path(workspace_root) if workspace_root else get_workspace_root()

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """
        Match if formal workflow is active.

        Detection question: "Are you in a formally documented workflow?"

        Args:
            hook_input: PreCompact hook input with trigger, session_id, etc.

        Returns:
            True if formal workflow detected, False otherwise
        """
        # Check if this is actually a PreCompact event
        if hook_input.get("hook_event_name") != "PreCompact":
            return False

        # Detect workflow
        return self._detect_workflow(hook_input)

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """
        Update or create workflow state file.

        Lifecycle:
        - If workflow state file exists: UPDATE it with current state
        - If workflow state file missing: CREATE it with start_time timestamp
        - File persists across compaction cycles
        - Only deleted when workflow completes

        Directory structure: ./untracked/workflow-state/{workflow-name}/
        Filename format: state-{workflow-name}-{start_time}.json

        Args:
            hook_input: PreCompact hook input

        Returns:
            HookResult with decision=Decision.ALLOW (always allows compaction)
        """
        try:
            # Only process if workflow is detected
            if not self._detect_workflow(hook_input):
                return HookResult(decision=Decision.ALLOW)

            # Extract workflow state
            workflow_state = self._extract_workflow_state(hook_input)

            # Create untracked/ directory if it doesn't exist
            untracked_dir = self.workspace_root / "untracked"
            untracked_dir.mkdir(parents=True, exist_ok=True)

            # Sanitize workflow name for directory/filename
            workflow_name = self._sanitize_workflow_name(workflow_state["workflow"])

            # Create workflow-specific directory
            workflow_dir = untracked_dir / "workflow-state" / workflow_name
            workflow_dir.mkdir(parents=True, exist_ok=True)

            # Look for existing state file for this workflow
            existing_files = list(workflow_dir.glob(f"state-{workflow_name}-*.json"))

            if existing_files:
                # Update existing file (should only be one)
                state_file = existing_files[0]
                # Preserve the original created_at timestamp
                try:
                    with state_file.open() as f:
                        old_state = json.load(f)
                        workflow_state["created_at"] = old_state.get(
                            "created_at", workflow_state["created_at"]
                        )
                except Exception:
                    pass
            else:
                # Create new file with start_time timestamp
                start_time = datetime.now().strftime("%Y%m%d_%H%M%S")
                state_file = workflow_dir / f"state-{workflow_name}-{start_time}.json"

            # Write/update state file
            with state_file.open("w") as f:
                json.dump(workflow_state, f, indent=2)

        except Exception:
            # Fail open - if anything goes wrong, just allow compaction
            pass

        # Always allow compaction to proceed
        return HookResult(decision=Decision.ALLOW)

    def _detect_workflow(self, _hook_input: dict[str, Any]) -> bool:
        """
        Detect if agent is in a formal workflow.

        Detection methods (in order):
        1. Check for workflow state in CLAUDE.local.md
        2. Check for active plan with workflow phases
        3. Check conversation context for workflow markers

        Args:
            _hook_input: PreCompact hook input (unused - detection uses filesystem)

        Returns:
            True if formal workflow detected, False otherwise
        """
        # Method 1: Check CLAUDE.local.md for workflow state
        claude_local = self.workspace_root / "CLAUDE.local.md"
        if claude_local.exists():
            try:
                with claude_local.open() as f:
                    content = f.read()
                    if "WORKFLOW STATE" in content or "workflow:" in content.lower():
                        return True
            except Exception:
                pass

        # Method 2: Check for active plans
        plan_dir = self.workspace_root / "CLAUDE/Plan"
        if not plan_dir.exists():
            return False
        plan_files = list(plan_dir.glob("*/PLAN.md"))
        for plan_file in plan_files:
            try:
                with plan_file.open() as f:
                    content = f.read()
                    # Check for "In Progress" status and phase markers
                    in_progress = "🔄 In Progress" in content or "🔄 in_progress" in content.lower()
                    has_phase_or_workflow = (
                        "phase" in content.lower() or "workflow" in content.lower()
                    )
                    if in_progress and has_phase_or_workflow:
                        return True
            except Exception:
                pass

        # Method 3: Check transcript for workflow skill markers
        # (Would require reading transcript_path, but for now we keep it simple)

        # No formal workflow detected
        return False

    def _extract_workflow_state(self, _hook_input: dict[str, Any]) -> dict[str, Any]:
        """
        Extract workflow state from current context.

        Builds generic workflow state structure by:
        1. Parsing CLAUDE.local.md for workflow info
        2. Checking active plan for context
        3. Building REQUIRED READING list with @ syntax

        Args:
            _hook_input: PreCompact hook input (unused - extraction uses filesystem)

        Returns:
            dict: Workflow state in standard format
        """
        # Initialize default state
        state = {
            "workflow": "Unknown Workflow",
            "workflow_type": "custom",
            "phase": {"current": 1, "total": 1, "name": "In Progress", "status": "in_progress"},
            "required_reading": [],
            "context": {},
            "key_reminders": [],
            "created_at": datetime.now().isoformat() + "Z",
        }

        # Try to extract from CLAUDE.local.md
        claude_local = self.workspace_root / "CLAUDE.local.md"
        if claude_local.exists():
            try:
                with claude_local.open() as f:
                    content = f.read()
                    state = self._parse_workflow_from_memory(content, state)
            except Exception:
                pass

        # Try to extract from active plan
        plan_dir = self.workspace_root / "CLAUDE/Plan"
        plan_files = list(plan_dir.glob("*/PLAN.md")) if plan_dir.exists() else []
        for plan_file in plan_files:
            try:
                with plan_file.open() as f:
                    content = f.read()
                    if "🔄 In Progress" in content or "🔄 in_progress" in content.lower():
                        state = self._parse_workflow_from_plan(str(plan_file), content, state)
                        break
            except Exception:
                pass

        return state

    def _parse_workflow_from_memory(self, content: str, state: dict[str, Any]) -> dict[str, Any]:
        """
        Parse workflow state from CLAUDE.local.md content.

        Args:
            content: File content from CLAUDE.local.md
            state: Current state dict to update

        Returns:
            dict: Updated state
        """
        # Look for workflow markers
        lines = content.split("\n")

        for line in lines:
            # Extract workflow name
            if line.startswith("Workflow:") or line.startswith("workflow:"):
                state["workflow"] = line.split(":", 1)[1].strip()

            # Extract phase info
            if line.startswith("Phase:") or line.startswith("phase:"):
                phase_info = line.split(":", 1)[1].strip()
                # Try to parse "4/10 - SEO Generation" format
                if "/" in phase_info:
                    parts = phase_info.split("-", 1)
                    phase_numbers = parts[0].strip().split("/")
                    if len(phase_numbers) == 2:
                        state["phase"]["current"] = int(phase_numbers[0])
                        state["phase"]["total"] = int(phase_numbers[1])
                    if len(parts) > 1:
                        state["phase"]["name"] = parts[1].strip()

            # Extract required reading (look for @ syntax)
            if line.strip().startswith("@"):
                file_path = line.strip()
                if file_path not in state["required_reading"]:
                    state["required_reading"].append(file_path)

        return state

    def _parse_workflow_from_plan(
        self, plan_file: str, content: str, state: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Parse workflow state from active plan file.

        Args:
            plan_file: Path to PLAN.md file
            content: File content
            state: Current state dict to update

        Returns:
            dict: Updated state
        """
        # Extract plan number from path
        plan_path = Path(plan_file)
        plan_name = plan_path.parent.name

        # Parse plan number (format: 066-workflow-name)
        if plan_name and plan_name[0].isdigit():
            plan_number = int(plan_name.split("-", 1)[0])
            state["context"]["plan_number"] = plan_number
            state["context"]["plan_name"] = plan_name

        # Extract workflow name from plan title (first # heading)
        lines = content.split("\n")
        for line in lines:
            if line.startswith("# Plan"):
                # Format: "# Plan 066: Workflow Name"
                if ":" in line:
                    state["workflow"] = line.split(":", 1)[1].strip()
                break

        # Look for workflow documentation references
        for line in lines:
            # Find CLAUDE/ references that could be required reading
            if "CLAUDE/" in line or ".claude/" in line:
                # Extract file paths
                paths = re.findall(r"(CLAUDE/[^\s\)]+\.md)", line)
                paths += re.findall(r"(\.claude/[^\s\)]+\.md)", line)
                for path in paths:
                    formatted_path = f"@{path}"
                    if formatted_path not in state["required_reading"]:
                        state["required_reading"].append(formatted_path)

        return state

    def _sanitize_workflow_name(self, workflow_name: str) -> str:
        """
        Sanitize workflow name for use in directory/filename.

        Converts to lowercase, replaces spaces/special chars with hyphens.

        Args:
            workflow_name: Raw workflow name from state

        Returns:
            str: Sanitized name safe for filesystem
        """
        # Convert to lowercase
        sanitized = workflow_name.lower()
        # Replace spaces and special characters with hyphens
        sanitized = re.sub(r"[^a-z0-9]+", "-", sanitized)
        # Remove leading/trailing hyphens
        sanitized = sanitized.strip("-")
        # Limit length to 50 characters
        sanitized = sanitized[:50]
        return sanitized
