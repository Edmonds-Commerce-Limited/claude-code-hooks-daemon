"""Tests for DaemonController."""

from datetime import datetime
from typing import Any
from unittest.mock import Mock

import pytest

from claude_code_hooks_daemon.core.chain import ChainExecutionResult
from claude_code_hooks_daemon.core.event import EventType, HookEvent
from claude_code_hooks_daemon.daemon.controller import (
    DaemonController,
    DaemonStats,
    get_controller,
    reset_controller,
)


class TestDaemonStats:
    """Tests for DaemonStats class."""

    @pytest.fixture
    def stats(self) -> DaemonStats:
        """Create a DaemonStats instance."""
        return DaemonStats()

    def test_stats_initialization(self, stats: DaemonStats) -> None:
        """Stats initialize with default values."""
        assert stats.requests_processed == 0
        assert stats.requests_by_event == {}
        assert stats.total_processing_time_ms == 0.0
        assert stats.errors == 0
        assert stats.last_request_time is None
        assert isinstance(stats.start_time, datetime)

    def test_record_request(self, stats: DaemonStats) -> None:
        """Recording a request updates stats."""
        stats.record_request("PreToolUse", 10.5)

        assert stats.requests_processed == 1
        assert stats.requests_by_event["PreToolUse"] == 1
        assert stats.total_processing_time_ms == 10.5
        assert stats.last_request_time is not None

    def test_record_multiple_requests(self, stats: DaemonStats) -> None:
        """Recording multiple requests accumulates stats."""
        stats.record_request("PreToolUse", 10.0)
        stats.record_request("PreToolUse", 20.0)
        stats.record_request("PostToolUse", 15.0)

        assert stats.requests_processed == 3
        assert stats.requests_by_event["PreToolUse"] == 2
        assert stats.requests_by_event["PostToolUse"] == 1
        assert stats.total_processing_time_ms == 45.0

    def test_record_error(self, stats: DaemonStats) -> None:
        """Recording an error increments error count."""
        assert stats.errors == 0

        stats.record_error()
        assert stats.errors == 1

        stats.record_error()
        assert stats.errors == 2

    def test_uptime_seconds(self, stats: DaemonStats) -> None:
        """Uptime seconds returns time since start."""
        uptime = stats.uptime_seconds
        assert uptime >= 0.0
        assert uptime < 1.0  # Test should run fast

    def test_avg_processing_time_ms(self, stats: DaemonStats) -> None:
        """Average processing time calculated correctly."""
        stats.record_request("PreToolUse", 10.0)
        stats.record_request("PostToolUse", 20.0)

        assert stats.avg_processing_time_ms == 15.0

    def test_avg_processing_time_ms_no_requests(self, stats: DaemonStats) -> None:
        """Average processing time is 0 when no requests."""
        assert stats.avg_processing_time_ms == 0.0

    def test_to_dict(self, stats: DaemonStats) -> None:
        """Stats can be converted to dictionary."""
        stats.record_request("PreToolUse", 10.0)

        result = stats.to_dict()

        assert isinstance(result, dict)
        assert "start_time" in result
        assert "uptime_seconds" in result
        assert "requests_processed" in result
        assert result["requests_processed"] == 1
        assert "requests_by_event" in result
        assert "avg_processing_time_ms" in result
        assert "errors" in result
        assert "last_request_time" in result

    def test_to_dict_with_no_last_request(self, stats: DaemonStats) -> None:
        """to_dict handles None last_request_time."""
        result = stats.to_dict()

        assert result["last_request_time"] is None


class TestDaemonController:
    """Tests for DaemonController class."""

    @pytest.fixture
    def controller(self) -> DaemonController:
        """Create a DaemonController instance."""
        return DaemonController()

    def test_controller_initialization(self, controller: DaemonController) -> None:
        """Controller initializes with default state."""
        assert controller.is_initialised is False
        assert controller.get_stats().requests_processed == 0

    def test_controller_initialization_with_config(self) -> None:
        """Controller can be initialized with config."""
        config = Mock()
        controller = DaemonController(config=config)

        assert controller._config is config

    def test_initialise(self, controller: DaemonController) -> None:
        """Initialise discovers and registers handlers."""
        controller.initialise()

        assert controller.is_initialised is True

    def test_initialise_only_once(self, controller: DaemonController) -> None:
        """Initialise only runs once."""
        controller.initialise()
        assert controller.is_initialised is True

        # Second call should be a no-op
        controller.initialise()
        assert controller.is_initialised is True

    def test_initialise_with_handler_config(self, controller: DaemonController) -> None:
        """Initialise accepts handler configuration."""
        handler_config: dict[str, dict[str, dict[str, Any]]] = {
            "pre_tool_use": {"destructive_git": {"enabled": True, "priority": 10}}
        }

        controller.initialise(handler_config=handler_config)

        assert controller.is_initialised is True

    def test_process_event(self, controller: DaemonController) -> None:
        """Process event routes to handler chain."""
        # Create a minimal HookEvent using correct field names
        from claude_code_hooks_daemon.core.event import HookInput

        event = HookEvent(
            event=EventType.PRE_TOOL_USE,
            hook_input=HookInput(
                tool_name="Bash",
                tool_input={"command": "ls"},
                transcript_path="/tmp/transcript.jsonl",
            ),
        )

        result = controller.process_event(event)

        assert isinstance(result, ChainExecutionResult)
        assert result.result is not None
        assert result.execution_time_ms >= 0

    def test_process_event_auto_initialises(self, controller: DaemonController) -> None:
        """Process event auto-initialises if not done."""
        from claude_code_hooks_daemon.core.event import HookInput

        assert controller.is_initialised is False

        event = HookEvent(
            event=EventType.PRE_TOOL_USE,
            hook_input=HookInput(
                tool_name="Bash",
                tool_input={"command": "ls"},
                transcript_path="/tmp/transcript.jsonl",
            ),
        )

        controller.process_event(event)

        assert controller.is_initialised is True

    def test_process_event_records_stats(self, controller: DaemonController) -> None:
        """Process event records statistics."""
        from claude_code_hooks_daemon.core.event import HookInput

        event = HookEvent(
            event=EventType.PRE_TOOL_USE,
            hook_input=HookInput(
                tool_name="Bash",
                tool_input={"command": "ls"},
                transcript_path="/tmp/transcript.jsonl",
            ),
        )

        controller.process_event(event)

        stats = controller.get_stats()
        assert stats.requests_processed == 1
        assert stats.requests_by_event["PreToolUse"] == 1

    def test_process_event_returns_valid_result(self, controller: DaemonController) -> None:
        """Process event returns a valid ChainExecutionResult."""
        from claude_code_hooks_daemon.core.event import HookInput

        controller._initialised = True

        event = HookEvent(
            event=EventType.PRE_TOOL_USE,
            hook_input=HookInput(
                tool_name="Bash",
                tool_input={"command": "ls"},
                transcript_path="/tmp/transcript.jsonl",
            ),
        )

        result = controller.process_event(event)

        # Should return a valid result
        assert isinstance(result, ChainExecutionResult)
        assert result.result is not None
        assert result.result.decision.value in ["allow", "deny", "block", "error"]
        assert result.execution_time_ms >= 0

    def test_process_request(self, controller: DaemonController) -> None:
        """Process request parses and routes event."""
        request_data = {
            "event": "PreToolUse",
            "hook_input": {
                "tool_name": "Bash",
                "tool_input": {"command": "ls"},
                "transcript_path": "/tmp/transcript.jsonl",
            },
        }

        response = controller.process_request(request_data)

        assert isinstance(response, dict)
        # Response should be a valid hook response dict
        assert "result" in response or "hookSpecificOutput" in response or "decision" in response

    def test_process_request_invalid_data(self, controller: DaemonController) -> None:
        """Process request handles invalid data."""
        request_data = {
            "invalid": "data",
        }

        response = controller.process_request(request_data)

        assert isinstance(response, dict)
        # Should contain error response in some form
        assert "result" in response or "decision" in response or "hookSpecificOutput" in response

    def test_get_stats(self, controller: DaemonController) -> None:
        """Get stats returns current statistics."""
        stats = controller.get_stats()

        assert isinstance(stats, DaemonStats)
        assert stats.requests_processed == 0

    def test_get_health(self, controller: DaemonController) -> None:
        """Get health returns health information."""
        health = controller.get_health()

        assert isinstance(health, dict)
        assert "status" in health
        assert health["status"] == "healthy"
        assert "initialised" in health
        assert "stats" in health
        assert "handlers" in health

    def test_get_handlers(self, controller: DaemonController) -> None:
        """Get handlers returns handler details."""
        controller.initialise()

        handlers = controller.get_handlers()

        assert isinstance(handlers, dict)
        # Should have handler entries for various events
        # (depends on discovered handlers, so just check structure)
        for event_type, handler_list in handlers.items():
            assert isinstance(event_type, str)
            assert isinstance(handler_list, list)
            for handler_info in handler_list:
                assert "name" in handler_info
                assert "class" in handler_info
                assert "priority" in handler_info
                assert "terminal" in handler_info

    def test_get_router(self, controller: DaemonController) -> None:
        """Get router returns event router."""
        router = controller.get_router()

        assert router is not None
        assert router is controller._router

    def test_get_registry(self, controller: DaemonController) -> None:
        """Get registry returns handler registry."""
        registry = controller.get_registry()

        assert registry is not None
        assert registry is controller._registry


class TestGlobalController:
    """Tests for global controller functions."""

    def teardown_method(self) -> None:
        """Reset controller after each test."""
        reset_controller()

    def test_get_controller_creates_instance(self) -> None:
        """get_controller creates a controller instance."""
        controller = get_controller()

        assert isinstance(controller, DaemonController)

    def test_get_controller_returns_same_instance(self) -> None:
        """get_controller returns the same instance."""
        controller1 = get_controller()
        controller2 = get_controller()

        assert controller1 is controller2

    def test_reset_controller(self) -> None:
        """reset_controller clears the global controller."""
        controller1 = get_controller()
        assert controller1 is not None

        reset_controller()

        controller2 = get_controller()
        assert controller2 is not controller1


class TestIntegration:
    """Integration tests for DaemonController."""

    @pytest.fixture
    def controller(self) -> DaemonController:
        """Create a DaemonController instance."""
        return DaemonController()

    def test_full_request_processing_flow(self, controller: DaemonController) -> None:
        """Full flow from request to response."""
        # Initialize
        controller.initialise()

        # Process request
        request_data = {
            "event": "PreToolUse",
            "hook_input": {
                "tool_name": "Bash",
                "tool_input": {"command": "echo hello"},
                "transcript_path": "/tmp/transcript.jsonl",
            },
        }

        response = controller.process_request(request_data)

        # Verify response
        assert isinstance(response, dict)

        # Verify stats updated - should have processed 1 request
        stats = controller.get_stats()
        assert stats.requests_processed >= 1
        assert "PreToolUse" in stats.requests_by_event
        assert stats.errors == 0

    def test_multiple_requests(self, controller: DaemonController) -> None:
        """Multiple requests accumulate stats."""
        controller.initialise()

        for i in range(5):
            request_data = {
                "event": "PreToolUse",
                "hook_input": {
                    "tool_name": "Bash",
                    "tool_input": {"command": f"echo {i}"},
                    "transcript_path": "/tmp/transcript.jsonl",
                },
            }
            controller.process_request(request_data)

        stats = controller.get_stats()
        assert stats.requests_processed >= 5
        assert stats.requests_by_event.get("PreToolUse", 0) >= 5

    def test_health_check_after_requests(self, controller: DaemonController) -> None:
        """Health check reflects request processing."""
        controller.initialise()

        request_data = {
            "event": "PreToolUse",
            "hook_input": {
                "tool_name": "Bash",
                "tool_input": {"command": "ls"},
                "transcript_path": "/tmp/transcript.jsonl",
            },
        }

        controller.process_request(request_data)

        health = controller.get_health()
        assert health["status"] == "healthy"
        assert health["initialised"] is True
        assert health["stats"]["requests_processed"] >= 1
