"""Tests for the ``record-config-optimisation-run`` CLI subcommand (Plan 00308)."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from claude_code_hooks_daemon.config_optimisation.state import STATE_FILE_NAME, load_state
from claude_code_hooks_daemon.daemon.cli import cmd_record_config_optimisation_run
from claude_code_hooks_daemon.version import __version__


class TestCmdRecordConfigOptimisationRun:
    def test_records_current_version(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        args = argparse.Namespace(project_root=tmp_path)
        exit_code = cmd_record_config_optimisation_run(args)
        assert exit_code == 0

        state_path = tmp_path / ".claude" / "hooks-daemon" / "untracked" / STATE_FILE_NAME
        state = load_state(state_path)
        assert state.last_run_version == __version__
        assert state.last_run_at is not None

        out = capsys.readouterr().out
        assert __version__ in out

    def test_overwrites_prior_recorded_run(self, tmp_path: Path) -> None:
        from claude_code_hooks_daemon.config_optimisation.state import record_run

        state_path = tmp_path / ".claude" / "hooks-daemon" / "untracked" / STATE_FILE_NAME
        record_run(state_path, version="0.0.1", now=1.0)

        args = argparse.Namespace(project_root=tmp_path)
        cmd_record_config_optimisation_run(args)

        state = load_state(state_path)
        assert state.last_run_version == __version__
