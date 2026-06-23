"""RecoveryCronAdvisorHandler - lifecycle advisory for failsafe recovery crons.

Fires on PostToolUse events that represent the three lifecycle moments of a
CLAUDE/Plan/<digits>-<name>/PLAN.md:

  1. CREATION  — a new PLAN.md is written, or mkplan.bash is invoked.
  2. PROGRESS  — an existing PLAN.md is edited touching task-status icons
                 (⬜/🔄/✅) or the "## Notes & Updates" section.
  3. COMPLETION — the plan's **Status** line is changed to Complete/Completed.

On each phase the handler injects advisory context:
  - Creation:    prompt the agent to create a non-durable hourly recovery cron.
  - Progress:    remind agent to verify the cron is still running (CronList).
  - Completion:  prompt the agent to delete the cron (CronDelete).

IMPORTANT: this is a FAILSAFE RECOVERY cron, NOT a heartbeat.  The agent must
never pace itself to the cron; work must proceed at full speed until an
external factor (API error, rate limit, usage limit) actually stalls it.

Decision D1 (PLAN.md): crons are created non-durable (durable:false) so they
are session-only and cleaned up naturally on session exit.

Decision D2 (PLAN.md): dedup is via an in-session per-plan PROGRESS edit
counter owned by the handler.  The handler advises on every Nth progress
edit for a given plan (independent of global daemon traffic).  The agent
uses CronList to avoid duplicate creates.

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
from claude_code_hooks_daemon.core import Decision, Handler, HookResult
from claude_code_hooks_daemon.core.utils import get_bash_command, get_file_path

# ─── Lifecycle phase ──────────────────────────────────────────────────────────


class LifecyclePhase(Enum):
    """The detected lifecycle phase of a PLAN.md interaction."""

    CREATION = "creation"
    PROGRESS = "progress"
    COMPLETION = "completion"


# ─── Path patterns ────────────────────────────────────────────────────────────

# Matches: CLAUDE/Plan/<digits>-<name>/PLAN.md (NOT inside Completed/)
_PLAN_PATH_RE: Final[re.Pattern[str]] = re.compile(
    r"CLAUDE/Plan/(\d+-[^/]+)/PLAN\.md$",
    re.IGNORECASE,
)

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

# Matches the Notes & Updates section heading
_NOTES_SECTION_RE: Final[re.Pattern[str]] = re.compile(
    r"##\s+Notes\s+[&&]\s+Updates",
    re.IGNORECASE,
)

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

# Maximum number of plan folders tracked in the per-plan progress-count map.
# Bounds memory on the daemon-lifetime singleton: when exceeded, the oldest
# inserted entry is evicted (insertion-ordered dict).  A plan re-entering after
# eviction simply restarts its progress count — harmless for an advisory.
_MAX_TRACKED_PLANS: Final[int] = 256

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
    "external factor actually stops you — waiting for the cron is an own goal. When\n"
    "the plan is complete and no resumable work remains, delete this cron\n"
    "(CronDelete)."
)

# ─── Advisory text per phase ──────────────────────────────────────────────────

_CREATION_GUIDANCE: Final[str] = (
    "Recovery-cron setup is part of executing this plan.\n\n"
    "Create a non-durable hourly failsafe recovery cron NOW:\n"
    "  • Use CronCreate with durable:false and recurring:true.\n"
    "  • Choose an off-:00 minute (e.g. 17 * * * * or 37 * * * *).\n"
    "  • Record the cron ID in this plan's Notes & Updates section.\n"
    "  • Do NOT wait for the cron to fire — keep working immediately.\n\n"
    "This is a FAILSAFE RECOVERY cron, NOT a heartbeat. The agent must never\n"
    "pace itself to the cron. Work proceeds at full speed until an external\n"
    "factor (API error, rate limit, usage limit) actually stops it.\n\n"
    "Paste the following text verbatim as the cron prompt:\n\n"
    f"{_CANONICAL_CRON_PROMPT}"
)

_PROGRESS_GUIDANCE: Final[str] = (
    "Confirm your failsafe recovery cron is still running:\n"
    "  1. Run CronList and look for the hourly recovery cron you created.\n"
    "  2. If it is missing, recreate it now (CronCreate, durable:false,\n"
    "     recurring:true, off-:00 minute, same canonical prompt).\n"
    "  3. Keep working — do not wait for the cron to fire."
)

_COMPLETION_GUIDANCE: Final[str] = (
    "This plan is complete — delete its failsafe recovery cron so it does not\n"
    "fire in unrelated future work:\n"
    "  • Run CronDelete with the cron ID you recorded in the plan.\n"
    "  • If you did not record the ID, run CronList first to locate it."
)


# ─── Phase detection helper ───────────────────────────────────────────────────


def _is_plan_path(file_path: str) -> tuple[bool, str]:
    """Return (matches, plan_folder) for a file path.

    Returns (True, folder_name) when the path is an active PLAN.md.
    Returns (False, '') when excluded (Completed/) or not a plan path.
    """
    normalized = file_path.replace("\\", "/")
    if _COMPLETED_SEGMENT in normalized:
        return False, ""
    m = _PLAN_PATH_RE.search(normalized)
    if not m:
        return False, ""
    return True, m.group(1)


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
    """Return True if text contains task-status icons or Notes & Updates heading."""
    return bool(_TASK_STATUS_ICON_RE.search(text)) or bool(_NOTES_SECTION_RE.search(text))


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


def _detect_lifecycle_phase(hook_input: dict[str, Any]) -> LifecyclePhase | None:
    """Detect the plan lifecycle phase from a PostToolUse hook input.

    Returns the detected LifecyclePhase or None if this event is not relevant.

    Detection rules:
    - CREATION: Write to an active PLAN.md (any content) OR a Bash call to mkplan.bash.
    - COMPLETION: Write/Edit to active PLAN.md with **Status**: Complete in content.
    - PROGRESS: Edit to active PLAN.md touching task-status icons or Notes & Updates.
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
    is_plan, _folder = _is_plan_path(file_path)
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


class RecoveryCronAdvisorHandler(Handler):
    """Advisory handler that manages failsafe recovery cron across plan lifecycle.

    Fires on three lifecycle moments:
    - Plan creation  → advise agent to create a non-durable hourly recovery cron.
    - Plan progress  → remind agent to verify the cron is still running.
    - Plan completion → prompt agent to delete the cron (CronDelete).

    The recovery cron is a FAILSAFE RECOVERY mechanism, NOT a heartbeat.  The
    agent must never pace itself to the cron; work must continue at full speed
    until an external factor actually blocks progress.

    A per-plan PROGRESS edit counter (keyed by plan folder name) advises only on
    every Nth progress edit, preventing spam on every single PLAN.md edit while
    staying independent of unrelated daemon traffic.  Completion advisories
    always fire regardless of the counter.  The counter map is bounded
    (_MAX_TRACKED_PLANS) so it cannot grow without limit on the daemon-lifetime
    singleton.

    Opt-in: get_default_enabled() returns False.  Projects dogfooding this repo
    set enabled: true explicitly in .claude/hooks-daemon.yaml.
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
        # Phase computed in matches() and reused in handle() (avoids running the
        # detection twice per event).  Set per-call; never relied on across
        # events.
        self._cached_phase: LifecyclePhase | None = None

    def get_default_enabled(self) -> bool:
        """Opt-in handler — off by default (Plan 00139, Decision D4).

        Projects that want recovery-cron advisory must explicitly set
        enabled: true in their .claude/hooks-daemon.yaml.  Must stay
        consistent with the ``enabled: false`` flag in the config template
        (enforced by test_default_enabled_template_consistency).
        """
        return False

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Return True if this event represents a plan lifecycle moment.

        Matches when _detect_lifecycle_phase returns a non-None phase.  The
        detected phase is cached on the instance and reused by handle() for the
        same event, so detection runs once per event rather than twice.
        """
        self._cached_phase = _detect_lifecycle_phase(hook_input)
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
        return _detect_lifecycle_phase(hook_input)

    def _should_advise_progress(self, plan_folder: str) -> bool:
        """Record a progress edit for plan_folder and return whether to advise.

        Advises on the 1st progress edit and every _PROGRESS_ADVISE_INTERVAL-th
        edit thereafter.  Bounds the tracking map at _MAX_TRACKED_PLANS by
        evicting the oldest inserted entry when a new plan would overflow it.
        """
        count = self._progress_counts.get(plan_folder)
        if count is None:
            if len(self._progress_counts) >= _MAX_TRACKED_PLANS:
                oldest_key = next(iter(self._progress_counts))
                del self._progress_counts[oldest_key]
            count = _PROGRESS_COUNT_START
        else:
            count += 1
        self._progress_counts[plan_folder] = count
        return (count - _PROGRESS_COUNT_START) % _PROGRESS_ADVISE_INTERVAL == 0

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Inject advisory context appropriate for the detected lifecycle phase.

        Phase routing:
        - CREATION   → always advise (cron setup is part of plan execution).
        - COMPLETION → always advise (teardown the cron).
        - PROGRESS   → advise on every Nth progress edit per plan.

        Returns:
            HookResult with ALLOW decision, and context[] when advising.
        """
        phase = self._resolve_phase(hook_input)
        if phase is None:
            return HookResult(decision=Decision.ALLOW)

        if phase == LifecyclePhase.CREATION:
            return HookResult(decision=Decision.ALLOW, context=[_CREATION_GUIDANCE])

        if phase == LifecyclePhase.COMPLETION:
            # Completion always fires — bypass the progress interval.
            return HookResult(decision=Decision.ALLOW, context=[_COMPLETION_GUIDANCE])

        # PROGRESS — advise on every Nth progress edit for this plan.
        file_path = get_file_path(hook_input) or ""
        _, plan_folder = _is_plan_path(file_path)
        # For Bash (mkplan.bash) there is no file_path; use a sentinel key.
        if not plan_folder:
            plan_folder = "__mkplan__"

        if not self._should_advise_progress(plan_folder):
            return HookResult(decision=Decision.ALLOW)

        return HookResult(decision=Decision.ALLOW, context=[_PROGRESS_GUIDANCE])

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
            "### What it does\n\n"
            "Three lifecycle phases are detected from Write/Edit to `CLAUDE/Plan/<digits>-<name>/PLAN.md`\n"
            "(never from files inside `Completed/`) and from `mkplan.bash` Bash invocations:\n\n"
            "| Phase | Trigger | Guidance injected |\n"
            "|-------|---------|-------------------|\n"
            "| **Creation** | New PLAN.md written, or `mkplan.bash` invoked | Create a non-durable hourly cron now (CronCreate, durable:false); record the ID in the plan; do NOT wait for the cron. |\n"
            "| **Progress** | Edit to PLAN.md touching task-status icons (⬜/🔄/✅) or `## Notes & Updates` section | Confirm the recovery cron is still running (CronList); recreate if missing; keep working. |\n"
            "| **Completion** | `**Status**: Complete[d]` written/edited | Plan complete — delete the recovery cron (CronDelete). |\n\n"
            "Progress reminders are rate-limited per plan: the handler advises on the first\n"
            "progress edit and then once every few progress edits for that plan, so it does\n"
            "not spam context on every edit.  Completion always advises (bypasses the interval).\n\n"
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
            "This handler is **opt-in** (off by default).  Enable with:\n\n"
            "```yaml\n"
            "handlers:\n"
            "  post_tool_use:\n"
            "    recovery_cron_advisor:\n"
            "      enabled: true\n"
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
                expected_message_patterns=[r"CronList", r"[Rr]ecreat"],
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
                title="Plan completion: writing Status Complete triggers cron teardown",
                command=(
                    f"Use the Write tool to write to {plan_path}"
                    " with content '# Plan 00099\\n\\n**Status**: Complete'"
                ),
                description=(
                    "On plan completion, advises agent to delete the recovery cron"
                    " (CronDelete) so it does not fire in unrelated future work."
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
