"""RemindPromptLibraryHandler - reminds to capture successful prompts to the library."""

from typing import Any

from claude_code_hooks_daemon.core import Decision, Handler, HookResult


class RemindPromptLibraryHandler(Handler):
    """Remind to capture successful prompts to the library."""

    def __init__(self) -> None:
        super().__init__(name="remind-capture-prompt", priority=100)

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
