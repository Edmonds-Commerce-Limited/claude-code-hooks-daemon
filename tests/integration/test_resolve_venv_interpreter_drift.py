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
