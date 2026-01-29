"""Claude Code tool name constants - single source of truth.

This module defines all Claude Code tool names used in hook events.
These are the tool names that appear in the toolName field of hook inputs.

Usage:
    from claude_code_hooks_daemon.constants import ToolName

    # In handler matches():
    def matches(self, hook_input: dict[str, Any]) -> bool:
        tool_name = hook_input.get("toolName")
        return tool_name == ToolName.BASH

    # Type-safe comparisons:
    if tool_name in [ToolName.WRITE, ToolName.EDIT]:
        # Handle file operations
        pass
"""

from __future__ import annotations

from typing import Literal


class ToolName:
    """Claude Code tool names - single source of truth.

    These are the exact tool names as they appear in Claude Code's hook
    input JSON (camelCase format matching the toolName field).

    Tool Categories:
        - Command execution: Bash
        - File operations: Write, Edit, Read, Glob, Grep
        - Web access: WebSearch, WebFetch
        - Task management: Task, TaskCreate, TaskUpdate, TaskGet, TaskList
        - Skills: Skill
        - Plan mode: EnterPlanMode, ExitPlanMode
        - Questions: AskUserQuestion
        - Notebook: NotebookEdit
    """

    # Command execution
    BASH = "Bash"

    # File operations
    WRITE = "Write"
    EDIT = "Edit"
    READ = "Read"
    GLOB = "Glob"
    GREP = "Grep"

    # Web access
    WEB_SEARCH = "WebSearch"
    WEB_FETCH = "WebFetch"

    # Task management
    TASK = "Task"
    TASK_CREATE = "TaskCreate"
    TASK_UPDATE = "TaskUpdate"
    TASK_GET = "TaskGet"
    TASK_LIST = "TaskList"
    TASK_OUTPUT = "TaskOutput"
    TASK_STOP = "TaskStop"

    # Skills
    SKILL = "Skill"

    # Plan mode
    ENTER_PLAN_MODE = "EnterPlanMode"
    EXIT_PLAN_MODE = "ExitPlanMode"

    # User interaction
    ASK_USER_QUESTION = "AskUserQuestion"

    # Notebook operations
    NOTEBOOK_EDIT = "NotebookEdit"


# Type alias for valid tool names (for type checking)
ToolNameLiteral = Literal[
    "Bash",
    "Write",
    "Edit",
    "Read",
    "Glob",
    "Grep",
    "WebSearch",
    "WebFetch",
    "Task",
    "TaskCreate",
    "TaskUpdate",
    "TaskGet",
    "TaskList",
    "TaskOutput",
    "TaskStop",
    "Skill",
    "EnterPlanMode",
    "ExitPlanMode",
    "AskUserQuestion",
    "NotebookEdit",
]


__all__ = ["ToolName", "ToolNameLiteral"]
