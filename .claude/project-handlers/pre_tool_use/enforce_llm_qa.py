"""EnforceLlmQaHandler - blocks run_all.sh, requires llm_qa.py.

This project uses LLM-optimised QA output (scripts/qa/llm_qa.py) which
produces ~16 lines instead of 200+. LLM agents should never run the
verbose run_all.sh directly.
"""

from typing import Any

from claude_code_hooks_daemon.core import AcceptanceTest, Handler, HookResult, TestType
from claude_code_hooks_daemon.core.hook_result import Decision

_BLOCKED_SCRIPT = "run_all.sh"
_LLM_SCRIPT = "./scripts/qa/llm_qa.py all"


class EnforceLlmQaHandler(Handler):
    """Block run_all.sh and direct LLM agents to llm_qa.py."""

    def __init__(self) -> None:
        super().__init__(
            handler_id="enforce-llm-qa",
            priority=41,
            terminal=True,
            tags=["project", "blocking", "qa"],
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Match Bash commands that invoke run_all.sh."""
        if hook_input.get("tool_name") != "Bash":
            return False
        tool_input = hook_input.get("tool_input", {})
        command = tool_input.get("command", "") if isinstance(tool_input, dict) else ""
        return _BLOCKED_SCRIPT in command

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Block with guidance to use llm_qa.py instead."""
        return HookResult(
            decision=Decision.DENY,
            reason=(
                "USE LLM-OPTIMISED QA SCRIPT\n\n"
                "run_all.sh produces 200+ lines of verbose output.\n"
                "Use the LLM-optimised wrapper instead:\n\n"
                f"  {_LLM_SCRIPT}\n\n"
                "This produces ~16 lines with structured JSON output.\n"
                "Individual scripts (run_tests.sh, run_lint.sh, etc.) are still allowed."
            ),
        )

    def get_acceptance_tests(self) -> list[AcceptanceTest]:
        """Define acceptance tests."""
        return [
            AcceptanceTest(
                title="Block run_all.sh",
                command='echo "./scripts/qa/run_all.sh"',
                description="Blocks verbose QA script, directs to llm_qa.py",
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"llm_qa\.py", r"run_all\.sh"],
                safety_notes="Uses echo - safe to execute",
                test_type=TestType.BLOCKING,
            ),
        ]
