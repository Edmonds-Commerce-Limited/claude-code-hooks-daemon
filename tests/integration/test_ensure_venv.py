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

        fp_result = _run_bash(f'python_venv_fingerprint "{sys.executable}" "{daemon_dir}"')
        assert fp_result.returncode == 0
        fingerprint = fp_result.stdout.strip()
        expected_venv = daemon_dir / "untracked" / f"venv-{fingerprint}"

        assert not expected_venv.exists(), "Precondition: venv should not exist"

        result = _run_bash(f'ensure_venv "{daemon_dir}" "v99.0.0" "{sys.executable}"')
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

        fp_result = _run_bash(f'python_venv_fingerprint "{sys.executable}" "{daemon_dir}"')
        fingerprint = fp_result.stdout.strip()
        fake_venv = daemon_dir / "untracked" / f"venv-{fingerprint}"
        (fake_venv / "bin").mkdir(parents=True)
        (fake_venv / "bin" / "python").symlink_to(sys.executable)
        (fake_venv / ".daemon-version").write_text("v99.0.0\n")
        marker = fake_venv / "SENTINEL"
        marker.write_text("must-survive-noop")

        result = _run_bash(f'ensure_venv "{daemon_dir}" "v99.0.0" "{sys.executable}"')
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

        fp_result = _run_bash(f'python_venv_fingerprint "{sys.executable}" "{daemon_dir}"')
        fingerprint = fp_result.stdout.strip()
        stale_venv = daemon_dir / "untracked" / f"venv-{fingerprint}"
        (stale_venv / "bin").mkdir(parents=True)
        (stale_venv / ".daemon-version").write_text("v1.0.0\n")
        sentinel = stale_venv / "SENTINEL"
        sentinel.write_text("should-be-deleted")

        result = _run_bash(f'ensure_venv "{daemon_dir}" "v99.0.0" "{sys.executable}"')
        assert result.returncode == 0, f"ensure_venv failed: {result.stderr}"
        assert stale_venv.exists(), "New venv should exist after recreate"
        assert not sentinel.exists(), "Stale venv contents should have been wiped"
        assert (stale_venv / ".daemon-version").read_text().strip() == "v99.0.0"


class TestEnsureVenvDowngradeSafety:
    """Plan 00100 Task 3.7: lock_hash is the authoritative freshness signal.

    When ``.daemon-metadata.json`` records a ``lock_hash`` that matches the
    current project's pyproject.toml/uv.lock state, ``ensure_venv`` MUST
    reuse the venv even if the legacy ``.daemon-version`` stamp says it
    was built for a different daemon release. This makes daemon
    upgrades/downgrades cheap when dependencies are unchanged — the venv
    itself is only driven by the lock_hash, not by the daemon SemVer.
    """

    def test_noop_when_lock_hash_matches_even_if_stamp_differs(self, tmp_path: Path) -> None:
        daemon_dir = tmp_path / "project"
        daemon_dir.mkdir()
        _minimal_daemon_dir(daemon_dir)

        fp_result = _run_bash(f'python_venv_fingerprint "{sys.executable}" "{daemon_dir}"')
        fingerprint = fp_result.stdout.strip()
        venv_dir = daemon_dir / "untracked" / f"venv-{fingerprint}"
        (venv_dir / "bin").mkdir(parents=True)
        (venv_dir / "bin" / "python").symlink_to(sys.executable)
        (venv_dir / ".daemon-version").write_text("v1.0.0\n")

        from claude_code_hooks_daemon.daemon.metadata import compute_project_lock_hash

        current_lock_hash = compute_project_lock_hash(daemon_dir)
        metadata_json = (
            "{"
            f'"python_path": "{(venv_dir / "bin" / "python").resolve()}",'
            f'"fingerprint": "{fingerprint}",'
            f'"lock_hash": "{current_lock_hash}",'
            '"daemon_version": "v1.0.0",'
            '"written_at": "2026-01-01T00:00:00Z"'
            "}"
        )
        (venv_dir / ".daemon-metadata.json").write_text(metadata_json)

        sentinel = venv_dir / "SENTINEL"
        sentinel.write_text("must-survive-downgrade-safety-noop")

        result = _run_bash(f'ensure_venv "{daemon_dir}" "v99.0.0" "{sys.executable}"')
        assert result.returncode == 0, f"ensure_venv failed: {result.stderr}"
        assert sentinel.exists(), (
            "ensure_venv wrongly rebuilt venv despite matching lock_hash. "
            f"stderr: {result.stderr}"
        )
        assert sentinel.read_text() == "must-survive-downgrade-safety-noop"

    def test_rebuilds_when_metadata_absent_and_stamp_differs(self, tmp_path: Path) -> None:
        """Backward-compat: with no metadata, falls back to legacy stamp check."""
        daemon_dir = tmp_path / "project"
        daemon_dir.mkdir()
        _minimal_daemon_dir(daemon_dir)

        fp_result = _run_bash(f'python_venv_fingerprint "{sys.executable}" "{daemon_dir}"')
        fingerprint = fp_result.stdout.strip()
        stale_venv = daemon_dir / "untracked" / f"venv-{fingerprint}"
        (stale_venv / "bin").mkdir(parents=True)
        (stale_venv / ".daemon-version").write_text("v1.0.0\n")
        # Intentionally NO .daemon-metadata.json — pure legacy state.
        sentinel = stale_venv / "SENTINEL"
        sentinel.write_text("legacy-stamp-only-should-be-rebuilt")

        result = _run_bash(f'ensure_venv "{daemon_dir}" "v99.0.0" "{sys.executable}"')
        assert result.returncode == 0, f"ensure_venv failed: {result.stderr}"
        assert not sentinel.exists(), (
            "ensure_venv must still rebuild on stamp mismatch when metadata "
            "is absent — legacy pre-Phase-3 state."
        )


class TestEnsureVenvCIGate:
    """CI environments + HOOKS_DAEMON_SKIP_VENV_BOOTSTRAP=1 must skip the bootstrap."""

    def test_skips_when_skip_env_var_set(self, tmp_path: Path) -> None:
        daemon_dir = tmp_path / "project"
        daemon_dir.mkdir()
        _minimal_daemon_dir(daemon_dir)

        result = _run_bash(
            f"HOOKS_DAEMON_SKIP_VENV_BOOTSTRAP=1 "
            f'ensure_venv "{daemon_dir}" "v99.0.0" "{sys.executable}"'
        )
        assert result.returncode == 0, f"ensure_venv failed: {result.stderr}"
        assert not (daemon_dir / "untracked").exists() or not any(
            (daemon_dir / "untracked").glob("venv-*")
        ), "HOOKS_DAEMON_SKIP_VENV_BOOTSTRAP=1 must skip bootstrap"


class TestEnsureVenvSlugIsolation:
    """Plan 00124: ensure_venv must key the venv by the project-path slug.

    The slug (Plan 00100 Task 3.0.5) is the discriminator that keeps a host
    view (e.g. ``/home/dev/proj``) and a container view (``/workspace``) of the
    *same* bind-mounted project on separate venvs inside a shared ``untracked/``
    — even when their Python fingerprint (``sys.version | sys.base_prefix |
    arch``) is identical.

    Regression: ``ensure_venv`` called ``python_venv_fingerprint "$python_bin"``
    WITHOUT passing its ``daemon_dir`` ($1) as the slug root, so the venv was
    created with the bare slug-less key ``venv-py{MM}-{hash}``. A desktop host
    and a container sharing the same Python then collided on one venv. This test
    pins the slug into the created venv's name and fails on the bare key.
    """

    @pytest.mark.slow
    def test_created_venv_name_includes_project_slug(self, tmp_path: Path) -> None:
        daemon_dir = tmp_path / "project"
        daemon_dir.mkdir()
        _minimal_daemon_dir(daemon_dir)

        bare_fp = _run_bash(f'python_venv_fingerprint "{sys.executable}"').stdout.strip()
        slugged_result = _run_bash(f'python_venv_fingerprint "{sys.executable}" "{daemon_dir}"')
        assert slugged_result.returncode == 0, slugged_result.stderr
        slugged_fp = slugged_result.stdout.strip()

        # The slug must actually change the key, otherwise the test is vacuous.
        assert (
            slugged_fp != bare_fp
        ), f"slug did not alter the fingerprint (bare={bare_fp}, slugged={slugged_fp})"

        result = _run_bash(f'ensure_venv "{daemon_dir}" "v99.0.0" "{sys.executable}"')
        assert result.returncode == 0, f"ensure_venv failed: {result.stderr}"

        slugged_venv = daemon_dir / "untracked" / f"venv-{slugged_fp}"
        bare_venv = daemon_dir / "untracked" / f"venv-{bare_fp}"

        created = sorted(p.name for p in (daemon_dir / "untracked").glob("venv-*"))
        assert slugged_venv.exists(), (
            f"ensure_venv must create the slugged venv {slugged_venv.name!r}; "
            f"created instead: {created}"
        )
        assert not bare_venv.exists(), (
            "ensure_venv must NOT create a slug-less venv — that is the "
            f"host/container collision bug. created: {created}"
        )
