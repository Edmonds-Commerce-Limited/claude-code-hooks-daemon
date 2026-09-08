"""upgrade_version.sh Step 4 on a fresh clone (Plan 00362 Task 2.2, D3).

Plan 00291 Task 1.1: a client in the fresh-clone state (config and forwarders
present, no venv, no daemon checkout on disk) is the documented upgrade route,
and it aborted into rollback. ``VENV_PYTHON`` is deliberately empty there
(Plan 00104 Task 5.2), ``stop_daemon_safe`` returns 1 on an empty argument,
and the script runs under ``set -euo pipefail`` — so Step 4 was the line
that killed the upgrade.

Reproduced by a client canary install. The fix: no venv means there is no
daemon to stop, so Step 4 skips the stop and says so, instead of failing it.

These tests run the REAL Step 4 block, extracted from the script between its
step banners, under the same ``set -euo pipefail`` the script uses, with the
real ``daemon_control.sh`` sourced. They do not run the whole script (that
needs git, a venv and a network).
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
UPGRADE_SH = REPO_ROOT / "scripts" / "upgrade_version.sh"
INSTALL_LIB = REPO_ROOT / "scripts" / "install"

# The block between the Step 4 banner comment and the Step 5 banner.
_STEP4_PATTERN = re.compile(
    r"# Step 4: Stop daemon\n# =+\n(?P<body>.*?)\n# =+\n# Step 5:",
    re.DOTALL,
)

_HARNESS = """
set -euo pipefail
source "$INSTALL_LIB/output.sh"
source "$INSTALL_LIB/daemon_control.sh"
log_step() { echo "STEP $1: $2"; }
VENV_PYTHON="$VENV_PYTHON_UNDER_TEST"
source "$STEP4_FILE"
echo "STEP4_COMPLETED"
"""


def _step4_body() -> str:
    match = _STEP4_PATTERN.search(UPGRADE_SH.read_text())
    assert match is not None, "scripts/upgrade_version.sh no longer has a Step 4 banner pair"
    return match.group("body")


def _run_step4(tmp_path: Path, venv_python: str) -> subprocess.CompletedProcess[str]:
    step4_file = tmp_path / "step4.sh"
    step4_file.write_text(_step4_body() + "\n")
    env = os.environ.copy()
    env.update(
        INSTALL_LIB=str(INSTALL_LIB),
        STEP4_FILE=str(step4_file),
        VENV_PYTHON_UNDER_TEST=venv_python,
        NO_COLOR="1",
    )
    return subprocess.run(
        ["bash", "-c", _HARNESS],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def test_stop_daemon_safe_still_refuses_an_empty_argument() -> None:
    """The library contract this fix routes around: an empty venv python is a
    caller error, not a 'not running' condition. Pinned so the guard in the
    script stays load-bearing rather than being quietly made redundant."""
    result = subprocess.run(
        [
            "bash",
            "-c",
            'set -uo pipefail; source "$1/output.sh"; source "$1/daemon_control.sh"; '
            'stop_daemon_safe ""',
            "_",
            str(INSTALL_LIB),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1


def test_fresh_clone_step4_completes_under_set_e(tmp_path: Path) -> None:
    result = _run_step4(tmp_path, venv_python="")
    assert result.returncode == 0, (
        "Step 4 aborted with an empty VENV_PYTHON — the fresh-clone upgrade "
        f"would roll back here.\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "STEP4_COMPLETED" in result.stdout


def test_fresh_clone_step4_says_it_skipped_the_stop(tmp_path: Path) -> None:
    result = _run_step4(tmp_path, venv_python="")
    combined = result.stdout + result.stderr
    assert re.search(r"no (existing )?venv", combined, re.IGNORECASE), combined
    assert re.search(r"no daemon to stop|skipping", combined, re.IGNORECASE), combined
    assert "venv_python parameter required" not in combined


def test_missing_venv_python_path_still_completes(tmp_path: Path) -> None:
    """A stale path (venv directory removed) is the other no-daemon shape and
    was already tolerated by the library; it must stay that way."""
    result = _run_step4(tmp_path, venv_python=str(tmp_path / "gone" / "bin" / "python"))
    assert result.returncode == 0, result.stderr
    assert "STEP4_COMPLETED" in result.stdout


def test_step4_does_not_call_stop_daemon_safe_unguarded() -> None:
    body = _step4_body()
    for line in body.splitlines():
        if "stop_daemon_safe" in line and not line.lstrip().startswith("#"):
            assert line.startswith((" ", "\t")), (
                "stop_daemon_safe must sit inside a guard on VENV_PYTHON, not "
                f"at column 0 where an empty value aborts the script: {line!r}"
            )
