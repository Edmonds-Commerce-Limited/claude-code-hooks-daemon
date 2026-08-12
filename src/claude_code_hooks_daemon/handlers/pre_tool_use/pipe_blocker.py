"""PipeBlockerHandler - three-tier decision for commands piped to tail/head.

Three-tier logic:
  1. Matches whitelist?  → ALLOW (grep, awk, jq, ls, git tag, etc.)
  2. Matches blacklist?  → DENY: "expensive command, use temp file"
  3. Unknown?           → DENY: "unrecognized, add to extra_whitelist or use temp file"

Uses Strategy Pattern: all language-specific blacklist patterns are delegated to
PipeBlockerStrategy implementations registered in PipeBlockerStrategyRegistry.
The handler itself has ZERO language awareness.
"""

import logging
import os
import re
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import (
    Decision,
    Handler,
    HookResult,
    get_data_layer,
)
from claude_code_hooks_daemon.core.utils import get_bash_command
from claude_code_hooks_daemon.strategies.pipe_blocker.common import UNIVERSAL_WHITELIST_PATTERNS
from claude_code_hooks_daemon.strategies.pipe_blocker.registry import PipeBlockerStrategyRegistry
from claude_code_hooks_daemon.utils.shell_segmentation import split_unquoted

logger = logging.getLogger(__name__)

# Config key hints shown in unknown-command message
_CONFIG_HINT_EXTRA_WHITELIST = "extra_whitelist"
_CONFIG_HINT_HANDLER = "handlers.pre_tool_use.pipe_blocker"
_CONFIG_YAML_KEY = "pipe_blocker"

# Default preview line count suggested in the echd-capture recommendation.
_ECHD_CAPTURE_DEFAULT_LINES = 20
# Name of the deployed capture helper (Plan 00164 Phase 6) and its location
# relative to the daemon dir (parent of the untracked runtime dir).
_ECHD_CAPTURE_NAME = "echd-capture"
_ECHD_CAPTURE_REL_PARTS = ("scripts", _ECHD_CAPTURE_NAME)

# Redaction placeholder substituted for a -m/-F message VALUE before pipe
# detection. Deliberately contains no "|" so it can never itself trigger a
# false match.
_MESSAGE_BODY_PLACEHOLDER = "<REDACTED>"

# Sanity-check thresholds before templating a remediation block (Plan 00209
# §1 / Task 1.2). Field report: a heredoc journal entry whose PROSE described
# an earlier pipe block tripped detection (correct — the literal characters
# of a pipe-to-pager were present). The defect was what happened NEXT: the
# matched "command" was run through the extra_whitelist/echd-capture
# templates, which extracted "the" (the first word of a SENTENCE) as a binary
# name and offered `extra_whitelist: - "^the\\b"` plus a full remediation
# block — a correct safety decision presented as broken, and several hundred
# lines of the agent's own prose echoed back into a denial reason. Detection
# itself is NOT changed (Non-Goals) — only whether the verbose template is
# safe to build from what was matched.
#
# A real "text before a pipe" shell segment is rarely long; prose commonly
# is. This is a structural heuristic, not shell parsing.
_MAX_SOURCE_SEGMENT_CHARS_FOR_TEMPLATE = 80

# Closed-class English function words (articles, pronouns, conjunctions,
# prepositions, common auxiliary verbs, wh-words) — never a valid Unix
# command name, so a first token drawn from this set is always prose. This
# is what actually happened in the field report: the sentence "the guardrail
# blocks piping straight to a pager... | tail" had "the" as its first word.
_COMMON_ENGLISH_FUNCTION_WORDS: frozenset[str] = frozenset(
    {
        "a",
        "an",
        "the",
        "this",
        "that",
        "these",
        "those",
        "it",
        "its",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "and",
        "or",
        "but",
        "so",
        "because",
        "if",
        "when",
        "while",
        "as",
        "which",
        "who",
        "whom",
        "what",
        "why",
        "how",
        "where",
        "of",
        "in",
        "on",
        "at",
        "to",
        "for",
        "with",
        "from",
        "by",
        "about",
    }
)

# Leading/trailing punctuation stripped from a candidate first token before
# comparing against the function-word set (heredoc prose often starts
# mid-sentence, or the token was quoted).
_LEADING_TRAILING_PUNCTUATION = ".,;:!?\"'()[]{}"

# Task 1.3: the echoed COMMAND line is capped at this many characters
# regardless of path (blacklisted/unknown/prose) — the full text is rarely
# what makes a block actionable, and re-quoting a long command wastes
# context. Applied uniformly, not just to the prose fallback.
_MAX_ECHOED_COMMAND_CHARS = 500
_TRUNCATION_SUFFIX = "… [truncated]"

# Shell separators that end one command and begin the next. A NEWLINE is one of
# them: omitting it meant a multi-line command never split, so the producer for
# "cd /workspace\ngrep foo | head" resolved to the whole two-line string and no
# anchored whitelist pattern (e.g. ^grep\b) could match it — denying a
# whitelisted producer purely because of how the caller laid the command out.
# Ordered longest-first so "&&" is preferred over a bare "&" prefix match.
_CHAIN_SEPARATORS: tuple[str, ...] = ("&&", "||", ";", "\n")

# The shell pipe. Split separately from the chain separators because the pipe
# split must run AFTER the chain split has narrowed to the final command.
_PIPE_SEPARATORS: tuple[str, ...] = ("|",)

# Matches a `-m`/`--message`/`-F`/`--file` flag immediately followed by its
# VALUE, so the value's content can be excluded from pipe detection: these
# flags carry human-authored prose (a commit/tag message, or a message-file
# path), never shell syntax to execute. A literal "| tail" inside that prose
# — e.g. this very handler's own CLAUDE.md example, quoted in a commit
# message describing a fix for it — is DATA, not a pipe operator.
#
# Three value shapes, tried in order (DOTALL so "." spans newlines, needed
# for the heredoc alternative's body):
#   1. The canonical heredoc-embedded message idiom used throughout this
#      repo: -m "$(cat <<'EOF' ... EOF)" (leading whitespace before the
#      closing delimiter is tolerated — messages are often re-indented).
#   2. A single- or double-quoted string (may itself span multiple literal
#      newlines — bash allows that inside quotes).
#   3. A bare word (e.g. -F commit-msg.txt) as a fallback.
_MESSAGE_BODY_PATTERN = re.compile(
    r"(?P<flag>(?<![\w-])(?:-m|--message|-F|--file))"
    r"(?P<sep>=|\s+)"
    r"(?P<value>"
    r"\"\$\(cat\s+<<-?\s*'?(?P<delim>\w+)'?\s*\n.*?\n[ \t]*(?P=delim)[ \t]*\n?\s*\)\""
    r"|'(?:[^'\\]|\\.)*'"
    r'|"(?:[^"\\]|\\.)*"'
    r"|\S+"
    r")",
    re.DOTALL,
)


class PipeBlockerHandler(Handler):
    """Block expensive commands piped to tail/head to prevent information loss.

    Three-tier decision system:
    1. Whitelist (universal + extra_whitelist): always ALLOW
    2. Blacklist (language strategies + extra_blacklist): always DENY with
       "expensive command" message
    3. Unknown: DENY with "unrecognized command, add to extra_whitelist" message

    Language-specific blacklists are managed by PipeBlockerStrategy implementations
    in the pipe_blocker strategy domain. The handler has zero language awareness.

    Configuration options (set via YAML config):
        extra_whitelist: list[str] - Additional regex patterns to always allow.
            Example: ["^git\\\\s+log\\\\b"]  — allows git log | tail
        extra_blacklist: list[str] - Additional regex patterns to always block.
            Example: ["^my_test_runner\\\\b"]
        languages: list[str] — Restrict to specific language blacklists.
            Universal is always active. If unset, ALL language blacklists are used.
    """

    def __init__(self, options: dict[str, Any] | None = None) -> None:
        """Initialize with optional per-project extra whitelist/blacklist."""
        super().__init__(
            handler_id=HandlerID.PIPE_BLOCKER,
            priority=Priority.PIPE_BLOCKER,
            tags=[HandlerTag.SAFETY, HandlerTag.BASH, HandlerTag.BLOCKING, HandlerTag.TERMINAL],
        )
        options = options or {}

        # Strategy registry for language-specific blacklists
        self._registry = PipeBlockerStrategyRegistry.create_default()

        # Project-level extra whitelist/blacklist (from options/config)
        self._extra_whitelist: list[re.Pattern[str]] = [
            re.compile(p, re.IGNORECASE) for p in options.get("extra_whitelist", [])
        ]
        self._extra_blacklist: list[str] = list(options.get("extra_blacklist", []))

        # Language filtering (applied lazily on first use)
        self._languages: list[str] | None = None
        self._languages_applied: bool = False

        # Pre-compiled universal whitelist patterns
        self._whitelist: list[re.Pattern[str]] = [
            re.compile(p, re.IGNORECASE) for p in UNIVERSAL_WHITELIST_PATTERNS
        ]

        # Pipe detection patterns
        self._pipe_pattern: re.Pattern[str] = re.compile(r"\|\s*(tail|head)\b", re.IGNORECASE)
        self._tail_follow_pattern: re.Pattern[str] = re.compile(r"\btail\s+-[a-z]*f", re.IGNORECASE)
        self._head_bytes_pattern: re.Pattern[str] = re.compile(r"\bhead\s+-[a-z]*c", re.IGNORECASE)

    def _apply_language_filter(self) -> None:
        """Apply language filter to registry on first use (lazy)."""
        if self._languages_applied:
            return
        self._languages_applied = True
        effective_languages = self._languages or getattr(self, "_project_languages", None)
        if effective_languages:
            self._registry.filter_by_languages(effective_languages)

    @staticmethod
    def _strip_message_bodies(command: str) -> str:
        """Blank out `-m`/`--message`/`-F`/`--file` VALUES before pipe scanning.

        These flags carry human-authored prose (a commit/tag message, or a
        message-file path), never shell syntax to execute. A literal
        "| tail" inside that prose — e.g. a commit message documenting this
        very handler — must never be mistaken for a real pipe operator.
        Everything else in the command (including a REAL pipe elsewhere) is
        left untouched.
        """
        return _MESSAGE_BODY_PATTERN.sub(
            lambda m: f"{m.group('flag')}{m.group('sep')}{_MESSAGE_BODY_PLACEHOLDER}",
            command,
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Check if command pipes a non-whitelisted operation to tail/head.

        Returns True (block) if:
        - Bash tool with pipe to tail/head
        - NOT tail -f or head -c (these are allowed)
        - Source segment does NOT match whitelist (universal + extra_whitelist)

        Returns False (allow) if:
        - Not a Bash tool
        - No pipe to tail/head
        - tail -f or head -c
        - Source segment is whitelisted (cheap filtering/output commands)
        """
        self._apply_language_filter()

        command = get_bash_command(hook_input)
        if not command:
            return False

        # -m/-F message VALUES are data, not shell syntax — scan a copy with
        # them blanked out so prose inside a commit message can never be
        # mistaken for a real pipe. A real pipe elsewhere in the SAME
        # command is untouched and still detected.
        scan_target = self._strip_message_bodies(command)

        if not self._pipe_pattern.search(scan_target):
            return False

        # Allow tail -f (follow mode) and head -c (byte count)
        if self._tail_follow_pattern.search(scan_target):
            return False
        if self._head_bytes_pattern.search(scan_target):
            return False

        # Extract full source segment before pipe to tail/head
        source_segment = self._extract_source_segment(scan_target)

        # Step 1: Whitelist check — if whitelisted, always allow
        if self._matches_whitelist(source_segment):
            return False

        # Steps 2 & 3: Blacklisted or unknown → block
        return True

    def _extract_source_segment(self, command: str) -> str:
        """Extract full segment before pipe to tail/head.

        Returns the FULL segment text (not just first word), enabling
        multi-word pattern matching like r'^npm\\s+test\\b'.

        Examples:
            "find . | tail -n 20"           -> "find ."
            "npm test | tail -5"            -> "npm test"
            "go test ./... | tail -20"      -> "go test ./..."
            "grep err log | awk '{p}' | tail" -> "awk '{p}'"
            "npm test && grep FAIL | tail"  -> "grep FAIL"
            'cmd | grep -E "a|b" | head'    -> 'grep -E "a|b"'

        Returns empty string if extraction fails (treated as unknown command).
        """
        try:
            match = self._pipe_pattern.search(command)
            if not match:
                return ""

            # Get everything before the pipe to tail/head
            before_pipe = command[: match.start()]

            # Handle command chains (&&, ||, ;, newline) — take the last segment.
            # Quote-aware so a separator inside a quoted argument (grep -E "a;b")
            # is not mistaken for a chain.
            before_pipe = split_unquoted(before_pipe, _CHAIN_SEPARATORS)[-1]

            # Handle multiple actual pipes — take the last segment.
            # Quote-aware split prevents false splits on | inside grep patterns
            # like grep -E "15:56|15:57" where | is a regex alternation, not a pipe.
            before_pipe = split_unquoted(before_pipe, _PIPE_SEPARATORS)[-1]

            return before_pipe.strip()

        except Exception:  # nosec B110 - fail-safe: extraction error → empty string (unknown)
            return ""

    def _matches_whitelist(self, source_segment: str) -> bool:
        """Check if source segment matches the whitelist (never block)."""
        if not source_segment:
            return False
        for pattern in self._whitelist:
            if pattern.search(source_segment):
                return True
        return any(pattern.search(source_segment) for pattern in self._extra_whitelist)

    def _matches_blacklist(self, source_segment: str) -> bool:
        """Check if source segment matches any blacklisted pattern (known expensive)."""
        if not source_segment:
            return False
        # Check language strategy patterns
        for pattern_str in self._registry.get_blacklist_patterns():
            if re.search(pattern_str, source_segment, re.IGNORECASE):
                return True
        # Check extra blacklist from config
        for pattern_str in self._extra_blacklist:
            if re.search(pattern_str, source_segment, re.IGNORECASE):
                return True
        return False

    def _resolve_echd_capture_path(self) -> Path | None:
        """Resolve the deployed ``echd-capture`` helper to an absolute path.

        Looks under the daemon dir (the parent of the untracked runtime dir),
        which resolves correctly for BOTH install modes:
          - Self-install (dogfooding): {project_root}/scripts/echd-capture
          - Normal client install: {project_root}/.claude/hooks-daemon/scripts/echd-capture

        If the helper exists but lost its executable bit (e.g. a client
        checkout with ``git core.fileMode=false``), self-heal by chmod'ing it —
        this is the daemon's own vendored script, so fixing its permissions in
        place is safe and expected.

        Returns:
            Absolute path to a present AND executable helper, or ``None`` if
            it cannot be found/made executable anywhere plausible.
        """
        from claude_code_hooks_daemon.core.project_context import ProjectContext

        daemon_dir: Path | None
        try:
            daemon_dir = ProjectContext.daemon_untracked_dir().parent
        except RuntimeError:
            # ProjectContext not initialised (default-config / standalone
            # entry point / unit tests). This is an expected branch, not an
            # error: the caller falls back to the temp-file guidance whenever
            # no helper path can be resolved.
            daemon_dir = None
        if daemon_dir is None:
            return None

        helper = daemon_dir.joinpath(*_ECHD_CAPTURE_REL_PARTS)
        if not helper.is_file():
            return None

        if not os.access(helper, os.X_OK):
            # Self-heal a lost exec bit (e.g. a client checkout with
            # git core.fileMode=false). A chmod failure is logged, never
            # swallowed, and degrades to the temp-file guidance below rather
            # than crashing a block message.
            try:
                helper.chmod(0o755)
            except OSError as exc:
                logger.warning(
                    "Could not restore exec bit on echd-capture helper %s: %s", helper, exc
                )
            if not os.access(helper, os.X_OK):
                return None

        return helper

    def _capture_helper_invocation(self) -> str | None:
        """Return the recommended ``echd-capture`` invocation, or None if unresolved.

        Resolved to the deployed helper's ABSOLUTE path so the recommended
        command works from any cwd. Returns ``None`` (never the bare command
        name) when the helper cannot be found — a bare ``echd-capture`` is not
        on PATH in client installs and would fail if run as suggested.
        """
        helper = self._resolve_echd_capture_path()
        return str(helper) if helper is not None else None

    def _temp_file_block(self, source_segment: str) -> str:
        """Shell snippet: redirect to a temp file and report the exit code."""
        source = source_segment or "command"
        return (
            f'  TEMP_FILE="/tmp/output_$$.txt"\n'
            f'  {source} > "$TEMP_FILE" 2>&1\n'
            f"  EXIT_CODE=$?\n"
            f'  if [ $EXIT_CODE -eq 0 ]; then echo "Completed OK"; '
            f'else echo "Completed with errors (exit code: $EXIT_CODE) - check $TEMP_FILE"; fi\n'
        )

    def _echd_capture_recommendation(self, source_segment: str) -> str:
        """Verbose recommendation block: ``echd-capture`` when resolvable,
        otherwise the always-works temp-file redirect (never a bare, possibly
        not-on-PATH ``echd-capture`` command).

        When resolvable, this is the PRIMARY alternative — it captures the
        FULL output and prints only a bounded preview + the capture path,
        replacing the pointless "redirect to a file then echo it all to
        stdout" theatre agents fall into.
        """
        helper = self._capture_helper_invocation()
        source = source_segment or "command"

        if helper is None:
            return (
                f"✅ RECOMMENDED ALTERNATIVE — redirect to a temp file and capture "
                f"the exit code:\n\n{self._temp_file_block(source_segment)}"
            )

        return (
            f"✅ RECOMMENDED ALTERNATIVE — capture full output, preview a slice "
            f"({_ECHD_CAPTURE_NAME}):\n\n"
            f"  set -o pipefail\n"
            f"  {source} 2>&1 | {helper} {_ECHD_CAPTURE_DEFAULT_LINES}\n\n"
            f"  → prints the last {_ECHD_CAPTURE_DEFAULT_LINES} lines AND the path to the "
            f"FULL capture for follow-up.\n"
            f"    Use `--head N` for the first N lines. `set -o pipefail` keeps "
            f"{source}'s own exit status visible.\n\n"
            f"  Or, without a pipe — redirect to a temp file and capture the exit code:\n\n"
            f"{self._temp_file_block(source_segment)}"
        )

    def _echd_capture_terse(self, source_segment: str) -> str:
        """One-line recommendation for terse (repeat) blocks.

        Falls back to the temp-file redirect (never a bare ``echd-capture``
        token) when the helper cannot be resolved.
        """
        helper = self._capture_helper_invocation()
        source = source_segment or "command"
        if helper is None:
            return (
                f'Redirect to a temp file: TEMP_FILE="/tmp/output_$$.txt"; '
                f'{source} > "$TEMP_FILE" 2>&1\n'
            )
        return (
            f"Capture full + preview: set -o pipefail; "
            f"{source} 2>&1 | {helper} {_ECHD_CAPTURE_DEFAULT_LINES}\n"
        )

    def _get_block_count(self) -> int:
        """Get number of previous blocks by this handler."""
        try:
            return get_data_layer().history.count_blocks_by_handler(self.name)
        except Exception:
            return 0

    @staticmethod
    def _truncate_command(command: str) -> str:
        """Cap the echoed COMMAND text (Task 1.3): the full text is rarely
        what makes a block actionable, and re-quoting a long command wastes
        context. Applied unconditionally, regardless of which message path
        is used below."""
        if len(command) <= _MAX_ECHOED_COMMAND_CHARS:
            return command
        return command[:_MAX_ECHOED_COMMAND_CHARS] + _TRUNCATION_SUFFIX

    @staticmethod
    def _looks_like_prose(source_segment: str) -> bool:
        """Sanity-check before templating (Task 1.2): does the matched text
        look like a real shell command, or like prose that happens to
        contain the literal characters of a pipe-to-pager?

        Two independent, purely structural/lexical triggers — no shell
        parsing (Non-Goals: detection itself is unchanged):

        - the segment is implausibly long for "text before a pipe" in a
          real command (a heredoc/prose sentence commonly is; a shell
          command piped to tail/head rarely is)
        - its first token is a closed-class English function word — never a
          valid Unix command name (this is the exact field-report failure:
          "the" extracted as a binary name from a sentence)
        """
        if not source_segment:
            return False
        if len(source_segment) > _MAX_SOURCE_SEGMENT_CHARS_FOR_TEMPLATE:
            return True
        words = source_segment.split()
        if not words:
            return False
        first_token = words[0].strip(_LEADING_TRAILING_PUNCTUATION).lower()
        return first_token in _COMMON_ENGLISH_FUNCTION_WORDS

    def _prose_reason(self) -> str:
        """Short, accurate block reason for matched text that looks like
        prose, not a shell command (Task 1.1/1.2). Deliberately carries NO
        remediation template and does NOT echo the matched text back — the
        field-report defect was exactly a correct safety decision presented
        as broken by re-quoting a large amount of the agent's own prose
        wrapped in fabricated shell scaffolding.
        """
        return (
            "🚫 BLOCKED: pipe-like pattern (`| tail` / `| head`) detected, but the "
            "matched text does not look like a real shell command\n\n"
            "WHY BLOCKED:\n"
            "  • This handler errs on the side of caution and cannot reliably tell "
            "heredoc/prose content apart from executable shell text\n"
            "  • The matched text is not shown here — it did not look like a "
            "command, so re-quoting it would not help\n\n"
            "IF THIS WAS A REAL COMMAND: rephrase so the piped segment starts "
            "with a recognisable program name (e.g. `grep ... | tail`)\n\n"
            "IF THIS WAS PROSE (e.g. a heredoc describing a pipe pattern): no "
            "action needed beyond retrying — the false trigger is now handled; "
            "for a permanent fix use the `Write` tool instead of a `cat <<EOF` "
            "heredoc for prose content\n\n"
            f"To disable: {_CONFIG_HINT_HANDLER}  (set enabled: false)"
        )

    def _blacklisted_reason(self, source_segment: str, command: str) -> str:
        """Return verbose block message for known-expensive commands (blacklisted)."""
        source_name = source_segment.split()[0] if source_segment else "command"
        return (
            f"🚫 BLOCKED: Pipe to tail/head detected\n\n"
            f"COMMAND: {self._truncate_command(command)}\n\n"
            f"WHY BLOCKED:\n"
            f"  • Piping {source_name} to tail/head causes information loss\n"
            f"  • If needed data isn't in those N truncated lines, the ENTIRE\n"
            f"    expensive command must be re-run\n"
            f"  • This wastes time and resources\n\n"
            f"{self._echd_capture_recommendation(source_segment)}\n"
            f"To disable: {_CONFIG_HINT_HANDLER}  (set enabled: false)"
        )

    def _blacklisted_terse_reason(self, source_segment: str, command: str) -> str:
        """Return terse block message for known-expensive commands (subsequent blocks)."""
        source_name = source_segment.split()[0] if source_segment else "command"
        return (
            f"BLOCKED: Pipe to tail/head — {source_name} is expensive\n\n"
            f"COMMAND: {self._truncate_command(command)}\n\n"
            f"{self._echd_capture_terse(source_segment)}\n"
            f"To disable: {_CONFIG_HINT_HANDLER}  (set enabled: false)"
        )

    def _unknown_reason(self, source_segment: str, command: str) -> str:
        """Return verbose block message for unrecognized commands (not in whitelist or blacklist)."""
        source_name = source_segment.split()[0] if source_segment else "command"
        return (
            f"🚫 BLOCKED: Pipe to tail/head detected\n\n"
            f"COMMAND: {self._truncate_command(command)}\n\n"
            f"WHY BLOCKED:\n"
            f"  • This command is unrecognized by the pipe blocker\n"
            f"  • If it is cheap/safe to pipe, add it to {_CONFIG_HINT_EXTRA_WHITELIST} in "
            f".claude/hooks-daemon.yaml:\n\n"
            f"    {_CONFIG_YAML_KEY}:\n"
            f"      {_CONFIG_HINT_EXTRA_WHITELIST}:\n"
            f'        - "^{source_name}\\\\b"\n\n'
            f"  • If it IS expensive, capture it with the helper below\n\n"
            f"{self._echd_capture_recommendation(source_segment)}\n"
            f"INFO: WHITELISTED COMMANDS (piping is OK):\n"
            f"  Commands that already filter output: grep, rg, awk, sed, jq, ls, cat, etc.\n\n"
            f"  Example: grep error /var/log/syslog | tail -n 20  (allowed)\n\n"
            f"To disable: {_CONFIG_HINT_HANDLER}  (set enabled: false)"
        )

    def _unknown_terse_reason(self, source_segment: str, command: str) -> str:
        """Return terse block message for unrecognized commands (subsequent blocks)."""
        source_name = source_segment.split()[0] if source_segment else "command"
        return (
            f"BLOCKED: Pipe to tail/head — {source_name} unrecognized\n\n"
            f"COMMAND: {self._truncate_command(command)}\n\n"
            f"Add to whitelist in .claude/hooks-daemon.yaml:\n"
            f"  {_CONFIG_YAML_KEY}:\n"
            f"    {_CONFIG_HINT_EXTRA_WHITELIST}:\n"
            f'      - "^{source_name}\\\\b"\n\n'
            f"{self._echd_capture_terse(source_segment)}\n"
            f"To disable: {_CONFIG_HINT_HANDLER}  (set enabled: false)"
        )

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Block with blacklisted or unknown message based on pattern match and block count."""
        command = get_bash_command(hook_input) or "unknown command"
        # Extract the segment from a message-blanked copy so a fake pipe
        # inside a -m/-F value earlier in the string can never be mistaken
        # for the real one that triggered the block. The displayed COMMAND
        # below still shows the full, un-redacted original.
        source_segment = self._extract_source_segment(self._strip_message_bodies(command))

        # Task 1.2: sanity-check BEFORE templating. Matched text that looks
        # like prose, not a shell command, gets a short accurate reason and
        # skips the extra_whitelist/echd-capture template entirely — that
        # template is what turned a defensible block into an embarrassing
        # one (Plan 00209 §1).
        if self._looks_like_prose(source_segment):
            return HookResult(decision=Decision.DENY, reason=self._prose_reason())

        block_count = self._get_block_count()

        # Differentiate: known expensive vs unrecognized, verbose vs terse
        if self._matches_blacklist(source_segment):
            if block_count == 0:
                reason = self._blacklisted_reason(source_segment, command)
            else:
                reason = self._blacklisted_terse_reason(source_segment, command)
        else:
            if block_count == 0:
                reason = self._unknown_reason(source_segment, command)
            else:
                reason = self._unknown_terse_reason(source_segment, command)

        return HookResult(decision=Decision.DENY, reason=reason)

    def get_claude_md(self) -> str | None:
        """Return CLAUDE.md guidance about the pipe blocker."""
        return (
            "### Pipe Blocker\n\n"
            "Commands piped to `tail` or `head` are **blocked** — piping truncates output "
            "and causes information loss.\n\n"
            "**Do NOT do the theatre** of capturing output to a file and then echoing the "
            "WHOLE file to stdout — that defeats the point and just bloats tokens.\n\n"
            "**Preferred — `echd-capture`**: capture the FULL output, see only a preview. "
            "When the block fires it prints the exact invocation to use — an ABSOLUTE path "
            "to the deployed helper, not a bare name — so copy the path from the block "
            "message (the helper is not guaranteed to be on `PATH`). If no helper path can "
            "be resolved, the block recommends the temp-file redirect below instead.\n\n"
            "```bash\n"
            "# WRONG — blocked (and truncates):\n"
            "pytest tests/ 2>&1 | tail -20\n\n"
            "# RIGHT — full capture, bounded preview + path to the rest. Use the ABSOLUTE\n"
            "# echd-capture path from the block message (shown here as /…/scripts/echd-capture):\n"
            "set -o pipefail\n"
            "pytest tests/ 2>&1 | /…/scripts/echd-capture 20\n"
            "# prints the last 20 lines + '(full output: /…/command-output-….txt)'.\n"
            "# Use --head N for the first N lines. pipefail keeps pytest's exit code visible.\n"
            "```\n\n"
            "**Always-works alternative** (no helper, no pipe): "
            "`pytest tests/ > /tmp/out.txt 2>&1` then read the file selectively.\n\n"
            "**Allowed** (whitelisted): `grep`, `rg`, `awk`, `sed`, `jq`, `ls`, `cat`, "
            "`git log`, `git tag`, `git branch`, and other cheap filtering commands.\n\n"
            "**Only PIPES are restricted — reading a file directly is not.** "
            "`tail -n 40 <file>`, `head -n 40 <file>` and `grep pattern <file>` take "
            "the path as an ARGUMENT, so no pipe exists and this handler never sees "
            "them. That is the supported way to sample a large append-only file such "
            "as a plan's `JOURNAL/` day-file — which you should tail or grep rather "
            "than read whole.\n\n"
            "**Add to whitelist** (if safe to pipe): set `extra_whitelist` in "
            "`.claude/hooks-daemon.yaml` under `pipe_blocker`.\n\n"
            "**A heredoc body describing a pipe pattern can false-trigger this "
            "handler** (the literal characters `| tail`/`| head` are matched even "
            "inside prose). When the matched text does not look like a real "
            "command — implausibly long, or starting with a common English word "
            'like "the" — the block reason is short and does NOT echo your text '
            "back or suggest a fabricated `extra_whitelist` entry. If this "
            "happens, just retry (nothing to fix); to avoid it entirely, write "
            "prose content with the `Write` tool instead of a `cat <<EOF` heredoc."
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for pipe blocker handler."""
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
        )

        # Safe no-op patterns for pipe blocker acceptance tests:
        #
        # Blacklisted commands (npm test, pytest): use "false && CMD | tail -N"
        #   - bash: | binds tighter than &&, so parsed as: false && (CMD | tail -N)
        #   - false exits 1 → && short-circuits → CMD never executes (safe if hook fails)
        #   - _extract_source_segment splits on && separator → source = "npm test" / "pytest"
        #   - source matches blacklist → DENY with "expensive" message ✓ (blacklist path exercised)
        #
        # Unknown commands (find): use [[ "CMD | tail -N" == 0 ]]
        #   - bash: evaluates false string comparison (exit 1), no side effects
        #   - source segment = '[[ "find ...' → not in blacklist → "unknown" path → extra_whitelist ✓
        #
        # Never use: echo (whitelisted), real direct commands (execute if hook fails)
        return [
            AcceptanceTest(
                title="npm test piped to tail (blacklisted — expensive path)",
                command="false && npm test | tail -5",
                description=(
                    "Blocks npm test | tail via blacklist path (expensive message). "
                    "'false &&' short-circuits so npm test never executes. "
                    "_extract_source_segment splits on && → source='npm test' → blacklist match."
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"Pipe to tail/head detected",
                    r"expensive",
                ],
                safety_notes=(
                    "Safe no-op: 'false' exits 1, && short-circuits, npm test never runs. "
                    "bash precedence: | > && so parsed as: false && (npm test | tail -5)"
                ),
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="pytest piped to head (blacklisted — expensive path)",
                command="false && pytest | head -20",
                description=(
                    "Blocks pytest | head via blacklist path (expensive message). "
                    "'false &&' short-circuits so pytest never executes."
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"Pipe to tail/head",
                    r"expensive",
                ],
                safety_notes=("Safe no-op: 'false' exits 1, && short-circuits, pytest never runs."),
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="docker ps piped to tail (unknown command — extra_whitelist path)",
                command='[[ "docker ps -a | tail -20" == 0 ]]',
                description=(
                    "Blocks docker ps | tail via unknown-command path (extra_whitelist hint). "
                    "docker ps is not in blacklist so handler suggests adding to extra_whitelist."
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"Pipe to tail/head",
                    r"extra_whitelist",
                ],
                safety_notes="No-op: [[ ... ]] evaluates to false (exit 1), no side effects",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="commit message quoting a pipe example is not a real pipe",
                command=(
                    'git commit -m "docs: pytest tests/ 2>&1 | tail -20 is now blocked" '
                    "--dry-run --allow-empty"
                ),
                description=(
                    "A commit message that quotes a '| tail' example as prose (e.g. "
                    "documenting this very handler) must NOT be treated as a real "
                    "pipe. Regression test for a dogfooding false positive "
                    "(Plan 00200) where -m message VALUES were scanned as shell "
                    "syntax instead of data. --dry-run never creates a commit."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="--dry-run --allow-empty: no commit is created, no side effects",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="heredoc prose describing a pipe pattern gets a short reason, no fabricated remediation",
                command=(
                    "false && cat >> /tmp/never-created-$$.md <<'EOF'\n"
                    "the guardrail described above blocks piping straight to a pager e.g. output | tail -20\n"
                    "EOF"
                ),
                description=(
                    "Plan 00209 §1: a heredoc body whose PROSE contains the literal "
                    "characters of a pipe-to-pager still gets blocked (detection is "
                    "unchanged — correct, cautious behaviour), but must NOT be run "
                    "through the extra_whitelist/echd-capture template (the field-report "
                    "defect: 'the' extracted as a binary name from a sentence) and must "
                    "NOT echo the prose back. 'false &&' short-circuits so the heredoc "
                    "write never executes even if the hook fails to block."
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"does not look like a real shell command",
                ],
                safety_notes=(
                    "Safe no-op: 'false' exits 1, && short-circuits, the heredoc write "
                    "never executes."
                ),
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
