"""BackgroundProcessTrackerHandler - track backgrounded processes (Plan 00142, Layer B).

PostToolUse advisory. When a Bash tool call backgrounds a process — via
``run_in_background: true`` or a ``&`` / ``nohup`` / ``setsid`` / ``disown``
command — this handler:

  1. records the backgrounded command to a best-effort JSONL state file in the
     daemon's untracked dir (``background-processes.jsonl``), and
  2. injects RATE-LIMITED guidance telling the agent to run
     ``harvest-background`` and to keep a non-durable watchdog cron that
     re-surfaces a runaway during idle.

**The daemon never kills.** The harvester detects and the agent decides (owner
steer, Plan 00142 Decision 1). The PostToolUse hook only fires on tool calls,
so the watchdog *cron* (created by the agent on this advice) is what covers the
dangerous idle/compaction window — exactly mirroring ``recovery_cron_advisor``.

Default-ON, rate-limited per session (Plan 00142 user decision) so routine
backgrounded commands do not spam context.
"""

import logging
import re
from typing import Any, Final

from pydantic import ValidationError

from claude_code_hooks_daemon.config.models import Config
from claude_code_hooks_daemon.constants import (
    HandlerID,
    HandlerTag,
    HookInputField,
    Priority,
    ToolName,
)
from claude_code_hooks_daemon.core import BlockingResult, Decision
from claude_code_hooks_daemon.core.handler_bases import PostToolUseHandlerBase
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.core.utils import get_bash_command
from claude_code_hooks_daemon.handlers.utils.session_advice_counter import (
    SessionAdviceCounter,
)
from claude_code_hooks_daemon.utils.autonomy import autonomy_allowed
from claude_code_hooks_daemon.utils.cli_command import (
    daemon_cli_command,
    daemon_cli_command_for_docs,
)
from claude_code_hooks_daemon.utils.config_cache import default_config, load_config_cached
from claude_code_hooks_daemon.utils.cron_hosts import effective_hostname
from claude_code_hooks_daemon.utils.cron_tick import TickKind, classify_tick, tick_sentinel
from claude_code_hooks_daemon.utils.heredoc_operators import scan_heredocs

logger = logging.getLogger(__name__)

# State file under the daemon untracked dir (never /tmp — B108).
_STATE_FILENAME: Final[str] = "background-processes.jsonl"

# Bound the best-effort audit trail so it cannot grow without limit.
_MAX_STATE_LINES: Final[int] = 200

# Advise on the 1st backgrounded command per session, then every Nth — keeps a
# default-on advisory from spamming routine background work.
_ADVISE_INTERVAL: Final[int] = 10

# Bound the per-session counter map on the daemon-lifetime singleton.
_MAX_TRACKED_SESSIONS: Final[int] = 256

# Backgrounding keywords (whole-word).
_BACKGROUND_KEYWORDS_RE: Final[re.Pattern[str]] = re.compile(r"\b(?:nohup|setsid|disown)\b")

# A ``&`` used as a backgrounding operator: not part of ``&&`` and not a
# redirection like ``2>&1`` (``&`` preceded by ``>``/``&``/digit is excluded).
_BACKGROUND_AMP_RE: Final[re.Pattern[str]] = re.compile(r"(?<![>&\d])&(?!&)")

# Shell quoting/escaping characters, for masking spans in which a ``&`` is data
# rather than a control operator.
_ESCAPE_CHAR: Final[str] = "\\"
_SINGLE_QUOTE: Final[str] = "'"
_DOUBLE_QUOTE: Final[str] = '"'
_QUOTE_CHARS: Final[frozenset[str]] = frozenset({_SINGLE_QUOTE, _DOUBLE_QUOTE})

# Masked characters are replaced (not deleted) so surrounding offsets survive
# and the lookbehind in _BACKGROUND_AMP_RE still sees the true preceding char.
_MASK_CHAR: Final[str] = " "
_LINE_SEPARATOR: Final[str] = "\n"


def _mask_heredoc_bodies(command: str) -> str:
    """Return ``command`` with heredoc bodies masked out.

    Plan 00190: everything between a heredoc operator and its terminator is
    literal data, so an ``&`` there is prose — never a control operator. This
    is how plan and journal text reaches disk in this project, so leaving
    bodies unmasked makes the advisory fire on routine documentation writes.

    Masking also protects the quote scanner that runs next: an unbalanced
    quote in prose would otherwise desynchronise it for the rest of the string.

    Where bodies start and close is `scan_heredocs`'s call, so any delimiter
    word bash accepts is read here too (Plan 00466 N120). Each body and its
    closing line are masked; newlines are kept so line structure survives.
    """
    masked = list(command)
    for heredoc in scan_heredocs(command).heredocs:
        for index in range(heredoc.body_start, heredoc.closer_end):
            if masked[index] != _LINE_SEPARATOR:
                masked[index] = _MASK_CHAR
    return "".join(masked)


def _mask_quoted_spans(command: str) -> str:
    """Return ``command`` with quoted and backslash-escaped spans masked out.

    Plan 00190: a ``&`` inside a quoted string is DATA — a grep pattern
    (``grep "Notes & Updates"``), a commit message, an echoed literal — not a
    backgrounding operator. Scanning with shell quoting rules (single quotes
    are fully literal; double quotes honour backslash escapes) is what
    distinguishes the two; a regex alone cannot.
    """
    masked: list[str] = []
    quote: str | None = None
    index = 0
    length = len(command)
    while index < length:
        char = command[index]
        # A backslash escapes the next character outside quotes, and inside
        # double quotes (but NOT inside single quotes, where it is literal).
        escapes_next = char == _ESCAPE_CHAR and quote != _SINGLE_QUOTE and index + 1 < length
        if escapes_next:
            masked.append(_MASK_CHAR * 2)
            index += 2
            continue
        if quote is None:
            if char in _QUOTE_CHARS:
                quote = char
                masked.append(_MASK_CHAR)
            else:
                masked.append(char)
        else:
            if char == quote:
                quote = None
            masked.append(_MASK_CHAR)
        index += 1
    return "".join(masked)


def _command_is_backgrounded(command: str) -> bool:
    """Return True if a bash command launches a process in the background."""
    if not command:
        return False
    # The two masks are applied asymmetrically, following what bash actually
    # does with each span:
    #   - A HEREDOC BODY is stdin data; the outer shell never executes it. So
    #     it is masked for BOTH tests — prose there is never a command.
    #   - A QUOTED SPAN may well be a command for a nested interpreter
    #     (``bash -c "nohup worker"``), so it is masked only for the bare-``&``
    #     test, where treating a literal ampersand as an operator was the
    #     observed false positive.
    heredoc_masked = _mask_heredoc_bodies(command)
    if _BACKGROUND_KEYWORDS_RE.search(heredoc_masked):
        return True
    return _BACKGROUND_AMP_RE.search(_mask_quoted_spans(heredoc_masked)) is not None


def write_state_record(
    state_file: "Any", record: dict[str, Any], max_lines: int = _MAX_STATE_LINES
) -> None:
    """Append ``record`` as a JSON line to ``state_file``, bounded to ``max_lines``.

    Creates the parent directory if needed. Keeps only the most recent
    ``max_lines`` entries so the best-effort audit trail cannot grow unbounded.
    """
    import json
    from pathlib import Path

    path = Path(state_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: list[str] = []
    # eacces-safe-exempt: the daemon's own state file, whose parent it created
    # two lines above. EACCES here means the daemon cannot write its own state.
    if path.exists():
        existing = [ln for ln in path.read_text().splitlines() if ln.strip()]
    existing.append(json.dumps(record))
    path.write_text("\n".join(existing[-max_lines:]) + "\n")


def watchdog_cron_prompt() -> str:
    """The watchdog cron's prompt, for the agent to paste verbatim.

    Supplied rather than described (Plan 00388 option 2'): an agent-composed
    prompt differs every session and carries nothing the daemon can recognise,
    so its ticks were read as the owner replying and wiped the
    ``[awaiting-human]`` marker. The leading sentinel is what lets the
    blockage suppressor tell this tick from the human. Computed on demand for
    the same reason as ``_advisory``: it names the deployed wrapper.

    The wrapper is named project-root-relative (Plan 00470 Task 2.4): this text
    is also declared under ``persistent_crons`` in a tracked file, and a live
    cron is matched to its declaration on the normalised prompt, so an absolute
    path would make a worktree's cron fail to satisfy the declaration. A cron
    fires from the project root, where the relative path runs.
    """
    return (
        f"{tick_sentinel(TickKind.WATCHDOG)}\n"
        "**BACKGROUND WATCHDOG TICK (automated — NOT a heartbeat, NOT human input).**\n"
        f"Run `{daemon_cli_command_for_docs('harvest-background')}` and act on any runaway it\n"
        "surfaces: reap the WHOLE process group (`kill -- -<pgid>`), never just the pid.\n"
        "A long task that is deliberately wanted (a build, a server, a QA run) is not a\n"
        'runaway: note KEEP_RUNNING_BECAUSE="<reason>" and leave it alone. If nothing is\n'
        "surfaced, this tick is a no-op — do not interrupt or duplicate work in flight.\n"
        "Do NOT delete this cron merely because a tick finds nothing: it is non-durable\n"
        "and ends with the session, and the next backgrounded job needs it."
    )


def declares_watchdog_cron(config: Config, hostname: str | None = None) -> bool:
    """Whether ``config`` declares the watchdog cron as an active persistent job.

    A declared watchdog is re-established at session start and required by
    ``cron_stop_enforcer`` for the whole session, so this advisory has nothing
    left to ask for (Plan 00470 Task 2.4). Recognised by its ``[tick:watchdog]``
    sentinel, the same way the failsafe is.

    Args:
        config: The project's daemon config.
        hostname: The session's effective hostname; None resolves it from this
            process's environment.
    """
    for job in config.persistent_crons.active_jobs(hostname):
        tick = classify_tick(job.prompt)
        if tick is not None and tick.kind is TickKind.WATCHDOG:
            return True
    return False


def _declared_advisory() -> str:
    """The advisory for a project that declares the watchdog under ``persistent_crons``."""
    return (
        "You launched a background / long-lived process. The daemon will NOT "
        "auto-kill it — detection is surfaced, you decide.\n\n"
        "This project DECLARES the background watchdog cron under persistent_crons, "
        "so it is re-established at session start and covers EVERY tracked "
        "background process. Create nothing and never add a second; do not "
        "CronDelete it, even once the background work ends — an idle tick is a "
        "no-op.\n"
        f"  • Check now once: run `{daemon_cli_command('harvest-background')}` yourself.\n\n"
        "If a runaway is surfaced, reap the WHOLE process group (not just the pid):\n"
        "      kill -- -<pgid>\n"
        "To deliberately keep a wanted long task (build/server), note "
        'KEEP_RUNNING_BECAUSE="reason" and move on.'
    )


def _protective_advisory() -> str:
    """The advisory where autonomy is off: harvest and reap, but no cron (Plan 00498).

    A watchdog cron schedules work the session was not asked to do, so it is
    left out; running ``harvest-background`` by hand is protective and stays.
    """
    return (
        "You launched a background / long-lived process. The daemon will NOT "
        "auto-kill it — detection is surfaced, you decide.\n\n"
        "Autonomy is off in this environment, so no watchdog cron is asked for. "
        "Check on the process yourself before you finish:\n"
        f"  • Run `{daemon_cli_command('harvest-background')}` once the work is done.\n\n"
        "If a runaway is surfaced, reap the WHOLE process group (not just the pid):\n"
        "      kill -- -<pgid>\n"
        "To deliberately keep a wanted long task (build/server), note "
        'KEEP_RUNNING_BECAUSE="reason" and move on.'
    )


def _advisory() -> str:
    """Build the backgrounded-process advisory.

    Computed on demand (Plan 00192) because the harvest command names the
    deployed wrapper, whose path depends on the install mode that
    ``ProjectContext`` only knows after daemon startup.
    """
    return (
        "You launched a background / long-lived process. The daemon will NOT "
        "auto-kill it — detection is surfaced, you decide.\n\n"
        "Set up the failsafe (mirrors the recovery cron; the dangerous window is when "
        "the REPL is idle/compacting, so a tool-call hook cannot cover it).\n"
        "EXACTLY ONE watchdog cron covers the whole session — its prompt harvests "
        "ALL tracked background processes, not one of them — so never create a "
        "second, and this advisory fires on every backgrounded process:\n"
        "  • Run CronList FIRST. If a watchdog cron is already listed, REUSE it and "
        "create nothing (CronDelete any extras so one remains).\n"
        "  • ONLY IF none is listed, create a non-durable recurring watchdog cron "
        "(CronCreate, durable:false, recurring:true, off-:00 minute). Paste the "
        "following text verbatim as its prompt — the first line is how the daemon "
        "tells this tick from you, so do not reword or drop it:\n\n"
        f"{watchdog_cron_prompt()}\n\n"
        "    Record the cron ID. Do NOT wait for the cron — keep working at full speed.\n"
        "  • Check now once: run `harvest-background` yourself.\n\n"
        "If a runaway is surfaced, reap the WHOLE process group (not just the pid):\n"
        "      kill -- -<pgid>\n"
        "To deliberately keep a wanted long task (build/server), note "
        'KEEP_RUNNING_BECAUSE="reason" and move on.\n'
        "Keep the watchdog cron for the whole session: an idle tick is a no-op, and "
        "it ends with the session."
    )


class BackgroundProcessTrackerHandler(PostToolUseHandlerBase):
    """Track backgrounded Bash processes and advise on watchdog/harvest (never kills)."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.BACKGROUND_PROCESS_TRACKER,
            priority=Priority.BACKGROUND_PROCESS_TRACKER,
            terminal=False,
            tags=[HandlerTag.WORKFLOW, HandlerTag.ADVISORY, HandlerTag.NON_TERMINAL],
        )
        # Shared with teammate_reap_advisor rather than duplicated into it:
        # both copies of this bookkeeping evicted without a lock, which can
        # raise under the dispatch thread pool (ledger 00422 N5 row (c), Plan
        # 00437).
        self._advice_counter = SessionAdviceCounter(
            interval=_ADVISE_INTERVAL, max_sessions=_MAX_TRACKED_SESSIONS
        )

    def get_default_enabled(self) -> bool:
        """Opt-OUT handler — ON by default (Plan 00142 user decision).

        Advisory-only and rate-limited, so safe to ship enabled. Projects that
        do not want it set ``enabled: false``. Must stay consistent with the
        template (which marks it ``enabled: true``).
        """
        return True

    def matches(self, hook_input: dict[str, Any]) -> bool:
        if hook_input.get(HookInputField.TOOL_NAME) != ToolName.BASH:
            return False
        tool_input: dict[str, Any] = hook_input.get(HookInputField.TOOL_INPUT, {})
        if tool_input.get("run_in_background") is True:
            return True
        return _command_is_backgrounded(get_bash_command(hook_input) or "")

    def _resolve_state_file(self) -> Any | None:
        """Return the state-file path, or None when ProjectContext is unavailable.

        Inside the daemon ProjectContext is always initialised. In unit tests it
        is not — the RuntimeError is caught explicitly (not blanket-suppressed)
        and the write is skipped, since the advisory is the primary function.
        """
        from claude_code_hooks_daemon.core.project_context import ProjectContext

        try:
            return ProjectContext.daemon_untracked_dir() / _STATE_FILENAME
        except RuntimeError:
            return None

    def _load_config(self) -> Config:
        """The project's daemon config; defaults when it cannot be read.

        Defaults mean "no declaration", which keeps the advisory asking for the
        watchdog -- the safe direction, since the ask is idempotent (CronList
        first).
        """
        try:
            config_path = ProjectContext.project_root() / ".claude" / "hooks-daemon.yaml"
            return load_config_cached(config_path)
        except (ValidationError, OSError, ValueError, RuntimeError) as exc:
            logger.debug("background_process_tracker: config unavailable: %s", exc)
            return default_config()

    def _should_advise(self, session_id: str) -> bool:
        """Record a detection for ``session_id`` and return whether to advise now."""
        return self._advice_counter.should_advise(session_id)

    def handle(self, hook_input: dict[str, Any]) -> BlockingResult:
        command = get_bash_command(hook_input) or ""
        tool_input: dict[str, Any] = hook_input.get(HookInputField.TOOL_INPUT, {})
        session_id = str(hook_input.get(HookInputField.SESSION_ID, "") or "unknown")

        # Best-effort state record (skipped when no untracked dir is resolvable).
        state_file = self._resolve_state_file()
        if state_file is not None:
            write_state_record(
                state_file,
                {
                    "command": command,
                    "session_id": session_id,
                    "run_in_background": tool_input.get("run_in_background") is True,
                },
            )

        if not self._should_advise(session_id):
            return BlockingResult(decision=Decision.ALLOW)
        if not autonomy_allowed(hook_input):
            return BlockingResult(decision=Decision.ALLOW, context=[_protective_advisory()])
        declared = declares_watchdog_cron(self._load_config(), effective_hostname(hook_input))
        advisory = _declared_advisory() if declared else _advisory()
        return BlockingResult(decision=Decision.ALLOW, context=[advisory])

    def get_claude_md(self) -> str | None:
        return (
            "## background_process_tracker — backgrounded processes are tracked\n\n"
            "A PostToolUse advisory that fires when a Bash call backgrounds a process "
            "(`run_in_background: true`, or a `&`/`nohup`/`setsid`/`disown` command). "
            "It records the command to `background-processes.jsonl` and injects "
            "rate-limited guidance.\n\n"
            "**The daemon never kills.** It surfaces runaways; you decide.\n\n"
            "When you background a long-lived process:\n\n"
            "- Ensure **EXACTLY ONE** non-durable recurring **watchdog cron** exists — "
            "one covers the whole session, since its prompt harvests ALL tracked "
            "background processes. When the project DECLARES it under `persistent_crons` "
            "it is re-established at session start: create nothing. Otherwise `CronList` "
            "FIRST: reuse the one already running "
            "(`CronDelete` any extras), and only if none is listed create it "
            "(CronCreate, durable:false) with the prompt the advisory supplies, "
            "pasted verbatim: it runs "
            f"`{daemon_cli_command_for_docs('harvest-background')}` and "
            "acts on any runaway — this covers the idle/compaction window a tool-call "
            "hook cannot. Its first line, `[tick:watchdog]`, is how the daemon tells "
            "the tick from you, so an `[awaiting-human]` wait survives it; keep it. "
            "Do NOT wait for the cron; keep working.\n"
            "- Check on demand: run `harvest-background` (exit 1 == runaways surfaced).\n"
            "- Reap a runaway by its **process group**: `kill -- -<pgid>` (not just the pid).\n"
            '- Keep a wanted long task: note `KEEP_RUNNING_BECAUSE="reason"`.\n'
            "- Keep the watchdog cron for the whole session: an idle tick is a no-op, and "
            "it ends with the session.\n\n"
            "Advisory is rate-limited per session (default-on). Disable with "
            "`handlers.post_tool_use.background_process_tracker.enabled: false`."
        )

    def get_acceptance_tests(self) -> list[Any]:
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="backgrounded command triggers harvester advisory",
                command="sleep 600 &",
                dispatch_as_bash=True,
                description=(
                    "Backgrounding a process (trailing &) surfaces guidance to run "
                    "harvest-background and manage a watchdog cron; never kills."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"harvest-background", r"kill -- -", r"[Cc]ron"],
                safety_notes="sleep 600 & is harmless; the advisory only adds context.",
                test_type=TestType.ADVISORY,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=False,
            ),
        ]
