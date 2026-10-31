"""Plan 00555 DBF: every judgement of a venv interpreter goes through the one gate.

A venv whose ``pyvenv.cfg`` records another ``major.minor`` than its
``bin/python`` now runs is the incident: it starts, and cannot see its own
site-packages. These tests pin that ``venv_interpreter_usable`` refuses it and
that freshness, the venv-metadata writer, the live-venv set, the resolver and
``repair`` all agree.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.daemon import cli
from claude_code_hooks_daemon.daemon import paths as paths_mod
from claude_code_hooks_daemon.daemon.paths import (
    CHECK_VENV_FRESH_EXIT_STALE,
    _cli_check_venv_fresh,
    fingerprint_major_minor,
    live_venv_realpaths,
    resolve_existing_venv_python,
    venv_interpreter_usable,
)

_RUNNING = (sys.version_info.major, sys.version_info.minor)
_OTHER = (_RUNNING[0], _RUNNING[1] + 1 if _RUNNING[1] < 50 else _RUNNING[1] - 1)


def _venv(venv_dir: Path, cfg_version: tuple[int, int]) -> Path:
    """A venv whose ``bin/python`` is the running interpreter, with a recorded version."""
    (venv_dir / "bin").mkdir(parents=True)
    py = venv_dir / "bin" / "python"
    py.symlink_to(os.path.realpath(sys.executable))
    (venv_dir / "pyvenv.cfg").write_text(f"version_info = {cfg_version[0]}.{cfg_version[1]}.5\n")
    return py


def _lock_hash(daemon_dir: Path) -> str:
    (daemon_dir / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    digest = hashlib.sha256()
    digest.update((daemon_dir / "pyproject.toml").read_bytes())
    digest.update(b"\x00no-uv-lock\x00")
    return f"sha256:{digest.hexdigest()}"


class TestFingerprintMajorMinor:
    @pytest.mark.parametrize(
        ("fingerprint", "expected"),
        [
            ("py313-956ed987", (3, 13)),
            ("workspace-py311-2fa8b3c1", (3, 11)),
            ("py39-3bb0ae3d", (3, 9)),
            ("nonsense", None),
            ("py313-zzzzzzzz", None),
        ],
    )
    def test_parses_the_py_tag(self, fingerprint: str, expected: tuple[int, int] | None) -> None:
        assert fingerprint_major_minor(fingerprint) == expected


class TestCheckVenvFreshFollowsTheGate:
    """Matching lock_hash is not freshness when the interpreter drifted."""

    @staticmethod
    def _run(daemon_dir: Path, venv: Path) -> int:
        args = argparse.Namespace(venv_path=str(venv), daemon_dir=str(daemon_dir))
        return _cli_check_venv_fresh(args)

    def _fresh_venv(self, tmp_path: Path, cfg_version: tuple[int, int]) -> tuple[Path, Path]:
        daemon_dir = tmp_path / "d"
        daemon_dir.mkdir()
        venv = daemon_dir / "untracked" / "venv-py311-abcdef12"
        py = _venv(venv, cfg_version)
        (venv / ".daemon-metadata.json").write_text(
            json.dumps({"python_path": str(py), "lock_hash": _lock_hash(daemon_dir)})
        )
        return daemon_dir, venv

    def test_matching_interpreter_is_fresh(self, tmp_path: Path) -> None:
        daemon_dir, venv = self._fresh_venv(tmp_path, _RUNNING)
        assert self._run(daemon_dir, venv) == 0

    def test_drifted_interpreter_is_stale_despite_matching_lock(self, tmp_path: Path) -> None:
        daemon_dir, venv = self._fresh_venv(tmp_path, _OTHER)
        assert self._run(daemon_dir, venv) == CHECK_VENV_FRESH_EXIT_STALE


class TestWriteVenvMetadataFollowsTheGate:
    def test_refuses_a_drifted_venv(self, tmp_path: Path) -> None:
        daemon_dir = tmp_path / "d"
        daemon_dir.mkdir()
        _lock_hash(daemon_dir)
        venv = daemon_dir / "untracked" / "venv-py311-abcdef12"
        _venv(venv, _OTHER)

        error = cli._write_venv_metadata(venv, "py311-abcdef12", "v1.2.3", daemon_dir)

        assert error is not None and "unusable" in error
        assert not (venv / ".daemon-metadata.json").exists()

    def test_stamps_a_matching_venv(self, tmp_path: Path) -> None:
        daemon_dir = tmp_path / "d"
        daemon_dir.mkdir()
        _lock_hash(daemon_dir)
        venv = daemon_dir / "untracked" / "venv-py311-abcdef12"
        _venv(venv, _RUNNING)

        assert cli._write_venv_metadata(venv, "py311-abcdef12", "v1.2.3", daemon_dir) is None


class TestResolverAndLiveSetFollowTheGate:
    def test_keyed_drifted_venv_is_not_returned_first(self, tmp_path: Path) -> None:
        daemon_dir = tmp_path / "d"
        daemon_dir.mkdir()
        keyed = (
            daemon_dir
            / "untracked"
            / f"venv-{paths_mod.python_venv_fingerprint(daemon_dir)}"
            / "bin"
            / "python"
        )
        _venv(keyed.parent.parent, _OTHER)
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("HOOKS_DAEMON_VENV_PATH", None)
            resolved = resolve_existing_venv_python(daemon_dir)

        assert resolved != keyed

    def test_drifted_venv_is_not_live(self, tmp_path: Path) -> None:
        daemon_dir = tmp_path / "d"
        daemon_dir.mkdir()
        drifted = tmp_path / "ven"
        _venv(drifted, _OTHER)
        with patch.dict(os.environ, {"HOOKS_DAEMON_VENV_PATH": str(drifted)}):
            live = live_venv_realpaths(daemon_dir)

        assert drifted.resolve() not in live


class TestRepairVerifiesTheBuiltMinor:
    """``uv sync`` may build another minor than the fingerprint's tag names."""

    def _repair(self, venv: Path) -> int:
        done = subprocess.CompletedProcess(args=["uv"], returncode=0, stdout="", stderr="")
        with (
            patch.object(cli, "find_uv", return_value="uv"),
            patch("claude_code_hooks_daemon.daemon.cli.subprocess.run", return_value=done),
            patch.object(cli, "_record_repaired_venv_lock"),
        ):
            return cli._repair_venv_locked(venv.parent.parent, venv, {})

    def test_other_minor_than_the_fingerprint_is_not_a_repair(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        tag = f"py{_RUNNING[0]}{_RUNNING[1]}"
        venv = tmp_path / "d" / "untracked" / f"venv-{tag}-abcdef12"
        _venv(venv, _OTHER)

        assert self._repair(venv) == 1
        assert "fingerprint names Python" in capsys.readouterr().out

    def test_same_minor_as_the_fingerprint_is_repaired(self, tmp_path: Path) -> None:
        tag = f"py{_RUNNING[0]}{_RUNNING[1]}"
        venv = tmp_path / "d" / "untracked" / f"venv-{tag}-abcdef12"
        _venv(venv, _RUNNING)

        assert self._repair(venv) == 0


def test_the_gate_itself_refuses_drift(tmp_path: Path) -> None:
    assert venv_interpreter_usable(_venv(tmp_path / "ok", _RUNNING)) is True
    assert venv_interpreter_usable(_venv(tmp_path / "bad", _OTHER)) is False
    assert venv_interpreter_usable(tmp_path / "missing" / "bin" / "python") is False


def test_the_gate_refuses_a_missing_interpreter_without_launching_it(tmp_path: Path) -> None:
    """``cmd_start`` enumerates candidate venvs on every start; one that is not
    there is unusable, and probing it would spawn a process for nothing."""
    with patch.object(subprocess, "run") as run:
        assert venv_interpreter_usable(tmp_path / "missing" / "bin" / "python") is False
        dangling = tmp_path / "dangling" / "bin" / "python"
        dangling.parent.mkdir(parents=True)
        dangling.symlink_to(tmp_path / "gone" / "python3.11")
        assert venv_interpreter_usable(dangling) is False
    run.assert_not_called()
