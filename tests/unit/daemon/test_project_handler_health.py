"""Unit tests for project-handler health-state persistence (Plan 00143).

The running daemon records which project handlers failed to load into a state
file under its untracked dir. The SessionStart alert handler and the
``status``/``health``/``check`` CLI commands read that file to surface a loud,
recurring "protection degraded" signal — instead of the old silent log line.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.daemon import project_handler_health as health
from claude_code_hooks_daemon.handlers.project_loader import ProjectHandlerLoadFailure


@pytest.fixture
def untracked_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the health module's state file at a temp untracked dir."""
    monkeypatch.setattr(
        ProjectContext,
        "daemon_untracked_dir",
        classmethod(lambda cls: tmp_path),
    )
    return tmp_path


def _failures() -> list[ProjectHandlerLoadFailure]:
    return [
        ProjectHandlerLoadFailure(
            filename="branch_naming_enforcer.py",
            event_dir="session_start",
            reason="missing required method get_claude_md (introduced in v2.30.0)",
        ),
        ProjectHandlerLoadFailure(
            filename="phpcs_reminder.py",
            event_dir="post_tool_use",
            reason="missing required method get_claude_md (introduced in v2.30.0)",
        ),
    ]


class TestStateFilePath:
    def test_state_file_under_untracked_dir(self, untracked_dir: Path) -> None:
        path = health.state_file_path()
        assert path.parent == untracked_dir
        assert path.suffix == ".json"
        assert "project-handler" in path.name


class TestWriteAndRead:
    def test_write_then_read_round_trips_failures(self, untracked_dir: Path) -> None:
        failures = _failures()
        health.write_load_failures(failures, loaded_count=1)

        state = health.read_load_failures()
        assert state.is_degraded is True
        assert state.failed_count == 2
        assert state.loaded_count == 1
        # Detail preserved for an actionable alert.
        by_name = {f.filename: f for f in state.failures}
        assert by_name["branch_naming_enforcer.py"].event_dir == "session_start"
        assert "get_claude_md" in by_name["phpcs_reminder.py"].reason

    def test_write_creates_file_on_disk(self, untracked_dir: Path) -> None:
        health.write_load_failures(_failures(), loaded_count=1)
        assert health.state_file_path().exists()

    def test_written_file_is_valid_json(self, untracked_dir: Path) -> None:
        health.write_load_failures(_failures(), loaded_count=3)
        data = json.loads(health.state_file_path().read_text(encoding="utf-8"))
        assert data["failed_count"] == 2
        assert data["loaded_count"] == 3
        assert len(data["failures"]) == 2


class TestHealthyState:
    def test_read_missing_file_is_healthy(self, untracked_dir: Path) -> None:
        state = health.read_load_failures()
        assert state.is_degraded is False
        assert state.failed_count == 0
        assert state.failures == []

    def test_write_empty_failures_does_not_create_file(self, untracked_dir: Path) -> None:
        health.write_load_failures([], loaded_count=8)
        assert not health.state_file_path().exists()

    def test_write_empty_failures_clears_stale_state(self, untracked_dir: Path) -> None:
        """A now-clean daemon erases prior degraded state (always-rewrite)."""
        health.write_load_failures(_failures(), loaded_count=1)
        assert health.state_file_path().exists()

        health.write_load_failures([], loaded_count=8)
        assert not health.state_file_path().exists()
        assert health.read_load_failures().is_degraded is False


class TestClear:
    def test_clear_removes_file(self, untracked_dir: Path) -> None:
        health.write_load_failures(_failures(), loaded_count=1)
        health.clear_load_failures()
        assert not health.state_file_path().exists()

    def test_clear_is_idempotent_when_missing(self, untracked_dir: Path) -> None:
        # Must not raise when there is nothing to clear.
        health.clear_load_failures()
        assert not health.state_file_path().exists()


class TestReadAt:
    """``read_load_failures_at`` reads a given untracked dir directly.

    The CLI uses this to read the daemon's state deterministically without
    depending on ProjectContext singleton initialisation.
    """

    def test_reads_state_from_explicit_dir(self, tmp_path: Path) -> None:
        # Write via the explicit dir (no ProjectContext needed).
        state_file = tmp_path / "project-handler-load-failures.json"
        state_file.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "loaded_count": 2,
                    "failed_count": 1,
                    "failures": [
                        {
                            "filename": "x.py",
                            "event_dir": "pre_tool_use",
                            "reason": "boom",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        state = health.read_load_failures_at(tmp_path)
        assert state.is_degraded is True
        assert state.failed_count == 1
        assert state.failures[0].filename == "x.py"

    def test_missing_dir_reads_healthy(self, tmp_path: Path) -> None:
        state = health.read_load_failures_at(tmp_path / "does_not_exist")
        assert state.is_degraded is False


class TestResilience:
    def test_corrupt_json_reads_as_healthy_with_warning(
        self, untracked_dir: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        health.state_file_path().write_text("{ this is not json", encoding="utf-8")
        with caplog.at_level(logging.WARNING):
            state = health.read_load_failures()
        assert state.is_degraded is False
        assert any("project-handler health" in r.message.lower() for r in caplog.records)
