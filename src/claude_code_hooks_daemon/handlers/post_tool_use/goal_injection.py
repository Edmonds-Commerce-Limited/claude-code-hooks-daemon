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

Trigger semantics are STATE-based, not transition-based (PLAN.md Task 2.1):
the handler observes single writes and its once-per-``(plan, session)`` latch
is in-memory, so the first qualifying write in a NEW session re-fires — which
is what re-establishes the goal after a session restart.

**Multi-plan combined signal (Plan 00299)**: the upstream `/goal` slot is a
single, last-writer-wins value, so under concurrent plans the goal ledger
(``goal_ledger.GoalLedger``, per ``(plan_number, session_id)``) is the SOURCE
OF TRUTH, and the signal this handler writes is a RENDERED VIEW of every
still-live ledgered plan for the session (``render_combined_goal_line``): one
live plan renders byte-for-byte identically to the pre-00299 single-plan
text; two or more render one combined work line naming every live plan
number. A plan reaching a terminal status re-renders the signal to drop it
(``_maybe_refresh_on_retirement``), without disturbing any other still-live
plan's contribution. The supervisor's own thrash guard (``last_goal_text``)
skips re-typing an unchanged combined `/goal`.

Opt-in (``get_default_enabled() -> False``); never blocks.
"""

import json
import logging
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar, Final

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, HookInputField, Priority
from claude_code_hooks_daemon.constants.tools import ToolName
from claude_code_hooks_daemon.core import BlockingResult, Decision
from claude_code_hooks_daemon.core.handler import WorkspaceScope
from claude_code_hooks_daemon.core.handler_bases import PostToolUseHandlerBase
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.core.utils import get_file_path
from claude_code_hooks_daemon.plan_qa.model import TERMINAL_STATUSES, PlanDoc
from claude_code_hooks_daemon.utils.goal_ledger import LEDGER_FILENAME, GoalLedger, LivePlanRef

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
# facade's plan_dir (Plan 00288 Task 4.2), not this literal fallback — see
# _FALLBACK_PLAN_DIR and _plan_dir()/_plan_path_pattern() below.
_FALLBACK_PLAN_DIR: Final[str] = "CLAUDE/Plan"
_COMPLETED_SEGMENT: Final[str] = "/Completed/"
_STATUS_IN_PROGRESS_RE: Final[re.Pattern[str]] = re.compile(
    r"^\*\*Status\*\*:\s*In Progress\s*$", re.MULTILINE
)
_PLAN_MD_FILENAME: Final[str] = "PLAN.md"
_TITLE_HEADING_PREFIX: Final[str] = "# "
# Strips a redundant "Plan NNNNN: " lead-in from the heading text, since the
# work line already states the plan number.
_TITLE_PLAN_PREFIX_RE: Final[re.Pattern[str]] = re.compile(r"^Plan\s+\d+\s*:\s*")

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

    Failures are logged, never raised — this is a best-effort sensor signal
    and must never break the tool call that triggered it. Returns the final
    path, or None on failure.
    """
    try:
        target_dir = ProjectContext.daemon_untracked_dir() / _SIGNAL_SUBDIR
        target_dir.mkdir(parents=True, exist_ok=True)
        stem = _UNSAFE_SESSION_CHARS.sub("_", session_id) if session_id else _SESSION_ID_FALLBACK
        final_path = target_dir / f"{stem}{_SIGNAL_SUFFIX}"
        tmp_path = target_dir / f".{stem}.{os.getpid()}.tmp"
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
    """Remove the ``<session>.goal-intent`` signal file (Plan 00320).

    The retract counterpart to :func:`write_goal_signal`. Declining to
    REWRITE the signal is not the same as retracting it: the file written
    when the goal was emitted survives, so a retired goal keeps being read
    as live. An already-absent file counts as success.

    Failures are logged, never raised — same best-effort contract as the
    writer. Returns True if no signal file remains for this session.
    """
    try:
        target_dir = ProjectContext.daemon_untracked_dir() / _SIGNAL_SUBDIR
        stem = _UNSAFE_SESSION_CHARS.sub("_", session_id) if session_id else _SESSION_ID_FALLBACK
        (target_dir / f"{stem}{_SIGNAL_SUFFIX}").unlink(missing_ok=True)
        return True
    except RuntimeError as e:
        logger.warning("goal_injection: skipping signal clear (no project context): %s", e)
        return False
    except OSError as e:
        logger.warning("goal_injection: failed to clear goal signal: %s", e)
        return False


def extract_plan_title(plan_text: str) -> str:
    """First ``# `` heading of PLAN.md, minus any leading ``Plan NNNNN:``."""
    for raw_line in plan_text.splitlines():
        stripped = raw_line.strip()
        if stripped.startswith(_TITLE_HEADING_PREFIX):
            heading = stripped[len(_TITLE_HEADING_PREFIX) :].strip()
            return _TITLE_PLAN_PREFIX_RE.sub("", heading)
    return ""


class GoalInjectionHandler(PostToolUseHandlerBase):
    """Write a goal-intent signal when a plan flips to In Progress.

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

    def get_default_enabled(self) -> bool:
        """Opt-in: only useful when a PTY supervisor is watching."""
        return False

    def _plan_dir(self) -> str:
        """Configured plan directory (facade, or the matching default)."""
        layout = self._project_layout
        return layout.plan_dir if layout is not None else _FALLBACK_PLAN_DIR

    def _plan_path_pattern(self) -> re.Pattern[str]:
        """Compile the trigger pattern from the configured plan directory.

        Matches ``<plan_dir>/<digits>-<name>/PLAN.md`` (the ``/Completed/``
        exclusion is checked separately by callers via _COMPLETED_SEGMENT).
        """
        return re.compile(rf"{re.escape(self._plan_dir())}/(\d+-[^/]+)/PLAN\.md$")

    @staticmethod
    def _is_inside_project(file_path: str) -> bool:
        """True when ``file_path`` lives under this project's root.

        The trigger pattern is applied with ``search``, so any path merely
        CONTAINING ``<plan_dir>/NNNNN-name/PLAN.md`` matches wherever it
        lives — while the rendered goal re-points it at the PROJECT's plan
        directory. A scratch plan under /tmp would therefore emit a live
        goal naming a project path that does not exist, and an
        unsatisfiable goal cannot be discharged by doing the work
        (Plan 00320).

        Fails OPEN — an unresolvable path or uninitialised context keeps the
        pre-existing behaviour rather than silently disabling the trigger,
        matching this module's best-effort sensor contract.
        """
        try:
            root = ProjectContext.project_root().resolve()
        except (RuntimeError, OSError) as e:
            logger.warning("goal_injection: project-root check skipped: %s", e)
            return True
        try:
            Path(file_path).resolve().relative_to(root)
        except (ValueError, OSError):
            return False
        return True

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

        An In-Progress flip renders+records this plan then writes the
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

        plan_text = self._read_plan(Path(file_path))
        if plan_text is None:
            return BlockingResult(decision=Decision.ALLOW)

        session_id = str(hook_input.get(HookInputField.SESSION_ID, "") or "")

        if not _STATUS_IN_PROGRESS_RE.search(plan_text):
            self._maybe_refresh_on_retirement(session_id, plan_number, Path(file_path), plan_text)
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
        # qualifying event, or it never gets a /goal at all.
        self._record_latch(latch_key)

        if displaced:
            plans = ", ".join(displaced)
            verb = "it is" if len(displaced) == 1 else "they are"
            advisory = _DISPLACEMENT_ADVISORY_TEMPLATE.format(
                plans=plans, new_plan=plan_number, verb=verb
            )
            return BlockingResult(decision=Decision.ALLOW, context=[advisory])
        return BlockingResult(decision=Decision.ALLOW)

    def _maybe_refresh_on_retirement(
        self, session_id: str, plan_number: str, plan_md_path: Path, plan_text: str
    ) -> None:
        """Re-render the combined signal when a LEDGERED plan just retired.

        Retirement itself is detected lazily inside the ledger (every
        ``live_plan_refs`` call re-reads each live plan's current PLAN.md),
        so this only decides whether re-rendering is worthwhile: a terminal
        write for a plan this session never emitted a goal for has nothing
        to refresh, so it is skipped fast without touching the ledger.
        """
        if not session_id or not self._fired.get((session_id, plan_number)):
            return
        doc = PlanDoc.parse(plan_text)
        if doc.status is None or doc.status not in TERMINAL_STATUSES:
            return
        self._write_combined_signal(
            session_id, plan_md_path, fallback=None, fallback_plan_number=plan_number
        )

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
        """
        try:
            ledger_path = ProjectContext.daemon_untracked_dir() / LEDGER_FILENAME
        except RuntimeError as e:
            logger.warning("goal_injection: combined signal skipped (no project context): %s", e)
            return self._write_fallback(session_id, fallback, fallback_plan_number)

        plan_dir = plan_md_path.parent.parent
        refs: list[LivePlanRef] = GoalLedger(ledger_path).live_plan_refs(plan_dir)
        if not refs:
            return self._write_fallback(session_id, fallback, fallback_plan_number)

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
            return self._write_fallback(session_id, fallback, fallback_plan_number)

        plan_numbers_field = ",".join(sorted(plan.plan_number for plan in live_plans))
        return write_goal_signal(session_id, plan_numbers_field, combined, _SOURCE_STATUS_FLIP)

    @staticmethod
    def _write_fallback(session_id: str, fallback: str | None, plan_number: str) -> Path | None:
        if fallback is None:
            clear_goal_signal(session_id)
            return None
        return write_goal_signal(session_id, plan_number, fallback, _SOURCE_STATUS_FLIP)

    @staticmethod
    def _ledger_record(
        session_id: str, plan_number: str, joined: str, plan_md_path: Path
    ) -> list[str]:
        """Record the emission in the goal ledger; fail-open on any failure.

        ``plan_md_path`` is ``.../CLAUDE/Plan/<folder>/PLAN.md``; its
        grandparent is the active plan directory used for reconciliation.
        Returns the plan numbers this emission newly displaced.
        """
        try:
            ledger_path = ProjectContext.daemon_untracked_dir() / LEDGER_FILENAME
        except RuntimeError as e:
            logger.warning("goal_injection: ledger skipped (no project context): %s", e)
            return []
        plan_dir = plan_md_path.parent.parent
        return GoalLedger(ledger_path).record_emission(session_id, plan_number, joined, plan_dir)

    def _read_plan(self, path: Path) -> str | None:
        """Read the just-written PLAN.md from disk; None when unreadable."""
        try:
            return path.read_text(encoding="utf-8")
        except OSError as e:
            logger.warning("goal_injection: could not read %s: %s", path, e)
            return None

    def _record_latch(self, key: tuple[str, str]) -> None:
        if key not in self._fired and len(self._fired) >= _MAX_TRACKED_LATCHES:
            del self._fired[next(iter(self._fired))]
        self._fired[key] = True

    def get_claude_md(self) -> str | None:
        return (
            "## goal_injection — plan-start goal signal for the ccy supervisor\n\n"
            "PostToolUse advisory (never blocks; ships disabled). When a `PLAN.md` "
            "Write/Edit under `CLAUDE/Plan/` (never `Completed/`) results in "
            "`**Status**: In Progress`, the daemon writes a `<session>.goal-intent` "
            "signal; the ccy PTY supervisor — if armed and watching — types a "
            "single-line `/goal 🤖 [ccy-supervisor] ...` message into the foreground "
            "chat. Fires once per plan per session (state-based: the first "
            "qualifying edit in a NEW session re-fires, re-establishing the goal "
            "after a restart). Manual fallback / debug tool: "
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

        return [
            AcceptanceTest(
                title="plan flip to In Progress writes a goal-intent signal",
                command=(
                    "Use the Edit tool to set a scratch plan's PLAN.md "
                    "'**Status**:' line to 'In Progress', then verify a "
                    "'<session>.goal-intent' file appeared in the "
                    "context-sidecar untracked directory."
                ),
                description=(
                    "With goal_injection enabled, an active PLAN.md write whose "
                    "resulting status reads In Progress produces exactly one "
                    "goal-intent signal for this session."
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
                description=(
                    "Plan 00276: emitting a goal while another ledgered plan is "
                    "still In Progress marks the older ledger entry displaced and "
                    "injects an advisory naming it."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"GOAL DISPLACED", r"\d{5}"],
                safety_notes=(
                    "Observe-only: writes goal-ledger.json under untracked/; "
                    "never blocks the edit."
                ),
                test_type=TestType.CONTEXT,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=False,
            ),
        ]
