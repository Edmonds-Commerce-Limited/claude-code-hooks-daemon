"""DisclosureResetSessionStartHandler - resets per-agent rule disclosure state.

Plan 00116, Phase 4 (Task 4.2), Decision E. A clear/new session has no memory
of any verbose block already shown to the agent, so the disclosure ladder
must start over. The hook input does not reliably distinguish "clear" from an
ordinary SessionStart (see Decision E), so this handler resets on EVERY
SessionStart -- worst case is one extra verbose block on a resume, the same
acceptable cost as a daemon restart re-disclosing (Decision G).
"""

from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, HookInputField, Priority
from claude_code_hooks_daemon.core import AdvisoryResult, Decision, get_data_layer
from claude_code_hooks_daemon.core.handler_bases import SessionStartHandlerBase


class DisclosureResetSessionStartHandler(SessionStartHandlerBase):
    """Reset DisclosureTracker state for the firing agent on SessionStart."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.DISCLOSURE_RESET_SESSION_START,
            priority=Priority.DISCLOSURE_RESET_SESSION_START,
            terminal=False,
            tags=[HandlerTag.SAFETY, HandlerTag.WORKFLOW, HandlerTag.NON_TERMINAL],
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Reset on every SessionStart, including resumes (Decision E)."""
        return True

    def handle(self, hook_input: dict[str, Any]) -> AdvisoryResult:
        """Clear this agent's disclosure state; silent, non-blocking.

        A missing ``transcript_path`` is a safe no-op: there is no per-agent
        key to reset, and the blocking handlers already fail toward verbose
        whenever ``transcript_path`` is absent.
        """
        transcript_path = hook_input.get(HookInputField.TRANSCRIPT_PATH)
        if transcript_path:
            get_data_layer().disclosure.reset(str(transcript_path))
        return AdvisoryResult(decision=Decision.ALLOW)

    def get_claude_md(self) -> str | None:
        # Observe-only state reset; nothing for the agent to fight or learn.
        return None

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for this handler."""
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="disclosure reset on SessionStart",
                command='echo "test"',
                description=(
                    "Tests that SessionStart clears this agent's rule-disclosure "
                    "state, so the first rule fire in a fresh/resumed session is "
                    "verbose rather than a stale terse reminder."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r".*"],
                safety_notes="Observe-only SessionStart writer - blocks nothing",
                test_type=TestType.CONTEXT,
                requires_event="SessionStart event",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
