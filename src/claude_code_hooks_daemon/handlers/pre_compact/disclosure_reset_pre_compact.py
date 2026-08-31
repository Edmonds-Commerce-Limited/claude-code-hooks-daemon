"""DisclosureResetPreCompactHandler - resets per-agent rule disclosure state.

Plan 00116, Phase 4 (Task 4.1), Decision E. The verbose block for a rule the
agent already saw this session is about to be compacted out of context, so
the disclosure ladder must start over: the next fire of any rule for this
agent should be verbose again, not the terse reminder it would otherwise get.
"""

from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, HookInputField, Priority
from claude_code_hooks_daemon.core import BlockingResult, Decision, get_data_layer
from claude_code_hooks_daemon.core.handler_bases import PreCompactHandlerBase


class DisclosureResetPreCompactHandler(PreCompactHandlerBase):
    """Reset DisclosureTracker state for the firing agent on PreCompact."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.DISCLOSURE_RESET_PRE_COMPACT,
            priority=Priority.DISCLOSURE_RESET_PRE_COMPACT,
            terminal=False,
            tags=[HandlerTag.SAFETY, HandlerTag.WORKFLOW, HandlerTag.NON_TERMINAL],
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Reset on every compaction."""
        return True

    def handle(self, hook_input: dict[str, Any]) -> BlockingResult:
        """Clear this agent's disclosure state; never block compaction.

        A missing ``transcript_path`` is a safe no-op: there is no per-agent
        key to reset, and ``handle()`` in the blocking handlers already fails
        toward verbose whenever ``transcript_path`` is absent.
        """
        transcript_path = hook_input.get(HookInputField.TRANSCRIPT_PATH)
        if transcript_path:
            get_data_layer().disclosure.reset(str(transcript_path))
        return BlockingResult(decision=Decision.ALLOW)

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
                title="disclosure reset on PreCompact",
                command='echo "test"',
                description=(
                    "Tests that PreCompact clears this agent's rule-disclosure "
                    "state, so the next rule fire after a compaction is verbose "
                    "again rather than a stale terse reminder."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r".*"],
                safety_notes="Observe-only PreCompact writer - blocks nothing",
                test_type=TestType.CONTEXT,
                requires_event="PreCompact event",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
