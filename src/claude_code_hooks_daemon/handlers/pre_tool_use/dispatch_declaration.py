"""DispatchDeclarationHandler - enforce the file-handoff contract at dispatch time.

Plan 00307 Task 2.1. A dispatched subagent's final message travels back to
the coordinator over a bounded-size wire channel: Task 1.1's reproduction
found a ~24k-token inline return silently elided in the MIDDLE by the
harness, with both start/end sentinels surviving intact — so a coordinator
can receive a report that LOOKS complete while silently missing content.
Enforcement at return (SubagentStop) cannot undo that on its own; the other
half of the fix is at dispatch time, before the subagent starts: every
dispatch prompt should declare WHERE its long-form output goes.

This handler runs on every ``Task`` tool dispatch and checks the prompt for
one of two declarations:

- a plan-folder path — which then IS the canonical home for the agent's
  ``subagent-reports/`` artefacts, or
- an explicit "not plan work" statement paired with a declared file
  destination for anything it writes.

Absent either, the contract is injected as ``additionalContext`` (advisory,
the default) or the dispatch is denied (strict mode, opt-in via
``dispatch_declaration.options.strict``).
"""

from __future__ import annotations

import re
from typing import Any

from claude_code_hooks_daemon.constants import (
    HandlerID,
    HandlerTag,
    HookInputField,
    Priority,
    ToolName,
)
from claude_code_hooks_daemon.core import Decision, GatingResult
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase

# Fallback location for dispatches that are genuinely plan-less. Configurable
# via dispatch_declaration.options.fallback_report_dir.
_DEFAULT_FALLBACK_REPORT_DIR = "untracked/agent-reports/"

# A plan-folder path: the configured plan directory (default CLAUDE/Plan)
# followed by a 5-digit plan number and a dash. Matched loosely (no anchors)
# so it fires whether the prompt writes an absolute path, a relative one, or
# wraps it in punctuation/backticks.
_PLAN_PATH_PATTERN = re.compile(r"CLAUDE/Plan/\d{5}-", re.IGNORECASE)

# "Not plan work" declaration — deliberately narrow phrasing, not a bare
# "not a plan" substring, so it does not false-fire on unrelated prose.
_NOT_PLAN_WORK_PATTERN = re.compile(r"\bnot\s+plan\s+work\b", re.IGNORECASE)

# A declared file destination: a verb ("write"/"save"/"report"/"output"/
# "store") followed by "to"/"in"/"under"/"into" and a path-shaped token
# (contains a "/"). This is a proxy for "names where files go", not a full
# path grammar — it only needs to distinguish a destination declaration from
# its absence.
_DESTINATION_PATTERN = re.compile(
    r"\b(?:writ(?:e|es|ten)|sav(?:e|es|ed)|report(?:s|ed)?|output(?:s|ted)?|stor(?:e|es|ed))\b"
    r"\s+(?:it\s+)?(?:to|in|under|into)\s+\S*/",
    re.IGNORECASE,
)


class DispatchDeclarationHandler(PreToolUseHandlerBase):
    """Advise or (strict mode) require a file-handoff declaration on Task dispatch.

    Silent when the dispatch prompt already declares a plan folder OR an
    explicit non-plan destination. Otherwise injects the contract as
    ``additionalContext`` (default) or denies (strict mode).
    """

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.DISPATCH_DECLARATION,
            priority=Priority.DISPATCH_DECLARATION,
            terminal=False,
            tags=[
                HandlerTag.WORKFLOW,
                HandlerTag.ADVISORY,
                HandlerTag.NON_TERMINAL,
                # Advisory in the default config, but opt-in strict mode
                # denies an undeclared dispatch -- the deny path is real,
                # not merely theoretical, so it is tagged BLOCKING too
                # (test_declared_behaviour_matches_source.py).
                HandlerTag.BLOCKING,
            ],
        )
        # Config flags, declared here so mypy can verify them and a typo in a
        # config setter surfaces as a normal attribute (fail-fast).
        self._strict: bool = False
        self._fallback_report_dir: str = _DEFAULT_FALLBACK_REPORT_DIR

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """True for a Task dispatch carrying a non-empty prompt."""
        if hook_input.get(HookInputField.TOOL_NAME) != ToolName.TASK:
            return False

        tool_input = hook_input.get(HookInputField.TOOL_INPUT, {})
        if not isinstance(tool_input, dict):
            return False

        return bool(tool_input.get("prompt"))

    def _has_declaration(self, prompt: str) -> bool:
        """True if the prompt names a plan folder OR a non-plan-work destination."""
        if _PLAN_PATH_PATTERN.search(prompt):
            return True
        return bool(_NOT_PLAN_WORK_PATTERN.search(prompt) and _DESTINATION_PATTERN.search(prompt))

    def _contract_text(self) -> str:
        return (
            "📋 DISPATCH DECLARATION (Plan 00307): this dispatch prompt does not "
            "declare where long-form output goes. Either:\n\n"
            "1. Name the plan folder this agent is working in (e.g. "
            "`CLAUDE/Plan/NNNNN-name/`) — it then IS the canonical home for "
            "this agent's reports, at "
            "`<plan-folder>/subagent-reports/{yymmdd}-{agent-name}-{model}.md`, or\n"
            "2. State explicitly that this is 'not plan work' AND declare where "
            f"any files it creates go (fallback: `{self._fallback_report_dir}`).\n\n"
            "Either way: long-form output goes to a FILE, never inline. The "
            "agent's final message should be a short completion summary plus "
            "the file path — a subagent's return travels over a bounded-size "
            "channel that silently elides an oversized inline report."
        )

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        """Silent when declared; otherwise advise (default) or deny (strict)."""
        tool_input = hook_input.get(HookInputField.TOOL_INPUT, {})
        prompt = tool_input.get("prompt", "") if isinstance(tool_input, dict) else ""

        if self._has_declaration(prompt):
            return GatingResult(decision=Decision.ALLOW)

        if self._strict:
            return GatingResult(decision=Decision.DENY, reason=self._contract_text())

        return GatingResult(decision=Decision.ALLOW, context=[self._contract_text()])

    def get_claude_md(self) -> str | None:
        return (
            "## dispatch_declaration — declare where a subagent's reports go\n\n"
            "Every `Task` dispatch prompt should declare EITHER the plan folder "
            "this agent is working in (its reports then live under "
            "`<plan-folder>/subagent-reports/{yymmdd}-{agent-name}-{model}.md`) "
            "OR that this is 'not plan work' plus where any created files go "
            f"(fallback: `{_DEFAULT_FALLBACK_REPORT_DIR}`).\n\n"
            "**Long-form output goes to a file, never inline** — a subagent's "
            "final message travels over a bounded-size wire channel that "
            "silently elides an oversized inline report in the MIDDLE, so a "
            "coordinator can receive what looks like a complete report while "
            "content is missing. Reply with a short summary + file path.\n\n"
            "Advisory by default (context injected when the declaration is "
            "missing); a project may opt into strict mode, which denies an "
            "undeclared dispatch."
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for the dispatch declaration handler."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="Task dispatch without a file-handoff declaration",
                command='Use the Agent tool to dispatch a subagent with a prompt that names '
                "neither a plan folder nor a non-plan-work destination",
                description=(
                    "Injects the file-handoff contract as additionalContext "
                    "(advisory default) when the dispatch prompt declares neither "
                    "a plan folder nor an explicit non-plan destination."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"DISPATCH DECLARATION", r"subagent-reports"],
                safety_notes="Advisory only in default config — never blocks the dispatch.",
                test_type=TestType.ADVISORY,
                requires_event="PreToolUse with Task tool",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
            AcceptanceTest(
                title="Task dispatch without a declaration, strict mode enabled",
                command=(
                    "With dispatch_declaration.options.strict: true, use the Agent "
                    "tool to dispatch a subagent with a prompt naming neither a "
                    "plan folder nor a non-plan-work destination"
                ),
                description="Denies the dispatch until a declaration is present (opt-in strict mode)",
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"DISPATCH DECLARATION", r"subagent-reports"],
                safety_notes="Strict mode is opt-in (disabled by default); this exercises that path.",
                test_type=TestType.BLOCKING,
                requires_event="PreToolUse with Task tool",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
            AcceptanceTest(
                title="Task dispatch naming a plan folder (near-miss allow)",
                command="Use the Agent tool with a prompt naming a CLAUDE/Plan/NNNNN-name/ folder",
                description="Stays silent when the plan folder is already declared",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Negative case: advising a compliant dispatch trains agents to ignore it.",
                test_type=TestType.ADVISORY,
                requires_event="PreToolUse with Task tool",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=False,
            ),
        ]
