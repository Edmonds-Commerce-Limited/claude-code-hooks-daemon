"""Tests to reproduce pipe blocker bug - THESE SHOULD FAIL."""

from claude_code_hooks_daemon.handlers.pre_tool_use.pipe_blocker import PipeBlockerHandler


class TestPipeBlockerBug:
    """Reproduce the bug where pipe blocker didn't block ls | tail."""

    def test_blocks_ls_pipe_tail(self) -> None:
        """Test that ls piped to tail is blocked (SHOULD PASS BUT DOESN'T)."""
        handler = PipeBlockerHandler()

        # This is the EXACT command that was NOT blocked
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {
                "command": "ls -1d CLAUDE/Plan/[0-9]* 2>/dev/null | tail -5",
            },
        }

        # Handler SHOULD match this
        assert handler.matches(hook_input), "Handler should match ls | tail command"

        # Handler SHOULD deny this
        result = handler.handle(hook_input)
        assert result.decision == "deny", "Handler should deny ls | tail"

    def test_blocks_find_pipe_tail(self) -> None:
        """Test that find piped to tail is blocked."""
        handler = PipeBlockerHandler()

        hook_input = {
            "tool_name": "Bash",
            "tool_input": {
                "command": 'find . -name "*.py" -type f | tail -10',
            },
        }

        # Handler SHOULD match this
        assert handler.matches(hook_input), "Handler should match find | tail command"

        # Handler SHOULD deny this
        result = handler.handle(hook_input)
        assert result.decision == "deny", "Handler should deny find | tail"

    def test_does_not_block_grep_pipe_tail(self) -> None:
        """Test that whitelisted commands (grep) are allowed through."""
        handler = PipeBlockerHandler()

        hook_input = {
            "tool_name": "Bash",
            "tool_input": {
                "command": 'grep "error" /var/log/syslog | tail -20',
            },
        }

        # Handler should NOT match grep (it's whitelisted)
        assert not handler.matches(hook_input), "Handler should not match grep | tail (whitelisted)"
