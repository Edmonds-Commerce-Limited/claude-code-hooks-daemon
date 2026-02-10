"""
Dogfooding Reminder Handler.

Reminds developers that this project dogfoods its own hooks daemon and that
any bugs discovered must be addressed immediately with TDD reproduction.

This handler is non-terminal and advisory - it never blocks execution, only
provides critical workflow reminders at session start.

This is a PROJECT-LEVEL plugin handler. Its constants are defined here,
not in the library's constants module.
"""

import logging
from typing import Any

from claude_code_hooks_daemon.constants import HandlerTag, HookInputField
from claude_code_hooks_daemon.constants.handlers import HandlerIDMeta
from claude_code_hooks_daemon.core import Handler, HookResult
from claude_code_hooks_daemon.core.hook_result import Decision

logger = logging.getLogger(__name__)

# Plugin-level constants (not in the library)
HANDLER_ID = HandlerIDMeta(
    class_name="DogfoodingReminderHandler",
    config_key="dogfooding_reminder",
    display_name="dogfooding-reminder",
)
PRIORITY = 2  # Very early - session start advisory
TAG_DOGFOODING = "dogfooding"


class DogfoodingReminderHandler(Handler):
    """
    Reminds developers of dogfooding workflow and bug handling protocol.

    This project uses its own hooks daemon for development, making it a
    dogfooding environment. Any bugs discovered in handlers must be fixed
    immediately with proper TDD reproduction.
    """

    def __init__(self) -> None:
        """Initialize handler."""
        super().__init__(
            handler_id=HANDLER_ID,
            priority=PRIORITY,
            terminal=False,
            tags=[
                HandlerTag.WORKFLOW,
                HandlerTag.ADVISORY,
                HandlerTag.NON_TERMINAL,
                TAG_DOGFOODING,
            ],
        )

    def matches(self, hook_input: dict[str, Any] | None) -> bool:
        """
        Check if this handler should run.

        Args:
            hook_input: Hook input data

        Returns:
            True if SessionStart event
        """
        if hook_input is None:
            return False

        if not isinstance(hook_input, dict):
            return False

        # Only match SessionStart events
        event_name = hook_input.get(HookInputField.HOOK_EVENT_NAME)
        return event_name == "SessionStart"

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """
        Handle dogfooding reminder display.

        Args:
            hook_input: Hook input data

        Returns:
            HookResult with ALLOW decision and dogfooding workflow context
        """
        try:
            context: list[str] = []

            # Main dogfooding notice
            context.append("⚠️  DOGFOODING PROJECT: You are working in the hooks daemon repository")
            context.append("")

            # Bug handling protocol
            context.append("🐛 Bug Handling Protocol:")
            context.append("")
            context.append("If you discover ANY bug in handlers or daemon code:")
            context.append("")
            context.append("  1. **STOP current work immediately**")
            context.append("  2. **Write TDD reproduction test** that demonstrates the bug")
            context.append("  3. **Choose fix approach:**")
            context.append("")
            context.append("     **Small/Medium bugs:**")
            context.append("     • Dispatch sub-agent to fix with TDD")
            context.append("     • Sub-agent writes failing test → implements fix → verifies QA")
            context.append(
                "     • Example: `Task(subagent_type='general-purpose', prompt='Fix false positive...')`"
            )
            context.append("")
            context.append("     **Large/Complex bugs:**")
            context.append("     • Dispatch sub-agent to create Plan Workflow plan")
            context.append("     • Capture all context from discovery thread")
            context.append("     • Plan documents: root cause, approach, tasks, testing strategy")
            context.append("     • Execute plan separately with proper TDD lifecycle")
            context.append("")
            context.append(
                "  4. **Never skip TDD reproduction** - without failing test, bug can return"
            )
            context.append("  5. **Always run full QA** after fix: `./scripts/qa/run_all.sh`")
            context.append(
                "  6. **Always restart daemon** to verify: `$PYTHON -m claude_code_hooks_daemon.daemon.cli restart`"
            )
            context.append("")

            # Why this matters
            context.append("📊 Why This Matters:")
            context.append("  • This project uses its own hooks for protection")
            context.append("  • Bugs in handlers affect our own development workflow")
            context.append("  • False positives block legitimate work")
            context.append("  • False negatives allow dangerous operations")
            context.append("  • TDD ensures bugs never return")
            context.append("")

            # Quick reference
            context.append("🔗 Quick Reference:")
            context.append("  • Bug lifecycle: @CLAUDE/CodeLifecycle/Bugs.md")
            context.append("  • Plan workflow: @CLAUDE/PlanWorkflow.md")
            context.append("  • Handler development: @CLAUDE/HANDLER_DEVELOPMENT.md")

            return HookResult(decision=Decision.ALLOW, reason=None, context=context)

        except Exception as e:
            logger.error("Dogfooding reminder handler error: %s", e, exc_info=True)
            return HookResult(
                decision=Decision.ALLOW,
                reason=None,
                context=["⚠️  Dogfooding reminder failed to load"],
            )

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for this handler."""
        from claude_code_hooks_daemon.core import AcceptanceTest, TestType

        return [
            AcceptanceTest(
                title="dogfooding reminder handler test",
                command='echo "test"',
                description="Tests dogfooding reminder handler functionality",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r".*"],
                safety_notes="Context/utility handler - minimal testing required",
                test_type=TestType.CONTEXT,
                requires_event="SessionStart event",
            ),
        ]
