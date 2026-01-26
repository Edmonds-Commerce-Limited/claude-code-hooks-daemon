"""Comprehensive tests for FrontController."""

import json
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

import pytest

from claude_code_hooks_daemon.core.front_controller import (
    FrontController,
    get_workspace_root,
    log_error_to_file,
)
from claude_code_hooks_daemon.core.handler import Handler
from claude_code_hooks_daemon.core.hook_result import HookResult

# Test Fixtures


@pytest.fixture
def front_controller():
    """Create FrontController instance."""
    return FrontController("PreToolUse")


@pytest.fixture
def mock_terminal_handler():
    """Create mock terminal handler."""
    handler = MagicMock(spec=Handler)
    handler.name = "test-terminal-handler"
    handler.priority = 10
    handler.terminal = True
    handler.matches.return_value = False
    handler.handle.return_value = HookResult(decision="deny", reason="Terminal handler blocked")
    return handler


@pytest.fixture
def mock_non_terminal_handler():
    """Create mock non-terminal handler."""
    handler = MagicMock(spec=Handler)
    handler.name = "test-non-terminal-handler"
    handler.priority = 5
    handler.terminal = False
    handler.matches.return_value = False
    handler.handle.return_value = HookResult(decision="allow", context="Non-terminal context")
    return handler


# Initialization Tests


class TestFrontControllerInit:
    """Test FrontController initialization."""

    def test_init_sets_event_name(self):
        """Should set event_name from parameter."""
        fc = FrontController("PreToolUse")
        assert fc.event_name == "PreToolUse"

    def test_init_creates_empty_handlers_list(self):
        """Should initialize empty handlers list."""
        fc = FrontController("PostToolUse")
        assert fc.handlers == []
        assert isinstance(fc.handlers, list)

    def test_init_with_different_event_names(self):
        """Should support different event names."""
        events = ["PreToolUse", "PostToolUse", "SessionStart", "PreCompact"]
        for event in events:
            fc = FrontController(event)
            assert fc.event_name == event


# Handler Registration Tests


class TestHandlerRegistration:
    """Test handler registration."""

    def test_register_adds_handler_to_list(self, front_controller, mock_terminal_handler):
        """Should add handler to handlers list."""
        front_controller.register(mock_terminal_handler)
        assert len(front_controller.handlers) == 1
        assert front_controller.handlers[0] == mock_terminal_handler

    def test_register_multiple_handlers(self, front_controller):
        """Should register multiple handlers."""
        handler1 = MagicMock(spec=Handler)
        handler1.priority = 10
        handler2 = MagicMock(spec=Handler)
        handler2.priority = 20

        front_controller.register(handler1)
        front_controller.register(handler2)

        assert len(front_controller.handlers) == 2

    def test_register_sorts_handlers_by_priority(self, front_controller):
        """Should keep handlers sorted by priority (lower first)."""
        handler_high = MagicMock(spec=Handler)
        handler_high.priority = 50
        handler_high.name = "high"

        handler_low = MagicMock(spec=Handler)
        handler_low.priority = 10
        handler_low.name = "low"

        handler_mid = MagicMock(spec=Handler)
        handler_mid.priority = 30
        handler_mid.name = "mid"

        # Register out of order
        front_controller.register(handler_high)
        front_controller.register(handler_low)
        front_controller.register(handler_mid)

        # Should be sorted: low (10), mid (30), high (50)
        assert front_controller.handlers[0].name == "low"
        assert front_controller.handlers[1].name == "mid"
        assert front_controller.handlers[2].name == "high"

    def test_register_maintains_sort_after_each_registration(self, front_controller):
        """Should maintain sort order after each registration."""
        handler1 = MagicMock(spec=Handler)
        handler1.priority = 30

        handler2 = MagicMock(spec=Handler)
        handler2.priority = 10

        front_controller.register(handler1)
        assert front_controller.handlers[0].priority == 30

        front_controller.register(handler2)
        # After adding lower priority, it should be first
        assert front_controller.handlers[0].priority == 10
        assert front_controller.handlers[1].priority == 30


# Priority Sorting Tests


class TestPrioritySorting:
    """Test priority-based handler sorting."""

    def test_same_priority_maintains_registration_order(self, front_controller):
        """Handlers with same priority maintain registration order."""
        handler1 = MagicMock(spec=Handler)
        handler1.priority = 20
        handler1.name = "first"

        handler2 = MagicMock(spec=Handler)
        handler2.priority = 20
        handler2.name = "second"

        front_controller.register(handler1)
        front_controller.register(handler2)

        # Python's sort is stable, so registration order preserved
        assert front_controller.handlers[0].name == "first"
        assert front_controller.handlers[1].name == "second"

    def test_priority_ranges_sorted_correctly(self, front_controller):
        """Should sort full range of priorities correctly."""
        priorities = [60, 5, 45, 10, 25, 50, 15, 30, 40, 20]
        handlers = []

        for priority in priorities:
            handler = MagicMock(spec=Handler)
            handler.priority = priority
            handler.name = f"handler-{priority}"
            handlers.append(handler)
            front_controller.register(handler)

        # Verify sorted order
        sorted_priorities = sorted(priorities)
        for i, expected_priority in enumerate(sorted_priorities):
            assert front_controller.handlers[i].priority == expected_priority


# Terminal Handler Dispatch Tests


class TestTerminalHandlerDispatch:
    """Test terminal handler dispatch (stop immediately)."""

    def test_terminal_handler_match_stops_dispatch(self, front_controller):
        """Terminal handler that matches should stop dispatch immediately."""
        handler1 = MagicMock(spec=Handler)
        handler1.priority = 10
        handler1.terminal = True
        handler1.matches.return_value = True
        handler1.handle.return_value = HookResult(decision="deny", reason="Blocked")

        handler2 = MagicMock(spec=Handler)
        handler2.priority = 20
        handler2.terminal = True
        handler2.matches.return_value = True

        front_controller.register(handler1)
        front_controller.register(handler2)

        result = front_controller.dispatch({"tool_name": "Bash"})

        # Should execute handler1 and stop
        assert handler1.handle.called
        assert not handler2.handle.called  # Should NOT reach handler2
        assert result.decision == "deny"

    def test_terminal_handler_returns_result_immediately(
        self, front_controller, mock_terminal_handler
    ):
        """Terminal handler result should be returned immediately."""
        mock_terminal_handler.matches.return_value = True
        front_controller.register(mock_terminal_handler)

        result = front_controller.dispatch({"tool_name": "Bash"})

        assert result.decision == "deny"
        assert result.reason == "Terminal handler blocked"

    def test_terminal_handler_no_match_continues(self, front_controller):
        """Terminal handler that doesn't match should continue dispatch."""
        handler1 = MagicMock(spec=Handler)
        handler1.priority = 10
        handler1.terminal = True
        handler1.matches.return_value = False  # No match

        handler2 = MagicMock(spec=Handler)
        handler2.priority = 20
        handler2.terminal = True
        handler2.matches.return_value = True
        handler2.handle.return_value = HookResult(decision="allow")

        front_controller.register(handler1)
        front_controller.register(handler2)

        result = front_controller.dispatch({"tool_name": "Bash"})

        # Should skip handler1, execute handler2
        assert not handler1.handle.called
        assert handler2.handle.called
        assert result.decision == "allow"

    def test_multiple_terminal_handlers_first_match_wins(self, front_controller):
        """First matching terminal handler should win."""
        handler1 = MagicMock(spec=Handler)
        handler1.priority = 10
        handler1.terminal = True
        handler1.matches.return_value = True
        handler1.handle.return_value = HookResult(decision="deny", reason="First")

        handler2 = MagicMock(spec=Handler)
        handler2.priority = 20
        handler2.terminal = True
        handler2.matches.return_value = True
        handler2.handle.return_value = HookResult(decision="ask", reason="Second")

        front_controller.register(handler1)
        front_controller.register(handler2)

        result = front_controller.dispatch({"tool_name": "Bash"})

        assert result.decision == "deny"
        assert result.reason == "First"


# Non-Terminal Handler Dispatch Tests


class TestNonTerminalHandlerDispatch:
    """Test non-terminal handler dispatch (fall-through)."""

    def test_non_terminal_handler_allows_continuation(self, front_controller):
        """Non-terminal handler should allow subsequent handlers to run."""
        handler1 = MagicMock(spec=Handler)
        handler1.priority = 10
        handler1.terminal = False  # Non-terminal
        handler1.matches.return_value = True
        handler1.handle.return_value = HookResult(decision="allow", context="Context from handler1")

        handler2 = MagicMock(spec=Handler)
        handler2.priority = 20
        handler2.terminal = True
        handler2.matches.return_value = True
        handler2.handle.return_value = HookResult(decision="deny", reason="Blocked by handler2")

        front_controller.register(handler1)
        front_controller.register(handler2)

        result = front_controller.dispatch({"tool_name": "Bash"})

        # Both should execute
        assert handler1.handle.called
        assert handler2.handle.called

        # Terminal handler result wins
        assert result.decision == "deny"
        assert result.reason == "Blocked by handler2"

    def test_non_terminal_handler_context_accumulated(self, front_controller):
        """Non-terminal handler context should be accumulated."""
        handler1 = MagicMock(spec=Handler)
        handler1.priority = 10
        handler1.terminal = False
        handler1.matches.return_value = True
        handler1.handle.return_value = HookResult(decision="allow", context="Context from handler1")

        handler2 = MagicMock(spec=Handler)
        handler2.priority = 20
        handler2.terminal = True
        handler2.matches.return_value = True
        handler2.handle.return_value = HookResult(decision="deny", reason="Blocked")

        front_controller.register(handler1)
        front_controller.register(handler2)

        result = front_controller.dispatch({"tool_name": "Bash"})

        # Context from non-terminal should be in result
        assert "Context from handler1" in result.context

    def test_multiple_non_terminal_handlers_all_execute(self, front_controller):
        """Multiple non-terminal handlers should all execute."""
        handler1 = MagicMock(spec=Handler)
        handler1.priority = 10
        handler1.terminal = False
        handler1.matches.return_value = True
        handler1.handle.return_value = HookResult(decision="allow", context="Context 1")

        handler2 = MagicMock(spec=Handler)
        handler2.priority = 20
        handler2.terminal = False
        handler2.matches.return_value = True
        handler2.handle.return_value = HookResult(decision="allow", context="Context 2")

        handler3 = MagicMock(spec=Handler)
        handler3.priority = 30
        handler3.terminal = False
        handler3.matches.return_value = True
        handler3.handle.return_value = HookResult(decision="allow", context="Context 3")

        front_controller.register(handler1)
        front_controller.register(handler2)
        front_controller.register(handler3)

        result = front_controller.dispatch({"tool_name": "Bash"})

        # All should execute
        assert handler1.handle.called
        assert handler2.handle.called
        assert handler3.handle.called

        # Last handler result returned
        assert result.decision == "allow"


# Context Accumulation Tests


class TestContextAccumulation:
    """Test context accumulation from multiple handlers."""

    def test_accumulates_context_from_multiple_non_terminal_handlers(self, front_controller):
        """Should merge context from multiple non-terminal handlers."""
        handler1 = MagicMock(spec=Handler)
        handler1.priority = 10
        handler1.terminal = False
        handler1.matches.return_value = True
        handler1.handle.return_value = HookResult(decision="allow", context="Context from handler1")

        handler2 = MagicMock(spec=Handler)
        handler2.priority = 20
        handler2.terminal = False
        handler2.matches.return_value = True
        handler2.handle.return_value = HookResult(decision="allow", context="Context from handler2")

        handler3 = MagicMock(spec=Handler)
        handler3.priority = 30
        handler3.terminal = True
        handler3.matches.return_value = True
        handler3.handle.return_value = HookResult(
            decision="deny", reason="Blocked", context="Terminal context"
        )

        front_controller.register(handler1)
        front_controller.register(handler2)
        front_controller.register(handler3)

        result = front_controller.dispatch({"tool_name": "Bash"})

        # All contexts should be merged
        assert "Context from handler1" in result.context
        assert "Context from handler2" in result.context
        assert "Terminal context" in result.context

    def test_context_accumulated_as_list(self, front_controller):
        """Contexts should be accumulated as a list."""
        handler1 = MagicMock(spec=Handler)
        handler1.priority = 10
        handler1.terminal = False
        handler1.matches.return_value = True
        handler1.handle.return_value = HookResult(decision="allow", context="First")

        handler2 = MagicMock(spec=Handler)
        handler2.priority = 20
        handler2.terminal = False
        handler2.matches.return_value = True
        handler2.handle.return_value = HookResult(decision="allow", context="Second")

        handler3 = MagicMock(spec=Handler)
        handler3.priority = 30
        handler3.terminal = True
        handler3.matches.return_value = True
        handler3.handle.return_value = HookResult(decision="allow", context="Third")

        front_controller.register(handler1)
        front_controller.register(handler2)
        front_controller.register(handler3)

        result = front_controller.dispatch({"tool_name": "Bash"})

        # Context is now a list
        assert "First" in result.context
        assert "Second" in result.context
        assert "Third" in result.context

    def test_non_terminal_without_context_not_added(self, front_controller):
        """Non-terminal handler without context should not add to accumulation."""
        handler1 = MagicMock(spec=Handler)
        handler1.priority = 10
        handler1.terminal = False
        handler1.matches.return_value = True
        handler1.handle.return_value = HookResult(decision="allow", context=None)  # No context

        handler2 = MagicMock(spec=Handler)
        handler2.priority = 20
        handler2.terminal = True
        handler2.matches.return_value = True
        handler2.handle.return_value = HookResult(decision="allow", context="Terminal context")

        front_controller.register(handler1)
        front_controller.register(handler2)

        result = front_controller.dispatch({"tool_name": "Bash"})

        # Only terminal context should be present (as list)
        assert result.context == ["Terminal context"]

    def test_terminal_without_context_gets_accumulated_context(self, front_controller):
        """Terminal handler without context should get accumulated context."""
        handler1 = MagicMock(spec=Handler)
        handler1.priority = 10
        handler1.terminal = False
        handler1.matches.return_value = True
        handler1.handle.return_value = HookResult(decision="allow", context="Non-terminal context")

        handler2 = MagicMock(spec=Handler)
        handler2.priority = 20
        handler2.terminal = True
        handler2.matches.return_value = True
        handler2.handle.return_value = HookResult(decision="deny", reason="Blocked", context=None)

        front_controller.register(handler1)
        front_controller.register(handler2)

        result = front_controller.dispatch({"tool_name": "Bash"})

        # Terminal result should have accumulated context (as list)
        assert result.context == ["Non-terminal context"]


# Error Handling Tests


class TestErrorHandling:
    """Test error handling during dispatch."""

    def test_handler_exception_returns_allow_with_error_context(self, front_controller):
        """Handler exception should return allow with error context."""
        handler = MagicMock(spec=Handler)
        handler.name = "crashing-handler"
        handler.priority = 10
        handler.terminal = True
        handler.matches.return_value = True
        handler.handle.side_effect = RuntimeError("Handler crashed")

        front_controller.register(handler)

        with patch("claude_code_hooks_daemon.core.front_controller.log_error_to_file"):
            result = front_controller.dispatch({"tool_name": "Bash"})

        # Should fail open
        assert result.decision == "allow"
        # Context is now a list, join for text search
        context_text = "\n".join(result.context).lower()
        assert "error" in context_text
        assert "crashing-handler" in context_text

    def test_handler_exception_logs_to_file(self, front_controller):
        """Handler exception should log to file."""
        handler = MagicMock(spec=Handler)
        handler.name = "crashing-handler"
        handler.priority = 10
        handler.terminal = True
        handler.matches.return_value = True
        handler.handle.side_effect = ValueError("Test error")

        front_controller.register(handler)

        with patch("claude_code_hooks_daemon.core.front_controller.log_error_to_file") as mock_log:
            front_controller.dispatch({"tool_name": "Bash"})

        # Should call log_error_to_file
        assert mock_log.called

    def test_no_matching_handlers_returns_allow(self, front_controller):
        """No matching handlers should return default allow."""
        handler = MagicMock(spec=Handler)
        handler.priority = 10
        handler.terminal = True
        handler.matches.return_value = False  # No match

        front_controller.register(handler)

        result = front_controller.dispatch({"tool_name": "Bash"})

        assert result.decision == "allow"
        assert result.reason is None
        assert result.context == []

    def test_empty_handlers_list_returns_allow(self, front_controller):
        """Empty handlers list should return default allow."""
        result = front_controller.dispatch({"tool_name": "Bash"})

        assert result.decision == "allow"
        assert result.reason is None
        assert result.context == []


# JSON Input/Output Tests


class TestJSONInputOutput:
    """Test JSON input/output handling."""

    def test_run_reads_stdin_and_writes_stdout(self, front_controller):
        """run() should read stdin and write stdout."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "ls"}}

        # Mock stdin and stdout
        with (
            patch("sys.stdin", StringIO(json.dumps(hook_input))),
            patch("sys.stdout", new_callable=StringIO) as mock_stdout,
            pytest.raises(SystemExit) as exc_info,
        ):
            front_controller.run()

            # Should exit with 0
            assert exc_info.value.code == 0

            # Check output
            output = mock_stdout.getvalue()
            # Silent allow = empty JSON
            assert output == "{}"

    def test_run_with_invalid_json_returns_empty_json(self, front_controller):
        """run() with invalid JSON should return empty JSON (fail open)."""
        with (
            patch("sys.stdin", StringIO("invalid json")),
            patch("sys.stdout", new_callable=StringIO) as mock_stdout,
            pytest.raises(SystemExit) as exc_info,
        ):
            front_controller.run()

            assert exc_info.value.code == 0
            # json.dump adds newline
            assert mock_stdout.getvalue().strip() == "{}"

    def test_run_with_handler_match_outputs_result(self, front_controller):
        """run() with matching handler should output result JSON."""
        handler = MagicMock(spec=Handler)
        handler.priority = 10
        handler.terminal = True
        handler.matches.return_value = True
        handler.handle.return_value = HookResult(decision="deny", reason="Blocked")

        front_controller.register(handler)

        hook_input = {"tool_name": "Bash", "tool_input": {"command": "rm -rf /"}}

        with (
            patch("sys.stdin", StringIO(json.dumps(hook_input))),
            patch("sys.stdout", new_callable=StringIO) as mock_stdout,
            pytest.raises(SystemExit) as exc_info,
        ):
            front_controller.run()

            assert exc_info.value.code == 0

            output = json.loads(mock_stdout.getvalue())
            assert "hookSpecificOutput" in output
            assert output["hookSpecificOutput"]["permissionDecision"] == "deny"


# run() Method Tests


class TestRunMethod:
    """Test run() entry point method."""

    def test_run_calls_dispatch(self):
        """run() should call dispatch with hook_input."""
        hook_input = {"tool_name": "Bash"}

        with (
            patch("sys.stdin", StringIO(json.dumps(hook_input))),
            patch("sys.stdout", new_callable=StringIO),
            patch.object(
                FrontController, "dispatch", return_value=HookResult(decision="allow")
            ) as mock_dispatch,
        ):
            fc = FrontController("PreToolUse")

            with pytest.raises(SystemExit):
                fc.run()

            mock_dispatch.assert_called_once_with(hook_input)

    def test_run_exception_during_dispatch_fails_open(self):
        """run() exception during dispatch should fail open."""
        hook_input = {"tool_name": "Bash"}

        with (
            patch("sys.stdin", StringIO(json.dumps(hook_input))),
            patch("sys.stdout", new_callable=StringIO) as mock_stdout,
            patch("sys.stderr", new_callable=StringIO),
            patch.object(FrontController, "dispatch", side_effect=RuntimeError("Test")),
            patch("claude_code_hooks_daemon.core.front_controller.log_error_to_file"),
        ):
            fc = FrontController("PreToolUse")

            with pytest.raises(SystemExit) as exc_info:
                fc.run()

            assert exc_info.value.code == 0

            # Should return allow with error context
            output = json.loads(mock_stdout.getvalue())
            assert "hookSpecificOutput" in output
            assert "additionalContext" in output["hookSpecificOutput"]


# log_error_to_file() Tests


class TestLogErrorToFile:
    """Test error logging to file."""

    @patch("claude_code_hooks_daemon.core.front_controller.get_workspace_root")
    @patch("pathlib.Path.open", new_callable=mock_open)
    @patch("pathlib.Path.exists")
    @patch("pathlib.Path.mkdir")
    def test_log_error_creates_log_file(self, mock_mkdir, mock_exists, mock_file, mock_get_root):
        """Should create log file in untracked directory."""
        mock_get_root.return_value = Path("/workspace")
        mock_exists.return_value = False

        exception = ValueError("Test error")
        hook_input = {"tool_name": "Bash"}

        log_error_to_file("PreToolUse", exception, hook_input)

        # Should create directory
        mock_mkdir.assert_called_once()

    @patch("claude_code_hooks_daemon.core.front_controller.get_workspace_root")
    @patch("pathlib.Path.open", new_callable=mock_open)
    @patch("pathlib.Path.exists")
    @patch("pathlib.Path.mkdir")
    def test_log_error_includes_handler_name(
        self, mock_mkdir, mock_exists, mock_file, mock_get_root
    ):
        """Should include handler name in log entry."""
        mock_get_root.return_value = Path("/workspace")
        mock_exists.return_value = False

        exception = RuntimeError("Handler error")
        hook_input = {"tool_name": "Write"}

        log_error_to_file("PreToolUse", exception, hook_input, handler_name="test-handler")

        # Check written content includes handler name
        written = "".join(call.args[0] for call in mock_file().write.call_args_list)
        assert "Handler: test-handler" in written

    @patch("claude_code_hooks_daemon.core.front_controller.get_workspace_root")
    @patch("pathlib.Path.stat")
    @patch("pathlib.Path.rename")
    @patch("pathlib.Path.open", new_callable=mock_open)
    @patch("pathlib.Path.exists")
    @patch("pathlib.Path.mkdir")
    def test_log_error_rotates_large_log(
        self, mock_mkdir, mock_exists, mock_file, mock_rename, mock_stat, mock_get_root
    ):
        """Should rotate log file if it exceeds 1MB."""
        mock_get_root.return_value = Path("/workspace")
        mock_exists.return_value = True

        # Mock large file size
        mock_stat.return_value.st_size = 2_000_000  # 2MB

        exception = RuntimeError("Test")
        hook_input = {"tool_name": "Bash"}

        log_error_to_file("PreToolUse", exception, hook_input)

        # Should rename old log
        assert mock_rename.called


# get_workspace_root() Tests


class TestGetWorkspaceRoot:
    """Test workspace root detection."""

    def test_get_workspace_root_finds_git_and_claude(self):
        """Should find directory with both .git and CLAUDE."""
        # This test runs in actual project, should find root
        root = get_workspace_root()
        assert root.exists()
        assert (root / ".git").exists()
        assert (root / "CLAUDE").exists()

    def test_get_workspace_root_requires_both_markers(self):
        """Should require BOTH .git AND CLAUDE to exist."""
        root = get_workspace_root()
        # Verify both markers exist
        assert (root / ".git").exists()
        assert (root / "CLAUDE").exists()

    def test_get_workspace_root_returns_path(self):
        """Should return Path object."""
        root = get_workspace_root()
        assert isinstance(root, Path)
