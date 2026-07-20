"""Tests for the `disk-usage` CLI subcommand (Plan 00181 Task 5.1).

`disk-usage` is a pure REPORT: it never deletes anything. It surfaces per-writer
accumulation under the daemon untracked dir plus what a `prune-venvs` would
reclaim, so the disk time-bombs this plan bounds are visible on demand.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.daemon import cli


def _mark_self_install(project_root: Path) -> None:
    (project_root / "src" / "claude_code_hooks_daemon").mkdir(parents=True, exist_ok=True)


def _make_venv(path: Path, stamp_version: str) -> None:
    (path / "bin").mkdir(parents=True)
    (path / "bin" / "python").write_text("#!/bin/sh\n")
    (path / ".daemon-version").write_text(stamp_version)


def _args(project_root: Path, *, json_output: bool = False) -> argparse.Namespace:
    return argparse.Namespace(project_root=project_root, json=json_output)


class TestCollectDiskUsage:
    def _untracked(self, tmp_path: Path) -> Path:
        _mark_self_install(tmp_path)
        untracked = tmp_path / "untracked"
        untracked.mkdir()
        return untracked

    def test_reports_writer_dir_sizes(self, tmp_path: Path) -> None:
        untracked = self._untracked(tmp_path)
        tr = untracked / "thread-registry"
        tr.mkdir()
        (tr / "s1.json").write_text("x" * 100)

        rows = cli._collect_disk_usage(tmp_path)

        by_name = {r["name"]: r for r in rows}
        assert "thread-registry" in by_name
        assert by_name["thread-registry"]["size_bytes"] >= 100

    def test_reports_writer_file_sizes(self, tmp_path: Path) -> None:
        untracked = self._untracked(tmp_path)
        supervise = untracked / "supervise"
        supervise.mkdir()
        (supervise / "decision.log").write_text("y" * 250)

        rows = cli._collect_disk_usage(tmp_path)
        by_name = {r["name"]: r for r in rows}
        assert by_name["supervise/decision.log"]["size_bytes"] == 250

    def test_missing_paths_are_zero_not_errors(self, tmp_path: Path) -> None:
        self._untracked(tmp_path)  # empty untracked, no writers
        rows = cli._collect_disk_usage(tmp_path)
        # Every known writer row exists with size 0; no exception raised.
        assert rows
        assert all(r["size_bytes"] == 0 for r in rows)

    def test_venv_row_reports_total_and_reclaimable(self, tmp_path: Path) -> None:
        from claude_code_hooks_daemon.daemon.paths import python_venv_fingerprint

        untracked = self._untracked(tmp_path)
        fp = python_venv_fingerprint(tmp_path)
        _make_venv(untracked / f"venv-{fp}", "v3.7.0")  # current
        _make_venv(untracked / "venv-py310-deadbeef", "v3.6.0")  # reclaimable

        rows = cli._collect_disk_usage(tmp_path)
        venv_row = next(r for r in rows if r["name"] == "venvs")
        assert venv_row["size_bytes"] > 0
        assert venv_row["reclaimable_bytes"] > 0
        # reclaimable is a strict subset of the total (current venv is not reclaimable)
        assert venv_row["reclaimable_bytes"] < venv_row["size_bytes"]


class TestCmdDiskUsage:
    def _untracked(self, tmp_path: Path) -> Path:
        _mark_self_install(tmp_path)
        untracked = tmp_path / "untracked"
        untracked.mkdir()
        return untracked

    def test_json_output_is_valid(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        untracked = self._untracked(tmp_path)
        (untracked / "transcripts").mkdir()
        (untracked / "transcripts" / "t.json").write_text("z" * 50)

        with patch("claude_code_hooks_daemon.daemon.cli.get_project_path", return_value=tmp_path):
            rc = cli.cmd_disk_usage(_args(tmp_path, json_output=True))

        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        names = {row["name"] for row in payload}
        assert "transcripts" in names

    def test_human_output_has_total(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        untracked = self._untracked(tmp_path)
        (untracked / "transcripts").mkdir()
        (untracked / "transcripts" / "t.json").write_text("z" * 50)

        with patch("claude_code_hooks_daemon.daemon.cli.get_project_path", return_value=tmp_path):
            rc = cli.cmd_disk_usage(_args(tmp_path))

        assert rc == 0
        out = capsys.readouterr().out
        assert "TOTAL" in out
        assert "transcripts" in out
