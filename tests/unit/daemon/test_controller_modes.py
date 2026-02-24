"""Tests for DaemonController mode integration."""

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from claude_code_hooks_daemon.constants.modes import DaemonMode, ModeConstant
from claude_code_hooks_daemon.core.event import EventType, HookEvent
from claude_code_hooks_daemon.core.hook_result import Decision
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.daemon.controller import DaemonController


def _make_stop_event(stop_hook_active: bool = False) -> HookEvent:
    """Create a Stop hook event for testing."""
    return HookEvent(
        event=EventType.STOP.value,
        hook_input={"stop_hook_active": stop_hook_active},
    )


def _make_pre_tool_use_event() -> HookEvent:
    """Create a PreToolUse hook event for testing."""
    return HookEvent(
        event=EventType.PRE_TOOL_USE.value,
        hook_input={"tool_name": "Bash", "tool_input": {"command": "echo hi"}},
    )


@pytest.fixture
def workspace_root(tmp_path: Path) -> Path:
    """Create a workspace root with config file for testing."""
    workspace = tmp_path / "test-workspace"
    claude_dir = workspace / ".claude"
    claude_dir.mkdir(parents=True)
    config_file = claude_dir / "hooks-daemon.yaml"
    config_file.write_text(
        "version: '1.0'\n"
        "daemon:\n"
        "  idle_timeout_seconds: 600\n"
        "  log_level: INFO\n"
        "handlers:\n"
        "  pre_tool_use: {}\n"
    )
    return workspace


def _init_controller(
    workspace_root: Path,
    mode: DaemonMode = DaemonMode.DEFAULT,
    custom_message: str | None = None,
) -> DaemonController:
    """Create and initialise a DaemonController with mocked git.

    Args:
        workspace_root: Workspace root with .claude/hooks-daemon.yaml.
        mode: Daemon mode to set after init.
        custom_message: Optional custom message.

    Returns:
        Initialized DaemonController.
    """
    controller = DaemonController()
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = Mock(
            returncode=0,
            stdout=str(workspace_root).encode() + b"\n",
        )
        controller.initialise(workspace_root=workspace_root)
    if mode != DaemonMode.DEFAULT or custom_message is not None:
        controller.set_mode(mode, custom_message=custom_message)
    return controller


class TestControllerModeInit:
    """Tests for mode initialization in DaemonController."""

    def teardown_method(self) -> None:
        """Reset ProjectContext after each test."""
        ProjectContext.reset()

    def test_default_mode_manager_exists(self) -> None:
        controller = DaemonController()
        assert controller.get_mode() is not None

    def test_default_mode_is_default(self) -> None:
        controller = DaemonController()
        mode_info = controller.get_mode()
        assert mode_info[ModeConstant.KEY_MODE] == DaemonMode.DEFAULT.value

    def test_mode_from_config(self) -> None:
        """Controller should read default_mode from config."""
        from claude_code_hooks_daemon.config.models import DaemonConfig

        config = DaemonConfig(default_mode="unattended")
        controller = DaemonController(config=config)
        mode_info = controller.get_mode()
        assert mode_info[ModeConstant.KEY_MODE] == DaemonMode.UNATTENDED.value

    def test_invalid_config_mode_uses_default(self) -> None:
        """Invalid mode in config should fall back to default."""
        from claude_code_hooks_daemon.config.models import DaemonConfig

        config = DaemonConfig(default_mode="bogus")
        controller = DaemonController(config=config)
        mode_info = controller.get_mode()
        assert mode_info[ModeConstant.KEY_MODE] == DaemonMode.DEFAULT.value


class TestControllerSetMode:
    """Tests for set_mode on DaemonController."""

    def teardown_method(self) -> None:
        """Reset ProjectContext after each test."""
        ProjectContext.reset()

    def test_set_unattended(self) -> None:
        controller = DaemonController()
        result = controller.set_mode(DaemonMode.UNATTENDED)
        assert result is True
        mode_info = controller.get_mode()
        assert mode_info[ModeConstant.KEY_MODE] == DaemonMode.UNATTENDED.value

    def test_set_default(self) -> None:
        controller = DaemonController()
        controller.set_mode(DaemonMode.UNATTENDED)
        result = controller.set_mode(DaemonMode.DEFAULT)
        assert result is True
        mode_info = controller.get_mode()
        assert mode_info[ModeConstant.KEY_MODE] == DaemonMode.DEFAULT.value

    def test_set_mode_with_message(self) -> None:
        controller = DaemonController()
        controller.set_mode(DaemonMode.UNATTENDED, custom_message="do the thing")
        mode_info = controller.get_mode()
        assert mode_info[ModeConstant.KEY_CUSTOM_MESSAGE] == "do the thing"


class TestControllerModeIntercept:
    """Tests for mode interception in process_event."""

    def teardown_method(self) -> None:
        """Reset ProjectContext after each test."""
        ProjectContext.reset()

    def test_default_mode_does_not_intercept_stop(self, workspace_root: Path) -> None:
        """In default mode, Stop events should reach handlers normally."""
        controller = _init_controller(workspace_root)
        event = _make_stop_event()
        result = controller.process_event(event)
        # In default mode, result should come from handler chain (allow)
        assert result.result.decision != Decision.DENY or "UNATTENDED" not in (
            result.result.reason or ""
        )

    def test_unattended_mode_blocks_stop(self, workspace_root: Path) -> None:
        """In unattended mode, Stop events should be blocked before handlers."""
        controller = _init_controller(workspace_root, mode=DaemonMode.UNATTENDED)
        event = _make_stop_event()
        result = controller.process_event(event)
        assert result.result.decision == Decision.DENY
        assert "UNATTENDED" in (result.result.reason or "")

    def test_unattended_mode_does_not_intercept_pre_tool_use(self, workspace_root: Path) -> None:
        """Unattended mode should not affect PreToolUse events."""
        controller = _init_controller(workspace_root, mode=DaemonMode.UNATTENDED)
        event = _make_pre_tool_use_event()
        result = controller.process_event(event)
        # Should not have UNATTENDED in reason - it went through normal handlers
        assert "UNATTENDED" not in (result.result.reason or "")

    def test_unattended_mode_respects_reentry(self, workspace_root: Path) -> None:
        """Stop events with stop_hook_active should not be intercepted."""
        controller = _init_controller(workspace_root, mode=DaemonMode.UNATTENDED)
        event = _make_stop_event(stop_hook_active=True)
        result = controller.process_event(event)
        # Re-entry: should NOT have unattended block
        assert "UNATTENDED" not in (result.result.reason or "")

    def test_unattended_mode_with_custom_message(self, workspace_root: Path) -> None:
        """Custom message should appear in block reason."""
        controller = _init_controller(
            workspace_root,
            mode=DaemonMode.UNATTENDED,
            custom_message="finish release",
        )
        event = _make_stop_event()
        result = controller.process_event(event)
        assert result.result.decision == Decision.DENY
        assert "finish release" in (result.result.reason or "")


class TestControllerHealthIncludesMode:
    """Tests for mode in health output."""

    def teardown_method(self) -> None:
        """Reset ProjectContext after each test."""
        ProjectContext.reset()

    def test_health_includes_mode(self) -> None:
        controller = DaemonController()
        health = controller.get_health()
        assert ModeConstant.KEY_MODE in health
        assert health[ModeConstant.KEY_MODE] == DaemonMode.DEFAULT.value

    def test_health_shows_unattended(self) -> None:
        controller = DaemonController()
        controller.set_mode(DaemonMode.UNATTENDED)
        health = controller.get_health()
        assert health[ModeConstant.KEY_MODE] == DaemonMode.UNATTENDED.value
