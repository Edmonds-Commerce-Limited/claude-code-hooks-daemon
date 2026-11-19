"""The shared upgrade lock (Plan 00625 Phase 3, DESIGN.md section 6).

``scripts/upgrade.sh`` (Layer 1) and ``provision.sh`` each carry the lock as a
block of functions between ``# BEGIN upgrade-lock`` and ``# END upgrade-lock``.
Each script is fetched or deployed standalone, so neither can source the other;
a lockstep test pins the two blocks identical. The behaviour tests lift the
block verbatim out of ``upgrade.sh`` and run it in real bash against real lock
files, with real processes standing in for owners.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Final

import pytest

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_UPGRADE_SH: Final[Path] = _REPO_ROOT / "scripts" / "upgrade.sh"
_PROVISION_SH: Final[Path] = _REPO_ROOT / "provision.sh"
_BASH: Final[str] = shutil.which("bash") or "/bin/bash"
_TIMEOUT_SECONDS: Final[int] = 60
_BEGIN: Final[str] = "# BEGIN upgrade-lock"
_END: Final[str] = "# END upgrade-lock"

_NOW_FOREIGN: Final[str] = "foreign-boot-id-0000"


def _block(script: Path) -> str:
    """The lock block of ``script``, lifted verbatim, marker lines included."""
    text = script.read_text(encoding="utf-8")
    start = text.index(_BEGIN)
    end = text.index(_END, start)
    return text[start : text.index("\n", end) + 1]


def _bash(body: str, *, lock_env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    script = "\n".join(["set -euo pipefail", _block(_UPGRADE_SH), body])
    return subprocess.run(
        [_BASH, "-c", script],
        capture_output=True,
        text=True,
        check=False,
        timeout=_TIMEOUT_SECONDS,
        env={**os.environ, **(lock_env or {})},
    )


def _proc_start(pid: int) -> str:
    stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    return stat.rsplit(") ", 1)[1].split()[19]


def _boot_id() -> str:
    return Path("/proc/sys/kernel/random/boot_id").read_text(encoding="utf-8").strip()


def _pidns() -> str:
    return str(Path("/proc/self/ns/pid").readlink())


def _dead_pid() -> int:
    return int(Path("/proc/sys/kernel/pid_max").read_text(encoding="utf-8")) + 1


def _record(lock: Path, **overrides: str | int) -> dict[str, str]:
    """Write an owner record for a holder that looks like this very process."""
    fields: dict[str, str] = {
        "token": "other-token",
        "host": "some-host",
        "boot_id": _boot_id(),
        "pidns": _pidns(),
        "pid": str(os.getpid()),
        "pid_start": _proc_start(os.getpid()),
        "started": str(int(time.time())),
        "purpose": "upgrade",
    }
    fields.update({key: str(value) for key, value in overrides.items()})
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text("".join(f"{k}={v}\n" for k, v in fields.items()), encoding="utf-8")
    return fields


def _token_of(lock: Path) -> str:
    for line in lock.read_text(encoding="utf-8").splitlines():
        if line.startswith("token="):
            return line.split("=", 1)[1]
    raise AssertionError(f"no token in {lock}")


_ACQUIRE = 'rc=0; _upgrade_lock_acquire "$LOCK" "{purpose}" {wait} || rc=$?; echo "rc=$rc"\n'


def _acquire_body(lock: Path, *, purpose: str = "upgrade", wait: int = 0, then: str = "") -> str:
    return (
        f'LOCK="{lock}"\n'
        + _ACQUIRE.format(purpose=purpose, wait=wait)
        + then
        + '_upgrade_lock_release\necho "released"\n'
    )


class TestLockstep:
    def test_the_two_scripts_carry_identical_lock_blocks(self) -> None:
        assert _block(_UPGRADE_SH) == _block(_PROVISION_SH)

    def test_the_deployed_provision_copy_is_the_same_file(self) -> None:
        deployed = _REPO_ROOT / ".claude" / "provision.sh"
        assert deployed.read_bytes() == _PROVISION_SH.read_bytes()

    def test_the_block_never_signals_a_process(self) -> None:
        """Layer 1 signals no process (test_upgrade_sh_stop_bootstrap.py)."""
        for line in _block(_UPGRADE_SH).splitlines():
            if not line.lstrip().startswith("#"):
                assert "kill" not in line.split(), line


class TestLockPath:
    def test_it_is_inside_the_git_common_dir(self, tmp_path: Path) -> None:
        project = tmp_path / "proj"
        project.mkdir()
        subprocess.run(["git", "-C", str(project), "init", "-q"], check=True)

        result = _bash(f'_upgrade_lock_path "{project}"')

        assert result.stdout.strip() == f"{project.resolve()}/.git/hooks-daemon-upgrade.lock"

    def test_a_worktree_shares_its_repositorys_lock(self, tmp_path: Path) -> None:
        project = tmp_path / "proj"
        project.mkdir()
        git = ["git", "-C", str(project)]
        subprocess.run([*git, "init", "-q", "-b", "main"], check=True)
        identity = ["-c", "user.name=t", "-c", "user.email=t@x.invalid"]
        subprocess.run(
            [*git, *identity, "commit", "-q", "--allow-empty", "-m", "x"], check=True
        )
        worktree = tmp_path / "wt"
        subprocess.run([*git, "worktree", "add", "-q", str(worktree)], check=True)

        main = _bash(f'_upgrade_lock_path "{project}"').stdout.strip()
        other = _bash(f'_upgrade_lock_path "{worktree}"').stdout.strip()

        assert main == other
        assert Path(main).is_absolute()

    def test_a_directory_that_is_not_a_repository_falls_back_to_dot_claude(
        self, tmp_path: Path
    ) -> None:
        result = _bash(f'_upgrade_lock_path "{tmp_path}"')

        assert result.stdout.strip() == f"{tmp_path}/.claude/hooks-daemon-upgrade.lock"


class TestAcquireAndRelease:
    def test_acquire_writes_the_owner_record_and_a_heartbeat(self, tmp_path: Path) -> None:
        lock = tmp_path / "x.lock"
        body = _acquire_body(
            lock,
            purpose="provision-sync",
            then=f'cat "{lock}"; test -f "{lock}.beat" && echo beat-present\n',
        )

        result = _bash(body)

        assert "rc=0" in result.stdout, result.stderr
        assert "beat-present" in result.stdout
        fields = dict(
            line.split("=", 1)
            for line in result.stdout.splitlines()
            if "=" in line and not line.startswith("rc=")
        )
        assert fields["purpose"] == "provision-sync"
        assert fields["boot_id"] == _boot_id()
        assert fields["pidns"] == _pidns()
        assert fields["pid"].isdigit() and fields["pid_start"].isdigit()
        assert fields["host"] and fields["token"] and fields["started"].isdigit()

    def test_release_leaves_no_lock_and_no_heartbeat_file(self, tmp_path: Path) -> None:
        lock = tmp_path / "x.lock"

        result = _bash(_acquire_body(lock))

        assert "rc=0" in result.stdout and "released" in result.stdout, result.stderr
        assert list(tmp_path.iterdir()) == []

    def test_a_lock_carrying_another_token_is_not_removed_by_our_release(
        self, tmp_path: Path
    ) -> None:
        lock = tmp_path / "x.lock"
        body = _acquire_body(
            lock,
            then=f'printf "token=somebody-else\\npid=1\\n" > "{lock}"\n',
        )

        result = _bash(body)

        assert "released" in result.stdout, result.stderr
        assert lock.read_text(encoding="utf-8").startswith("token=somebody-else")

    def test_a_held_lock_is_reported_with_its_holder_and_left_alone(self, tmp_path: Path) -> None:
        lock = tmp_path / "x.lock"
        _record(lock, host="builder-7", purpose="provision-sync")
        before = lock.read_text(encoding="utf-8")

        result = _bash(_acquire_body(lock, then='echo "holder=$_UPGRADE_LOCK_HOLDER"\n'))

        assert "rc=1" in result.stdout, result.stderr
        assert "builder-7" in result.stdout and "provision-sync" in result.stdout
        assert f"pid={os.getpid()}" in result.stdout
        assert lock.read_text(encoding="utf-8") == before, "another owner's lock is never removed"

    def test_wait_polls_until_the_holder_releases(self, tmp_path: Path) -> None:
        lock = tmp_path / "x.lock"
        _record(lock)
        waiter = subprocess.Popen(
            [_BASH, "-c", "\n".join(["set -euo pipefail", _block(_UPGRADE_SH),
                                     _acquire_body(lock, wait=20)])],
            stdout=subprocess.PIPE,
            text=True,
        )
        time.sleep(1.5)
        lock.unlink()

        out, _ = waiter.communicate(timeout=_TIMEOUT_SECONDS)

        assert "rc=0" in out

    def test_wait_gives_up_when_the_holder_never_releases(self, tmp_path: Path) -> None:
        lock = tmp_path / "x.lock"
        _record(lock)

        started = time.monotonic()
        result = _bash(_acquire_body(lock, wait=2))

        assert "rc=1" in result.stdout
        assert 1.5 <= time.monotonic() - started < 15


class TestHeartbeat:
    def test_the_beat_is_rewritten_while_the_owner_lives(self, tmp_path: Path) -> None:
        lock = tmp_path / "x.lock"
        body = _acquire_body(
            lock,
            then=(
                f'first="$(cat "{lock}.beat")"; sleep 4; second="$(cat "{lock}.beat")"\n'
                'echo "first=$first second=$second"\n'
            ),
        )

        result = _bash("_UPGRADE_LOCK_HEARTBEAT_SECONDS=2\n" + body)

        line = next(item for item in result.stdout.splitlines() if item.startswith("first="))
        first, second = (int(part.split("=")[1]) for part in line.split())
        assert second > first, result.stderr

    def test_the_heartbeat_stops_when_its_owner_is_killed(self, tmp_path: Path) -> None:
        lock = tmp_path / "x.lock"
        body = (
            f'LOCK="{lock}"\n_upgrade_lock_acquire "$LOCK" upgrade 0\n'
            'echo "hb=$_UPGRADE_LOCK_HEARTBEAT_PID"\n'
            'echo "owner=$$"\n'
            "while :; do sleep 1; done\n"
        )
        owner = subprocess.Popen(
            [_BASH, "-c", "\n".join(["set -euo pipefail", _block(_UPGRADE_SH), body])],
            stdout=subprocess.PIPE,
            text=True,
        )
        assert owner.stdout is not None
        heartbeat = int(owner.stdout.readline().split("=")[1])
        assert Path(f"/proc/{heartbeat}").exists()

        owner.kill()
        owner.wait(timeout=_TIMEOUT_SECONDS)
        deadline = time.monotonic() + 10
        while Path(f"/proc/{heartbeat}").exists() and time.monotonic() < deadline:
            time.sleep(0.2)

        assert not Path(f"/proc/{heartbeat}").exists(), "a killed owner stops beating"


class TestStaleRule:
    """The same-kernel proof of death, and the expiry for everything else."""

    def test_a_foreign_boot_with_a_fresh_beat_is_never_taken_over(self, tmp_path: Path) -> None:
        lock = tmp_path / "x.lock"
        _record(lock, boot_id=_NOW_FOREIGN, pid=_dead_pid(), started=int(time.time()) - 5000)
        Path(f"{lock}.beat").write_text(f"{int(time.time())}\n", encoding="utf-8")

        result = _bash(_acquire_body(lock))

        assert "rc=1" in result.stdout, result.stderr
        assert _token_of(lock) == "other-token"

    def test_a_foreign_pid_namespace_with_a_fresh_beat_is_never_taken_over(
        self, tmp_path: Path
    ) -> None:
        lock = tmp_path / "x.lock"
        _record(lock, pidns="pid:[4026539999]", pid=_dead_pid(), started=int(time.time()) - 5000)
        Path(f"{lock}.beat").write_text(f"{int(time.time())}\n", encoding="utf-8")

        result = _bash(_acquire_body(lock))

        assert "rc=1" in result.stdout, result.stderr

    def test_a_foreign_holder_with_an_expired_beat_is_taken_over(self, tmp_path: Path) -> None:
        lock = tmp_path / "x.lock"
        old = int(time.time()) - 5000
        _record(lock, boot_id=_NOW_FOREIGN, started=old)
        Path(f"{lock}.beat").write_text(f"{old}\n", encoding="utf-8")

        result = _bash(_acquire_body(lock, then=f'echo "mine=$(grep -c . "{lock}")"\n'))

        assert "rc=0" in result.stdout, result.stderr
        assert list(tmp_path.iterdir()) == [], "taken over, then released"

    def test_a_foreign_holder_without_any_beat_is_judged_by_its_start_time(
        self, tmp_path: Path
    ) -> None:
        lock = tmp_path / "x.lock"
        _record(lock, boot_id=_NOW_FOREIGN, started=int(time.time()) - 60)

        assert "rc=1" in _bash(_acquire_body(lock)).stdout

    def test_a_same_namespace_holder_whose_pid_is_gone_is_taken_over_at_once(
        self, tmp_path: Path
    ) -> None:
        lock = tmp_path / "x.lock"
        _record(lock, pid=_dead_pid(), pid_start="12345", started=int(time.time()))

        result = _bash(_acquire_body(lock))

        assert "rc=0" in result.stdout, result.stderr

    def test_a_same_namespace_pid_that_was_reused_is_taken_over(self, tmp_path: Path) -> None:
        lock = tmp_path / "x.lock"
        _record(lock, pid_start="1", started=int(time.time()))

        result = _bash(_acquire_body(lock))

        assert "rc=0" in result.stdout, result.stderr

    def test_a_same_namespace_live_owner_is_held_even_with_an_old_start(
        self, tmp_path: Path
    ) -> None:
        lock = tmp_path / "x.lock"
        _record(lock, started=int(time.time()) - 5000)

        assert "rc=1" in _bash(_acquire_body(lock)).stdout

    def test_a_half_written_record_is_held_until_it_expires(self, tmp_path: Path) -> None:
        lock = tmp_path / "x.lock"
        lock.write_text("", encoding="utf-8")

        assert "rc=1" in _bash(_acquire_body(lock)).stdout
        assert lock.exists()

        old = time.time() - 5000
        os.utime(lock, (old, old))

        assert "rc=0" in _bash(_acquire_body(lock)).stdout

    def test_a_live_takers_generation_means_busy(self, tmp_path: Path) -> None:
        lock = tmp_path / "x.lock"
        _record(lock, pid=_dead_pid(), pid_start="1")
        # A taker that is alive (this test process) holds generation 1.
        _record(Path(f"{lock}.takeover.1"), token="taker")

        assert "rc=1" in _bash(_acquire_body(lock)).stdout, "a live taker means busy"
        assert lock.exists()

    def test_a_half_written_generation_is_busy_until_it_is_old(self, tmp_path: Path) -> None:
        lock = tmp_path / "x.lock"
        takeover = Path(f"{lock}.takeover.1")
        _record(lock, pid=_dead_pid(), pid_start="1")
        takeover.write_text("someone\n", encoding="utf-8")

        assert "rc=1" in _bash(_acquire_body(lock)).stdout, "a fresh takeover file means busy"

        old = time.time() - 120
        os.utime(takeover, (old, old))

        assert "rc=0" in _bash(_acquire_body(lock)).stdout

    def test_a_dead_takers_generation_is_passed_over_and_never_removed(
        self, tmp_path: Path
    ) -> None:
        lock = tmp_path / "x.lock"
        takeover = Path(f"{lock}.takeover.1")
        _record(lock, pid=_dead_pid(), pid_start="1")
        _record(takeover, token="crashed-taker", pid=_dead_pid(), pid_start="1")

        result = _bash(_acquire_body(lock))

        assert "rc=0" in result.stdout, result.stderr
        assert takeover.exists(), "another process's takeover file is never removed"
        assert not Path(f"{lock}.takeover.2").exists(), "the taker removes its own generation"


_RACER = r"""
LOCK="{lock}"
while [ ! -e "{go}" ]; do sleep 0.01; done
rc=0; _upgrade_lock_acquire "$LOCK" upgrade 0 || rc=$?
if [ "$rc" -eq 0 ]; then
    echo WON
    while [ ! -e "{done}" ]; do sleep 0.05; done
    _upgrade_lock_release
else
    echo HELD
fi
"""


def _race(tmp_path: Path, lock: Path, racers: int) -> list[str]:
    go, done = tmp_path / "go", tmp_path / "done"
    script = "\n".join(
        ["set -euo pipefail", _block(_UPGRADE_SH), _RACER.format(lock=lock, go=go, done=done)]
    )
    procs = [
        subprocess.Popen([_BASH, "-c", script], stdout=subprocess.PIPE, text=True)
        for _ in range(racers)
    ]
    go.write_text("go", encoding="utf-8")
    deadline = time.monotonic() + 30
    while sum(p.poll() is not None for p in procs) < racers - 1 and time.monotonic() < deadline:
        time.sleep(0.05)
    done.write_text("done", encoding="utf-8")
    results = []
    for proc in procs:
        out, _ = proc.communicate(timeout=_TIMEOUT_SECONDS)
        results.append(out.strip())
    return results


class TestConcurrentTakers:
    def test_exactly_one_of_many_wins_a_free_lock(self, tmp_path: Path) -> None:
        results = _race(tmp_path, tmp_path / "x.lock", 8)

        assert results.count("WON") == 1, results
        assert results.count("HELD") == 7, results

    def test_exactly_one_of_many_takes_over_a_dead_holders_lock(self, tmp_path: Path) -> None:
        lock = tmp_path / "x.lock"
        _record(lock, pid=_dead_pid(), pid_start="1")

        results = _race(tmp_path, lock, 8)

        assert results.count("WON") == 1, results
        assert results.count("HELD") == 7, results


_TIMED_RACER = r"""
LOCK="{lock}"
while [ ! -e "{go}" ]; do sleep 0.01; done
rc=0; _upgrade_lock_acquire "$LOCK" upgrade 0 || rc=$?
if [ "$rc" -eq 0 ]; then
    echo "GOT $(date +%s.%N)"
    sleep {hold}
    echo "REL $(date +%s.%N)"
    _upgrade_lock_release
else
    echo "MISS rc=$rc"
fi
"""


def _max_overlap(intervals: list[tuple[float, float]]) -> int:
    events = sorted([(start, 1) for start, _ in intervals] + [(end, -1) for _, end in intervals])
    current = peak = 0
    for _, step in events:
        current += step
        peak = max(peak, current)
    return peak


def _seed_crashed_takeover(lock: Path) -> None:
    """The state a taker leaves when it is killed inside its critical section:
    a dead holder's lock and a takeover file nobody will remove, backdated
    past the takeover staleness. Seeded under both the single-file name and
    the first generation name, so the test means the same against either."""
    _record(lock, pid=_dead_pid(), pid_start="1")
    old = time.time() - 120
    for name in (f"{lock}.takeover", f"{lock}.takeover.1"):
        Path(name).write_text("crashed\n", encoding="utf-8")
        os.utime(name, (old, old))


class TestAStaleTakeoverNeverLetsTwoHold:
    """Adversarial review F1: a contender broke a stale takeover file by path
    after an age check, which could delete a fresh one another contender had
    just created, so both went on to replace the lock and both held it (7 of
    15 trials with 20 racers)."""

    _RACERS: Final[int] = 20
    _TRIALS: Final[int] = 30
    _HOLD: Final[float] = 0.5

    def _trial(self, tmp_path: Path) -> list[str]:
        lock = tmp_path / "x.lock"
        _seed_crashed_takeover(lock)
        go = tmp_path / "go"
        script = "\n".join(
            [
                "set -euo pipefail",
                _block(_UPGRADE_SH),
                _TIMED_RACER.format(lock=lock, go=go, hold=self._HOLD),
            ]
        )
        procs = [
            subprocess.Popen([_BASH, "-c", script], stdout=subprocess.PIPE, text=True)
            for _ in range(self._RACERS)
        ]
        go.write_text("go", encoding="utf-8")
        lines: list[str] = []
        for proc in procs:
            out, _ = proc.communicate(timeout=_TIMEOUT_SECONDS)
            lines.extend(out.splitlines())
        return lines

    def test_never_two_holders_at_once_across_many_trials(self, tmp_path: Path) -> None:
        peaks: list[int] = []
        winners: list[int] = []
        for trial in range(self._TRIALS):
            trial_dir = tmp_path / f"t{trial}"
            trial_dir.mkdir()
            lines = self._trial(trial_dir)
            got = [float(line.split()[1]) for line in lines if line.startswith("GOT ")]
            rel = [float(line.split()[1]) for line in lines if line.startswith("REL ")]
            peaks.append(_max_overlap(list(zip(sorted(got), sorted(rel), strict=True))))
            winners.append(len(got))

        assert max(peaks) == 1, f"peak holders per trial {peaks}, winners per trial {winners}"
        assert min(winners) >= 1, f"a crashed takeover must not block for ever: {winners}"


_OUTER = r"""
LOCK="{lock}"
_upgrade_lock_acquire "$LOCK" upgrade 0
trap '_upgrade_lock_release' EXIT
_upgrade_lock_hold_through_signals
echo "OUTER $$"
rc=0
_upgrade_lock_run_writer "{bash}" -c 'echo "$$" > "{started}"; sleep {hold}; echo done > "{finished}"' > /dev/null 2>&1 || rc=$?
echo "writer rc=$rc"
"""


def _second_acquire(lock: Path) -> str:
    return _bash(
        f'LOCK="{lock}"\nrc=0; _upgrade_lock_acquire "$LOCK" second 0 || rc=$?\n'
        'echo "rc=$rc"\nif [ "$rc" -eq 0 ]; then _upgrade_lock_release; fi\n'
    ).stdout


class TestTheWriterHoldsTheLock:
    """Adversarial review F2: Layer 1 owned the lock, but its child Layer 2 does
    the writing. SIGTERM to Layer 1 ran its EXIT trap and released the lock
    while Layer 2 went on writing, and a SIGKILL left a dead owner whose lock
    a second upgrader took over at once."""

    _HOLD: Final[int] = 4

    def _start_outer(self, tmp_path: Path) -> tuple[subprocess.Popen[str], Path, Path, Path]:
        lock = tmp_path / "x.lock"
        started, finished = tmp_path / "writer.pid", tmp_path / "writer.done"
        body = _OUTER.format(
            lock=lock, bash=_BASH, started=started, finished=finished, hold=self._HOLD
        )
        outer = subprocess.Popen(
            [_BASH, "-c", "\n".join(["set -euo pipefail", _block(_UPGRADE_SH), body])],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        deadline = time.monotonic() + 20
        while not started.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert started.exists(), "the writer never started"
        return outer, lock, started, finished

    def test_the_record_names_the_writer(self, tmp_path: Path) -> None:
        outer, lock, started, _ = self._start_outer(tmp_path)
        writer = started.read_text(encoding="utf-8").strip()
        record = lock.read_text(encoding="utf-8")
        writer_start = _proc_start(int(writer))
        outer.communicate(timeout=_TIMEOUT_SECONDS)

        assert f"writer={writer}\n" in record
        assert _proc_start_or_empty(record) == writer_start

    def test_sigterm_to_the_owner_keeps_the_lock_until_the_writer_ends(
        self, tmp_path: Path
    ) -> None:
        outer, lock, _, finished = self._start_outer(tmp_path)
        outer.terminate()
        time.sleep(1.0)

        assert lock.exists(), "a signalled owner released the lock under a live writer"
        assert "rc=1" in _second_acquire(lock)

        outer.communicate(timeout=_TIMEOUT_SECONDS)
        assert finished.exists(), "the writer was cut short"
        assert outer.returncode == 143
        assert not lock.exists(), "the lock is released once the writer has finished"

    def test_sigkill_of_the_owner_leaves_the_lock_held_while_the_writer_lives(
        self, tmp_path: Path
    ) -> None:
        outer, lock, _, finished = self._start_outer(tmp_path)
        outer.kill()
        outer.communicate(timeout=_TIMEOUT_SECONDS)
        time.sleep(0.5)

        assert not finished.exists()
        assert "rc=1" in _second_acquire(lock), "the dead owner's live writer must hold the lock"

        deadline = time.monotonic() + self._HOLD + 10
        while not finished.exists() and time.monotonic() < deadline:
            time.sleep(0.1)
        time.sleep(0.5)
        assert "rc=0" in _second_acquire(lock), "once the writer is gone the lock is free"

    def test_a_writer_whose_lock_is_not_ours_never_runs(self, tmp_path: Path) -> None:
        lock = tmp_path / "x.lock"
        ran = tmp_path / "ran"
        body = (
            f'LOCK="{lock}"\n_upgrade_lock_acquire "$LOCK" upgrade 0\n'
            f"printf 'token=someone-else\\n' > \"$LOCK\"\n"
            f'rc=0; _upgrade_lock_run_writer touch "{ran}" || rc=$?\necho "rc=$rc"\n'
        )

        result = _bash(body)

        assert "rc=75" in result.stdout, result.stdout + result.stderr
        assert not ran.exists()


def _proc_start_or_empty(record: str) -> str:
    for line in record.splitlines():
        if line.startswith("writer_start="):
            return line.split("=", 1)[1]
    return "<missing>"


class TestTakeoverNeverRemovesAFreshLock:
    """The re-judge under the takeover file must not delete a lock it did not judge."""

    def test_a_lock_that_vanished_at_rejudge_is_not_removed_when_a_fresh_one_appears(
        self, tmp_path: Path
    ) -> None:
        lock = tmp_path / "x.lock"
        _record(lock, pid=_dead_pid(), pid_start="1")
        body = f"""
LOCK="{lock}"
_upgrade_lock_judge() {{
    rm -f "$LOCK"
    printf 'token=fresh-holder\\npid=1\\nstarted=%s\\n' "$(date +%s)" > "$LOCK"
    return 2
}}
rc=0
_upgrade_lock_takeover "$LOCK" "mine" "token=mine" || rc=$?
echo "rc=$rc"
"""
        result = _bash(body)

        assert "rc=0" not in result.stdout, result.stdout + result.stderr
        assert "fresh-holder" in lock.read_text(encoding="utf-8")
        assert not (tmp_path / "x.lock.takeover").exists()

    def test_a_lock_replaced_between_judge_and_removal_is_left_alone(self, tmp_path: Path) -> None:
        lock = tmp_path / "x.lock"
        _record(lock, pid=_dead_pid(), pid_start="1")
        body = f"""
LOCK="{lock}"
_upgrade_lock_judge() {{
    printf 'token=fresh-holder\\npid=1\\nstarted=%s\\n' "$(date +%s)" > "$LOCK"
    return 0
}}
rc=0
_upgrade_lock_takeover "$LOCK" "mine" "token=mine" || rc=$?
echo "rc=$rc"
"""
        result = _bash(body)

        assert "rc=1" in result.stdout, result.stdout + result.stderr
        assert "fresh-holder" in lock.read_text(encoding="utf-8")
        assert not (tmp_path / "x.lock.takeover").exists()


class TestWaitSecondsAreDecimal:
    """Adversarial review: --lock-wait accepts any run of digits, and bash
    arithmetic reads a leading zero as octal, so "08" crashed the acquire."""

    @pytest.mark.parametrize("wait", ["08", "010", "0"])
    def test_a_leading_zero_wait_is_read_as_decimal(self, tmp_path: Path, wait: str) -> None:
        lock = tmp_path / "x.lock"
        body = (
            f'LOCK="{lock}"\n'
            f'rc=0; _upgrade_lock_acquire "$LOCK" "upgrade" {wait} || rc=$?; echo "rc=$rc"\n'
            '_upgrade_lock_release\necho "released"\n'
        )

        result = _bash(body)

        assert result.returncode == 0, result.stderr
        assert "rc=0" in result.stdout, result.stdout + result.stderr
        assert "value too great for base" not in result.stderr


def _unshare_pidns_available() -> bool:
    unshare = shutil.which("unshare")
    if unshare is None:
        return False
    probe = subprocess.run(
        [unshare, "-U", "-r", "-p", "-f", "true"], capture_output=True, check=False, timeout=30
    )
    return probe.returncode == 0


class TestAProcThatIsNotThisNamespaces:
    """Adversarial review F5: in a pid namespace whose /proc was not remounted
    (``unshare -p`` without ``--mount-proc``, some container setups), ``$$`` is
    a pid of THIS namespace but /proc answers for another one. The record then
    named a pid /proc could not vouch for, and a second process in the same
    namespace judged the LIVE holder dead and took the lock as well."""

    @pytest.mark.skipif(not _unshare_pidns_available(), reason="needs unprivileged pid namespaces")
    def test_a_live_holder_is_never_taken_over_in_that_namespace(self, tmp_path: Path) -> None:
        lock = tmp_path / "x.lock"
        block = _block(_UPGRADE_SH)
        # The holder is its own bash process (as upgrade.sh is): its $$ is a
        # small pid of the new namespace that the old /proc does not describe.
        holder = tmp_path / "holder.sh"
        holder.write_text(
            "set -euo pipefail\n"
            + block
            + f'_upgrade_lock_acquire "{lock}" holder 0\necho HOLDER_GOT\nsleep 4\n'
            + "_upgrade_lock_release\n",
            encoding="utf-8",
        )
        # The old /proc vouches for nothing only when it has no process at the
        # holder's pid; pick the first such pid and burn pids up to it.
        target = next(n for n in range(3, 4096) if not Path(f"/proc/{n}").exists())
        script = tmp_path / "inner.sh"
        script.write_text(
            "set -euo pipefail\n"
            + block
            + f'LOCK="{lock}"\n'
            + f"while [ $(( $(sh -c 'echo $$') + 1 )) -lt {target} ]; do :; done\n"
            + f'"{_BASH}" "{holder}" &\n'
            + "h=$!\nsleep 1.5\n"
            + 'rc=0; _upgrade_lock_acquire "$LOCK" second 0 || rc=$?\n'
            + 'echo "second rc=$rc"\n'
            + 'if [ "$rc" -eq 0 ]; then _upgrade_lock_release; fi\n'
            + 'wait "$h"\n',
            encoding="utf-8",
        )

        result = subprocess.run(
            ["unshare", "-U", "-r", "-p", "-f", _BASH, str(script)],
            capture_output=True,
            text=True,
            check=False,
            timeout=_TIMEOUT_SECONDS,
        )

        assert "HOLDER_GOT" in result.stdout, result.stdout + result.stderr
        assert "second rc=1" in result.stdout, result.stdout + result.stderr
