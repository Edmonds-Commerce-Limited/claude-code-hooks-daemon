"""Integration tests for Plan 00100 Task 2.7 — ``ensure_venv()`` guard.

Context: the Phase 2 SSOT refactor removed duplicate resolvers, but one
failure mode persisted in principle — if paths.py was missing at
venv-include sourcing time, the wrapper fell back to the legacy
``$PROJECT_ROOT/untracked/venv`` path AND ``ensure_venv`` would happily
create a fresh venv there. That path is the very shape that caused the
concurrent-container cross-Python corruption in v3.7.0, so we must never
create at it even as a degraded fallback.

Guard contract:

  1. ``ensure_venv`` detects when VENV_DIR is the bare legacy path
     (ends with ``/untracked/venv`` — no fingerprint suffix) AND the venv
     does not already exist.
  2. In that state it FAILS FAST with a clear error naming the issue.
  3. Existing legacy venvs (pre-v3.7.0 installs) are still accepted —
     the guard only refuses *creation*, never pre-existing installs.
  4. Fingerprint-keyed paths (``untracked/venv-py311-abc12345``) are
     always permitted — those are the canonical target.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
VENV_INCLUDE = REPO_ROOT / "scripts" / "venv-include.bash"
PATHS_SSOT = REPO_ROOT / "src" / "claude_code_hooks_daemon" / "daemon" / "paths.py"


def _setup_fake_project(tmp_path: Path, include_ssot: bool = True) -> Path:
    project = tmp_path / "project"
    (project / "scripts").mkdir(parents=True)
    (project / "scripts" / "venv-include.bash").symlink_to(VENV_INCLUDE)
    if include_ssot:
        ssot_parent = project / "src" / "claude_code_hooks_daemon" / "daemon"
        ssot_parent.mkdir(parents=True)
        (ssot_parent / "paths.py").symlink_to(PATHS_SSOT)
    return project


def _fake_venv(path: Path) -> None:
    (path / "bin").mkdir(parents=True)
    (path / "bin" / "python3").symlink_to(sys.executable)


def _run_ensure_venv(
    project: Path, env_overrides: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Source venv-include.bash, call ensure_venv, capture result."""
    script = project / "scripts" / "venv-include.bash"
    env = os.environ.copy()
    if env_overrides:
        env.update(env_overrides)
    if not env_overrides or "HOOKS_DAEMON_VENV_PATH" not in env_overrides:
        env.pop("HOOKS_DAEMON_VENV_PATH", None)
    return subprocess.run(
        ["bash", "-c", f'source "{script}" && ensure_venv'],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


class TestLegacyPathCreationRefused:
    """The core guard: creating a NEW venv at the bare legacy path must fail."""

    def test_refuses_to_create_at_legacy_path_when_ssot_unavailable(self, tmp_path: Path) -> None:
        """No SSOT script present → wrapper falls back to legacy path. Without
        the guard, ensure_venv would silently create the exact failure mode
        Plan 00100 deleted. The guard must stop it."""
        project = _setup_fake_project(tmp_path, include_ssot=False)

        result = _run_ensure_venv(project)
        assert result.returncode != 0, (
            f"ensure_venv must refuse to create at the legacy path, but it "
            f"succeeded.\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
        combined = (result.stdout + result.stderr).lower()
        assert "legacy" in combined, (
            "Error message should explain why the legacy path is refused. "
            f"Got: {result.stdout}\n{result.stderr}"
        )
        # And it must NOT have created the venv.
        assert not (
            project / "untracked" / "venv" / "bin" / "python3"
        ).exists(), "Guard must fail BEFORE creating the venv — no side effects."


class TestExistingLegacyVenvAccepted:
    """A pre-v3.7.0 install that already has untracked/venv/ is still valid —
    we only refuse *creation* at that path."""

    def test_pre_existing_legacy_venv_is_accepted(self, tmp_path: Path) -> None:
        project = _setup_fake_project(tmp_path, include_ssot=False)
        _fake_venv(project / "untracked" / "venv")

        result = _run_ensure_venv(project)
        assert result.returncode == 0, (
            f"ensure_venv must accept an existing legacy venv.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )


class TestFingerprintPathCreationAllowed:
    """Creating at a fingerprint-keyed path is always fine."""

    def test_fingerprint_path_creation_is_allowed(self, tmp_path: Path) -> None:
        """SSOT present, no venvs on disk → wrapper returns the
        fingerprint-keyed creation target via --fallback-target. That path
        must NOT trigger the guard."""
        project = _setup_fake_project(tmp_path, include_ssot=True)

        result = _run_ensure_venv(project)
        # The creation itself may fail for other reasons (e.g. python3 -m venv
        # limitations in the test env), but the guard must not be what blocks
        # it — check stdout/stderr does not mention the legacy refusal.
        combined = (result.stdout + result.stderr).lower()
        assert "legacy" not in combined or "refuse" not in combined, (
            "Fingerprint path must not trip the legacy-path guard. "
            f"Got: {result.stdout}\n{result.stderr}"
        )

    def test_fingerprint_path_suffix_is_recognised(self, tmp_path: Path) -> None:
        """The guard matches on exact ``/untracked/venv`` suffix — paths with
        a fingerprint like ``/untracked/venv-py311-abc12345`` must pass."""
        project = _setup_fake_project(tmp_path, include_ssot=True)
        # Pre-create a fingerprint-keyed venv so the SSOT returns it.
        from claude_code_hooks_daemon.daemon.paths import python_venv_fingerprint

        fp = python_venv_fingerprint()
        _fake_venv(project / "untracked" / f"venv-{fp}")

        result = _run_ensure_venv(project)
        assert result.returncode == 0, (
            f"Fingerprint-keyed existing venv must be accepted.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
