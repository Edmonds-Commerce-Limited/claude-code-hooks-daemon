"""PlanTimeEstimatesHandler - blocks time estimates in plan documents."""

import re
from pathlib import Path
from typing import Any, ClassVar

from claude_code_hooks_daemon.constants import (
    HandlerID,
    HandlerTag,
    HookInputField,
    Priority,
    ToolName,
)
from claude_code_hooks_daemon.core import Decision, GatingResult
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.core.utils import get_file_content, get_file_path
from claude_code_hooks_daemon.plan_qa.paths import is_journal_file


class PlanTimeEstimatesHandler(PreToolUseHandlerBase):
    """Block time estimates in plan documents."""

    ESTIMATE_PATTERNS: ClassVar[list[str]] = [
        r"\*\*Estimated\s+Effort\*\*:\s*[^\n]*(?:hours?|minutes?|days?|weeks?)",
        r"Estimated\s+Effort:\s*[^\n]*(?:hours?|minutes?|days?|weeks?)",
        r"(?:Time\s+)?[Ee]stimated\s+(?:time)?:\s*[^\n]*(?:hours?|minutes?|days?|weeks?)",
        r"\*\*Total\s+Estimated\s+Time\*\*:\s*[^\n]*(?:hours?|minutes?|days?|weeks?)",
        r"Total\s+Estimated\s+Time:\s*[^\n]*(?:hours?|minutes?|days?|weeks?)",
        r"\*\*Target\s+Completion\*\*:\s*\d{4}-\d{2}-\d{2}",
        r"Target\s+Completion:\s*\d{4}-\d{2}-\d{2}",
        r"\*\*Completion\*\*:\s*\d{4}-\d{2}-\d{2}",
        r"Completion:\s*\d{4}-\d{2}-\d{2}",
        # Work estimate patterns (with context clues)
        r"\b(?:take|takes|require|requires|need|needs|approximately|about)\s+\d+[-]\d+\s*(?:hour|hr|minute|min|day|week|month)s?\b",
        r"\b(?:take|takes|require|requires|need|needs|approximately|about)\s+\d+\s+(?:hour|hr|minute|min|day|week|month)s?\b",
        r"\bPhase\s+\d+[^:]*:\s*[^\(]*\(\s*\d+[-]\d+\s*(?:hour|hr|minute|min|day|week)s?\s*\)",
        r"\bPhase\s+\d+[^:]*:\s*[^\(]*\(\s*\d+\s+(?:hour|hr|minute|min|day|week)s?\s*\)",
        r"\b(?:Total|Overall|Combined)[^\n:]*:\s*\d+[-]\d+\s*(?:hour|hr|minute|min|day|week)s?\b",
        r"\b(?:Total|Overall|Combined)[^\n:]*:\s*\d+\s+(?:hour|hr|minute|min|day|week)s?\b",
        r"\b\d+[-]\d+\s*(?:hour|hr|minute|min|day|week)s?\s+(?:of\s+)?(?:work|implementation|development|effort|time)\b",
        r"\b\d+\s+(?:hour|hr|minute|min|day|week)s?\s+(?:of\s+)?(?:work|implementation|development|effort|time)\b",
        r"\b(ETA|timeline|deadline|due date):\s*\d",
    ]

    # Technical terms that should NOT be flagged (feature descriptions)
    TECHNICAL_PATTERNS: ClassVar[list[str]] = [
        r"\bTTL\b",
        r"\bcache\b",
        r"\bretention\b",
        r"\bpolicy\b",
        r"\bwindow\b",
        r"\btimeout\b",
        r"\bexpir(?:e|es|ation|y)\b",
        r"\btracking\b",
        r"\btrial\b",
        r"\bperiod\b",
        r"\bsession\b",
        r"\brolling\b",
        r"\busage\b",
        r"\bAPI\b",
        r"\brate\s+limit",
    ]

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.PLAN_TIME_ESTIMATES,
            priority=Priority.PLAN_TIME_ESTIMATES,
            tags=[
                HandlerTag.WORKFLOW,
                HandlerTag.PLANNING,
                # BLOCKING, not ADVISORY: `handle()` returns Decision.DENY
                # unconditionally for a matched time estimate. The generated
                # handler table renders whatever is declared here, so an
                # ADVISORY tag advertised this blocker as a mere warning.
                HandlerTag.BLOCKING,
                HandlerTag.NON_TERMINAL,
            ],
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Check if writing time estimates to plan files."""
        tool_name = hook_input.get(HookInputField.TOOL_NAME)
        if tool_name not in [ToolName.WRITE, ToolName.EDIT]:
            return False

        file_path = get_file_path(hook_input)
        if not file_path or "/Plan/" not in file_path or not file_path.endswith(".md"):
            return False

        # Plan 00190: a journal is an APPEND-ONLY record of what actually
        # happened, not a plan document. "this took two hours" in a journal is
        # a historical fact, not a forward estimate, so the plan-document rule
        # must never reach it. ``is_journal_file`` is the shared, config-
        # independent predicate: it exempts by LOCATION (anything inside a
        # journal directory, however its name is spelled) as well as by
        # day-file grammar. Keying on the name alone let a typo'd date
        # re-enable plan rules on journal content.
        if is_journal_file(Path(file_path)):
            return False

        content = get_file_content(hook_input)
        if tool_name == ToolName.EDIT:
            content = hook_input.get(HookInputField.TOOL_INPUT, {}).get("new_string", "")

        if not content:
            return False

        # Block if ANY estimate has no co-located technical term on its own line.
        # Scoping the technical-term exemption to the matched estimate's line
        # prevents a single technical keyword anywhere in the document from
        # whitelisting every estimate (a trivial whole-document bypass).
        return self._has_unexempted_estimate(content)

    def _has_unexempted_estimate(self, content: str) -> bool:
        """Return True if any time-estimate line lacks a co-located technical term.

        Args:
            content: The text being written to the plan document.

        Returns:
            True when at least one line contains a blocked estimate pattern and
            no technical-term exemption on that same line; False otherwise.
        """
        for line in content.splitlines():
            if not self._line_has_estimate(line):
                continue
            if not self._line_has_technical_term(line):
                return True
        return False

    def _line_has_estimate(self, line: str) -> bool:
        """Return True if the line matches any blocked estimate pattern."""
        return any(re.search(pattern, line, re.IGNORECASE) for pattern in self.ESTIMATE_PATTERNS)

    def _line_has_technical_term(self, line: str) -> bool:
        """Return True if the line contains a technical-term exemption."""
        return any(re.search(pattern, line, re.IGNORECASE) for pattern in self.TECHNICAL_PATTERNS)

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        """Block time estimates."""
        file_path = get_file_path(hook_input)

        return GatingResult(
            decision=Decision.DENY,
            reason=(
                "🚫 BLOCKED: Time estimates not allowed in plan documents\n\n"
                f"File: {file_path}\n\n"
                "Plans should focus on WHAT needs to be done, not WHEN.\n\n"
                "WHY: Time estimates in plans create false expectations and pressure.\n\n"
                "✅ CORRECT APPROACH:\n"
                "  - Break work into concrete tasks\n"
                "  - Describe implementation steps\n"
                "  - Let user decide scheduling\n"
                "  - Focus on actionable work, not timelines"
            ),
        )

    def get_claude_md(self) -> str | None:
        return (
            "## plan_time_estimates — plans describe WHAT, not WHEN\n\n"
            "A `Write`/`Edit` that puts time estimates into a plan document is "
            "blocked — that is any "
            "`CLAUDE/Plan/**/*.md` EXCEPT anything under a plan's `JOURNAL/`. Plans "
            "capture the work to be done, not how long it will take.\n\n"
            "**Everything under `JOURNAL/` is exempt** — day-files "
            "(`NNNNN-Journal-YY-MM-DD.md`) and any other file in there. A journal "
            "records what actually happened, so an elapsed duration is a historical "
            "fact, not a forward estimate. The exemption is by LOCATION as well as by "
            "filename, so a mis-named day-file stays exempt.\n\n"
            "**Blocked in plan documents:**\n\n"
            "- Effort estimates — `**Estimated Effort**: 4 hours`, `Total Estimated Time: 2 days`\n"
            "- Per-phase durations — `Phase 1: ... (3 days)`, `takes 8-12 hours`\n"
            "- Target/completion dates — `**Target Completion**: 2026-06-30`, "
            "`Completion: 2026-06-30`\n"
            "- `ETA:`, `timeline:`, `deadline:`, `due date:` lines\n\n"
            "**Instead:** break work into concrete tasks and implementation steps, and "
            "let the user decide scheduling. Technical durations that describe a feature "
            "(cache TTL, session timeout, retention window) are allowed — only work/effort "
            "estimates are blocked."
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for Plan Time Estimates."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="Block time estimates in plan",
                command=(
                    "Use the Write tool to write to /tmp/acceptance-test-plantime/Plan/001-test/PLAN.md"
                    " with content '# Plan 001\\n\\n**Estimated Effort**: 4 hours\\n\\nTask list here.'"
                ),
                description="Blocks time estimates in plan documents (plans focus on WHAT not WHEN)",
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"time estimate", r"BLOCKED"],
                safety_notes="Uses /tmp path - safe. Handler blocks Write before file is created.",
                test_type=TestType.BLOCKING,
                setup_commands=["mkdir -p /tmp/acceptance-test-plantime/Plan/001-test"],
                cleanup_commands=["rm -rf /tmp/acceptance-test-plantime"],
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
