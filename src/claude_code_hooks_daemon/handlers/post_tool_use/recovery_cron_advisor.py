"""RecoveryCronAdvisorHandler - lifecycle advisory for failsafe recovery crons.

Fires on PostToolUse events that represent the three lifecycle moments of a
CLAUDE/Plan/<digits>-<name>/PLAN.md:

  1. CREATION  — a new PLAN.md is written, or mkplan.bash is invoked.
  2. PROGRESS  — an existing PLAN.md is edited touching task-status icons
                 (⬜/🔄/✅).
  3. COMPLETION — the plan's **Status** line is changed to Complete/Completed.

On each phase the handler injects advisory context:
  - Creation:    prompt the agent to create a non-durable hourly recovery cron.
  - Progress:    remind agent to verify the cron is still running (CronList).
  - Completion:  warn first — keep the cron while the session is still live
                 (deleting it strands a live session with no recovery coverage);
                 CronDelete only once the session is genuinely finished.

IMPORTANT: this is a FAILSAFE RECOVERY cron, NOT a heartbeat.  The agent must
never pace itself to the cron; work must proceed at full speed until an
external factor (API error, rate limit, usage limit) actually stalls it.

Decision D1 (PLAN.md): crons are created non-durable (durable:false) so they
are session-only and cleaned up naturally on session exit.

Decision D2 (PLAN.md): dedup is via in-session per-plan tracking owned by the
handler.  PROGRESS uses a per-plan edit counter and advises on every Nth
progress edit for a given plan (independent of global daemon traffic).
CREATION and COMPLETION are state TRANSITIONS rather than ongoing activity,
so each advises only on the FIRST occurrence for a given plan folder, then
stays silent for that plan.  The agent uses CronList to avoid duplicate
creates.

Decision D4 (PLAN.md): this is a PostToolUse handler, not an extension of the
PreToolUse plan_workflow handler.
"""

import re
from enum import Enum
from typing import Any, Final

from claude_code_hooks_daemon.constants import (
    HandlerID,
    HandlerTag,
    HookInputField,
    Priority,
    ToolName,
)
from claude_code_hooks_daemon.core import BlockingResult, Decision
from claude_code_hooks_daemon.core.handler_bases import PostToolUseHandlerBase
from claude_code_hooks_daemon.core.utils import get_bash_command, get_file_path

# ─── Lifecycle phase ──────────────────────────────────────────────────────────


class LifecyclePhase(Enum):
    """The detected lifecycle phase of a PLAN.md interaction."""

    CREATION = "creation"
    PROGRESS = "progress"
    COMPLETION = "completion"


# ─── Path patterns ────────────────────────────────────────────────────────────

# The plan-dir portion of the trigger pattern (<plan_dir>/<digits>-<name>/
# PLAN.md, NOT inside Completed/) is built per-handler-instance from the
# ProjectLayout facade's plan_dir (Plan 00288 Task 4.2), not this literal
# fallback — see RecoveryCronAdvisorHandler._plan_dir() and
# _plan_path_pattern() below.
_FALLBACK_PLAN_DIR: Final[str] = "CLAUDE/Plan"


def _plan_path_pattern(plan_dir: str) -> re.Pattern[str]:
    """Compile the trigger pattern for the given configured plan directory."""
    return re.compile(rf"{re.escape(plan_dir)}/(\d+-[^/]+)/PLAN\.md$", re.IGNORECASE)


# Excluded: anything already in the Completed/ archive
_COMPLETED_SEGMENT: Final[str] = "/Completed/"

# ─── Content patterns ─────────────────────────────────────────────────────────

# Matches a **Status** line whose VALUE is exactly Complete/Completed.
# Anchored to the end of the line (re.MULTILINE) so prose such as
# "**Status**: Complete the migration before merging" or "Completion pending"
# does NOT trigger the completion teardown advisory on an active plan.
# re.IGNORECASE keeps the match case-insensitive consistently (e.g. lowercase
# "**status**:" still matches) as the docstring promises.
_STATUS_COMPLETE_RE: Final[re.Pattern[str]] = re.compile(
    r"\*\*Status\*\*:\s*Complete[d]?\s*$",
    re.MULTILINE | re.IGNORECASE,
)

# Matches task-status icons used in PLAN.md task lists: the documented set is
# ⬜ (not started), ✅ (completed), and 🔄 (in progress).  A single deduped
# character class — ⚠️ (warning) is NOT a documented task icon and must not be
# misclassified as PROGRESS.
_TASK_STATUS_ICON_RE: Final[re.Pattern[str]] = re.compile(r"[⬜✅\U0001f504]")

# Matches mkplan.bash invocations in Bash commands
_MKPLAN_BASH_RE: Final[re.Pattern[str]] = re.compile(
    r"mkplan\.bash\b",
)

# ─── Cooldown configuration ───────────────────────────────────────────────────

# Advise on the 1st progress edit for a plan, then once every Nth progress edit
# thereafter.  The counter is a per-plan PROGRESS edit count owned by the
# handler — it is incremented only on a PROGRESS-classified edit for that plan,
# so the cadence is independent of global daemon traffic (unlike the old
# total_count approach, which was exhausted in a handful of unrelated tool
# calls and re-fired on practically every PLAN.md edit).
_PROGRESS_ADVISE_INTERVAL: Final[int] = 5

# First progress edit per plan is recorded at this count and always advises.
_PROGRESS_COUNT_START: Final[int] = 1

# Maximum number of plan folders tracked in each per-plan tracking map
# (progress counts, creation-seen, completion-seen). Bounds memory on the
# daemon-lifetime singleton: when exceeded, the oldest inserted entry is
# evicted (insertion-ordered dict). A plan re-entering after eviction simply
# restarts tracking for that phase — harmless for an advisory.
_MAX_TRACKED_PLANS: Final[int] = 256

# Fallback key for CREATION events with no derivable plan folder — a Bash
# invocation of mkplan.bash carries only the shell command in its hook input,
# not the folder the script created on disk. Every such invocation in a
# session shares this one bucket, so a repeat mkplan.bash call is treated as
# the same identity for once-per-plan gating (see _resolve_plan_folder).
#
# CONSEQUENCE, stated plainly rather than left to be derived: creating a SECOND,
# genuinely different plan via mkplan.bash in one session is silent — it is not
# a repeat, but it is bucketed as one. Accepted deliberately, because the advice
# it would repeat is "CronList first, reuse the cron already running": there is
# exactly ONE recovery cron per session (Plan 00247), so by the second plan it
# already exists and the agent has already been told how to handle it. The
# advisory is a safety net for the transition, not a per-plan entitlement.
#
# It IS now fixable — mkplan.bash prints the created folder on stdout, which a
# real event carries at HookInputField.TOOL_RESPONSE. It is not done here because
# the gain is the low-value case above, and reading the response would couple
# this handler to a payload sub-shape nothing else in it depends on. Revisit if
# multi-plan sessions become common, not before.
_MKPLAN_SENTINEL_KEY: Final[str] = "__mkplan__"

# ─── Canonical recovery-cron prompt ──────────────────────────────────────────

# Verbatim from PLAN.md "Canonical recovery-cron prompt" section.
_CANONICAL_CRON_PROMPT: Final[str] = (
    "**FAILSAFE RECOVERY CHECK (automated hourly safety net — NOT a heartbeat).**\n"
    "If your most recent work on the active plan/task was interrupted by an\n"
    "*external* factor (Claude API error/overload, rate limit, 5-hour usage limit,\n"
    "network failure) and is now resumable, resume it immediately and carry it to\n"
    "completion. If you are blocked **only** on human input, do nothing and keep\n"
    "waiting. If work is already proceeding normally, this is a **no-op** — do not\n"
    "interrupt, restart, or duplicate anything in flight. Never treat this as a\n"
    "heartbeat or pacing signal: between checks, continue at full speed until an\n"
    "external factor actually stops you — waiting for the cron is an own goal. Do\n"
    "NOT delete this cron merely because a tick finds nothing to resume: it is\n"
    "non-durable and ends automatically when the session exits, and a still-live\n"
    "session stays exposed to the next rate limit without it. Remove it (CronDelete)\n"
    "only once the session is genuinely finished with no further work."
)

# ─── Advisory text per phase ──────────────────────────────────────────────────

_CREATION_GUIDANCE: Final[str] = (
    "Recovery-cron setup is part of executing this plan.\n\n"
    "There must be EXACTLY ONE failsafe recovery cron per session — never one\n"
    "per plan. The canonical prompt below is plan-agnostic ('the active\n"
    "plan/task'), so a single cron already covers this plan and every other one\n"
    "in this session; a second only double-fires on the same session.\n\n"
    "So CHECK BEFORE YOU CREATE:\n"
    "  1. Run CronList FIRST.\n"
    "  2. If a recurring failsafe recovery cron is already listed: REUSE it.\n"
    "     Record THAT id in this plan's JOURNAL/ day-file and create nothing.\n"
    "     If more than one is listed, CronDelete the extras so one remains.\n"
    "  3. ONLY IF none is listed, create it: CronCreate with durable:false and\n"
    "     recurring:true, on an off-:00 minute (e.g. 17 * * * * or 37 * * * *).\n"
    "     Then record its id in this plan's JOURNAL/ day-file (append a dated\n"
    "     entry at the bottom) — NOT in PLAN.md. Runtime session state is\n"
    "     journal content; PLAN.md stays a lean, curated spec.\n"
    "  4. Do NOT wait for the cron to fire — keep working immediately.\n\n"
    "This is a FAILSAFE RECOVERY cron, NOT a heartbeat. The agent must never\n"
    "pace itself to the cron. Work proceeds at full speed until an external\n"
    "factor (API error, rate limit, usage limit) actually stops it.\n\n"
    "Paste the following text verbatim as the cron prompt:\n\n"
    f"{_CANONICAL_CRON_PROMPT}"
)

_PROGRESS_GUIDANCE: Final[str] = (
    "Confirm there is EXACTLY ONE failsafe recovery cron:\n"
    "  1. Run CronList.\n"
    "  2. Exactly one recurring recovery cron listed → nothing to do.\n"
    "  3. More than one (duplicates stack when a session creates several plans)\n"
    "     → CronDelete the extras until a single one remains. They are\n"
    "     identical, so keep any one of them.\n"
    "  4. None → create one now (CronCreate, durable:false, recurring:true,\n"
    "     off-:00 minute, same canonical prompt).\n"
    "  5. Keep working — do not wait for the cron to fire."
)

_COMPLETION_GUIDANCE: Final[str] = (
    "This plan is complete. Decide about its failsafe recovery cron — but FIRST a\n"
    "warning: deleting the cron now leaves THIS still-live session with NO recovery\n"
    "coverage. If a rate limit, 5-hour usage limit, or API/network stall hits before\n"
    "the session ends, nothing will resume you.\n"
    "  • If ANY further work may happen this session (more tasks, follow-ups,\n"
    "    ongoing conversation): KEEP the cron. It is non-durable — it dies\n"
    "    automatically on session exit — and is a no-op whenever nothing is\n"
    "    resumable, so keeping it costs nothing.\n"
    "  • ONLY if you are certain the session is wrapping up with no further work:\n"
    "    run CronDelete with the cron ID you recorded (CronList to locate it if\n"
    "    unrecorded)."
)


# ─── Phase detection helper ───────────────────────────────────────────────────


def _is_plan_path(file_path: str, plan_dir: str = _FALLBACK_PLAN_DIR) -> tuple[bool, str]:
    """Return (matches, plan_folder) for a file path.

    Returns (True, folder_name) when the path is an active PLAN.md under
    ``plan_dir``. Returns (False, '') when excluded (Completed/) or not a
    plan path.
    """
    normalized = file_path.replace("\\", "/")
    if _COMPLETED_SEGMENT in normalized:
        return False, ""
    m = _plan_path_pattern(plan_dir).search(normalized)
    if not m:
        return False, ""
    return True, m.group(1)


# ─── Bounded per-plan tracking helper ─────────────────────────────────────────


def _evict_oldest_tracked_entry_if_full(tracked: dict[str, Any]) -> None:
    """Evict the oldest inserted key from a bounded per-plan tracking map.

    Shared by every per-plan tracking map on this handler (progress counts,
    creation-seen markers, completion-seen markers) so the bound
    (_MAX_TRACKED_PLANS) and eviction policy — oldest-first, relying on
    insertion-ordered dict iteration — live in exactly one place rather than
    being copy-pasted per map.  No-op while the map has room.
    """
    if len(tracked) >= _MAX_TRACKED_PLANS:
        oldest_key = next(iter(tracked))
        del tracked[oldest_key]


# Matches a bare Complete/Completed VALUE occupying its own line (no
# **Status**: prefix).  Used to recognise a partial-line completion edit whose
# new_string replaces only the status value (e.g. old line "**Status**: In
# Progress" → new_string "Complete").
_BARE_COMPLETE_VALUE_RE: Final[re.Pattern[str]] = re.compile(
    r"^\s*Complete[d]?\s*$",
    re.IGNORECASE,
)

# Matches the **Status**: prefix anywhere in a string (value-agnostic).  Used to
# detect that an Edit's old_string targeted the status line.
_STATUS_PREFIX_RE: Final[re.Pattern[str]] = re.compile(
    r"\*\*Status\*\*:",
    re.IGNORECASE,
)


def _text_has_progress_markers(text: str) -> bool:
    """Return True if text contains task-status icons.

    Plan 00190: a dated note appended to PLAN.md is deliberately NOT a
    progress marker. The retired ``## Notes & Updates`` section is the
    anti-pattern the plan/journal separation removes, so treating an edit to
    it as first-class progress rewarded the very behaviour being eliminated.
    Every genuine progress edit touches a task-status icon under the plan
    template's own task grammar, so no real signal is lost.
    """
    return bool(_TASK_STATUS_ICON_RE.search(text))


def _edit_results_in_status_complete(new_string: str, old_string: str) -> bool:
    """Return True if applying this Edit yields a ``**Status**: Complete[d]`` line.

    Robustly detects completion for partial-line edits that PROGRESS would
    otherwise mis-classify.  Two cases:

    1. ``new_string`` itself contains a complete, anchored ``**Status**:
       Complete[d]`` line (full-line replacement).
    2. ``old_string`` targeted the status line (it contains the ``**Status**:``
       prefix) and ``new_string`` is the bare ``Complete[d]`` value replacing
       only the old value — so the resulting line reads ``**Status**: Complete``
       even though ``new_string`` alone lacks the prefix.
    """
    if _STATUS_COMPLETE_RE.search(new_string):
        return True
    if _STATUS_PREFIX_RE.search(old_string) and _BARE_COMPLETE_VALUE_RE.search(new_string):
        return True
    return False


def _detect_lifecycle_phase(
    hook_input: dict[str, Any], plan_dir: str = _FALLBACK_PLAN_DIR
) -> LifecyclePhase | None:
    """Detect the plan lifecycle phase from a PostToolUse hook input.

    Returns the detected LifecyclePhase or None if this event is not relevant.

    Detection rules:
    - CREATION: Write to an active PLAN.md (any content) OR a Bash call to mkplan.bash.
    - COMPLETION: Write/Edit to active PLAN.md with **Status**: Complete in content.
    - PROGRESS: Edit to active PLAN.md touching task-status icons.
      (Completion takes priority over Progress when Status Complete is present.)
    """
    tool_name = hook_input.get(HookInputField.TOOL_NAME)

    # ── Bash: only mkplan.bash creates a plan ────────────────────────────────
    if tool_name == ToolName.BASH:
        command = get_bash_command(hook_input) or ""
        if _MKPLAN_BASH_RE.search(command):
            return LifecyclePhase.CREATION
        return None

    # ── Write / Edit only from here ───────────────────────────────────────────
    if tool_name not in (ToolName.WRITE, ToolName.EDIT):
        return None

    file_path = get_file_path(hook_input) or ""
    is_plan, _folder = _is_plan_path(file_path, plan_dir)
    if not is_plan:
        return None

    tool_input: dict[str, Any] = hook_input.get(HookInputField.TOOL_INPUT, {})

    if tool_name == ToolName.WRITE:
        content: str = tool_input.get("content", "")
        # Completion check first (takes priority)
        if _STATUS_COMPLETE_RE.search(content):
            return LifecyclePhase.COMPLETION
        # Any Write to an active PLAN.md that doesn't set Complete is Creation
        # UNLESS it contains progress markers (in which case it is Progress)
        if _text_has_progress_markers(content):
            return LifecyclePhase.PROGRESS
        return LifecyclePhase.CREATION

    # ── Edit tool ─────────────────────────────────────────────────────────────
    new_string: str = tool_input.get("new_string", "")
    old_string: str = tool_input.get("old_string", "")
    combined = new_string + "\n" + old_string

    if _edit_results_in_status_complete(new_string, old_string):
        return LifecyclePhase.COMPLETION

    if _text_has_progress_markers(combined):
        return LifecyclePhase.PROGRESS

    return None


# ─── Handler ─────────────────────────────────────────────────────────────────


class RecoveryCronAdvisorHandler(PostToolUseHandlerBase):
    """Advisory handler that manages failsafe recovery cron across plan lifecycle.

    Fires on three lifecycle moments:
    - Plan creation  → advise agent to create a non-durable hourly recovery cron.
    - Plan progress  → remind agent to verify the cron is still running.
    - Plan completion → warn first; keep the cron while the session is live and
      CronDelete only once the session is genuinely finished.

    The recovery cron is a FAILSAFE RECOVERY mechanism, NOT a heartbeat.  The
    agent must never pace itself to the cron; work must continue at full speed
    until an external factor actually blocks progress.

    A per-plan PROGRESS edit counter (keyed by plan folder name) advises only on
    every Nth progress edit, preventing spam on every single PLAN.md edit while
    staying independent of unrelated daemon traffic.  CREATION and COMPLETION
    are state transitions rather than ongoing activity, so each advises only
    once per plan folder — a repeat creation or a re-save of an
    already-complete plan is silent.  All three tracking maps are bounded
    (_MAX_TRACKED_PLANS) so none can grow without limit on the daemon-lifetime
    singleton.

    Opt-out: get_default_enabled() returns True (advisory-only, safe + useful, so
    on by default).  Projects that do not want it set enabled: false.
    """

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.RECOVERY_CRON_ADVISOR,
            priority=Priority.RECOVERY_CRON_ADVISOR,
            terminal=False,
            tags=[
                HandlerTag.WORKFLOW,
                HandlerTag.PLANNING,
                HandlerTag.ADVISORY,
                HandlerTag.NON_TERMINAL,
            ],
        )
        # Per-plan PROGRESS edit count: {plan_folder: number_of_progress_edits}.
        # Insertion-ordered so the oldest entry can be evicted once the map
        # exceeds _MAX_TRACKED_PLANS.
        self._progress_counts: dict[str, int] = {}
        # Per-plan CREATION / COMPLETION "seen" markers: {plan_folder: True}.
        # Presence of a key means that phase has already advised once for that
        # plan folder. Insertion-ordered so the oldest entry can be evicted
        # once a map exceeds _MAX_TRACKED_PLANS — same policy as
        # _progress_counts, via the shared _evict_oldest_tracked_entry helper.
        self._creation_seen: dict[str, bool] = {}
        self._completion_seen: dict[str, bool] = {}
        # Phase computed in matches() and reused in handle() (avoids running the
        # detection twice per event).  Set per-call; never relied on across
        # events.
        self._cached_phase: LifecyclePhase | None = None

    def get_default_enabled(self) -> bool:
        """Opt-OUT handler — ON by default (Plan 00139 follow-up).

        The handler is advisory-only (never blocks; only fires on plan-lifecycle
        PLAN.md writes), so it is safe and useful enough to ship enabled by
        default. Projects that do not want it set enabled: false in their
        .claude/hooks-daemon.yaml. Must stay consistent with the template, which
        does NOT mark this handler ``enabled: false`` (enforced by
        test_default_enabled_template_consistency).
        """
        return True

    def _plan_dir(self) -> str:
        """Configured plan directory (facade, or the matching default)."""
        layout = self._project_layout
        return layout.plan_dir if layout is not None else _FALLBACK_PLAN_DIR

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Return True if this event represents a plan lifecycle moment.

        Matches when _detect_lifecycle_phase returns a non-None phase.  The
        detected phase is cached on the instance and reused by handle() for the
        same event, so detection runs once per event rather than twice.
        """
        self._cached_phase = _detect_lifecycle_phase(hook_input, self._plan_dir())
        return self._cached_phase is not None

    def _resolve_phase(self, hook_input: dict[str, Any]) -> LifecyclePhase | None:
        """Return the phase for this event, reusing the matches() cache if set.

        Consumes the cache (resets it to None) so a stale value from a prior
        event can never leak into a later handle() call invoked without a
        preceding matches().
        """
        cached = self._cached_phase
        self._cached_phase = None
        if cached is not None:
            return cached
        return _detect_lifecycle_phase(hook_input, self._plan_dir())

    def _should_advise_progress(self, plan_folder: str) -> bool:
        """Record a progress edit for plan_folder and return whether to advise.

        Advises on the 1st progress edit and every _PROGRESS_ADVISE_INTERVAL-th
        edit thereafter.  Bounds the tracking map at _MAX_TRACKED_PLANS via the
        shared eviction helper.
        """
        count = self._progress_counts.get(plan_folder)
        if count is None:
            _evict_oldest_tracked_entry_if_full(self._progress_counts)
            count = _PROGRESS_COUNT_START
        else:
            count += 1
        self._progress_counts[plan_folder] = count
        return (count - _PROGRESS_COUNT_START) % _PROGRESS_ADVISE_INTERVAL == 0

    def _should_advise_once(self, tracked: dict[str, bool], plan_folder: str) -> bool:
        """Record plan_folder as seen and return True only the FIRST time.

        Shared by CREATION and COMPLETION, which are one-shot state
        TRANSITIONS — the meaningful event is the first one for a given plan
        folder, so a repeat creation or a re-save of an already-complete plan
        carries no new information and stays silent. This is deliberately NOT
        the PROGRESS rule (every Nth edit), which tracks ongoing activity
        rather than a transition. Bounded and evicted identically to
        _progress_counts via the shared eviction helper.
        """
        if plan_folder in tracked:
            return False
        _evict_oldest_tracked_entry_if_full(tracked)
        tracked[plan_folder] = True
        return True

    def _resolve_plan_folder(self, hook_input: dict[str, Any]) -> str:
        """Return the plan-folder key used by every per-plan tracking map.

        Derived from the file path for Write/Edit events. A Bash invocation of
        mkplan.bash carries no file path in its hook input — the daemon cannot
        see which folder the script created from the Bash tool call alone — so
        it falls back to the shared _MKPLAN_SENTINEL_KEY bucket.
        """
        file_path = get_file_path(hook_input) or ""
        _, plan_folder = _is_plan_path(file_path, self._plan_dir())
        return plan_folder or _MKPLAN_SENTINEL_KEY

    def handle(self, hook_input: dict[str, Any]) -> BlockingResult:
        """Inject advisory context appropriate for the detected lifecycle phase.

        Phase routing:
        - CREATION   → advise once per plan folder (a state transition, not
                        ongoing activity — a repeat creation write is silent).
        - COMPLETION → advise once per plan folder (same rationale — re-saving
                        an already-complete plan is silent).
        - PROGRESS   → advise on every Nth progress edit per plan.

        Returns:
            BlockingResult with ALLOW decision, and context[] when advising.
        """
        phase = self._resolve_phase(hook_input)
        if phase is None:
            return BlockingResult(decision=Decision.ALLOW)

        if phase == LifecyclePhase.CREATION:
            plan_folder = self._resolve_plan_folder(hook_input)
            if not self._should_advise_once(self._creation_seen, plan_folder):
                return BlockingResult(decision=Decision.ALLOW)
            return BlockingResult(decision=Decision.ALLOW, context=[_CREATION_GUIDANCE])

        if phase == LifecyclePhase.COMPLETION:
            plan_folder = self._resolve_plan_folder(hook_input)
            if not self._should_advise_once(self._completion_seen, plan_folder):
                return BlockingResult(decision=Decision.ALLOW)
            return BlockingResult(decision=Decision.ALLOW, context=[_COMPLETION_GUIDANCE])

        # PROGRESS — advise on every Nth progress edit for this plan.
        plan_folder = self._resolve_plan_folder(hook_input)
        if not self._should_advise_progress(plan_folder):
            return BlockingResult(decision=Decision.ALLOW)

        return BlockingResult(decision=Decision.ALLOW, context=[_PROGRESS_GUIDANCE])

    def get_claude_md(self) -> str | None:
        """Return CLAUDE.md guidance about this handler.

        Documents the recover-vs-heartbeat distinction and the canonical cron
        prompt so agents understand both the intent and the exact text to use.
        """
        return (
            "## recovery_cron_advisor — failsafe recovery cron lifecycle advisory\n\n"
            "An advisory PostToolUse handler that fires across a plan's lifecycle and\n"
            "injects guidance telling the agent to manage a non-durable hourly failsafe\n"
            "recovery cron.\n\n"
            "**There must be EXACTLY ONE recovery cron per session — never one per\n"
            "plan.** The canonical prompt is plan-agnostic ('the active plan/task'), so a\n"
            "single cron covers every plan in the session and a second only double-fires\n"
            "on the same session. Always `CronList` before creating: reuse what is\n"
            "running, delete extras, create only when none exists.\n\n"
            "### What it does\n\n"
            "Three lifecycle phases are detected from Write/Edit to `CLAUDE/Plan/<digits>-<name>/PLAN.md`\n"
            "(never from files inside `Completed/`) and from `mkplan.bash` Bash invocations:\n\n"
            "| Phase | Trigger | Guidance injected |\n"
            "|-------|---------|-------------------|\n"
            "| **Creation** | New PLAN.md written, or `mkplan.bash` invoked | `CronList` FIRST: reuse the recovery cron already running (record THAT id in the plan's `JOURNAL/`, create nothing) and `CronDelete` any extras; create one (CronCreate, durable:false) ONLY if none is listed. Do NOT wait for the cron. |\n"
            "| **Progress** | Edit to PLAN.md touching task-status icons (⬜/🔄/✅) | `CronList`: exactly one → nothing to do; more than one → `CronDelete` the extras; none → create one. Keep working. |\n"
            "| **Completion** | `**Status**: Complete[d]` written/edited | Plan complete — **warns first**: deleting now leaves the still-live session with no recovery coverage. Keep the cron if any further work may happen (it is non-durable and dies on session exit); `CronDelete` only when certain the session is finished. |\n\n"
            "Progress reminders are rate-limited per plan: the handler advises on the first\n"
            "progress edit and then once every few progress edits for that plan, so it does\n"
            "not spam context on every edit.  Creation and completion each advise ONCE per\n"
            "plan folder instead — they are state transitions, not ongoing activity, so a\n"
            "repeat creation write or a re-save of an already-complete plan stays silent.\n\n"
            "### CRITICAL: recovery cron is NOT a heartbeat\n\n"
            "The recovery cron is a **failsafe safety net**, not a pacing mechanism:\n\n"
            "- The agent **must never** wait for the cron between units of work.\n"
            "- Work proceeds at **full speed** until an external factor (Claude API error,\n"
            "  rate limit, 5-hour usage limit, network failure) actually stalls it.\n"
            "- The cron fires only while the REPL is idle; it cannot interrupt active work.\n"
            "- Treating the cron as a heartbeat is an **own goal** — it would convert a\n"
            "  safety net into an artificial hourly throttle.\n\n"
            "### Canonical recovery-cron prompt\n\n"
            "Use this verbatim as the CronCreate prompt:\n\n"
            f"```\n{_CANONICAL_CRON_PROMPT}\n```\n\n"
            "### Configuration\n\n"
            "This handler is **on by default** (opt-out).  Disable with:\n\n"
            "```yaml\n"
            "handlers:\n"
            "  post_tool_use:\n"
            "    recovery_cron_advisor:\n"
            "      enabled: false\n"
            "```\n"
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for the three lifecycle phases."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        plan_dir = "/tmp/acceptance-test-recovcron/CLAUDE/Plan/00099-test"  # nosec B108 - acceptance test fixture path, not a runtime temp file
        plan_path = f"{plan_dir}/PLAN.md"

        return [
            AcceptanceTest(
                title="Plan creation: writing new PLAN.md triggers recovery cron setup",
                command=(
                    f"Use the Write tool to write to {plan_path}"
                    " with content '# Plan 00099: Test\\n\\n**Status**: Not Started'"
                ),
                description=(
                    "On plan creation, advises agent to create a non-durable hourly"
                    " recovery cron (CronCreate, durable:false).  Must include the"
                    " canonical FAILSAFE RECOVERY CHECK prompt and the not-a-heartbeat rule."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[
                    r"CronCreate",
                    r"durable",
                    r"[Nn]ot.*wait|[Dd]o not wait|[Nn]ever.*wait",
                    r"FAILSAFE RECOVERY",
                    r"heartbeat",
                ],
                safety_notes="Uses /tmp path - safe.  Advisory handler allows write and adds guidance.",
                test_type=TestType.ADVISORY,
                setup_commands=[f"mkdir -p {plan_dir}"],
                cleanup_commands=["rm -rf /tmp/acceptance-test-recovcron"],
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="Plan progress-update: editing PLAN.md task status triggers cron check",
                command=(
                    f"Use the Edit tool on {plan_path}"
                    " to change '⬜ **Task 1.1**' to '✅ **Task 1.1**'"
                ),
                description=(
                    "On progress-update, advises agent to verify the recovery cron is"
                    " still running (CronList) and recreate if missing."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"CronList", r"create one now"],
                safety_notes="Uses /tmp path - safe.  Advisory handler allows edit and adds guidance.",
                test_type=TestType.ADVISORY,
                setup_commands=[
                    f"mkdir -p {plan_dir}",
                    (
                        f"echo '# Plan 00099\\n\\n**Status**: In Progress"
                        f"\\n\\n- [ ] ⬜ **Task 1.1**: Todo' > {plan_path}"
                    ),
                ],
                cleanup_commands=["rm -rf /tmp/acceptance-test-recovcron"],
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="Plan completion: writing Status Complete warns before cron teardown",
                command=(
                    f"Use the Write tool to write to {plan_path}"
                    " with content '# Plan 00099\\n\\n**Status**: Complete'"
                ),
                description=(
                    "On plan completion, warns that deleting the recovery cron"
                    " while the session is still live strands it with no recovery"
                    " coverage; advises keeping the cron and running CronDelete"
                    " only once the session is genuinely finished."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"CronDelete"],
                safety_notes="Uses /tmp path - safe.  Advisory handler allows write and adds guidance.",
                test_type=TestType.ADVISORY,
                setup_commands=[f"mkdir -p {plan_dir}"],
                cleanup_commands=["rm -rf /tmp/acceptance-test-recovcron"],
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=False,
            ),
        ]
