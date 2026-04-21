"""Integration tests for scripts/venv-include.bash's `_resolve_venv_dir()`.

Plan 00099 Phase 3: venv-include.bash (sourced by all QA scripts) resolves
VENV_DIR using the same precedence as init.sh:
  1. $HOOKS_DAEMON_VENV_PATH     — explicit override
  2. untracked/venv-{fingerprint}/ — fingerprint-keyed (when present)
  3. untracked/venv/              — legacy fallback (pre-v3.7.0)

Tests source the file in an isolated PROJECT_ROOT so we can control which
paths exist.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
VENV_INCLUDE = REPO_ROOT / "scripts" / "venv-include.bash"
FP_HELPER = REPO_ROOT / "scripts" / "install" / "python_fingerprint.sh"


def _run(project_root: Path, env_overrides: dict[str, str] | None = None) -> str:
    """Source venv-include.bash from a fake project root and print VENV_DIR."""
    fake_script = project_root / "scripts" / "venv-include.bash"
    env = os.environ.copy()
    if env_overrides:
        env.update(env_overrides)
    if not env_overrides or "HOOKS_DAEMON_VENV_PATH" not in env_overrides:
        env.pop("HOOKS_DAEMON_VENV_PATH", None)
    result = subprocess.run(
        ["bash", "-c", f'source "{fake_script}" > /dev/null 2>&1 && echo "$VENV_DIR"'],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    return result.stdout.strip().splitlines()[-1]


def _setup_fake_project(tmp_path: Path, include_fp_helper: bool = True) -> Path:
    """Create a minimal project directory layout that venv-include.bash expects."""
    project = tmp_path / "project"
    (project / "scripts" / "install").mkdir(parents=True)
    # venv-include.bash computes PROJECT_ROOT as parent of its own directory,
    # so the sourced script must live at {project}/scripts/venv-include.bash
    (project / "scripts" / "venv-include.bash").symlink_to(VENV_INCLUDE)
    if include_fp_helper:
        (project / "scripts" / "install" / "python_fingerprint.sh").symlink_to(FP_HELPER)
    return project


def _fake_venv(path: Path) -> None:
    (path / "bin").mkdir(parents=True)
    (path / "bin" / "python3").symlink_to(sys.executable)


class TestExplicitOverride:
    def test_explicit_override_wins_over_everything(self, tmp_path: Path) -> None:
        project = _setup_fake_project(tmp_path)
        override = tmp_path / "explicit-venv"
        _fake_venv(override)
        # Also create legacy + keyed venvs — override must still win
        _fake_venv(project / "untracked" / "venv")

        result = _run(project, env_overrides={"HOOKS_DAEMON_VENV_PATH": str(override)})
        assert result == str(override)


class TestFingerprintKeyed:
    def test_fingerprint_keyed_wins_over_legacy(self, tmp_path: Path) -> None:
        project = _setup_fake_project(tmp_path)
        from claude_code_hooks_daemon.daemon.paths import python_venv_fingerprint

        fp = python_venv_fingerprint()
        keyed = project / "untracked" / f"venv-{fp}"
        _fake_venv(keyed)
        # Legacy venv also present — must NOT be chosen
        _fake_venv(project / "untracked" / "venv")

        result = _run(project)
        assert result == str(keyed)

    def test_fingerprint_keyed_preferred_for_creation_when_no_legacy(self, tmp_path: Path) -> None:
        """If neither fingerprint nor legacy venv exists, prefer keyed path."""
        project = _setup_fake_project(tmp_path)
        from claude_code_hooks_daemon.daemon.paths import python_venv_fingerprint

        fp = python_venv_fingerprint()
        expected = project / "untracked" / f"venv-{fp}"

        result = _run(project)
        assert result == str(expected)


class TestLegacyFallback:
    def test_falls_back_to_legacy_when_fp_helper_missing(self, tmp_path: Path) -> None:
        project = _setup_fake_project(tmp_path, include_fp_helper=False)

        result = _run(project)
        assert result == str(project / "untracked" / "venv")

    def test_falls_back_to_legacy_when_legacy_exists_and_keyed_does_not(
        self, tmp_path: Path
    ) -> None:
        """Pre-v3.7.0 installs have untracked/venv/ but no keyed venv yet."""
        project = _setup_fake_project(tmp_path)
        _fake_venv(project / "untracked" / "venv")

        result = _run(project)
        assert result == str(project / "untracked" / "venv")
