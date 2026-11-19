"""``upgrade.sh --unattended`` and the upgrade lock, end to end (Plan 00625 Phases 3 and 5).

The real Layer 1 script runs against a scratch client project whose daemon
clone tracks a scratch origin with tagged fake releases. The fake Layer 2
(``scripts/upgrade_version.sh`` in each release) exits with the code the test
chooses and records the flags it was given. Nothing here touches a real
checkout.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import pytest

from claude_code_hooks_daemon.install.auto_upgrade import AttemptStatus, read_attempt_record

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_UPGRADE_SH: Final[Path] = _REPO_ROOT / "scripts" / "upgrade.sh"
_ROLLBACK_SH: Final[Path] = _REPO_ROOT / "scripts" / "install" / "rollback.sh"
_BASH: Final[str] = shutil.which("bash") or "/bin/bash"
_TIMEOUT_SECONDS: Final[int] = 120

_LAYER2_WITH_SUPPORT: Final[str] = """#!/bin/bash
readonly LAYER2_SUPPORTS_UNATTENDED=1
printf '%s\\n' "$UPGRADE_FLAGS" > "$FAKE_L2_FLAGS_OUT"
if [ -n "${FAKE_L2_STARTED:-}" ]; then
    echo "$$" > "$FAKE_L2_STARTED"
    sleep "${FAKE_L2_SLEEP:-0}"
    echo done > "$FAKE_L2_STARTED.done"
fi
exit "${FAKE_L2_EXIT:-0}"
"""
_LAYER2_WITHOUT_SUPPORT: Final[str] = """#!/bin/bash
printf '%s\\n' "$UPGRADE_FLAGS" > "$FAKE_L2_FLAGS_OUT"
exit "${FAKE_L2_EXIT:-0}"
"""

#: tag -> (does its Layer 2 carry the unattended support line)
_RELEASES: Final[dict[str, bool]] = {
    "1.0.0": False,
    "1.1.0": True,
    "1.2.0": False,
    "2.0.0": True,
}


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@x.invalid", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull},
    )
    return result.stdout.strip()


@dataclass
class Fixture:
    project: Path
    daemon: Path
    flags_out: Path

    def head(self) -> str:
        return _git(self.daemon, "rev-parse", "HEAD")

    def run(
        self, *args: str, layer2_exit: int = 0, extra_env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        env = {
            **os.environ,
            "FAKE_L2_EXIT": str(layer2_exit),
            "FAKE_L2_FLAGS_OUT": str(self.flags_out),
            "HOOKS_DAEMON_PYTHON": sys.executable,
            **(extra_env or {}),
        }
        return subprocess.run(
            [_BASH, str(_UPGRADE_SH), "--project-root", str(self.project), *args],
            capture_output=True,
            text=True,
            check=False,
            timeout=_TIMEOUT_SECONDS,
            env=env,
        )

    def lock_file(self) -> Path:
        return self.project / ".git" / "hooks-daemon-upgrade.lock"

    def record(self, version: str) -> Path:
        return self.daemon / "untracked" / "auto-upgrade" / f"v{version}.state"


def _build(tmp_path: Path, *, installed: str = "1.0.0") -> Fixture:
    origin_work = tmp_path / "origin-work"
    origin_work.mkdir()
    _git(origin_work, "init", "-q", "-b", "main")
    for version, supported in _RELEASES.items():
        (origin_work / "scripts").mkdir(exist_ok=True)
        (origin_work / "pyproject.toml").write_text(
            f'[project]\nname = "x"\nversion = "{version}"\nrequires-python = ">=3.11"\n',
            encoding="utf-8",
        )
        layer2 = origin_work / "scripts" / "upgrade_version.sh"
        layer2.write_text(
            _LAYER2_WITH_SUPPORT if supported else _LAYER2_WITHOUT_SUPPORT, encoding="utf-8"
        )
        _git(origin_work, "add", "-A")
        _git(origin_work, "commit", "-q", "-m", f"release {version}")
        _git(origin_work, "tag", f"v{version}")
    origin = tmp_path / "origin.git"
    _git(tmp_path, "clone", "-q", "--bare", str(origin_work), str(origin))

    project = tmp_path / "project"
    project.mkdir()
    _git(project, "init", "-q", "-b", "main")
    (project / ".gitignore").write_text(".claude/hooks-daemon/\nuntracked/\n", encoding="utf-8")
    _git(project, "add", ".gitignore")
    _git(project, "commit", "-q", "-m", "project")
    daemon = project / ".claude" / "hooks-daemon"
    daemon.parent.mkdir(parents=True)
    _git(tmp_path, "clone", "-q", str(origin), str(daemon))
    _git(daemon, "checkout", "-q", f"v{installed}")
    return Fixture(project=project, daemon=daemon, flags_out=tmp_path / "flags-seen.txt")


def _write_record(fixture: Fixture, version: str) -> Path:
    path = fixture.record(version)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"status=failed\ntarget={version}\nfrom=1.0.0\ndetail=earlier attempt\n", encoding="utf-8"
    )
    return path


class TestLockHeldByAnotherUpgrade:
    def _hold(self, fixture: Fixture) -> None:
        proc = subprocess.run(
            [_BASH, "-c", "echo $$; cat /proc/sys/kernel/random/boot_id; readlink /proc/self/ns/pid"],
            capture_output=True,
            text=True,
            check=True,
        )
        # The holder is this test process: alive, same boot, same namespace.
        pid = os.getpid()
        start = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").rsplit(") ", 1)[1].split()[19]
        boot, ns = proc.stdout.splitlines()[1:3]
        fixture.lock_file().write_text(
            f"token=held\nhost=other-host\nboot_id={boot}\npidns={ns}\npid={pid}\n"
            f"pid_start={start}\nstarted={int(time.time())}\npurpose=provision-sync\n",
            encoding="utf-8",
        )

    @pytest.mark.parametrize("flags", [[], ["--unattended"]])
    def test_a_held_lock_exits_75_and_changes_nothing(self, tmp_path: Path, flags: list[str]) -> None:
        fixture = _build(tmp_path)
        self._hold(fixture)
        head = fixture.head()

        result = fixture.run(*flags, "v1.1.0")

        assert result.returncode == 75, result.stdout + result.stderr
        assert "other-host" in result.stderr and "provision-sync" in result.stderr
        assert fixture.head() == head
        assert not fixture.flags_out.exists()
        assert "token=held" in fixture.lock_file().read_text(encoding="utf-8")

    def test_lock_wait_polls_then_gives_up(self, tmp_path: Path) -> None:
        fixture = _build(tmp_path)
        self._hold(fixture)

        started = time.monotonic()
        result = fixture.run("--lock-wait=2", "v1.1.0")

        assert result.returncode == 75
        assert time.monotonic() - started >= 1.5

    def test_lock_wait_proceeds_when_the_holder_releases(self, tmp_path: Path) -> None:
        fixture = _build(tmp_path)
        self._hold(fixture)
        lock = fixture.lock_file()
        releaser = subprocess.Popen([_BASH, "-c", f'sleep 2; rm -f "{lock}"'])

        result = fixture.run("--lock-wait", "30", "v1.1.0")
        releaser.wait(timeout=_TIMEOUT_SECONDS)

        assert result.returncode == 0, result.stdout + result.stderr
        assert fixture.head() == _git(fixture.daemon, "rev-parse", "v1.1.0^{commit}")


class TestASignalledLayer1KeepsTheLockForLayer2:
    """Adversarial review F2, end to end: SIGTERM to Layer 1 released the lock
    while Layer 2 was still writing the daemon clone."""

    def test_sigterm_mid_layer_2_holds_the_lock_until_layer_2_ends(self, tmp_path: Path) -> None:
        fixture = _build(tmp_path)
        started = tmp_path / "l2.pid"
        env = {
            **os.environ,
            "FAKE_L2_EXIT": "0",
            "FAKE_L2_FLAGS_OUT": str(fixture.flags_out),
            "FAKE_L2_STARTED": str(started),
            "FAKE_L2_SLEEP": "4",
            "HOOKS_DAEMON_PYTHON": sys.executable,
        }
        layer1 = subprocess.Popen(
            [_BASH, str(_UPGRADE_SH), "--project-root", str(fixture.project), "v1.1.0"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        deadline = time.monotonic() + 60
        while not started.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert started.exists(), "Layer 2 never started"

        layer1.terminate()
        time.sleep(1.0)
        lock_while_writing = fixture.lock_file().exists()
        layer1.communicate(timeout=_TIMEOUT_SECONDS)

        assert lock_while_writing, "the lock was released while Layer 2 was still running"
        assert Path(f"{started}.done").exists(), "Layer 2 was cut short"
        assert not fixture.lock_file().exists(), "released once Layer 2 has finished"


class TestAttendedRun:
    def test_it_upgrades_and_releases_the_lock(self, tmp_path: Path) -> None:
        fixture = _build(tmp_path)

        result = fixture.run("v1.1.0")

        assert result.returncode == 0, result.stdout + result.stderr
        assert "--unattended" not in fixture.flags_out.read_text(encoding="utf-8")
        assert not fixture.lock_file().exists()
        assert not Path(f"{fixture.lock_file()}.beat").exists()

    def test_it_releases_the_lock_when_layer_2_fails(self, tmp_path: Path) -> None:
        fixture = _build(tmp_path)

        result = fixture.run("v1.1.0", layer2_exit=1)

        assert result.returncode == 1
        assert not fixture.lock_file().exists()
        assert not fixture.record("1.1.0").exists(), "an attended run leaves no attempt record"

    def test_a_success_clears_the_records_of_the_versions_it_reached(
        self, tmp_path: Path
    ) -> None:
        fixture = _build(tmp_path)
        reached = _write_record(fixture, "1.0.5")
        later = _write_record(fixture, "3.0.0")

        result = fixture.run("v1.1.0")

        assert result.returncode == 0, result.stdout + result.stderr
        assert not reached.exists()
        assert later.exists()


class TestUnattendedSuccess:
    def test_the_flag_reaches_layer_2_and_old_records_are_cleared(self, tmp_path: Path) -> None:
        fixture = _build(tmp_path)
        reached = _write_record(fixture, "1.0.5")
        later = _write_record(fixture, "3.0.0")

        result = fixture.run("--unattended", "v1.1.0")

        assert result.returncode == 0, result.stdout + result.stderr
        assert "--unattended" in fixture.flags_out.read_text(encoding="utf-8")
        assert not reached.exists()
        assert later.exists()
        assert not fixture.lock_file().exists()


class TestUnattendedRefusals:
    """Exit 5: needs a human. The clone is untouched and Layer 2 never runs."""

    def _assert_refused(self, fixture: Fixture, result: subprocess.CompletedProcess[str], head: str) -> None:
        assert result.returncode == 5, result.stdout + result.stderr
        assert "NEEDS-HUMAN" in result.stderr
        assert fixture.head() == head
        assert not fixture.flags_out.exists()
        assert not fixture.lock_file().exists(), "a refusal still releases the lock"

    def test_a_release_in_flight(self, tmp_path: Path) -> None:
        fixture = _build(tmp_path)
        (fixture.project / "untracked").mkdir()
        (fixture.project / "untracked" / "release-state.json").write_text("{}", encoding="utf-8")
        head = fixture.head()

        self._assert_refused(fixture, fixture.run("--unattended", "v1.1.0"), head)

    def test_uncommitted_changes_in_the_project(self, tmp_path: Path) -> None:
        fixture = _build(tmp_path)
        (fixture.project / "work-in-progress.txt").write_text("x", encoding="utf-8")
        head = fixture.head()

        self._assert_refused(fixture, fixture.run("--unattended", "v1.1.0"), head)

    def test_a_major_version_bump(self, tmp_path: Path) -> None:
        fixture = _build(tmp_path)
        head = fixture.head()

        result = fixture.run("--unattended", "v2.0.0")

        self._assert_refused(fixture, result, head)
        assert "MAJOR" in result.stderr

    def test_a_version_with_an_earlier_attempt_record(self, tmp_path: Path) -> None:
        fixture = _build(tmp_path)
        _write_record(fixture, "1.1.0")
        head = fixture.head()

        self._assert_refused(fixture, fixture.run("--unattended", "v1.1.0"), head)

    def test_a_target_whose_layer_2_lacks_the_unattended_support_line(
        self, tmp_path: Path
    ) -> None:
        fixture = _build(tmp_path)
        head = fixture.head()

        result = fixture.run("--unattended", "v1.2.0")

        self._assert_refused(fixture, result, head)
        assert "predates --unattended" in result.stderr


class TestUnattendedArgumentRefusals:
    """Exit 1: a combination an unattended run never makes."""

    def test_release(self, tmp_path: Path) -> None:
        fixture = _build(tmp_path)

        result = fixture.run("--unattended", "--release")

        assert result.returncode == 1, result.stdout + result.stderr
        assert not fixture.flags_out.exists()

    def test_uv(self, tmp_path: Path) -> None:
        fixture = _build(tmp_path)

        result = fixture.run("--unattended", "--uv", sys.executable, "v1.1.0")

        assert result.returncode == 1, result.stdout + result.stderr
        assert not fixture.flags_out.exists()

    def test_a_branch_install(self, tmp_path: Path) -> None:
        fixture = _build(tmp_path)

        result = fixture.run(
            "--unattended",
            extra_env={
                "HOOKS_DAEMON_UNSAFE_TRACK_REF": "main",
                "HOOKS_DAEMON_UNSAFE_TRACK_REF_BECAUSE": "testing",
            },
        )

        assert result.returncode == 1, result.stdout + result.stderr
        assert not fixture.flags_out.exists()

    def test_an_explicit_downgrade(self, tmp_path: Path) -> None:
        fixture = _build(tmp_path, installed="1.1.0")
        head = fixture.head()

        result = fixture.run("--unattended", "v1.0.0")

        assert result.returncode == 1, result.stdout + result.stderr
        assert fixture.head() == head
        assert not fixture.flags_out.exists()


class TestTheAttemptRecord:
    """What Layer 2's exit leaves behind, read back by the Python reader."""

    def test_exit_5_records_needs_human(self, tmp_path: Path) -> None:
        fixture = _build(tmp_path)

        result = fixture.run("--unattended", "v1.1.0", layer2_exit=5)

        assert result.returncode == 5
        record = read_attempt_record(fixture.daemon / "untracked", "1.1.0")
        assert record is not None
        assert record.status is AttemptStatus.NEEDS_HUMAN
        assert record.target == "1.1.0" and record.from_version == "1.0.0"
        assert record.detail
        assert not fixture.lock_file().exists()

    def test_exit_1_records_failed_and_the_version_is_then_refused(self, tmp_path: Path) -> None:
        fixture = _build(tmp_path)

        first = fixture.run("--unattended", "v1.1.0", layer2_exit=1)
        again = fixture.run("--unattended", "v1.1.0")

        assert first.returncode == 1
        record = read_attempt_record(fixture.daemon / "untracked", "1.1.0")
        assert record is not None and record.status is AttemptStatus.FAILED
        assert again.returncode == 5, "the same version is never retried unattended"

    @pytest.mark.parametrize("exit_code", [3, 75])
    def test_the_reading_stop_and_a_held_lock_leave_no_record(
        self, tmp_path: Path, exit_code: int
    ) -> None:
        fixture = _build(tmp_path)

        result = fixture.run("--unattended", "v1.1.0", layer2_exit=exit_code)

        assert result.returncode == exit_code
        assert not fixture.record("1.1.0").exists()

    def test_a_record_leaves_no_temporary_file_behind(self, tmp_path: Path) -> None:
        fixture = _build(tmp_path)

        fixture.run("--unattended", "v1.1.0", layer2_exit=1)

        assert [p.name for p in fixture.record("1.1.0").parent.iterdir()] == ["v1.1.0.state"]


class TestTheRecordSurvivesLayer2sRestore:
    """The record sits under the clone's untracked/, outside everything a restore touches."""

    def test_restore_only_checks_out_a_ref_and_copies_back_known_files(self) -> None:
        text = _ROLLBACK_SH.read_text(encoding="utf-8")
        start = text.index("restore_state_snapshot() {")
        end = text.index("\n}\n", start)
        body = text[start:end]

        assert "auto-upgrade" not in body
        assert "git clean" not in body
        assert " rm " not in body and "rm -" not in body

    def test_the_only_recursive_removal_stays_inside_the_snapshot_directory(self) -> None:
        lines = [
            line
            for line in _ROLLBACK_SH.read_text(encoding="utf-8").splitlines()
            if "rm -rf" in line and not line.lstrip().startswith("#")
        ]

        assert lines == ['            rm -rf "$snapshot_dir"'] or all(
            "$snapshot_dir" in line for line in lines
        )
