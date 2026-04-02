"""Regression tests for pipe blocker behavior under three-tier decision system.

These tests document the CORRECT behavior after the strategy-pattern redesign:
- Tier 1 (whitelist):  ls, grep, cat, find, ps, df, etc. → ALLOW (matches() returns False)
- Tier 2 (blacklist):  pytest, npm test, etc. → DENY "expensive command"
- Tier 3 (unknown):    docker ps, etc. → DENY "unrecognized, add to extra_whitelist"
"""

from claude_code_hooks_daemon.handlers.pre_tool_use.pipe_blocker import PipeBlockerHandler


class TestPipeBlockerRegressionBehavior:
    """Regression tests covering whitelist, blacklist, and unknown command paths."""

    def test_does_not_block_ls_pipe_tail(self) -> None:
        """Test that ls piped to tail is ALLOWED (ls is whitelisted output command).

        This is intentional: ls is a cheap listing command and should be allowed
        to pipe to tail/head for output truncation.
        """
        handler = PipeBlockerHandler()

        # This is the EXACT command that triggered the original bug report
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {
                "command": "ls -1d CLAUDE/Plan/[0-9]* 2>/dev/null | tail -5",
            },
        }

        # ls is whitelisted — handler should NOT match (not blocked)
        assert not handler.matches(
            hook_input
        ), "Handler should NOT match ls | tail (ls is whitelisted)"

    def test_does_not_block_find_pipe_tail(self) -> None:
        """Test that find piped to tail is ALLOWED (find is whitelisted).

        find was moved to Tier 1 (whitelist) — it is a cheap filesystem listing
        command and safe to pipe to tail/head for output truncation.
        """
        handler = PipeBlockerHandler()

        hook_input = {
            "tool_name": "Bash",
            "tool_input": {
                "command": 'find . -name "*.py" -type f | tail -10',
            },
        }

        # find is whitelisted — handler should NOT match (not blocked)
        assert not handler.matches(
            hook_input
        ), "Handler should NOT match find | tail (find is whitelisted)"

    def test_does_not_block_grep_pipe_tail(self) -> None:
        """Test that whitelisted commands (grep) are allowed through."""
        handler = PipeBlockerHandler()

        hook_input = {
            "tool_name": "Bash",
            "tool_input": {
                "command": 'grep "error" /var/log/syslog | tail -20',
            },
        }

        # grep is whitelisted — handler should NOT match
        assert not handler.matches(hook_input), "Handler should not match grep | tail (whitelisted)"

    def test_does_not_block_grep_with_pipe_in_pattern_piped_to_head(self) -> None:
        """Regression test: grep with | in pattern (e.g. grep -E "15:56|15:57") must not be blocked.

        Bug: _extract_source_segment used re.split(r"(?<!\\)\\|", ...) which splits on ALL
        unescaped | characters, including | inside quoted grep patterns like "15:56|15:57".
        This caused source_segment to become "15:57\"" instead of "grep -E ...",
        failing the whitelist check and incorrectly blocking the command.

        The fix: quote-aware pipe splitting must not split on | inside double/single quotes.
        """
        handler = PipeBlockerHandler()

        # Exact pattern that triggered the dogfooding bug:
        # python -m ... logs 2>/dev/null | grep -E "15:56|15:57" | head -30
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {
                "command": (
                    "/workspace/untracked/venv/bin/python -m claude_code_hooks_daemon.daemon.cli "
                    'logs 2>/dev/null | grep -E "15:56|15:57" | head -30'
                ),
            },
        }

        # grep is whitelisted — must NOT be blocked despite | inside the quoted pattern
        assert not handler.matches(
            hook_input
        ), "Handler should NOT match grep | head when grep pattern contains | (whitelisted)"

    def test_extract_source_segment_handles_quoted_pipe_in_grep_pattern(self) -> None:
        """Unit test: _extract_source_segment returns grep command, not fragment of its pattern.

        With "cmd | grep -E 'a|b' | head -10", the source segment should be
        "grep -E 'a|b'", not "b'" (which is what naive re.split produced).
        """
        handler = PipeBlockerHandler()

        # Double-quoted pattern
        segment = handler._extract_source_segment('python logs | grep -E "15:56|15:57" | head -30')
        assert segment.startswith(
            "grep"
        ), f"Source segment should start with 'grep', got: {segment!r}"

        # Single-quoted pattern
        segment2 = handler._extract_source_segment("cat file | grep -E '15:56|15:57' | tail -20")
        assert segment2.startswith(
            "grep"
        ), f"Source segment should start with 'grep', got: {segment2!r}"

    def test_blocks_pytest_pipe_tail_as_blacklisted(self) -> None:
        """Test that pytest piped to tail is blocked as a known expensive command."""
        handler = PipeBlockerHandler()

        hook_input = {
            "tool_name": "Bash",
            "tool_input": {
                "command": "pytest tests/ | tail -20",
            },
        }

        # pytest is blacklisted — should block with "expensive" message
        assert handler.matches(hook_input), "Handler should match pytest | tail (blacklisted)"

        result = handler.handle(hook_input)
        assert result.decision == "deny", "Handler should deny pytest | tail"
        assert "expensive" in result.reason, "Blacklisted reason should mention expensive"
