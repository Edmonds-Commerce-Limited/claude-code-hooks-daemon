"""Plan 00555 DBF: the remaining shell scripts ask ``venv_python_usable``.

Companion to ``test_dbf_gate_shell_consumers.py``. A venv whose ``pyvenv.cfg``
records Python 3.A while its ``bin/python`` runs 3.B must be treated as "no
venv" by every script that would otherwise run it on an exec-bit test.
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
BASH = shutil.which("bash") or "/bin/bash"

_RUNNING = (sys.version_info.major, sys.version_info.minor)
_OTHER = (_RUNNING[0], _RUNNING[1] + 1 if _RUNNING[1] < 50 else _RUNNING[1] - 1)

SKILL_DIRS = (
    REPO_ROOT / ".claude" / "skills" / "hooks-daemon" / "scripts",
    REPO_ROOT / "src" / "claude_code_hooks_daemon" / "skills" / "hooks-daemon" / "scripts",
)
SKILL_SCRIPTS = ("daemon-cli.sh", "health-check.sh", "init-handlers.sh")


def _venv(venv_dir: Path, cfg_version: tuple[int, int]) -> Path:
    (venv_dir / "bin").mkdir(parents=True)
    py = venv_dir / "bin" / "python"
    py.symlink_to(os.path.realpath(sys.executable))
    (venv_dir / "pyvenv.cfg").write_text(f"version_info = {cfg_version[0]}.{cfg_version[1]}.5\n")
    return py


def _run(
    argv: list[str], cwd: Path, env_extra: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("HOOKS_DAEMON_")}
    env.update(env_extra or {})
    return subprocess.run(
        argv,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
        env=env,
        timeout=Timeout.REQUEST_LONG,
    )


class TestSkillScriptsRefuseADriftedInterpreter:
    """The skill wrappers ran ``$PYTHON`` after ``[ -f ]`` alone."""

    def _project(self, tmp_path: Path, drifted_python: Path) -> Path:
        project = tmp_path / "proj"
        lib = project / ".claude" / "hooks-daemon" / "scripts" / "lib"
        lib.mkdir(parents=True)
        (project / ".claude" / "hooks-daemon.yaml").write_text("version: 1\n")
        # Real gate, but the resolver is pinned to the drifted interpreter so the
        # script's own guard is what is under test.
        (lib / "resolve_venv.sh").write_text(
            textwrap.dedent(
                f"""\
                . "{RESOLVE_VENV_SH}"
                resolve_venv_python() {{ echo "{drifted_python}"; }}
                """
            )
        )
        return project

    @pytest.mark.parametrize("script", SKILL_SCRIPTS)
    @pytest.mark.parametrize("skill_dir", SKILL_DIRS, ids=["deployed", "source"])
    def test_drifted_interpreter_is_refused(
        self, tmp_path: Path, skill_dir: Path, script: str
    ) -> None:
        py = _venv(tmp_path / "v", _OTHER)
        project = self._project(tmp_path, py)

        result = _run(
            [BASH, str(skill_dir / script)], project, {"HOOKS_DAEMON_SKIP_BOOTSTRAP": "1"}
        )

        assert result.returncode == 1, result.stdout + result.stderr
        assert "not usable" in result.stdout, result.stdout + result.stderr


def _stub_tree(tmp_path: Path, drifted_python: Path) -> Path:
    """A fake repo whose resolvers hand back ``drifted_python`` but whose gate is real."""
    root = tmp_path / "repo"
    for sub in ("scripts/lib", "scripts/install", "scripts/qa", "untracked"):
        (root / sub).mkdir(parents=True)
    (root / "scripts" / "lib" / "resolve_venv.sh").write_text(
        textwrap.dedent(
            f"""\
            . "{RESOLVE_VENV_SH}"
            resolve_venv_python() {{ echo "{drifted_python}"; }}
            resolve_existing_venv_python() {{ echo "{drifted_python}"; }}
            """
        )
    )
    (root / "scripts" / "install" / "venv_resolver.sh").write_text(
        f'. "{root}/scripts/lib/resolve_venv.sh"\n'
    )
    return root


def _install_script(root: Path, relative: str) -> Path:
    target = root / relative
    shutil.copy(REPO_ROOT / relative, target)
    return target


class TestQaAndDebugScriptsRefuseADriftedInterpreter:
    @pytest.mark.parametrize(
        "relative",
        ["scripts/qa/run_canonical_callers_check.sh", "scripts/qa/run_strategy_pattern_check.sh"],
    )
    def test_qa_runners_refuse(self, tmp_path: Path, relative: str) -> None:
        py = _venv(tmp_path / "v", _OTHER)
        root = _stub_tree(tmp_path, py)
        checker = root / "scripts" / "qa" / "check_canonical_callers.sh"
        checker.write_text("#!/bin/bash\nexit 0\n")
        checker.chmod(0o755)
        script = _install_script(root, relative)

        result = _run([BASH, str(script)], root)

        assert result.returncode == 2, result.stdout + result.stderr
        assert "not usable" in result.stderr, result.stdout + result.stderr

    def test_debug_hooks_refuses(self, tmp_path: Path) -> None:
        py = _venv(tmp_path / "v", _OTHER)
        root = _stub_tree(tmp_path, py)
        (root / "untracked" / "daemon-x.sock").write_text("")
        script = _install_script(root, "scripts/debug_hooks.sh")

        result = _run([BASH, str(script), "status"], root)

        assert result.returncode == 1, result.stdout + result.stderr
        assert "not usable" in result.stdout, result.stdout + result.stderr
