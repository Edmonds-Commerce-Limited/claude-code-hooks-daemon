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

**Precision**: by default, Read/Grep/Glob/Edit/Write/NotebookEdit/Task/Agent
tool responses are excluded from matching (``options.excluded_tools``). The
first six return FILE CONTENTS the model merely read -- prose in a file that
happens to discuss budget exhaustion (this very docstring, for instance) is
not a live exhaustion event. Task/Agent's ``tool_response`` is a dispatched
sub-agent's own composed final message, never a field the Task/Agent tool
machinery itself populates from a budget check; if the sub-agent's own work
genuinely hits a budget, that fires directly in the sub-agent's own session
at the tool call that hit it, so excluding the orchestrator's echo of it
loses no signal. Every other tool's ``tool_response`` is a genuine
tool-produced result, where the same wording is a live signal.

Beyond the excluded-tools list, two STRUCTURAL checks (not keyword lists)
keep the detector from self-triggering on text that merely QUOTES a budget
message rather than delivering one, documented in full in
``CLAUDE/Plan/00319-supervisor-release-review-followups/BUDGET-DETECTOR-DESIGN.md``:

  - a Bash ``tool_response`` is excluded when the COMMAND's every pipeline
    stage is a content-passthrough verb (``cat``, ``grep``, ``jq``, ``tail``,
    etc. -- see ``_CONTENT_PASSTHROUGH_VERBS``), because such a command only
    ever reproduces or reformats bytes that already exist somewhere; it never
    independently discovers a live budget signal. Classified by VERB, not by
    which file is named, so it generalises to any file (a copy of the
    ledger, a generated report, this handler's own source) without listing
    any of them.
  - any span of ``tool_response`` text that parses as a JSON object carrying
    this handler's own ledger record key set (``_LEDGER_RECORD_KEYS``) is
    stripped before matching runs, because a genuine harness budget message
    is prose, never JSON in this handler's own record shape. This survives
    ``jq``'s pretty-printing, which defeats a literal-substring or
    per-line-JSON check.

The pre-existing literal ``_SELF_REFERENTIAL_COMMAND_MARKERS`` /
``_SELF_REFERENTIAL_RESPONSE_MARKERS`` checks still run underneath both of
the above -- they catch the one shape neither structural check does: a
*generated report* whose producing command is not a content-passthrough verb
(e.g. a Python script) but whose output names this handler by class or
module.

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
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.constants import (
    SUBAGENT_DISPATCH_TOOL_NAMES,
    HandlerID,
    HandlerTag,
    HookInputField,
    Priority,
)
from claude_code_hooks_daemon.core import BlockingResult, Decision
from claude_code_hooks_daemon.core.handler_bases import PostToolUseHandlerBase
from claude_code_hooks_daemon.utils.private_io import make_private_dir, open_private_append
from claude_code_hooks_daemon.utils.retention import cap_log_file
from claude_code_hooks_daemon.utils.shell_segmentation import split_unquoted

logger = logging.getLogger(__name__)

# ─── Tools excluded from matching by default ─────────────────────────────────

# File-content tools: their tool_response is what a file merely SAYS, not a
# live budget signal from a tool that was actually rate/quota-limited. Task
# and Agent (SUBAGENT_DISPATCH_TOOL_NAMES -- the same constant
# dispatch_declaration/agent_isolation_advisor use for the same two tool
# names) join them for a related reason: their tool_response is a dispatched
# sub-agent's own composed final message, never a field the Task/Agent tool
# machinery itself populates from a live budget check. A genuine budget hit
# during the sub-agent's own work already fires directly in the sub-agent's
# own session, at the tool call that hit it -- hooks run per-session, so
# that is a fully independent event. Excluding the orchestrator's later,
# LLM-mediated echo of it loses no signal (PLAN.md Task 4.5).
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
    *sorted(SUBAGENT_DISPATCH_TOOL_NAMES),
)

# A Bash command naming any of these is INSPECTING recorded/pattern text —
# the ledger itself, or this handler's own source/tests (whose fixtures
# contain the trigger phrases) — not hitting a live budget. Without this
# guard, cat-ing the ledger re-fires the detector and appends a fresh entry:
# a self-feeding loop.
_SELF_REFERENTIAL_COMMAND_MARKERS: Final[tuple[str, ...]] = (
    "budget-exhaustion-events.jsonl",
    "budget_exhaustion_detector",
    # The same handler under its other spelling. Registries, playbooks and
    # generated reports name handlers by CLASS, so a marker list that knows
    # only the module path misses every one of them.
    "BudgetExhaustionDetector",
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
    # A generated report is the sharpest case: it prints this handler's own
    # acceptance blocks, one of which quotes the refusal sentence verbatim
    # because that is precisely what the block simulates. So the detector fired
    # on its own test fixture, and named the class while doing it.
    "BudgetExhaustionDetector",
    # Belt-and-braces alongside the structural JSON-shape check below
    # (`_strip_ledger_records`): this is the ledger's own record key, which a
    # genuine harness budget message -- prose, never JSON in this handler's
    # own record shape -- will never contain as a bare substring either.
    "matched_fragment",
)

# ─── Content-passthrough Bash commands ────────────────────────────────────────

# Utilities whose entire function is to REPRODUCE or losslessly filter/
# reformat bytes already sitting in a named source (a file, stdin) -- never to
# invoke a live service or generate new content. A Bash command is classified
# as content-passthrough when EVERY pipeline stage's leading verb is one of
# these (see `_is_content_passthrough_command`), which is why `curl | jq .`
# is correctly NOT passthrough: `curl` genuinely fetches live content, and one
# passthrough stage in a pipeline does not launder the others. Closed by
# definition (the semantic category "read/filter/reformat, cannot originate
# content"), not an open list of filenames or handler names to keep adding to.
_CONTENT_PASSTHROUGH_VERBS: Final[frozenset[str]] = frozenset(
    {
        "cat",
        "head",
        "tail",
        "less",
        "more",
        "grep",
        "egrep",
        "fgrep",
        "rg",
        "jq",
        "awk",
        "sed",
        "strings",
        "od",
        "xxd",
        "hexdump",
        "wc",
        "nl",
        "cut",
        "tac",
    }
)

# Longest-first so `&&`/`||` match whole before the single-character `&`/`|`
# variants claim the first character (mirrors shell_segmentation's own rule).
_PIPELINE_SEPARATORS: Final[tuple[str, ...]] = ("&&", "||", ";", "|", "&", "\n")


def _leading_verb(segment: str) -> str:
    """Return the command word a pipeline segment starts with, or "" if none."""
    stripped = segment.strip().lstrip("(){}")
    if not stripped:
        return ""
    return stripped.split(maxsplit=1)[0].rsplit("/", 1)[-1]


def _is_content_passthrough_command(command: str) -> bool:
    """True when every stage of ``command`` is a content-passthrough verb.

    Segments the command the same way the project's other Bash-shape
    handlers do (`shell_segmentation.split_unquoted`), so a separator sitting
    inside a quoted argument is never mistaken for a pipeline boundary. A
    command with no recognisable leading verb (empty, or one built by shell
    expansion) is conservatively NOT passthrough -- the safe direction is to
    leave it eligible for detection, never to grant an exemption a caller
    cannot justify.
    """
    segments = split_unquoted(command, _PIPELINE_SEPARATORS)
    found_verb = False
    for segment in segments:
        if not segment.strip():
            continue
        verb = _leading_verb(segment)
        if not verb or verb not in _CONTENT_PASSTHROUGH_VERBS:
            return False
        found_verb = True
    # An all-blank command (no verb found anywhere) is NOT passthrough -- a
    # vacuous "every segment passed" must not grant an exemption nothing
    # justified.
    return found_verb


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

# One declared name per ledger record field, reused by BOTH the writer
# (`_append_ledger_entry`) and the structural self-feed recognizer
# (`_strip_ledger_records`) -- a single source of truth for the ledger's own
# schema, so the two can never drift apart.
_LEDGER_TIMESTAMP_KEY: Final[str] = "timestamp"
_LEDGER_SESSION_ID_KEY: Final[str] = "session_id"
_LEDGER_TOOL_NAME_KEY: Final[str] = "tool_name"
_LEDGER_MATCHED_FRAGMENT_KEY: Final[str] = "matched_fragment"
_LEDGER_RECORD_KEYS: Final[frozenset[str]] = frozenset(
    {
        _LEDGER_TIMESTAMP_KEY,
        _LEDGER_SESSION_ID_KEY,
        _LEDGER_TOOL_NAME_KEY,
        _LEDGER_MATCHED_FRAGMENT_KEY,
    }
)


def _iter_balanced_json_objects(text: str) -> Iterator[str]:
    """Yield each top-level, brace-balanced ``{...}`` span in ``text``.

    String-aware: a ``{``/``}`` inside a JSON string value never affects
    depth. Deliberately a scanner, not a JSON parser -- callers still run
    ``json.loads`` on each yielded span and discard anything that fails to
    parse. This is what lets the ledger self-feed recognizer survive ``jq
    .``'s pretty-printing (a record spread across several lines is still one
    balanced span), where a per-line parse would not.
    """
    depth = 0
    start = -1
    in_string = False
    escape = False
    for index, char in enumerate(text):
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            if depth == 0:
                start = index
            depth += 1
        elif char == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start != -1:
                    yield text[start : index + 1]
                    start = -1


def _strip_ledger_records(text: str) -> str:
    """Remove any span of ``text`` that structurally IS this handler's own
    ledger record (F2, PLAN.md Task 1.4).

    A genuine harness-delivered budget message is prose from a tool
    integration -- it is never a JSON object carrying exactly this handler's
    own record key set, because nothing outside this module ever produces
    that shape. Recognising the SHAPE (parse + key-set check), not a keyword,
    is what survives `cat` (single-line JSONL), `jq .` (the same record
    reformatted across several lines) and any future reproduction that does
    not spell the ledger's filename.
    """
    result = text
    for candidate in _iter_balanced_json_objects(text):
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict) and parsed.keys() >= _LEDGER_RECORD_KEYS:
            result = result.replace(candidate, "", 1)
    return result


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
    tools (Read/Grep/Glob/Edit/Write/NotebookEdit) and dispatched sub-agent
    responses (Task/Agent) by default so file prose and a sub-agent's own
    composed report are never mistaken for a live exhaustion event. Two
    structural checks (a content-passthrough Bash command shape; the
    ledger's own JSON record shape) additionally exclude text that merely
    QUOTES a budget message rather than delivering one -- see the module
    docstring and
    ``CLAUDE/Plan/00319-supervisor-release-review-followups/BUDGET-DETECTOR-DESIGN.md``.
    Never blocks: on a match it ALLOWs with an advisory demanding prominent
    user-facing reporting, and appends one line to an untracked occurrence
    ledger.
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

    def _quoted_not_delivered(self, hook_input: dict[str, Any]) -> bool:
        """True when this event's ``tool_input.command`` structurally cannot
        be delivering a live budget signal.

        Two independent checks, both structural rather than keyword-based
        beyond the pre-existing literal marker list: a self-referential
        marker in the command text (unchanged), and a Bash command whose
        every pipeline stage is a content-passthrough verb (new -- see
        ``_is_content_passthrough_command``).
        """
        tool_input = hook_input.get(HookInputField.TOOL_INPUT)
        if not isinstance(tool_input, dict):
            return False
        command = tool_input.get("command")
        if not isinstance(command, str):
            return False
        if any(marker in command for marker in _SELF_REFERENTIAL_COMMAND_MARKERS):
            return True
        return _is_content_passthrough_command(command)

    def _prepared_response_text(self, hook_input: dict[str, Any]) -> str | None:
        """Return the response text eligible for pattern matching, or None.

        None means "structurally cannot be a delivered budget message" --
        either an excluded tool, a content-passthrough/self-referential
        command, or a response with nothing left after ledger-record spans
        (F2) and the literal self-referential response markers are removed.
        """
        tool_name = hook_input.get(HookInputField.TOOL_NAME)
        if tool_name in self._resolved_excluded_tools():
            return None
        if self._quoted_not_delivered(hook_input):
            return None
        tool_response = hook_input.get(HookInputField.TOOL_RESPONSE)
        text = _stringify_tool_response(tool_response)
        if not text:
            return None
        text = _strip_ledger_records(text)
        if not text:
            return None
        if any(marker in text for marker in _SELF_REFERENTIAL_RESPONSE_MARKERS):
            return None
        return text

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Return True if the tool response matches a budget-exhaustion pattern."""
        self._cached_fragment = None
        text = self._prepared_response_text(hook_input)
        if text is None:
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
        text = self._prepared_response_text(hook_input)
        if text is None:
            return None
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
                _LEDGER_TIMESTAMP_KEY: datetime.now(tz=UTC).isoformat(),
                _LEDGER_SESSION_ID_KEY: session_id,
                _LEDGER_TOOL_NAME_KEY: tool_name,
                _LEDGER_MATCHED_FRAGMENT_KEY: matched_fragment[:_MATCHED_FRAGMENT_TRUNCATE_LEN],
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
            "response is text a file merely CONTAINS, not a live exhaustion signal. "
            "Dispatched sub-agent responses (Task/Agent) are excluded too -- a "
            "sub-agent's final message is its own composed prose, never a field the "
            "Task/Agent tool populates from a budget check; a genuine hit during the "
            "sub-agent's own work already fires directly in its own session.\n\n"
            "**Quoted text never re-triggers this handler.** A Bash command whose "
            "every pipeline stage is a content-passthrough verb (`cat`, `grep`, "
            "`jq`, `tail`, ...) is excluded -- such a command only reproduces or "
            "reformats bytes that already exist, so `cat untracked/*.jsonl`, "
            "`jq . budget*.jsonl` or `grep ... playbook.md` never re-fire the "
            "advisory. Any text that structurally IS this handler's own ledger "
            "record (a JSON object carrying its record key set) is stripped before "
            "matching, which survives `jq .`'s reformatting. See "
            "`CLAUDE/Plan/00319-supervisor-release-review-followups/"
            "BUDGET-DETECTOR-DESIGN.md` for the full design.\n\n"
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
            "        excluded_tools: [Read, Grep, Glob, Edit, Write, NotebookEdit, Task, Agent]  # override\n"
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
                harness_cannot_produce=(
                    "This handler reads `tool_response`, and the whole input under "
                    "test IS that response — but a declared payload states only "
                    "`tool_name` and `tool_input`, and the harness fills "
                    '`tool_response` with a fixed `{"success": true}` because no '
                    "dispatchable handler had ever read it. Convertible by letting "
                    "a payload carry a `tool_response`, which is a harness "
                    "capability rather than a per-block fix. Covered by "
                    "tests/unit/handlers/post_tool_use/test_budget_exhaustion_detector.py."
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
                harness_cannot_produce=(
                    "Same `tool_response` gap as its sibling above, and convertible "
                    "with the same harness capability."
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
