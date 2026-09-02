"""BudgetExhaustionDetectorHandler - generic budget/quota-exhaustion advisory.

Plan 00315 Task 2.1. Beyond the visible 5-hour/weekly usage limits, agent
sessions carry opaque operational budgets (a web-search budget, output-size
caps, and possibly others not yet catalogued) that surface only as mid-task
tool responses. `BUDGETS.md` (Plan 00315, Task 1.3 synthesis) found the
field-confirmed web-search refusal shape and a family of generic
budget/quota/limit-reached shapes; this handler is a GENERIC PostToolUse
detector for that family, so it catches the web-search shape today and any
future budget message without a new handler per budget.

Matching scans the completed tool call's ``tool_response`` for:

  - the pinned web-search fragments ("Web search was not performed", "web
    search budget"), verbatim from the field-confirmed fixture, and
  - generic shapes: "budget" near "exhausted"/"used up"/"exceeded", "quota
    exceeded", "budget ... limit reached".

Deliberately NEVER keys on the configurable ceiling number (e.g. "200" of
"200 WebSearch calls") -- BUDGETS.md pins the ceiling as environment-variable
configurable (``CLAUDE_CODE_MAX_WEB_SEARCHES``), so a number alone is not a
stable signal and would false-fire on ordinary counts ("Found 200 results").

**Precision**: by default, Read/Grep/Glob/Edit/Write/NotebookEdit tool
responses are excluded from
matching (``options.excluded_tools``). Those tools return FILE CONTENTS the
model merely read -- prose in a file that happens to discuss budget
exhaustion (this very docstring, for instance) is not a live exhaustion
event, and firing on it would be a false positive on the single most common
shape of activity in a session. Every other tool's ``tool_response`` is a
genuine tool-produced result, where the same wording is a live signal.

On a match: ALLOW with an advisory instructing the agent to surface the
budget hit to the user with a bold, prominent banner, name the affected
work, and stop retrying the exhausted tool -- never blocks (Decision.ALLOW
always; the tool call already completed).

Each detection is also appended to an untracked occurrence ledger
(``budget-exhaustion-events.jsonl``, Task 2.2) so recurrence is visible
across a session and to the owner afterwards, mirroring the append/cap
conventions of ``stop-events.jsonl``. Ledger writes are best-effort and
fail-open: an I/O error is logged and never raised into the handler's
Decision.ALLOW return.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.constants import (
    HandlerID,
    HandlerTag,
    HookInputField,
    Priority,
)
from claude_code_hooks_daemon.core import BlockingResult, Decision
from claude_code_hooks_daemon.core.handler_bases import PostToolUseHandlerBase
from claude_code_hooks_daemon.utils.private_io import make_private_dir, open_private_append
from claude_code_hooks_daemon.utils.retention import cap_log_file

logger = logging.getLogger(__name__)

# ─── Tools excluded from matching by default ─────────────────────────────────

# File-content tools: their tool_response is what a file merely SAYS, not a
# live budget signal from a tool that was actually rate/quota-limited.
_DEFAULT_EXCLUDED_TOOLS: Final[tuple[str, ...]] = (
    "Read",
    "Grep",
    "Glob",
    # Edit/Write/NotebookEdit responses echo AUTHORED file content back, so a
    # budget phrase being written into a test fixture or document would
    # otherwise fire the detector on its own material.
    "Edit",
    "Write",
    "NotebookEdit",
)

# A Bash command naming any of these is INSPECTING recorded/pattern text —
# the ledger itself, or this handler's own source/tests (whose fixtures
# contain the trigger phrases) — not hitting a live budget. Without this
# guard, cat-ing the ledger re-fires the detector and appends a fresh entry:
# a self-feeding loop.
_SELF_REFERENTIAL_COMMAND_MARKERS: Final[tuple[str, ...]] = (
    "budget-exhaustion-events.jsonl",
    "budget_exhaustion_detector",
)

# The same markers, applied to the tool RESPONSE. A payload that names this
# handler or its ledger is documentation ABOUT the feature -- the CHANGELOG
# entry, BUDGETS.md, the release notes -- not a live budget signal, and the
# command guard above cannot see it (the command is an innocent `head
# CHANGELOG.md`; the trigger prose is in the CONTENT). Observed live while
# reading this repo's own changelog during the v3.60.0 release. Safe because a
# genuine harness budget message never names the detector or its ledger.
_SELF_REFERENTIAL_RESPONSE_MARKERS: Final[tuple[str, ...]] = (
    "budget-exhaustion-events.jsonl",
    "budget_exhaustion_detector",
)

# ─── Pattern family ───────────────────────────────────────────────────────────

# Pinned, verbatim-derived fragments from the field-confirmed web-search
# budget refusal (BUDGETS.md). Never the ceiling number ("200 of 200") --
# that count is configurable via CLAUDE_CODE_MAX_WEB_SEARCHES and is not a
# stable trigger on its own.
_WEB_SEARCH_BUDGET_RE: Final[re.Pattern[str]] = re.compile(
    r"Web search was not performed|web search budget",
    re.IGNORECASE,
)

# Generic "budget ... exhausted/used up/exceeded" (either order, bounded gap
# so unrelated prose two paragraphs apart never links up).
_BUDGET_EXHAUSTED_RE: Final[re.Pattern[str]] = re.compile(
    r"budget\b.{0,40}\b(exhausted|used up|exceeded)\b"
    r"|\b(exhausted|used up|exceeded)\b.{0,40}\bbudget\b",
    re.IGNORECASE | re.DOTALL,
)

# "quota exceeded" -- a distinct vocabulary from "budget" that BUDGETS.md
# names explicitly as part of the generic shape family.
_QUOTA_EXCEEDED_RE: Final[re.Pattern[str]] = re.compile(
    r"quota\b.{0,20}\bexceeded\b",
    re.IGNORECASE | re.DOTALL,
)

# "budget ... limit reached" (either order) -- "limit reached" alone is too
# generic (matches unrelated rate-limit/size-cap prose with no budget
# framing), so it only counts here paired with "budget" nearby.
_BUDGET_LIMIT_REACHED_RE: Final[re.Pattern[str]] = re.compile(
    r"budget\b.{0,40}\blimit reached\b|\blimit reached\b.{0,40}\bbudget\b",
    re.IGNORECASE | re.DOTALL,
)

_BUILTIN_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    _WEB_SEARCH_BUDGET_RE,
    _BUDGET_EXHAUSTED_RE,
    _QUOTA_EXCEEDED_RE,
    _BUDGET_LIMIT_REACHED_RE,
)

# ─── Ledger ────────────────────────────────────────────────────────────────────

_LEDGER_FILENAME: Final[str] = "budget-exhaustion-events.jsonl"
_MATCHED_FRAGMENT_TRUNCATE_LEN: Final[int] = 200
# Mirrors stop-events.jsonl's bound (Plan 00181): keep newest half on breach.
_LEDGER_MAX_BYTES: Final[int] = 644 * 1024


def _stringify_tool_response(tool_response: Any) -> str:
    """Return a searchable string form of ``tool_response``.

    ``tool_response`` shape varies by tool (a dict with stdout/stderr for
    Bash, a dict with content for WebSearch, a bare string for some tools).
    JSON-serialising whatever it is (falling back to ``str()`` for anything
    non-serialisable) gives one text blob to pattern-match without coupling
    this handler to any single tool's response schema.
    """
    if isinstance(tool_response, str):
        return tool_response
    try:
        return json.dumps(tool_response, default=str)
    except (TypeError, ValueError):
        return str(tool_response)


def _find_matched_fragment(text: str, extra_patterns: list[re.Pattern[str]]) -> str | None:
    """Return the first matched fragment's own text, or None if no pattern hits."""
    for pattern in (*_BUILTIN_PATTERNS, *extra_patterns):
        match = pattern.search(text)
        if match:
            return match.group(0)
    return None


def _advisory(tool_name: str, matched_fragment: str) -> str:
    """Build the budget-exhaustion advisory for the given tool/fragment."""
    return (
        "BUDGET EXHAUSTION DETECTED in the response of this tool call "
        f"({tool_name}). Matched text: {matched_fragment!r}\n\n"
        "You MUST surface this to the user VERY CLEARLY in your next "
        "user-facing message. Lead with a bold banner, e.g.:\n\n"
        "  🚨 **BUDGET EXHAUSTED: <budget name>** 🚨\n\n"
        "Name what you were attempting when the budget was hit, state what "
        "work is now affected or incomplete as a result, and do NOT silently "
        "retry the exhausted tool or quietly degrade to a worse alternative "
        "-- the user must be told plainly, not left to infer it from missing "
        "results."
    )


class BudgetExhaustionDetectorHandler(PostToolUseHandlerBase):
    """Advisory PostToolUse handler that flags budget/quota-exhaustion messaging.

    Generic pattern family (never keyed on a configurable ceiling number) over
    the tool_response of any completed tool call, excluding file-content
    tools (Read/Grep/Glob/Edit/Write/NotebookEdit) by default so file prose
    about budgets is never
    mistaken for a live exhaustion event. Never blocks: on a match it ALLOWs
    with an advisory demanding prominent user-facing reporting, and appends
    one line to an untracked occurrence ledger.
    """

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.BUDGET_EXHAUSTION_DETECTOR,
            priority=Priority.BUDGET_EXHAUSTION_DETECTOR,
            terminal=False,
            tags=[HandlerTag.WORKFLOW, HandlerTag.ADVISORY, HandlerTag.NON_TERMINAL],
        )
        # Config options — injected by the registry via setattr; typed and
        # defaulted here so mypy sees real attributes, not dynamic ones.
        self._excluded_tools: list[str] | None = None
        self._extra_patterns: list[str] | None = None
        # Cached compiled extra patterns, resolved lazily (options are applied
        # by the registry after __init__ runs).
        self._compiled_extra_patterns: list[re.Pattern[str]] | None = None
        # Matched fragment computed in matches() and reused by handle() for
        # the same event, so the scan runs once per event.
        self._cached_fragment: str | None = None

    def get_default_enabled(self) -> bool:
        """Opt-OUT handler — ON by default (owner ruling, Plan 00315).

        Advisory-only (never blocks), so safe to ship enabled. Must stay
        consistent with the config template (enabled: true).
        """
        return True

    def _resolved_excluded_tools(self) -> tuple[str, ...]:
        if self._excluded_tools is None:
            return _DEFAULT_EXCLUDED_TOOLS
        return tuple(self._excluded_tools)

    def _resolved_extra_patterns(self) -> list[re.Pattern[str]]:
        if self._compiled_extra_patterns is None:
            compiled: list[re.Pattern[str]] = []
            for raw in self._extra_patterns or []:
                try:
                    compiled.append(re.compile(raw, re.IGNORECASE | re.DOTALL))
                except re.error as exc:
                    logger.warning(
                        "budget_exhaustion_detector: invalid extra_patterns regex %r: %s",
                        raw,
                        exc,
                    )
                    continue
            self._compiled_extra_patterns = compiled
        return self._compiled_extra_patterns

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Return True if the tool response matches a budget-exhaustion pattern."""
        self._cached_fragment = None
        tool_name = hook_input.get(HookInputField.TOOL_NAME)
        if tool_name in self._resolved_excluded_tools():
            return False
        tool_input = hook_input.get(HookInputField.TOOL_INPUT)
        if isinstance(tool_input, dict):
            command = tool_input.get("command")
            if isinstance(command, str) and any(
                marker in command for marker in _SELF_REFERENTIAL_COMMAND_MARKERS
            ):
                return False
        tool_response = hook_input.get(HookInputField.TOOL_RESPONSE)
        text = _stringify_tool_response(tool_response)
        if not text:
            return False
        if any(marker in text for marker in _SELF_REFERENTIAL_RESPONSE_MARKERS):
            return False
        fragment = _find_matched_fragment(text, self._resolved_extra_patterns())
        if fragment is None:
            return False
        self._cached_fragment = fragment
        return True

    def _resolve_fragment(self, hook_input: dict[str, Any]) -> str | None:
        """Return the matched fragment, reusing matches()'s cache if set."""
        cached = self._cached_fragment
        self._cached_fragment = None
        if cached is not None:
            return cached
        tool_response = hook_input.get(HookInputField.TOOL_RESPONSE)
        text = _stringify_tool_response(tool_response)
        return _find_matched_fragment(text, self._resolved_extra_patterns())

    def _append_ledger_entry(self, session_id: str, tool_name: str, matched_fragment: str) -> bool:
        """Best-effort append to the untracked occurrence ledger.

        Fail-open: any error (no ProjectContext, permissions, disk) is logged
        at WARNING here -- this is observability, not a gate, and must never
        turn a successful detection into a broken tool call. Returns True on
        a successful append and False when the error was swallowed, mirroring
        ``blockage_marker.write_marker``'s Plan 00314 contract: the caller can
        tell "detected but not logged" apart from "detected and logged"
        rather than the outcome vanishing silently into a log line.
        """
        try:
            from claude_code_hooks_daemon.core.project_context import ProjectContext

            untracked_dir: Path = ProjectContext.daemon_untracked_dir()
            ledger_path = untracked_dir / _LEDGER_FILENAME
            make_private_dir(ledger_path.parent)
            entry: dict[str, Any] = {
                "timestamp": datetime.now(tz=UTC).isoformat(),
                "session_id": session_id,
                "tool_name": tool_name,
                "matched_fragment": matched_fragment[:_MATCHED_FRAGMENT_TRUNCATE_LEN],
            }
            with open_private_append(ledger_path) as handle:
                handle.write(json.dumps(entry) + "\n")
            cap_log_file(
                ledger_path,
                max_bytes=_LEDGER_MAX_BYTES,
                retain_bytes=_LEDGER_MAX_BYTES // 2,
            )
            return True
        except (RuntimeError, OSError) as exc:
            logger.warning(
                "budget_exhaustion_detector: ledger append failed (non-critical): %s", exc
            )
            return False

    def handle(self, hook_input: dict[str, Any]) -> BlockingResult:
        """Inject a prominent budget-exhaustion advisory and log the occurrence.

        Always returns Decision.ALLOW -- the tool call already completed, and
        this handler's entire role is to make an already-happened budget hit
        legible, never to gate anything.
        """
        tool_name = str(hook_input.get(HookInputField.TOOL_NAME, "") or "unknown")
        fragment = self._resolve_fragment(hook_input)
        if fragment is None:
            return BlockingResult(decision=Decision.ALLOW)

        session_id = str(hook_input.get(HookInputField.SESSION_ID, "") or "unknown")
        ledger_written = self._append_ledger_entry(session_id, tool_name, fragment)
        if not ledger_written:
            logger.debug(
                "budget_exhaustion_detector: advisory fired without a ledger record "
                "(tool=%s, session=%s)",
                tool_name,
                session_id,
            )

        return BlockingResult(decision=Decision.ALLOW, context=[_advisory(tool_name, fragment)])

    def get_claude_md(self) -> str | None:
        """Return CLAUDE.md guidance about this handler."""
        return (
            "## budget_exhaustion_detector — hidden agent budgets are surfaced\n\n"
            "Beyond the visible 5-hour/weekly usage limits, sessions carry opaque "
            "operational budgets (e.g. a per-session web-search budget) that surface "
            "only as mid-task tool responses, with no upfront warning. A PostToolUse "
            "advisory scans each completed tool call's response for budget/quota-"
            "exhaustion messaging (the web-search refusal shape, plus a generic "
            "'budget exhausted'/'quota exceeded'/'budget ... limit reached' family) "
            "and, when it matches, tells you to report it.\n\n"
            "**When this fires: report it prominently, immediately, and do not "
            "silently retry or degrade.** Lead your next user-facing message with a "
            "bold banner naming the budget, state what you were attempting and what "
            "work is now affected, and stop hammering the exhausted tool.\n\n"
            "File-content tools (Read/Grep/Glob/Edit/Write/NotebookEdit) are excluded by default, since their "
            "response is text a file merely CONTAINS, not a live exhaustion signal.\n\n"
            "Every detection is appended to `budget-exhaustion-events.jsonl` in the "
            "daemon's untracked directory, so recurrence is visible across the "
            "session and afterwards.\n\n"
            "### Configuration\n\n"
            "On by default (opt-out). Configure via "
            "`handlers.post_tool_use.budget_exhaustion_detector.options`:\n\n"
            "```yaml\n"
            "handlers:\n"
            "  post_tool_use:\n"
            "    budget_exhaustion_detector:\n"
            "      enabled: true\n"
            "      options:\n"
            "        excluded_tools: [Read, Grep, Glob, Edit, Write, NotebookEdit]  # override\n"
            "        extra_patterns: []                   # extra regexes, additive\n"
            "```\n"
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests: an advisory probe and a near-miss allow."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="Web-search budget refusal triggers a prominent budget advisory",
                command=(
                    "Simulate a WebSearch tool response containing the text "
                    "'Web search was not performed: this session has used its web "
                    "search budget (200 of 200 WebSearch calls).'"
                ),
                description=(
                    "The pinned field-confirmed web-search budget refusal shape "
                    "triggers an advisory instructing the agent to report the "
                    "budget hit to the user with a bold banner and stop retrying."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[
                    r"BUDGET EXHAUSTED",
                    r"🚨",
                    r"Web search was not performed",
                    r"not.*retry|retry.*not",
                ],
                safety_notes="Synthetic tool_response text only; no live tool call is made.",
                test_type=TestType.ADVISORY,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="Ordinary prose mentioning 'budget' does not trigger the advisory",
                command=(
                    "Simulate a Bash tool response containing the text 'Updated the "
                    "project budget planning spreadsheet.'"
                ),
                description=(
                    "Near-miss: the word 'budget' appears with no exhaustion/quota "
                    "context, so no advisory fires and the response is unaffected."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Synthetic tool_response text only; no live tool call is made.",
                test_type=TestType.ADVISORY,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=False,
            ),
        ]
