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

import shutil
import subprocess
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
mkdir -p "$daemon_dir/untracked/{_FRESH_VENV}/bin"
echo fresh > "$daemon_dir/untracked/{_FRESH_VENV}/built-by"
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


def _skill_install(box: Sandbox, *args: str) -> subprocess.CompletedProcess[str]:
    return box.run([BASH, str(SKILL_SCRIPTS / "install.sh"), *args])


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

    def test_venvs_are_restored_even_when_the_installer_fails(self, sandbox: Sandbox) -> None:
        other = sandbox.other_view_venv()
        before = snapshot(other)
        (sandbox.root / "installer-fails").touch()

        result = _skill_install(sandbox, "--force")

        assert result.returncode != 0
        assert snapshot(sandbox.clone / "untracked" / OTHER_VIEW_VENV) == before
        assert not list((sandbox.project / ".claude").glob(".hooks-daemon-venvs.*"))


class TestVenvsStrandedByAKilledForceAreRecovered:
    """Review I3: the restore runs from the EXIT trap, and KILL runs no trap.
    The aside directory must never be committable, and the next run must put
    what it holds back."""

    def _strand(self, sandbox: Sandbox) -> Path:
        (sandbox.root / "installer-killed").touch()
        result = _skill_install(sandbox, "--force")
        assert result.returncode != 0
        (sandbox.root / "installer-killed").unlink()
        [aside] = list((sandbox.project / ".claude").glob(".hooks-daemon-venvs.*"))
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


class TestTheDeployedCopyMatchesItsTemplate:
    """deployed_artefact_drift compares them; a fix in one copy only is no fix."""

    @pytest.mark.parametrize("script", ["install.sh", "upgrade.sh"])
    def test_deployed_skill_script_is_the_template(self, script: str) -> None:
        deployed = DEPLOYED_SCRIPTS / script
        if not deployed.is_file():
            pytest.skip("skill not deployed in this checkout")
        assert deployed.read_bytes() == (SKILL_SCRIPTS / script).read_bytes()
