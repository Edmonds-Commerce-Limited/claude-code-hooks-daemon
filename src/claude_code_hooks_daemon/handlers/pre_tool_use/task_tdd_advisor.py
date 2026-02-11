"""TaskTddAdvisorHandler - advises on TDD when spawning implementation agents."""

import re
from typing import Any

from claude_code_hooks_daemon.constants import (
    HandlerID,
    HandlerTag,
    HookInputField,
    Priority,
    ToolName,
)
from claude_code_hooks_daemon.core import Decision, Handler, HookResult


class TaskTddAdvisorHandler(Handler):
    """Advise on TDD workflow when spawning Task agents for implementation work.

    This handler detects when the Task tool is being used to spawn agents for
    implementation work (coding, creating handlers, building features) and injects
    a reminder about TDD workflow:
    1. Write failing tests first (RED)
    2. Implement code to pass tests (GREEN)
    3. Refactor for clarity (REFACTOR)

    Advisory Only: This handler is non-terminal (terminal=False) and always allows
    the operation. It provides guidance without blocking.

    Matches:
    - Task tool with implementation keywords: implement, create handler, write code,
      add feature, build, develop, code up, write handler
    - Case-insensitive matching

    Does NOT match:
    - Research/exploration tasks: search, find, investigate, analyze, explore
    - Bug fixes: fix, debug (different workflow - reproduce bug first)
    - Read-only operations: read, review
    """

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.TASK_TDD_ADVISOR,
            priority=Priority.TASK_TDD_ADVISOR,
            terminal=False,  # Advisory only - does not block
            tags=[
                HandlerTag.TDD,
                HandlerTag.WORKFLOW,
                HandlerTag.ADVISORY,
                HandlerTag.NON_TERMINAL,
            ],
        )
        # Compile regex for implementation keywords
        self._implementation_pattern = re.compile(
            r"(implement|create.*handler|write\s+code|add\s+feature|build|develop|code\s+up|write\s+handler)",
            re.IGNORECASE,
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Check if Task tool is being used for implementation work."""
        # Only match Task tool
        if hook_input.get(HookInputField.TOOL_NAME) != ToolName.TASK:
            return False

        # Get the prompt from tool_input
        tool_input = hook_input.get(HookInputField.TOOL_INPUT, {})
        prompt = tool_input.get("prompt")

        if not prompt or not isinstance(prompt, str):
            return False

        # Check if prompt contains implementation keywords
        return bool(self._implementation_pattern.search(prompt))

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Provide TDD guidance for implementation tasks."""
        tool_input = hook_input.get(HookInputField.TOOL_INPUT, {})
        prompt = tool_input.get("prompt", "")
        subagent_type = tool_input.get("subagent_type", "unknown")

        return HookResult(
            decision=Decision.ALLOW,
            reason=(
                f"💡 TDD REMINDER: Implementation Task Detected\n\n"
                f"Agent Type: {subagent_type}\n"
                f"Task: {prompt[:100]}{'...' if len(prompt) > 100 else ''}\n\n"
                f"📋 RECOMMENDED WORKFLOW (Test-Driven Development):\n\n"
                f"1️⃣  RED PHASE - Write Failing Tests:\n"
                f"   • Create test file FIRST (tests/...)\n"
                f"   • Write comprehensive test cases\n"
                f"   • Run tests - they MUST FAIL\n"
                f"   • Verify tests fail for the right reason\n\n"
                f"2️⃣  GREEN PHASE - Implement Code:\n"
                f"   • Write minimum code to pass tests\n"
                f"   • Run tests - they MUST PASS\n"
                f"   • Verify all tests pass\n\n"
                f"3️⃣  REFACTOR PHASE - Clean Up:\n"
                f"   • Improve code clarity\n"
                f"   • Remove duplication\n"
                f"   • Keep tests passing\n\n"
                f"4️⃣  VERIFY:\n"
                f"   • Run full QA suite: ./scripts/qa/run_all.sh\n"
                f"   • Restart daemon: $PYTHON -m claude_code_hooks_daemon.daemon.cli restart\n"
                f"   • Verify daemon status: RUNNING\n\n"
                f"✅ BENEFITS OF TDD:\n"
                f"   • Clear requirements before coding\n"
                f"   • 95%+ test coverage guaranteed\n"
                f"   • Design-focused implementation\n"
                f"   • No untested code in production\n"
                f"   • Catches import errors early\n\n"
                f"📖 REFERENCE:\n"
                f"   • @CLAUDE/CodeLifecycle/Features.md\n"
                f"   • @CLAUDE/PlanWorkflow.md (TDD mandatory)\n\n"
                f"This is advisory only - proceeding with task..."
            ),
            context=[
                "TDD_WORKFLOW: Reminder to follow RED-GREEN-REFACTOR cycle",
                "TEST_FIRST: Write failing tests before implementation",
                "QA_VERIFICATION: Run full QA suite after implementation",
                "DAEMON_RESTART: Verify daemon loads successfully",
            ],
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for Task TDD advisor."""
        from claude_code_hooks_daemon.core import AcceptanceTest, TestType

        return [
            AcceptanceTest(
                title="Task tool with implementation keyword",
                command="Use the Task tool with prompt 'implement a new validation handler for email addresses'",
                description="Advises on TDD workflow when spawning agent for implementation",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[
                    r"TDD",
                    r"Test-Driven",
                ],
                safety_notes="Advisory only - does not block. Task tool may not be available to subagent.",
                test_type=TestType.ADVISORY,
                requires_event="PreToolUse with Task tool",
            ),
        ]
