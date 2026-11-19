"""Unattended, a failed Step 15 or Step 16 rolls back instead of keeping the new code.

Attended, a daemon that does not start (Step 15) or fails post-upgrade
validation (Step 16) is left on the new code for a human to fix, so
``UPGRADE_STARTED`` is cleared and the EXIT trap does nothing. Unattended
(``--unattended``, Plan 00625 DESIGN section 7) nobody is there, so the trap must
restore the snapshot and restart the previous daemon.

The real Step 15 / Step 16 blocks and the real ``cleanup_on_failure`` are cut out
of ``scripts/upgrade_version.sh`` and run against stubbed library functions that
record what was called, so the wiring under test is the script's own.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Final

import pytest

_LAYER2: Final[Path] = Path(__file__).resolve().parents[2] / "scripts" / "upgrade_version.sh"
_STEP_15: Final[str] = 'log_step "15"'
_STEP_15_END: Final[str] = "# The install has succeeded"
_STEP_16: Final[str] = 'log_step "16"'
_STEP_16_END: Final[str] = "# Step 16.5"
_TRAP_START: Final[str] = "cleanup_on_failure() {"
_TRAP_END: Final[str] = "trap cleanup_on_failure EXIT"

_STUBS: Final[str] = """
print_info() { echo "INFO: $*"; }
print_warning() { echo "WARN: $*"; }
print_error() { echo "ERROR: $*"; }
print_success() { echo "OK: $*"; }
log_step() { echo "STEP $1"; }
_record_tracking() { echo "RECORDED_TRACKING"; }
cleanup_old_default_config() { :; }
get_snapshot_dir() { echo /nowhere; }
restore_state_snapshot() { echo "RESTORED_SNAPSHOT $3"; }
venv_python_usable() { return 0; }
restore_install_tracking() { echo "RESTORED_TRACKING"; }
restart_daemon_quick() { echo "RESTARTED_PREVIOUS_DAEMON"; }
eager_cleanup_stale_venvs() { echo "EAGER_CLEANUP"; }
"""


def _slice(text: str, start: str, end: str) -> str:
    begin = text.index(start)
    return text[begin : text.index(end, begin)]


def _run(step: str, *, unattended: bool, fail_step: str) -> subprocess.CompletedProcess[str]:
    text = _LAYER2.read_text(encoding="utf-8")
    if step == "15":
        block = _slice(text, _STEP_15, _STEP_15_END)
    else:
        block = _slice(text, _STEP_16, _STEP_16_END)
    trap = _slice(text, _TRAP_START, _TRAP_END) + _TRAP_END
    start_ok = "true" if fail_step != "15" else "false"
    checks_ok = "true" if fail_step != "16" else "false"
    harness = (
        "set -euo pipefail\n"
        f"{_STUBS}"
        f"restart_daemon_verified() {{ {start_ok}; }}\n"
        f"run_post_install_checks() {{ {checks_ok}; }}\n"
        f'UNATTENDED={"true" if unattended else "false"}\n'
        "UPGRADE_STARTED=true\n"
        'SNAPSHOT_ID="snap-1"\nROLLBACK_REF=""\nCONFIG_BACKUP=""\nTARGET_CONFIG=/x\n'
        'DAEMON_DIR=/d\nPROJECT_ROOT=/p\nVENV_PYTHON=/v/bin/python\nVENV_PATH=/v\n'
        'OLD_DEFAULT_CONFIG=""\nPREVIOUS_TRACKED_REF=""\nPREVIOUS_TRACKED_SHA=""\n'
        'PREVIOUS_RECORDED_RELEASE=""\n'
        f"{trap}\n"
        f"{block}\n"
        'echo "REACHED_END"\n'
    )
    return subprocess.run(
        ["bash", "-c", harness], capture_output=True, text=True, check=False, timeout=60
    )


@pytest.mark.parametrize("step", ["15", "16"])
def test_unattended_failure_rolls_back_and_restarts_the_previous_daemon(step: str) -> None:
    result = _run(step, unattended=True, fail_step=step)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "RESTORED_SNAPSHOT snap-1" in result.stdout
    assert "RESTARTED_PREVIOUS_DAEMON" in result.stdout
    assert "REACHED_END" not in result.stdout


@pytest.mark.parametrize("step", ["15", "16"])
def test_attended_failure_keeps_the_new_code_and_does_not_roll_back(step: str) -> None:
    result = _run(step, unattended=False, fail_step=step)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "RESTORED_SNAPSHOT" not in result.stdout
    assert "RESTARTED_PREVIOUS_DAEMON" not in result.stdout


def test_unattended_step_15_failure_does_not_record_the_new_install() -> None:
    result = _run("15", unattended=True, fail_step="15")
    assert "RECORDED_TRACKING" not in result.stdout


def test_attended_step_15_failure_records_the_new_install() -> None:
    result = _run("15", unattended=False, fail_step="15")
    assert "RECORDED_TRACKING" in result.stdout


def test_unattended_defers_the_stale_venv_cleanup_until_validation_passed() -> None:
    """The previous daemon's venv must still exist when Step 16 rolls back."""
    text = _LAYER2.read_text(encoding="utf-8")
    step_15 = text.index(_STEP_15)
    step_16 = text.index(_STEP_16)
    step_16_end = text.index(_STEP_16_END)
    cleanup_calls = [
        at
        for at in range(step_15, step_16_end)
        if text.startswith("eager_cleanup_stale_venvs ", at)
    ]
    assert len(cleanup_calls) == 2, "one for attended runs, one for unattended"
    attended, unattended = cleanup_calls
    assert attended < step_16 < unattended
    assert 'UNATTENDED" != true' in text[attended - 80 : attended]
    assert 'UNATTENDED" = true' in text[unattended - 80 : unattended]
    validation_failure = text.index("exit 1", text.index("run_post_install_checks", step_16))
    assert validation_failure < unattended, "cleanup runs only after validation passed"


def test_second_pass_carries_the_unattended_flag() -> None:
    text = _LAYER2.read_text(encoding="utf-8")
    exec_line = next(line for line in text.splitlines() if line.lstrip().startswith("exec bash"))
    assert "_second_pass_flags" in exec_line
