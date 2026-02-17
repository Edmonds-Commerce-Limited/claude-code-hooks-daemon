"""Integration test for plugin loading in DaemonController."""

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from claude_code_hooks_daemon.config.models import PluginConfig, PluginsConfig
from claude_code_hooks_daemon.core.event import EventType
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.daemon.controller import DaemonController


class TestPluginLoading:
    """Test plugin loading integration."""

    def teardown_method(self) -> None:
        """Reset ProjectContext after each test."""
        ProjectContext.reset()

    def test_load_real_plugin(self, tmp_path: Path) -> None:
        """Load a real plugin file and verify it's registered."""
        # Create a real plugin file
        plugin_file = tmp_path / "my_test_plugin.py"
        plugin_file.write_text('''"""Test plugin."""
from typing import Any
from claude_code_hooks_daemon.core import Handler, HookResult, Decision
from claude_code_hooks_daemon.constants import HandlerID, Priority


class MyTestPlugin(Handler):
    """Simple test plugin."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.DESTRUCTIVE_GIT,
            priority=Priority.DESTRUCTIVE_GIT,
            terminal=False,
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        return hook_input.get("tool_name") == "TestTool"

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        return HookResult(decision=Decision.DENY, reason="Test plugin blocked this")

    def get_acceptance_tests(self) -> list:
        return []
''')

        # Create plugins config pointing to the real file
        plugins_config = PluginsConfig(
            enabled=True,
            plugins=[
                PluginConfig(
                    path=str(plugin_file),
                    event_type="pre_tool_use",  # snake_case as per config
                    enabled=True,
                )
            ],
        )

        # Create workspace structure
        workspace_root = tmp_path / "workspace"
        workspace_root.mkdir()
        claude_dir = workspace_root / ".claude"
        claude_dir.mkdir()

        # Create config file (required by ProjectContext.initialize)
        config_file = claude_dir / "hooks-daemon.yaml"
        config_file.write_text("version: '1.0'\n")

        # Initialize controller with plugin
        controller = DaemonController()

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                Mock(returncode=0, stdout=str(workspace_root).encode() + b"\n"),
                Mock(returncode=0, stdout=b"git@github.com:test/repo.git\n"),
                Mock(returncode=0, stdout=str(workspace_root).encode() + b"\n"),
            ]
            controller.initialise(workspace_root=workspace_root, plugins_config=plugins_config)

        # Verify plugin was loaded
        assert controller.is_initialised

        # Check that the plugin handler is registered
        handlers = controller._router.get_chain(EventType.PRE_TOOL_USE).handlers
        plugin_handler = next((h for h in handlers if h.__class__.__name__ == "MyTestPlugin"), None)

        assert plugin_handler is not None, "Plugin handler should be registered"
        assert plugin_handler.name == "prevent-destructive-git"  # From HandlerID.DESTRUCTIVE_GIT

    def test_load_plugin_with_handler_suffix(self, tmp_path: Path) -> None:
        """Test plugin with Handler suffix in class name (documented convention).

        Regression test for bug: Plugin handlers with Handler suffix are silently
        skipped because DaemonController only checks base class name without suffix.

        PluginLoader.load_handler() correctly handles the suffix (tries both variants),
        but DaemonController._load_plugins() only checks the base name.
        """
        # Create plugin with Handler suffix (the documented convention)
        plugin_file = tmp_path / "system_paths.py"
        plugin_file.write_text('''"""System paths protection plugin."""
from typing import Any
from claude_code_hooks_daemon.core import Handler, HookResult, Decision
from claude_code_hooks_daemon.constants import HandlerID, Priority


class SystemPathsHandler(Handler):
    """Blocks edits to system configuration files."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.DESTRUCTIVE_GIT,
            priority=Priority.DESTRUCTIVE_GIT,
            terminal=True,
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        return hook_input.get("tool_name") == "Edit"

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        return HookResult(decision=Decision.DENY, reason="System file blocked")

    def get_acceptance_tests(self) -> list:
        return []
''')

        plugins_config = PluginsConfig(
            enabled=True,
            plugins=[
                PluginConfig(
                    path=str(plugin_file),
                    event_type="pre_tool_use",
                    enabled=True,
                )
            ],
        )

        workspace_root = tmp_path / "workspace"
        workspace_root.mkdir()
        claude_dir = workspace_root / ".claude"
        claude_dir.mkdir()
        config_file = claude_dir / "hooks-daemon.yaml"
        config_file.write_text("version: '1.0'\n")

        controller = DaemonController()

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                Mock(returncode=0, stdout=str(workspace_root).encode() + b"\n"),
                Mock(returncode=0, stdout=b"git@github.com:test/repo.git\n"),
                Mock(returncode=0, stdout=str(workspace_root).encode() + b"\n"),
            ]
            controller.initialise(workspace_root=workspace_root, plugins_config=plugins_config)

        # Verify plugin with Handler suffix was loaded and registered
        assert controller.is_initialised
        handlers = controller._router.get_chain(EventType.PRE_TOOL_USE).handlers
        plugin_handler = next(
            (h for h in handlers if h.__class__.__name__ == "SystemPathsHandler"), None
        )

        assert plugin_handler is not None, (
            "Plugin handler with Handler suffix should be registered. "
            "Bug: DaemonController._load_plugins() only checks base class name "
            "without Handler suffix, while PluginLoader.load_handler() correctly "
            "handles the suffix."
        )

    def test_daemon_crashes_on_unmatched_plugin_handler(self, tmp_path: Path) -> None:
        """Test daemon CRASHES (not warns) if plugin handler can't be matched to config.

        FAIL FAST: If a configured handler can't be registered, daemon MUST crash.
        Current behaviour: Logs warning and continues (silently disables protection).
        Expected behaviour: Raise RuntimeError with clear error message.
        """
        # Create plugin that will load but can't be matched back to config
        # This simulates a mismatch between loaded class name and expected class name
        plugin_file = tmp_path / "weird_name.py"
        plugin_file.write_text('''"""Plugin with non-standard class name."""
from typing import Any
from claude_code_hooks_daemon.core import Handler, HookResult, Decision
from claude_code_hooks_daemon.constants import HandlerID, Priority


class CompletelyDifferentClassName(Handler):
    """Class name doesn't match module name at all."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.DESTRUCTIVE_GIT,
            priority=Priority.DESTRUCTIVE_GIT,
            terminal=True,
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        return False

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        return HookResult(decision=Decision.ALLOW, reason="")

    def get_acceptance_tests(self) -> list:
        return []
''')

        plugins_config = PluginsConfig(
            enabled=True,
            plugins=[
                PluginConfig(
                    path=str(plugin_file),
                    event_type="pre_tool_use",
                    enabled=True,
                )
            ],
        )

        workspace_root = tmp_path / "workspace"
        workspace_root.mkdir()
        claude_dir = workspace_root / ".claude"
        claude_dir.mkdir()
        config_file = claude_dir / "hooks-daemon.yaml"
        config_file.write_text("version: '1.0'\n")

        controller = DaemonController()

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                Mock(returncode=0, stdout=str(workspace_root).encode() + b"\n"),
                Mock(returncode=0, stdout=b"git@github.com:test/repo.git\n"),
                Mock(returncode=0, stdout=str(workspace_root).encode() + b"\n"),
            ]
            # Daemon MUST crash if configured handler can't be registered
            with pytest.raises(RuntimeError, match="Failed to load plugin handler"):
                controller.initialise(workspace_root=workspace_root, plugins_config=plugins_config)
