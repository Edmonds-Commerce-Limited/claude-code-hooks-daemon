"""Regression tests for pipe blocker behavior under three-tier decision system.

These tests document the CORRECT behavior after the strategy-pattern redesign:
- Tier 1 (whitelist):  ls, grep, cat, etc. → ALLOW (matches() returns False)
- Tier 2 (blacklist):  pytest, npm test, etc. → DENY "expensive command"
- Tier 3 (unknown):    find, docker ps, etc. → DENY "unrecognized, add to extra_whitelist"
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

    def test_blocks_find_pipe_tail(self) -> None:
        """Test that find piped to tail is blocked as an unknown command."""
        handler = PipeBlockerHandler()

        hook_input = {
            "tool_name": "Bash",
            "tool_input": {
                "command": 'find . -name "*.py" -type f | tail -10',
            },
        }

        # find is unknown (not whitelisted, not blacklisted) — should block
        assert handler.matches(hook_input), "Handler should match find | tail (unknown command)"

        # Handler SHOULD deny with "unrecognized" message (tier 3: unknown path)
        result = handler.handle(hook_input)
        assert result.decision == "deny", "Handler should deny find | tail"
        assert (
            "extra_whitelist" in result.reason
        ), "Unknown command reason should mention extra_whitelist"

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
