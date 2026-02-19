"""RemindPromptLibraryHandler - reminds to capture successful prompts to the library."""

from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import Decision, Handler, HookResult


class RemindPromptLibraryHandler(Handler):
    """Remind to capture successful prompts to the library."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.REMIND_PROMPT_LIBRARY,
            priority=Priority.REMIND_PROMPT_LIBRARY,
            tags=[HandlerTag.WORKFLOW, HandlerTag.ADVISORY, HandlerTag.NON_TERMINAL],
        )

    def matches(self, _hook_input: dict[str, Any]) -> bool:
        """Always match - remind after every sub-agent completion."""
        return True

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Remind user to capture prompt if successful."""
        agent_type = hook_input.get("subagent_type", "unknown")

        return HookResult(
            decision=Decision.ALLOW,
            reason=(
                f"\n💡 Sub-agent '{agent_type}' completed.\n\n"
                "If this prompt worked well, consider capturing it:\n"
                "  npm run llm:prompts -- add --from-json <prompt-file>\n\n"
                "Benefits:\n"
                "  • Reuse successful prompts later\n"
                "  • Track what works (metrics)\n"
                "  • Build institutional knowledge\n\n"
                "📖 See: CLAUDE/PromptLibrary/README.md"
            ),
        )

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
                title="remind prompt library handler test",
                command='echo "test"',
                description="Tests remind prompt library handler functionality",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r".*"],
                safety_notes="Context/utility handler - minimal testing required",
                test_type=TestType.CONTEXT,
                requires_event="Stop event",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
