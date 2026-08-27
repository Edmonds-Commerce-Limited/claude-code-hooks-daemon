"""Tests for daemon-start agent-asset sync (Plan 00279 Task 2.1).

The controller's ``initialise`` runs the config-driven agent lifecycle sync so
that enabling a gating key + restarting the daemon deploys the agent, and
disabling it surfaces a removal advisory in the daemon log — never a silent
delete.
"""

from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

import pytest

from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.daemon.controller import DaemonController
from claude_code_hooks_daemon.install.agent_assets import (
    OPUS_SECURITY_AGENT_NAME,
    deployed_agent_path,
    spec_by_name,
)

_BASE_YAML = "version: '1.0'\nhandlers:\n  pre_tool_use: {}\n"


def _make_workspace(tmp_path: Path, extra_yaml: str = "") -> Path:
    workspace = tmp_path / "test-workspace"
    claude_dir = workspace / ".claude"
    claude_dir.mkdir(parents=True)
    (claude_dir / "hooks-daemon.yaml").write_text(_BASE_YAML + extra_yaml)
    return workspace


def _initialise(workspace: Path) -> DaemonController:
    controller = DaemonController()

    def _fake_run(*_args: Any, **_kwargs: Any) -> Mock:
        return Mock(returncode=0, stdout=f"{workspace}\n")

    with patch("subprocess.run", side_effect=_fake_run):
        controller.initialise(workspace_root=workspace)
    return controller


class TestAgentSyncOnInitialise:
    def teardown_method(self) -> None:
        ProjectContext.reset()

    def test_enabled_agent_is_deployed_on_daemon_start(self, tmp_path: Path) -> None:
        workspace = _make_workspace(tmp_path, "agents:\n  opus_security:\n    enabled: true\n")
        _initialise(workspace)
        assert deployed_agent_path(spec_by_name(OPUS_SECURITY_AGENT_NAME), workspace).is_file()

    def test_disabled_present_agent_is_never_deleted(self, tmp_path: Path) -> None:
        workspace = _make_workspace(tmp_path)
        spec = spec_by_name(OPUS_SECURITY_AGENT_NAME)
        target = deployed_agent_path(spec, workspace)
        target.parent.mkdir(parents=True)
        target.write_text("anything\n")
        _initialise(workspace)
        assert target.read_text() == "anything\n"

    def test_sync_failure_does_not_break_daemon_start(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        workspace = _make_workspace(tmp_path)

        def _boom(project_root: Path, config_path: Path) -> None:
            raise OSError("disk on fire")

        monkeypatch.setattr(
            "claude_code_hooks_daemon.install.agent_assets.deploy_agents_if_enabled",
            _boom,
        )
        controller = _initialise(workspace)
        assert controller.is_initialised
