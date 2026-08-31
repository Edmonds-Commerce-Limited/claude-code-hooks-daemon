"""AskUserQuestionBlockerHandler — nuanced prefix-positive policy.

Plan 00108. The handler mirrors the Stop handler's `STOPPING BECAUSE:`
convention: questions are only allowed through to the user when the agent
explicitly declares why it cannot decide autonomously, by prefixing each
`question` string with `ASKING BECAUSE:`. Without that prefix the call is
denied with guidance to state the assumed answer in plain text and proceed,
leaving an audit trail for the watching user to interrupt if the assumption
is wrong.

Two modes:
  * ``strict`` (default): DENY when any question lacks the prefix.
  * ``advisory``: ALLOW with a context warning so projects can dogfood the
    convention before turning on hard blocking.

Disabled by default. Enable in ``hooks-daemon.yaml``::

    pre_tool_use:
      handlers:
        ask_user_question_blocker:
          enabled: true
          options:
            mode: strict             # or "advisory"
            required_prefix: "ASKING BECAUSE:"
"""

from __future__ import annotations

from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, HookInputField, Priority
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.constants.tools import ToolName
from claude_code_hooks_daemon.core import Decision, GatingResult, get_data_layer
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.core.rule import Rule, RuleFormatter

# Defaults / option keys — no magic strings
DEFAULT_REQUIRED_PREFIX = "ASKING BECAUSE:"
MODE_STRICT = "strict"
MODE_ADVISORY = "advisory"

# Full first-fire teaching content (Plan 00116). The prefix is a runtime
# option (overridable per-handler-instance, even after construction — see
# test_custom_required_prefix_override), so the Rule this handler denies
# with is built fresh from the CURRENT prefix on every call rather than
# fixed once in __init__.
_RULE_VERBOSE_TEMPLATE = (
    "This handler enforces a prefix-positive policy mirroring the Stop "
    "handler's `STOPPING BECAUSE:` convention. Asking the user pauses the "
    "session; the daemon will only let a question through when you have "
    "declared why you cannot decide autonomously.\n\n"
    "TAUTOLOGICAL QUESTIONS (do NOT ask — when one option is obviously the "
    "good one, pick it):\n"
    "- Best practice vs. quick bodge → best practice\n"
    "- Increasing code quality vs. decreasing → increasing\n"
    "- Delivering the requirement vs. not delivering → delivering\n"
    "- Fixing the failing test vs. leaving it broken → fixing\n"
    "- Following project conventions vs. inventing your own → following\n"
    "If the question reduces to good-vs-bad, you already know the answer.\n\n"
    "WHAT TO DO INSTEAD:\n"
    "1. State the question and your assumed-correct answer in your output "
    "text, then proceed with that assumption. The user is watching and will "
    "interrupt if the assumption is wrong — this gives them the same control "
    "they would have had via the question, without pausing the session for "
    "an obvious answer.\n"
    "2. If the question really does have equally-valid options that you "
    "cannot resolve from context, retry the AskUserQuestion call with every "
    "`question` text prefixed `{prefix} <one-line reason you cannot decide>`."
    "\n\nExample retry:\n"
    '  "{prefix} the project README does not specify the database driver '
    'and both Postgres and MySQL are equally supported. Which should I use?"'
)

_ADVISORY_GUIDANCE_TEMPLATE = (
    "WARNING: AskUserQuestion without `{prefix}` prefix\n\n"
    "Asking pauses the session. State your assumed-correct answer in plain "
    "output text and proceed — the user will interrupt if the assumption is "
    "wrong. If the question is genuinely undecidable, prefix every question "
    "with `{prefix} <reason>` so future strict-mode rollout will not block "
    "it."
)


class AskUserQuestionBlockerHandler(PreToolUseHandlerBase):
    """Allow AskUserQuestion only when every question is prefix-justified.

    Strict mode (default): denies the call when any ``question`` lacks the
    required prefix, returning guidance to state the assumed answer instead.
    Advisory mode: allows the call through but attaches a context warning so
    teams can observe the convention before turning on hard blocking.
    """

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.ASK_USER_QUESTION_BLOCKER,
            priority=Priority.ASK_USER_QUESTION_BLOCKER,
            tags=[HandlerTag.WORKFLOW, HandlerTag.TERMINAL],
        )
        self._formatter = RuleFormatter()

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Return True only for AskUserQuestion tool calls."""
        return hook_input.get(HookInputField.TOOL_NAME) == ToolName.ASK_USER_QUESTION

    @staticmethod
    def _build_rule(prefix: str) -> Rule:
        """Build the Rule for the given prefix.

        The prefix is a runtime option that can change even after
        construction (``handler._required_prefix = "..."``), so the Rule is
        built fresh from the CURRENT prefix on every call rather than fixed
        once in ``__init__``.
        """
        return Rule(
            rule_id=RuleID.ASK_USER_QUESTION_UNJUSTIFIED,
            blocked=f"AskUserQuestion without `{prefix}` prefix",
            why="Asking pauses the session for a question the daemon cannot verify was necessary",
            fix=(
                f"State the assumed answer in output text and proceed, or retry every "
                f"question prefixed `{prefix} <reason>`"
            ),
            verbose=_RULE_VERBOSE_TEMPLATE.format(prefix=prefix),
        )

    def get_rules(self) -> list[Rule]:
        """Return the single Rule backing this handler's strict-mode blocking."""
        return [self._build_rule(DEFAULT_REQUIRED_PREFIX)]

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        """Allow if every question carries the required prefix; otherwise act per mode."""
        prefix = getattr(self, "_required_prefix", DEFAULT_REQUIRED_PREFIX)
        mode = getattr(self, "_mode", MODE_STRICT)

        all_justified = self._all_questions_justified(hook_input, prefix)

        if all_justified:
            return GatingResult(decision=Decision.ALLOW)

        if mode == MODE_ADVISORY:
            advisory_text = _ADVISORY_GUIDANCE_TEMPLATE.format(prefix=prefix)
            return GatingResult(
                decision=Decision.ALLOW,
                context=[
                    f"WARNING: AskUserQuestion without `{prefix}` prefix",
                    "State your assumed-correct answer in output text instead",
                    "User is watching and will interrupt if the assumption is wrong",
                ],
                guidance=advisory_text,
            )

        rule = self._build_rule(prefix)
        transcript_path = hook_input.get(HookInputField.TRANSCRIPT_PATH)
        tracker = get_data_layer().disclosure

        if transcript_path and tracker.was_disclosed(
            transcript_path, RuleID.ASK_USER_QUESTION_UNJUSTIFIED
        ):
            message = self._formatter.terse(rule)
        else:
            if transcript_path:
                tracker.mark_disclosed(transcript_path, RuleID.ASK_USER_QUESTION_UNJUSTIFIED)
            message = self._formatter.verbose(rule)

        return GatingResult(
            decision=Decision.DENY,
            reason=message,
        )

    @staticmethod
    def _all_questions_justified(hook_input: dict[str, Any], prefix: str) -> bool:
        """Return True iff tool_input.questions is non-empty and every question begins with prefix.

        FAIL FAST on schema violations (missing tool_input, missing questions,
        empty array, missing question text) — return False so the DENY path
        emits the guidance message. We never silently allow on malformed
        input.
        """
        tool_input = hook_input.get(HookInputField.TOOL_INPUT)
        if not isinstance(tool_input, dict):
            return False

        questions = tool_input.get("questions")
        if not isinstance(questions, list) or not questions:
            return False

        for entry in questions:
            if not isinstance(entry, dict):
                return False
            text = entry.get("question")
            if not isinstance(text, str):
                return False
            if not text.lstrip().startswith(prefix):
                return False

        return True

    def get_claude_md(self) -> str | None:
        prefix = getattr(self, "_required_prefix", DEFAULT_REQUIRED_PREFIX)
        return (
            "## ask_user_question_blocker — questions need `"
            f"{prefix}` justification\n\n"
            "AskUserQuestion calls are only allowed when every `question` "
            f"string begins with `{prefix}` (case-sensitive, leading "
            "whitespace OK). The convention mirrors the Stop handler's "
            "`STOPPING BECAUSE:` pattern — explicit declared intent gates "
            "the privilege of pausing the session.\n\n"
            "**Before asking, evaluate critically**:\n"
            "- Tautological/rhetorical questions with one obvious answer "
            '("Should I continue?", "Would you like me to proceed?") — '
            "do NOT ask. State the question and your assumed-correct answer "
            "in plain output text and proceed. The user is watching and will "
            "interrupt if the assumption is wrong.\n"
            "- Questions whose options reduce to **good vs. bad** are "
            "tautological — the answer is always the good option. Examples: "
            "best practice vs. bodge, increasing vs. decreasing code "
            "quality, delivering the requirement vs. not delivering it, "
            "fixing the failing test vs. leaving it broken, following "
            "project conventions vs. inventing your own. Do NOT ask; pick "
            "the good option and proceed.\n"
            '- Errors with a clear recovery path ("Should I fix the failing '
            'test?") — do NOT ask. Fix it.\n'
            "- Genuine choice questions where you cannot resolve the answer "
            "from context — these are the legitimate use case. Prefix every "
            f"question text with `{prefix} <one-line reason you cannot "
            "decide>` so the daemon allows the call through.\n\n"
            "**Audit log pattern** (preferred for tautological questions):\n"
            "```\n"
            "I would normally ask: <question>.\n"
            "Assumed answer: <your assumption>.\n"
            "Proceeding on that basis; the user will interrupt if wrong.\n"
            "```\n\n"
            f"**Escape hatch** (genuine ambiguity): prefix every question "
            f"text with `{prefix} <reason>`. Mixing prefixed and "
            "non-prefixed questions in one call still triggers a block — "
            "prefix all or none."
        )

    def get_acceptance_tests(self) -> list[Any]:
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            RecommendedModel,
            TestType,
        )

        prefix = DEFAULT_REQUIRED_PREFIX
        return [
            AcceptanceTest(
                title="Deny AskUserQuestion without prefix",
                command="AskUserQuestion tool call without `ASKING BECAUSE:` prefix",
                description=(
                    "Tautological / unjustified questions are denied; agent "
                    "is instructed to state the assumed answer and proceed."
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"BLOCKED", prefix, r"(?i)assum"],
                safety_notes="Only active when explicitly enabled in config",
                test_type=TestType.BLOCKING,
                requires_event="PreToolUse for AskUserQuestion",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
            AcceptanceTest(
                title="Allow AskUserQuestion when every question is prefix-justified",
                command=(
                    "AskUserQuestion call where every `question` begins with "
                    "`ASKING BECAUSE: <reason>`"
                ),
                description=(
                    "Genuinely-justified questions reach the user. The "
                    "prefix declares why the agent could not decide "
                    "autonomously."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Only active when explicitly enabled in config",
                test_type=TestType.BLOCKING,
                requires_event="PreToolUse for AskUserQuestion",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
            AcceptanceTest(
                title="Deny mixed AskUserQuestion (some prefixed, some not)",
                command=(
                    "AskUserQuestion call where one question has the prefix " "and another lacks it"
                ),
                description=(
                    "Mixed calls are denied to close the prefix-laundering "
                    "loophole (one justified question carrying N "
                    "tautological ones into the user's lap)."
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"BLOCKED", prefix],
                safety_notes="Only active when explicitly enabled in config",
                test_type=TestType.BLOCKING,
                requires_event="PreToolUse for AskUserQuestion",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
