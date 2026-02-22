"""Integration test for pipe blocker through full daemon pipeline.

Tests the three-tier decision system end-to-end through EventRouter:
- Tier 1 (whitelist):  grep, ls, cat → ALLOW
- Tier 2 (blacklist):  pytest, npm test, cargo test → DENY "expensive"
- Tier 3 (unknown):    find, docker ps → DENY "unrecognized, add to extra_whitelist"
"""

from claude_code_hooks_daemon.constants import HandlerID
from claude_code_hooks_daemon.core import EventRouter, EventType
from claude_code_hooks_daemon.handlers.pre_tool_use.pipe_blocker import PipeBlockerHandler


class TestPipeBlockerIntegration:
    """Integration test pipe blocker through EventRouter."""

    def test_blacklisted_command_blocks_through_router(self) -> None:
        """Test known-expensive command is denied with 'expensive' message through router."""
        router = EventRouter()
        handler = PipeBlockerHandler()
        router.register(EventType.PRE_TOOL_USE, handler)

        # pytest is a known-expensive blacklisted command
        hook_input = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {
                "command": "pytest tests/ | tail -20",
            },
            "session_id": "test-session",
            "transcript_path": "/tmp/test.jsonl",
            "cwd": "/workspace",
        }

        result = router.route(EventType.PRE_TOOL_USE, hook_input)

        # Should be denied with blacklisted "expensive" message
        assert result.result.decision == "deny", f"Expected deny, got {result.result.decision}"
        assert "pipe" in result.result.reason.lower(), "Reason should mention pipe"
        assert "expensive" in result.result.reason, "Blacklisted reason should mention expensive"
        assert len(result.handlers_matched) > 0, "Should have matched handlers"
        assert HandlerID.PIPE_BLOCKER.display_name in result.handlers_matched

    def test_docker_ps_pipe_tail_blocks_as_unknown_through_router(self) -> None:
        """Test docker ps | tail is blocked as unknown command through full pipeline."""
        router = EventRouter()
        handler = PipeBlockerHandler()
        router.register(EventType.PRE_TOOL_USE, handler)

        hook_input = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {
                "command": "docker ps -a | tail -10",
            },
            "session_id": "test-session",
        }

        result = router.route(EventType.PRE_TOOL_USE, hook_input)

        # Should be denied with "unknown" message mentioning extra_whitelist
        assert result.result.decision == "deny"
        assert (
            "extra_whitelist" in result.result.reason
        ), "Unknown reason should mention extra_whitelist"
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

    def test_ls_pipe_tail_allowed_through_router(self) -> None:
        """Test whitelisted ls | tail is allowed (ls is a cheap listing command)."""
        router = EventRouter()
        handler = PipeBlockerHandler()
        router.register(EventType.PRE_TOOL_USE, handler)

        hook_input = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {
                "command": "ls -1d CLAUDE/Plan/[0-9]* 2>/dev/null | tail -5",
            },
        }

        result = router.route(EventType.PRE_TOOL_USE, hook_input)

        # Should be allowed (ls is whitelisted)
        assert result.result.decision == "allow"

    def test_extra_whitelist_allows_custom_command(self) -> None:
        """Test that extra_whitelist config option allows custom commands through router."""
        router = EventRouter()
        # Configure extra_whitelist to allow 'my_custom_script'
        handler = PipeBlockerHandler(options={"extra_whitelist": [r"^my_custom_script\b"]})
        router.register(EventType.PRE_TOOL_USE, handler)

        hook_input = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {
                "command": "my_custom_script --args | tail -20",
            },
        }

        result = router.route(EventType.PRE_TOOL_USE, hook_input)

        # Should be allowed via extra_whitelist
        assert result.result.decision == "allow"
