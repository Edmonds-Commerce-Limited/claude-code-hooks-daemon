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

Opt-in (``get_default_enabled() -> False``); never blocks.
"""

import json
import logging
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, HookInputField, Priority
from claude_code_hooks_daemon.constants.tools import ToolName
from claude_code_hooks_daemon.core import BlockingResult, Decision
from claude_code_hooks_daemon.core.handler_bases import PostToolUseHandlerBase
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.core.utils import get_file_path

logger = logging.getLogger(__name__)

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
_WORK_LINE_TEXT: Final[str] = (
    "Work on Plan {plan_number} ({plan_title}) at {plan_path} until completion."
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

# ── Trigger detection ──────────────────────────────────────────────────────
# Matches CLAUDE/Plan/<digits>-<name>/PLAN.md, NOT inside Completed/ — the
# same shape recovery_cron_advisor uses for the same trigger surface.
_PLAN_PATH_RE: Final[re.Pattern[str]] = re.compile(r"CLAUDE/Plan/(\d+-[^/]+)/PLAN\.md$")
_COMPLETED_SEGMENT: Final[str] = "/Completed/"
_STATUS_IN_PROGRESS_RE: Final[re.Pattern[str]] = re.compile(
    r"^\*\*Status\*\*:\s*In Progress\s*$", re.MULTILINE
)
_PLAN_DIR_PREFIX: Final[str] = "CLAUDE/Plan/"
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
        stem = (
            _UNSAFE_SESSION_CHARS.sub("_", session_id) if session_id else _SESSION_ID_FALLBACK
        )
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

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """True for a Write/Edit landing on an ACTIVE plan's PLAN.md."""
        if hook_input.get(HookInputField.TOOL_NAME) not in (ToolName.WRITE, ToolName.EDIT):
            return False
        file_path = get_file_path(hook_input) or ""
        normalized = file_path.replace("\\", "/")
        if _COMPLETED_SEGMENT in normalized:
            return False
        return _PLAN_PATH_RE.search(normalized) is not None

    def handle(self, hook_input: dict[str, Any]) -> BlockingResult:
        """Render and write the goal-intent signal; always ALLOW."""
        file_path = get_file_path(hook_input) or ""
        normalized = file_path.replace("\\", "/")
        match = _PLAN_PATH_RE.search(normalized)
        if match is None:
            return BlockingResult(decision=Decision.ALLOW)
        folder = match.group(1)
        plan_number = folder.split("-", 1)[0].zfill(5)

        plan_text = self._read_plan(Path(file_path))
        if plan_text is None or not _STATUS_IN_PROGRESS_RE.search(plan_text):
            return BlockingResult(decision=Decision.ALLOW)

        session_id = str(hook_input.get(HookInputField.SESSION_ID, "") or "")
        latch_key = (session_id, plan_number)
        if self._once_per_plan_per_session and self._fired.get(latch_key):
            return BlockingResult(decision=Decision.ALLOW)

        joined = render_goal_line(
            plan_number,
            extract_plan_title(plan_text),
            f"{_PLAN_DIR_PREFIX}{folder}",
            mode=self._mode,
            raw_lines=self._lines,
        )
        if joined is None:
            return BlockingResult(decision=Decision.ALLOW)
        written = write_goal_signal(session_id, plan_number, joined, _SOURCE_STATUS_FLIP)
        if written is not None:
            self._record_latch(latch_key)
        return BlockingResult(decision=Decision.ALLOW)

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
        ]
