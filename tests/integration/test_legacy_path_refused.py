"""Integration tests for Plan 00100 Task 2.7 — ``ensure_venv()`` guard.

Plan 00103 Decision 2 supersedes the original failure mode this guard
defended against. When paths.py is missing at sourcing time the wrapper
no longer falls back to the bare legacy path silently — sourcing itself
fails loudly with a stderr directive. The legacy-path creation refusal
is now achieved at sourcing time rather than inside ensure_venv.

Surviving guard responsibilities (Plan 00103-compatible):

  1. Sourcing fails loudly when paths.py is missing — no opportunity to
     reach ensure_venv or to create at the bare legacy path.
  2. Existing legacy venvs (pre-v3.7.0 installs) are still accepted via
     the SSOT's own legacy-precedence return.
  3. Fingerprint-keyed paths (``untracked/venv-py311-abc12345``) are
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
CANONICAL_LIB = REPO_ROOT / "scripts" / "lib" / "resolve_venv.sh"
PYTHON_DISCOVERY_LIB = REPO_ROOT / "scripts" / "lib" / "python_discovery.sh"


def _setup_fake_project(tmp_path: Path, include_ssot: bool = True) -> Path:
    project = tmp_path / "project"
    (project / "scripts").mkdir(parents=True)
    (project / "scripts" / "venv-include.bash").symlink_to(VENV_INCLUDE)
    # Plan 00104 Phase 5 Task 5.5: venv-include.bash now sources the
    # canonical bash library at scripts/lib/resolve_venv.sh.
    lib_dir = project / "scripts" / "lib"
    lib_dir.mkdir(parents=True)
    (lib_dir / "resolve_venv.sh").symlink_to(CANONICAL_LIB)
    # Plan 00110 Phase 4: resolve_venv.sh sources scripts/lib/python_discovery.sh
    # at runtime to drive glob-and-sort interpreter discovery. The helper is
    # part of the installed surface and must be linked into every fake project.
    (lib_dir / "python_discovery.sh").symlink_to(PYTHON_DISCOVERY_LIB)
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
    """Plan 00103 supersedes the original guard via fail-loud sourcing.

    When paths.py is absent the wrapper no longer falls back to the bare
    legacy path — sourcing aborts before ensure_venv ever runs. The
    end-result invariant ("no venv is created at the legacy path") is
    preserved; the failure point moves earlier.
    """

    def test_refuses_to_create_at_legacy_path_when_ssot_unavailable(self, tmp_path: Path) -> None:
        """No SSOT script present → sourcing fails with a stderr directive.

        Pre-Plan-00103: wrapper silently fell through to the legacy path
        and the ensure_venv guard caught it. Post-Plan-00103: sourcing
        itself fails — the legacy path is never assigned to VENV_DIR.
        """
        project = _setup_fake_project(tmp_path, include_ssot=False)

        result = _run_ensure_venv(project)
        assert result.returncode != 0, (
            f"Sourcing venv-include.bash must fail loudly when paths.py is "
            f"missing.\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "paths.py" in result.stderr or "SSOT" in result.stderr, (
            "Error message should reference the missing SSOT. "
            f"Got: {result.stdout}\n{result.stderr}"
        )
        # And it must NOT have created the venv.
        assert not (
            project / "untracked" / "venv" / "bin" / "python3"
        ).exists(), "Sourcing must fail BEFORE creating any venv — no side effects."


class TestExistingLegacyVenvAccepted:
    """A pre-v3.7.0 install that already has ``untracked/venv/`` is still
    valid. The SSOT's own legacy-precedence return preserves this — paths.py
    must be present (Plan 00103 contract), and when only the legacy venv
    exists it gets returned as the resolved VENV_DIR."""

    def test_pre_existing_legacy_venv_is_accepted(self, tmp_path: Path) -> None:
        project = _setup_fake_project(tmp_path, include_ssot=True)
        _fake_venv(project / "untracked" / "venv")

        result = _run_ensure_venv(project)
        assert result.returncode == 0, (
            f"ensure_venv must accept an existing legacy venv when the SSOT "
            f"is reachable.\nstdout: {result.stdout}\nstderr: {result.stderr}"
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
