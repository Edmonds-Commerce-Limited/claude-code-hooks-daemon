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


UPGRADE_VERSION_SH = REPO_ROOT / "scripts" / "upgrade_version.sh"


class TestUpgradeVersionAsksTheGate:
    """Static contract: ``upgrade_version.sh`` is too heavy to run end to end here.

    Every decision to run ``$VENV_PYTHON`` goes through ``venv_python_usable``;
    the file existing is not evidence the interpreter works.
    """

    def test_no_file_existence_test_on_venv_python(self) -> None:
        hits = [
            f"{n}: {line.strip()}"
            for n, line in enumerate(UPGRADE_VERSION_SH.read_text().splitlines(), 1)
            if '[ -f "$VENV_PYTHON" ]' in line
        ]
        assert hits == []

    def test_the_five_guards_use_the_gate(self) -> None:
        text = UPGRADE_VERSION_SH.read_text()
        assert text.count('venv_python_usable "$VENV_PYTHON"') >= 5


OUTPUT_SH = REPO_ROOT / "scripts" / "install" / "output.sh"
VENV_SH = REPO_ROOT / "scripts" / "install" / "venv.sh"
_PATHS_REL = Path("src") / "claude_code_hooks_daemon" / "daemon" / "paths.py"


def _venv_sh(script: str, env_extra: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    body = f'. "{OUTPUT_SH}"\n. "{VENV_SH}"\n{textwrap.dedent(script)}'
    return _run([BASH, "-c", body], REPO_ROOT, env_extra)


def _stub_paths(daemon_dir: Path, marker: Path) -> None:
    """A paths.py that records it ran: the drifted interpreter must never run it."""
    paths = daemon_dir / _PATHS_REL
    paths.parent.mkdir(parents=True)
    paths.write_text(f"import pathlib\npathlib.Path({str(marker)!r}).write_text('ran')\n")


class TestVenvShAsksTheGate:
    @pytest.mark.parametrize("drifted", [True, False])
    def test_verify_venv(self, tmp_path: Path, drifted: bool) -> None:
        py = _venv(tmp_path / "v", _OTHER if drifted else _RUNNING)

        result = _venv_sh(f'verify_venv "{py}" ""')

        assert (result.returncode != 0) is drifted, result.stdout + result.stderr

    @pytest.mark.parametrize("drifted", [True, False])
    def test_lock_hash_matches_never_runs_a_drifted_interpreter(
        self, tmp_path: Path, drifted: bool
    ) -> None:
        venv = tmp_path / "v"
        py = _venv(venv, _OTHER if drifted else _RUNNING)
        (venv / "bin" / "python3").symlink_to(py)
        daemon = tmp_path / "daemon"
        marker = tmp_path / "marker"
        _stub_paths(daemon, marker)

        result = _venv_sh(f'venv_lock_hash_matches "{daemon}" "{venv}"')

        assert (result.returncode != 0) is drifted, result.stdout + result.stderr
        assert marker.exists() is not drifted

    def test_install_package_editable_refuses_a_drifted_venv(self, tmp_path: Path) -> None:
        py = _venv(tmp_path / "v", _OTHER)

        result = _venv_sh(
            f'_venv_uv() {{ echo UV_CALLED; }}\ninstall_package_editable "{py}" "{tmp_path}"\n'
        )

        assert result.returncode != 0
        assert "UV_CALLED" not in result.stdout

    def test_eager_cleanup_skips_with_a_drifted_current_venv(self, tmp_path: Path) -> None:
        venv = tmp_path / "daemon" / "untracked" / "venv-x-py3-abc"
        _venv(venv, _OTHER)
        marker = tmp_path / "marker"
        _stub_paths(tmp_path / "daemon", marker)

        result = _venv_sh(f'eager_cleanup_stale_venvs "{tmp_path / "daemon"}" "{venv}"')

        assert result.returncode == 0
        assert "SKIPPED" in result.stderr, result.stdout + result.stderr
        assert not marker.exists()


class TestWorktreeScriptsAskTheGate:
    def test_validate_worktrees_calls_a_drifted_venv_no_venv(self, tmp_path: Path) -> None:
        py = _venv(tmp_path / "v", _OTHER)
        root = _stub_tree(tmp_path, py)
        (root / "untracked" / "worktrees" / "wt1").mkdir(parents=True)
        script = _install_script(root, "scripts/validate_worktrees.sh")

        result = _run([BASH, str(script), "wt1"], root)

        assert "NO VENV" in result.stdout + result.stderr, result.stdout + result.stderr
        assert "not usable" in result.stdout, result.stdout + result.stderr

    def test_setup_worktree_and_install_version_use_the_gate(self) -> None:
        # Both scripts need git, uv and the network to run end to end; pin the contract.
        for name, fragment in (
            ("setup_worktree.sh", 'venv_python_usable "${WT_VENV_PATH}/bin/python"'),
            ("install_version.sh", 'venv_python_usable "$VENV_PATH/bin/python"'),
        ):
            text = (REPO_ROOT / "scripts" / name).read_text()
            assert fragment in text, name
