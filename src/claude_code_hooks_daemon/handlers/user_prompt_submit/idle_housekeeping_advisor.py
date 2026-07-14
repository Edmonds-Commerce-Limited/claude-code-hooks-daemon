"""IdleHousekeepingAdvisoryHandler - turn repeated no-op recovery ticks into
useful, bounded, report-first housekeeping (Plan 00161).

The daemon ships a failsafe recovery cron that fires a ``FAILSAFE RECOVERY
CHECK`` prompt hourly while the REPL is idle. When there is nothing to resume,
each tick is a no-op and the agent re-stops -- wasting idle time. This handler
detects a run of consecutive no-op ticks (the session is demonstrably
idle-and-caught-up) and injects guidance to enter a bounded **housekeeping
mode**: dispatch specialist housekeeping sub-agents (protecting main-thread
context) that run report-first audits and write shareable markdown reports.

BETA (Plan 00161 Decision 4): opt-in / OFF by default, and strictly
report-only -- it surfaces issues/suggestions, it never auto-mutates or
auto-commits. Reports are markdown files (Decision 5) written to an untracked
reports directory so they can be shared agent-to-agent, via Slack, or as a
GitHub issue.
"""

import logging
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import Decision, Handler, HookResult, ProjectContext
from claude_code_hooks_daemon.core.transcript_reader import TranscriptMessage, TranscriptReader

logger = logging.getLogger(__name__)

# The stable marker every failsafe-recovery-cron prompt begins with. Mirrors the
# first line of ``recovery_cron_advisor._CANONICAL_CRON_PROMPT`` -- matching it is
# exact, not heuristic (the daemon authors the prompt).
_RECOVERY_MARKER: Final[str] = "FAILSAFE RECOVERY CHECK"

# Defaults (overridable via handler options in hooks-daemon.yaml).
_DEFAULT_NOOP_THRESHOLD: Final[int] = 2
_DEFAULT_MAX_PASSES_PER_SESSION: Final[int] = 1
_DEFAULT_REPORTS_DIR: Final[str] = "untracked/reports"

# Custom project guidance (Plan 00161): a project may point the handler at its own
# housekeeping doc, either ADDED to the default guidance or REPLACING it entirely.
_DEFAULT_CUSTOM_GUIDANCE_MODE: Final[str] = "additive"
_MODE_REPLACE: Final[str] = "replace"

# Bound the per-session pass-count map so a long-lived daemon cannot leak memory
# across many sessions.
_MAX_TRACKED_SESSIONS: Final[int] = 256

_TOOL_USE_BLOCK: Final[str] = "tool_use"
_ASSISTANT_ROLE: Final[str] = "assistant"
_USER_ROLES: Final[frozenset[str]] = frozenset({"user", "human"})


def count_trailing_noop_recovery_ticks(messages: list[TranscriptMessage], marker: str) -> int:
    """Count consecutive no-op recovery ticks at the tail of the transcript.

    Walks newest -> oldest. A *no-op tick* is a user message containing
    ``marker`` whose only follow-up (before the next tick) was a text-only
    assistant stop. The run ends -- and counting stops -- as soon as we hit
    either an assistant message that used a tool (real work happened) or a
    user message that is NOT a recovery tick (a real prompt, or a tool result).

    This is intentionally conservative: any sign of work (a tool_use) in the
    trailing window yields the count so far, so housekeeping never fires while
    the agent is actually doing something.

    Args:
        messages: Transcript messages, oldest first.
        marker: The recovery-tick marker substring to match.

    Returns:
        The number of consecutive trailing no-op recovery ticks.
    """
    count = 0
    for message in reversed(messages):
        if message.role == _ASSISTANT_ROLE:
            if any(block.block_type == _TOOL_USE_BLOCK for block in message.content_blocks):
                return count
            continue
        if message.role in _USER_ROLES:
            if marker in message.content:
                count += 1
                continue
            # A real user prompt or a tool result -> boundary.
            return count
        # Other roles (system, etc.) are skipped.
    return count


class IdleHousekeepingAdvisoryHandler(Handler):
    """After N consecutive no-op recovery ticks, advise a report-first
    housekeeping pass dispatched to specialist sub-agents (beta, opt-in)."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.IDLE_HOUSEKEEPING_ADVISORY,
            priority=Priority.IDLE_HOUSEKEEPING_ADVISORY,
            terminal=False,
            tags=[HandlerTag.ADVISORY, HandlerTag.NON_TERMINAL],
        )
        # Defaults; the registry overrides these from handler options via setattr.
        self._noop_threshold: int = _DEFAULT_NOOP_THRESHOLD
        self._max_passes_per_session: int = _DEFAULT_MAX_PASSES_PER_SESSION
        self._reports_dir: str = _DEFAULT_REPORTS_DIR
        # Optional project-defined guidance doc + how it combines with the default.
        self._custom_guidance_doc: str = ""
        self._custom_guidance_mode: str = _DEFAULT_CUSTOM_GUIDANCE_MODE
        # Per-session housekeeping-pass counter (in-memory; resets on daemon
        # restart, which is acceptable for a bounded beta safety-net feature).
        self._passes_by_session: dict[str, int] = {}

    def get_default_enabled(self) -> bool:
        """Opt-in: ships OFF by default (beta).

        This is a new, exploratory behaviour that changes how idle time is
        spent, so it is opt-in until it has field time. Enable it explicitly via
        ``handlers.user_prompt_submit.idle_housekeeping_advisory.enabled: true``.
        """
        return False

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Match any string prompt (branching happens in handle)."""
        return isinstance(hook_input.get("prompt"), str)

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Fire housekeeping guidance once the idle-tick threshold is reached."""
        prompt = hook_input.get("prompt")
        if not isinstance(prompt, str):
            return HookResult(decision=Decision.ALLOW)

        session_id = str(hook_input.get("session_id", ""))

        # A real (non-tick) user prompt means new work is starting: reset this
        # session's housekeeping budget and get out of the way.
        if _RECOVERY_MARKER not in prompt:
            self._passes_by_session.pop(session_id, None)
            return HookResult(decision=Decision.ALLOW)

        # Recovery tick. Respect the per-session pass cap.
        if self._passes_by_session.get(session_id, 0) >= self._max_passes_per_session:
            return HookResult(decision=Decision.ALLOW)

        transcript_path = hook_input.get("transcript_path")
        if not isinstance(transcript_path, str) or not transcript_path:
            return HookResult(decision=Decision.ALLOW)

        reader = TranscriptReader()
        try:
            reader.load(transcript_path)
        except (OSError, ValueError) as exc:
            logger.debug("housekeeping: could not load transcript %s: %s", transcript_path, exc)
            return HookResult(decision=Decision.ALLOW)

        count = count_trailing_noop_recovery_ticks(reader.get_messages(), _RECOVERY_MARKER)
        if count < self._noop_threshold:
            return HookResult(decision=Decision.ALLOW)

        self._record_pass(session_id)
        return HookResult(decision=Decision.ALLOW, context=[self._build_guidance()])

    def _record_pass(self, session_id: str) -> None:
        """Increment this session's pass count, bounding the tracking map."""
        if (
            session_id not in self._passes_by_session
            and len(self._passes_by_session) >= _MAX_TRACKED_SESSIONS
        ):
            self._passes_by_session.pop(next(iter(self._passes_by_session)))
        self._passes_by_session[session_id] = self._passes_by_session.get(session_id, 0) + 1

    def _build_guidance(self) -> str:
        """Compose the injected guidance from the default and any project doc.

        A project may set ``custom_guidance_doc`` to a markdown file (absolute,
        or relative to the project root). ``custom_guidance_mode: replace`` uses
        ONLY that doc; ``additive`` (default) appends it to the built-in
        guidance. A configured-but-unreadable doc fails safe to the default.
        """
        default = self._default_guidance()
        custom = self._load_custom_guidance()
        if custom is None:
            return default
        if self._custom_guidance_mode == _MODE_REPLACE:
            return custom
        return (
            f"{default}\n\n---\n\nPROJECT-SPECIFIC HOUSEKEEPING GUIDANCE "
            f"(from {self._custom_guidance_doc}):\n{custom}"
        )

    def _load_custom_guidance(self) -> str | None:
        """Read the project's custom guidance doc, or None if unset/absent.

        Uses precondition checks (not try/except-return) so the common "unset"
        and "file absent" cases degrade cleanly to the default guidance, while a
        genuine read error (permissions, bad encoding) fails fast into the
        daemon's per-handler fail-open rather than being silently swallowed.
        """
        raw = (self._custom_guidance_doc or "").strip()
        if not raw:
            return None
        path = Path(raw)
        if not path.is_absolute():
            path = ProjectContext.project_root() / path
        if not path.is_file():
            logger.debug("housekeeping: custom guidance doc not found: %s", path)
            return None
        text = path.read_text(encoding="utf-8").strip()
        return text or None

    def _default_guidance(self) -> str:
        """The built-in housekeeping-mode guidance."""
        return (
            "🧹 HOUSEKEEPING MODE (idle detected — repeated no-op recovery ticks).\n"
            "The session is caught up: clean tree, nothing to resume, several "
            "consecutive no-op failsafe-recovery ticks. Rather than re-stopping, "
            "spend this idle time on useful, LOW-priority, REPORT-ONLY housekeeping.\n\n"
            "HOW (protect main-thread context — do NOT run the audits inline):\n"
            "  • Dispatch one or more specialist housekeeping SUB-AGENTS. Each "
            "runs a scoped, read-only audit and writes a detailed **markdown "
            f"report file** under `{self._reports_dir}/` (e.g. "
            "`YYYY-MM-DD-<topic>.md`). Markdown files have no size limit — include "
            "transcripts, logs, and code snippets so the report is genuinely useful.\n"
            "  • Candidate audits (pick what fits): plan-tree sweep "
            "(`plan-qa --sweep`), QA baseline (`llm_qa.py all`), daemon "
            "log/health scan, stale-artifact/venv/background reaping report, doc/"
            "truth-drift & dead-link scan, TODO/FIXME inventory, `get_claude_md()` "
            "completeness audit, coverage-gap report.\n"
            "  • This is REPORT-ONLY (beta): surface issues/suggestions in the "
            "report. Do NOT auto-fix, auto-commit, or make decisions that are the "
            "user's to make.\n\n"
            "SHARE the report via: agent-to-agent hand-off, Slack/colleague, or a "
            "GitHub issue. See docs/guides/CREATING_REPORTS.md for the format and "
            "sharing channels.\n\n"
            "RULES: housekeeping is strictly lower priority than real work — a real "
            "user prompt aborts it immediately. When the pass is done (or nothing "
            "actionable remains), summarise what the report covers and stop with "
            "`STOPPING BECAUSE: housekeeping pass complete; report at <path>`. Do "
            "NOT loop: this fires once per idle stretch."
        )

    def get_claude_md(self) -> str | None:
        return (
            "## idle_housekeeping_advisory — report-first idle housekeeping (beta, opt-in)\n\n"
            "When the session is idle and caught up (repeated no-op failsafe-recovery "
            "ticks), this advisory suggests a bounded HOUSEKEEPING MODE: dispatch "
            "specialist housekeeping sub-agents that run read-only audits and write "
            "shareable **markdown report files** (default `untracked/reports/`). It is "
            "REPORT-ONLY — never auto-fix or auto-commit — and strictly lower priority "
            "than real work (a real user prompt aborts it). Off by default; enable via "
            "`handlers.user_prompt_submit.idle_housekeeping_advisory.enabled: true`. "
            "A project can point it at its own doc via the `custom_guidance_doc` option "
            "(`custom_guidance_mode: additive` appends it to the default, `replace` uses "
            "only the project doc). See docs/guides/CREATING_REPORTS.md."
        )

    def get_acceptance_tests(self) -> list[Any]:
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="Idle housekeeping advisory fires after repeated no-op ticks",
                command='echo "test"',
                description=(
                    "Opt-in advisory (off by default). After N consecutive no-op "
                    "failsafe-recovery ticks it injects housekeeping-mode guidance "
                    "to dispatch report-writing sub-agents. Hard to trigger "
                    "synthetically; covered by unit tests."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"(housekeeping|report)"],
                safety_notes="Advisory only — never blocks; report-only guidance.",
                test_type=TestType.CONTEXT,
                requires_event="UserPromptSubmit event (cannot be triggered by subagent)",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
