"""CommandHintsHandler - generic, config-driven command-hint advisories (Plan 00212).

PostToolUse advisory. ONE handler, driven by a config object mapping command
patterns to hint text — deliberately NOT a handler per hinted command. When a
Bash tool call's command matches a configured hint's ``pattern`` (a literal
command name, matched at the START of a shell segment), a rate-limited HINT
is injected as advisory context reminding the agent of a follow-up action.

**Never blocks.** ``terminal=False``, and ``handle()`` has no DENY/ASK branch
at all — a hint that can block is a bug.

Command matching reuses the project's shared grammar rather than hand-rolling
detection (Plan 00202 lesson): ``utils/shell_segmentation.split_unquoted`` for
compound-command boundaries, and the ``env``-prefix / path-qualifier idiom
from ``utils/command_evasion`` for invocation respellings. A pattern only
matches at the START of a segment (after stripping an optional ``env `` /
path prefix), so the configured word appearing as an ARGUMENT to an unrelated
command (``grep agent-browser notes.md``) or inside a commit message never
fires the hint.

**TTL rate limiting** (Plan 00212 design decision): each hint fires at most
once per ``ttl_seconds`` window, tracked per ``(session_id, hint_id)`` in a
bounded, FIFO-evicted in-memory map — the same shape as
``background_process_tracker._should_advise``. Time is the PRIMARY gate
("don't fire again for at least N seconds" is literally a duration, and the
daemon observes discrete EVENTS, not turns — ten tool calls can span ten
seconds or ten minutes, so a call-count proxy for "recently" is unreliable).
An optional secondary count gate, ``min_calls_between``, additionally
requires at least that many further matching calls before re-firing even
once the TTL has elapsed. State lives only on the handler instance: a daemon
restart resets it and a hint may fire once more than strictly necessary —
acceptable for an advisory hint, not worth a persistence layer (YAGNI).

**Config paradigm** (mirrors ``idle_housekeeping_advisor``'s
``custom_guidance_mode``): ``handlers.post_tool_use.command_hints.options``
takes ``mode`` (``additive``, default, or ``replace``) and ``hints`` (a list
of ``{id, pattern, hint, ttl_seconds, min_calls_between}`` dicts). In
``additive`` mode the project's ``hints`` are appended to the built-in set; a
project entry whose ``id`` matches a built-in one OVERRIDES that built-in
entirely (position preserved, content replaced). In ``replace`` mode ONLY the
project's ``hints`` are used — the built-in set is discarded entirely, even
if the project supplies none (yielding zero active hints, a deliberate,
if unusual, way to fully disable matching without setting ``enabled: false``).
"""

import logging
import re
import time
from dataclasses import dataclass
from typing import Any, Final

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, HookInputField, Priority
from claude_code_hooks_daemon.constants.tools import ToolName
from claude_code_hooks_daemon.core import BlockingResult, Decision
from claude_code_hooks_daemon.core.handler_bases import PostToolUseHandlerBase
from claude_code_hooks_daemon.core.utils import get_bash_command
from claude_code_hooks_daemon.utils.command_evasion import OPTIONAL_PATH
from claude_code_hooks_daemon.utils.shell_segmentation import split_unquoted

logger = logging.getLogger(__name__)

# ── Config keys (mirrors sensitive_content's `_PATTERN_KEY_*` style) ───────
_KEY_ID: Final[str] = "id"
_KEY_PATTERN: Final[str] = "pattern"
_KEY_HINT: Final[str] = "hint"
_KEY_TTL_SECONDS: Final[str] = "ttl_seconds"
_KEY_MIN_CALLS_BETWEEN: Final[str] = "min_calls_between"

# ── Config mode (additive/replace paradigm, mirrors idle_housekeeping_advisor) ──
_MODE_ADDITIVE: Final[str] = "additive"
_MODE_REPLACE: Final[str] = "replace"
_DEFAULT_MODE: Final[str] = _MODE_ADDITIVE

# ── Defaults for a hint entry that omits optional fields ───────────────────
_DEFAULT_TTL_SECONDS: Final[int] = 1800  # 30 minutes
_DEFAULT_MIN_CALLS_BETWEEN: Final[int] = 0  # 0 = no secondary count gate

# Bound the (session_id, hint_id) TTL-bookkeeping map so a long-lived daemon
# cannot leak memory across many sessions/hints. Same FIFO-eviction shape as
# background_process_tracker._session_counts, sized larger because this map
# is keyed on TWO axes (session x hint) rather than one.
_MAX_TRACKED_FIRE_STATES: Final[int] = 512

# An optional `env ` prefix before the command name (e.g. `env agent-browser`).
_ENV_PREFIX: Final[str] = r"(?:env\s+)?"

# Shell separators that start a NEW command position. A pattern only ever
# matches at the START of one of these segments, never mid-argument — this is
# what stops `grep agent-browser notes.md` (where "grep" is the segment's
# leading command) from being mistaken for an `agent-browser` invocation.
# Ordered longest-first per split_unquoted's contract.
_SEGMENT_SEPARATORS: Final[tuple[str, ...]] = ("&&", "||", ";", "\n", "|")

# The built-in hint's id, pattern and reminder text (Plan 00212's only
# default-shipped hint).
_AGENT_BROWSER_HINT_ID: Final[str] = "agent-browser-close-session"
_AGENT_BROWSER_PATTERN: Final[str] = "agent-browser"
_AGENT_BROWSER_HINT_TEXT: Final[str] = (
    "You used `agent-browser` — remember to close the browser session when "
    "you're finished with it (its close/quit command) to avoid leaving an "
    "orphaned browser process running."
)


@dataclass(frozen=True)
class CommandHint:
    """One configured command-hint rule.

    Attributes:
        id: Stable identifier, used for TTL-state keying and for a project
            entry to override a built-in entry of the same id.
        pattern: A LITERAL command name (not an arbitrary regex — Plan 00212
            Technical Decision 1), matched at the start of a shell segment.
        hint: The reminder text injected as advisory context when this hint
            fires.
        ttl_seconds: Minimum seconds between two firings of this hint within
            one session. The PRIMARY rate-limit gate.
        min_calls_between: Optional SECONDARY gate — at least this many
            further matching calls must also occur before re-firing, even
            once ``ttl_seconds`` has elapsed. ``0`` (default) disables it.

    Raises:
        ValueError: if any field fails validation. This is FAIL FAST defence
            for the trusted/internal construction path (the built-in default
            below, and any hint the parser below has already validated) —
            external config that fails validation is instead skipped with a
            logged warning by :func:`_parse_hint_entry`, never raised here.
    """

    id: str
    pattern: str
    hint: str
    ttl_seconds: int
    min_calls_between: int = _DEFAULT_MIN_CALLS_BETWEEN

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("CommandHint.id must be a non-empty string")
        if not self.pattern.strip():
            raise ValueError("CommandHint.pattern must be a non-empty string")
        if not self.hint.strip():
            raise ValueError("CommandHint.hint must be a non-empty string")
        if self.ttl_seconds < 0:
            raise ValueError("CommandHint.ttl_seconds must be >= 0")
        if self.min_calls_between < 0:
            raise ValueError("CommandHint.min_calls_between must be >= 0")


@dataclass
class _HintFireState:
    """Per-(session_id, hint_id) TTL bookkeeping."""

    last_fired_monotonic: float
    calls_since_fire: int = 0


# The built-in default hint set (Plan 00212: exactly one hint ships).
_DEFAULT_HINTS: Final[tuple[CommandHint, ...]] = (
    CommandHint(
        id=_AGENT_BROWSER_HINT_ID,
        pattern=_AGENT_BROWSER_PATTERN,
        hint=_AGENT_BROWSER_HINT_TEXT,
        ttl_seconds=_DEFAULT_TTL_SECONDS,
    ),
)


def _segment_commands(command: str) -> list[str]:
    """Split ``command`` into top-level shell segments, each a command position.

    Uses the shared quote-aware scanner (``split_unquoted``) rather than a
    hand-rolled split, so a separator inside a quoted argument (a grep
    pattern, a commit message) is never mistaken for a real boundary.
    """
    return [
        segment.strip()
        for segment in split_unquoted(command, _SEGMENT_SEPARATORS)
        if segment.strip()
    ]


def _compile_hint_pattern(pattern: str) -> re.Pattern[str]:
    """Compile ``pattern`` into a segment-start-anchored command-name regex.

    Recognises the same invocation respellings the shared ``command_evasion``
    fragments defend against: an optional ``env `` prefix and an optional
    path qualifier (``/usr/local/bin/agent-browser``, ``./agent-browser``).

    Uses a ``(?=\\s|$)`` lookahead rather than ``\\b`` after the literal
    (Plan 00212 Technical Decision 2): a hyphenated command name like
    ``agent-browser`` ends on a non-word character to Python ``re``, so a
    trailing ``\\b`` would also match ``agent-browser-extra-tool`` — the
    boundary between ``r`` and ``-`` is itself a word/non-word transition.
    Requiring whitespace or end-of-segment instead closes that false
    positive.
    """
    return re.compile(rf"^{_ENV_PREFIX}{OPTIONAL_PATH}{re.escape(pattern)}(?=\s|$)")


def _parse_hint_entry(entry: Any, index: int) -> CommandHint | None:
    """Parse one raw ``hints[index]`` config entry into a :class:`CommandHint`.

    External config is validated defensively and degrades gracefully: a
    malformed entry is skipped (logged, never raised) so one bad line in a
    project's YAML cannot take down the whole handler — the same fail-open
    convention used for ``sensitive_content.public_patterns`` and
    ``background_process_tracker``'s option parsing. FAIL FAST instead
    applies to the TRUSTED construction path (``CommandHint.__post_init__``),
    which this function relies on to reject anything that slips through.

    Returns:
        A validated :class:`CommandHint`, or ``None`` if the entry is
        malformed (missing/empty required fields, or not a mapping at all).
    """
    if not isinstance(entry, dict):
        logger.warning("command_hints: hints[%d] is not a mapping; skipped", index)
        return None

    hint_id = str(entry.get(_KEY_ID, "") or "").strip()
    pattern = str(entry.get(_KEY_PATTERN, "") or "").strip()
    hint_text = str(entry.get(_KEY_HINT, "") or "").strip()
    if not hint_id or not pattern or not hint_text:
        logger.warning("command_hints: hints[%d] missing required id/pattern/hint; skipped", index)
        return None

    ttl_seconds = entry.get(_KEY_TTL_SECONDS, _DEFAULT_TTL_SECONDS)
    if not isinstance(ttl_seconds, int) or isinstance(ttl_seconds, bool) or ttl_seconds < 0:
        logger.warning(
            "command_hints: hints[%d] (%s) has invalid ttl_seconds; using default %d",
            index,
            hint_id,
            _DEFAULT_TTL_SECONDS,
        )
        ttl_seconds = _DEFAULT_TTL_SECONDS

    min_calls_between = entry.get(_KEY_MIN_CALLS_BETWEEN, _DEFAULT_MIN_CALLS_BETWEEN)
    if (
        not isinstance(min_calls_between, int)
        or isinstance(min_calls_between, bool)
        or min_calls_between < 0
    ):
        logger.warning(
            "command_hints: hints[%d] (%s) has invalid min_calls_between; using default %d",
            index,
            hint_id,
            _DEFAULT_MIN_CALLS_BETWEEN,
        )
        min_calls_between = _DEFAULT_MIN_CALLS_BETWEEN

    return CommandHint(
        id=hint_id,
        pattern=pattern,
        hint=hint_text,
        ttl_seconds=ttl_seconds,
        min_calls_between=min_calls_between,
    )


def _parse_raw_hints(raw: Any) -> list[CommandHint]:
    """Parse a raw ``options.hints`` config value into valid :class:`CommandHint`\\ s."""
    if not raw:
        return []
    if not isinstance(raw, list):
        logger.warning("command_hints: 'hints' option must be a list; ignoring")
        return []
    parsed: list[CommandHint] = []
    for index, entry in enumerate(raw):
        hint = _parse_hint_entry(entry, index)
        if hint is not None:
            parsed.append(hint)
    return parsed


class CommandHintsHandler(PostToolUseHandlerBase):
    """Inject a rate-limited advisory HINT when a configured command is detected.

    Generic and config-driven: ONE handler, a config object mapping command
    patterns to hint text — never a handler per hinted command. Ships with
    exactly one default hint (``agent-browser`` -> close-session reminder).
    ADVISORY ONLY: never blocks, never denies, never terminal.
    """

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.COMMAND_HINTS,
            priority=Priority.COMMAND_HINTS,
            terminal=False,
            tags=[
                HandlerTag.WORKFLOW,
                HandlerTag.ADVISORY,
                HandlerTag.NON_TERMINAL,
                HandlerTag.BASH,
            ],
        )
        # Config options — injected by the registry via setattr; typed and
        # defaulted here so mypy sees real attributes, not dynamic ones.
        self._mode: str = _DEFAULT_MODE
        self._hints: list[dict[str, Any]] | None = None

        # Lazily resolved (merged default+project) hints and their compiled
        # patterns — computed once on first use, after the registry has
        # applied any config options via setattr (Plan 00212; mirrors
        # pipe_blocker's `_languages_applied` lazy-application pattern).
        self._resolved_hints: list[CommandHint] | None = None
        self._compiled_patterns: dict[str, re.Pattern[str]] = {}

        # Per (session_id, hint_id) TTL bookkeeping — bounded, FIFO eviction.
        self._fire_state: dict[tuple[str, str], _HintFireState] = {}

    def _resolve_hints(self) -> list[CommandHint]:
        """Return the merged (default + project, or project-only) hint set, cached."""
        if self._resolved_hints is None:
            self._resolved_hints = self._build_hints()
            self._compiled_patterns = {
                hint.id: _compile_hint_pattern(hint.pattern) for hint in self._resolved_hints
            }
        return self._resolved_hints

    def _build_hints(self) -> list[CommandHint]:
        """Merge the built-in default hints with any project-configured hints.

        ``replace`` mode discards the built-in set entirely, using ONLY the
        project's hints (possibly zero — an explicit, if unusual, way to
        disable matching without ``enabled: false``). Any other value
        (including the default, unset ``_mode``) behaves as ``additive``: a
        project hint whose ``id`` matches a built-in one OVERRIDES it in
        place; a project hint with a new ``id`` is appended.
        """
        project_hints = _parse_raw_hints(self._hints)
        if self._mode == _MODE_REPLACE:
            return project_hints

        merged: dict[str, CommandHint] = {hint.id: hint for hint in _DEFAULT_HINTS}
        for hint in project_hints:
            merged[hint.id] = hint
        return list(merged.values())

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """True if the Bash command matches at least one configured hint's pattern."""
        if hook_input.get(HookInputField.TOOL_NAME) != ToolName.BASH:
            return False
        command = get_bash_command(hook_input)
        if not command:
            return False
        return bool(self._matching_hints(command))

    def _matching_hints(self, command: str) -> list[CommandHint]:
        """Every configured hint whose pattern matches a leading command position."""
        segments = _segment_commands(command)
        if not segments:
            return []
        return [
            hint
            for hint in self._resolve_hints()
            if any(self._compiled_patterns[hint.id].match(segment) for segment in segments)
        ]

    def handle(self, hook_input: dict[str, Any]) -> BlockingResult:
        """Fire any due hints as advisory context. Always ALLOW — never blocks."""
        command = get_bash_command(hook_input) or ""
        session_id = str(hook_input.get(HookInputField.SESSION_ID, "") or "unknown")

        matched = self._matching_hints(command)
        if not matched:
            return BlockingResult(decision=Decision.ALLOW)

        fired = [hint for hint in matched if self._should_fire(session_id, hint)]
        if not fired:
            return BlockingResult(decision=Decision.ALLOW)
        return BlockingResult(
            decision=Decision.ALLOW, context=[self._render(hint) for hint in fired]
        )

    def _should_fire(self, session_id: str, hint: CommandHint) -> bool:
        """Apply the TTL (+ optional count) gate; records a firing when it fires."""
        key = (session_id, hint.id)
        now = time.monotonic()
        state = self._fire_state.get(key)

        if state is None:
            self._record_fire(key, now)
            return True

        elapsed = now - state.last_fired_monotonic
        ttl_ready = elapsed >= hint.ttl_seconds
        count_ready = (
            hint.min_calls_between <= 0 or state.calls_since_fire >= hint.min_calls_between
        )

        if ttl_ready and count_ready:
            self._record_fire(key, now)
            return True

        state.calls_since_fire += 1
        return False

    def _record_fire(self, key: tuple[str, str], now: float) -> None:
        """Record a firing for ``key``, bounding the tracked-state map (FIFO eviction)."""
        if key not in self._fire_state and len(self._fire_state) >= _MAX_TRACKED_FIRE_STATES:
            del self._fire_state[next(iter(self._fire_state))]
        self._fire_state[key] = _HintFireState(last_fired_monotonic=now, calls_since_fire=0)

    @staticmethod
    def _render(hint: CommandHint) -> str:
        return f"💡 {hint.hint}"

    def get_claude_md(self) -> str | None:
        return (
            "## command_hints — advisory reminders after specific commands\n\n"
            "PostToolUse advisory (never blocks). When a configured command is detected "
            "in a Bash call, a HINT is injected reminding you of a follow-up action. "
            "Shipped default: running `agent-browser` reminds you to close the browser "
            "session when finished.\n\n"
            "**Rate-limited per hint** — each hint has a `ttl_seconds` cooldown "
            "(tracked per session + hint id) so it does not repeat on every matching "
            "command; state resets on daemon restart, so a hint may fire once more "
            "after a restart.\n\n"
            "**Configure** via `handlers.post_tool_use.command_hints.options`: "
            "`mode: additive` (default) appends your `hints` list to the built-in set "
            "— a project entry whose `id` matches a built-in one overrides it; "
            "`mode: replace` discards the built-in set entirely and uses only your "
            "list. Each hint: `id`, `pattern` (a literal command name, matched at the "
            "start of a shell segment — path-qualified and `env`-prefixed spellings "
            "are recognised, but it never fires on the word appearing as an unrelated "
            "argument), `hint` (the reminder text), `ttl_seconds`, and optional "
            "`min_calls_between` (secondary count-based gate). Disable with "
            "`handlers.post_tool_use.command_hints.enabled: false`."
        )

    def get_acceptance_tests(self) -> list[Any]:
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="agent-browser command triggers close-session hint",
                command="agent-browser --version",
                description=(
                    "Running a command starting with `agent-browser` surfaces the "
                    "close-session reminder as advisory context. The binary need not "
                    "exist — the daemon inspects the command STRING, not the outcome."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"agent-browser", r"close"],
                safety_notes=(
                    "Harmless whether or not agent-browser is installed: a missing "
                    "binary just exits 127 (command not found), no side effects."
                ),
                test_type=TestType.ADVISORY,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="unrelated command mentioning agent-browser does not trigger a hint",
                command="grep agent-browser /dev/null",
                description=(
                    "The word `agent-browser` appearing as an ARGUMENT to an unrelated "
                    "command (not the command itself) must NOT surface the hint — "
                    "verify no advisory context about agent-browser appears."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="grep against /dev/null is a safe no-op read.",
                test_type=TestType.ADVISORY,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=False,
            ),
        ]
