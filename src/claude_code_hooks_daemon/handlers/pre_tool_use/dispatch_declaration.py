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
from typing import Any, Final

from claude_code_hooks_daemon.constants import (
    SUBAGENT_DISPATCH_TOOL_NAMES,
    HandlerID,
    HandlerTag,
    HookInputField,
    Priority,
)
from claude_code_hooks_daemon.core import Decision, GatingResult
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.utils.option_coercion import coerce_bool_option

# Fallback location for dispatches that are genuinely plan-less. Configurable
# via dispatch_declaration.options.fallback_report_dir.
_DEFAULT_FALLBACK_REPORT_DIR = "untracked/agent-reports/"

# Fallback plan directory, used only when no ProjectLayout facade was
# injected (e.g. a handler constructed directly in a unit test). Mirrors
# PlanWorkflowConfig.directory's default exactly -- same idiom as
# plan_workflow.py's `_FALLBACK_PLAN_DIR`.
_FALLBACK_PLAN_DIR: Final[str] = "CLAUDE/Plan"

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
        # `Any`, not `bool`: options arrive by blind setattr from YAML, so a
        # string value is a real runtime possibility `_is_strict()` guards
        # against via the shared `coerce_bool_option` helper (peer callers:
        # bash_safe_mode's `_min_statements: Any` and
        # subagent_report_size_blocker's `_threshold_chars: Any`, both
        # coerced through that same module's `coerce_int_option`, for the
        # identical mypy redundant-expr concern).
        self._strict: Any = False
        self._fallback_report_dir: str = _DEFAULT_FALLBACK_REPORT_DIR

    def _plan_dir(self) -> str:
        """Configured plan directory (facade, or the matching default).

        ``_project_layout`` is injected onto every handler instance
        unconditionally (registry.py), unlike ``_track_plans_in_project``
        which the registry only injects into PLANNING-tagged handlers. This
        handler is tagged WORKFLOW/ADVISORY/BLOCKING, not PLANNING, so the
        facade -- already the general-purpose home for this exact question,
        precedented in ``plan_workflow.py``'s identically-named method -- is
        the route that needs no tag change. Same idiom as
        ``markdown_organization.py`` and ``recovery_cron_advisor.py``.
        """
        layout = self._project_layout
        return layout.plan_dir if layout is not None else _FALLBACK_PLAN_DIR

    def _plan_path_pattern(self) -> re.Pattern[str]:
        """A plan-folder path built from the configured plan directory.

        The configured directory followed by a 5-digit plan number and a
        dash. Matched loosely (no anchors) so it fires whether the prompt
        writes an absolute path, a relative one, or wraps it in
        punctuation/backticks. ``re.escape`` guards against a configured
        directory that happens to contain regex metacharacters.
        """
        return re.compile(rf"{re.escape(self._plan_dir())}/\d{{5}}-", re.IGNORECASE)

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """True for a subagent dispatch (Task/Agent) carrying a non-empty prompt."""
        if hook_input.get(HookInputField.TOOL_NAME) not in SUBAGENT_DISPATCH_TOOL_NAMES:
            return False

        tool_input = hook_input.get(HookInputField.TOOL_INPUT, {})
        if not isinstance(tool_input, dict):
            return False

        return bool(tool_input.get("prompt"))

    def _has_declaration(self, prompt: str) -> bool:
        """True if the prompt names a plan folder OR a non-plan-work destination."""
        if self._plan_path_pattern().search(prompt):
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
            "any files it creates go (fallback: "
            f"`{self._fallback_report_dir}{{yymmdd}}-{{agent-name}}-"
            "{model}.md`, same filename convention as the plan-folder case).\n\n"
            "Either way: long-form output goes to a FILE, never inline. The "
            "agent's final message should be a short completion summary plus "
            "the file path — a subagent's return travels over a bounded-size "
            "channel that silently elides an oversized inline report."
        )

    def _is_strict(self) -> bool:
        """Coerced ``strict`` option.

        Options arrive by blind ``setattr`` from YAML, so the type is not
        trusted: a YAML author writing ``strict: "false"`` (a string) would
        otherwise be silently treated as truthy Python and get an unwanted
        DENY. Delegates to the shared :func:`coerce_bool_option` (Plan 00311
        Task 1.5): a real ``bool`` is used as-is; a string is matched
        case-insensitively against ``"true"``/``"false"``; anything else
        (including a genuinely malformed value) degrades to the advisory
        default (``False``) rather than surprising the caller with strict
        enforcement.
        """
        return coerce_bool_option(self._strict, default=False)

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        """Silent when declared; otherwise advise (default) or deny (strict)."""
        tool_input = hook_input.get(HookInputField.TOOL_INPUT, {})
        prompt = tool_input.get("prompt", "") if isinstance(tool_input, dict) else ""

        if self._has_declaration(prompt):
            return GatingResult(decision=Decision.ALLOW)

        if self._is_strict():
            return GatingResult(decision=Decision.DENY, reason=self._contract_text())

        return GatingResult(decision=Decision.ALLOW, context=[self._contract_text()])

    def get_claude_md(self) -> str | None:
        return (
            "## dispatch_declaration — declare where a subagent's reports go\n\n"
            "Every `Task` dispatch prompt should declare EITHER the plan folder "
            "this agent is working in (its reports then live under "
            "`<plan-folder>/subagent-reports/{yymmdd}-{agent-name}-{model}.md`) "
            "OR that this is 'not plan work' plus where any created files go "
            "(fallback: `"
            f"{_DEFAULT_FALLBACK_REPORT_DIR}{{yymmdd}}-{{agent-name}}-"
            "{model}.md`, same filename convention as the plan-folder case).\n\n"
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
        from claude_code_hooks_daemon.constants.tools import ToolName
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            RecommendedModel,
            TestType,
            ToolPayload,
        )

        undeclared_probe = ToolPayload(
            tool_name=ToolName.AGENT,
            tool_input={
                "description": "summarise findings",
                "prompt": "Read the three files under src/ and summarise what they do.",
            },
        )
        declared_probe = ToolPayload(
            tool_name=ToolName.AGENT,
            tool_input={
                "description": "summarise findings",
                "prompt": (
                    "Write your report into CLAUDE/Plan/00345-harness-payloads-for-"
                    "shell-and-call-syntax-tests/ and summarise what you found."
                ),
            },
        )

        return [
            AcceptanceTest(
                title="Task dispatch without a file-handoff declaration",
                command=undeclared_probe.as_instruction(),
                tool_payload=undeclared_probe,
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
                harness_cannot_produce=(
                    "Strict mode is off in this checkout's configuration, and a "
                    "payload cannot turn it on: the harness varies the EVENT, not "
                    "the daemon's config. Converting this needs a per-probe config "
                    "override the harness does not have, and inventing one would "
                    "mean a probe that reconfigures the daemon other probes are "
                    "sharing. Covered by "
                    "tests/unit/handlers/pre_tool_use/test_dispatch_declaration.py."
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
                command=declared_probe.as_instruction(),
                tool_payload=declared_probe,
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
