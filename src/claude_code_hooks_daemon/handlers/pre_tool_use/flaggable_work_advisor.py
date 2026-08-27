"""FlaggableWorkAdvisorHandler - delegate-first advisory for flaggable work.

Plan 00278 Phase 3. Some caller models carry an API-side content safety
classifier that keys on attack-mechanics CONTENT, not intent: reading or
producing text describing attack/spoofing/evasion/exploit/rootkit mechanics —
even defensively — can silently downgrade the session's model for its whole
remainder. The durable prevention is DELEGATION: recognise the flaggable
category from the task framing or the target path, and hand the WHOLE sub-task
to a quarantine subagent BEFORE the main context reads the flaggable content.

This PreToolUse handler is the deterministic backstop for that discipline.
When a ``Read``/``Edit``/``Write``/``Grep`` targets a path matching the
project's configured flaggable globs, or a ``Bash`` command mentions such a
path, or the tool input text matches 2+ configured topic terms, it ADVISES
(never denies) delegating to the quarantine subagent. Advisory-only and
non-terminal by design — the boundary is domain-specific, over-routing is its
own failure, and the project owns the trigger set.

Rate-limited on the ``lsp_enforcement`` model: once per session per matched
key (the matched path, or the topic-term route), so a deliberate retry passes
silently.

Ships DISABLED: with no configured globs the path routes are inert, and only
a project that has this problem should opt into the topic-term seed.
"""

from __future__ import annotations

import json
import logging
from fnmatch import fnmatch
from typing import Any, Final

from claude_code_hooks_daemon.constants import (
    HandlerID,
    HandlerTag,
    HookInputField,
    Priority,
    ToolName,
)
from claude_code_hooks_daemon.core import Decision, GatingResult
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.core.utils import get_bash_command

logger = logging.getLogger(__name__)

# ── Config modes (command_hints' clobber-or-extend convention) ──────────────
_MODE_ADDITIVE: Final[str] = "additive"
_MODE_REPLACE: Final[str] = "replace"
_DEFAULT_MODE: Final[str] = _MODE_ADDITIVE

# ── Built-in seeds and defaults ─────────────────────────────────────────────
# The topic-term seed is deliberately NARROW: only attack-mechanics vocabulary
# that recurs across field reports, never general security words ("firewall",
# "credential") that would over-route routine defensive work.
_SEED_TOPIC_TERMS: Final[tuple[str, ...]] = (
    "spoof",
    "spoofing",
    "evasion",
    "exploit",
    "rootkit",
)
_SEED_PATH_GLOBS: Final[tuple[str, ...]] = ()
_DEFAULT_QUARANTINE_AGENT: Final[str] = "hooks-daemon-opus-security"

# The topic route needs at least this many DISTINCT terms present — one word
# alone ("we patched the exploit") is routine prose, two is a mechanics text.
_MIN_TOPIC_TERM_HITS: Final[int] = 2

# Rate-limit key for the topic-term route (path routes use the path itself).
_TOPIC_ROUTE_KEY: Final[str] = "topic-terms"

# Tools whose target path is inspected directly.
_PATH_TOOLS: Final[tuple[str, ...]] = (
    ToolName.READ,
    ToolName.EDIT,
    ToolName.WRITE,
    ToolName.GREP,
)
# tool_input keys that can carry the target path, checked in order.
_PATH_INPUT_KEYS: Final[tuple[str, ...]] = ("file_path", "path")

# Bound the advised-key memory (same FIFO shape as command_hints).
_MAX_ADVISED_KEYS: Final[int] = 512

# Characters stripped from Bash tokens before glob matching (quotes and
# trailing shell punctuation around a path argument).
_TOKEN_STRIP_CHARS: Final[str] = "'\"`;,()"


class FlaggableWorkAdvisorHandler(PreToolUseHandlerBase):
    """Advise delegating safeguard-flaggable work BEFORE opening the content.

    ADVISORY ONLY: ``terminal=False`` and ``handle()`` has no DENY branch —
    the point is a reminder at the exact moment the delegate-before-reading
    decision must be made, never a block.
    """

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.FLAGGABLE_WORK_ADVISOR,
            priority=Priority.FLAGGABLE_WORK_ADVISOR,
            terminal=False,
            tags=[
                HandlerTag.ADVISORY,
                HandlerTag.NON_TERMINAL,
                HandlerTag.WORKFLOW,
            ],
        )
        # Options — injected by the registry via setattr; typed and defaulted
        # here so mypy sees real attributes (command_hints convention).
        self._mode: str = _DEFAULT_MODE
        self._flaggable_path_globs: list[str] = []
        self._flaggable_topic_terms: list[str] = []
        self._quarantine_agent: str = _DEFAULT_QUARANTINE_AGENT

        # (session_id, matched key) pairs already advised — bounded FIFO.
        self._advised: dict[tuple[str, str], None] = {}

    def get_default_enabled(self) -> bool:
        """Opt-in: the flaggable boundary is project-specific (Plan 00278)."""
        return False

    # ── Effective config (mode: additive | replace) ─────────────────────────

    def _effective_globs(self) -> list[str]:
        return self._merge(_SEED_PATH_GLOBS, self._flaggable_path_globs)

    def _effective_terms(self) -> list[str]:
        return self._merge(_SEED_TOPIC_TERMS, self._flaggable_topic_terms)

    def _merge(self, seed: tuple[str, ...], configured: list[str] | None) -> list[str]:
        """Merge a built-in seed list with the project's configured list.

        ``replace`` discards the seed entirely; anything else (including the
        default) appends project entries to the seed, deduplicated.
        """
        project = [str(entry) for entry in (configured or []) if str(entry).strip()]
        if self._mode == _MODE_REPLACE:
            return project
        merged: list[str] = list(seed)
        for entry in project:
            if entry not in merged:
                merged.append(entry)
        return merged

    # ── Matching ────────────────────────────────────────────────────────────

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """True when an un-advised flaggable route matches this call."""
        return bool(self._pending_keys(hook_input))

    def _pending_keys(self, hook_input: dict[str, Any]) -> list[str]:
        """Matched rate-limit keys not yet advised for this session."""
        if not isinstance(hook_input, dict):
            return []
        session_id = str(hook_input.get(HookInputField.SESSION_ID, "") or "unknown")
        return [
            key for key in self._matched_keys(hook_input) if (session_id, key) not in self._advised
        ]

    def _matched_keys(self, hook_input: dict[str, Any]) -> list[str]:
        """Every flaggable route this tool call matches (paths, then topic)."""
        tool_name = hook_input.get(HookInputField.TOOL_NAME)
        tool_input = hook_input.get(HookInputField.TOOL_INPUT)
        if not isinstance(tool_input, dict):
            return []

        keys: list[str] = []
        globs = self._effective_globs()

        if tool_name in _PATH_TOOLS and globs:
            for path_key in _PATH_INPUT_KEYS:
                candidate = tool_input.get(path_key)
                if isinstance(candidate, str) and self._path_matches(candidate, globs):
                    keys.append(candidate)
                    break
        elif tool_name == ToolName.BASH and globs:
            command = get_bash_command(hook_input) or ""
            for token in command.split():
                cleaned = token.strip(_TOKEN_STRIP_CHARS)
                if cleaned and self._path_matches(cleaned, globs):
                    keys.append(cleaned)
                    break

        if not keys and self._topic_terms_hit(tool_input):
            keys.append(_TOPIC_ROUTE_KEY)
        return keys

    @staticmethod
    def _path_matches(path: str, globs: list[str]) -> bool:
        """Glob match tolerant of relative globs against absolute paths."""
        for pattern in globs:
            if fnmatch(path, pattern):
                return True
            if not pattern.startswith("/") and fnmatch(path, f"*/{pattern}"):
                return True
        return False

    def _topic_terms_hit(self, tool_input: dict[str, Any]) -> bool:
        """True when 2+ DISTINCT configured topic terms appear in the input text."""
        terms = self._effective_terms()
        if len(terms) < _MIN_TOPIC_TERM_HITS:
            return False
        try:
            text = json.dumps(tool_input).lower()
        except (TypeError, ValueError):
            return False
        hits = {term for term in terms if term.lower() in text}
        return len(hits) >= _MIN_TOPIC_TERM_HITS

    # ── Handling ────────────────────────────────────────────────────────────

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        """ALLOW with the delegate-first advisory; record the rate-limit keys."""
        session_id = str(hook_input.get(HookInputField.SESSION_ID, "") or "unknown")
        pending = self._pending_keys(hook_input)
        if not pending:
            return GatingResult(decision=Decision.ALLOW)

        for key in pending:
            self._record_advised(session_id, key)
        return GatingResult(decision=Decision.ALLOW, context=[self._advisory(pending)])

    def _record_advised(self, session_id: str, key: str) -> None:
        map_key = (session_id, key)
        if map_key not in self._advised and len(self._advised) >= _MAX_ADVISED_KEYS:
            del self._advised[next(iter(self._advised))]
        self._advised[map_key] = None

    def _advisory(self, matched_keys: list[str]) -> str:
        matched = ", ".join(matched_keys)
        return (
            "⚠️ This looks safeguard-flaggable (matched: "
            f"{matched}). Reading or producing attack-mechanics content in "
            "THIS context can silently downgrade the session's model.\n\n"
            "Delegate the WHOLE sub-task to the quarantine subagent BEFORE "
            "opening the content:\n"
            f'  Agent(subagent_type: "{self._quarantine_agent}", '
            "prompt: <goal + files, not a narration>)\n\n"
            "Decide from the framing and the path — never by reading first "
            "(scouting first is reading first) — and take back only the clean "
            "summary. If this call is routine work with no attack-mechanics "
            "text, retry it: this advisory fires once per session per match."
        )

    # ── Guidance surfaces ───────────────────────────────────────────────────

    def get_claude_md(self) -> str | None:
        return (
            "## flaggable_work_advisor — delegate flaggable work BEFORE reading it\n\n"
            "Advisory only (never denies; ships disabled). When a Read/Edit/"
            "Write/Grep targets a configured flaggable path, a Bash command "
            "mentions one, or the tool input carries 2+ configured "
            "attack-mechanics topic terms, it reminds you: reading or "
            "producing that content in the MAIN context can silently trip a "
            "safety classifier and downgrade the session's model for its "
            "whole remainder.\n\n"
            "**The move**: delegate the WHOLE sub-task to the quarantine "
            "subagent BEFORE opening the content — "
            '`Agent(subagent_type: "<quarantine_agent>")` — deciding from '
            "the framing and the path, never by reading first (scouting "
            "first IS reading first), and take back only the clean summary.\n\n"
            "**Configure** via `handlers.pre_tool_use.flaggable_work_advisor."
            "options`: `flaggable_path_globs` (default empty), "
            "`flaggable_topic_terms` (seed: spoof, spoofing, evasion, "
            "exploit, rootkit), `quarantine_agent` (default "
            "`hooks-daemon-opus-security`), and `mode: additive` (default — "
            "project lists extend the seeds) or `replace` (project lists "
            "stand alone). Rate-limited once per session per matched path, "
            "so a deliberate retry passes silently."
        )

    def get_acceptance_tests(self) -> list[Any]:
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="flaggable topic terms trigger the delegate-first advisory",
                command='echo "exploit rootkit mechanics discussion"',
                description=(
                    "A tool input carrying two or more configured topic terms "
                    "surfaces the delegate-to-quarantine-subagent advisory as "
                    "context; the call is still allowed."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"safeguard-flaggable", r"subagent_type"],
                safety_notes=(
                    "Advisory only — echo of two harmless words; requires the "
                    "handler to be enabled (ships disabled)."
                ),
                test_type=TestType.ADVISORY,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="single topic term does not trigger the advisory",
                command='echo "we patched the exploit yesterday"',
                description=(
                    "One term alone is routine prose — verify no "
                    "safeguard-flaggable advisory appears."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Advisory-only handler; echo is a safe no-op.",
                test_type=TestType.ADVISORY,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=False,
            ),
        ]
