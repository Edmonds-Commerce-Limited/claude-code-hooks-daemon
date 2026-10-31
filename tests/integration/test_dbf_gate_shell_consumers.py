"""Plan 00555 DBF: the shell side asks ``venv_python_usable``, never the exec bit.

The incident: a venv whose ``pyvenv.cfg`` records Python 3.A while its
``bin/python`` now runs 3.B. Each consumer below must treat it as "no venv",
which is what lets the self-heal and ``repair`` arms (gated on "nothing
resolves") fire.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants import Timeout

REPO_ROOT = Path(__file__).resolve().parents[2]
RESOLVE_VENV_SH = REPO_ROOT / "scripts" / "lib" / "resolve_venv.sh"
VENV_BOOTSTRAP_SH = REPO_ROOT / "scripts" / "venv_bootstrap.sh"
INIT_SH = REPO_ROOT / "init.sh"
BASH = shutil.which("bash") or "/bin/bash"

_RUNNING = (sys.version_info.major, sys.version_info.minor)
_OTHER = (_RUNNING[0], _RUNNING[1] + 1 if _RUNNING[1] < 50 else _RUNNING[1] - 1)


def _venv(venv_dir: Path, cfg_version: tuple[int, int]) -> Path:
    (venv_dir / "bin").mkdir(parents=True)
    py = venv_dir / "bin" / "python"
    py.symlink_to(os.path.realpath(sys.executable))
    (venv_dir / "pyvenv.cfg").write_text(f"version_info = {cfg_version[0]}.{cfg_version[1]}.5\n")
    return py


def _bash(script: str, env_extra: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("HOOKS_DAEMON_")}
    env.update(env_extra or {})
    return subprocess.run(
        [BASH, "-c", textwrap.dedent(script)],
        capture_output=True,
        text=True,
        check=False,
        env=env,
        timeout=Timeout.REQUEST_LONG,
    )


class TestTheBashGateNeverPrints:
    @pytest.mark.parametrize("drifted", [False, True])
    def test_no_output_either_way(self, tmp_path: Path, drifted: bool) -> None:
        py = _venv(tmp_path / "v", _OTHER if drifted else _RUNNING)

        result = _bash(f'. "{RESOLVE_VENV_SH}"\nvenv_python_usable "{py}"\n')

        assert (result.returncode != 0) is drifted
        assert result.stdout == "" and result.stderr == ""


class TestOverrideIsGated:
    """``HOOKS_DAEMON_VENV_PATH`` used to be returned on the exec bit alone."""

    def _resolve(self, daemon_dir: Path, venv: Path) -> subprocess.CompletedProcess[str]:
        return _bash(
            f'. "{RESOLVE_VENV_SH}"\n_rv_pick_python "{daemon_dir}"\n',
            {"HOOKS_DAEMON_VENV_PATH": str(venv)},
        )

    def test_drifted_override_does_not_resolve(self, tmp_path: Path) -> None:
        _venv(tmp_path / "v", _OTHER)
        result = self._resolve(tmp_path / "d", tmp_path / "v")
        assert result.returncode != 0, result.stdout

    def test_matching_override_resolves(self, tmp_path: Path) -> None:
        py = _venv(tmp_path / "v", _RUNNING)
        result = self._resolve(tmp_path / "d", tmp_path / "v")
        assert result.stdout.strip() == str(py)

    def test_in_venv_lookup_refuses_a_drifted_venv(self, tmp_path: Path) -> None:
        _venv(tmp_path / "v", _OTHER)
        result = _bash(f'. "{RESOLVE_VENV_SH}"\nresolve_venv_python_in_venv "{tmp_path / "v"}"\n')
        assert result.returncode != 0 and result.stdout == ""


class TestBuildSuccessIsJudgedByTheVersionAwareResolver:
    """``_vb_build_under_lock`` calls a build good only if the resolver returns one."""

    def _build(self, tmp_path: Path, cfg: tuple[int, int]) -> subprocess.CompletedProcess[str]:
        venv = tmp_path / "built"
        _venv(venv, cfg)
        daemon_dir = tmp_path / "daemon"
        (daemon_dir / "untracked").mkdir(parents=True)
        script = f"""
            . "{VENV_BOOTSTRAP_SH}"
            venv_bootstrap_switched_off_by() {{ return 1; }}
            _vb_clone_version() {{ echo 1.2.3; }}
            ensure_venv_locked() {{ return 0; }}
            _vb_write_marker() {{ echo MARKER_WRITTEN; }}
            _vb_build_under_lock "{daemon_dir}" "{sys.executable}" py-fp inputs
            """
        return _bash(script, {"HOOKS_DAEMON_VENV_PATH": str(venv)})

    def test_a_build_that_leaves_a_drifted_venv_is_a_failed_build(self, tmp_path: Path) -> None:
        result = self._build(tmp_path, _OTHER)
        assert result.returncode == 1, result.stdout + result.stderr
        assert "MARKER_WRITTEN" in result.stdout

    def test_a_build_that_leaves_a_matching_venv_succeeds(self, tmp_path: Path) -> None:
        result = self._build(tmp_path, _RUNNING)
        assert result.returncode == 0, result.stdout + result.stderr


class TestInitShTreatsADriftedVenvAsNotInstalled:
    """The incident: resolver empty -> not installed -> VENV_MISSING -> self-heal."""

    def _installed(self, tmp_path: Path, venv: Path) -> subprocess.CompletedProcess[str]:
        project = tmp_path / "proj"
        (project / ".claude" / "hooks-daemon").mkdir(parents=True)
        shutil.copy(INIT_SH, project / ".claude" / "init.sh")
        (project / ".claude" / "hooks-daemon.env").write_text(
            'HOOKS_DAEMON_ROOT_DIR="$PROJECT_PATH/.claude/hooks-daemon"\n'
        )
        scripts = project / ".claude" / "hooks-daemon" / "scripts"
        scripts.mkdir()
        (scripts / "lib").symlink_to(REPO_ROOT / "scripts" / "lib")
        subprocess.run(["git", "init", "-q", str(project)], check=True, capture_output=True)
        script = f"""
            cd "{project}"
            source .claude/init.sh
            PYTHON_CMD="{venv}/bin/python"
            if _is_daemon_installed; then echo INSTALLED; else echo NOT_INSTALLED; fi
            HOOKS_DAEMON_VENV_PATH="{venv}"
            if _resolve_python_cmd 2>/dev/null; then echo RESOLVED; else echo UNRESOLVED; fi
            """
        return _bash(script)

    def test_drifted_venv_is_not_installed_and_does_not_resolve(self, tmp_path: Path) -> None:
        _venv(tmp_path / "v", _OTHER)
        result = self._installed(tmp_path, tmp_path / "v")
        assert "NOT_INSTALLED" in result.stdout, result.stdout + result.stderr
        assert "UNRESOLVED" in result.stdout, result.stdout + result.stderr

    def test_matching_venv_is_installed(self, tmp_path: Path) -> None:
        _venv(tmp_path / "v", _RUNNING)
        result = self._installed(tmp_path, tmp_path / "v")
        assert "NOT_INSTALLED" not in result.stdout and "INSTALLED" in result.stdout, (
            result.stdout + result.stderr
        )
