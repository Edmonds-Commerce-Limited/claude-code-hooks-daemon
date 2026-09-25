"""BudgetExhaustionDetectorHandler - channel-scoped budget-exhaustion advisory.

Plan 00315 Task 2.1. Beyond the visible 5-hour/weekly usage limits, agent
sessions carry opaque operational budgets (a web-search budget, output-size
caps, and possibly others not yet catalogued) that surface only as mid-task
tool responses. `BUDGETS.md` (Plan 00315, Task 1.3 synthesis) found exactly
ONE field-confirmed shape: the web-search refusal. It also sketched a
"generic" budget/quota/limit-reached wording family as a hedge against
future, unconfirmed signals -- but that hedge was the recurring defect
magnet (Plan 00400 N4: a `ps` listing of this project's own source; Plan
00466 N46: a `git diff` showing an unrelated error-message string literal),
because free-text keyword matching cannot tell a delivered message from a
file merely discussing one. Removed for that reason (N46's remedy): this
handler now matches ONLY a signal's own CHANNEL (which tool) and SHAPE
(its verbatim wording), never scans arbitrary Bash stdout, and never
free-text-scans a keyword across a tool response whose channel it does not
recognise.

Matching scans the completed tool call's ``tool_response`` against
``_BUILTIN_SIGNALS``, currently two channel-scoped signals (N46 review 1,
MINOR-5 added the second):

  - the pinned web-search fragments ("Web search was not performed", "web
    search budget"), ONLY when ``tool_name == "WebSearch"``. The TEXT is
    field-confirmed (a real fixture); the CHANNEL is not independently
    field-confirmed from the same fixture -- it is documented in the
    vendored ``tools-reference.md`` ("Session search limit": capped
    WebSearch calls "return a notice"), which this handler treats as
    sufficient support without claiming a live re-verification it has not
    done.
  - ``Agent terminated early due to an API error: You've hit your (session|
    weekly) limit``, anchored at the START of the response and requiring the
    harness's stable ``(error type rate_limit, HTTP 429`` tail nearby (N46
    review 2, NIT-6), ONLY when ``tool_name`` is a sub-agent dispatch tool
    (``SUBAGENT_DISPATCH_TOOL_NAMES`` -- Task/Agent). This is the harness's
    own text for a dispatched sub-agent cut off mid-task by a usage-limit
    rejection -- caught live in this session's own transcripts (three
    reachable occurrences: two weekly-limit, one session-limit, all
    ``completed``-status dispatches whose ``tool_response.content`` is a
    list of text blocks), and previously undetected entirely (main excluded
    Task/Agent outright). A fourth, ``is_error: true`` occurrence is
    delivered as a bare string to ``PostToolUseFailure``, a DIFFERENT event
    this PostToolUse handler does not receive (N46 review 2, BLOCKER-1) --
    not handled here.

  **Foreground dispatches only.** Only a ``status: "completed"`` result
  carries ``content`` at all; an ``async_launched`` background dispatch or a
  ``teammate_spawned`` handoff (264 of 351 real Agent/Task results in the
  reviewing corpus) returns at launch and never delivers a later usage-limit
  death through PostToolUse -- there is no further PostToolUse event for
  that dispatch to carry it. Surfacing a BACKGROUND agent's death is Plan
  00470 Tasks 3.1/3.2 (the StopFailure and Notification handlers), a
  different channel entirely; this handler does not attempt it.

A project can declare additional signals via ``options.extra_patterns`` once
it has confirmed a real channel of its own (a CLI's own quota message
surfacing through Bash, for example); nothing here matches such a channel
automatically, because a structural marker that ordinary file content
cannot carry by accident -- not a keyword -- is what makes matching it
safe, and only the project configuring it can supply one for its own tool.

Deliberately NEVER keys on the configurable ceiling number (e.g. "200" of
"200 WebSearch calls") -- BUDGETS.md pins the ceiling as environment-variable
configurable (``CLAUDE_CODE_MAX_WEB_SEARCHES_PER_SESSION``), so a number
alone is not a stable signal and would false-fire on ordinary counts
("Found 200 results"). The harness's refusal wording may have moved since
the original fixture was captured (the fixture and this code both predate
the current vendored doc's env-var name); a follow-up should re-verify the
notice wording against a live session.

**Precision**: by default, Read/Grep/Glob/Edit/Write/NotebookEdit/Bash tool
responses are excluded from matching (``options.excluded_tools``) --
Task/Agent are deliberately NOT excluded; see below. The first six return
FILE CONTENTS the model merely read, or authored -- prose that happens to
discuss budget exhaustion (this very docstring, for instance) is not a live
exhaustion event. Bash's ``tool_response`` is the model's OWN invoked
command's stdout/stderr: the same class of free-form, model-directed
content as a file's own text. No BUILT-IN signal's confirmed channel is
Bash (the one documented harness-written Bash artefact, BUDGETS.md's
``<persisted-output>`` output-size marker, is a DIFFERENT signal this
handler does not implement), so nothing Bash prints can match one; a
verb-by-verb allowlist of "safe" commands (cat/grep/git/...) is not needed
to reach that guarantee and previously kept needing a new entry per false
positive.

Task/Agent are NOT excluded, because their ``tool_response`` genuinely IS
sometimes a field the harness itself populates -- the Agent-terminated-early
signal above. The honest reason a dispatched sub-agent's ORDINARY composed
prose never fires is not that the harness never writes there; it is that
free LLM-composed prose is (a) never channel-scoped to a signal it does not
own, and (b) exceedingly unlikely to independently OPEN with another
signal's exact anchored sentence merely while discussing or quoting it (see
``TestSubagentDispatchReportNeverFires`` / ``TestAgentTerminatedEarlySignal``
mid-response quoting case). If the sub-agent's own work genuinely hits a
DIFFERENT budget mid-task, that already fires directly in the sub-agent's
own session, at the tool call that hit it, so nothing is lost by not
re-scanning the orchestrator's later echo of it for THAT signal.

Beyond the channel gate, two STRUCTURAL checks
(not keyword lists) keep the detector from self-triggering on text that
merely QUOTES a budget message rather than delivering one:

  - any span of ``tool_response`` text that parses as a JSON object carrying
    this handler's own ledger record key set (``_LEDGER_RECORD_KEYS``) is
    stripped before matching runs, because a genuine harness budget message
    is prose, never JSON in this handler's own record shape. This survives
    ``jq``'s pretty-printing, which defeats a literal-substring or
    per-line-JSON check.
  - a literal ``_SELF_REFERENTIAL_RESPONSE_MARKERS`` check on the response
    text catches a *generated report* that names this handler by class or
    module (a playbook dump, a CHANGELOG entry) -- documentation ABOUT the
    feature, never a live signal.

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
from dataclasses import dataclass
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
    # N46 (Plan 00466 ledger 16): Bash's tool_response is the model's OWN
    # invoked command's stdout/stderr -- free-form content that can be
    # ANYTHING (a diff, a log, a source file, a live fetch), the same class
    # as a file the model merely read. No tool the harness itself
    # rate/quota-limits is reached by running a shell command, so nothing
    # Bash prints is this handler's confirmed channel; a verb-by-verb
    # allowlist of "safe" commands (cat/grep/git/...) keeps needing a new
    # entry per false positive instead of closing the class. A project that
    # has confirmed its OWN CLI reports a genuine quota signal through Bash
    # can re-include "Bash" via `options.excluded_tools` and pair it with an
    # `extra_patterns` regex specific enough not to match ordinary output.
    "Bash",
    # Task and Agent (SUBAGENT_DISPATCH_TOOL_NAMES) are deliberately NOT
    # here (N46 review 1, MINOR-5). Their tool_response IS sometimes a field
    # the harness itself populates: a dispatched sub-agent cut off mid-task
    # by a usage-limit rejection writes the harness's own sentence into its
    # tool_result. A blanket exclusion would drop that real signal (this is
    # what main did, and what this session's own transcripts caught it
    # missing). Precision instead comes from the channel-scoped, anchored
    # `_AGENT_TERMINATED_EARLY_RE` signal below: it only matches Task/Agent,
    # and only at the very START of the response, so a sub-agent's own
    # composed prose that merely QUOTES the sentence mid-response -- the
    # same risk `_SELF_REFERENTIAL_RESPONSE_MARKERS` guards against for
    # everything else -- still cannot match.
)

# A literal marker on the tool RESPONSE text: a payload that names this
# handler or its ledger is documentation ABOUT the feature -- the CHANGELOG
# entry, BUDGETS.md, the release notes, a generated playbook -- not a live
# budget signal. Observed live while reading this repo's own changelog
# during the v3.60.0 release. Safe because a genuine harness budget message
# never names the detector or its ledger.
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

# ─── Channel-scoped signals ────────────────────────────────────────────────────

# Pinned, verbatim-derived fragments from the field-confirmed web-search
# budget refusal TEXT (BUDGETS.md's fixture). Never the ceiling number ("200
# of 200") -- that count is configurable via
# CLAUDE_CODE_MAX_WEB_SEARCHES_PER_SESSION and is not a stable trigger on
# its own.
_WEB_SEARCH_BUDGET_RE: Final[re.Pattern[str]] = re.compile(
    r"Web search was not performed|web search budget",
    re.IGNORECASE,
)

# The harness's own sentence for a dispatched sub-agent terminated mid-task
# by a usage-limit API rejection (N46 review 1, MINOR-5) -- caught live in
# this session's transcripts, verbatim. Anchored at the response's START
# (`\A`) so a sub-agent's OWN composed prose merely quoting or discussing
# the sentence mid-response cannot match -- the anchor is the structural
# marker that lets this channel stay UNEXCLUDED (see _DEFAULT_EXCLUDED_TOOLS)
# without reopening the free-text-quoting risk the exclusion existed to
# avoid. "session" and "weekly" are the two limit kinds observed; the
# resets-at clause, error type and request id are deliberately NOT part of
# the anchor (they vary per occurrence).
# N46 review 2, NIT-6: the anchor alone still let a report that OPENS with
# the bare sentence and nothing else fire, so a bounded lookahead requires
# the harness's own stable tail (the rate-limit error-type clause) to appear
# nearby too -- a structural marker that a bare quote of the opening clause
# alone does not carry.
_AGENT_TERMINATED_EARLY_RE: Final[re.Pattern[str]] = re.compile(
    r"\A\s*Agent terminated early due to an API error: You've hit your "
    r"(?:session|weekly) limit(?=.{0,300}?\(error type rate_limit, HTTP 429)",
    re.DOTALL,
)


@dataclass(frozen=True, slots=True)
class _Signal:
    """A budget-exhaustion signal: the tool CHANNEL it arrives through, paired
    with its verbatim SHAPE (N46, Plan 00466 ledger 16).

    A signal is matched ONLY when the event's ``tool_name`` is one of
    ``tool_names`` -- never scanned against every tool's response the way a
    bare keyword list was. This is what makes a diff, a log or a file's own
    prose structurally unable to trigger a signal that only ever arrives
    through a different tool: the CHANNEL check runs before the pattern ever
    sees the text, rather than trying to guess from the text's shape alone.
    """

    tool_names: frozenset[str]
    pattern: re.Pattern[str]


# The WebSearch tool's own tool_response, replaced verbatim by the harness
# when the session's web-search budget is exhausted (BUDGETS.md fixture; the
# CHANNEL is documented, not independently field-confirmed -- see the module
# docstring). A prior "generic" family (budget/quota/limit-reached wording,
# matched against ANY non-excluded tool's response) was removed here: it had
# no confirmed channel, and was the repeat false-positive source (Plan
# 00400 N4 via `ps`; N46 via `git diff`) precisely because a keyword cannot
# tell a delivered message from a file that merely discusses one.
#
# A dispatched sub-agent's own tool_response, when the harness itself cuts
# the sub-agent off mid-task on a usage limit (N46 review 1, MINOR-5) --
# see `_AGENT_TERMINATED_EARLY_RE` for the anchoring rationale.
#
# A project that confirms a genuine further channel (its own CLI reporting
# a quota through Bash, say) declares it via ``options.extra_patterns`` --
# see the module docstring for why that must carry a structural marker, not
# a keyword, if it is ever pointed at Bash.
_BUILTIN_SIGNALS: Final[tuple[_Signal, ...]] = (
    _Signal(frozenset({"WebSearch"}), _WEB_SEARCH_BUDGET_RE),
    _Signal(frozenset(SUBAGENT_DISPATCH_TOOL_NAMES), _AGENT_TERMINATED_EARLY_RE),
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


def _join_text_blocks(blocks: list[Any]) -> str:
    """Join the ``text`` of each ``{"type": "text", ...}`` block, in order.

    N46 review 2, BLOCKER-1: this is the DOCUMENTED/observed ``completed``
    PostToolUse:Agent ``tool_response.content`` shape (hooks.md:1775-1787,
    ``[{"type": "text", "text": "..."}]``) -- every real ``completed``
    occurrence in the corpus used it, and the prior string-only read of
    ``content`` never matched any of them. A non-text block (there is none
    documented today, but the harness may add one) is skipped rather than
    stringified, so nothing but the sub-agent's own composed text ever
    reaches the anchor.
    """
    return "\n".join(
        block["text"]
        for block in blocks
        if isinstance(block, dict)
        and block.get("type") == "text"
        and isinstance(block.get("text"), str)
    )


def _stringify_tool_response(tool_name: str, tool_response: Any) -> str:
    """Return a searchable string form of ``tool_response``.

    ``tool_response`` shape varies by tool (a dict with stdout/stderr for
    Bash, a dict with a ``content`` string for WebSearch, a dict with a
    ``content`` LIST of text blocks for a completed Task/Agent dispatch, a
    bare string for some tools). A dict's own ``content`` field, when it is a
    string, is returned directly -- that IS the actual message text a tool
    integration composed, which is what lets an ANCHORED signal
    (`_AGENT_TERMINATED_EARLY_RE`) match at the message's true start rather
    than at a JSON envelope's literal ``{"content": "`` prefix. When
    ``content`` is a list, its text blocks are joined (`_join_text_blocks`) --
    the same true-start guarantee, for the shape a real dispatch actually
    uses.

    For a sub-agent dispatch tool (``SUBAGENT_DISPATCH_TOOL_NAMES``) whose
    ``tool_response`` carries no ``content`` at all (an ``async_launched``
    background dispatch, or a ``teammate_spawned`` handoff -- 264 of 351 real
    occurrences), this deliberately returns "" rather than falling back to
    JSON-serialising the whole dict: that dict's other fields are the
    orchestrator's own dispatch BRIEF (``prompt``) and run telemetry, never a
    harness-delivered message, and scanning them would let an admin's
    ``extra_patterns`` fire on the brief's own wording (N46 review 2,
    MINOR-3) rather than the sub-agent's reported text. Any other shape
    falls back to JSON-serialising the whole value (falling back further to
    ``str()`` for anything non-serialisable), which still gives one text
    blob a non-anchored pattern can search anywhere in -- unchanged for
    every non-dispatch tool.
    """
    if isinstance(tool_response, str):
        return tool_response
    if isinstance(tool_response, dict):
        content = tool_response.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return _join_text_blocks(content)
        if tool_name in SUBAGENT_DISPATCH_TOOL_NAMES:
            return ""
    try:
        return json.dumps(tool_response, default=str)
    except (TypeError, ValueError):
        return str(tool_response)


# A format placeholder that was never substituted: `{name}`, `{name:spec}`,
# `{name!r}`, or shell `${NAME}`. A RENDERED runtime message always has its
# placeholders filled in, so one still sitting in the text proves the span is
# SOURCE CODE rather than a delivered signal (Plan 00400 N4 — a `ps` listing
# surfaced a hook wrapper's own f-string and the detector demanded a bold
# user-facing banner for a budget nothing had hit).
#
# Deliberately anchored on an IDENTIFIER immediately inside the brace, so a real
# signal delivered as JSON (`{"error": "quota exceeded"}`) is never mistaken for
# a placeholder — that opens with a quote, not an identifier.
_UNRENDERED_PLACEHOLDER_RE: Final[re.Pattern[str]] = re.compile(
    r"\$?\{[A-Za-z_][A-Za-z0-9_.]*(?:\[[^\]]*\])?(?:![rsa])?(?::[^{}]*)?\}"
)


def _find_matched_fragment(
    tool_name: str, text: str, extra_patterns: list[re.Pattern[str]]
) -> str | None:
    """Return the first matched fragment's own text, or None if no pattern hits.

    Channel-scoped (N46, Plan 00466 ledger 16): a builtin signal's pattern is
    only even considered when ``tool_name`` is one of that signal's declared
    ``tool_names`` -- a WebSearch-shaped fragment appearing in, say, a Bash
    response can never match, because Bash never reaches this loop for any
    builtin signal in the first place. ``extra_patterns`` stay tool-agnostic
    (an admin-declared regex applies to whichever tools are not excluded),
    since that is an explicit opt-in the admin authors and scopes themselves.

    A match on a LINE that still carries an unexpanded format placeholder is
    source code, not a delivered message, so it is skipped and scanning
    continues — a genuine signal elsewhere in the same text is still found.

    The window is the whole line, not the matched span: a template often holds
    the placeholder just OUTSIDE the phrase that matched (`quota exceeded for
    {resource}` matches only `quota exceeded`), so a span-scoped test misses
    exactly the shapes it exists to catch. Judging TEXT rather than the command
    also covers source surfaced by `cat`, a heredoc echo, or a stack trace.
    """
    channel_patterns = (
        signal.pattern for signal in _BUILTIN_SIGNALS if tool_name in signal.tool_names
    )
    for pattern in (*channel_patterns, *extra_patterns):
        for match in pattern.finditer(text):
            if _UNRENDERED_PLACEHOLDER_RE.search(_line_around(text, match.start(), match.end())):
                continue
            return match.group(0)
    return None


def _line_around(text: str, start: int, end: int) -> str:
    """The full line(s) spanning ``text[start:end]``, used as the placeholder window."""
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end)
    return text[line_start:] if line_end == -1 else text[line_start:line_end]


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


def dispatch_identity(tool_input: Any, tool_response: Any) -> str:
    """A human-readable identity for a Task/Agent dispatch.

    N46 review 2, MINOR-4: ``name`` -- the handle a re-brief via SendMessage
    needs, and set on 243 of 351 real Agent/Task calls in the corpus -- is
    tried FIRST, ahead of ``description``/``subagent_type`` (the fields this
    project's own dispatch tooling, ``dispatch_declaration.py``, reads for
    the same purpose but without a re-brief handle to prefer). If
    ``tool_input`` names nothing at all, the ``tool_response``'s own
    ``agentId`` (present on every real ``completed``/``async_launched``
    shape) is the last identifying fallback before "an unnamed dispatch".

    Public (no leading underscore): the PostToolUseFailure sibling signal,
    ``agent_terminated_early_detector`` (N46 review 2's follow-up), imports
    this directly rather than duplicating it -- the same cross-event-package
    reuse shape as ``recovery_cron_advisor``'s ``declares_failsafe_cron``."""
    if isinstance(tool_input, dict):
        for key in ("name", "description", "subagent_type"):
            value = tool_input.get(key)
            if isinstance(value, str) and value:
                return value
    if isinstance(tool_response, dict):
        agent_id = tool_response.get("agentId")
        if isinstance(agent_id, str) and agent_id:
            return agent_id
    return "an unnamed dispatch"


def _agent_terminated_advisory(
    tool_name: str, tool_input: Any, tool_response: Any, matched_fragment: str
) -> str:
    """Build the advisory for a dispatched sub-agent the harness cut off on
    a usage limit (N46 review 1, MINOR-5) -- names WHICH agent died and
    demands a re-brief, since its work is incomplete and silently treating
    the dispatch as done loses the assignment."""
    identity = dispatch_identity(tool_input, tool_response)
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


class BudgetExhaustionDetectorHandler(PostToolUseHandlerBase):
    """Advisory PostToolUse handler that flags budget-exhaustion messaging.

    Channel-scoped (never a bare keyword scan): each builtin signal is a
    (tool(s), verbatim shape) pair, matched only against the tool(s) it can
    genuinely arrive from -- WebSearch's documented refusal text (BUDGETS.md
    fixture), and a dispatched sub-agent's own usage-limit termination
    (Task/Agent -- N46 review 1, MINOR-5). Excludes file-content tools
    (Read/Grep/Glob/Edit/Write/NotebookEdit) and Bash (its response is the
    model's own invoked command output, never a harness-populated field) by
    default so file prose and arbitrary shell output are never mistaken for
    a live exhaustion event. Task/Agent are deliberately NOT excluded: their
    tool_response genuinely can carry a harness-written signal, and the
    Agent-terminated-early signal's own anchor (not a tool exclusion) is
    what keeps a sub-agent's ordinary composed prose from matching. That
    signal covers FOREGROUND dispatches only -- a background/teammate
    dispatch returns before any later limit hits, so its death never reaches
    PostToolUse at all; see Plan 00470 Tasks 3.1/3.2 for that separate
    channel. A structural ledger-record-shape check additionally excludes
    text that merely QUOTES a budget message rather than delivering one --
    see the module docstring. Never blocks: on a match it ALLOWs with an
    advisory demanding prominent user-facing reporting, and appends one line
    to an untracked occurrence ledger.
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
        # by the registry after __init__ runs). Safe to cache: derived only
        # from config options, which are stable for the handler's lifetime --
        # unlike a per-event match result (see `_matched_fragment`), nothing
        # about a compiled pattern varies by which event is in flight.
        self._compiled_extra_patterns: list[re.Pattern[str]] | None = None

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

    def _prepared_response_text(self, hook_input: dict[str, Any]) -> str | None:
        """Return the response text eligible for pattern matching, or None.

        None means "structurally cannot be a delivered budget message" --
        either an excluded tool, or a response with nothing left after
        ledger-record spans (F2) and the literal self-referential response
        markers are removed.
        """
        tool_name = hook_input.get(HookInputField.TOOL_NAME)
        if tool_name in self._resolved_excluded_tools():
            return None
        tool_response = hook_input.get(HookInputField.TOOL_RESPONSE)
        text = _stringify_tool_response(str(tool_name or ""), tool_response)
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
        return self._matched_fragment(hook_input) is not None

    def _matched_fragment(self, hook_input: dict[str, Any]) -> str | None:
        """Return the matched fragment for THIS event's tool response, or None.

        Plan 00319 F10: deliberately NOT cached on ``self``. The daemon shares
        one handler instance across events, dispatching concurrently on an
        executor pool (``daemon/server.py``'s ``run_in_executor``), so a
        result stashed here by one event's ``matches()`` could be read back by
        a DIFFERENT event's ``handle()`` if the two interleave -- a genuine
        cross-session leak. This re-derives the fragment purely from
        ``hook_input``, so ``matches()`` and ``handle()`` each get THEIR OWN
        event's answer, at the cost of one extra cheap regex scan on the rare
        path where a real match already fired ``matches()``.
        """
        text = self._prepared_response_text(hook_input)
        if text is None:
            return None
        tool_name = str(hook_input.get(HookInputField.TOOL_NAME) or "")
        return _find_matched_fragment(tool_name, text, self._resolved_extra_patterns())

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
        fragment = self._matched_fragment(hook_input)
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

        if tool_name in SUBAGENT_DISPATCH_TOOL_NAMES:
            advisory_text = _agent_terminated_advisory(
                tool_name,
                hook_input.get(HookInputField.TOOL_INPUT),
                hook_input.get(HookInputField.TOOL_RESPONSE),
                fragment,
            )
        else:
            advisory_text = _advisory(tool_name, fragment)

        return BlockingResult(decision=Decision.ALLOW, context=[advisory_text])

    def get_claude_md(self) -> str | None:
        """Return CLAUDE.md guidance about this handler."""
        return (
            "## budget_exhaustion_detector — hidden agent budgets are surfaced\n\n"
            "Beyond the visible 5-hour/weekly usage limits, sessions carry opaque "
            "operational budgets (e.g. a per-session web-search budget) that surface "
            "only as mid-task tool responses, with no upfront warning. A PostToolUse "
            "advisory matches each completed tool call's response against a "
            "CHANNEL-SCOPED signal -- currently two: the WebSearch tool's own "
            "budget-refusal text, and a dispatched sub-agent's own usage-limit "
            "termination on Task/Agent -- and, when it matches, tells you to report "
            "it.\n\n"
            "**When this fires: report it prominently, immediately, and do not "
            "silently retry or degrade.** Lead your next user-facing message with a "
            "bold banner naming the budget, state what you were attempting and what "
            "work is now affected, and stop hammering the exhausted tool. For a "
            "died sub-agent specifically: name WHICH dispatch died, and re-brief the "
            "same assignment to a fresh dispatch once the limit resets -- its output "
            "is partial, not a completed result.\n\n"
            "**The sub-agent signal covers FOREGROUND dispatches only.** A "
            "background/teammate dispatch (`async_launched`/`teammate_spawned`) "
            "returns at launch and delivers no later PostToolUse event, so a usage "
            "limit that kills it mid-task never reaches this handler at all -- "
            "surfacing that is Plan 00470 Tasks 3.1/3.2 (the StopFailure and "
            "Notification handlers), a different channel this handler does not "
            "attempt.\n\n"
            "**No arbitrary Bash stdout is ever scanned.** A signal is matched only "
            "against the tool(s) it is documented/confirmed to arrive from -- never "
            "a bare keyword scanned across any tool's response. File-content tools "
            "(Read/Grep/Glob/Edit/Write/NotebookEdit) and Bash are excluded by "
            "default: Bash's response is the model's own invoked command output (a "
            "diff, a log, a live fetch), the same free-form class as a file's own "
            "text, and no BUILT-IN signal's channel is Bash (Plan 00466 N46 -- an "
            "earlier generic keyword family false-fired on a `git diff` merely "
            "quoting budget-adjacent wording; removed rather than patched "
            "verb-by-verb). **Task/Agent are deliberately NOT excluded** (N46 "
            "review 1): their tool_response genuinely can carry a harness-written "
            "signal (the usage-limit termination above), caught live in this "
            "project's own transcripts. A sub-agent's ORDINARY composed prose does "
            "not fire because the signal is anchored at the response's very START, "
            "not because the tool is excluded -- prose that merely quotes or "
            "discusses the phrase mid-response cannot match.\n\n"
            "**Quoted text never re-triggers this handler.** Any text that "
            "structurally IS this handler's own ledger record (a JSON object "
            "carrying its record key set) is stripped before matching, which "
            "survives `jq .`'s reformatting. A literal marker naming this handler "
            "or its ledger (a CHANGELOG entry, a generated playbook) is excluded "
            "too. See "
            "`CLAUDE/Plan/00319-supervisor-release-review-followups/"
            "BUDGET-DETECTOR-DESIGN.md` for the original design and "
            "`CLAUDE/Plan/00466-niggles-ledger-sixteen/NIGGLES.md` (N46) for why "
            "the generic keyword family was removed and the Agent-terminated-early "
            "signal was added.\n\n"
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
            "        excluded_tools: [Read, Grep, Glob, Edit, Write, NotebookEdit, Bash]  # override\n"
            "                                              # (Task/Agent are NOT excluded by default)\n"
            "        extra_patterns: []                   # extra regexes, additive; tool-agnostic\n"
            "                                              # among non-excluded tools -- if you point\n"
            "                                              # one at Bash (by removing it from\n"
            "                                              # excluded_tools), write a pattern specific\n"
            "                                              # enough that ordinary output cannot match it\n"
            "                                              # by accident, not a bare keyword.\n"
            "```\n"
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests: an advisory probe and a Bash-exclusion allow."""
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
                title="A Bash tool response is never scanned, even quoting the exact refusal",
                command=(
                    "Simulate a Bash tool response containing the text 'Web search "
                    "was not performed: this session has used its web search budget "
                    "(200 of 200 WebSearch calls).'"
                ),
                harness_cannot_produce=(
                    "Same `tool_response` gap as its sibling above, and convertible "
                    "with the same harness capability."
                ),
                description=(
                    "Bash is excluded by default: its response is the model's own "
                    "invoked command output, never the WebSearch tool's own "
                    "harness-populated field, so no advisory fires even when the "
                    "text is the pinned refusal fragment verbatim (e.g. a diff or a "
                    "log quoting it)."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Synthetic tool_response text only; no live tool call is made.",
                test_type=TestType.ADVISORY,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="A dispatched sub-agent cut off by a usage limit triggers a re-brief advisory",
                command=(
                    "Simulate an Agent tool response containing the text 'Agent "
                    "terminated early due to an API error: You've hit your weekly "
                    "limit · resets Sep 27, 8am (UTC) (error type rate_limit, HTTP "
                    "429, request id req_example, model claude-sonnet-5).'"
                ),
                harness_cannot_produce=(
                    "Same `tool_response` gap as its siblings above, and "
                    "convertible with the same harness capability."
                ),
                description=(
                    "N46 review 1, MINOR-5 (real shape fixed by N46 review 2, "
                    "BLOCKER-1: the documented `tool_response.content` is a LIST "
                    "of text blocks, not a bare string): the harness's own "
                    "usage-limit termination sentence, anchored at the first "
                    "text block's start, triggers an advisory naming the "
                    "dispatch and demanding a re-brief once the limit resets. "
                    "Foreground dispatches only -- see the module docstring."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[
                    r"SUB-AGENT DIED",
                    r"🚨",
                    r"re-brief",
                ],
                safety_notes="Synthetic tool_response text only; no live tool call is made.",
                test_type=TestType.ADVISORY,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=False,
            ),
        ]
