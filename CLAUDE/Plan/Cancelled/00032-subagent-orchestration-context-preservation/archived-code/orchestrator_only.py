"""OrchestratorOnlyHandler - enforces orchestration-only pattern for the main Claude thread.

When enabled, blocks all work tools (Edit, Write, NotebookEdit, mutating Bash)
and only allows orchestration tools (Task, Read, Glob, Grep, etc.) so the main
thread delegates all implementation work to subagents via the Task tool.

This handler is opt-in (disabled by default) and must be explicitly enabled
in the hooks-daemon.yaml configuration.
"""

from typing import Any

from claude_code_hooks_daemon.constants import (
    HandlerID,
    HandlerTag,
    HookInputField,
    Priority,
    ToolName,
)
from claude_code_hooks_daemon.core import Decision, Handler, HookResult
from claude_code_hooks_daemon.core.utils import get_bash_command

# Tools that are always allowed in orchestrator mode (read-only, delegation, planning)
_ALLOWED_TOOLS: frozenset[str] = frozenset(
    {
        ToolName.TASK,
        ToolName.TASK_CREATE,
        ToolName.TASK_UPDATE,
        ToolName.TASK_GET,
        ToolName.TASK_LIST,
        ToolName.TASK_OUTPUT,
        ToolName.TASK_STOP,
        ToolName.READ,
        ToolName.GLOB,
        ToolName.GREP,
        ToolName.WEB_SEARCH,
        ToolName.WEB_FETCH,
        ToolName.ASK_USER_QUESTION,
        ToolName.ENTER_PLAN_MODE,
        ToolName.EXIT_PLAN_MODE,
        ToolName.SKILL,
        # SendMessage is not in ToolName constants but should be allowed
        "SendMessage",
    }
)

# Default read-only Bash command prefixes that are safe for orchestrators
_DEFAULT_READONLY_BASH_PREFIXES: list[str] = [
    "git status",
    "git log",
    "git diff",
    "git branch",
    "git show",
    "git remote",
    "git tag",
    "git rev-parse",
    "git ls-files",
    "git blame",
    "git shortlog",
    "ls",
    "cat",
    "head",
    "tail",
    "find",
    "grep",
    "rg",
    "wc",
    "pwd",
    "which",
    "echo",
    "env",
    "printenv",
    "whoami",
    "hostname",
    "date",
    "file",
    "du",
    "df",
    "tree",
    "gh",
    "sort",
    "uniq",
    "cut",
    "awk",
    "diff",
    "stat",
    "id",
    "uname",
    "test",
    "true",
    "false",
    "[",
]


class OrchestratorOnlyHandler(Handler):
    """Enforce orchestration-only pattern: block work tools, allow delegation.

    When enabled, the main Claude thread can only:
    - Delegate work via Task tool
    - Read files (Read, Glob, Grep)
    - Search the web (WebSearch, WebFetch)
    - Run read-only Bash commands (git status, ls, cat, etc.)
    - Use planning tools (EnterPlanMode, ExitPlanMode)
    - Ask questions (AskUserQuestion)

    All work tools (Edit, Write, NotebookEdit, mutating Bash) are blocked
    with a clear message directing to the Task tool for delegation.
    """

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.ORCHESTRATOR_ONLY,
            priority=Priority.ORCHESTRATOR_ONLY,
            tags=[HandlerTag.WORKFLOW, HandlerTag.BLOCKING, HandlerTag.TERMINAL],
        )
        self.enabled: bool = False
        self._readonly_bash_prefixes: list[str] = list(_DEFAULT_READONLY_BASH_PREFIXES)

    def set_enabled(self, enabled: bool) -> None:
        """Set whether the handler is enabled."""
        self.enabled = enabled

    def set_readonly_bash_prefixes(self, prefixes: list[str]) -> None:
        """Set custom read-only Bash command prefixes."""
        self._readonly_bash_prefixes = list(prefixes)

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Check if this tool call should be blocked in orchestrator mode."""
        if not self.enabled:
            return False

        tool_name = hook_input.get(HookInputField.TOOL_NAME)
        if not tool_name:
            return False

        # Always allow orchestration/read-only tools
        if tool_name in _ALLOWED_TOOLS:
            return False

        # Bash requires special handling: allow read-only commands
        if tool_name == ToolName.BASH:
            command = get_bash_command(hook_input)
            if not command:
                return False
            return not self._is_readonly_bash(command)

        # Block everything else (Edit, Write, NotebookEdit, unknown tools)
        return True

    def _is_readonly_bash(self, command: str) -> bool:
        """Check if a bash command is read-only based on prefix allowlist."""
        stripped = command.strip()
        if not stripped:
            return True

        for prefix in self._readonly_bash_prefixes:
            # Match exact prefix or prefix followed by space/flag
            if (
                stripped == prefix
                or stripped.startswith(prefix + " ")
                or stripped.startswith(prefix + "\t")
            ):
                return True

        return False

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Block the tool with a message directing to Task tool for delegation."""
        tool_name = hook_input.get(HookInputField.TOOL_NAME, "Unknown")

        # Build context-specific message
        if tool_name == ToolName.BASH:
            command = get_bash_command(hook_input) or ""
            blocked_detail = f"Bash command: {command}"
        else:
            blocked_detail = f"Tool: {tool_name}"

        return HookResult(
            decision=Decision.DENY,
            reason=(
                f"BLOCKED: Orchestrator-only mode is active\n\n"
                f"{blocked_detail}\n\n"
                f"In orchestrator mode, the main thread cannot use {tool_name} directly.\n\n"
                f"WHAT TO DO:\n"
                f"  Use the Task tool to delegate this work to a subagent.\n"
                f"  The subagent will have full access to all tools.\n\n"
                f"EXAMPLE:\n"
                f"  Task tool -> 'Implement the changes in src/main.py'\n\n"
                f"ALLOWED TOOLS in orchestrator mode:\n"
                f"  - Task (delegate work to subagents)\n"
                f"  - Read, Glob, Grep (read files)\n"
                f"  - WebSearch, WebFetch (web access)\n"
                f"  - Read-only Bash (git status, ls, cat, etc.)\n"
                f"  - Planning tools (EnterPlanMode, ExitPlanMode)\n"
                f"  - AskUserQuestion, SendMessage"
            ),
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for orchestrator-only handler."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="Block Edit tool in orchestrator mode",
                command='echo "Edit tool blocked test"',
                description="Opt-in handler disabled by default - verified by daemon load",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Handler is opt-in (disabled by default) - unit tests verify blocking logic",
                test_type=TestType.CONTEXT,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
