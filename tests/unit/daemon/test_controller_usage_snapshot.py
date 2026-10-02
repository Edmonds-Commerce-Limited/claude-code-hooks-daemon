"""The controller keeps the usage snapshot from each Status event (Plan 00479 Task 2.1)."""

import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from tests.support.status_usage import load_status_payload

from claude_code_hooks_daemon.config.models import VerdictLogConfig
from claude_code_hooks_daemon.core.data_layer import get_data_layer, reset_data_layer
from claude_code_hooks_daemon.core.event import EventType, HookEvent, HookInput
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.core.usage_snapshot import STATE_FILE_NAME
from claude_code_hooks_daemon.daemon.controller import DaemonController


class TestControllerKeepsUsage:
    def teardown_method(self) -> None:
        ProjectContext.reset()
        reset_data_layer()

    @pytest.fixture
    def controller(self, tmp_path: Path) -> DaemonController:
        workspace = tmp_path / "test-workspace"
        (workspace / ".claude").mkdir(parents=True)
        (workspace / ".claude" / "hooks-daemon.yaml").write_text(
            "version: '1.0'\ndaemon:\n  idle_timeout_seconds: 600\n  log_level: INFO\n"
            "handlers:\n  status_line: {}\n"
        )
        controller = DaemonController()
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                Mock(returncode=0, stdout="/tmp/test\n"),
                Mock(returncode=0, stdout="git@github.com:test/repo.git\n"),
                Mock(returncode=0, stdout="/tmp/test\n"),
            ]
            controller.initialise(
                workspace_root=workspace, verdict_log=VerdictLogConfig(enabled=False)
            )
        return controller

    @staticmethod
    def _status_event(fixture: str) -> HookEvent:
        return HookEvent(
            event_type=EventType.STATUS_LINE,
            hook_input=HookInput(**load_status_payload(fixture)),
        )

    def test_status_event_populates_memory_and_the_host_wide_file(
        self, controller: DaemonController
    ) -> None:
        controller.process_event(self._status_event("main_thread_fractional.json"))

        windows = get_data_layer().usage.latest(now=1_800_000_000.0)
        assert windows is not None and windows.five_hour is not None
        assert windows.five_hour.used_percentage == 67.4
        state_file = ProjectContext.daemon_untracked_dir() / STATE_FILE_NAME
        assert json.loads(state_file.read_text("utf-8"))["seven_day"]["used_percentage"] == 81.9

    def test_status_event_without_usage_keeps_the_previous_reading(
        self, controller: DaemonController
    ) -> None:
        controller.process_event(self._status_event("main_thread_integer.json"))
        controller.process_event(self._status_event("before_first_response.json"))

        windows = get_data_layer().usage.latest(now=1_800_000_000.0)
        assert windows is not None and windows.five_hour is not None
        assert windows.five_hour.used_percentage == 13.0
