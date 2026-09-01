"""Tests for the config-optimisation last-run state module (Plan 00308).

Follows the same JSON-sidecar-under-daemon-untracked-dir pattern as
``skill_scan.state``: missing or corrupt state is treated as "never run",
write failures are logged and swallowed, never raised.
"""

from __future__ import annotations

import json
from pathlib import Path

from claude_code_hooks_daemon.config_optimisation.state import (
    STATE_FILE_NAME,
    load_state,
    record_run,
)


class TestLoadState:
    def test_missing_file_yields_never_run(self, tmp_path: Path) -> None:
        state = load_state(tmp_path / STATE_FILE_NAME)
        assert state.last_run_version is None
        assert state.last_run_at is None

    def test_corrupt_file_yields_never_run(self, tmp_path: Path) -> None:
        path = tmp_path / STATE_FILE_NAME
        path.write_text("{not json")
        state = load_state(path)
        assert state.last_run_version is None

    def test_non_dict_json_yields_never_run(self, tmp_path: Path) -> None:
        path = tmp_path / STATE_FILE_NAME
        path.write_text(json.dumps(["not", "a", "dict"]))
        state = load_state(path)
        assert state.last_run_version is None

    def test_reads_recorded_values(self, tmp_path: Path) -> None:
        path = tmp_path / STATE_FILE_NAME
        record_run(path, version="3.58.1", now=1000.0)
        state = load_state(path)
        assert state.last_run_version == "3.58.1"
        assert state.last_run_at == 1000.0


class TestRecordRun:
    def test_creates_parent_dir(self, tmp_path: Path) -> None:
        path = tmp_path / "nested" / STATE_FILE_NAME
        record_run(path, version="3.58.1", now=1000.0)
        assert path.exists()

    def test_overwrites_prior_run(self, tmp_path: Path) -> None:
        path = tmp_path / STATE_FILE_NAME
        record_run(path, version="3.58.0", now=500.0)
        record_run(path, version="3.58.1", now=1000.0)
        state = load_state(path)
        assert state.last_run_version == "3.58.1"
        assert state.last_run_at == 1000.0

    def test_write_failure_is_swallowed(self, tmp_path: Path) -> None:
        # Parent path collides with a file, so mkdir must fail — record_run
        # must not raise.
        blocker = tmp_path / "blocker"
        blocker.write_text("not a dir")
        path = blocker / STATE_FILE_NAME
        record_run(path, version="3.58.1", now=1000.0)  # must not raise
