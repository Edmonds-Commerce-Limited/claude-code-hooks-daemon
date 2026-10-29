"""Plan 00555 DBF: the upgrade metadata block never records a drifted interpreter.

``scripts/upgrade.sh`` ends by choosing a venv interpreter, writing its path to
``UPGRADE_METADATA`` and running the post-upgrade checks with it. The resolver
later trusts that metadata, so a venv whose ``pyvenv.cfg`` records a different
major.minor than its ``bin/python`` runs must never be named there.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants import Timeout

REPO_ROOT = Path(__file__).resolve().parents[2]
UPGRADE_SH = REPO_ROOT / "scripts" / "upgrade.sh"
LIB_DIR = REPO_ROOT / "scripts" / "lib"
BASH = shutil.which("bash") or "/bin/bash"

_START = "for _gate_lib in"
_END = "# Host: prefer $HOSTNAME"

_RUNNING = (sys.version_info.major, sys.version_info.minor)
_OTHER = (_RUNNING[0], _RUNNING[1] + 1)


def _block() -> str:
    text = UPGRADE_SH.read_text()
    start = text.index(_START)
    return text[start : text.index(_END, start)]


def _venv(daemon_dir: Path, name: str, cfg_version: tuple[int, int]) -> Path:
    venv = daemon_dir / "untracked" / name
    (venv / "bin").mkdir(parents=True)
    py = venv / "bin" / "python"
    py.symlink_to(os.path.realpath(sys.executable))
    (venv / "pyvenv.cfg").write_text(f"version_info = {cfg_version[0]}.{cfg_version[1]}.1\n")
    return py


def _run_block(tmp_path: Path, *, sibling_lib: bool, daemon_lib: bool) -> dict[str, str]:
    """Run the metadata block against ``tmp_path/daemon``; return its resulting variables."""
    daemon = tmp_path / "daemon"
    daemon.mkdir(exist_ok=True)
    scripts = tmp_path / "scripts"
    scripts.mkdir(exist_ok=True)
    if sibling_lib:
        (scripts / "lib").symlink_to(LIB_DIR)
    if daemon_lib:
        (daemon / "scripts").mkdir(exist_ok=True)
        (daemon / "scripts" / "lib").symlink_to(LIB_DIR)
    driver = scripts / "block.sh"
    driver.write_text(
        "set -euo pipefail\n"
        + _block()
        + 'printf "python=%s\\npath=%s\\nvenv=%s\\n" '
        + '"$_metadata_venv_python" "$_metadata_python_path" "$_metadata_venv_path"\n'
    )
    env = {k: v for k, v in os.environ.items() if not k.startswith("HOOKS_DAEMON_")}
    env["DAEMON_DIR"] = str(daemon)
    result = subprocess.run(
        [BASH, str(driver)],
        capture_output=True,
        text=True,
        check=False,
        env=env,
        timeout=Timeout.REQUEST_LONG,
    )
    assert result.returncode == 0, result.stderr
    return dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)


class TestMetadataNamesOnlyAUsableInterpreter:
    def test_a_healthy_venv_is_recorded(self, tmp_path: Path) -> None:
        py = _venv(tmp_path / "daemon", "venv-x-py3-aaa", _RUNNING)
        got = _run_block(tmp_path, sibling_lib=True, daemon_lib=False)
        assert got["python"] == str(py)
        assert got["path"] == str(py)

    def test_a_drifted_venv_is_not_recorded(self, tmp_path: Path) -> None:
        _venv(tmp_path / "daemon", "venv-x-py3-aaa", _OTHER)
        got = _run_block(tmp_path, sibling_lib=True, daemon_lib=False)
        assert got["python"] == ""
        assert got["path"] == ""
        assert got["venv"] == ""

    def test_the_first_usable_venv_wins_over_an_earlier_drifted_one(self, tmp_path: Path) -> None:
        daemon = tmp_path / "daemon"
        _venv(daemon, "venv-a-py3-aaa", _OTHER)
        good = _venv(daemon, "venv-b-py3-bbb", _RUNNING)
        got = _run_block(tmp_path, sibling_lib=True, daemon_lib=False)
        assert got["python"] == str(good)

    def test_the_daemon_dirs_own_library_is_used_when_there_is_no_sibling(
        self, tmp_path: Path
    ) -> None:
        _venv(tmp_path / "daemon", "venv-x-py3-aaa", _OTHER)
        got = _run_block(tmp_path, sibling_lib=False, daemon_lib=True)
        assert got["python"] == ""

    @pytest.mark.parametrize("cfg_version", [_RUNNING, _OTHER])
    def test_no_gate_available_records_nothing_rather_than_an_unverified_path(
        self, tmp_path: Path, cfg_version: tuple[int, int]
    ) -> None:
        _venv(tmp_path / "daemon", "venv-x-py3-aaa", cfg_version)
        got = _run_block(tmp_path, sibling_lib=False, daemon_lib=False)
        assert got["python"] == ""
        assert got["path"] == ""
