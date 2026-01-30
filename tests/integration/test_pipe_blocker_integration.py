"""Integration test for pipe blocker through full daemon pipeline."""

from claude_code_hooks_daemon.constants import HandlerID
from claude_code_hooks_daemon.core import EventRouter, EventType
from claude_code_hooks_daemon.handlers.pre_tool_use.pipe_blocker import PipeBlockerHandler


class TestPipeBlockerIntegration:
    """Integration test pipe blocker through EventRouter."""

    def test_pipe_blocker_blocks_through_router(self) -> None:
        """Test pipe blocker works when routed through EventRouter."""
        # Setup router and register handler
        router = EventRouter()
        handler = PipeBlockerHandler()
        router.register(EventType.PRE_TOOL_USE, handler)

        # Simulate the EXACT hook_input that Claude Code would send
        hook_input = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {
                "command": "ls -1d CLAUDE/Plan/[0-9]* 2>/dev/null | tail -5",
            },
            "session_id": "test-session",
            "transcript_path": "/tmp/test.jsonl",
            "cwd": "/workspace",
        }

        # Route through the full pipeline
        result = router.route(EventType.PRE_TOOL_USE, hook_input)

        # Should be denied by pipe blocker
        assert result.result.decision == "deny", f"Expected deny, got {result.result.decision}"
        assert "pipe" in result.result.reason.lower(), "Reason should mention pipe"
        assert len(result.handlers_matched) > 0, "Should have matched handlers"
        assert HandlerID.PIPE_BLOCKER.display_name in result.handlers_matched

    def test_find_pipe_tail_blocks_through_router(self) -> None:
        """Test find | tail is blocked through full pipeline."""
        router = EventRouter()
        handler = PipeBlockerHandler()
        router.register(EventType.PRE_TOOL_USE, handler)

        hook_input = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {
                "command": 'find . -name "*.py" | tail -10',
            },
            "session_id": "test-session",
        }

        result = router.route(EventType.PRE_TOOL_USE, hook_input)

        # Should be denied
        assert result.result.decision == "deny"
        assert (
            result.terminated_by == HandlerID.PIPE_BLOCKER.display_name
        ), "Terminal handler should terminate chain"

    def test_grep_pipe_tail_allowed_through_router(self) -> None:
        """Test whitelisted grep | tail is allowed."""
        router = EventRouter()
        handler = PipeBlockerHandler()
        router.register(EventType.PRE_TOOL_USE, handler)

        hook_input = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {
                "command": 'grep "error" file.txt | tail -20',
            },
        }

        result = router.route(EventType.PRE_TOOL_USE, hook_input)

        # Should be allowed (grep is whitelisted)
        assert result.result.decision == "allow"
