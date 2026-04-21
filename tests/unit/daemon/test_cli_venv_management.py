"""Tests for Plan 00099 Phase 5 venv-management CLI subcommands.

Covers:
- ``cmd_list_venvs``: enumerate ``venv-*/`` under untracked/, with current-env marker
- ``cmd_prune_venvs``: delete stale venvs with --dry-run/--legacy/--all-except-current
- ``cmd_repair`` migration to ``get_venv_path()`` (fingerprint-keyed)
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from claude_code_hooks_daemon.daemon import cli
from claude_code_hooks_daemon.daemon.paths import get_venv_path, python_venv_fingerprint


def _make_venv(path: Path, stamp_version: str | None = None) -> None:
    """Materialise a fake venv on disk that looks healthy enough for listing."""
    (path / "bin").mkdir(parents=True)
    (path / "bin" / "python").write_text("#!/bin/sh\nexec /usr/bin/python3 \"$@\"\n")
    (path / "bin" / "python").chmod(0o755)
    if stamp_version is not None:
        (path / ".daemon-version").write_text(stamp_version)


def _args(
    project_root: Path,
    *,
    json_output: bool = False,
    legacy: bool = False,
    stale: bool = False,
    all_except_current: bool = False,
    dry_run: bool = False,
    force: bool = False,
) -> argparse.Namespace:
    return argparse.Namespace(
        project_root=project_root,
        json=json_output,
        legacy=legacy,
        stale=stale,
        all_except_current=all_except_current,
        dry_run=dry_run,
        force=force,
    )


class TestListVenvs:
    def test_list_empty_when_no_venvs_exist(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (tmp_path / "untracked").mkdir()

        with patch(
            "claude_code_hooks_daemon.daemon.cli.get_project_path", return_value=tmp_path
        ):
            rc = cli.cmd_list_venvs(_args(tmp_path))

        assert rc == 0
        out = capsys.readouterr().out
        assert "No venvs found" in out

    def test_list_shows_fingerprint_keyed_and_legacy(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        untracked = tmp_path / "untracked"
        untracked.mkdir()
        fp = python_venv_fingerprint()
        _make_venv(untracked / f"venv-{fp}", stamp_version="v3.7.0")
        _make_venv(untracked / "venv-py310-deadbeef", stamp_version="v3.6.0")
        _make_venv(untracked / "venv", stamp_version="v3.5.0")  # legacy pre-fp

        with patch(
            "claude_code_hooks_daemon.daemon.cli.get_project_path", return_value=tmp_path
        ):
            rc = cli.cmd_list_venvs(_args(tmp_path))

        assert rc == 0
        out = capsys.readouterr().out
        assert fp in out
        assert "py310-deadbeef" in out
        assert "v3.7.0" in out
        assert "v3.6.0" in out
        # Current-env marker points at the fp-keyed row, not py310 or legacy
        lines = [ln for ln in out.splitlines() if "←" in ln or "current" in ln.lower()]
        assert any(fp in ln for ln in lines), f"current marker missing for {fp}"

    def test_list_json_mode_emits_machine_readable(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        untracked = tmp_path / "untracked"
        untracked.mkdir()
        fp = python_venv_fingerprint()
        _make_venv(untracked / f"venv-{fp}", stamp_version="v3.7.0")

        with patch(
            "claude_code_hooks_daemon.daemon.cli.get_project_path", return_value=tmp_path
        ):
            rc = cli.cmd_list_venvs(_args(tmp_path, json_output=True))

        assert rc == 0
        out = capsys.readouterr().out
        payload = json.loads(out)
        assert isinstance(payload, list)
        assert len(payload) == 1
        entry = payload[0]
        assert entry["fingerprint"] == fp
        assert entry["stamped_version"] == "v3.7.0"
        assert entry["is_current"] is True
        assert Path(entry["path"]).name == f"venv-{fp}"


class TestPruneVenvs:
    def test_dry_run_lists_but_does_not_delete(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        untracked = tmp_path / "untracked"
        untracked.mkdir()
        fp = python_venv_fingerprint()
        _make_venv(untracked / f"venv-{fp}", stamp_version="v3.7.0")
        stale = untracked / "venv-py310-deadbeef"
        _make_venv(stale, stamp_version="v3.6.0")

        with patch(
            "claude_code_hooks_daemon.daemon.cli.get_project_path", return_value=tmp_path
        ):
            rc = cli.cmd_prune_venvs(
                _args(tmp_path, all_except_current=True, dry_run=True, force=True)
            )

        assert rc == 0
        assert stale.exists()  # not deleted
        out = capsys.readouterr().out
        assert "py310-deadbeef" in out
        assert "dry-run" in out.lower()

    def test_prune_legacy_removes_untracked_venv(self, tmp_path: Path) -> None:
        untracked = tmp_path / "untracked"
        untracked.mkdir()
        fp = python_venv_fingerprint()
        _make_venv(untracked / f"venv-{fp}", stamp_version="v3.7.0")
        legacy = untracked / "venv"
        _make_venv(legacy, stamp_version="v3.5.0")

        with patch(
            "claude_code_hooks_daemon.daemon.cli.get_project_path", return_value=tmp_path
        ):
            rc = cli.cmd_prune_venvs(_args(tmp_path, legacy=True, force=True))

        assert rc == 0
        assert not legacy.exists()
        assert (untracked / f"venv-{fp}").exists()  # current preserved

    def test_prune_all_except_current_keeps_current_fp_venv(self, tmp_path: Path) -> None:
        untracked = tmp_path / "untracked"
        untracked.mkdir()
        fp = python_venv_fingerprint()
        current = untracked / f"venv-{fp}"
        _make_venv(current, stamp_version="v3.7.0")
        other1 = untracked / "venv-py310-deadbeef"
        other2 = untracked / "venv-py312-12345678"
        _make_venv(other1, stamp_version="v3.6.0")
        _make_venv(other2, stamp_version="v3.5.0")

        with patch(
            "claude_code_hooks_daemon.daemon.cli.get_project_path", return_value=tmp_path
        ):
            rc = cli.cmd_prune_venvs(
                _args(tmp_path, all_except_current=True, force=True)
            )

        assert rc == 0
        assert current.exists()
        assert not other1.exists()
        assert not other2.exists()

    def test_prune_refuses_without_force(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Destructive delete requires --force or --dry-run — otherwise abort."""
        untracked = tmp_path / "untracked"
        untracked.mkdir()
        fp = python_venv_fingerprint()
        _make_venv(untracked / f"venv-{fp}", stamp_version="v3.7.0")
        stale = untracked / "venv-py310-deadbeef"
        _make_venv(stale, stamp_version="v3.6.0")

        with patch(
            "claude_code_hooks_daemon.daemon.cli.get_project_path", return_value=tmp_path
        ):
            rc = cli.cmd_prune_venvs(_args(tmp_path, all_except_current=True))

        assert rc == 1
        assert stale.exists()
        captured = capsys.readouterr()
        combined = (captured.out + captured.err).lower()
        assert "force" in combined or "dry-run" in combined

    def test_prune_refuses_to_delete_current_fingerprint(self, tmp_path: Path) -> None:
        """Even with --all-except-current + --force, never touch current-env venv."""
        untracked = tmp_path / "untracked"
        untracked.mkdir()
        fp = python_venv_fingerprint()
        current = untracked / f"venv-{fp}"
        _make_venv(current, stamp_version="v3.7.0")

        with patch(
            "claude_code_hooks_daemon.daemon.cli.get_project_path", return_value=tmp_path
        ):
            rc = cli.cmd_prune_venvs(
                _args(tmp_path, all_except_current=True, force=True)
            )

        assert rc == 0
        assert current.exists()


class TestRepairUsesFingerprintKeyedPath:
    def test_repair_targets_fingerprint_keyed_venv(self, tmp_path: Path) -> None:
        """cmd_repair must provision the venv at get_venv_path(), not untracked/venv."""
        args = argparse.Namespace(project_root=tmp_path)

        expected_venv = get_venv_path(tmp_path)

        sync_call: dict[str, str] = {}

        def fake_run(cmd: list[str], **kw: object) -> MagicMock:
            env = kw.get("env", {})
            if isinstance(env, dict) and env.get("UV_PROJECT_ENVIRONMENT"):
                sync_call["UV_PROJECT_ENVIRONMENT"] = str(
                    env["UV_PROJECT_ENVIRONMENT"]
                )
            m = MagicMock()
            m.returncode = 0
            m.stderr = ""
            m.stdout = "OK\n"
            return m

        with (
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_project_path",
                return_value=tmp_path,
            ),
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=None),
            patch("subprocess.run", side_effect=fake_run),
        ):
            rc = cli.cmd_repair(args)

        assert rc == 0
        assert sync_call["UV_PROJECT_ENVIRONMENT"] == str(expected_venv)
