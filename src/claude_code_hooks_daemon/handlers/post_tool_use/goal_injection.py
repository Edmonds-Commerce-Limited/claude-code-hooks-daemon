"""GoalInjectionHandler - plan-execution-start goal-intent signal (Plan 00269).

PostToolUse sensor half of the supervisor `/goal` injection feature. When a
``PLAN.md`` Write/Edit under the active plan directory results in a
``**Status**:`` line reading ``In Progress``, this handler renders the
configured goal lines (config paradigm mirrors ``command_hints``:
``mode: additive|replace`` with per-``id`` override), joins them into ONE
physical line, and atomically writes a ``<session>.goal-intent`` signal file
into the context-sidecar directory. The standalone ccy PTY supervisor (the
actuator) consumes the signal and types ``/goal 🤖 [ccy-supervisor] ...``
into the foreground chat, subject to every existing injection rail.

Safety model (PLAN.md Decisions 2 and 3):

- The payload is ONE physical line — the logical-line cap applies pre-join,
  the joined line is length-capped, and control characters (newlines above
  all) never survive rendering. The supervisor independently re-validates.
- The fixed ``header`` line (machine-origin marker + "NOT human
  authorisation" clause) is not overridable and not removable, even in
  ``replace`` mode.
- Authorisation-flavoured built-in lines ship DISABLED and their vetted text
  points at the project's recorded ``standing_authorisations`` config rather
  than asserting fresh consent; enabling one is the same deliberate
  repository-owner act as enabling a standing authorisation entry.

Trigger semantics are TRANSITION-based (ledger 00466 N3): the handler fires
only when THIS Write/Edit is what moved the Status line INTO a target
classification -- into In Progress for the flip signal, into a terminal
status for the retirement refresh -- never merely because the post-write
file happens to already read that way. Both directions share one
reconstruction (``_is_real_transition``): an Edit's pre-edit text is
recovered by reversing this edit against the post-edit text already on
disk and parsed with the same fenced-block-aware parser
(:class:`plan_qa.model.PlanDoc`) the post-state check uses, trying every
occurrence of the replaced text as a candidate edit site and reporting a
transition only when every surviving candidate agrees (a bare value like
"In Progress" can otherwise collide with unrelated text -- a table cell, a
title, a fenced example -- and reconstruct the WRONG span). A Write has
already landed on disk by the time PostToolUse runs, so there is no
unmodified copy left to diff against; the file's content at git HEAD
(``utils.git_facts.project_relative_head_text``, read from the file's OWN
enclosing repository) stands in for "before" instead, narrowed further for
the in-progress flip by the ledger itself (a Write's git-HEAD signal can lag
an uncommitted flip that already landed on disk and in the ledger). The
once-per-plan-per-session latch (in-memory) still applies on top of the
transition check and still resets per session.

**A resumed session still gets its goal back**, restoring Plan 00269 Task
2.1's original intent without reintroducing N3's over-firing: a non-flip
touch of an already-ledgered plan ADDS this session to the plan's live
ledger entry (``GoalLedger.reassert_session`` -- additive, never a transfer)
and writes this session's own signal (``_maybe_reassert_for_new_session``),
gated by an in-memory ``(session_id, plan_number)`` latch that resets every
daemon lifetime -- not by whether the persisted ledger has ever heard of
this session, so a SAME-session-id resume (Claude Code's ``--resume``/
``--continue``) gets answered even though its OWN earlier real flip is
exactly what ledgered the plan in the first place. A session that already
real-flipped a DIFFERENT plan of its own does not implicitly absorb an
unrelated plan it merely happens to touch. A completing write is likewise
detected via the persisted ledger, not the in-memory latch, so it survives a
daemon restart too (``_maybe_refresh_on_retirement``) -- and refreshes EVERY
session the ledger currently answers as an owner (the plan's live entry, or
else its most recently retired one), since ownership is additive rather than
a single value one session can quietly lose.

**Multi-plan combined signal (Plan 00299)**: the upstream `/goal` slot is a
single, last-writer-wins value, so under concurrent plans the goal ledger
(``goal_ledger.GoalLedger``, per plan number with a ``sessions`` set of
every owner) is the SOURCE OF TRUTH, and the signal this handler writes is a
RENDERED VIEW of every still-live ledgered plan for the session
(``render_combined_goal_line``): one live plan renders byte-for-byte
identically to the pre-00299 single-plan text; two or more render one
combined work line naming every live plan number. A session becomes an
owner of every plan its OWN combined text names this way, not only the one
that triggered the write, so a plan it never directly touched still
refreshes correctly when it later reaches a terminal status. A plan
reaching a terminal status re-renders the signal ONCE and writes it to
every owning session (``_maybe_refresh_on_retirement``), without disturbing
any other still-live plan's contribution. The supervisor's own thrash guard
(``last_goal_text``) skips re-typing an unchanged combined `/goal`.

Full defect history and review write-ups: ``CLAUDE/Plan/00466-niggles-
ledger-sixteen/NIGGLES.md`` (N3).

Opt-in (``get_default_enabled() -> False``); never blocks.
"""

import json
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar, Final

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, HookInputField, Priority
from claude_code_hooks_daemon.constants.tools import ToolName
from claude_code_hooks_daemon.core import BlockingResult, Decision
from claude_code_hooks_daemon.core.handler import WorkspaceScope
from claude_code_hooks_daemon.core.handler_bases import PostToolUseHandlerBase
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.core.relevance import Relevance, RelevanceContext
from claude_code_hooks_daemon.core.utils import get_file_path
from claude_code_hooks_daemon.plan_qa.model import TERMINAL_STATUSES, PlanDoc, PlanStatus
from claude_code_hooks_daemon.utils.ccy_supervisor import supervisor_relevance
from claude_code_hooks_daemon.utils.git_facts import project_relative_head_text
from claude_code_hooks_daemon.utils.goal_ledger import LEDGER_FILENAME, GoalLedger, LivePlanRef
from claude_code_hooks_daemon.utils.markdown_fences import line_spans_outside_fences
from claude_code_hooks_daemon.utils.plan_status_snapshot import plan_status_snapshots
from claude_code_hooks_daemon.utils.plan_trigger import PlanUnreadable
from claude_code_hooks_daemon.utils.plan_trigger import (
    is_inside_project as _plan_trigger_is_inside_project,
)
from claude_code_hooks_daemon.utils.plan_trigger import (
    plan_dir_for as _plan_trigger_plan_dir_for,
)
from claude_code_hooks_daemon.utils.plan_trigger import (
    plan_path_pattern as _plan_trigger_plan_path_pattern,
)
from claude_code_hooks_daemon.utils.temp_names import unique_temp_path

logger = logging.getLogger(__name__)

# ── Goal ledger + displacement advisory (Plan 00276) ───────────────────────
# The /goal slot is last-writer-wins upstream; the ledger remembers every
# emission so a displaced-but-unfinished plan is never silently forgotten.
_DISPLACEMENT_ADVISORY_TEMPLATE: Final[str] = (
    "⚠️ GOAL DISPLACED: the /goal slot is last-writer-wins, so any live /goal "
    "condition for Plan(s) {plans} is now superseded by Plan {new_plan}'s "
    "goal (a displaced condition set in an earlier session was already gone), "
    "but {verb} still In Progress. "
    "Claude Code's /goal slot holds only ONE condition (last writer wins); the "
    "daemon's goal ledger still tracks the displaced plan(s) — their work "
    "remains owed and the Stop hook will keep challenging stops on their "
    "behalf until they reach a terminal status."
)

# ── Signal transport (same family as <session>.compacting) ─────────────────
_SIGNAL_SUBDIR: Final[str] = "context-sidecar"
# Deliberately NOT ``.json`` so the supervisor's sidecar reader never
# mistakes a goal signal for a context sidecar.
_SIGNAL_SUFFIX: Final[str] = ".goal-intent"
# Plan 00321: retraction gets its own signal, whose PRESENCE is the whole
# message. The supervisor types the fixed literal `/goal clear` and reads no
# text out of this file, so a forged one can only ever clear a goal — it can
# never inject instruction text the way a widened .goal-intent validator could.
_CLEAR_SUFFIX: Final[str] = ".goal-clear"
_SESSION_ID_FALLBACK: Final[str] = "unknown"
_UNSAFE_SESSION_CHARS: Final[re.Pattern[str]] = re.compile(r"[^A-Za-z0-9_.-]")

# ── Signal payload fields (Task 1.2 schema) ────────────────────────────────
_FIELD_TS: Final[str] = "ts"
_FIELD_SESSION_ID: Final[str] = "session_id"
_FIELD_PLAN_NUMBER: Final[str] = "plan_number"
_FIELD_RENDERED_LINES: Final[str] = "rendered_lines"
_FIELD_SOURCE: Final[str] = "source"
_SOURCE_STATUS_FLIP: Final[str] = "status-flip"
_SOURCE_CLI: Final[str] = "cli"

# ── Rendering caps (Decision 2 corollary; supervisor re-validates) ─────────
_LOGICAL_LINE_SEPARATOR: Final[str] = " — "
_MAX_LOGICAL_LINES: Final[int] = 8
_MAX_JOINED_CHARS: Final[int] = 500
_MAX_TITLE_CHARS: Final[int] = 120

# ── Config keys (mirrors command_hints) ────────────────────────────────────
_KEY_ID: Final[str] = "id"
_KEY_TEXT: Final[str] = "text"
_KEY_ENABLED: Final[str] = "enabled"
_MODE_ADDITIVE: Final[str] = "additive"
_MODE_REPLACE: Final[str] = "replace"
_DEFAULT_MODE: Final[str] = _MODE_ADDITIVE

# ── Placeholder vocabulary (closed set; unknown tokens skip the line) ──────
_PLACEHOLDER_PLAN_NUMBER: Final[str] = "plan_number"
_PLACEHOLDER_PLAN_TITLE: Final[str] = "plan_title"
_PLACEHOLDER_PLAN_PATH: Final[str] = "plan_path"
_PLACEHOLDER_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"\{([a-z_]+)\}")
_PLAN_NUMBER_RE: Final[re.Pattern[str]] = re.compile(r"^\d{5}$")

# ── Built-in line set (SIGNAL-CONTRACT.md; ids are the API) ────────────────
_HEADER_LINE_ID: Final[str] = "header"
_HEADER_TEXT: Final[str] = (
    "🤖 [ccy-supervisor] automated goal — machine-generated, NOT a human "
    "instruction and NOT human authorisation for anything."
)
_WORK_LINE_ID: Final[str] = "work-until-complete"
# Two terminal conditions, not one. "until completion" alone left a plan
# blocked on human input with no sanctioned stop: the agent tries to stop, the
# Stop-hook challenge cites the still-live goal, the agent re-engages, finds
# nothing to do, and loops. Naming a total block as a valid stop — and telling
# the agent to STATE it — gives the Stop-hook challenge a satisfiable answer and
# breaks the loop. Kept tight so the tail clause survives the joined-line cap.
_WORK_LINE_TEXT: Final[str] = (
    "Work on Plan {plan_number} ({plan_title}) at {plan_path} until complete, "
    "or until totally blocked (on human input, or an external blocker you "
    "cannot clear). A total block is a valid stop: stop and state it; do not "
    "re-loop a done or blocked plan."
)
_SUBAGENTS_LINE_ID: Final[str] = "subagents-encouraged"
_SUBAGENTS_LINE_TEXT: Final[str] = (
    "Per this project's standing authorisation, you are encouraged to "
    "delegate to specialist sub-agents."
)
_QA_REVIEW_LINE_ID: Final[str] = "qa-review-subagents"
_QA_REVIEW_LINE_TEXT: Final[str] = (
    "Use specialist QA and code-review sub-agents; they log their reports "
    "directly into the plan folder."
)

# ── Combined multi-plan rendering (Plan 00299) ──────────────────────────────
# The upstream /goal slot is last-writer-wins (single value), so with two or
# more ledgered plans live at once the per-plan work line (which names ONE
# plan_number/title/path) is replaced by a single line naming every live
# plan number instead. One live plan renders byte-for-byte identically to
# ``render_goal_line`` — see ``render_combined_goal_line``.
_PLACEHOLDER_PLAN_NUMBERS: Final[str] = "plan_numbers"
_MULTI_WORK_LINE_TEXT: Final[str] = (
    "Work on Plan(s) {plan_numbers} until each is complete or totally blocked "
    "(on human input, or an external blocker you cannot clear). A total "
    "block on one plan is a valid stop for THAT plan: state which plan(s) "
    "are done or blocked; do not re-loop a done or blocked plan while "
    "others remain live."
)

# ── Trigger detection ──────────────────────────────────────────────────────
# The plan-dir portion of the trigger pattern (<plan_dir>/<digits>-<name>/
# PLAN.md, NOT inside Completed/ — the same shape recovery_cron_advisor uses
# for the same trigger surface) is built per-instance from the ProjectLayout
# facade's plan_dir (Plan 00288 Task 4.2) via the shared
# ``utils.plan_trigger`` module (Plan 00466 RV3-n5) — see
# _plan_dir()/_plan_path_pattern() below, which delegate to it.
_COMPLETED_SEGMENT: Final[str] = "/Completed/"
# RV3-m2: locates a candidate Status line's position for the replace_all
# ambiguity check below -- classification of ITS VALUE is always left to
# PlanDoc (fenced-block-aware, tolerant of dates/icons), never this regex.
_STATUS_LINE_LOCATE_RE: Final[re.Pattern[str]] = re.compile(r"^\*\*Status\*\*\s*:")
_PLAN_MD_FILENAME: Final[str] = "PLAN.md"
_TITLE_HEADING_PREFIX: Final[str] = "# "
# Strips a redundant "Plan NNNNN: " lead-in from the heading text, since the
# work line already states the plan number.
_TITLE_PLAN_PREFIX_RE: Final[re.Pattern[str]] = re.compile(r"^Plan\s+\d+\s*:\s*")

# ── Transition detection (ledger 00466 N3) ─────────────────────────────────
# Matches the Edit tool_input fields carrying the pre-/post-edit span. Not in
# HookInputField: old_string/new_string/replace_all are Edit-specific, not a
# general hook-envelope field like tool_name/session_id.
_FIELD_OLD_STRING: Final[str] = "old_string"
_FIELD_NEW_STRING: Final[str] = "new_string"
_FIELD_REPLACE_ALL: Final[str] = "replace_all"
_SINGLE_REPLACEMENT: Final[int] = 1

# Bound the (session_id, plan_number) latch map (FIFO eviction) so a
# long-lived daemon cannot leak memory across many sessions.
_MAX_TRACKED_LATCHES: Final[int] = 256

# Strip every control character (C0 + DEL) from interpolated values — the
# single-physical-line contract bans them, newlines above all.
_CONTROL_CHARS_RE: Final[re.Pattern[str]] = re.compile(r"[\x00-\x1f\x7f]")


@dataclass(frozen=True)
class GoalLine:
    """One goal message line: stable id, template text, enabled flag."""

    id: str
    text: str
    enabled: bool


_DEFAULT_LINES: Final[tuple[GoalLine, ...]] = (
    GoalLine(id=_WORK_LINE_ID, text=_WORK_LINE_TEXT, enabled=True),
    GoalLine(id=_SUBAGENTS_LINE_ID, text=_SUBAGENTS_LINE_TEXT, enabled=False),
    GoalLine(id=_QA_REVIEW_LINE_ID, text=_QA_REVIEW_LINE_TEXT, enabled=False),
)

_KNOWN_LINE_TEXTS: Final[dict[str, str]] = {line.id: line.text for line in _DEFAULT_LINES}


def _sanitise_value(value: str, *, max_chars: int) -> str:
    """Strip control chars, collapse whitespace, and cap length."""
    cleaned = _CONTROL_CHARS_RE.sub(" ", value)
    collapsed = " ".join(cleaned.split())
    return collapsed[:max_chars]


def _parse_raw_line(entry: Any, index: int) -> GoalLine | None:
    """Parse one raw ``lines[index]`` config entry; malformed entries skip.

    A project entry may enable a BUILT-IN line without restating its text
    (``{id: subagents-encouraged, enabled: true}``): the vetted default text
    is used. An entry with a new id must carry ``text``. The fixed ``header``
    id is never accepted from config (the safety marker is not content).
    """
    if not isinstance(entry, dict):
        logger.warning("goal_injection: lines[%d] is not a mapping; skipped", index)
        return None
    line_id = str(entry.get(_KEY_ID, "") or "").strip()
    if not line_id:
        logger.warning("goal_injection: lines[%d] missing id; skipped", index)
        return None
    if line_id == _HEADER_LINE_ID:
        logger.warning(
            "goal_injection: lines[%d] tries to override the fixed header; ignored", index
        )
        return None
    text = str(entry.get(_KEY_TEXT, "") or "").strip()
    if not text:
        default_text = _KNOWN_LINE_TEXTS.get(line_id)
        if default_text is None:
            logger.warning(
                "goal_injection: lines[%d] (%s) has no text and no built-in default; skipped",
                index,
                line_id,
            )
            return None
        text = default_text
    enabled = bool(entry.get(_KEY_ENABLED, True))
    return GoalLine(id=line_id, text=text, enabled=enabled)


def resolve_goal_lines(mode: str, raw_lines: Any) -> list[GoalLine]:
    """Merge built-in and project lines per the additive/replace paradigm.

    Excludes the fixed header (the renderer always prepends it). ``replace``
    uses only the project's lines; anything else behaves as ``additive``,
    where a project entry whose id matches a built-in overrides it in place.
    """
    parsed: list[GoalLine] = []
    if isinstance(raw_lines, list):
        for index, entry in enumerate(raw_lines):
            line = _parse_raw_line(entry, index)
            if line is not None:
                parsed.append(line)
    elif raw_lines not in (None, []):
        logger.warning("goal_injection: 'lines' option must be a list; ignoring")

    if mode == _MODE_REPLACE:
        return parsed
    merged: dict[str, GoalLine] = {line.id: line for line in _DEFAULT_LINES}
    for line in parsed:
        merged[line.id] = line
    return list(merged.values())


def _substitute_placeholders(text: str, values: dict[str, str]) -> str | None:
    """Substitute the closed placeholder vocabulary; None on unknown tokens."""
    rendered = text
    for token, value in values.items():
        rendered = rendered.replace("{" + token + "}", value)
    leftover = _PLACEHOLDER_TOKEN_RE.search(rendered)
    if leftover is not None:
        logger.warning(
            "goal_injection: unknown placeholder {%s} in configured line; line skipped",
            leftover.group(1),
        )
        return None
    return rendered


def render_goal_line(
    plan_number: str,
    plan_title: str,
    plan_path: str,
    *,
    mode: str = _DEFAULT_MODE,
    raw_lines: Any = None,
) -> str | None:
    """Render the goal message as ONE physical line, or None on bad inputs.

    The fixed machine-origin header is always the first logical line and is
    never overridable. Logical lines are capped pre-join
    (``_MAX_LOGICAL_LINES``); optional lines are dropped from the end until
    the joined line fits ``_MAX_JOINED_CHARS`` (hard-truncated as a last
    resort). All interpolated values are sanitised to a printable,
    control-free charset first, so the result can never contain a newline.
    """
    if not _PLAN_NUMBER_RE.match(plan_number):
        logger.error("goal_injection: invalid plan_number %r; goal not rendered", plan_number)
        return None
    values = {
        _PLACEHOLDER_PLAN_NUMBER: plan_number,
        _PLACEHOLDER_PLAN_TITLE: _sanitise_value(plan_title, max_chars=_MAX_TITLE_CHARS),
        _PLACEHOLDER_PLAN_PATH: _sanitise_value(plan_path, max_chars=_MAX_JOINED_CHARS),
    }

    logical: list[str] = [_HEADER_TEXT]
    for line in resolve_goal_lines(mode, raw_lines):
        if not line.enabled:
            continue
        rendered = _substitute_placeholders(line.text, values)
        if rendered is None or not rendered.strip():
            continue
        logical.append(_sanitise_value(rendered, max_chars=_MAX_JOINED_CHARS))
        if len(logical) >= _MAX_LOGICAL_LINES:
            break

    joined = _LOGICAL_LINE_SEPARATOR.join(logical)
    while len(joined) > _MAX_JOINED_CHARS and len(logical) > 1:
        logical.pop()
        joined = _LOGICAL_LINE_SEPARATOR.join(logical)
    return joined[:_MAX_JOINED_CHARS]


@dataclass(frozen=True)
class LivePlan:
    """One live plan's rendering identity for the combined `/goal` payload."""

    plan_number: str
    plan_title: str
    plan_path: str


def render_combined_goal_line(
    live_plans: list[LivePlan],
    *,
    mode: str = _DEFAULT_MODE,
    raw_lines: Any = None,
) -> str | None:
    """Render ONE `/goal` payload naming every live plan (Plan 00299).

    Exactly one live plan renders BYTE-FOR-BYTE identical output to
    :func:`render_goal_line` — the single-plan session's `/goal` text and
    Stop-hook behaviour must be unchanged from before this feature existed.
    Two or more live plans render a single combined work line naming every
    plan number instead of the per-plan work line (which cannot express
    more than one plan/title/path); every other configured line (built-in
    or project-added) still applies, since none of them reference a
    per-plan placeholder. Returns None for an empty list or an invalid
    plan number, mirroring :func:`render_goal_line`'s failure contract.
    """
    if not live_plans:
        return None
    ordered = sorted(live_plans, key=lambda plan: plan.plan_number)
    if len(ordered) == 1:
        only = ordered[0]
        return render_goal_line(
            only.plan_number, only.plan_title, only.plan_path, mode=mode, raw_lines=raw_lines
        )
    for plan in ordered:
        if not _PLAN_NUMBER_RE.match(plan.plan_number):
            logger.error(
                "goal_injection: invalid plan_number %r in combined render; skipped",
                plan.plan_number,
            )
            return None

    plan_numbers_text = _sanitise_value(
        ", ".join(plan.plan_number for plan in ordered), max_chars=_MAX_JOINED_CHARS
    )
    multi_work = _MULTI_WORK_LINE_TEXT.replace(
        "{" + _PLACEHOLDER_PLAN_NUMBERS + "}", plan_numbers_text
    )
    logical: list[str] = [_HEADER_TEXT, _sanitise_value(multi_work, max_chars=_MAX_JOINED_CHARS)]

    for line in resolve_goal_lines(mode, raw_lines):
        if line.id == _WORK_LINE_ID or not line.enabled:
            continue
        # Every other built-in/project line is plan-agnostic text (no
        # {plan_number}/{plan_title}/{plan_path} tokens), so it renders with
        # an empty placeholder set; an accidental per-plan token skips the
        # line, same as the single-plan renderer.
        rendered = _substitute_placeholders(line.text, {})
        if rendered is None or not rendered.strip():
            continue
        logical.append(_sanitise_value(rendered, max_chars=_MAX_JOINED_CHARS))
        if len(logical) >= _MAX_LOGICAL_LINES:
            break

    joined = _LOGICAL_LINE_SEPARATOR.join(logical)
    while len(joined) > _MAX_JOINED_CHARS and len(logical) > 1:
        logical.pop()
        joined = _LOGICAL_LINE_SEPARATOR.join(logical)
    return joined[:_MAX_JOINED_CHARS]


def write_goal_signal(
    session_id: str, plan_number: str, joined_line: str, source: str
) -> Path | None:
    """Atomically write the ``<session>.goal-intent`` signal file.

    Also drops any pending ``<session>.goal-clear`` for this session, which
    makes the exclusion between the two signals SYMMETRIC: ``clear_goal_signal``
    already unlinks the intent file. Without this half, a clear the supervisor
    had not yet consumed survived alongside the new intent, and its precedence
    rule ("goal wins, the clear waits a tick") only deferred the clear by one
    tick — the next goal was set, then retracted a tick later.

    Failures are logged, never raised — this is a best-effort sensor signal
    and must never break the tool call that triggered it. Returns the final
    path, or None on failure.
    """
    try:
        target_dir = ProjectContext.daemon_untracked_dir() / _SIGNAL_SUBDIR
        target_dir.mkdir(parents=True, exist_ok=True)
        stem = _UNSAFE_SESSION_CHARS.sub("_", session_id) if session_id else _SESSION_ID_FALLBACK
        (target_dir / f"{stem}{_CLEAR_SUFFIX}").unlink(missing_ok=True)
        final_path = target_dir / f"{stem}{_SIGNAL_SUFFIX}"
        tmp_path = unique_temp_path(final_path)
        payload = {
            _FIELD_TS: time.time(),
            _FIELD_SESSION_ID: session_id,
            _FIELD_PLAN_NUMBER: plan_number,
            _FIELD_RENDERED_LINES: [joined_line],
            _FIELD_SOURCE: source,
        }
        tmp_path.write_text(json.dumps(payload), encoding="utf-8")
        tmp_path.replace(final_path)
        return final_path
    except RuntimeError as e:
        logger.warning("goal_injection: skipping signal (no project context): %s", e)
        return None
    except OSError as e:
        logger.warning("goal_injection: failed to write goal signal: %s", e)
        return None


def clear_goal_signal(session_id: str) -> bool:
    """Retract the session's goal (Plans 00320, 00321).

    The retract counterpart to :func:`write_goal_signal`, and it has two
    halves because the goal lives in two places.

    First, remove ``<session>.goal-intent``: declining to REWRITE it is not
    the same as retracting it, so without this the file written when the
    goal was emitted survives and a retired goal keeps being read as live.

    Second, drop a ``<session>.goal-clear`` trigger. Removing the sidecar
    only stops RE-injection; Claude Code's own ``/goal`` slot is
    last-writer-wins and holds the condition until something types a
    clearing form, so the supervisor needs telling. The file's PRESENCE is
    the entire message — the supervisor types a fixed literal and reads no
    text out of it, so a forged trigger can only ever clear a goal.

    Failures are logged, never raised — same best-effort contract as the
    writer. Returns True when both halves succeeded.
    """
    try:
        target_dir = ProjectContext.daemon_untracked_dir() / _SIGNAL_SUBDIR
        stem = _UNSAFE_SESSION_CHARS.sub("_", session_id) if session_id else _SESSION_ID_FALLBACK
        (target_dir / f"{stem}{_SIGNAL_SUFFIX}").unlink(missing_ok=True)
        target_dir.mkdir(parents=True, exist_ok=True)
        clear_path = target_dir / f"{stem}{_CLEAR_SUFFIX}"
        tmp_path = unique_temp_path(clear_path)
        tmp_path.write_text(
            json.dumps({_FIELD_TS: time.time(), _FIELD_SESSION_ID: session_id}),
            encoding="utf-8",
        )
        tmp_path.replace(clear_path)
        return True
    except RuntimeError as e:
        logger.warning("goal_injection: skipping signal clear (no project context): %s", e)
        return False
    except OSError as e:
        logger.warning("goal_injection: failed to clear goal signal: %s", e)
        return False


def _real_status_line_span(text: str) -> tuple[int, int] | None:
    """Start/end character offsets of the first non-fenced ``**Status**:``
    line -- the same line :class:`PlanDoc` treats as the document's real
    status. RV3-m1's ``replace_all`` ambiguity check (below) uses this to
    tell whether a matched occurrence of ``new_string`` coincides with THAT
    specific line, as opposed to an unrelated line (a table cell, a fenced
    example) that merely contains the same text.
    """
    for start, end, content in line_spans_outside_fences(text):
        if _STATUS_LINE_LOCATE_RE.match(content):
            return start, end
    return None


def _reverse_all_except(text: str, new_string: str, old_string: str, skip_site: int) -> str:
    """Reverse every non-overlapping occurrence of ``new_string`` back to
    ``old_string``, except the one starting at ``skip_site`` (left as
    ``new_string``). Used by RV3-m1's ``replace_all`` ambiguity check to
    build the "what if only the OTHER occurrences were really this edit"
    candidate.
    """
    pieces: list[str] = []
    cursor = 0
    search_from = 0
    while True:
        site = text.find(new_string, search_from)
        if site == -1:
            break
        if site == skip_site:
            pieces.append(text[cursor : site + len(new_string)])
        else:
            pieces.append(text[cursor:site])
            pieces.append(old_string)
        cursor = site + len(new_string)
        search_from = cursor
    pieces.append(text[cursor:])
    return "".join(pieces)


def extract_plan_title(plan_text: str) -> str:
    """First ``# `` heading of PLAN.md, minus any leading ``Plan NNNNN:``."""
    for raw_line in plan_text.splitlines():
        stripped = raw_line.strip()
        if stripped.startswith(_TITLE_HEADING_PREFIX):
            heading = stripped[len(_TITLE_HEADING_PREFIX) :].strip()
            return _TITLE_PLAN_PREFIX_RE.sub("", heading)
    return ""


class GoalInjectionHandler(PostToolUseHandlerBase):
    """Write a goal-intent signal when a plan TRANSITIONS to In Progress.

    Fires only when THIS Write/Edit is what moved the Status line to In
    Progress (see ``_is_real_flip_to_in_progress``) — never merely because
    the post-write file happens to already read In Progress (ledger 00466
    N3). An edit unrelated to the Status line, or a Write that rewrites an
    already-In-Progress plan, emits nothing THROUGH THE FLIP PATH — but a
    session touching an already-live plan without flipping it still gets
    its OWN goal signal rewritten, once per ``(session, plan)`` per daemon
    lifetime (``_maybe_reassert_for_new_session``), restoring the "goal
    survives a session restart" contract — including a SAME-session-id
    resume — without a real flip's displacement side effects, and it ADDS
    to the plan's ownership rather than transferring it away from whoever
    already held it.

    Sensor only: the daemon never types; the ccy PTY supervisor consumes the
    signal at its injection choke point. ADVISORY: never blocks, never denies.
    """

    # REPO-scoped: the plan tree is repository-singular (see
    # CLAUDE/Code/WorkspaceResolution.md).
    workspace_scope: ClassVar[WorkspaceScope] = WorkspaceScope.REPO

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.GOAL_INJECTION,
            priority=Priority.GOAL_INJECTION,
            terminal=False,
            tags=[HandlerTag.WORKFLOW, HandlerTag.ADVISORY, HandlerTag.NON_TERMINAL],
        )
        # Config options — injected by the registry via setattr; typed and
        # defaulted here so mypy sees real attributes.
        self._mode: str = _DEFAULT_MODE
        self._lines: list[dict[str, Any]] | None = None
        self._once_per_plan_per_session: bool = True
        # (session_id, plan_number) latch — bounded, FIFO eviction.
        self._fired: dict[tuple[str, str], bool] = {}
        # (session_id, plan_number) latch for a CONFIRMED reassert-path
        # write THIS daemon lifetime (review RV-m3) — separate from
        # ``_fired`` (which only ever latches a REAL flip): a resumed
        # session with the SAME session id as its earlier real flip must
        # still get its signal rewritten once per daemon lifetime even
        # though ``_fired`` is already set for it.
        self._reasserted: dict[tuple[str, str], bool] = {}

    def get_default_enabled(self) -> bool:
        """Opt-in: only useful when a PTY supervisor is watching."""
        return False

    def get_relevance(self, context: RelevanceContext) -> Relevance:
        """Relevant only under an armed ccy supervisor (Plan 00330)."""
        return supervisor_relevance(context)

    def _plan_dir(self) -> str:
        """Configured plan directory (facade, or the matching default).

        Delegates to :mod:`utils.plan_trigger` (Plan 00466 RV3-n5) — kept
        as a thin wrapper, rather than removed, so every existing call site
        below is unaffected while ``plan_status_snapshot`` (PreToolUse)
        shares the SAME implementation, keeping the two handlers' notion of
        "the trigger" from silently drifting apart.
        """
        return _plan_trigger_plan_dir_for(self._project_layout)

    def _plan_path_pattern(self) -> re.Pattern[str]:
        """Compile the trigger pattern from the configured plan directory.

        Matches ``<plan_dir>/<digits>-<name>/PLAN.md`` (the ``/Completed/``
        exclusion is checked separately by callers via _COMPLETED_SEGMENT).
        Delegates to :mod:`utils.plan_trigger`; see :meth:`_plan_dir`.
        """
        return _plan_trigger_plan_path_pattern(self._plan_dir())

    @staticmethod
    def _is_inside_project(file_path: str) -> bool:
        """True when ``file_path`` lives under this project's root.

        The trigger pattern is applied with ``search``, so any path merely
        CONTAINING ``<plan_dir>/NNNNN-name/PLAN.md`` matches wherever it
        lives — while the rendered goal re-points it at the PROJECT's plan
        directory. A scratch plan under /tmp would therefore emit a live
        goal naming a project path that does not exist, and an
        unsatisfiable goal cannot be discharged by doing the work
        (Plan 00320). Delegates to :mod:`utils.plan_trigger`; see
        :meth:`_plan_dir`.
        """
        return _plan_trigger_is_inside_project(file_path)

    @staticmethod
    def _is_in_progress_status(status: PlanStatus | None) -> bool:
        return status == PlanStatus.IN_PROGRESS

    @staticmethod
    def _is_terminal_status(status: PlanStatus | None) -> bool:
        return status is not None and status in TERMINAL_STATUSES

    @staticmethod
    def _is_transition_via_reconstruction(
        tool_input: dict[str, Any],
        post_edit_text: str,
        is_target: Callable[[PlanStatus | None], bool],
    ) -> bool:
        """Undo this Edit against the CURRENT (post-edit) text and ask
        whether the pre-edit Status satisfied ``is_target`` -- if it did
        NOT, this Edit is the transition INTO ``is_target`` (a real flip to
        In Progress, or a real move into a terminal status, depending on
        which predicate the caller passed).

        Review m4: ``old_string`` alone is not always enough to answer
        whether the Status line was touched — an agent may quote only the
        minimal unique context (e.g. ``old_string="Not Started"`` with no
        ``**Status**:`` prefix), which carries no Status line even when the
        edit genuinely flipped one. The file already reflects ``new_string``
        by the time PostToolUse runs, so the pre-edit text is recoverable by
        reversing the SAME substitution the Edit tool itself performed
        (mirrors ``would_be_content``'s forward transform, in reverse).

        Review RV-m1: ``new_string`` is not necessarily UNIQUE in the
        post-edit file, so undoing only its first occurrence can reconstruct
        the WRONG span entirely — e.g. a table cell or a title also reading
        "In Progress" sits before the real Status line, and reversing that
        first hit reports a false flip (or masks a real one). The Edit tool
        itself only ever applies to a file where ``old_string`` was unique
        (without ``replace_all``), so every occurrence of ``new_string`` is
        tried as a candidate edit site, and only a candidate whose reversal
        leaves ``old_string`` unique in the reconstructed text could be the
        one the tool actually matched — anything else is a coincidental
        collision, not the real site. A transition is reported only when
        EVERY surviving candidate agrees the pre-edit Status did not satisfy
        ``is_target``; any disagreement, or no viable candidate at all
        (mirrors this method's prior conservative default for an
        unreversable edit), reads as "not a transition".

        ``replace_all`` carries no uniqueness guarantee for ``old_string`` at
        all (that is the point of ``replace_all``), so the per-occurrence
        candidate filter above does not apply. Review RV3-m1: a clean
        ``replace_all`` leaves no ``old_string`` behind, so the ORIGINAL
        guard (bail out if ``old_string`` survives anywhere) only catches a
        collision where the edit was never cleanly applied at all -- it does
        NOT catch the far more common case where ``new_string`` ALREADY sat
        on the real Status line before this edit, untouched, while a
        DIFFERENT site (a table cell) was the one genuinely replaced: after
        a clean ``replace_all`` neither the untouched Status line's
        occurrence nor the genuinely-replaced one leaves any ``old_string``
        behind, so that guard cannot distinguish them, and blindly reversing
        EVERY occurrence (including the untouched Status line) reconstructs
        a status the edit never touched. So: if a ``new_string`` occurrence
        overlaps the real (non-fenced) Status line AND at least one other
        occurrence exists elsewhere, two verdicts are compared -- reversing
        every occurrence, and reversing every occurrence EXCEPT the one on
        the Status line (i.e. leaving the Status line exactly as the
        post-edit file already reads). Agreement means the Status line's own
        occurrence was never genuinely ambiguous either way; disagreement
        means it cannot be told apart, so this conservatively reads as "not
        a transition" -- the SAME trade-off this method already accepts for
        an unreversable non-``replace_all`` edit, now extended to cover a
        genuine BULK multi-site transition that happens to include the
        Status line too (previously detected, now conservatively missed,
        because there is no way from the post-edit text alone to tell that
        case apart from the untouched-Status-line collision it is most often
        confused with). A single occurrence overlapping the Status line, with
        nothing else to disambiguate against, is unambiguous and answered
        directly from the full reversal.
        """
        new_string = str(tool_input.get(_FIELD_NEW_STRING, ""))
        old_string = str(tool_input.get(_FIELD_OLD_STRING, ""))
        if not new_string or new_string not in post_edit_text:
            return False
        if bool(tool_input.get(_FIELD_REPLACE_ALL, False)):
            if old_string and old_string in post_edit_text:
                return False
            sites: list[int] = []
            search_from = 0
            while True:
                site = post_edit_text.find(new_string, search_from)
                if site == -1:
                    break
                sites.append(site)
                search_from = site + 1
            status_span = _real_status_line_span(post_edit_text)
            overlapping = None
            if status_span is not None:
                s_start, s_end = status_span
                overlapping = next((s for s in sites if s_start <= s < s_end), None)
            full_reverse = post_edit_text.replace(new_string, old_string)
            full_verdict = not is_target(PlanDoc.parse(full_reverse).status)
            other_sites = [s for s in sites if s != overlapping]
            if overlapping is None or not other_sites:
                return full_verdict
            partial_reverse = _reverse_all_except(
                post_edit_text, new_string, old_string, overlapping
            )
            partial_verdict = not is_target(PlanDoc.parse(partial_reverse).status)
            if full_verdict != partial_verdict:
                return False
            return full_verdict

        verdicts: list[bool] = []
        search_from = 0
        while True:
            site = post_edit_text.find(new_string, search_from)
            if site == -1:
                break
            candidate = (
                post_edit_text[:site] + old_string + post_edit_text[site + len(new_string) :]
            )
            if candidate.count(old_string) == _SINGLE_REPLACEMENT:
                verdicts.append(not is_target(PlanDoc.parse(candidate).status))
            search_from = site + 1
        return bool(verdicts) and all(verdicts)

    def _is_real_transition(
        self,
        hook_input: dict[str, Any],
        file_path: Path,
        post_edit_text: str,
        *,
        is_target: Callable[[PlanStatus | None], bool],
    ) -> bool:
        """True only when THIS Write/Edit is what moved the Status line INTO
        the ``is_target`` classification -- never merely because the
        post-write file already satisfies it. Shared by the in-progress
        flip detector (``is_target=_is_in_progress_status``) and RV3-M1's
        terminal-transition detector (``is_target=_is_terminal_status``) so
        both read pre-edit state through the same tested machinery.

        Edit: ``old_string`` is the FIRST witness of the pre-edit text
        consulted, and used DIRECTLY only when its ``**Status**:`` line is
        verified to be the document's REAL one (RV3-m2): a fragment carrying
        a per-phase or fenced-example ``**Status**:`` line is not the plan's
        actual status line, and trusting it in isolation misread a
        completely unrelated edit under that OTHER line as a top-level
        transition. The full pre-edit file is instead always reconstructed
        by reversing this edit against the post-edit text already on disk
        (:meth:`_is_transition_via_reconstruction`, which also resolves
        review RV-m1/RV3-m1's ``new_string`` collision cases) and parsed
        with the SAME fenced-block-aware, first-line-wins rule PlanDoc
        already applies to the post-edit side — so both sides of the
        transition agree on what "the real Status line" is. An irreversible
        reconstruction (``new_string`` not found) is read as "not a
        transition", the conservative default this function already used
        for an ``old_string`` with no Status line at all.

        Write: the file has already landed on disk by the time PostToolUse
        runs, so there is no unmodified copy left to compare against. git
        HEAD stands in for "before" instead of the Write's ``tool_response``
        deliberately: this codebase's own
        ``CLAUDE/Plan/Completed/001-test-fixture-validation/
        POSTTOOLUSE_FIXTURE_VERIFICATION.md`` records a handler that
        silently never matched real events because of an unverified
        ``tool_response`` shape, and no fixture or vendored doc in this repo
        pins what a Write/Edit ``tool_response`` actually carries — while
        HEAD is a stable interface this project already relies on elsewhere
        (``utils.git_facts``, shared with ``recovery_cron_advisor`` via
        :func:`project_relative_head_text`, which reads it from the file's
        OWN enclosing repository — review m5 — not necessarily the project
        root's). A path absent at HEAD (brand new, or never committed)
        correctly reads as "nothing to transition FROM": a fresh document
        already in the target state is a genuine transition, not noise.
        """
        tool_name = hook_input.get(HookInputField.TOOL_NAME)
        if tool_name == ToolName.EDIT:
            tool_input = hook_input.get(HookInputField.TOOL_INPUT, {}) or {}
            return self._is_transition_via_reconstruction(tool_input, post_edit_text, is_target)
        before_text = project_relative_head_text(file_path, ProjectContext.project_root())
        if before_text is None:
            return True
        return not is_target(PlanDoc.parse(before_text).status)

    def _resolve_transition(
        self,
        hook_input: dict[str, Any],
        file_path: Path,
        post_edit_text: str,
        *,
        is_target: Callable[[PlanStatus | None], bool],
    ) -> tuple[bool, bool]:
        """Ground-truth-first transition check (Plan 00466 RV3-n5).

        Returns ``(is_transition, used_fallback)``. Prefers the PreToolUse
        snapshot recorded for THIS SAME tool call (``plan_status_snapshot``,
        keyed by ``tool_use_id``) over :meth:`_is_real_transition`'s
        inference: a value read directly off disk immediately before the
        write cannot collide with a table cell or a fenced example the way
        reconstructing the pre-edit text from ``old_string``/``new_string``
        can (RV3-m1/m2), and is not subject to git HEAD lagging an
        uncommitted flip (RV3-m6) the way the Write-only fallback is. The
        inference machinery is kept and used ONLY when no snapshot exists
        for this ``tool_use_id`` -- a daemon restart between the Pre and
        Post dispatch of this same call, or a payload carrying no
        ``tool_use_id`` at all -- and that fallback use is logged, since it
        is the narrower, sometimes-ambiguous signal being kept for exactly
        that narrow window rather than the common path.
        """
        tool_use_id = str(hook_input.get(HookInputField.TOOL_USE_ID, "") or "")
        snapshot_status, found = plan_status_snapshots.consume(tool_use_id)
        if found:
            return not is_target(snapshot_status), False
        logger.info(
            "goal_injection: no pre-write status snapshot for tool_use_id=%r; "
            "falling back to old_string/new_string and git-HEAD inference",
            tool_use_id,
        )
        transition = self._is_real_transition(
            hook_input, file_path, post_edit_text, is_target=is_target
        )
        return transition, True

    def _is_real_flip_to_in_progress(
        self, hook_input: dict[str, Any], file_path: Path, plan_number: str, post_edit_text: str
    ) -> bool:
        """True only when THIS Write/Edit is what set Status to In Progress.

        Delegates to :meth:`_resolve_transition`. RV3-m6: for a Write only,
        a positive transition verdict reached via the INFERENCE FALLBACK
        (no snapshot available) is narrowed further -- git HEAD can lag an
        uncommitted flip (a teammate's Write lands on disk, and in the
        ledger, before it is ever committed), so a Write that reads "not
        yet in progress at HEAD" is still not a fresh flip when the ledger
        ALREADY has a live entry for this plan: someone else already
        started it, and this Write is not what did so. Edit is immune to
        this race -- its ``old_string``/``new_string`` are the tool's own
        record of the pre-/post-edit text on THIS call, not a git snapshot.
        A snapshot-backed verdict needs no such narrowing: it already read
        the plan's actual pre-write status straight off disk, so the race
        this guards against cannot have occurred.
        """
        transition, used_fallback = self._resolve_transition(
            hook_input, file_path, post_edit_text, is_target=self._is_in_progress_status
        )
        if not transition:
            return False
        if (
            used_fallback
            and hook_input.get(HookInputField.TOOL_NAME) != ToolName.EDIT
            and self._ledger_plan_is_live(plan_number)
        ):
            return False
        return True

    def _ledger_plan_is_live(self, plan_number: str) -> bool:
        """RV3-m6: True when the ledger already has a live entry for
        ``plan_number``, regardless of which session owns it. Fails open to
        False (not live) on a ``ProjectContext`` failure -- this is a
        narrowing check layered on top of the git-HEAD verdict
        :meth:`_is_real_flip_to_in_progress` already computed, so falling
        back to THAT verdict is a substantive fallback, not a swallow.
        """
        try:
            ledger = self._open_ledger()
        except RuntimeError as e:
            logger.warning("goal_injection: live-plan check skipped (no project context): %s", e)
            return False
        return ledger.is_plan_live(plan_number)

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """True for a Write/Edit landing on an ACTIVE plan's PLAN.md."""
        if hook_input.get(HookInputField.TOOL_NAME) not in (ToolName.WRITE, ToolName.EDIT):
            return False
        file_path = get_file_path(hook_input) or ""
        normalized = file_path.replace("\\", "/")
        if _COMPLETED_SEGMENT in normalized:
            return False
        if self._plan_path_pattern().search(normalized) is None:
            return False
        return self._is_inside_project(file_path)

    def handle(self, hook_input: dict[str, Any]) -> BlockingResult:
        """Render and write the goal-intent signal; always ALLOW.

        A REAL transition to In Progress (see ``_is_real_flip_to_in_progress``
        — ledger 00466 N3) renders+records this plan then writes the
        COMBINED signal for every live ledgered plan (Plan 00299) — a
        single live plan degrades byte-for-byte to the pre-00299 text. A
        flip to a TERMINAL status for a plan this session already ledgered
        re-renders the combined signal too, so a completing plan drops out
        of the `/goal` text promptly rather than only on the next
        UNRELATED plan's write.
        """
        file_path = get_file_path(hook_input) or ""
        normalized = file_path.replace("\\", "/")
        match = self._plan_path_pattern().search(normalized)
        if match is None or not self._is_inside_project(file_path):
            return BlockingResult(decision=Decision.ALLOW)
        folder = match.group(1)
        plan_number = folder.split("-", 1)[0].zfill(5)

        try:
            plan_text = self._read_plan(Path(file_path))
        except PlanUnreadable as e:
            logger.warning("goal_injection: %s; no goal signal for this write", e)
            return BlockingResult(decision=Decision.ALLOW)

        session_id = str(hook_input.get(HookInputField.SESSION_ID, "") or "")

        # RV3-m2: PlanDoc, not a literal-only regex, decides the post-write
        # state -- the same fenced-block-aware, date/icon-tolerant parser
        # the pre-write side already used, so both sides of the transition
        # agree on what "the real Status line" is (a fenced example or a
        # per-phase second Status line no longer masquerades as it).
        post_doc = PlanDoc.parse(plan_text)
        if not self._is_in_progress_status(post_doc.status):
            self._maybe_refresh_on_retirement(
                session_id, plan_number, Path(file_path), plan_text, hook_input
            )
            return BlockingResult(decision=Decision.ALLOW)

        if not self._is_real_flip_to_in_progress(
            hook_input, Path(file_path), plan_number, plan_text
        ):
            self._maybe_reassert_for_new_session(
                session_id, plan_number, plan_text, folder, Path(file_path)
            )
            return BlockingResult(decision=Decision.ALLOW)

        latch_key = (session_id, plan_number)
        if self._once_per_plan_per_session and self._fired.get(latch_key):
            return BlockingResult(decision=Decision.ALLOW)

        joined = render_goal_line(
            plan_number,
            extract_plan_title(plan_text),
            f"{self._plan_dir()}/{folder}",
            mode=self._mode,
            raw_lines=self._lines,
        )
        if joined is None:
            return BlockingResult(decision=Decision.ALLOW)

        displaced = self._ledger_record(session_id, plan_number, joined, Path(file_path))

        written = self._write_combined_signal(
            session_id, Path(file_path), fallback=joined, fallback_plan_number=plan_number
        )
        if written is None:
            return BlockingResult(decision=Decision.ALLOW)

        # Latch only after a CONFIRMED write -- a failed write (returns
        # None) must leave the session free to retry on the next
        # qualifying event, or it never gets a /goal at all. RV3-m4: the
        # reassert latch is set here too, not just _fired -- otherwise a
        # same-session, same-lifetime non-flip touch right after this flip
        # falls through to _maybe_reassert_for_new_session and writes a
        # second, redundant signal before that path's OWN latch would ever
        # have been set.
        self._record_latch(self._fired, latch_key)
        self._record_latch(self._reasserted, latch_key)

        if displaced:
            plans = ", ".join(displaced)
            verb = "it is" if len(displaced) == 1 else "they are"
            advisory = _DISPLACEMENT_ADVISORY_TEMPLATE.format(
                plans=plans, new_plan=plan_number, verb=verb
            )
            return BlockingResult(decision=Decision.ALLOW, context=[advisory])
        return BlockingResult(decision=Decision.ALLOW)

    @staticmethod
    def _open_ledger() -> GoalLedger:
        """Build a :class:`GoalLedger` against the daemon's untracked dir.

        Raises ``RuntimeError`` when ``ProjectContext`` has not been
        initialised — it does not catch, so every caller sees the SAME
        failure and decides its own fail-open action explicitly, rather
        than interpreting a shared ``None`` sentinel this helper would
        otherwise have to invent.

        Each of this class's four ledger-touching callers decides its OWN
        fail-open action, sized to what it can meaningfully do on failure,
        rather than all four sharing one invented "give up" shape:

        - ``_write_combined_signal`` catches and falls back to writing the
          caller-supplied fallback signal verbatim — a substantive
          alternate action, not a bare log.
        - ``_ledger_record`` catches and reports no displacement (an empty
          list is a legitimate, differently-typed answer to "what did this
          newly displace", not a disguised ``None``).
        - ``_maybe_refresh_on_retirement`` and
          ``_maybe_reassert_for_new_session`` do NOT catch at all — neither
          has anything substantive to fall back to (both are ``-> None``,
          and a bare "log the error, then keep going" except clause is
          ``error_hiding``'s OWN separate ``log-and-continue`` anti-pattern,
          not a fix for the first one. The exception propagates to
          ``core/chain.py``'s per-handler exception wrapper
          (``fail-open-boundaries.yaml``, ``chain.py``/``execute``): an
          already-reviewed, already-documented fail-open boundary that logs,
          surfaces the failure in the result's context, and ALLOWs — except
          under ``strict_mode`` (this repo's setting), where it both DENIES
          the tool call and stops the rest of this PostToolUse chain (no
          handler after this one's priority runs for that event; see
          ``core/chain.py``'s ``execute``) — the same contract every other
          handler in this codebase already relies on.
        """
        ledger_path = ProjectContext.daemon_untracked_dir() / LEDGER_FILENAME
        return GoalLedger(ledger_path)

    def _maybe_refresh_on_retirement(
        self,
        session_id: str,
        plan_number: str,
        plan_md_path: Path,
        plan_text: str,
        hook_input: dict[str, Any],
    ) -> None:
        """Refresh EVERY owning session's combined signal when THIS write is
        what moved a LEDGERED plan into a terminal status.

        RV3-M1: gated on :meth:`_resolve_transition` (target: terminal), the
        same transition discipline ledger 00466 N3 already requires for the
        flip side. Without this, ANY later write that merely leaves an
        already-Complete (or otherwise terminal) plan alone -- a note added
        before its Plan Completion Checklist archive move, say -- re-read as
        "just retired" and re-signalled every owner: handing an unrelated
        session a fresh goal for a plan it never touched, or clearing a
        session's own unrelated manual goal.

        Review M2: "somebody emitted a goal for this plan" is answered from
        the PERSISTENT ``GoalLedger`` (:meth:`GoalLedger.owning_sessions`),
        not the in-memory ``self._fired`` latch, so a plan flipped and
        completed in different daemon lifetimes (a restart between them)
        still drops out of the combined `/goal` text.

        Review RV-M1/RV3-M1: EVERY session ``owning_sessions`` names is
        refreshed, not just whichever session's write triggered this read --
        ``owning_sessions`` itself answers from the plan's LIVE entry, or
        else its MOST RECENTLY retired one, so a plan reopened and
        recompleted under a different session retracts the RIGHT session,
        never a stale one from an earlier lifecycle.

        RV3-m5: the combined text is rendered ONCE (:meth:`_render_combined`)
        and written to every owner, rather than re-derived per owner (which
        was a full live-plan-directory read PER owner -- measured at 0.25s
        for 150 owners, against 0.003s on main before this class of gap
        existed at all).

        Unlike ``_write_combined_signal``/``_ledger_record``, this method
        does NOT catch ``_open_ledger``'s ``RuntimeError`` itself. There is
        no substantive fail-open action to take here beyond "log and do
        nothing further" (this method returns nothing to fall back to), and
        a bare log-then-continue except clause is its own recognised
        anti-pattern (``error_hiding``'s ``log-and-continue`` check) — this
        module has one already-reviewed, already-documented fail-open
        boundary for exactly that shape, one level up:
        ``core/chain.py``'s per-handler exception wrapper
        (``fail-open-boundaries.yaml``, ``chain.py``/``execute``), which
        logs, surfaces the failure in the result's context, and denies
        instead under ``strict_mode`` — the same contract every other
        handler in this codebase already relies on, not a bespoke one
        invented for this method.
        """
        doc = PlanDoc.parse(plan_text)
        if doc.status is None or doc.status not in TERMINAL_STATUSES:
            return
        transition, _used_fallback = self._resolve_transition(
            hook_input, plan_md_path, plan_text, is_target=self._is_terminal_status
        )
        if not transition:
            return
        ledger = self._open_ledger()
        owners = ledger.owning_sessions(plan_number)
        if not owners:
            return
        plan_dir = plan_md_path.parent.parent
        refs = ledger.live_plan_refs(plan_dir)
        if not refs:
            for owner in owners:
                clear_goal_signal(owner)
            return
        payload = self._render_combined(refs)
        if payload is None:
            logger.warning(
                "goal_injection: combined render failed while refreshing %d owner(s); "
                "leaving existing goal signals untouched",
                len(owners),
            )
            return
        plan_numbers_field, combined = payload
        for owner in owners:
            write_goal_signal(owner, plan_numbers_field, combined, _SOURCE_STATUS_FLIP)

    def _maybe_reassert_for_new_session(
        self,
        session_id: str,
        plan_number: str,
        plan_text: str,
        folder: str,
        plan_md_path: Path,
    ) -> None:
        """Restore Plan 00269's "goal survives a session restart" intent
        (review M3) for a session touching an already-ledgered In-Progress
        plan without a real flip of its own — a genuinely new session id,
        AND a session RESUMING with the SAME id (review RV-m3).

        Plan 00269 Task 2.1 deliberately relied on a weaker signal than a
        transition — "the first edit to an already-In-Progress plan in a
        NEW session re-fires" — specifically because a brand-new session
        has no ``/goal`` signal file of its own yet, however live the plan
        already is. Ledger 00466 N3 requires a genuine transition to fire
        the FULL flip path (ledger record, displacement advisory, latch),
        which silently dropped this: a session got no goal at all until a
        real flip or a manual ``inject-goal``.

        Re-arming through the full flip path would be wrong here: calling
        :meth:`_ledger_record` for a plan that is not actually starting
        could wrongly mark some OTHER still-live plan displaced. So this
        only ADDS this session to the plan's already-live entry
        (:meth:`GoalLedger.reassert_session` — additive, review RV-M1; no
        displacement bookkeeping runs at all) and writes this session's own
        signal file. ``reassert_session`` returning ``False`` (the ledger
        has never heard of this plan) leaves this a no-op, matching N3's
        contract: nothing to resume, so nothing fires.

        Gating, in order:

        1. An in-memory ``(session_id, plan_number)`` latch, reset every
           daemon lifetime (review RV-m3): the persisted ledger's
           ``session_has_entries`` survives a restart, which is exactly
           the problem — it reads "this session already got a goal" even
           when the FILE that goal lived in was consumed by the supervisor
           or lost across a restart, so a SAME-session-id resume (Claude
           Code's ``--resume``/``--continue``) never got its `/goal` back.
           Latching per daemon lifetime instead means "have I, this
           process, already confirmed a signal for this pair" — true for
           both a genuinely new session AND a resumed one, exactly once
           each, cheaply.
        2. ``session_has_entries`` (unaffected by RV-M1's additive change —
           it still reads the ``session_id`` field, which only a REAL
           flip/re-emission ever sets, never ``reassert_session``) blocks a
           session that already real-flipped some OTHER plan of its own
           from implicitly absorbing an UNRELATED plan it merely happens to
           touch — UNLESS it is already a stakeholder of THIS plan
           specifically (:meth:`GoalLedger.has_live_entry`), which is
           exactly the resumed-session case rule 1 exists to fix.

        Same fail-open contract as ``_maybe_refresh_on_retirement`` above:
        ``_open_ledger``'s ``RuntimeError`` is NOT caught here either, for
        the same reason -- nothing substantive to fall back to, so it is
        left to ``core/chain.py``'s already-reviewed, already-documented
        fail-open boundary one level up.
        """
        if not session_id:
            return
        latch_key = (session_id, plan_number)
        if self._reasserted.get(latch_key):
            return
        ledger = self._open_ledger()
        already_this_plan = ledger.has_live_entry(session_id, plan_number)
        if not already_this_plan and ledger.session_has_entries(session_id):
            return
        if not ledger.reassert_session(session_id, plan_number):
            return
        fallback = render_goal_line(
            plan_number,
            extract_plan_title(plan_text),
            f"{self._plan_dir()}/{folder}",
            mode=self._mode,
            raw_lines=self._lines,
        )
        written = self._write_combined_signal(
            session_id, plan_md_path, fallback=fallback, fallback_plan_number=plan_number
        )
        # Latch only after a CONFIRMED write -- same rationale as the real
        # flip path in handle(): a failed write must leave this pair free
        # to retry on the next qualifying event.
        if written is not None:
            self._record_latch(self._reasserted, latch_key)

    def _write_combined_signal(
        self,
        session_id: str,
        plan_md_path: Path,
        *,
        fallback: str | None,
        fallback_plan_number: str,
    ) -> Path | None:
        """Render the ledger's live-plan set and write it as the signal.

        ``fallback`` is written verbatim (single-plan compatibility path)
        when the ledger is unreachable or every live plan is unresolvable;
        ``fallback=None`` (the retirement-refresh caller) means RETRACT the
        signal in that case rather than re-asserting a goal for a plan that
        just went terminal. Retracting is the point: leaving the previously
        written file in place is what let a retired goal keep challenging
        session stop (Plan 00320).

        RV3-m3: ``session_id`` is registered as an owner of every plan its
        OWN combined text just named (:meth:`_extend_ownership`), not only
        the one plan that triggered this write -- a session's `/goal`
        already lists every live ledgered plan project-wide (that is what
        makes it COMBINED), so a session that never touched some other named
        plan directly still reads it in its own text, and without this that
        other plan's later completion never refreshed this session either.
        """
        try:
            ledger = self._open_ledger()
        except RuntimeError as e:
            logger.warning("goal_injection: combined signal skipped (no project context): %s", e)
            return self._write_fallback(session_id, fallback, fallback_plan_number)

        plan_dir = plan_md_path.parent.parent
        refs: list[LivePlanRef] = ledger.live_plan_refs(plan_dir)
        if not refs:
            return self._write_fallback(session_id, fallback, fallback_plan_number)

        payload = self._render_combined(refs)
        if payload is None:
            # Live plans exist and we simply could not render them (e.g. a
            # malformed plan number). That is NOT a retirement, so it must not
            # reach the retract path: clearing here would empty the /goal slot
            # while the ledger still reports work owed.
            logger.warning(
                "goal_injection: combined render failed for %d live plan(s); "
                "leaving the existing goal signal untouched",
                len(refs),
            )
            return None
        plan_numbers_field, combined = payload
        self._extend_ownership(ledger, session_id, refs)
        return write_goal_signal(session_id, plan_numbers_field, combined, _SOURCE_STATUS_FLIP)

    def _render_combined(self, refs: list[LivePlanRef]) -> tuple[str, str] | None:
        """Render the combined ``/goal`` payload from an already-fetched
        live-plan set: ``(plan_numbers_field, joined_text)``, or ``None``
        when rendering failed (e.g. a malformed plan number).

        RV3-m5: split out of ``_write_combined_signal`` so
        ``_maybe_refresh_on_retirement`` can render ONCE and write the same
        text to every owner, instead of re-deriving it (a full live-plan-
        directory read) once PER owner. ``refs`` is assumed non-empty; the
        empty case is each caller's own to handle (it means something
        different at each: the single-plan fallback vs. a full retraction).
        """
        live_plans = [
            LivePlan(
                plan_number=ref.plan_number,
                plan_title=extract_plan_title(ref.plan_text),
                plan_path=f"{self._plan_dir()}/{ref.plan_folder}",
            )
            for ref in refs
        ]
        combined = render_combined_goal_line(live_plans, mode=self._mode, raw_lines=self._lines)
        if combined is None:
            return None
        plan_numbers_field = ",".join(sorted(plan.plan_number for plan in live_plans))
        return plan_numbers_field, combined

    @staticmethod
    def _extend_ownership(ledger: GoalLedger, session_id: str, refs: list[LivePlanRef]) -> None:
        """RV3-m3: register ``session_id`` as an owner of every plan its own
        combined ``/goal`` text just named. Skips a plan this session
        already owns -- ``reassert_session`` locks and writes unconditionally
        even for a no-op membership check, so this avoids a redundant write
        on the common case (a session's own just-flipped plan is already in
        ``refs``). Deliberately NOT used by the retirement-refresh fan-out
        in ``_maybe_refresh_on_retirement``: that path already writes one
        signal per EXISTING owner (RV3-m5's bounded cost), and extending
        ownership there too would reintroduce an O(owners x live plans)
        write pattern for a widening this method does not need to perform on
        every single refresh.
        """
        for ref in refs:
            if not ledger.has_live_entry(session_id, ref.plan_number):
                ledger.reassert_session(session_id, ref.plan_number)

    @staticmethod
    def _write_fallback(session_id: str, fallback: str | None, plan_number: str) -> Path | None:
        if fallback is None:
            clear_goal_signal(session_id)
            return None
        return write_goal_signal(session_id, plan_number, fallback, _SOURCE_STATUS_FLIP)

    def _ledger_record(
        self, session_id: str, plan_number: str, joined: str, plan_md_path: Path
    ) -> list[str]:
        """Record the emission in the goal ledger; fail-open on any failure.

        ``plan_md_path`` is ``.../CLAUDE/Plan/<folder>/PLAN.md``; its
        grandparent is the active plan directory used for reconciliation.
        Returns the plan numbers this emission newly displaced.
        """
        try:
            ledger = self._open_ledger()
        except RuntimeError as e:
            logger.warning("goal_injection: ledger record skipped (no project context): %s", e)
            return []
        plan_dir = plan_md_path.parent.parent
        return ledger.record_emission(session_id, plan_number, joined, plan_dir)

    @staticmethod
    def _read_plan(path: Path) -> str:
        """Read the just-written PLAN.md from disk.

        RV3-m8: ``ValueError`` (not just ``OSError``) is caught alongside so
        a non-UTF-8 PLAN.md (``read_text``'s ``UnicodeDecodeError``, a
        ``ValueError`` subclass) is treated as unreadable like any other
        bad file, matching review RV-m5's tolerance for the ledger file
        itself, rather than crashing this handler under ``strict_mode``.

        Raises:
            PlanUnreadable: the file could not be read or decoded -- the
                single caller catches this explicitly, logs a WARNING, and
                takes the documented fail-open branch (no goal signal for
                this write).
        """
        try:
            return path.read_text(encoding="utf-8")
        except (OSError, ValueError) as e:
            raise PlanUnreadable(f"could not read {path}: {e}") from e

    @staticmethod
    def _record_latch(latches: dict[tuple[str, str], bool], key: tuple[str, str]) -> None:
        """Set ``key`` in ``latches`` with FIFO eviction at
        ``_MAX_TRACKED_LATCHES``. RV3-m4: shared by ``self._fired`` and
        ``self._reasserted`` -- both are per-``(session, plan)`` in-memory
        latches, and both need the SAME bound (a long-lived daemon touched
        by hundreds of distinct sessions must not leak memory in either
        map), so one bounded-insert helper serves both instead of each
        reimplementing FIFO eviction.
        """
        if key not in latches and len(latches) >= _MAX_TRACKED_LATCHES:
            del latches[next(iter(latches))]
        latches[key] = True

    def get_claude_md(self) -> str | None:
        return (
            "## goal_injection — plan-start goal signal for the ccy supervisor\n\n"
            "PostToolUse advisory (never blocks; ships disabled). When a `PLAN.md` "
            "Write/Edit under `CLAUDE/Plan/` (never `Completed/`) is a REAL "
            "TRANSITION to `**Status**: In Progress` — not merely a write that "
            "lands on a plan already reading In Progress — the daemon writes a "
            "`<session>.goal-intent` signal; the ccy PTY supervisor — if armed and "
            "watching — types a single-line `/goal 🤖 [ccy-supervisor] ...` message "
            "into the foreground chat. An Edit whose replaced span never touches "
            "the Status line, or a Write that rewrites an already-In-Progress plan "
            "(checked against the file's OWN repository's git HEAD, not "
            "necessarily the project root's), emits nothing THROUGH THE FLIP "
            "PATH: no ledger record, no displacement advisory (ledger 00466 N3). "
            "Fires once per plan per session thereafter (the latch is in-memory "
            "and resets on a new session). A session touching an already-live "
            "plan without flipping it still gets its own goal signal (re)written, "
            "once per (session, plan) per daemon lifetime, without a real flip's "
            "ledger record or displacement advisory (review M3/RV-m3) — this "
            "restores Plan 00269's 'goal survives a session restart' intent, "
            "including a resume with the SAME session id, that N3's flip-only "
            "rule otherwise silently dropped; a session that already flipped a "
            "DIFFERENT plan of its own does not implicitly absorb an unrelated "
            "plan it merely touches. Ownership is additive (review RV-M1): "
            "every session ever handed a plan's goal keeps its own claim, so a "
            "plan going terminal under ANY owning session's write refreshes "
            "every owner's own signal, not just whichever session's write "
            "triggered the check. A completing write is detected via the "
            "persisted ledger, not the in-memory latch, so it also survives a "
            "daemon restart (review M2). Manual fallback / debug tool: "
            "`bin/hooks-daemon inject-goal NNNNN` (requires `CLAUDE_CODE_SESSION_ID` "
            "in the environment, i.e. run it from the session to be targeted).\n\n"
            "**An injected goal is machine-generated** — it always opens with the "
            "machine-origin marker and a 'NOT human authorisation' clause, and can "
            "never satisfy any human-gated rule (release publishing, artefact "
            "publishing, unproven branch deletion).\n\n"
            "**Concurrent plans are tracked in a goal ledger** (Plan 00276) that is "
            "the SOURCE OF TRUTH: the /goal slot holds ONE condition (last writer "
            "wins), so every emission is recorded in `goal-ledger.json` under the "
            "daemon untracked dir. Since Plan 00299 the signal this handler writes "
            "is a COMBINED VIEW of every still-live ledgered plan for the session — "
            "one live plan renders byte-for-byte identically to the single-plan "
            "text; two or more render one line naming every live plan number. A "
            "plan reaching a terminal status re-renders the signal to drop it "
            "without disturbing any other live plan's contribution. Emitting a "
            "goal while another ledgered plan is still In Progress also injects a "
            "displacement advisory naming it, and the Stop hook challenges "
            "unexplained stops on behalf of EVERY still-live ledgered plan — the "
            "combined `/goal` text now agrees with that check. Entries retire when "
            "their plan reaches a terminal status or is archived.\n\n"
            "**Configure** via `handlers.post_tool_use.goal_injection.options`: "
            "`mode: additive` (default) merges your `lines` "
            "(`{id, text, enabled}`) onto the built-in set — a matching `id` "
            "overrides in place; `mode: replace` uses only your lines. The fixed "
            "header marker line is never overridable or removable. Placeholders: "
            "`{plan_number}`, `{plan_title}`, `{plan_path}` (closed set — an "
            "unknown token skips the line). Optional authorisation lines "
            "(`subagents-encouraged`, `qa-review-subagents`) ship disabled; their "
            "vetted text points at `standing_authorisations` rather than asserting "
            "fresh consent — enable them only as a deliberate repository-owner act."
        )

    def get_acceptance_tests(self) -> list[Any]:
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        # Deliberately NO `tool_payload` (Plan 00243). Both tests below are
        # stateful SEQUENCES -- set a status, then observe a file or an
        # advisory that appears as a consequence -- and the second additionally
        # depends on the first having already run this session.
        #
        # `ToolPayload` expresses exactly one tool call. Declaring one here
        # would capture the middle step and silently drop the observation that
        # IS the assertion, leaving a probe that dispatches cleanly and checks
        # nothing. A harness must keep skipping these with their reason shown.
        return [
            AcceptanceTest(
                title="plan flip to In Progress writes a goal-intent signal",
                command=(
                    "Use the Edit tool to set a scratch plan's PLAN.md "
                    "'**Status**:' line to 'In Progress', then verify a "
                    "'<session>.goal-intent' file appeared in the "
                    "context-sidecar untracked directory."
                ),
                harness_cannot_produce=(
                    "The assertion is not about the hook's answer — this handler "
                    "always ALLOWs — but about a FILE it writes as a side effect, "
                    "and the harness compares decisions and message patterns only. "
                    "Dispatching the payload would report a meaningless pass while "
                    "checking nothing, which is worse than a skip. Convertible by "
                    "letting a block declare a post-dispatch filesystem assertion. "
                    "Covered by "
                    "tests/unit/handlers/post_tool_use/test_goal_injection.py."
                ),
                description=(
                    "With goal_injection enabled, an Edit that FLIPS an active "
                    "PLAN.md's Status line to In Progress produces exactly one "
                    "goal-intent signal for this session (ledger 00466 N3: an "
                    "edit that merely lands on an ALREADY In-Progress plan must "
                    "not)."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes=(
                    "Observe-only: writes a small JSON file under untracked/; "
                    "nothing is injected unless a supervisor is armed."
                ),
                test_type=TestType.CONTEXT,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="second In Progress plan advises goal displacement",
                command=(
                    "With one scratch plan already flipped to In Progress this "
                    "session, use the Edit tool to flip a SECOND scratch plan's "
                    "PLAN.md '**Status**:' line to 'In Progress', then verify a "
                    "system-reminder advisory names the first plan as displaced."
                ),
                harness_cannot_produce=(
                    "Needs TWO ordered dispatches sharing one session: the "
                    "displacement advisory only exists because an earlier flip was "
                    "ledgered. The harness gives every probe its own session id — "
                    "deliberately, so one probe cannot mute another's disclosure "
                    "ladder — so the precondition is the very thing that isolation "
                    "prevents. Covered by "
                    "tests/unit/handlers/post_tool_use/test_goal_injection.py."
                ),
                description=(
                    "Plan 00276: emitting a goal while another ledgered plan is "
                    "still In Progress marks the older ledger entry displaced and "
                    "injects an advisory naming it."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"GOAL DISPLACED", r"\d{5}"],
                safety_notes=(
                    "Observe-only: writes goal-ledger.json under untracked/; never blocks the edit."
                ),
                test_type=TestType.CONTEXT,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=False,
            ),
        ]
