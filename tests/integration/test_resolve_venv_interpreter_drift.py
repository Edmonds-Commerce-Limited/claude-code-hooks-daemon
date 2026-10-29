"""Plan 00555 Task 2.2 -- the bash resolver agrees with paths.py on interpreter drift.

``scripts/lib/resolve_venv.sh::_rv_candidate_runs`` must refuse a venv whose
``pyvenv.cfg`` ``version_info`` / ``version`` ``major.minor`` differs from the
interpreter's, exactly as ``paths.py::_venv_interpreter_runs`` does.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from claude_code_hooks_daemon.daemon.paths import _venv_interpreter_runs

REPO_ROOT = Path(__file__).resolve().parents[2]
RESOLVE_VENV_SH = REPO_ROOT / "scripts" / "lib" / "resolve_venv.sh"
BASH = shutil.which("bash") or "/bin/bash"

_RUNNING = (sys.version_info.major, sys.version_info.minor)
_OTHER = (_RUNNING[0], _RUNNING[1] + 1 if _RUNNING[1] < 50 else _RUNNING[1] - 1)


def _fake_venv(venv_dir: Path, cfg_version: tuple[int, int] | None, key: str) -> Path:
    bin_dir = venv_dir / "bin"
    bin_dir.mkdir(parents=True)
    py = bin_dir / "python"
    py.symlink_to(os.path.realpath(sys.executable))
    lines = [f"home = {Path(os.path.realpath(sys.executable)).parent}"]
    if cfg_version is not None:
        lines.append(f"{key} = {cfg_version[0]}.{cfg_version[1]}.5")
    (venv_dir / "pyvenv.cfg").write_text("\n".join(lines) + "\n")
    return py


def _bash_runs(candidate: Path) -> bool:
    harness = textwrap.dedent(f"""\
        unset HOOKS_DAEMON_PYTHON HOOKS_DAEMON_VENV_PATH
        . "{RESOLVE_VENV_SH}"
        _rv_candidate_runs "{candidate}"
        """)
    result = subprocess.run(
        [BASH, "-c", harness], capture_output=True, text=True, check=False, timeout=30
    )
    return result.returncode == 0


@pytest.mark.parametrize("key", ["version_info", "version"])
@pytest.mark.parametrize("drifted", [False, True])
def test_bash_and_python_agree_on_drift(tmp_path: Path, key: str, drifted: bool) -> None:
    py = _fake_venv(tmp_path / "v", _OTHER if drifted else _RUNNING, key)

    assert _bash_runs(py) is (not drifted)
    assert _venv_interpreter_runs(py) is (not drifted)


def test_bash_and_python_agree_when_cfg_has_no_version(tmp_path: Path) -> None:
    py = _fake_venv(tmp_path / "v", None, "version_info")

    assert _bash_runs(py) is True
    assert _venv_interpreter_runs(py) is True


def test_pick_python_skips_a_drifted_venv(tmp_path: Path) -> None:
    daemon_dir = tmp_path / "daemon"
    _fake_venv(daemon_dir / "untracked" / "venv-py311-abcdef12", _OTHER, "version_info")
    harness = textwrap.dedent(f"""\
        unset HOOKS_DAEMON_PYTHON HOOKS_DAEMON_VENV_PATH
        . "{RESOLVE_VENV_SH}"
        _rv_pick_python "{daemon_dir}"
        """)

    result = subprocess.run(
        [BASH, "-c", harness], capture_output=True, text=True, check=False, timeout=30
    )

    assert result.returncode != 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"


def _versioned_chain_venv(
    daemon_dir: Path, link_version: tuple[int, int], cfg: tuple[int, int]
) -> Path:
    """Venv whose bin/python -> pythonX.Y -> real interpreter, with a given cfg version."""
    venv = daemon_dir / "untracked" / "venv-py311-abcdef12"
    (venv / "bin").mkdir(parents=True)
    system = venv.parent.parent / "system-bin"
    system.mkdir()
    versioned = system / f"python{link_version[0]}.{link_version[1]}"
    versioned.symlink_to(os.path.realpath(sys.executable))
    py = venv / "bin" / "python"
    py.symlink_to(versioned)
    (venv / "pyvenv.cfg").write_text(f"version_info = {cfg[0]}.{cfg[1]}.5\n")
    return py


def _resolve_with_cache(daemon_dir: Path, cached: Path) -> subprocess.CompletedProcess[str]:
    harness = textwrap.dedent(f"""\
        unset HOOKS_DAEMON_PYTHON HOOKS_DAEMON_VENV_PATH
        . "{RESOLVE_VENV_SH}"
        mtime="$(_rv_dir_mtime "{daemon_dir}/untracked")"
        printf '%s %s\\n' "$mtime" "{cached}" > "{daemon_dir}/untracked/.python-cmd-cache"
        _rv_resolve_python_impl "{daemon_dir}"
        """)
    return subprocess.run(
        [BASH, "-c", harness], capture_output=True, text=True, check=False, timeout=60
    )


def test_cache_hit_is_served_while_venv_matches(tmp_path: Path) -> None:
    py = _versioned_chain_venv(tmp_path / "d", _RUNNING, _RUNNING)

    result = _resolve_with_cache(tmp_path / "d", py)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(py)


def test_cache_hit_refused_when_cfg_version_changes(tmp_path: Path) -> None:
    """untracked/ mtime is untouched, yet the drifted venv must not be served."""
    daemon_dir = tmp_path / "d"
    py = _versioned_chain_venv(daemon_dir, _RUNNING, _OTHER)

    result = _resolve_with_cache(daemon_dir, py)

    assert str(py) not in result.stdout
    assert result.returncode != 0


def test_cached_venv_check_refuses_when_system_python_link_changes(tmp_path: Path) -> None:
    """Real incident: cfg still records the old minor, the interpreter link moved on."""
    py = _versioned_chain_venv(tmp_path / "d", _OTHER, _RUNNING)
    # End the chain at a plain file so the versioned name is the final hop.
    versioned = py.readlink()
    versioned.unlink()
    versioned.write_text("#!/bin/sh\n")
    harness = f'. "{RESOLVE_VENV_SH}"; _rv_cached_venv_current "{py}"'

    result = subprocess.run(
        [BASH, "-c", harness], capture_output=True, text=True, check=False, timeout=30
    )

    assert result.returncode != 0
