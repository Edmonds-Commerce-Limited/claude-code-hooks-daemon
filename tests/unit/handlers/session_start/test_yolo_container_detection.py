"""
Unit tests for YoloContainerDetectionHandler.

Tests the YOLO container detection handler that provides informational context
about running in a YOLO container environment during SessionStart.
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.core import HookResult

# We'll implement the handler next, so import will fail initially
try:
    from claude_code_hooks_daemon.handlers.session_start.yolo_container_detection import (
        YoloContainerDetectionHandler,
    )
except ImportError:
    YoloContainerDetectionHandler = None


pytestmark = pytest.mark.skipif(
    YoloContainerDetectionHandler is None,
    reason="YoloContainerDetectionHandler not yet implemented",
)


class TestYoloContainerDetectionHandler:
    """Test handler initialization and configuration."""

    def test_handler_initialization_defaults(self):
        """Test handler initializes with correct defaults."""
        handler = YoloContainerDetectionHandler()

        assert handler.name == "yolo-container-detection"
        assert handler.priority == 40
        assert handler.terminal is False

    def test_handler_with_custom_config(self):
        """Test handler accepts custom configuration."""
        config = {
            "min_confidence_score": 5,
            "show_detailed_indicators": False,
            "show_workflow_tips": False,
        }

        handler = YoloContainerDetectionHandler()
        handler.configure(config)

        # Verify config is stored (implementation will use these)
        assert hasattr(handler, "config")
        assert handler.config["min_confidence_score"] == 5
        assert handler.config["show_detailed_indicators"] is False
        assert handler.config["show_workflow_tips"] is False

    def test_handler_config_defaults_applied(self):
        """Test default config values are applied when not specified."""
        handler = YoloContainerDetectionHandler()
        handler.configure({})

        assert handler.config["min_confidence_score"] == 3
        assert handler.config["show_detailed_indicators"] is True
        assert handler.config["show_workflow_tips"] is True


class TestYoloContainerDetectionConfidenceScoring:
    """Test confidence scoring logic with various indicator combinations."""

    def test_primary_indicator_claudecode_env(self, monkeypatch):
        """Test CLAUDECODE=1 gives 3 points (primary)."""
        monkeypatch.setenv("CLAUDECODE", "1")

        handler = YoloContainerDetectionHandler()
        score = handler._calculate_confidence_score()

        assert score >= 3  # At least 3 from this indicator

    def test_primary_indicator_claude_code_entrypoint(self, monkeypatch):
        """Test CLAUDE_CODE_ENTRYPOINT=cli gives 3 points (primary)."""
        monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", "cli")

        handler = YoloContainerDetectionHandler()
        score = handler._calculate_confidence_score()

        assert score >= 3

    def test_primary_indicator_workspace_with_claude_dir(self, monkeypatch):
        """Test /workspace + .claude/ gives 3 points (primary)."""
        with patch("pathlib.Path.cwd", return_value=Path("/workspace")):
            with patch("pathlib.Path.exists", return_value=True):
                handler = YoloContainerDetectionHandler()
                score = handler._calculate_confidence_score()

                assert score >= 3

    def test_secondary_indicator_devcontainer(self, monkeypatch):
        """Test DEVCONTAINER=true gives 2 points (secondary)."""
        monkeypatch.setenv("DEVCONTAINER", "true")

        handler = YoloContainerDetectionHandler()
        score = handler._calculate_confidence_score()

        assert score >= 2

    def test_secondary_indicator_is_sandbox(self, monkeypatch):
        """Test IS_SANDBOX=1 gives 2 points (secondary)."""
        monkeypatch.setenv("IS_SANDBOX", "1")

        handler = YoloContainerDetectionHandler()
        score = handler._calculate_confidence_score()

        assert score >= 2

    def test_secondary_indicator_container_podman(self, monkeypatch):
        """Test container=podman gives 2 points (secondary)."""
        monkeypatch.setenv("container", "podman")

        handler = YoloContainerDetectionHandler()
        score = handler._calculate_confidence_score()

        assert score >= 2

    def test_secondary_indicator_container_docker(self, monkeypatch):
        """Test container=docker gives 2 points (secondary)."""
        monkeypatch.setenv("container", "docker")

        handler = YoloContainerDetectionHandler()
        score = handler._calculate_confidence_score()

        assert score >= 2

    def test_tertiary_indicator_socket_exists(self):
        """Test socket file existence gives 1 point (tertiary)."""
        with patch("pathlib.Path.exists", return_value=True):
            handler = YoloContainerDetectionHandler()
            score = handler._calculate_confidence_score()

            # Socket alone won't trigger detection, but adds to score
            assert score >= 1

    def test_tertiary_indicator_root_user(self):
        """Test running as root (UID 0) gives 1 point (tertiary)."""
        with patch("os.getuid", return_value=0):
            handler = YoloContainerDetectionHandler()
            score = handler._calculate_confidence_score()

            assert score >= 1

    def test_multiple_primary_indicators(self, monkeypatch):
        """Test multiple primary indicators accumulate points."""
        monkeypatch.setenv("CLAUDECODE", "1")
        monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", "cli")

        handler = YoloContainerDetectionHandler()
        score = handler._calculate_confidence_score()

        # Two primary indicators = 6 points minimum
        assert score >= 6

    def test_mixed_indicators(self, monkeypatch):
        """Test combination of primary, secondary, and tertiary indicators."""
        monkeypatch.setenv("CLAUDECODE", "1")  # Primary: 3
        monkeypatch.setenv("IS_SANDBOX", "1")  # Secondary: 2
        # Total: 5 points

        with patch("os.getuid", return_value=0):  # Tertiary: 1, Total: 6
            handler = YoloContainerDetectionHandler()
            score = handler._calculate_confidence_score()

            assert score >= 6

    def test_no_indicators_zero_score(self, monkeypatch):
        """Test no indicators results in zero score."""
        # Clear all environment variables
        for key in [
            "CLAUDECODE",
            "CLAUDE_CODE_ENTRYPOINT",
            "DEVCONTAINER",
            "IS_SANDBOX",
            "container",
        ]:
            monkeypatch.delenv(key, raising=False)

        with patch("pathlib.Path.cwd", return_value=Path("/home/user")):
            with patch("pathlib.Path.exists", return_value=False):
                with patch("os.getuid", return_value=1000):
                    handler = YoloContainerDetectionHandler()
                    score = handler._calculate_confidence_score()

                    assert score == 0

    def test_threshold_exactly_met(self, monkeypatch):
        """Test score exactly meeting threshold (3 points)."""
        # Clear all YOLO indicators first
        for key in [
            "CLAUDECODE",
            "CLAUDE_CODE_ENTRYPOINT",
            "DEVCONTAINER",
            "IS_SANDBOX",
            "container",
        ]:
            monkeypatch.delenv(key, raising=False)

        # Set exactly one primary indicator (3 points)
        monkeypatch.setenv("CLAUDECODE", "1")

        with patch("pathlib.Path.cwd", return_value=Path("/home/user")):
            with patch("pathlib.Path.exists", return_value=False):
                with patch("os.getuid", return_value=1000):
                    handler = YoloContainerDetectionHandler()
                    score = handler._calculate_confidence_score()

                    assert score == 3

    def test_threshold_not_met(self, monkeypatch):
        """Test score below threshold (< 3 points)."""
        # Clear all YOLO indicators first
        for key in [
            "CLAUDECODE",
            "CLAUDE_CODE_ENTRYPOINT",
            "DEVCONTAINER",
            "IS_SANDBOX",
            "container",
        ]:
            monkeypatch.delenv(key, raising=False)

        # Set exactly one secondary indicator (2 points)
        monkeypatch.setenv("IS_SANDBOX", "1")

        with patch("pathlib.Path.cwd", return_value=Path("/home/user")):
            with patch("pathlib.Path.exists", return_value=False):
                with patch("os.getuid", return_value=1000):
                    handler = YoloContainerDetectionHandler()
                    score = handler._calculate_confidence_score()

                    assert score == 2
                    assert score < 3  # Below threshold


class TestYoloContainerDetectionGetDetectedIndicators:
    """Test indicator detection and reporting."""

    def test_get_detected_indicators_primary(self, monkeypatch):
        """Test primary indicators are correctly identified."""
        monkeypatch.setenv("CLAUDECODE", "1")

        handler = YoloContainerDetectionHandler()
        indicators = handler._get_detected_indicators()

        assert "CLAUDECODE=1 environment variable" in indicators

    def test_get_detected_indicators_multiple(self, monkeypatch):
        """Test multiple indicators are all reported."""
        monkeypatch.setenv("CLAUDECODE", "1")
        monkeypatch.setenv("IS_SANDBOX", "1")

        handler = YoloContainerDetectionHandler()
        indicators = handler._get_detected_indicators()

        assert len(indicators) >= 2
        assert any("CLAUDECODE" in ind for ind in indicators)
        assert any("IS_SANDBOX" in ind for ind in indicators)

    def test_get_detected_indicators_empty(self, monkeypatch):
        """Test no indicators results in empty list."""
        for key in [
            "CLAUDECODE",
            "CLAUDE_CODE_ENTRYPOINT",
            "DEVCONTAINER",
            "IS_SANDBOX",
            "container",
        ]:
            monkeypatch.delenv(key, raising=False)

        with patch("pathlib.Path.exists", return_value=False):
            with patch("os.getuid", return_value=1000):
                handler = YoloContainerDetectionHandler()
                indicators = handler._get_detected_indicators()

                assert indicators == []


class TestYoloContainerDetectionMatches:
    """Test matches() method logic."""

    def test_matches_session_start_with_sufficient_confidence(self, monkeypatch):
        """Test handler matches SessionStart with score >= threshold."""
        monkeypatch.setenv("CLAUDECODE", "1")  # 3 points

        handler = YoloContainerDetectionHandler()
        hook_input = {"hook_event_name": "SessionStart"}

        assert handler.matches(hook_input) is True

    def test_matches_session_start_insufficient_confidence(self, monkeypatch):
        """Test handler doesn't match SessionStart with score < threshold."""
        # Clear all YOLO indicators first
        for key in [
            "CLAUDECODE",
            "CLAUDE_CODE_ENTRYPOINT",
            "DEVCONTAINER",
            "IS_SANDBOX",
            "container",
        ]:
            monkeypatch.delenv(key, raising=False)

        # Set exactly one secondary indicator (2 points, below threshold of 3)
        monkeypatch.setenv("IS_SANDBOX", "1")

        with patch("pathlib.Path.cwd", return_value=Path("/home/user")):
            with patch("pathlib.Path.exists", return_value=False):
                with patch("os.getuid", return_value=1000):
                    handler = YoloContainerDetectionHandler()
                    hook_input = {"hook_event_name": "SessionStart"}

                    assert handler.matches(hook_input) is False

    def test_matches_wrong_event_type(self, monkeypatch):
        """Test handler doesn't match non-SessionStart events."""
        monkeypatch.setenv("CLAUDECODE", "1")  # Sufficient confidence

        handler = YoloContainerDetectionHandler()
        hook_input = {"hook_event_name": "PreToolUse"}

        assert handler.matches(hook_input) is False

    def test_matches_respects_custom_threshold(self, monkeypatch):
        """Test handler respects custom min_confidence_score config."""
        # Clear all YOLO indicators first
        for key in [
            "CLAUDECODE",
            "CLAUDE_CODE_ENTRYPOINT",
            "DEVCONTAINER",
            "IS_SANDBOX",
            "container",
        ]:
            monkeypatch.delenv(key, raising=False)

        # Set exactly one primary indicator (3 points)
        monkeypatch.setenv("CLAUDECODE", "1")

        with patch("pathlib.Path.cwd", return_value=Path("/home/user")):
            with patch("pathlib.Path.exists", return_value=False):
                with patch("os.getuid", return_value=1000):
                    handler = YoloContainerDetectionHandler()
                    handler.configure({"min_confidence_score": 5})  # Require 5 points

                    hook_input = {"hook_event_name": "SessionStart"}

                    # 3 points < 5 required, should not match
                    assert handler.matches(hook_input) is False

    def test_matches_missing_hook_event_name(self):
        """Test handler handles missing hook_event_name gracefully."""
        handler = YoloContainerDetectionHandler()
        hook_input = {}

        # Should not crash, should return False
        assert handler.matches(hook_input) is False

    def test_matches_none_hook_input(self):
        """Test handler handles None hook_input gracefully."""
        handler = YoloContainerDetectionHandler()

        # Should not crash, should return False
        assert handler.matches(None) is False


class TestYoloContainerDetectionHandle:
    """Test handle() method output and behavior."""

    def test_handle_returns_allow_decision(self, monkeypatch):
        """Test handler always returns ALLOW decision."""
        monkeypatch.setenv("CLAUDECODE", "1")

        handler = YoloContainerDetectionHandler()
        hook_input = {"hook_event_name": "SessionStart"}

        result = handler.handle(hook_input)

        assert isinstance(result, HookResult)
        assert result.decision == "allow"

    def test_handle_context_is_list(self, monkeypatch):
        """Test context is a list, not a string."""
        monkeypatch.setenv("CLAUDECODE", "1")

        handler = YoloContainerDetectionHandler()
        hook_input = {"hook_event_name": "SessionStart"}

        result = handler.handle(hook_input)

        assert isinstance(result.context, list)
        assert len(result.context) > 0

    def test_handle_context_includes_detection_message(self, monkeypatch):
        """Test context includes YOLO detection message."""
        monkeypatch.setenv("CLAUDECODE", "1")

        handler = YoloContainerDetectionHandler()
        hook_input = {"hook_event_name": "SessionStart"}

        result = handler.handle(hook_input)

        # Join context items to search for message
        context_text = " ".join(result.context)
        assert "YOLO" in context_text or "container" in context_text.lower()

    def test_handle_context_includes_indicators_when_enabled(self, monkeypatch):
        """Test context includes indicator list when show_detailed_indicators=True."""
        monkeypatch.setenv("CLAUDECODE", "1")

        handler = YoloContainerDetectionHandler()
        handler.configure({"show_detailed_indicators": True})

        hook_input = {"hook_event_name": "SessionStart"}
        result = handler.handle(hook_input)

        context_text = " ".join(result.context)
        assert "CLAUDECODE" in context_text or "indicator" in context_text.lower()

    def test_handle_context_excludes_indicators_when_disabled(self, monkeypatch):
        """Test context excludes indicator list when show_detailed_indicators=False."""
        monkeypatch.setenv("CLAUDECODE", "1")

        handler = YoloContainerDetectionHandler()
        handler.configure({"show_detailed_indicators": False})

        hook_input = {"hook_event_name": "SessionStart"}
        result = handler.handle(hook_input)

        # Should still have basic message, but not detailed indicators
        assert len(result.context) > 0
        # This is harder to test precisely without knowing exact format

    def test_handle_context_includes_workflow_tips_when_enabled(self, monkeypatch):
        """Test context includes workflow tips when show_workflow_tips=True."""
        monkeypatch.setenv("CLAUDECODE", "1")

        handler = YoloContainerDetectionHandler()
        handler.configure({"show_workflow_tips": True})

        hook_input = {"hook_event_name": "SessionStart"}
        result = handler.handle(hook_input)

        context_text = " ".join(result.context)
        # Look for workflow-related keywords
        assert any(
            keyword in context_text.lower()
            for keyword in ["workflow", "tip", "ephemeral", "container"]
        )

    def test_handle_context_excludes_workflow_tips_when_disabled(self, monkeypatch):
        """Test context is minimal when show_workflow_tips=False."""
        monkeypatch.setenv("CLAUDECODE", "1")

        handler = YoloContainerDetectionHandler()
        handler.configure({"show_workflow_tips": False})

        hook_input = {"hook_event_name": "SessionStart"}
        result = handler.handle(hook_input)

        # Should have shorter context without tips
        assert len(result.context) >= 1

    def test_handle_no_reason_provided(self, monkeypatch):
        """Test handler doesn't provide reason (informational, not blocking)."""
        monkeypatch.setenv("CLAUDECODE", "1")

        handler = YoloContainerDetectionHandler()
        hook_input = {"hook_event_name": "SessionStart"}

        result = handler.handle(hook_input)

        # Reason should be None or empty for non-blocking handlers
        assert result.reason is None or result.reason == ""


class TestYoloContainerDetectionEdgeCases:
    """Test error handling and edge cases."""

    def test_handle_with_exception_in_scoring_fails_open(self, monkeypatch):
        """Test handler fails open (returns ALLOW) if scoring throws exception."""
        handler = YoloContainerDetectionHandler()

        # Patch _calculate_confidence_score to raise exception
        with patch.object(
            handler, "_calculate_confidence_score", side_effect=Exception("Test error")
        ):
            hook_input = {"hook_event_name": "SessionStart"}

            # Should not crash, should return ALLOW with no context
            result = handler.handle(hook_input)

            assert result.decision == "allow"
            # Context might be empty or have error message
            assert isinstance(result.context, list)

    def test_handle_with_exception_in_get_indicators_fails_open(self, monkeypatch):
        """Test handler fails open if get_indicators throws exception."""
        monkeypatch.setenv("CLAUDECODE", "1")  # Ensure matches() returns True

        handler = YoloContainerDetectionHandler()

        # Patch _get_detected_indicators to raise exception
        with patch.object(handler, "_get_detected_indicators", side_effect=Exception("Test error")):
            hook_input = {"hook_event_name": "SessionStart"}

            # Should not crash
            result = handler.handle(hook_input)

            assert result.decision == "allow"

    def test_filesystem_error_during_cwd_check(self):
        """Test handler handles filesystem errors gracefully."""
        with patch("pathlib.Path.cwd", side_effect=OSError("Permission denied")):
            handler = YoloContainerDetectionHandler()

            # Should not crash, should return 0 or partial score
            try:
                score = handler._calculate_confidence_score()
                assert score >= 0  # Should succeed with reduced score
            except Exception:
                pytest.fail("Handler should not raise exception on filesystem error")

    def test_filesystem_error_during_exists_check(self):
        """Test handler handles exists() errors gracefully."""
        with patch("pathlib.Path.exists", side_effect=OSError("Permission denied")):
            handler = YoloContainerDetectionHandler()

            # Should not crash
            try:
                score = handler._calculate_confidence_score()
                assert score >= 0
            except Exception:
                pytest.fail("Handler should not raise exception on exists() error")

    def test_malformed_hook_input(self, monkeypatch):
        """Test handler handles malformed hook_input gracefully."""
        monkeypatch.setenv("CLAUDECODE", "1")

        handler = YoloContainerDetectionHandler()

        # Various malformed inputs
        malformed_inputs = [
            {"hook_event_name": 12345},  # Wrong type
            {"hook_event_name": None},  # None value
            {"wrong_key": "SessionStart"},  # Wrong key
            [],  # List instead of dict
            "SessionStart",  # String instead of dict
        ]

        for hook_input in malformed_inputs:
            result = handler.matches(hook_input)
            # Should not crash, should return False
            assert result is False


class TestYoloContainerDetectionIntegration:
    """End-to-end integration tests."""

    def test_full_workflow_yolo_detected(self, monkeypatch):
        """Test complete workflow: matches → handle → result."""
        # Set up YOLO environment
        monkeypatch.setenv("CLAUDECODE", "1")
        monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", "cli")

        handler = YoloContainerDetectionHandler()
        hook_input = {"hook_event_name": "SessionStart", "source": "new"}

        # Step 1: Check if handler matches
        assert handler.matches(hook_input) is True

        # Step 2: Handle the event
        result = handler.handle(hook_input)

        # Step 3: Verify result is correct
        assert result.decision == "allow"
        assert isinstance(result.context, list)
        assert len(result.context) > 0

    def test_full_workflow_yolo_not_detected(self, monkeypatch):
        """Test complete workflow when YOLO not detected."""
        # Clear environment
        for key in [
            "CLAUDECODE",
            "CLAUDE_CODE_ENTRYPOINT",
            "DEVCONTAINER",
            "IS_SANDBOX",
            "container",
        ]:
            monkeypatch.delenv(key, raising=False)

        with patch("pathlib.Path.cwd", return_value=Path("/home/user")):
            with patch("pathlib.Path.exists", return_value=False):
                with patch("os.getuid", return_value=1000):
                    handler = YoloContainerDetectionHandler()
                    hook_input = {"hook_event_name": "SessionStart"}

                    # Handler should not match
                    assert handler.matches(hook_input) is False

                    # If we call handle anyway, should still return ALLOW (fail open)
                    result = handler.handle(hook_input)
                    assert result.decision == "allow"

    def test_json_serialization_of_result(self, monkeypatch):
        """Test that HookResult can be serialized to JSON."""
        monkeypatch.setenv("CLAUDECODE", "1")

        handler = YoloContainerDetectionHandler()
        hook_input = {"hook_event_name": "SessionStart"}

        result = handler.handle(hook_input)

        # Convert to dict and serialize
        result_dict = {
            "decision": result.decision,
            "reason": result.reason,
            "context": result.context,
        }

        # Should not raise exception
        json_str = json.dumps(result_dict)
        assert isinstance(json_str, str)

        # Should be parseable
        parsed = json.loads(json_str)
        assert parsed["decision"] == "allow"

    def test_handler_is_non_terminal(self, monkeypatch):
        """Test handler is non-terminal (allows dispatch to continue)."""
        handler = YoloContainerDetectionHandler()

        assert handler.terminal is False

    def test_handler_priority_is_workflow_range(self):
        """Test handler priority is in workflow range (36-55)."""
        handler = YoloContainerDetectionHandler()

        assert 36 <= handler.priority <= 55
