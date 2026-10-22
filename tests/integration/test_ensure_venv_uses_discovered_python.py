"""``ensure_venv`` in venv-include.bash creates the venv with a DISCOVERED interpreter.

A bare ``python3 -m venv`` ran whatever ``python3`` was first on PATH, which can
be older than the daemon's floor. The venv is now created by the interpreter
``find_latest_python`` selects (``$HOOKS_DAEMON_PYTHON`` first), and a host with
no qualifying interpreter fails loudly instead of building a wrong venv.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Final

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
VENV_INCLUDE: Final[Path] = REPO_ROOT / "scripts" / "venv-include.bash"
CANONICAL_LIB: Final[Path] = REPO_ROOT / "scripts" / "lib" / "resolve_venv.sh"
PYTHON_DISCOVERY_LIB: Final[Path] = REPO_ROOT / "scripts" / "lib" / "python_discovery.sh"
PATHS_SSOT: Final[Path] = REPO_ROOT / "src" / "claude_code_hooks_daemon" / "daemon" / "paths.py"

_TIMEOUT_SECONDS: Final[int] = 180


def _setup_fake_project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    (project / "scripts" / "lib").mkdir(parents=True)
    (project / "scripts" / "venv-include.bash").symlink_to(VENV_INCLUDE)
    (project / "scripts" / "lib" / "resolve_venv.sh").symlink_to(CANONICAL_LIB)
    (project / "scripts" / "lib" / "python_discovery.sh").symlink_to(PYTHON_DISCOVERY_LIB)
    ssot_parent = project / "src" / "claude_code_hooks_daemon" / "daemon"
    ssot_parent.mkdir(parents=True)
    (ssot_parent / "paths.py").symlink_to(PATHS_SSOT)
    return project


def _fake_old_python3(tmp_path: Path) -> tuple[Path, Path]:
    """A python3 that records being run and then fails, placed first on PATH."""
    fake_bin = tmp_path / "fakebin"
    fake_bin.mkdir()
    marker = tmp_path / "fake-python3-ran"
    fake = fake_bin / "python3"
    fake.write_text(f"#!/bin/sh\ntouch {marker}\nexit 1\n", encoding="utf-8")
    fake.chmod(0o755)
    return fake_bin, marker


def _run(
    tmp_path: Path, project: Path, hooks_python_after_source: str | None, path_prefix: Path
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOOKS_DAEMON_PYTHON"] = sys.executable
    env.pop("HOOKS_DAEMON_VENV_PATH", None)
    env["PATH"] = f"{path_prefix}:{env['PATH']}"
    override = (
        f'export HOOKS_DAEMON_PYTHON="{hooks_python_after_source}"\n'
        if hooks_python_after_source is not None
        else ""
    )
    script = (
        f'source "{project}/scripts/venv-include.bash" > /dev/null\n'
        f"{override}"
        "ensure_venv\n"
        'echo "rc=$?"\n'
        'echo "VENV_PYTHON=${VENV_PYTHON}"\n'
    )
    return subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(tmp_path),
        timeout=_TIMEOUT_SECONDS,
        check=False,
    )


class TestEnsureVenvUsesTheDiscoveredInterpreter:
    def test_a_python3_first_on_path_is_never_used_to_build_the_venv(self, tmp_path: Path) -> None:
        project = _setup_fake_project(tmp_path)
        fake_bin, marker = _fake_old_python3(tmp_path)

        result = _run(tmp_path, project, None, fake_bin)

        assert "rc=0" in result.stdout, (result.stdout, result.stderr)
        assert not marker.exists(), "ensure_venv ran the bare python3 from PATH"
        venv_python = result.stdout.split("VENV_PYTHON=", 1)[1].strip()
        assert Path(venv_python).exists()

    def test_no_qualifying_interpreter_fails_loudly_and_builds_nothing(
        self, tmp_path: Path
    ) -> None:
        project = _setup_fake_project(tmp_path)
        fake_bin, marker = _fake_old_python3(tmp_path)

        result = _run(tmp_path, project, str(tmp_path / "no-such-python"), fake_bin)

        assert "rc=1" in result.stdout, (result.stdout, result.stderr)
        assert "No compatible Python found" in result.stderr
        assert not marker.exists(), "ensure_venv fell back to the bare python3 from PATH"
        venv_python = result.stdout.split("VENV_PYTHON=", 1)[1].strip()
        assert not Path(venv_python).exists()
