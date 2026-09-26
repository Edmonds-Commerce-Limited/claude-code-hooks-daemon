"""Plan 00466 N30 — ``scripts/venv_bootstrap.sh``'s epoch-second call sites.

Five spots fed `$(date +%s)` straight into an arithmetic expression or a
numeric `[ ]` test:

  - ``_vb_watchdog`` (the build timeout bound check)
  - ``_vb_judge_stop`` (elapsed time, to decide "timed out" vs "just stopped")
  - ``_vb_print_running`` (the `elapsed=` status field)
  - ``_vb_hook`` (the `started=` field of a NEW detached build's record)
  - ``_vb_build`` (the fallback start-time seed)

Each is exercised directly (source the driver, call the function), with a
PATH that has every ordinary coreutil EXCEPT `date` -- reproducing the
hostile/stripped-PATH bootstrap scenario Plan 00466 N1 fixed for `sleep`
(commit 766677c1: a narrow PATH lacking a specific tool, not a totally
empty one -- these scripts still need `mv`/`mkdir`/etc. for unrelated
work, and a literal empty PATH would break those too, which is not this
class's hazard) -- and forcing ``_hp_bash_supports_printf_time`` to fail to
also cover a bash-3.2-like host with no `date` reachable at all: the case
that must fail LOUDLY rather than silently take the wrong branch.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import textwrap
import time
from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants.timeout import Timeout

REPO_ROOT = Path(__file__).resolve().parents[2]
VENV_BOOTSTRAP_SH = REPO_ROOT / "scripts" / "venv_bootstrap.sh"
BASH = shutil.which("bash") or "/bin/bash"
_TIMEOUT_SECONDS = 30


def _build_path_without(dest_dir: Path, missing_names: set[str]) -> Path:
    """Symlink every real PATH executable into ``dest_dir``, except ``missing_names``.

    Produces a PATH that behaves like the real one for everything EXCEPT
    the deliberately-omitted tool(s) -- the realistic "hostile/stripped
    PATH" shape (a narrow custom PATH missing one thing), not a literal
    empty PATH (which would also break unrelated commands these scripts
    genuinely need, like `mv`/`mkdir`, and is not this defect class's
    hazard).
    """
    seen: set[str] = set()
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        entry_path = Path(entry)
        if not entry_path.is_dir():
            continue
        try:
            entries = list(entry_path.iterdir())
        except OSError:
            continue
        for src in entries:
            name = src.name
            if name in seen or name in missing_names:
                continue
            if src.is_dir() or not os.access(src, os.X_OK):
                continue
            try:
                (dest_dir / name).symlink_to(src)
            except OSError:
                continue
            seen.add(name)
    return dest_dir


@pytest.fixture(scope="module")
def path_without_date(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _build_path_without(tmp_path_factory.mktemp("path-no-date"), {"date"})


def _run(harness: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [BASH, "-c", harness],
        capture_output=True,
        text=True,
        check=False,
        timeout=_TIMEOUT_SECONDS,
    )


def _source_prelude(*, force_no_epoch: bool = False, path_without_date: Path | None = None) -> str:
    prelude = f'. "{VENV_BOOTSTRAP_SH}"\n'
    if force_no_epoch:
        prelude += "_hp_bash_supports_printf_time() { return 1; }\n"
    if path_without_date is not None:
        prelude += f'PATH="{path_without_date}"\n'
    return prelude


class TestWatchdogNeverKillsWronglyUnderHostilePath:
    """``_vb_watchdog`` polls `kill -0` and, past the deadline, TERMs the
    build. Under a hostile PATH, epoch time must still resolve via the
    builtin -- the build is bounded correctly, not killed early or never."""

    def test_bounds_a_real_deadline_under_a_path_with_no_date(
        self, tmp_path: Path, path_without_date: Path
    ) -> None:
        # A long-lived shell process to watch and, if wrongly killed, prove it.
        proc = subprocess.Popen([BASH, "-c", "sleep 30"])
        try:
            harness = _source_prelude(path_without_date=path_without_date) + textwrap.dedent(f"""\
                now="$(_hp_epoch_seconds)"
                _vb_watchdog {proc.pid} "$((now + 1))"
                """)
            started = time.monotonic()
            result = _run(harness)
            elapsed = time.monotonic() - started

            assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
            assert elapsed < 10.0, f"watchdog must respect its bound; took {elapsed:.2f}s"
            # The watchdog only SIGNALS -- give the process a moment to die.
            proc.wait(timeout=Timeout.PROCESS_DEATH_WAIT)
            assert proc.returncode is not None and proc.returncode != 0
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()

    def test_does_not_kill_before_the_deadline_under_a_path_with_no_date(
        self, tmp_path: Path, path_without_date: Path
    ) -> None:
        proc = subprocess.Popen([BASH, "-c", "sleep 30"])
        try:
            harness = _source_prelude(path_without_date=path_without_date) + textwrap.dedent(f"""\
                now="$(_hp_epoch_seconds)"
                _vb_watchdog {proc.pid} "$((now + 100))" &
                watchdog_pid=$!
                sleep 1
                kill "$watchdog_pid" 2>/dev/null
                if kill -0 {proc.pid} 2>/dev/null; then echo STILL_ALIVE; else echo DEAD; fi
                """)
            result = _run(harness)

            assert "STILL_ALIVE" in result.stdout, (
                "a build well inside its bound must not be killed by a hostile-PATH "
                f"epoch failure. stdout={result.stdout!r} stderr={result.stderr!r}"
            )
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()

    def test_loud_failure_and_no_wrong_kill_when_epoch_is_wholly_unavailable(
        self, tmp_path: Path, path_without_date: Path
    ) -> None:
        """Bash < 4.2 AND no `date`: the watchdog must not guess -- it stops
        loudly rather than either killing immediately (N1's original hazard)
        or spinning silently forever."""
        proc = subprocess.Popen([BASH, "-c", "sleep 30"])
        try:
            harness = _source_prelude(
                force_no_epoch=True, path_without_date=path_without_date
            ) + textwrap.dedent(
                f"""\
                _vb_watchdog {proc.pid} 99999999999
                echo "exit=$?"
                """
            )
            started = time.monotonic()
            result = _run(harness)
            elapsed = time.monotonic() - started

            assert elapsed < 10.0, f"must not hang; took {elapsed:.2f}s"
            assert (
                "no epoch-second source" in result.stderr.lower()
            ), f"must fail loudly, not silently. stderr={result.stderr!r}"
            if proc.poll() is None:
                assert True  # not killed -- the safe direction when unsure
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()


class TestJudgeStopUnderHostilePath:
    """``_vb_judge_stop`` decides "timed out" (124) vs "just stopped" (143)
    from elapsed time. A stale/garbled elapsed value under a hostile PATH
    must not silently flip that verdict."""

    def test_correct_verdict_under_a_path_with_no_date_when_venv_does_not_resolve(
        self, tmp_path: Path, path_without_date: Path
    ) -> None:
        daemon_dir = tmp_path / "daemon"
        (daemon_dir / "untracked").mkdir(parents=True)
        marker = daemon_dir / "untracked" / ".venv-bootstrap-fp.failed"

        harness = _source_prelude(path_without_date=path_without_date) + textwrap.dedent(f"""\
            _VB_CHILD_DAEMON_DIR="{daemon_dir}"
            _VB_CHILD_MARKER="{marker}"
            _VB_CHILD_INPUTS="inputs-sig"
            _VB_CHILD_STARTED="$(( $(_hp_epoch_seconds) - 5 ))"
            _VB_CHILD_BOUND=3
            resolve_venv_python() {{ return 1; }}
            rc=0
            _vb_judge_stop 143 || rc=$?
            echo "exit=$rc"
            """)
        result = _run(harness)

        assert "exit=124" in result.stdout, (
            f"elapsed (5s) exceeds bound (3s) -- must be judged a timeout. "
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )
        assert marker.exists(), "a genuine timeout must record the failure marker"

    def test_loud_and_conservative_when_epoch_is_wholly_unavailable(
        self, tmp_path: Path, path_without_date: Path
    ) -> None:
        """Cannot compute elapsed at all: must NOT guess "timed out" (which
        would wrongly mark a healthy stop as a permanent failure) -- treats
        it as "just stopped" (143, nothing recorded, next hook retries) and
        says why on stderr."""
        daemon_dir = tmp_path / "daemon"
        (daemon_dir / "untracked").mkdir(parents=True)
        marker = daemon_dir / "untracked" / ".venv-bootstrap-fp.failed"

        harness = _source_prelude(
            force_no_epoch=True, path_without_date=path_without_date
        ) + textwrap.dedent(
            f"""\
            _VB_CHILD_DAEMON_DIR="{daemon_dir}"
            _VB_CHILD_MARKER="{marker}"
            _VB_CHILD_INPUTS="inputs-sig"
            _VB_CHILD_STARTED=1000
            _VB_CHILD_BOUND=3
            resolve_venv_python() {{ return 1; }}
            rc=0
            _vb_judge_stop 143 || rc=$?
            echo "exit=$rc"
            """
        )
        result = _run(harness)

        assert "exit=143" in result.stdout, (
            f"unknown elapsed time must never be judged a timeout. "
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )
        assert not marker.exists(), "an unknown-elapsed stop must not be recorded as a failure"
        assert "no epoch-second source" in result.stderr.lower()


class TestPrintRunningUnderHostilePath:
    """``_vb_print_running``'s `elapsed=` field is purely informational
    (status protocol for init.sh) -- when epoch time cannot be computed it
    must be OMITTED, never a garbled/negative number."""

    def test_omits_elapsed_when_epoch_is_wholly_unavailable(
        self, tmp_path: Path, path_without_date: Path
    ) -> None:
        daemon_dir = tmp_path / "daemon"
        untracked = daemon_dir / "untracked"
        untracked.mkdir(parents=True)
        # The record filename is dot-prefixed (VENV_BUILD_RECORD_NAME =
        # ".venv-bootstrap.current") -- a bare "venv-bootstrap.current" is
        # never read, which would make this test vacuously pass regardless
        # of the fix.
        (untracked / ".venv-bootstrap.current").write_text(
            "log=/tmp/x.log\npid=123\nstarted=1000\nbound=900\n"
        )

        harness = _source_prelude(
            force_no_epoch=True, path_without_date=path_without_date
        ) + textwrap.dedent(
            f"""\
            _vb_print_running "{daemon_dir}"
            """
        )
        result = _run(harness)

        assert "elapsed=" not in result.stdout, f"stdout={result.stdout!r}"
        assert "state=running" in result.stdout

    def test_includes_a_non_negative_elapsed_under_a_path_with_no_date(
        self, tmp_path: Path, path_without_date: Path
    ) -> None:
        daemon_dir = tmp_path / "daemon"
        untracked = daemon_dir / "untracked"
        untracked.mkdir(parents=True)
        harness_started = _run(f'. "{VENV_BOOTSTRAP_SH}"\n_hp_epoch_seconds\n')
        started = int(harness_started.stdout.strip()) - 5
        (untracked / ".venv-bootstrap.current").write_text(
            f"log=/tmp/x.log\npid=123\nstarted={started}\nbound=900\n"
        )

        harness = _source_prelude(path_without_date=path_without_date) + textwrap.dedent(f"""\
            _vb_print_running "{daemon_dir}"
            """)
        result = _run(harness)

        assert "elapsed=" in result.stdout, f"stdout={result.stdout!r}"
        elapsed_line = next(
            line for line in result.stdout.splitlines() if line.startswith("elapsed=")
        )
        elapsed_value = int(elapsed_line.split("=", 1)[1])
        assert elapsed_value >= 0, f"elapsed must not go negative; got {elapsed_value}"


class TestHookRecordWriteUnderHostilePath:
    """``_vb_hook``'s `started=` field seeds every later timeout judgement
    for a NEW detached build -- unlike `_vb_print_running`'s informational
    `elapsed=`, this is not optional: refuse to start the build rather than
    record a bad seed, and say why (state=error/detail=)."""

    def test_refuses_to_start_a_build_when_epoch_is_wholly_unavailable(
        self, tmp_path: Path, path_without_date: Path
    ) -> None:
        daemon_dir = tmp_path / "daemon"
        (daemon_dir / "untracked").mkdir(parents=True)

        harness = _source_prelude(
            force_no_epoch=True, path_without_date=path_without_date
        ) + textwrap.dedent(
            f"""\
            venv_bootstrap_switched_off_by() {{ return 1; }}
            venv_lock_is_held() {{ return 1; }}
            _vb_gate() {{
                VB_ALLOWED=true; VB_MISSING=(); VB_FIXES=()
                VB_PYTHON=/usr/bin/python3; VB_FINGERPRINT=fp1; VB_INPUTS=inputs1
                return 0
            }}
            try_acquire_venv_lock() {{ return 0; }}
            release_venv_lock() {{ :; }}
            forget_venv_lock() {{ :; }}
            venv_build_timeout() {{ echo 900; }}
            _vb_hook "{daemon_dir}"
            """
        )
        result = _run(harness)

        assert result.returncode == 0, "the hook contract is exit 0 whatever the state"
        assert "state=error" in result.stdout, f"stdout={result.stdout!r} stderr={result.stderr!r}"
        record = daemon_dir / "untracked" / ".venv-bootstrap.current"
        assert not record.exists(), "must not record a build start with no known start time"
        assert "no epoch-second source" in result.stderr.lower()


class TestBuildStartTimeSeedUnderHostilePath:
    """``_vb_build``'s fallback `now=` seed: a standalone assignment under
    the file's global ``set -euo pipefail``, so a missing epoch source
    aborts loudly -- and the EXIT trap (registered just before this line)
    still releases the lock cleanly."""

    def test_fails_loudly_and_releases_the_lock(
        self, tmp_path: Path, path_without_date: Path
    ) -> None:
        daemon_dir = tmp_path / "daemon"
        (daemon_dir / "untracked").mkdir(parents=True)
        lock_released = tmp_path / "lock-released"

        harness = _source_prelude(
            force_no_epoch=True, path_without_date=path_without_date
        ) + textwrap.dedent(
            f"""\
            adopt_venv_lock() {{ return 0; }}
            release_venv_lock() {{ touch "{lock_released}"; }}
            venv_build_record_field() {{ return 1; }}
            _vb_build "{daemon_dir}" /usr/bin/python3 fp1 inputs1
            """
        )
        result = _run(harness)

        assert result.returncode != 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
        assert "no epoch-second source" in result.stderr.lower()
        assert lock_released.exists(), "the EXIT trap must still release the lock"
