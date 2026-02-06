"""Tests for DaemonController degraded mode (config validation at startup).

Plan 00020: Configuration Validation at Daemon Startup
"""

from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

import pytest

from claude_code_hooks_daemon.core.event import EventType, HookEvent, HookInput
from claude_code_hooks_daemon.core.hook_result import Decision
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.daemon.controller import DaemonController


class TestDegradedModeInit:
    """Tests for DaemonController degraded mode initialization."""

    def teardown_method(self) -> None:
        """Reset ProjectContext after each test."""
        ProjectContext.reset()

    @pytest.fixture
    def workspace_root(self, tmp_path: Path) -> Path:
        """Create a workspace root with config file for testing."""
        workspace = tmp_path / "test-workspace"
        claude_dir = workspace / ".claude"
        claude_dir.mkdir(parents=True)
        config_file = claude_dir / "hooks-daemon.yaml"
        config_file.write_text("version: 1.0\n")
        return workspace

    def test_controller_not_degraded_by_default(self) -> None:
        """New controller should not be in degraded mode."""
        controller = DaemonController()
        assert controller.is_degraded is False

    def test_controller_no_config_errors_by_default(self) -> None:
        """New controller should have no config errors."""
        controller = DaemonController()
        assert controller.config_errors == []

    def test_controller_enters_degraded_mode_on_config_errors(self, workspace_root: Path) -> None:
        """Controller should enter degraded mode when config validation fails."""
        controller = DaemonController()

        # Mock ConfigValidator.validate to return errors
        with (
            patch("subprocess.run") as mock_run,
            patch(
                "claude_code_hooks_daemon.daemon.controller.ConfigValidator.validate",
                return_value=["Missing required field: version", "Invalid handler name 'bad'"],
            ),
        ):
            mock_run.side_effect = [
                Mock(returncode=0, stdout=b"/tmp/test\n"),
                Mock(returncode=0, stdout=b"git@github.com:test/repo.git\n"),
                Mock(returncode=0, stdout=b"/tmp/test\n"),
            ]
            controller.initialise(workspace_root=workspace_root)

        assert controller.is_degraded is True
        assert len(controller.config_errors) == 2
        assert "Missing required field: version" in controller.config_errors

    def test_controller_still_initialises_when_degraded(self, workspace_root: Path) -> None:
        """Controller should still be initialised even when degraded (fail-open)."""
        controller = DaemonController()

        with (
            patch("subprocess.run") as mock_run,
            patch(
                "claude_code_hooks_daemon.daemon.controller.ConfigValidator.validate",
                return_value=["Some error"],
            ),
        ):
            mock_run.side_effect = [
                Mock(returncode=0, stdout=b"/tmp/test\n"),
                Mock(returncode=0, stdout=b"git@github.com:test/repo.git\n"),
                Mock(returncode=0, stdout=b"/tmp/test\n"),
            ]
            controller.initialise(workspace_root=workspace_root)

        assert controller.is_initialised is True
        assert controller.is_degraded is True

    def test_controller_not_degraded_with_valid_config(self, workspace_root: Path) -> None:
        """Controller should not be degraded when config is valid."""
        controller = DaemonController()

        with (
            patch("subprocess.run") as mock_run,
            patch(
                "claude_code_hooks_daemon.daemon.controller.ConfigValidator.validate",
                return_value=[],
            ),
        ):
            mock_run.side_effect = [
                Mock(returncode=0, stdout=b"/tmp/test\n"),
                Mock(returncode=0, stdout=b"git@github.com:test/repo.git\n"),
                Mock(returncode=0, stdout=b"/tmp/test\n"),
            ]
            controller.initialise(workspace_root=workspace_root)

        assert controller.is_degraded is False
        assert controller.config_errors == []


class TestDegradedModeRequestHandling:
    """Tests for request handling in degraded mode."""

    def teardown_method(self) -> None:
        """Reset ProjectContext after each test."""
        ProjectContext.reset()

    @pytest.fixture
    def workspace_root(self, tmp_path: Path) -> Path:
        """Create a workspace root with config file for testing."""
        workspace = tmp_path / "test-workspace"
        claude_dir = workspace / ".claude"
        claude_dir.mkdir(parents=True)
        config_file = claude_dir / "hooks-daemon.yaml"
        config_file.write_text("version: 1.0\n")
        return workspace

    @pytest.fixture
    def degraded_controller(self, workspace_root: Path) -> DaemonController:
        """Create a controller in degraded mode."""
        controller = DaemonController()

        with (
            patch("subprocess.run") as mock_run,
            patch(
                "claude_code_hooks_daemon.daemon.controller.ConfigValidator.validate",
                return_value=["Missing required field: version"],
            ),
        ):
            mock_run.side_effect = [
                Mock(returncode=0, stdout=b"/tmp/test\n"),
                Mock(returncode=0, stdout=b"git@github.com:test/repo.git\n"),
                Mock(returncode=0, stdout=b"/tmp/test\n"),
            ]
            controller.initialise(workspace_root=workspace_root)

        return controller

    def test_degraded_process_event_returns_config_error(
        self, degraded_controller: DaemonController
    ) -> None:
        """In degraded mode, process_event should return configuration error."""
        event = HookEvent(
            event=EventType.PRE_TOOL_USE,
            hook_input=HookInput(
                tool_name="Bash",
                tool_input={"command": "ls"},
                transcript_path="/tmp/transcript.jsonl",
            ),
        )

        result = degraded_controller.process_event(event)

        # Should return allow with config error context (fail-open)
        assert result.result.decision == Decision.ALLOW
        context_text = "\n".join(result.result.context)
        assert "configuration" in context_text.lower() or "DEGRADED" in context_text

    def test_degraded_process_request_returns_config_error(
        self, degraded_controller: DaemonController
    ) -> None:
        """In degraded mode, process_request should return configuration error response."""
        request_data: dict[str, Any] = {
            "event": "PreToolUse",
            "hook_input": {
                "tool_name": "Bash",
                "tool_input": {"command": "ls"},
                "transcript_path": "/tmp/transcript.jsonl",
            },
        }

        response = degraded_controller.process_request(request_data)

        assert isinstance(response, dict)
        # Response should contain configuration error info
        # For PreToolUse, this means hookSpecificOutput with additionalContext
        if "hookSpecificOutput" in response:
            context = response["hookSpecificOutput"].get("additionalContext", "")
            assert "configuration" in context.lower() or "DEGRADED" in context

    def test_degraded_every_request_returns_error(
        self, degraded_controller: DaemonController
    ) -> None:
        """Every request in degraded mode should return config error."""
        for event_type in [EventType.PRE_TOOL_USE, EventType.POST_TOOL_USE]:
            event = HookEvent(
                event=event_type,
                hook_input=HookInput(
                    tool_name="Bash",
                    tool_input={"command": "ls"},
                    transcript_path="/tmp/transcript.jsonl",
                ),
            )

            result = degraded_controller.process_event(event)
            assert result.result.decision == Decision.ALLOW
            assert len(result.result.context) > 0


class TestDegradedModeHealthStatus:
    """Tests for health status in degraded mode."""

    def teardown_method(self) -> None:
        """Reset ProjectContext after each test."""
        ProjectContext.reset()

    @pytest.fixture
    def workspace_root(self, tmp_path: Path) -> Path:
        """Create a workspace root with config file for testing."""
        workspace = tmp_path / "test-workspace"
        claude_dir = workspace / ".claude"
        claude_dir.mkdir(parents=True)
        config_file = claude_dir / "hooks-daemon.yaml"
        config_file.write_text("version: 1.0\n")
        return workspace

    def test_degraded_health_status(self, workspace_root: Path) -> None:
        """Health check should report degraded status."""
        controller = DaemonController()

        with (
            patch("subprocess.run") as mock_run,
            patch(
                "claude_code_hooks_daemon.daemon.controller.ConfigValidator.validate",
                return_value=["Missing required field: version"],
            ),
        ):
            mock_run.side_effect = [
                Mock(returncode=0, stdout=b"/tmp/test\n"),
                Mock(returncode=0, stdout=b"git@github.com:test/repo.git\n"),
                Mock(returncode=0, stdout=b"/tmp/test\n"),
            ]
            controller.initialise(workspace_root=workspace_root)

        health = controller.get_health()
        assert health["status"] == "degraded"
        assert "config_errors" in health
        assert len(health["config_errors"]) == 1

    def test_healthy_status_with_valid_config(self, workspace_root: Path) -> None:
        """Health check should report healthy when config is valid."""
        controller = DaemonController()

        with (
            patch("subprocess.run") as mock_run,
            patch(
                "claude_code_hooks_daemon.daemon.controller.ConfigValidator.validate",
                return_value=[],
            ),
        ):
            mock_run.side_effect = [
                Mock(returncode=0, stdout=b"/tmp/test\n"),
                Mock(returncode=0, stdout=b"git@github.com:test/repo.git\n"),
                Mock(returncode=0, stdout=b"/tmp/test\n"),
            ]
            controller.initialise(workspace_root=workspace_root)

        health = controller.get_health()
        assert health["status"] == "healthy"
        assert "config_errors" not in health or health["config_errors"] == []


class TestConfigValidationIntegration:
    """Tests for config validation integration with startup."""

    def teardown_method(self) -> None:
        """Reset ProjectContext after each test."""
        ProjectContext.reset()

    @pytest.fixture
    def workspace_root(self, tmp_path: Path) -> Path:
        """Create a workspace root with config file for testing."""
        workspace = tmp_path / "test-workspace"
        claude_dir = workspace / ".claude"
        claude_dir.mkdir(parents=True)
        config_file = claude_dir / "hooks-daemon.yaml"
        config_file.write_text("version: 1.0\n")
        return workspace

    def test_validation_exception_does_not_crash_startup(self, workspace_root: Path) -> None:
        """If ConfigValidator.validate() itself raises, daemon should still start."""
        controller = DaemonController()

        with (
            patch("subprocess.run") as mock_run,
            patch(
                "claude_code_hooks_daemon.daemon.controller.ConfigValidator.validate",
                side_effect=Exception("Validator crashed"),
            ),
        ):
            mock_run.side_effect = [
                Mock(returncode=0, stdout=b"/tmp/test\n"),
                Mock(returncode=0, stdout=b"git@github.com:test/repo.git\n"),
                Mock(returncode=0, stdout=b"/tmp/test\n"),
            ]
            # Should NOT raise - daemon should start even if validator crashes
            controller.initialise(workspace_root=workspace_root)

        assert controller.is_initialised is True
        # Should be degraded with the exception error
        assert controller.is_degraded is True
        assert len(controller.config_errors) > 0

    def test_validation_called_with_config_dict(self, workspace_root: Path) -> None:
        """ConfigValidator.validate() should be called during initialise."""
        controller = DaemonController()

        with (
            patch("subprocess.run") as mock_run,
            patch(
                "claude_code_hooks_daemon.daemon.controller.ConfigValidator.validate",
                return_value=[],
            ) as mock_validate,
        ):
            mock_run.side_effect = [
                Mock(returncode=0, stdout=b"/tmp/test\n"),
                Mock(returncode=0, stdout=b"git@github.com:test/repo.git\n"),
                Mock(returncode=0, stdout=b"/tmp/test\n"),
            ]
            controller.initialise(workspace_root=workspace_root)

        # validate should have been called
        mock_validate.assert_called_once()
