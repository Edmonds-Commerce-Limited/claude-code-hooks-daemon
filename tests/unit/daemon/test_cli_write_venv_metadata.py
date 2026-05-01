"""Tests for the ``write-venv-metadata`` CLI subcommand.

Plan 00100 Task 3.3: bash-side ``ensure_venv`` shells out to this command
after ``uv sync`` succeeds, so metadata is written atomically through the
Python SSOT rather than reimplementing the schema in bash.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.daemon import cli
from claude_code_hooks_daemon.daemon.metadata import (
    DaemonVenvMetadata,
    read_daemon_metadata,
)


def _make_args(
    venv_path: Path,
    *,
    fingerprint: str = "workspace-py311-2fa8b3c1",
    daemon_version: str = "v3.9.0",
    project_root: Path | None = None,
) -> argparse.Namespace:
    return argparse.Namespace(
        venv_path=str(venv_path),
        fingerprint=fingerprint,
        daemon_version=daemon_version,
        project_root=str(project_root) if project_root else None,
    )


def _seed_venv(path: Path) -> None:
    (path / "bin").mkdir(parents=True)
    (path / "bin" / "python").write_text('#!/bin/sh\nexec python3 "$@"\n')
    (path / "bin" / "python").chmod(0o755)


class TestWriteVenvMetadataCommand:
    def test_writes_valid_metadata_file(self, tmp_path: Path) -> None:
        venv = tmp_path / "venv-workspace-py311-2fa8b3c1"
        _seed_venv(venv)
        (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n")

        rc = cli.cmd_write_venv_metadata(_make_args(venv, project_root=tmp_path))
        assert rc == 0

        meta = read_daemon_metadata(venv)
        assert meta is not None
        assert isinstance(meta, DaemonVenvMetadata)
        assert meta.fingerprint == "workspace-py311-2fa8b3c1"
        assert meta.daemon_version == "v3.9.0"
        # Plan 00104 Issue #4: contract is the absolute, *unresolved*
        # venv path — see test_python_path_records_venv_path_not_resolved_base.
        assert meta.python_path == str(venv / "bin" / "python")
        assert meta.lock_hash.startswith("sha256:")

    def test_command_is_idempotent(self, tmp_path: Path) -> None:
        """Re-running overwrites prior metadata (atomic replace)."""
        venv = tmp_path / "venv-workspace-py311-2fa8b3c1"
        _seed_venv(venv)
        (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n")

        cli.cmd_write_venv_metadata(_make_args(venv, project_root=tmp_path))
        cli.cmd_write_venv_metadata(_make_args(venv, project_root=tmp_path))
        meta = read_daemon_metadata(venv)
        assert meta is not None

    def test_fails_when_venv_path_missing(self, tmp_path: Path) -> None:
        """Bail early with a non-zero rc when the venv dir does not exist."""
        nonexistent = tmp_path / "no_such_venv"
        with patch.object(cli, "get_project_path", return_value=tmp_path):
            rc = cli.cmd_write_venv_metadata(_make_args(nonexistent, project_root=tmp_path))
        assert rc != 0

    def test_fails_when_no_python_binary(self, tmp_path: Path) -> None:
        """No bin/python → cannot stamp python_path → fail."""
        venv = tmp_path / "venv-workspace-py311-2fa8b3c1"
        venv.mkdir()
        (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n")
        rc = cli.cmd_write_venv_metadata(_make_args(venv, project_root=tmp_path))
        assert rc != 0

    def test_project_root_defaults_to_cwd(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Without --project-root, cwd is used for lock-hash computation."""
        venv = tmp_path / "venv-workspace-py311-2fa8b3c1"
        _seed_venv(venv)
        (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n")

        monkeypatch.chdir(tmp_path)
        rc = cli.cmd_write_venv_metadata(_make_args(venv, project_root=None))
        assert rc == 0
        assert read_daemon_metadata(venv) is not None

    def test_writes_file_atomically_via_tmp(self, tmp_path: Path) -> None:
        """After success no ``.tmp`` sidecar remains inside the venv."""
        venv = tmp_path / "venv-workspace-py311-2fa8b3c1"
        _seed_venv(venv)
        (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n")
        cli.cmd_write_venv_metadata(_make_args(venv, project_root=tmp_path))
        assert list(venv.glob(".daemon-metadata.json.tmp")) == []

    def test_written_file_is_valid_json(self, tmp_path: Path) -> None:
        venv = tmp_path / "venv-workspace-py311-2fa8b3c1"
        _seed_venv(venv)
        (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n")
        cli.cmd_write_venv_metadata(_make_args(venv, project_root=tmp_path))
        raw = (venv / ".daemon-metadata.json").read_text()
        assert isinstance(json.loads(raw), dict)

    def test_python_path_records_venv_path_not_resolved_base(self, tmp_path: Path) -> None:
        """Plan 00104 Issue #4: regression test for cli.py:1415 .resolve() bug.

        On a real fingerprint-keyed venv, bin/python is a symlink chain:

            bin/python      -> python3
            bin/python3     -> /usr/bin/python3
            bin/python3.11  -> python3

        Path.resolve() follows the chain and returns the BASE interpreter
        (/usr/bin/python3.11), NOT the venv's own bin/python. The bug
        caused .daemon-metadata.json to record the system Python; skill
        scripts then ran daemon code under that interpreter, which has no
        daemon packages installed → ModuleNotFoundError.

        The fix is to NOT call .resolve(): record str(python_binary), which
        is already absolute (constructed from --venv-path).

        This test reproduces the exact symlink topology the field bug had.
        """
        # Use real /usr/bin/python3 as the symlink-chain target —
        # mimicking how `python -m venv` constructs its bin/python.
        base_interpreter = Path("/usr/bin/python3")
        if not base_interpreter.exists():
            pytest.skip("requires /usr/bin/python3 (Linux test environment)")

        venv = tmp_path / "venv-workspace-py311-2fa8b3c1"
        (venv / "bin").mkdir(parents=True)
        # Reproduce the 3-link chain seen on a real venv.
        (venv / "bin" / "python3").symlink_to(base_interpreter)
        (venv / "bin" / "python").symlink_to("python3")
        (venv / "bin" / "python3.11").symlink_to("python3")
        (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n")

        # Sanity: confirm the test fixture reproduces the bug topology.
        assert (venv / "bin" / "python").resolve() != (venv / "bin" / "python")
        assert (venv / "bin" / "python").resolve() == base_interpreter.resolve()

        rc = cli.cmd_write_venv_metadata(_make_args(venv, project_root=tmp_path))
        assert rc == 0

        meta = read_daemon_metadata(venv)
        assert meta is not None
        # The recorded python_path MUST be the venv's own bin/python,
        # NOT the base interpreter that .resolve() would follow to.
        assert meta.python_path == str(venv / "bin" / "python"), (
            f"python_path was {meta.python_path!r}; "
            f"expected {str(venv / 'bin' / 'python')!r}. "
            f"If this is /usr/bin/python3.x then cli.py:1415 still calls "
            f".resolve() — the Plan 00104 Issue #4 fix has regressed."
        )
