"""A script lock must stay exclusive when the external ``mkdir`` does not.

``mkplan.bash``, ``mkroutine.bash`` and ``scripts/install/venv.sh`` (its
fallback backend) took their locks with ``mkdir "$lock"``, trusting the
command to fail with EEXIST when another runner already holds the lock. The
kernel's ``mkdir(2)`` does, but the COMMAND is whatever ``mkdir`` is first on
PATH. CI run 41530438536 (runner image ubuntu-26.04, which ships the Rust
uutils coreutils) traced two ``mkroutine.bash`` runners that both logged
``lock acquired after 0 busy attempt(s)`` 11 microseconds apart and both
allocated ``00001`` (Plan 00474 N568).

Each test below puts a fake ``mkdir`` FIRST on PATH. It behaves like
``mkdir -p``: it succeeds when the directory already exists, after a short
sleep that widens any check-then-create window. A lock built on the command's
exit status is no lock at all under it; a lock built on an exclusive create the
shell itself performs is unaffected, which is what these tests require.

The scaffolder holder is parked deterministically inside its critical section
by a ``git`` shim that blocks on the counter read (``config --get``), which
both scripts make only while holding the lock -- the same technique as
``test_scaffold_lock_signal.py``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants.timeout import Timeout

_SHELL_TIMEOUT = Timeout.QA_TEST_TIMEOUT
_POLL_SECONDS = 0.05
#: How long the second runner is given to (wrongly) reach the counter read
#: while the first is parked there. The fake mkdir sleeps 0.2s per call, so a
#: runner that is going to get in does so well inside this.
_INTRUSION_WINDOW_SECONDS = 2.0

_REPO_ROOT = Path(__file__).resolve().parents[3]
_PLAN_ASSETS = _REPO_ROOT / "CLAUDE" / "Plan"
_VENV_SH = _REPO_ROOT / "scripts" / "install" / "venv.sh"

#: (script path in this repo, subdirectory it is deployed into).
_SCRIPTS = {
    "mkroutine": (_REPO_ROOT / "CLAUDE" / "Routine" / "mkroutine.bash", Path("CLAUDE/Routine")),
    "mkplan": (_REPO_ROOT / "CLAUDE" / "Plan" / "mkplan.bash", Path("CLAUDE/Plan")),
}

_PERMISSIVE_MKDIR = """#!/usr/bin/env bash
# A mkdir that succeeds when the directory already exists, as a racy
# exists-check-then-create implementation (or one treating AlreadyExists as
# success) would. It sleeps first so two callers overlap.
sleep 0.2
operands=()
for arg in "$@"; do
    if [[ "$arg" != "-p" ]]; then
        operands+=("$arg")
    fi
done
exec "$SHIM_REAL_MKDIR" -p "${operands[@]}"
"""

_PARKING_GIT = """#!/usr/bin/env bash
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


def _write_tool(directory: Path, name: str, body: str) -> None:
    tool = directory / name
    tool.write_text(body)
    tool.chmod(0o755)


@pytest.fixture
def shim_env(tmp_path: Path) -> dict[str, str]:
    """An environment whose PATH starts with the permissive mkdir and parking git."""
    real_mkdir = shutil.which("mkdir")
    real_git = shutil.which("git")
    assert real_mkdir is not None and real_git is not None
    shim_dir = tmp_path / "shim"
    shim_dir.mkdir()
    _write_tool(shim_dir, "mkdir", _PERMISSIVE_MKDIR)
    _write_tool(shim_dir, "git", _PARKING_GIT)
    return {
        **os.environ,
        "PATH": f"{shim_dir}{os.pathsep}{os.environ['PATH']}",
        "SHIM_REAL_MKDIR": real_mkdir,
        "SHIM_REAL_GIT": real_git,
        "SHIM_RELEASE": str(tmp_path / "release"),
    }


def _deploy(tmp_path: Path, script_name: str) -> tuple[Path, Path]:
    """A temp git repo with the real scaffolder deployed; returns (repo, script)."""
    source, subdir = _SCRIPTS[script_name]
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
    for args in (
        ("init", "--quiet"),
        ("config", "user.email", "lock@test.invalid"),
        ("config", "user.name", "Lock Test"),
    ):
        subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            check=True,
            timeout=_SHELL_TIMEOUT,
        )
    return repo, script


def _start(
    script: Path, name: str, repo: Path, env: dict[str, str], parked: Path
) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [str(script), name],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=repo,
        env={**env, "SHIM_PARKED": str(parked), "MKROUTINE_TRACE": "1"},
    )


def _wait_for(path: Path, process: subprocess.Popen[str]) -> None:
    deadline = time.monotonic() + _SHELL_TIMEOUT
    while not path.exists():
        if process.poll() is not None:
            raise AssertionError(f"runner exited before parking: {process.communicate()}")
        if time.monotonic() > deadline:
            raise AssertionError(f"runner never reached the counter read ({path})")
        time.sleep(_POLL_SECONDS)


def _numbers(target_dir: Path) -> list[str]:
    return sorted(path.name.split("-", 1)[0] for path in target_dir.glob("0*-*"))


@pytest.mark.parametrize("script_name", sorted(_SCRIPTS))
def test_a_held_lock_keeps_a_second_runner_out(
    tmp_path: Path, script_name: str, shim_env: dict[str, str]
) -> None:
    """While one runner is parked holding the lock, a second never reaches the counter."""
    repo, script = _deploy(tmp_path, script_name)
    first_parked = tmp_path / "first-parked"
    second_parked = tmp_path / "second-parked"
    release = Path(shim_env["SHIM_RELEASE"])

    first = _start(script, "first-run", repo, shim_env, first_parked)
    second: subprocess.Popen[str] | None = None
    try:
        _wait_for(first_parked, first)
        second = _start(script, "second-run", repo, shim_env, second_parked)
        deadline = time.monotonic() + _INTRUSION_WINDOW_SECONDS
        while time.monotonic() < deadline and not second_parked.exists():
            time.sleep(_POLL_SECONDS)
        intruded = second_parked.exists()
        release.touch()
        first_out = first.communicate(timeout=_SHELL_TIMEOUT)
        second_out = second.communicate(timeout=_SHELL_TIMEOUT)
    finally:
        release.touch()
        for process in (first, second):
            if process is not None and process.poll() is None:
                process.kill()
                process.communicate()

    assert second is not None, "the second runner was never started"
    evidence = f"first={first.returncode} {first_out}\nsecond={second.returncode} {second_out}"
    assert not intruded, f"second runner entered the critical section under a held lock\n{evidence}"
    assert first.returncode == 0 and second.returncode == 0, evidence
    numbers = _numbers(repo / _SCRIPTS[script_name][1])
    assert len(numbers) == 2 and len(set(numbers)) == 2, f"numbers={numbers}\n{evidence}"


@pytest.mark.parametrize("script_name", sorted(_SCRIPTS))
def test_parallel_runs_get_distinct_numbers(
    tmp_path: Path, script_name: str, shim_env: dict[str, str]
) -> None:
    """Two runners started together still allocate two different numbers."""
    repo, script = _deploy(tmp_path, script_name)
    Path(shim_env["SHIM_RELEASE"]).touch()
    runners = [
        _start(script, name, repo, shim_env, tmp_path / f"{name}-parked")
        for name in ("alpha-run", "beta-run")
    ]
    outputs = [runner.communicate(timeout=_SHELL_TIMEOUT) for runner in runners]
    evidence = "\n".join(
        f"--- exit {runner.returncode} ---\n{out[1]}"
        for runner, out in zip(runners, outputs, strict=True)
    )

    assert all(runner.returncode == 0 for runner in runners), evidence
    numbers = _numbers(repo / _SCRIPTS[script_name][1])
    assert numbers == ["00001", "00002"] or (
        script_name == "mkplan" and len(set(numbers)) == 2
    ), f"numbers={numbers}\n{evidence}"


def test_venv_fallback_lock_refuses_a_second_taker(
    tmp_path: Path, shim_env: dict[str, str]
) -> None:
    """venv.sh's non-flock backend: a held lock answers HELD (75) to a second try."""
    daemon_dir = tmp_path / "daemon"
    (daemon_dir / "untracked").mkdir(parents=True)
    probe = (
        f'source "{_VENV_SH}"\n'
        f'try_acquire_venv_lock "{daemon_dir}"\n'
        'echo "first=$?"\n'
        "second=0\n"
        f'( try_acquire_venv_lock "{daemon_dir}" ) || second=$?\n'
        'echo "second=$second"\n'
        "release_venv_lock\n"
    )
    result = subprocess.run(
        ["bash", "-c", probe],
        capture_output=True,
        text=True,
        env={**shim_env, "HOOKS_DAEMON_VENV_LOCK_BACKEND": "mkdir"},
        timeout=_SHELL_TIMEOUT,
        check=False,
    )

    assert "first=0" in result.stdout, result.stdout + result.stderr
    assert "second=75" in result.stdout, result.stdout + result.stderr
    assert not any(
        (daemon_dir / "untracked").glob(".venv-bootstrap.lock*")
    ), "the holder's release must leave no lock behind"
