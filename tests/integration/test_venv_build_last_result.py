"""Every venv build path leaves a holder record, a log and a last-result record (Plan 00555 Task 2.7).

Before this, only the hook-started detached build recorded who held the venv
lock, and a successful build left no machine-readable trace at all. The
records reuse the existing files: ``untracked/.venv-bootstrap.current`` (the
holder record) and a sibling ``untracked/.venv-bootstrap.result`` in the same
key=value format.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Final

from tests.integration.test_venv_bootstrap_driver import (
    BASH,
    REPO_ROOT,
    _daemon_dir,
    _env,
    _fields,
    _run,
    _source_venv_sh,
    _stub_uv,
    _wait_for_lock_release,
)

_RESULT_NAME: Final[str] = ".venv-bootstrap.result"
_RECORD_NAME: Final[str] = ".venv-bootstrap.current"
_WAIT_SECONDS: Final[float] = 30.0


def _kv(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text().splitlines():
        key, _, value = line.partition("=")
        out[key] = value
    return out


def _wait_for(path: Path) -> None:
    deadline = time.monotonic() + _WAIT_SECONDS
    while time.monotonic() < deadline:
        if path.exists():
            return
        time.sleep(0.1)
    raise AssertionError(f"{path} never appeared")


class TestSuccessLeavesALastResult:
    """(b) A successful build used to delete its marker and record and say nothing."""

    def test_hook_build_success_is_reported_by_an_idle_probe(self, tmp_path: Path) -> None:
        daemon_dir = _daemon_dir(tmp_path)
        env = _env(tmp_path, with_uv=_stub_uv(tmp_path))
        first = _fields(_run("hook", daemon_dir, env).stdout)
        _wait_for_lock_release(daemon_dir)

        out = _fields(_run("probe", daemon_dir, env).stdout)

        assert out["state"] == ["idle"]
        assert out["last_result"] == ["succeeded"]
        assert out["log"] == first["log"]
        assert out["finished_at"][0].endswith("Z")

    def test_a_failed_build_is_reported_as_failed_with_its_exit(self, tmp_path: Path) -> None:
        daemon_dir = _daemon_dir(tmp_path)
        env = _env(tmp_path, with_uv=_stub_uv(tmp_path, fail=True))
        _run("hook", daemon_dir, env)
        _wait_for_lock_release(daemon_dir)

        out = _fields(_run("probe", daemon_dir, env).stdout)

        assert out["last_result"] == ["failed"]
        assert out["exit"] == ["1"]

    def test_a_timed_out_build_is_reported_as_timed_out(self, tmp_path: Path) -> None:
        daemon_dir = _daemon_dir(tmp_path)
        env = _env(
            tmp_path,
            with_uv=_stub_uv(tmp_path, sleep=30),
            extra={"HOOKS_DAEMON_VENV_BUILD_TIMEOUT": "2"},
        )
        _run("hook", daemon_dir, env)
        _wait_for_lock_release(daemon_dir)

        out = _fields(_run("probe", daemon_dir, env).stdout)

        assert out["last_result"] == ["timed-out"]

    def test_no_build_yet_means_a_bare_idle(self, tmp_path: Path) -> None:
        daemon_dir = _daemon_dir(tmp_path)
        env = _env(tmp_path, with_uv=_stub_uv(tmp_path))

        assert _fields(_run("probe", daemon_dir, env).stdout) == {"state": ["idle"]}

    def test_foreground_repair_records_its_result_and_log(self, tmp_path: Path) -> None:
        daemon_dir = _daemon_dir(tmp_path)
        env = _env(tmp_path, with_uv=_stub_uv(tmp_path))

        result = _run("repair", daemon_dir, env)

        assert result.returncode == 0, result.stderr
        record = _kv(daemon_dir / "untracked" / _RESULT_NAME)
        assert record["result"] == "succeeded"
        log = Path(record["log"])
        assert log.parent == daemon_dir / "untracked"
        assert "SUCCEEDED" in log.read_text()

    def test_ensure_venv_from_an_upgrade_records_its_result(self, tmp_path: Path) -> None:
        daemon_dir = _daemon_dir(tmp_path)
        env = _env(tmp_path, with_uv=_stub_uv(tmp_path))
        fingerprint_sh = REPO_ROOT / "scripts" / "install" / "python_fingerprint.sh"
        script = (
            f'source "{fingerprint_sh}"\n'
            f'ensure_venv "{daemon_dir}" v3.61.0 "{sys.executable}" > /dev/null'
        )
        assert _source_venv_sh(script, env).returncode == 0

        assert _kv(daemon_dir / "untracked" / _RESULT_NAME)["result"] == "succeeded"


class TestEveryLockHolderIsRecorded:
    """(a) A holder other than the hook showed as 'not recorded here'."""

    def test_acquire_venv_lock_writes_a_holder_record_while_held(self, tmp_path: Path) -> None:
        daemon_dir = _daemon_dir(tmp_path)
        env = _env(tmp_path, with_uv=_stub_uv(tmp_path))
        venv_sh = REPO_ROOT / "scripts" / "install" / "venv.sh"
        ready = tmp_path / "ready"
        holder = subprocess.Popen(
            [
                BASH,
                "-c",
                f'source "{venv_sh}"; acquire_venv_lock "{daemon_dir}"; '
                f'touch "{ready}"; sleep 20',
            ],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            _wait_for(ready)
            out = _fields(_run("probe", daemon_dir, env).stdout)
            assert out["state"] == ["running"]
            assert out["holder"] == ["ensure_venv"]
            assert out["pid"] == [str(holder.pid)]
        finally:
            holder.kill()
            holder.wait()

    def test_release_removes_the_record_it_wrote(self, tmp_path: Path) -> None:
        daemon_dir = _daemon_dir(tmp_path)
        env = _env(tmp_path, with_uv=_stub_uv(tmp_path))

        script = f'acquire_venv_lock "{daemon_dir}"; release_venv_lock'
        assert _source_venv_sh(script, env).returncode == 0

        assert not (daemon_dir / "untracked" / _RECORD_NAME).exists()

    def test_a_foreground_repair_is_named_while_it_builds(self, tmp_path: Path) -> None:
        daemon_dir = _daemon_dir(tmp_path)
        env = _env(tmp_path, with_uv=_stub_uv(tmp_path, sleep=4))
        repair = subprocess.Popen(
            [BASH, str(REPO_ROOT / "scripts" / "venv_bootstrap.sh"), "repair", str(daemon_dir)],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            _wait_for(daemon_dir / "untracked" / _RECORD_NAME)
            out = _fields(_run("probe", daemon_dir, env).stdout)
            assert out["state"] == ["running"]
            assert out["holder"] == ["repair"]
            assert Path(out["log"][0]).parent == daemon_dir / "untracked"
        finally:
            repair.wait(timeout=60)


class TestTheDaemonDownStopMessageNamesTheLastBuild:
    """(c) The plain 'daemon not running' stop block named neither log nor result."""

    def _reason(self, tmp_path: Path, *, with_result: bool, with_jq: bool) -> str:
        from tests.integration.test_init_sh_venv_missing_message import _project
        from tests.integration.test_init_sh_venv_missing_message import _run as run_init

        project = _project(tmp_path)
        if with_result:
            untracked = project / ".claude" / "hooks-daemon" / "untracked"
            untracked.mkdir(parents=True, exist_ok=True)
            (untracked / _RESULT_NAME).write_text(
                "result=failed\nfinished_at=2026-10-31T01:02:03Z\nexit=2\nlog=/x/build.log\n"
            )
        script = (
            "_HOOKS_DAEMON_VENV_MISSING=false\n_HOOKS_DAEMON_NOT_INSTALLED=false\n"
            'emit_hook_error "Stop" "socket_not_found" "no socket"'
        )
        result = run_init(project, script, with_jq=with_jq)
        return str(json.loads(result.stdout)["reason"])

    def test_the_jq_encoder_names_the_log_and_result(self, tmp_path: Path) -> None:
        reason = self._reason(tmp_path, with_result=True, with_jq=True)
        assert "last venv build: failed at 2026-10-31T01:02:03Z" in reason
        assert "/x/build.log" in reason

    def test_the_python_encoder_names_the_log_and_result(self, tmp_path: Path) -> None:
        reason = self._reason(tmp_path, with_result=True, with_jq=False)
        assert "last venv build: failed" in reason
        assert "/x/build.log" in reason

    def test_no_record_leaves_the_message_unchanged(self, tmp_path: Path) -> None:
        reason = self._reason(tmp_path, with_result=False, with_jq=True)
        assert reason == "Hooks daemon not running - protection not active"
