"""Plan 00555 DBF: a state snapshot never runs a drifted venv interpreter.

``create_state_snapshot`` records ``python_version`` in the manifest and takes a
best-effort ``pip freeze``. For a venv whose ``pyvenv.cfg`` records a different
major.minor than its ``bin/python`` runs, the record is kept (it is the venv a
rollback most needs) but comes from the cfg, marked drifted, and pip is not run.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

from claude_code_hooks_daemon.constants import Timeout

REPO_ROOT = Path(__file__).resolve().parents[2]
ROLLBACK_SH = REPO_ROOT / "scripts" / "install" / "rollback.sh"
BASH = shutil.which("bash") or "/bin/bash"

_RUNNING = (sys.version_info.major, sys.version_info.minor)
_OTHER = (_RUNNING[0], _RUNNING[1] + 1)


def _snapshot(tmp_path: Path, cfg_version: tuple[int, int] | None) -> tuple[dict[str, str], Path]:
    """Run create_state_snapshot with the resolver pinned to a fixture venv."""
    project = tmp_path / "proj"
    daemon = project / ".claude" / "hooks-daemon"
    venv = daemon / "untracked" / "venv-x-py3-aaa"
    (venv / "bin").mkdir(parents=True)
    python = venv / "bin" / "python"
    python.symlink_to(os.path.realpath(sys.executable))
    marker = tmp_path / "pip-ran"
    pip = venv / "bin" / "pip"
    pip.write_text(f"#!/bin/sh\ntouch {marker}\necho pkg==1\n")
    pip.chmod(0o755)
    if cfg_version is not None:
        (venv / "pyvenv.cfg").write_text(f"version_info = {cfg_version[0]}.{cfg_version[1]}.7\n")
    script = textwrap.dedent(f"""
        set -euo pipefail
        resolve_existing_venv_python() {{ printf '%s\\n' '{python}'; }}
        source '{ROLLBACK_SH}'
        # Fixed snapshot id, with the venv/ subdirectory the pip backup writes into
        # (create_state_snapshot does not create it itself).
        _hp_timestamp() {{ printf 'FIXED\\n'; }}
        mkdir -p '{daemon}/untracked/upgrade-snapshots/FIXED/files/venv'
        create_state_snapshot '{project}' '{daemon}' normal
        """)
    result = subprocess.run(
        [BASH, "-c", script],
        capture_output=True,
        text=True,
        check=False,
        timeout=Timeout.REQUEST_LONG,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    manifests = list((daemon / "untracked" / "upgrade-snapshots").glob("*/manifest.json"))
    assert len(manifests) == 1
    return json.loads(manifests[0].read_text()), marker


def test_a_usable_venv_records_the_interpreters_version_and_runs_pip(tmp_path: Path) -> None:
    manifest, pip_marker = _snapshot(tmp_path, _RUNNING)
    assert manifest["python_version"].startswith(f"{_RUNNING[0]}.{_RUNNING[1]}.")
    assert "drifted" not in manifest["python_version"]
    assert pip_marker.exists()


def test_a_drifted_venv_is_recorded_from_its_cfg_with_a_marker_and_pip_is_not_run(
    tmp_path: Path,
) -> None:
    manifest, pip_marker = _snapshot(tmp_path, _OTHER)
    assert manifest["python_version"] == f"{_OTHER[0]}.{_OTHER[1]}.7 (interpreter drifted)"
    assert not pip_marker.exists()


def test_a_venv_without_a_recorded_version_is_trusted_as_the_gate_trusts_it(
    tmp_path: Path,
) -> None:
    manifest, _ = _snapshot(tmp_path, None)
    assert manifest["python_version"].startswith(f"{_RUNNING[0]}.{_RUNNING[1]}.")
