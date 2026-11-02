"""A signal must END a scaffolder run that holds the lock, not let it carry on.

``mkplan.bash`` and ``mkroutine.bash`` serialise number allocation with an
exclusively-created lock file and remove it from a trap. When that trap covered INT and
TERM with the bare release function, bash ran the function and then RESUMED
the script: the lock was gone while the runner was still inside the critical
section, so a second runner could take the lock, read the same counter and
allocate the same number. Both exit 0, and two folders share one number --
the exact signature of the intermittent CI failure of
``test_parallel_runs_get_distinct_numbers`` (Plan 00474).

The holder is parked deterministically inside the critical section by a
``git`` shim on PATH that blocks on the counter read (``config --get``), which
both scripts make only while holding the lock. The test then signals the
holder, lets the read finish, and requires that the run stopped: non-zero exit,
no numbered folder, no lock left behind.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants.timeout import Timeout

_SHELL_TIMEOUT = Timeout.QA_TEST_TIMEOUT
_POLL_SECONDS = 0.05

_REPO_ROOT = Path(__file__).resolve().parents[3]
_PLAN_ASSETS = _REPO_ROOT / "CLAUDE" / "Plan"

#: (script path in this repo, subdirectory it is deployed into, lock it takes
#: relative to the temp repo root).
_SCRIPTS = {
    "mkroutine": (
        _REPO_ROOT / "CLAUDE" / "Routine" / "mkroutine.bash",
        Path("CLAUDE") / "Routine",
        Path("CLAUDE") / "Routine" / ".mkroutine.lock",
    ),
    "mkplan": (
        _REPO_ROOT / "CLAUDE" / "Plan" / "mkplan.bash",
        Path("CLAUDE") / "Plan",
        Path(".git") / "hooksdaemon-mkplan.lock",
    ),
}

_GIT_SHIM = """#!/usr/bin/env bash
# Park the caller on the counter read until the test releases it.
for arg in "$@"; do
    if [[ "$arg" == "--get" ]]; then
        : > "$SHIM_PARKED"
        while [[ ! -e "$SHIM_RELEASE" ]]; do
            sleep 0.05
        done
        break
    fi
done
exec "$SHIM_REAL_GIT" "$@"
"""


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
        timeout=_SHELL_TIMEOUT,
    )


def _wait_for(path: Path, process: subprocess.Popen[str]) -> None:
    deadline = time.monotonic() + _SHELL_TIMEOUT
    while not path.exists():
        if process.poll() is not None:
            raise AssertionError(f"scaffolder exited before parking: {process.communicate()}")
        if time.monotonic() > deadline:
            raise AssertionError(f"scaffolder never reached the counter read ({path})")
        time.sleep(_POLL_SECONDS)


@pytest.mark.parametrize("script_name", sorted(_SCRIPTS))
@pytest.mark.parametrize(("sig", "expected_exit"), [(signal.SIGTERM, 143), (signal.SIGINT, 130)])
def test_signal_inside_the_critical_section_ends_the_run(
    tmp_path: Path, script_name: str, sig: signal.Signals, expected_exit: int
) -> None:
    source, subdir, lock_rel = _SCRIPTS[script_name]
    repo = tmp_path / "repo"
    target_dir = repo / subdir
    target_dir.mkdir(parents=True)
    script = target_dir / source.name
    script.write_bytes(source.read_bytes())
    script.chmod(0o755)
    if script_name == "mkplan":
        for asset in _PLAN_ASSETS.glob("_*"):
            if asset.is_file():
                (target_dir / asset.name).write_bytes(asset.read_bytes())
    _git(repo, "init", "--quiet")
    _git(repo, "config", "user.email", "signal@test.invalid")
    _git(repo, "config", "user.name", "Signal Test")

    real_git = shutil.which("git")
    assert real_git is not None
    shim_dir = tmp_path / "shim"
    shim_dir.mkdir()
    shim = shim_dir / "git"
    shim.write_text(_GIT_SHIM)
    shim.chmod(0o755)
    parked = tmp_path / "parked"
    release = tmp_path / "release"
    env = {
        **os.environ,
        "PATH": f"{shim_dir}{os.pathsep}{os.environ['PATH']}",
        "SHIM_PARKED": str(parked),
        "SHIM_RELEASE": str(release),
        "SHIM_REAL_GIT": real_git,
    }

    holder = subprocess.Popen(
        [str(script), "signalled-run"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=repo,
        env=env,
    )
    try:
        _wait_for(parked, holder)
        assert (repo / lock_rel).is_file(), "holder is parked but does not hold the lock"
        holder.send_signal(sig)
        release.touch()
        _, stderr = holder.communicate(timeout=_SHELL_TIMEOUT)
    finally:
        release.touch()
        if holder.poll() is None:
            holder.kill()
            holder.communicate()

    created = sorted(path.name for path in target_dir.glob("0*-*"))
    assert holder.returncode == expected_exit, (holder.returncode, created, stderr)
    assert created == [], f"run continued past the signal without the lock: {created}"
    assert not (repo / lock_rel).exists(), "a signalled run must still release its lock"
