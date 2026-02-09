"""PipeBlockerHandler - blocks expensive commands piped to tail/head."""

import re
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import Decision, Handler, HookResult, get_data_layer
from claude_code_hooks_daemon.core.utils import get_bash_command


class PipeBlockerHandler(Handler):
    """Block expensive commands piped to tail/head to prevent information loss.

    Blocks:
        Expensive operations piped to tail/head (e.g., npm test | tail -n 20)

    Allows:
        - Filtering commands piped to tail/head (grep, awk, jq - already filtered)
        - Direct file operations (tail -n 20 file.txt - no pipe)
        - tail -f (follow mode) and head -c (byte count)

    Rationale:
        When expensive commands are piped to tail/head, critical information may be lost.
        If the needed data isn't in those N truncated lines, the ENTIRE expensive command
        must be re-run. Redirecting to a temp file allows selective extraction without re-runs.
    """

    def __init__(self, options: dict[str, Any] | None = None) -> None:
        """Initialize handler with default or custom whitelist."""
        super().__init__(
            handler_id=HandlerID.PIPE_BLOCKER,
            priority=Priority.PIPE_BLOCKER,
            tags=[HandlerTag.SAFETY, HandlerTag.BASH, HandlerTag.BLOCKING, HandlerTag.TERMINAL],
        )

        # Default whitelist: commands that already filter/process output
        default_whitelist = [
            "grep",  # Text search
            "rg",  # Ripgrep
            "awk",  # Text processing
            "sed",  # Stream editor
            "jq",  # JSON processor
            "cut",  # Column extraction
            "sort",  # Sorting
            "uniq",  # Deduplication
            "tr",  # Character translation
            "wc",  # Word/line count
        ]

        # Allow user customization via options
        options = options or {}
        self._allowed_pipe_sources = options.get("allowed_pipe_sources", default_whitelist)

        # Compile regex patterns for efficient matching
        # Match: | tail or | head (case insensitive, flexible spacing)
        self._pipe_pattern = re.compile(r"\|\s*(tail|head)\b", re.IGNORECASE)
        # Match: tail -f or head -c (exceptions to allow)
        self._tail_follow_pattern = re.compile(r"\btail\s+-[a-z]*f", re.IGNORECASE)
        self._head_bytes_pattern = re.compile(r"\bhead\s+-[a-z]*c", re.IGNORECASE)

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Check if command pipes expensive operation to tail/head.

        Returns True if:
        - Bash tool with pipe to tail/head
        - NOT tail -f or head -c (these are allowed)
        - NOT a whitelisted filtering command before the pipe

        Returns False if:
        - Not a Bash tool
        - No pipe to tail/head
        - Direct file operation (no pipe)
        - tail -f or head -c
        - Whitelisted command before pipe
        """
        # Only check Bash commands
        command = get_bash_command(hook_input)
        if not command:
            return False

        # Check if command has pipe to tail/head
        if not self._pipe_pattern.search(command):
            return False

        # Allow tail -f (follow mode) and head -c (byte count)
        if self._tail_follow_pattern.search(command):
            return False
        if self._head_bytes_pattern.search(command):
            return False

        # Check if source command is whitelisted (filtering commands are safe)
        source_cmd = self._extract_source_command(command)
        # Block unless source command is whitelisted
        return not (
            source_cmd and source_cmd.lower() in [cmd.lower() for cmd in self._allowed_pipe_sources]
        )

    def _extract_source_command(self, command: str) -> str | None:
        """Extract the command immediately before pipe to tail/head.

        Examples:
            "find . | tail -n 20" -> "find"
            "grep error log | tail" -> "grep"
            "docker ps | grep running | tail" -> "grep"
            "npm test && grep FAIL | tail" -> "grep"

        Returns:
            Command name (first word of last segment before tail/head), or None if extraction fails.
        """
        try:
            # Find the position of | tail or | head
            match = self._pipe_pattern.search(command)
            if not match:
                return None

            # Get everything before the pipe to tail/head
            before_pipe = command[: match.start()]

            # Handle command chains (&&, ||, ;) - take the last segment
            for separator in ["&&", "||", ";"]:
                if separator in before_pipe:
                    before_pipe = before_pipe.rsplit(separator, 1)[-1]

            # Handle multiple pipes - take the last segment
            if "|" in before_pipe:
                before_pipe = before_pipe.rsplit("|", 1)[-1]

            # Extract first word (the command name)
            before_pipe = before_pipe.strip()
            if not before_pipe:
                return None

            # Get first word (command name)
            parts = before_pipe.split()
            if not parts:
                return None

            return parts[0]

        except Exception:
            # Fail-safe: if extraction fails, return None (will block by default)
            return None

    def _get_block_count(self) -> int:
        """Get number of previous blocks by this handler."""
        try:
            return get_data_layer().history.count_blocks_by_handler(self.name)
        except Exception:
            return 0

    def _terse_reason(self, source_cmd: str | None, command: str) -> str:
        """Return terse blocking message for first block."""
        source_name = source_cmd if source_cmd else "command"
        return (
            f"🚫 BLOCKED: Pipe to tail/head detected\n\n"
            f"Use temp file instead:\n"
            f"  {source_name} > /tmp/out.txt"
        )

    def _standard_reason(self, source_cmd: str | None, command: str) -> str:
        """Return standard blocking message (without whitelist section)."""
        source_name = source_cmd if source_cmd else "expensive operation"
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
            f"  {source_cmd or 'command'} > \"$TEMP_FILE\"\n\n"
            f"  # Extract what you need (can run multiple times)\n"
            f'  tail -n 20 "$TEMP_FILE"\n'
            f"  grep 'error' \"$TEMP_FILE\"\n"
            f"  # etc.\n"
        )

    def _verbose_reason(self, source_cmd: str | None, command: str) -> str:
        """Return verbose blocking message with whitelist section."""
        source_name = source_cmd if source_cmd else "expensive operation"
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
            f"  {source_cmd or 'command'} > \"$TEMP_FILE\"\n\n"
            f"  # Extract what you need (can run multiple times)\n"
            f'  tail -n 20 "$TEMP_FILE"\n'
            f"  grep 'error' \"$TEMP_FILE\"\n"
            f"  # etc.\n\n"
            f"INFO: WHITELISTED COMMANDS (piping is OK):\n"
            f"  Commands that already filter output: {', '.join(self._allowed_pipe_sources)}\n\n"
            f"  Example: grep error /var/log/syslog | tail -n 20  (allowed)\n"
        )

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Block the operation with progressive verbosity."""
        # Extract the blocked command
        command = get_bash_command(hook_input) or "unknown command"

        # Extract source command for context
        source_cmd = self._extract_source_command(command)

        # Get block count and select appropriate verbosity level
        block_count = self._get_block_count()

        if block_count == 0:
            # First block: terse message
            reason = self._terse_reason(source_cmd, command)
        elif block_count <= 2:
            # Blocks 1-2: standard message
            reason = self._standard_reason(source_cmd, command)
        else:
            # Blocks 3+: verbose message with whitelist
            reason = self._verbose_reason(source_cmd, command)

        return HookResult(decision=Decision.DENY, reason=reason)

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for pipe blocker handler."""
        from claude_code_hooks_daemon.core import AcceptanceTest, TestType

        return [
            AcceptanceTest(
                title="npm test piped to tail",
                command='echo "npm test | tail -5"',
                description="Blocks expensive commands piped to tail (information loss)",
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"Pipe to tail/head detected",
                    r"information loss",
                    r"Redirect to temp file",
                ],
                safety_notes="Uses echo - safe to test",
                test_type=TestType.BLOCKING,
            ),
            AcceptanceTest(
                title="pytest piped to head",
                command='echo "pytest | head -20"',
                description="Blocks pytest piped to head",
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"Pipe to tail/head",
                    r"expensive",
                ],
                safety_notes="Uses echo - safe to test",
                test_type=TestType.BLOCKING,
            ),
        ]
