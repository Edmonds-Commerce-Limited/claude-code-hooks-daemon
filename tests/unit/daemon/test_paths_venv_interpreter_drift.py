"""Plan 00555 Tasks 1.1 / 2.2: a venv whose interpreter drifted is stale, not usable.

A venv built for Python 3.11 whose ``bin/python`` now runs another minor passes
an ``import sys`` probe, but its ``lib/python3.11/site-packages`` is invisible to
that interpreter. The resolver must treat a ``pyvenv.cfg`` ``version_info`` /
``version`` that differs from the interpreter's ``major.minor`` as unusable.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from claude_code_hooks_daemon.daemon.paths import (
    VENV_STALE,
    _venv_interpreter_runs,
    classify_venv,
    resolve_existing_venv_python_with_diagnostics,
)

_RUNNING = (sys.version_info.major, sys.version_info.minor)
_OTHER = (_RUNNING[0], _RUNNING[1] + 1 if _RUNNING[1] < 50 else _RUNNING[1] - 1)


def _fake_venv(
    venv_dir: Path, cfg_version: tuple[int, int] | None, key: str = "version_info"
) -> Path:
    """A venv dir whose ``bin/python`` is the real running interpreter."""
    bin_dir = venv_dir / "bin"
    bin_dir.mkdir(parents=True)
    py = bin_dir / "python"
    py.symlink_to(os.path.realpath(sys.executable))
    lines = [f"home = {Path(os.path.realpath(sys.executable)).parent}"]
    if cfg_version is not None:
        lines.append(f"{key} = {cfg_version[0]}.{cfg_version[1]}.5")
    (venv_dir / "pyvenv.cfg").write_text("\n".join(lines) + "\n")
    return py


def _with_metadata(daemon_dir: Path, venv_dir: Path, python_path: Path) -> None:
    import hashlib

    (daemon_dir / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    digest = hashlib.sha256()
    digest.update((daemon_dir / "pyproject.toml").read_bytes())
    digest.update(b"\x00no-uv-lock\x00")
    (venv_dir / ".daemon-metadata.json").write_text(
        json.dumps({"python_path": str(python_path), "lock_hash": f"sha256:{digest.hexdigest()}"})
    )


class TestInterpreterRuns:
    def test_matching_version_info_runs(self, tmp_path: Path) -> None:
        py = _fake_venv(tmp_path / "v", _RUNNING)
        assert _venv_interpreter_runs(py) is True

    def test_matching_stdlib_version_key_runs(self, tmp_path: Path) -> None:
        py = _fake_venv(tmp_path / "v", _RUNNING, key="version")
        assert _venv_interpreter_runs(py) is True

    def test_drifted_version_info_does_not_run(self, tmp_path: Path) -> None:
        py = _fake_venv(tmp_path / "v", _OTHER)
        assert _venv_interpreter_runs(py) is False

    def test_drifted_stdlib_version_key_does_not_run(self, tmp_path: Path) -> None:
        py = _fake_venv(tmp_path / "v", _OTHER, key="version")
        assert _venv_interpreter_runs(py) is False

    def test_cfg_without_version_is_not_judged(self, tmp_path: Path) -> None:
        py = _fake_venv(tmp_path / "v", None)
        assert _venv_interpreter_runs(py) is True


class TestResolverFallsThroughOnDrift:
    def test_metadata_step_rejects_a_drifted_venv(self, tmp_path: Path) -> None:
        daemon_dir = tmp_path / "daemon"
        venv = daemon_dir / "untracked" / "venv-py311-abcdef12"
        py = _fake_venv(venv, _OTHER)
        _with_metadata(daemon_dir, venv, py)

        resolved, steps = resolve_existing_venv_python_with_diagnostics(daemon_dir)

        assert resolved is None, steps

    def test_metadata_step_accepts_a_matching_venv(self, tmp_path: Path) -> None:
        daemon_dir = tmp_path / "daemon"
        venv = daemon_dir / "untracked" / "venv-py311-abcdef12"
        py = _fake_venv(venv, _RUNNING)
        _with_metadata(daemon_dir, venv, py)

        resolved, steps = resolve_existing_venv_python_with_diagnostics(daemon_dir)

        assert resolved == py, steps

    def test_scan_step_rejects_a_drifted_venv(self, tmp_path: Path) -> None:
        daemon_dir = tmp_path / "daemon"
        _fake_venv(daemon_dir / "untracked" / "venv-py311-abcdef12", _OTHER)

        resolved, steps = resolve_existing_venv_python_with_diagnostics(daemon_dir)

        assert resolved is None, steps


class TestClassifyVenv:
    def test_drifted_venv_is_stale_even_when_lock_hash_matches(self, tmp_path: Path) -> None:
        daemon_dir = tmp_path / "daemon"
        daemon_dir.mkdir()
        venv = daemon_dir / "untracked" / "venv-py311-abcdef12"
        py = _fake_venv(venv, _OTHER)
        _with_metadata(daemon_dir, venv, py)
        current = json.loads((venv / ".daemon-metadata.json").read_text())["lock_hash"]

        verdict, reason = classify_venv(venv, "any-slug", current, frozenset())

        assert verdict == VENV_STALE
        assert "interpreter" in reason

    def test_matching_venv_is_not_stale(self, tmp_path: Path) -> None:
        daemon_dir = tmp_path / "daemon"
        daemon_dir.mkdir()
        venv = daemon_dir / "untracked" / "venv-py311-abcdef12"
        py = _fake_venv(venv, _RUNNING)
        _with_metadata(daemon_dir, venv, py)
        current = json.loads((venv / ".daemon-metadata.json").read_text())["lock_hash"]

        verdict, _ = classify_venv(venv, "any-slug", current, frozenset())

        assert verdict != VENV_STALE
