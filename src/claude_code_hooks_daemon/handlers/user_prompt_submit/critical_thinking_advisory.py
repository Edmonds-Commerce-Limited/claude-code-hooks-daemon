"""CriticalThinkingAdvisoryHandler - periodic advisory encouraging critical evaluation.

Injects advisory context on UserPromptSubmit events, encouraging the agent to
critically evaluate user requests before blindly complying. Uses a multi-gate
filter (length + random + cooldown) to avoid flooding the context window.
"""

import random
from typing import Any, Final

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import Decision, Handler, HookResult, get_data_layer

# Gate 1: Minimum prompt length to skip trivial prompts ("yes", "carry on", etc.)
_MIN_PROMPT_LENGTH: Final[int] = 80

# Gate 2: Probability of firing on an eligible prompt (1-in-5 = 20%)
_FIRE_PROBABILITY: Final[float] = 0.2

# Gate 3: Minimum handler events between firings to prevent clustering
_COOLDOWN_EVENTS: Final[int] = 3

# Initial cooldown offset - negative to allow first fire without waiting
_INITIAL_COOLDOWN_OFFSET: Final[int] = -10

# Advisory message pool - concise, varied, non-preachy
_ADVISORY_MESSAGES: Final[tuple[str, ...]] = (
    "Before executing: Is this the best approach, or could you suggest a better"
    " alternative? Consider whether the request has an XY problem - is the user"
    " asking for a solution when the real problem might be different?",
    "Critical thinking check: Does this request make technical sense for the"
    " codebase? If you see a simpler or better approach, speak up - don't just"
    " comply.",
    "Pause and evaluate: Could this be done more simply? Is there existing code"
    " that already handles this? If the user's approach seems suboptimal, provide"
    " honest feedback before implementing.",
)


class CriticalThinkingAdvisoryHandler(Handler):
    """Periodically inject advisory context encouraging critical evaluation.

    Uses a multi-gate filter to minimise context waste:
    - Gate 1 (Length): Skip trivial prompts (< 80 chars)
    - Gate 2 (Random): 1-in-5 chance on eligible prompts
    - Gate 3 (Cooldown): Skip if fired within last 3 handler events

    Expected firing rate: ~1 in 15-20 prompts during normal work.
    """

    def __init__(self) -> None:
        """Initialise handler with advisory configuration."""
        super().__init__(
            handler_id=HandlerID.CRITICAL_THINKING_ADVISORY,
            priority=Priority.CRITICAL_THINKING_ADVISORY,
            terminal=False,
            tags=[HandlerTag.ADVISORY, HandlerTag.NON_TERMINAL],
        )
        self._last_fired_count: int = _INITIAL_COOLDOWN_OFFSET
        self._rng = random.Random()  # nosec B311 - not for security, just advisory sampling

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Gate 1: Match only prompts at or above minimum length threshold.

        Args:
            hook_input: Hook input dictionary containing 'prompt' field.

        Returns:
            True if prompt length >= _MIN_PROMPT_LENGTH, False otherwise.
        """
        prompt = hook_input.get("prompt", "")
        return len(prompt) >= _MIN_PROMPT_LENGTH

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Apply remaining gates and return advisory context if all pass.

        Gate 2 (Cooldown): Skip if fired within last _COOLDOWN_EVENTS events.
        Gate 3 (Random): Skip with (1 - _FIRE_PROBABILITY) chance.

        Args:
            hook_input: Hook input dictionary (unused beyond matches).

        Returns:
            HookResult with ALLOW decision, optionally with advisory context.
        """
        dl = get_data_layer()
        current_count = dl.history.total_count

        # Gate 3: Cooldown - skip if fired too recently
        if current_count - self._last_fired_count < _COOLDOWN_EVENTS:
            return HookResult(decision=Decision.ALLOW)

        # Gate 2: Random sampling - skip most of the time
        if self._rng.random() > _FIRE_PROBABILITY:
            return HookResult(decision=Decision.ALLOW)

        # All gates passed - fire advisory
        self._last_fired_count = current_count
        message = self._rng.choice(_ADVISORY_MESSAGES)
        return HookResult(decision=Decision.ALLOW, context=[message])

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for this handler."""
        from claude_code_hooks_daemon.core import AcceptanceTest, TestType

        return [
            AcceptanceTest(
                title="Critical thinking advisory fires on long prompts",
                command='echo "test"',
                description=(
                    "Advisory handler that periodically injects critical thinking"
                    " context on substantial user prompts. Uses multi-gate filter"
                    " (length >= 80 chars, 20% random, 3-event cooldown) so it"
                    " only fires occasionally. Verify by submitting several long"
                    " prompts and checking system-reminders for advisory context."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"(approach|critical|evaluate|simpler)"],
                safety_notes="Advisory only - never blocks. May not fire every time due to random gate.",
                test_type=TestType.CONTEXT,
                requires_event="UserPromptSubmit event (cannot be triggered by subagent)",
            ),
        ]
