"""Integration tests for ensure_venv() in scripts/install/venv.sh.

Plan 00099 Phase 2: ensure_venv() is the auto-bootstrap entry point that
init.sh calls on every daemon start. Its behavior matrix:

  | State                          | Action                          |
  |--------------------------------|---------------------------------|
  | venv missing                   | create + stamp                  |
  | venv present, stamp missing    | recreate + stamp (lazy upgrade) |
  | venv present, stamp mismatch   | recreate + stamp                |
  | venv present, stamp matches    | no-op                           |

The tests invoke the bash function in a subshell with a temp daemon_dir and
inspect the filesystem side-effects. Real uv is used — no mocking.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
VENV_SH = REPO_ROOT / "scripts" / "install" / "venv.sh"
FP_SH = REPO_ROOT / "scripts" / "install" / "python_fingerprint.sh"


def _run_bash(script: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    """Run a bash snippet that sources venv.sh + python_fingerprint.sh."""
    wrapper = f"""
set -euo pipefail
source "{VENV_SH}"
source "{FP_SH}"
{script}
"""
    return subprocess.run(
        ["bash", "-c", wrapper],
        capture_output=True,
        text=True,
        cwd=str(cwd) if cwd else None,
    )


def _minimal_daemon_dir(tmp: Path) -> Path:
    """Build a minimal daemon_dir that uv sync can operate on.

    Copies pyproject.toml, uv.lock, and src/ from the real repo so uv has a
    valid project to sync.
    """
    shutil.copy(REPO_ROOT / "pyproject.toml", tmp / "pyproject.toml")
    if (REPO_ROOT / "uv.lock").exists():
        shutil.copy(REPO_ROOT / "uv.lock", tmp / "uv.lock")
    # Symlink src so we don't copy ~MB of sources
    (tmp / "src").symlink_to(REPO_ROOT / "src")
    if (REPO_ROOT / "README.md").exists():
        shutil.copy(REPO_ROOT / "README.md", tmp / "README.md")
    return tmp


class TestEnsureVenvFunctionExists:
    """Preflight: ensure_venv must be exported by venv.sh."""

    def test_function_is_declared(self) -> None:
        """`declare -F ensure_venv` returns 0 after sourcing venv.sh."""
        result = _run_bash("declare -F ensure_venv > /dev/null && echo OK")
        assert result.returncode == 0, f"ensure_venv not declared: {result.stderr}"
        assert result.stdout.strip() == "OK"


class TestEnsureVenvCreatesWhenMissing:
    """When no venv exists at the fingerprint path, ensure_venv creates one."""

    @pytest.mark.slow
    def test_creates_venv_and_stamps(self, tmp_path: Path) -> None:
        daemon_dir = tmp_path / "project"
        daemon_dir.mkdir()
        _minimal_daemon_dir(daemon_dir)

        fp_result = _run_bash(f'python_venv_fingerprint "{sys.executable}"')
        assert fp_result.returncode == 0
        fingerprint = fp_result.stdout.strip()
        expected_venv = daemon_dir / "untracked" / f"venv-{fingerprint}"

        assert not expected_venv.exists(), "Precondition: venv should not exist"

        result = _run_bash(
            f'ensure_venv "{daemon_dir}" "v99.0.0" "{sys.executable}"'
        )
        assert result.returncode == 0, f"ensure_venv failed: {result.stderr}"
        assert expected_venv.exists(), "ensure_venv did not create venv"
        assert (expected_venv / "bin" / "python").exists() or (
            expected_venv / "Scripts" / "python.exe"
        ).exists()
        stamp_file = expected_venv / ".daemon-version"
        assert stamp_file.exists(), "ensure_venv did not stamp version"
        assert stamp_file.read_text().strip() == "v99.0.0"


class TestEnsureVenvNoOpWhenMatching:
    """When venv exists and stamp matches, ensure_venv must do nothing destructive."""

    def test_noop_when_stamp_matches(self, tmp_path: Path) -> None:
        daemon_dir = tmp_path / "project"
        daemon_dir.mkdir()
        _minimal_daemon_dir(daemon_dir)

        fp_result = _run_bash(f'python_venv_fingerprint "{sys.executable}"')
        fingerprint = fp_result.stdout.strip()
        fake_venv = daemon_dir / "untracked" / f"venv-{fingerprint}"
        (fake_venv / "bin").mkdir(parents=True)
        (fake_venv / "bin" / "python").symlink_to(sys.executable)
        (fake_venv / ".daemon-version").write_text("v99.0.0\n")
        marker = fake_venv / "SENTINEL"
        marker.write_text("must-survive-noop")

        result = _run_bash(
            f'ensure_venv "{daemon_dir}" "v99.0.0" "{sys.executable}"'
        )
        assert result.returncode == 0, f"ensure_venv failed: {result.stderr}"
        assert marker.exists(), "ensure_venv wrongly destroyed a matching venv"
        assert marker.read_text() == "must-survive-noop"


class TestEnsureVenvRecreatesOnStampMismatch:
    """When stamp disagrees with target version, venv must be recreated."""

    @pytest.mark.slow
    def test_rebuilds_when_stamp_differs(self, tmp_path: Path) -> None:
        daemon_dir = tmp_path / "project"
        daemon_dir.mkdir()
        _minimal_daemon_dir(daemon_dir)

        fp_result = _run_bash(f'python_venv_fingerprint "{sys.executable}"')
        fingerprint = fp_result.stdout.strip()
        stale_venv = daemon_dir / "untracked" / f"venv-{fingerprint}"
        (stale_venv / "bin").mkdir(parents=True)
        (stale_venv / ".daemon-version").write_text("v1.0.0\n")
        sentinel = stale_venv / "SENTINEL"
        sentinel.write_text("should-be-deleted")

        result = _run_bash(
            f'ensure_venv "{daemon_dir}" "v99.0.0" "{sys.executable}"'
        )
        assert result.returncode == 0, f"ensure_venv failed: {result.stderr}"
        assert stale_venv.exists(), "New venv should exist after recreate"
        assert not sentinel.exists(), "Stale venv contents should have been wiped"
        assert (stale_venv / ".daemon-version").read_text().strip() == "v99.0.0"


class TestEnsureVenvCIGate:
    """CI environments + HOOKS_DAEMON_SKIP_VENV_BOOTSTRAP=1 must skip the bootstrap."""

    def test_skips_when_skip_env_var_set(self, tmp_path: Path) -> None:
        daemon_dir = tmp_path / "project"
        daemon_dir.mkdir()
        _minimal_daemon_dir(daemon_dir)

        result = _run_bash(
            f'HOOKS_DAEMON_SKIP_VENV_BOOTSTRAP=1 '
            f'ensure_venv "{daemon_dir}" "v99.0.0" "{sys.executable}"'
        )
        assert result.returncode == 0, f"ensure_venv failed: {result.stderr}"
        assert not (daemon_dir / "untracked").exists() or not any(
            (daemon_dir / "untracked").glob("venv-*")
        ), "HOOKS_DAEMON_SKIP_VENV_BOOTSTRAP=1 must skip bootstrap"
