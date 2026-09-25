"""AgentTerminatedEarlyFailureDetectorHandler - surfaces a foreground sub-agent
killed by a usage limit, on PostToolUseFailure.

Plan 00466 N46 review 2's follow-up. ``budget_exhaustion_detector`` (the
PostToolUse sibling in ``handlers.post_tool_use``) matches the harness's
usage-limit-termination text on a COMPLETED sub-agent dispatch's
``tool_response``. But the real ``is_error: true`` occurrence this session
hit is delivered differently: Claude Code fires ``PostToolUseFailure``, not
``PostToolUse``, for a failed tool call (vendored ``hooks.md:2108-2151``,
``contracts/claude-code-hooks/PostToolUseFailure.json``), carrying the
failure as a top-level ``error`` STRING rather than inside
``tool_response``. ``budget_exhaustion_detector`` is a ``PostToolUse``
handler and structurally never receives this event, so this real weekly-
limit death went unsurfaced until this handler existed.

Matches ONLY the harness's own text for a dispatched sub-agent cut off
mid-task by a usage-limit rejection -- ``Error: Agent terminated early due
to an API error: You've hit your (session|weekly) limit...`` (observed live
in this project's own transcripts: the real is_error occurrence's
``toolUseResult`` is a bare string beginning with exactly this text) --
anchored at the response's START (the harness's own text opens with the
fixed ``"Error: "`` prefix followed immediately by the sentence) and
requiring the same stable ``(error type rate_limit, HTTP 429`` tail nearby
that the PostToolUse sibling requires (N46 review 2, NIT-6 parity), so a
report that merely opens with the bare sentence and nothing else does not
match. Channel-scoped to ``SUBAGENT_DISPATCH_TOOL_NAMES`` (Task/Agent) only
-- the same error text through, say, a failed Bash command's own stderr
must never fire.

On a match: ALLOW with an advisory naming which dispatch died (preferring
``tool_input.name``, via the shared ``dispatch_identity`` helper imported
from ``budget_exhaustion_detector`` -- the same cross-event-package reuse
shape ``recovery_cron_advisor``'s ``declares_failsafe_cron`` already has)
and demanding a re-brief once the limit resets, mirroring the PostToolUse
sibling's advisory shape exactly.

This handler does NOT cover a background/teammate dispatch killed after it
has already moved to the background: that death never reaches PostToolUse
or PostToolUseFailure at all (no further tool-call event exists for it),
and is a different channel entirely -- Plan 00470 Tasks 3.1/3.2
(StopFailure/Notification) own that separately.
"""

from __future__ import annotations

import re
from typing import Any, Final

from claude_code_hooks_daemon.constants import (
    SUBAGENT_DISPATCH_TOOL_NAMES,
    HandlerID,
    HandlerTag,
    HookInputField,
    Priority,
)
from claude_code_hooks_daemon.core import BlockingResult, Decision
from claude_code_hooks_daemon.core.handler_bases import PostToolUseFailureHandlerBase
from claude_code_hooks_daemon.handlers.post_tool_use.budget_exhaustion_detector import (
    dispatch_identity,
)

# The harness's own text for a dispatched sub-agent cut off mid-task by a
# usage-limit rejection, as delivered via PostToolUseFailure's `error` field:
# a bare string prefixed "Error: " (unlike PostToolUse's own list-of-text-
# blocks `tool_response.content` -- see budget_exhaustion_detector for that
# sibling signal's shape). Anchored at the response's true start and
# requiring the harness's stable "(error type rate_limit, HTTP 429" tail
# nearby, mirroring budget_exhaustion_detector's own anchor (N46 review 2,
# NIT-6).
_AGENT_TERMINATED_EARLY_FAILURE_RE: Final[re.Pattern[str]] = re.compile(
    r"\A\s*Error:\s*Agent terminated early due to an API error: You've hit your "
    r"(?:session|weekly) limit(?=.{0,300}?\(error type rate_limit, HTTP 429)",
    re.DOTALL,
)


def _advisory(tool_name: str, tool_input: Any, matched_fragment: str) -> str:
    """Build the advisory -- same shape as budget_exhaustion_detector's own
    agent-terminated-early advisory. ``tool_response`` is not a meaningful
    concept on PostToolUseFailure (it carries ``error``, not
    ``tool_response``), so ``dispatch_identity`` is called with ``None``
    for it -- its ``agentId`` fallback simply never applies here."""
    identity = dispatch_identity(tool_input, None)
    return (
        f"🚨 SUB-AGENT DIED ON A USAGE LIMIT ({tool_name}: {identity!r}) 🚨\n\n"
        f"The harness terminated this dispatch early. Matched text: "
        f"{matched_fragment!r}\n\n"
        "You MUST tell the user this agent died mid-task on a usage limit, "
        "not that it finished. Its output (if any) is PARTIAL, not a "
        "completed result -- do NOT treat the dispatch as done, and do NOT "
        "silently retry it immediately. Once the limit resets, RE-BRIEF the "
        "same assignment to a fresh dispatch so the work is not silently "
        "dropped."
    )


class AgentTerminatedEarlyFailureDetectorHandler(PostToolUseFailureHandlerBase):
    """PostToolUseFailure advisory: a foreground Agent/Task dispatch killed
    by a harness usage limit surfaces here, through its ``error`` field --
    the event ``budget_exhaustion_detector`` (its PostToolUse sibling) never
    receives, since a failed tool call fires PostToolUseFailure instead.
    Channel-scoped to Task/Agent; anchored at the response's start with the
    same stable-tail requirement as the PostToolUse sibling. Never blocks:
    on a match it ALLOWs with an advisory naming which dispatch died and
    demanding a re-brief once the limit resets.
    """

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.AGENT_TERMINATED_EARLY_FAILURE_DETECTOR,
            priority=Priority.AGENT_TERMINATED_EARLY_FAILURE_DETECTOR,
            terminal=False,
            tags=[HandlerTag.WORKFLOW, HandlerTag.ADVISORY, HandlerTag.NON_TERMINAL],
        )

    def get_default_enabled(self) -> bool:
        """Opt-OUT handler -- ON by default, mirrors budget_exhaustion_detector."""
        return True

    def _matched_fragment(self, hook_input: dict[str, Any]) -> str | None:
        """Return the matched fragment for this event, or None."""
        tool_name = hook_input.get(HookInputField.TOOL_NAME)
        if tool_name not in SUBAGENT_DISPATCH_TOOL_NAMES:
            return None
        error_text = hook_input.get(HookInputField.ERROR)
        if not isinstance(error_text, str):
            return None
        match = _AGENT_TERMINATED_EARLY_FAILURE_RE.search(error_text)
        return None if match is None else match.group(0)

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Return True if this is a real agent-terminated-early failure."""
        return self._matched_fragment(hook_input) is not None

    def handle(self, hook_input: dict[str, Any]) -> BlockingResult:
        """Inject a prominent re-brief advisory naming the dead dispatch.

        Always returns Decision.ALLOW -- the tool call already failed, and
        this handler's entire role is to make an already-happened
        usage-limit death legible, never to gate anything.
        """
        fragment = self._matched_fragment(hook_input)
        if fragment is None:
            return BlockingResult(decision=Decision.ALLOW)

        tool_name = str(hook_input.get(HookInputField.TOOL_NAME, "") or "unknown")
        advisory_text = _advisory(tool_name, hook_input.get(HookInputField.TOOL_INPUT), fragment)
        return BlockingResult(decision=Decision.ALLOW, context=[advisory_text])

    def get_claude_md(self) -> str | None:
        """Return CLAUDE.md guidance about this handler."""
        return (
            "## agent_terminated_early_failure_detector — a dead foreground "
            "sub-agent is surfaced on PostToolUseFailure\n\n"
            "A foreground Agent/Task dispatch that dies with `is_error: true` "
            "delivers its death through PostToolUseFailure's `error` field, "
            "NOT through PostToolUse — `budget_exhaustion_detector` (its "
            "PostToolUse sibling) never receives this event. This handler "
            "matches the harness's own `Error: Agent terminated early due to "
            "an API error: You've hit your session/weekly limit...` text, "
            "anchored at the response's start with the same stable-tail "
            "requirement as its sibling, scoped to Task/Agent only.\n\n"
            "**When this fires: tell the user this agent died mid-task on a "
            "usage limit, name WHICH dispatch died (preferring its `name`), "
            "and re-brief the same assignment to a fresh dispatch once the "
            "limit resets** — its output (if any) is PARTIAL, not a "
            "completed result.\n\n"
            "**Foreground dispatches only.** A background/teammate dispatch "
            "killed after it has already moved to the background never "
            "reaches PostToolUse or PostToolUseFailure at all — see Plan "
            "00470 Tasks 3.1/3.2 (StopFailure/Notification) for that "
            "separate channel.\n\n"
            "### Configuration\n\n"
            "On by default (opt-out). Configure via "
            "`handlers.post_tool_use_failure.agent_terminated_early_failure_detector`."
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests: a re-brief advisory probe and a scoping allow."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="A foreground sub-agent killed by a usage limit triggers a re-brief advisory",
                command=(
                    "Simulate a PostToolUseFailure event for tool 'Agent' whose "
                    'error field is "Error: Agent terminated early due to an '
                    "API error: You've hit your weekly limit · resets Sep "
                    "27, 8am (UTC) (error type rate_limit, HTTP 429, request id "
                    'req_example, model claude-sonnet-5)."'
                ),
                harness_cannot_produce=(
                    "This handler reads the top-level `error` field of a "
                    "PostToolUseFailure event, which the harness populates "
                    "only for a genuinely failed tool call; a declared "
                    "payload cannot fabricate that failure without one. "
                    "Covered by "
                    "tests/unit/handlers/post_tool_use_failure/"
                    "test_agent_terminated_early_failure_detector.py."
                ),
                description=(
                    "N46 review 2's follow-up: the harness's own usage-limit "
                    "termination text, delivered through PostToolUseFailure's "
                    "error field for a foreground Agent/Task dispatch, "
                    "triggers an advisory naming the dispatch and demanding a "
                    "re-brief once the limit resets."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[
                    r"SUB-AGENT DIED",
                    r"🚨",
                    r"re-brief",
                ],
                safety_notes="Synthetic PostToolUseFailure payload only; no live tool call is made.",
                test_type=TestType.ADVISORY,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="The same error text through a non-dispatch tool never fires",
                command=(
                    "Simulate a PostToolUseFailure event for tool 'Bash' whose "
                    'error field is "Error: Agent terminated early due to an '
                    "API error: You've hit your weekly limit (error type "
                    'rate_limit, HTTP 429)."'
                ),
                harness_cannot_produce=(
                    "Same PostToolUseFailure gap as its sibling above, and "
                    "convertible with the same harness capability."
                ),
                description=(
                    "Channel-scoped to Task/Agent only: the exact same error "
                    "text through a different tool's own failure must never "
                    "fire, since this signal only arrives from a sub-agent "
                    "dispatch's own termination."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Synthetic PostToolUseFailure payload only; no live tool call is made.",
                test_type=TestType.ADVISORY,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=False,
            ),
        ]
