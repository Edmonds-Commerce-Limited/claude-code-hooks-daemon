"""PipeBlockerHandler - three-tier decision for commands piped to tail/head.

Three-tier logic:
  1. Matches whitelist?  → ALLOW (grep, awk, jq, ls, git tag, etc.)
  2. Matches blacklist?  → DENY: "expensive command, use temp file"
  3. Unknown?           → DENY: "unrecognized, add to extra_whitelist or use temp file"

Uses Strategy Pattern: all language-specific blacklist patterns are delegated to
PipeBlockerStrategy implementations registered in PipeBlockerStrategyRegistry.
The handler itself has ZERO language awareness.
"""

import re
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import Decision, Handler, HookResult
from claude_code_hooks_daemon.core.utils import get_bash_command
from claude_code_hooks_daemon.strategies.pipe_blocker.common import UNIVERSAL_WHITELIST_PATTERNS
from claude_code_hooks_daemon.strategies.pipe_blocker.registry import PipeBlockerStrategyRegistry

# Config key hints shown in unknown-command message
_CONFIG_HINT_EXTRA_WHITELIST = "extra_whitelist"
_CONFIG_HINT_HANDLER = "handlers.pre_tool_use.pipe_blocker"
_CONFIG_YAML_KEY = "pipe_blocker"


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

        if not self._pipe_pattern.search(command):
            return False

        # Allow tail -f (follow mode) and head -c (byte count)
        if self._tail_follow_pattern.search(command):
            return False
        if self._head_bytes_pattern.search(command):
            return False

        # Extract full source segment before pipe to tail/head
        source_segment = self._extract_source_segment(command)

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

        Returns empty string if extraction fails (treated as unknown command).
        """
        try:
            match = self._pipe_pattern.search(command)
            if not match:
                return ""

            # Get everything before the pipe to tail/head
            before_pipe = command[: match.start()]

            # Handle command chains (&&, ||, ;) — take the last segment
            for separator in ["&&", "||", ";"]:
                if separator in before_pipe:
                    before_pipe = before_pipe.rsplit(separator, 1)[-1]

            # Handle multiple pipes — take the last segment
            if "|" in before_pipe:
                before_pipe = before_pipe.rsplit("|", 1)[-1]

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
        for pattern in self._extra_whitelist:
            if pattern.search(source_segment):
                return True
        return False

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

    def _blacklisted_reason(self, source_segment: str, command: str) -> str:
        """Return block message for known-expensive commands (blacklisted)."""
        source_name = source_segment.split()[0] if source_segment else "command"
        return (
            f"🚫 BLOCKED: Pipe to tail/head detected\n\n"
            f"COMMAND: {command}\n\n"
            f"WHY BLOCKED:\n"
            f"  • Piping {source_name} to tail/head causes information loss\n"
            f"  • If needed data isn't in those N truncated lines, the ENTIRE\n"
            f"    expensive command must be re-run\n"
            f"  • This wastes time and resources\n\n"
            f"✅ RECOMMENDED ALTERNATIVE:\n"
            f"  Redirect to temp file for selective extraction:\n\n"
            f"  # Redirect full output to temp file\n"
            f'  TEMP_FILE="/tmp/output_$$.txt"\n'
            f"  {source_segment or 'command'} > \"$TEMP_FILE\"\n\n"
            f"  # Extract what you need (can run multiple times)\n"
            f'  tail -n 20 "$TEMP_FILE"\n'
            f"  grep 'error' \"$TEMP_FILE\"\n"
            f"  # etc.\n\n"
            f"To disable: {_CONFIG_HINT_HANDLER}  (set enabled: false)"
        )

    def _unknown_reason(self, source_segment: str, command: str) -> str:
        """Return block message for unrecognized commands (not in whitelist or blacklist)."""
        source_name = source_segment.split()[0] if source_segment else "command"
        return (
            f"🚫 BLOCKED: Pipe to tail/head detected\n\n"
            f"COMMAND: {command}\n\n"
            f"WHY BLOCKED:\n"
            f"  • This command is unrecognized by the pipe blocker\n"
            f"  • If it is cheap/safe to pipe, add it to {_CONFIG_HINT_EXTRA_WHITELIST} in "
            f".claude/hooks-daemon.yaml:\n\n"
            f"    {_CONFIG_YAML_KEY}:\n"
            f"      {_CONFIG_HINT_EXTRA_WHITELIST}:\n"
            f'        - "^{source_name}\\\\b"\n\n'
            f"  • If it IS expensive, use a temp file instead\n\n"
            f"✅ RECOMMENDED ALTERNATIVE:\n"
            f"  Redirect to temp file for selective extraction:\n\n"
            f"  # Redirect full output to temp file\n"
            f'  TEMP_FILE="/tmp/output_$$.txt"\n'
            f"  {source_segment or 'command'} > \"$TEMP_FILE\"\n\n"
            f"  # Extract what you need (can run multiple times)\n"
            f'  tail -n 20 "$TEMP_FILE"\n'
            f"  grep 'error' \"$TEMP_FILE\"\n"
            f"  # etc.\n\n"
            f"INFO: WHITELISTED COMMANDS (piping is OK):\n"
            f"  Commands that already filter output: grep, rg, awk, sed, jq, ls, cat, etc.\n\n"
            f"  Example: grep error /var/log/syslog | tail -n 20  (allowed)\n\n"
            f"To disable: {_CONFIG_HINT_HANDLER}  (set enabled: false)"
        )

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Block with blacklisted or unknown message based on pattern match."""
        command = get_bash_command(hook_input) or "unknown command"
        source_segment = self._extract_source_segment(command)

        # Differentiate: known expensive vs unrecognized
        if self._matches_blacklist(source_segment):
            reason = self._blacklisted_reason(source_segment, command)
        else:
            reason = self._unknown_reason(source_segment, command)

        return HookResult(decision=Decision.DENY, reason=reason)

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
                title="find piped to tail (unknown command — extra_whitelist path)",
                command='[[ "find /tmp -name test.py | tail -20" == 0 ]]',
                description=(
                    "Blocks find | tail via unknown-command path (extra_whitelist hint). "
                    "find is not in blacklist so handler suggests adding to extra_whitelist."
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
        ]
