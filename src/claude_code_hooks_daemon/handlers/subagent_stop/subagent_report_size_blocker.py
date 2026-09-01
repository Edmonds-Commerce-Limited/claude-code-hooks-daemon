"""SubagentReportSizeBlockerHandler - block an oversized subagent final message.

Plan 00307 Task 3.1. Task 1.1's live reproduction dispatched a subagent
instructed to return a deliberately huge (~24k-token) final message inline:
the coordinator received a report with the requested start/end sentinels
intact, but an explicit truncation marker had been spliced into the MIDDLE by
the harness — roughly seven sections silently lost. A coordinator cannot
detect that failure by inspecting what it received (it looks complete), so
enforcement must live on the SUBAGENT side, at the moment it tries to stop.

The vendored SubagentStop contract (v2.1.252) delivers
``last_assistant_message`` directly on ``hook_input`` — no transcript parse
needed. This handler compares its length against a configured character
threshold and blocks the stop, instructing the agent to write the full report
to a file and reply with a short summary + path instead.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import BlockingResult, Decision
from claude_code_hooks_daemon.core.handler_bases import SubagentStopHandlerBase

# Task 1.1's reproduction measured harmful truncation at a ~24k-token
# (roughly 96k-character) final message. A subagent's final message should be
# a short completion summary, not the report itself — a few hundred to low
# thousands of characters covers that comfortably, so the default threshold
# sits an order of magnitude below the observed harmful shape.
_DEFAULT_THRESHOLD_CHARS = 4000

# Fallback directory for a report with no declared plan folder. MUST match
# dispatch_declaration's default (Plan 00307 Task 2.2/4.2) so the two
# handlers tell one consistent story, and MUST resolve under
# markdown_organization's built-in `untracked/` allow-rule so this handler's
# own prescription is never itself rejected by that handler (Task 4.2 tuning
# finding 2: the GREEN re-run's probe hit exactly that clash on its first,
# self-chosen write location). Configurable via
# subagent_report_size_blocker.options.fallback_report_dir.
_DEFAULT_FALLBACK_REPORT_DIR = "untracked/agent-reports/"

# Placeholder tokens used when the render inputs are unavailable at this
# surface — documented inline in the deny message so an agent copying the
# path literally sees they are placeholders, not real values.
_AGENT_NAME_PLACEHOLDER = "{agent-name}"
_MODEL_PLACEHOLDER = "{model}"


class SubagentReportSizeBlockerHandler(SubagentStopHandlerBase):
    """Block a SubagentStop whose ``last_assistant_message`` is oversized.

    Fails open on any missing/malformed input (no report, no verdict) and
    never re-fires on re-entry (``stop_hook_active``), so a subagent that
    complies after one block cannot be looped.
    """

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.SUBAGENT_REPORT_SIZE_BLOCKER,
            priority=Priority.SUBAGENT_REPORT_SIZE_BLOCKER,
            terminal=True,
            tags=[
                HandlerTag.WORKFLOW,
                HandlerTag.TERMINAL,
            ],
        )
        # Config flags, declared here so mypy can verify them and a typo in a
        # config setter surfaces as a normal attribute (fail-fast).
        self._threshold_chars: int = _DEFAULT_THRESHOLD_CHARS
        self._fallback_report_dir: str = _DEFAULT_FALLBACK_REPORT_DIR

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """True for every SubagentStop except a re-entry (loop guard)."""
        return not bool(hook_input.get("stop_hook_active", False))

    def _prescribed_fallback_path(self, hook_input: dict[str, Any]) -> str:
        """Render a concrete, always-writable target path for the deny reason.

        The dispatch's plan folder (if any) is not visible at this SubagentStop
        surface, so this always renders the FALLBACK directory (not a plan
        folder's ``subagent-reports/``) — a real path an agent can write to
        immediately, not vague "write to a file" guidance. ``{yymmdd}`` is
        rendered from today's date (always known); the agent name comes from
        ``agent_type`` when the hook input carries it, else the literal
        placeholder token (documented in the deny message); the model is
        always the placeholder token — it is not part of the SubagentStop
        contract at all.
        """
        yymmdd = datetime.now(tz=UTC).strftime("%y%m%d")
        agent_type = hook_input.get("agent_type")
        agent_name = (
            agent_type if isinstance(agent_type, str) and agent_type else (_AGENT_NAME_PLACEHOLDER)
        )
        return f"{self._fallback_report_dir}{yymmdd}-{agent_name}-{_MODEL_PLACEHOLDER}.md"

    def handle(self, hook_input: dict[str, Any]) -> BlockingResult:
        """DENY when ``last_assistant_message`` exceeds the threshold, else ALLOW."""
        message = hook_input.get("last_assistant_message")
        if not isinstance(message, str):
            # Fail open: no verdict without a readable report string.
            return BlockingResult(decision=Decision.ALLOW)

        if len(message) <= self._threshold_chars:
            return BlockingResult(decision=Decision.ALLOW)

        fallback_path = self._prescribed_fallback_path(hook_input)

        return BlockingResult(
            decision=Decision.DENY,
            reason=(
                "📦 REPORT TOO LARGE (Plan 00307): your final message is "
                f"{len(message)} characters, over the {self._threshold_chars}-"
                "character threshold. A subagent's final message travels over "
                "a bounded-size wire channel that silently elides an oversized "
                "inline report in the MIDDLE — the coordinator can receive "
                "something that LOOKS complete while content is missing.\n\n"
                "Write the full report to a file now, at this exact path:\n\n"
                f"  {fallback_path}\n\n"
                f"(`{_MODEL_PLACEHOLDER}` is a literal placeholder — this "
                "handler has no model field to render; replace it and "
                f"`{_AGENT_NAME_PLACEHOLDER}` if shown above with real values. "
                "This fallback directory is always writable under this "
                "project's markdown-location rules.)\n\n"
                "If this dispatch declared a plan folder, prefer that folder's "
                "`subagent-reports/{yymmdd}-{agent-name}-{model}.md` instead "
                "of the fallback above.\n\n"
                "Then reply with a short completion summary plus the file "
                "path — not the report content itself."
            ),
        )

    def get_claude_md(self) -> str | None:
        return (
            "## subagent_report_size_blocker — write large reports to a file\n\n"
            "A subagent whose final message exceeds a configured character "
            "threshold is blocked from stopping. A subagent's return travels "
            "over a bounded-size wire channel that silently elides an "
            "oversized inline report in the MIDDLE — the coordinator can "
            "receive what looks like a complete report while content is "
            "missing.\n\n"
            "**Fix**: write the full report to a file under the declared plan "
            "folder's `subagent-reports/{yymmdd}-{agent-name}-{model}.md` — "
            "or, for non-plan work, the configured fallback directory (default "
            f"`{_DEFAULT_FALLBACK_REPORT_DIR}`) using the same filename "
            "convention. The deny message renders this fallback path "
            "concretely (today's date, `agent_type` when the hook input "
            "carries it, `{model}` as a literal placeholder — no model field "
            "exists at this surface), then reply with a short completion "
            "summary plus the file path."
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for the subagent report size blocker."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="Subagent attempts to stop with an oversized final message",
                command=(
                    "Dispatch a subagent instructed to return a final message "
                    "well over the configured threshold, writing nothing to disk"
                ),
                description=(
                    "Blocks the SubagentStop and instructs the agent to write "
                    "the report to a file and reply with a summary + path"
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"REPORT TOO LARGE", r"subagent-reports"],
                safety_notes=(
                    "Fails open on any missing/malformed last_assistant_message "
                    "and never re-fires on stop_hook_active re-entry."
                ),
                test_type=TestType.BLOCKING,
                requires_event="SubagentStop",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
            AcceptanceTest(
                title="Subagent stops with a short summary + path (near-miss allow)",
                command="Dispatch a subagent that writes its report to a file and replies with a short summary",
                description="Stays silent when the final message is within the threshold",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Negative case: a compliant subagent must never be blocked.",
                test_type=TestType.BLOCKING,
                requires_event="SubagentStop",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=False,
            ),
        ]
