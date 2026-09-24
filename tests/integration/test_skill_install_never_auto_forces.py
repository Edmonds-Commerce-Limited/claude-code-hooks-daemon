"""The hooks-daemon skill's ``install.sh`` never forces a reinstall by itself (Plan 00456, #53).

When its health probe failed, the skill escalated to ``--force`` unprompted
("Repairing now (equivalent to --force)"). The installer's force path is
``rm -rf .claude/hooks-daemon``, and every environment's venv lives inside that
directory. In the #53 state the probe cannot pass: a clone is shared by a host
view and a container view, and neither has the other's venv. So following
the advice made each view delete the other's venv on every switch.

These tests drive the REAL skill script (the template, which the deployed copy
must match). A fake ``curl`` serves the fetched files locally, and a fake
installer records the ``FORCE`` it was given and mimics the real force path:
``rm -rf``, then a fresh clone holding this environment's new venv.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Final

import pytest

from tests.venv_bootstrap_sandbox import (
    BASH,
    CLONE_VERSION,
    OTHER_VIEW_VENV,
    REPO_ROOT,
    Sandbox,
    snapshot,
)

SKILL_SCRIPTS: Final[Path] = (
    REPO_ROOT / "src" / "claude_code_hooks_daemon" / "skills" / "hooks-daemon" / "scripts"
)
DEPLOYED_SCRIPTS: Final[Path] = REPO_ROOT / ".claude" / "skills" / "hooks-daemon" / "scripts"
_FRESH_VENV: Final[str] = "venv-this-view-py311-f00dface"


def _plant_fetch_fakes(box: Sandbox) -> None:
    installer = box.root / "fake-installer.sh"
    installer.write_text(f"""#!/bin/bash
set -euo pipefail
echo "FORCE=${{FORCE:-unset}}" >> "{box.root / 'installer-calls.log'}"
daemon_dir="$(pwd)/.claude/hooks-daemon"
if [ -d "$daemon_dir" ]; then
    if [ "${{FORCE:-false}}" = "true" ]; then
        rm -rf "$daemon_dir"
    else
        echo "ERR Daemon already installed at $daemon_dir" >&2
        exit 1
    fi
fi
if [ -f "{box.root / 'installer-killed'}" ]; then
    # What the Bash tool's timeout does to a long forced reinstall: KILL,
    # which runs no trap in the skill script.
    kill -KILL "$PPID"
    exit 9
fi
if [ -f "{box.root / 'installer-fails'}" ]; then
    echo "ERR simulated clone failure" >&2
    exit 3
fi
mkdir -p "$daemon_dir/untracked/{_FRESH_VENV}/bin" "$daemon_dir/bin"
echo fresh > "$daemon_dir/untracked/{_FRESH_VENV}/built-by"
echo "a cloned wrapper" > "$daemon_dir/bin/hooks-daemon"
""")
    curl = box.root / "tools" / "curl"
    curl.write_text(f"""#!/bin/bash
out=""
url=""
while [ "$#" -gt 0 ]; do
    case "$1" in
        -o) out="$2"; shift 2 ;;
        -*) shift ;;
        *) url="$1"; shift ;;
    esac
done
case "$url" in
    */pyproject.toml) cat "{REPO_ROOT / 'pyproject.toml'}" > "$out" ;;
    */python_discovery.sh) cat "{REPO_ROOT / 'scripts' / 'lib' / 'python_discovery.sh'}" > "$out" ;;
    */install.sh) cat "{installer}" > "$out" ;;
    *) echo "fake curl: unexpected url $url" >&2; exit 22 ;;
esac
""")
    curl.chmod(0o755)


@pytest.fixture
def sandbox(tmp_path: Path) -> Iterator[Sandbox]:
    box = Sandbox(tmp_path)
    _plant_fetch_fakes(box)
    yield box
    box.cleanup()


#: A 1s heartbeat, so a dead run's aside dir goes quiet within seconds.
_FAST_HEARTBEAT: Final[dict[str, str]] = {"HOOKS_DAEMON_VENV_LOCK_HEARTBEAT_SECONDS": "1"}
#: Two missed beats: long enough for a dead owner's heartbeat to have stopped.
_HEARTBEAT_SILENCE_SECONDS: Final[float] = 2.5


def _skill_install(box: Sandbox, *args: str) -> subprocess.CompletedProcess[str]:
    return box.run([BASH, str(SKILL_SCRIPTS / "install.sh"), *args], extra_env=_FAST_HEARTBEAT)


def _aside_dirs(box: Sandbox) -> list[Path]:
    return sorted((box.project / ".claude").glob(".hooks-daemon-venvs.*"))


def _dead_pid() -> int:
    """The pid of a process that has already exited and been reaped."""
    gone = subprocess.Popen(["true"])  # nosec B603 B607 - fixed argv
    gone.wait()
    return gone.pid


def _this_host() -> str:
    return subprocess.run(  # nosec B603 B607 - fixed argv, no shell
        ["hostname"], capture_output=True, text=True, check=True
    ).stdout.strip()


def _installer_calls(box: Sandbox) -> list[str]:
    log = box.root / "installer-calls.log"
    return log.read_text().splitlines() if log.exists() else []


class TestAnUnhealthyCloneIsRepairedInPlace:
    """The #53 state: a real clone, a readable version, no venv for this path."""

    def test_it_repairs_the_venv_and_never_runs_the_installer(self, sandbox: Sandbox) -> None:
        sandbox.stub_uv()
        other = sandbox.other_view_venv()
        before = snapshot(other)

        result = _skill_install(sandbox)

        output = result.stdout + result.stderr
        assert result.returncode == 0, output
        assert _installer_calls(sandbox) == [], "the installer (and its rm -rf) must not run"
        assert "equivalent to --force" not in output
        assert sandbox.resolves()
        assert snapshot(other) == before
        assert "repair" in output.lower()

    def test_a_failed_repair_stops_without_forcing(self, sandbox: Sandbox) -> None:
        sandbox.stub_uv(fail=True)
        other = sandbox.other_view_venv()
        before = snapshot(other)

        result = _skill_install(sandbox)

        output = result.stdout + result.stderr
        assert result.returncode == 1, output
        assert _installer_calls(sandbox) == []
        assert snapshot(other) == before
        assert f"upgrade {CLONE_VERSION}" in output, "the safe manual fallback must be named"
        assert "nothing was deleted" in output.lower()


class TestNothingElseEscalatesEither:
    def test_a_damaged_clone_stops_and_explains(self, sandbox: Sandbox) -> None:
        sandbox.stub_uv()
        other = sandbox.other_view_venv()
        (sandbox.clone / "scripts" / "lib" / "resolve_venv.sh").unlink()
        before = snapshot(sandbox.clone)

        result = _skill_install(sandbox)

        assert result.returncode == 1, result.stdout + result.stderr
        assert _installer_calls(sandbox) == []
        assert snapshot(sandbox.clone) == before
        assert other.is_dir()

    def test_an_unreadable_version_stops_and_explains(self, sandbox: Sandbox) -> None:
        sandbox.stub_uv()
        (sandbox.clone / "src" / "claude_code_hooks_daemon" / "version.py").write_text("# cut\n")

        result = _skill_install(sandbox)

        assert result.returncode == 1
        assert _installer_calls(sandbox) == []
        assert sandbox.uv_calls() == []

    def test_a_healthy_install_is_left_alone(self, sandbox: Sandbox) -> None:
        sandbox.stub_uv()
        assert sandbox.wrapper("repair").returncode == 0

        result = _skill_install(sandbox)

        assert result.returncode == 0
        assert "already installed" in result.stdout
        assert _installer_calls(sandbox) == []


class TestAFreshCheckoutStillInstalls:
    """init.sh creates `.claude/hooks-daemon/untracked/` on every hook, so a
    checkout that never had a clone still has that empty shell. It must
    install, and must do so WITHOUT the force path."""

    def test_the_runtime_shell_alone_installs_without_force(self, sandbox: Sandbox) -> None:
        shutil.rmtree(sandbox.clone)
        (sandbox.clone / "untracked").mkdir(parents=True)
        (sandbox.clone / "untracked" / ".exec-bit-checked").touch()

        result = _skill_install(sandbox)

        assert result.returncode == 0, result.stdout + result.stderr
        assert _installer_calls(sandbox) == ["FORCE=unset"]
        assert (sandbox.clone / "untracked" / _FRESH_VENV / "built-by").is_file()

    def test_no_daemon_dir_installs_without_force(self, sandbox: Sandbox) -> None:
        shutil.rmtree(sandbox.clone)

        result = _skill_install(sandbox)

        assert result.returncode == 0, result.stdout + result.stderr
        assert _installer_calls(sandbox) == ["FORCE=unset"]


class TestAnExplicitForceKeepsEveryVenv:
    def test_other_environments_venvs_survive_byte_for_byte(self, sandbox: Sandbox) -> None:
        other = sandbox.other_view_venv()
        before = snapshot(other)

        result = _skill_install(sandbox, "--force")

        output = result.stdout + result.stderr
        assert result.returncode == 0, output
        assert _installer_calls(sandbox) == ["FORCE=true"]
        assert snapshot(sandbox.clone / "untracked" / OTHER_VIEW_VENV) == before
        assert (sandbox.clone / "untracked" / _FRESH_VENV / "built-by").read_text() == "fresh\n"
        assert not list((sandbox.project / ".claude").glob(".hooks-daemon-venvs.*"))

    def test_this_environments_rebuilt_venv_wins_over_its_old_copy(self, sandbox: Sandbox) -> None:
        stale = sandbox.clone / "untracked" / _FRESH_VENV
        (stale / "bin").mkdir(parents=True)
        (stale / "built-by").write_text("stale\n")

        result = _skill_install(sandbox, "--force")

        assert result.returncode == 0, result.stdout + result.stderr
        assert (stale / "built-by").read_text() == "fresh\n"

    def test_a_failed_install_keeps_the_venvs_aside_and_creates_no_venv_only_dir(
        self, sandbox: Sandbox
    ) -> None:
        """Re-review N5: the installer removed the clone and then failed. Putting
        the venvs back would create a daemon dir holding only venvs, which the
        installer then refuses as "already installed". They stay aside, the
        output says so, and the next successful run restores them."""
        other = sandbox.other_view_venv()
        before = snapshot(other)
        (sandbox.root / "installer-fails").touch()

        failed = _skill_install(sandbox, "--force")

        assert failed.returncode != 0
        assert not sandbox.clone.exists(), "no daemon dir holding only venvs"
        [aside] = _aside_dirs(sandbox)
        assert snapshot(aside / OTHER_VIEW_VENV) == before
        assert str(aside) in failed.stdout + failed.stderr

        (sandbox.root / "installer-fails").unlink()
        result = _skill_install(sandbox)

        assert result.returncode == 0, result.stdout + result.stderr
        assert snapshot(sandbox.clone / "untracked" / OTHER_VIEW_VENV) == before
        assert _aside_dirs(sandbox) == []


class TestVenvsStrandedByAKilledForceAreRecovered:
    """Review I3: the restore runs from the EXIT trap, and KILL runs no trap.
    The aside directory must never be committable, and the next run must put
    what it holds back."""

    def _strand(self, sandbox: Sandbox) -> Path:
        (sandbox.root / "installer-killed").touch()
        result = _skill_install(sandbox, "--force")
        assert result.returncode != 0
        (sandbox.root / "installer-killed").unlink()
        [aside] = _aside_dirs(sandbox)
        # The killed run's heartbeat stops with it.
        time.sleep(_HEARTBEAT_SILENCE_SECONDS)
        return aside

    def test_the_aside_directory_ignores_itself(self, sandbox: Sandbox) -> None:
        sandbox.other_view_venv()

        aside = self._strand(sandbox)

        assert (aside / ".gitignore").read_text() == "*\n"
        assert (aside / OTHER_VIEW_VENV).is_dir()

    def test_the_next_run_restores_them(self, sandbox: Sandbox) -> None:
        sandbox.stub_uv()
        other = sandbox.other_view_venv()
        before = snapshot(other)
        aside = self._strand(sandbox)
        assert not other.exists(), "precondition: the killed run left it aside"

        result = _skill_install(sandbox)

        output = result.stdout + result.stderr
        assert result.returncode == 0, output
        assert snapshot(other) == before
        assert not aside.exists()
        assert str(aside) in output, "the recovery must be announced"

    def test_a_newer_venv_of_the_same_name_survives_a_force(self, sandbox: Sandbox) -> None:
        """Re-review N1: while a copy sat stranded, its environment rebuilt the
        venv. The next --force must keep the NEWER copy, and say why."""
        other = sandbox.other_view_venv()
        (other / "generation").write_text("OLD\n")
        self._strand(sandbox)
        (other / "bin").mkdir(parents=True)
        (other / "generation").write_text("NEWER\n")

        result = _skill_install(sandbox, "--force")

        output = result.stdout + result.stderr
        assert result.returncode == 0, output
        assert (other / "generation").read_text() == "NEWER\n"
        assert _aside_dirs(sandbox) == []
        assert "stranded" in output.lower() and "newer" in output.lower(), output
        assert "rebuilt for this environment" not in output

    def test_a_stranded_copy_gives_way_to_the_current_venv(self, sandbox: Sandbox) -> None:
        """A plain run in the #53 state (a clone, no venv for this path) finds a
        dead run's aside dir holding an OLD copy of a venv that is in place."""
        sandbox.stub_uv()
        other = sandbox.other_view_venv()
        (other / "generation").write_text("CURRENT\n")
        aside = sandbox.project / ".claude" / ".hooks-daemon-venvs.DeAd01"
        (aside / OTHER_VIEW_VENV / "bin").mkdir(parents=True)
        (aside / OTHER_VIEW_VENV / "generation").write_text("OLD\n")
        (aside / "owner").write_text(f"pid={_dead_pid()}\nhost={_this_host()}\n")
        stale = time.time() - 10
        os.utime(aside, (stale, stale))

        result = _skill_install(sandbox)

        output = result.stdout + result.stderr
        assert result.returncode == 0, output
        assert (other / "generation").read_text() == "CURRENT\n"
        assert _aside_dirs(sandbox) == []
        assert "newer copy is already in place" in output

    def test_stranded_venvs_stay_aside_when_no_clone_can_take_them(self, sandbox: Sandbox) -> None:
        """Re-review N5, for an adopted dir: a run that fails before installing
        leaves them aside, released for the next run, and says so. (The killed
        run had already removed the clone.)"""
        other = sandbox.other_view_venv()
        before = snapshot(other)
        aside = self._strand(sandbox)
        assert not sandbox.clone.exists()
        (sandbox.root / "installer-fails").touch()

        failed = _skill_install(sandbox)

        assert failed.returncode != 0
        assert not sandbox.clone.exists()
        assert snapshot(aside / OTHER_VIEW_VENV) == before
        assert str(aside) in failed.stdout + failed.stderr

        (sandbox.root / "installer-fails").unlink()
        result = _skill_install(sandbox)

        assert result.returncode == 0, result.stdout + result.stderr
        assert snapshot(other) == before


class TestALiveAsideDirIsNotTaken:
    """Re-review N4: two overlapping runs (host and container) must not take
    each other's aside dir. Only a dir whose owner is gone is adopted."""

    def _aside_owned_by(self, sandbox: Sandbox, pid: int) -> Path:
        aside = sandbox.project / ".claude" / ".hooks-daemon-venvs.LiVe01"
        venv = aside / OTHER_VIEW_VENV
        (venv / "bin").mkdir(parents=True)
        (aside / ".gitignore").write_text("*\n")
        (aside / "owner").write_text(f"pid={pid}\nhost={_this_host()}\n")
        return aside

    def test_an_aside_dir_whose_owner_lives_is_left_alone(self, sandbox: Sandbox) -> None:
        sandbox.stub_uv()
        owner = subprocess.Popen(["sleep", "30"])  # nosec B603 B607 - fixed argv
        try:
            aside = self._aside_owned_by(sandbox, owner.pid)
            before = snapshot(aside)

            result = _skill_install(sandbox)

            output = result.stdout + result.stderr
            assert result.returncode == 0, output
            assert snapshot(aside) == before, "a live run's aside dir must not be touched"
            assert not (sandbox.clone / "untracked" / OTHER_VIEW_VENV).exists()
            assert str(aside) in output and "may still be running" in output.lower(), output
        finally:
            owner.kill()
            owner.wait()

    def test_an_aside_dir_whose_owner_is_gone_is_adopted(self, sandbox: Sandbox) -> None:
        sandbox.stub_uv()
        aside = self._aside_owned_by(sandbox, _dead_pid())
        stale = time.time() - 10
        os.utime(aside, (stale, stale))

        result = _skill_install(sandbox)

        assert result.returncode == 0, result.stdout + result.stderr
        assert (sandbox.clone / "untracked" / OTHER_VIEW_VENV).is_dir()
        assert not aside.exists()


class TestTheDeployedCopyMatchesItsTemplate:
    """deployed_artefact_drift compares them; a fix in one copy only is no fix."""

    @pytest.mark.parametrize("script", ["install.sh", "upgrade.sh"])
    def test_deployed_skill_script_is_the_template(self, script: str) -> None:
        deployed = DEPLOYED_SCRIPTS / script
        if not deployed.is_file():
            pytest.skip("skill not deployed in this checkout")
        assert deployed.read_bytes() == (SKILL_SCRIPTS / script).read_bytes()
