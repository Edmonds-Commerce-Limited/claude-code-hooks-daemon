"""Tests for daemon-start directory-role-rules sync (Plan 00288 Task 5b.2).

The controller's ``initialise`` runs the config-driven rule lifecycle sync,
mirroring the agent-asset sync (Plan 00279): restarting the daemon deploys
any missing/outdated rule and refreshes globs after a layout config change,
without ever clobbering a customised rule file.
"""

from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

import pytest

from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.daemon.controller import DaemonController
from claude_code_hooks_daemon.install.directory_role_rules import (
    PLAN_DIR_RULE_KEY,
    SOURCE_DIRS_RULE_KEY,
    deployed_rule_path,
    spec_by_key,
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


class TestDirectoryRoleRulesSyncOnInitialise:
    def teardown_method(self) -> None:
        ProjectContext.reset()

    def test_unconditional_rule_is_deployed_on_daemon_start(self, tmp_path: Path) -> None:
        workspace = _make_workspace(tmp_path)
        _initialise(workspace)
        assert deployed_rule_path(spec_by_key(SOURCE_DIRS_RULE_KEY), workspace).is_file()

    def test_plan_dir_rule_not_deployed_when_workflow_disabled(self, tmp_path: Path) -> None:
        workspace = _make_workspace(tmp_path)
        _initialise(workspace)
        assert not deployed_rule_path(spec_by_key(PLAN_DIR_RULE_KEY), workspace).exists()

    def test_plan_dir_rule_deployed_when_workflow_enabled(self, tmp_path: Path) -> None:
        workspace = _make_workspace(tmp_path, "plan_workflow:\n  enabled: true\n")
        _initialise(workspace)
        assert deployed_rule_path(spec_by_key(PLAN_DIR_RULE_KEY), workspace).is_file()

    def test_customised_rule_is_never_deleted(self, tmp_path: Path) -> None:
        workspace = _make_workspace(tmp_path)
        spec = spec_by_key(SOURCE_DIRS_RULE_KEY)
        target = deployed_rule_path(spec, workspace)
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
            "claude_code_hooks_daemon.install.directory_role_rules."
            "sync_directory_role_rules_if_enabled",
            _boom,
        )
        controller = _initialise(workspace)
        assert controller.is_initialised
