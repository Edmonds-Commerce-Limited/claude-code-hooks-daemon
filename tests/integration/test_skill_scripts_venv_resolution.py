"""Integration tests for hooks-daemon skill script venv resolution.

Bug: v3.7.0 introduced fingerprint-keyed venvs (`untracked/venv-{fingerprint}/`)
but the three skill wrapper scripts in
`src/claude_code_hooks_daemon/skills/hooks-daemon/scripts/` still hardcoded the
legacy `$DAEMON_DIR/untracked/venv/bin/python` path. On fresh v3.7.0+ installs
the legacy dir does not exist so every skill invocation (/hooks-daemon
status/health/etc.) died with 'Python venv not found'.

Fix: introduce a shared `_resolve-venv.sh` helper next to the wrappers that
implements the same precedence as init.sh's `_resolve_python_cmd()`:

  1. $HOOKS_DAEMON_VENV_PATH       — explicit override
  2. $DAEMON_DIR/untracked/venv-{fingerprint}/bin/python
  3. $DAEMON_DIR/untracked/venv/bin/python   — legacy fallback (pre-v3.7.0)

and have daemon-cli.sh, health-check.sh, init-handlers.sh source it instead of
hardcoding the legacy path.

These tests exercise the helper directly and also assert the three wrappers
actually source it (no hardcoded legacy path remains).
"""

from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_SCRIPTS_DIR = (
    REPO_ROOT / "src" / "claude_code_hooks_daemon" / "skills" / "hooks-daemon" / "scripts"
)
RESOLVER = SKILL_SCRIPTS_DIR / "_resolve-venv.sh"

WRAPPER_SCRIPTS = ("daemon-cli.sh", "health-check.sh", "init-handlers.sh")

RESOLVER_HARNESS = "set -euo pipefail\n" 'DAEMON_DIR="$1"\n' 'source "$2"\n' 'echo "$PYTHON"\n'


def _make_venv_skeleton(path: Path) -> None:
    """Create a fake venv that looks healthy enough (bin/python symlinks sys.executable)."""
    (path / "bin").mkdir(parents=True)
    (path / "bin" / "python").symlink_to(sys.executable)


def _link_fingerprint_helper(daemon_dir: Path) -> None:
    """Symlink the real python_fingerprint.sh into a fake DAEMON_DIR."""
    install_dir = daemon_dir / "scripts" / "install"
    install_dir.mkdir(parents=True)
    (install_dir / "python_fingerprint.sh").symlink_to(
        REPO_ROOT / "scripts" / "install" / "python_fingerprint.sh"
    )


def _run_resolver(daemon_dir: Path, env_overrides: dict[str, str] | None = None) -> str:
    env = os.environ.copy()
    env.pop("HOOKS_DAEMON_VENV_PATH", None)
    env["PATH"] = os.environ["PATH"]
    if env_overrides:
        env.update(env_overrides)
    result = subprocess.run(
        ["bash", "-c", RESOLVER_HARNESS, "_", str(daemon_dir), str(RESOLVER)],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    return result.stdout.strip().splitlines()[-1]


class TestResolverExists:
    def test_resolver_script_is_shipped(self) -> None:
        assert RESOLVER.is_file(), (
            f"Expected shared resolver at {RESOLVER} so skill wrappers "
            "can share fingerprint-keyed venv resolution."
        )


class TestExplicitOverride:
    def test_hooks_daemon_venv_path_wins(self, tmp_path: Path) -> None:
        daemon_dir = tmp_path / "daemon"
        daemon_dir.mkdir()
        override = tmp_path / "explicit"
        _make_venv_skeleton(override)

        result = _run_resolver(daemon_dir, env_overrides={"HOOKS_DAEMON_VENV_PATH": str(override)})
        assert result == f"{override}/bin/python"


class TestFingerprintKeyed:
    def test_fingerprint_venv_wins_over_legacy(self, tmp_path: Path) -> None:
        from claude_code_hooks_daemon.daemon.paths import python_venv_fingerprint

        daemon_dir = tmp_path / "daemon"
        daemon_dir.mkdir()
        _link_fingerprint_helper(daemon_dir)

        fingerprint = python_venv_fingerprint()
        keyed_venv = daemon_dir / "untracked" / f"venv-{fingerprint}"
        _make_venv_skeleton(keyed_venv)
        legacy_venv = daemon_dir / "untracked" / "venv"
        _make_venv_skeleton(legacy_venv)

        result = _run_resolver(daemon_dir)
        assert result == f"{keyed_venv}/bin/python"

    def test_fingerprint_venv_used_when_legacy_absent(self, tmp_path: Path) -> None:
        from claude_code_hooks_daemon.daemon.paths import python_venv_fingerprint

        daemon_dir = tmp_path / "daemon"
        daemon_dir.mkdir()
        _link_fingerprint_helper(daemon_dir)

        fingerprint = python_venv_fingerprint()
        keyed_venv = daemon_dir / "untracked" / f"venv-{fingerprint}"
        _make_venv_skeleton(keyed_venv)

        result = _run_resolver(daemon_dir)
        assert result == f"{keyed_venv}/bin/python"


class TestLegacyFallback:
    def test_legacy_fallback_when_nothing_else_exists(self, tmp_path: Path) -> None:
        daemon_dir = tmp_path / "daemon"
        daemon_dir.mkdir()

        result = _run_resolver(daemon_dir)
        assert result == f"{daemon_dir}/untracked/venv/bin/python"

    def test_legacy_fallback_when_fingerprint_helper_absent(self, tmp_path: Path) -> None:
        daemon_dir = tmp_path / "daemon"
        daemon_dir.mkdir()
        # No scripts/install/python_fingerprint.sh — simulates a busted install.

        result = _run_resolver(daemon_dir)
        assert result == f"{daemon_dir}/untracked/venv/bin/python"


class TestFingerprintMismatchFallback:
    """When the installer built the venv with one Python (e.g. /usr/bin/python3.13)
    but the agent's PATH resolves `python3` to a different Python (e.g. 3.9),
    the recomputed fingerprint won't match the venv directory name. The resolver
    MUST still find the existing venv-* by scanning, not fall through to the
    deleted legacy path.

    Regression test for v3.8.0 bug: /hooks-daemon skill broken on systems where
    system python3 != installer-chosen Python.
    """

    def test_scans_for_any_venv_when_fingerprint_does_not_match(self, tmp_path: Path) -> None:
        daemon_dir = tmp_path / "daemon"
        daemon_dir.mkdir()
        _link_fingerprint_helper(daemon_dir)

        # Create a venv with a fingerprint that DOES NOT match what the
        # current python3 would compute — simulates installer having used a
        # different Python (e.g. installer used python3.13, resolver sees python3=3.9).
        foreign_venv = daemon_dir / "untracked" / "venv-py313-deadbeef"
        _make_venv_skeleton(foreign_venv)
        # No legacy venv — v3.7.0 upgrade deletes it.

        result = _run_resolver(daemon_dir)
        assert result == f"{foreign_venv}/bin/python", (
            "Resolver must scan for existing venv-* directories rather than "
            "relying solely on fingerprint recomputation. The installer's "
            "Python may differ from whatever `python3` resolves to when the "
            "skill wrapper fires."
        )

    def test_matching_fingerprint_still_preferred_over_foreign_venv(self, tmp_path: Path) -> None:
        """When both a matching-fingerprint venv AND a foreign venv exist, the
        matching one wins (correct multi-Python behaviour — container + host
        sharing the same project dir)."""
        from claude_code_hooks_daemon.daemon.paths import python_venv_fingerprint

        daemon_dir = tmp_path / "daemon"
        daemon_dir.mkdir()
        _link_fingerprint_helper(daemon_dir)

        fingerprint = python_venv_fingerprint()
        matching_venv = daemon_dir / "untracked" / f"venv-{fingerprint}"
        _make_venv_skeleton(matching_venv)

        foreign_venv = daemon_dir / "untracked" / "venv-py313-deadbeef"
        _make_venv_skeleton(foreign_venv)

        result = _run_resolver(daemon_dir)
        assert result == f"{matching_venv}/bin/python"

    def test_scan_fallback_skips_broken_venvs(self, tmp_path: Path) -> None:
        """A venv-* directory without a usable bin/python is skipped (e.g.
        partial install, cleanup-in-progress)."""
        daemon_dir = tmp_path / "daemon"
        daemon_dir.mkdir()
        _link_fingerprint_helper(daemon_dir)

        broken_venv = daemon_dir / "untracked" / "venv-py313-broken00"
        (broken_venv / "bin").mkdir(parents=True)
        # No bin/python at all

        working_venv = daemon_dir / "untracked" / "venv-py313-working0"
        _make_venv_skeleton(working_venv)

        result = _run_resolver(daemon_dir)
        assert result == f"{working_venv}/bin/python"


class TestWrappersUseResolver:
    """The three skill wrapper scripts must source the shared resolver and
    not hardcode the legacy venv path."""

    @pytest.mark.parametrize("script_name", WRAPPER_SCRIPTS)
    def test_wrapper_does_not_hardcode_legacy_path(self, script_name: str) -> None:
        script = SKILL_SCRIPTS_DIR / script_name
        content = script.read_text()
        hardcoded = 'PYTHON="$DAEMON_DIR/untracked/venv/bin/python"'
        assert hardcoded not in content, (
            f"{script_name} still hardcodes the legacy venv path. "
            "It must source _resolve-venv.sh instead so fingerprint-keyed "
            "venvs from v3.7.0+ are discovered."
        )

    @pytest.mark.parametrize("script_name", WRAPPER_SCRIPTS)
    def test_wrapper_sources_resolver(self, script_name: str) -> None:
        script = SKILL_SCRIPTS_DIR / script_name
        content = script.read_text()
        assert "_resolve-venv.sh" in content, (
            f"{script_name} must source _resolve-venv.sh to pick up "
            "fingerprint-keyed venv resolution."
        )


class TestResolverShipsExecutableBit:
    """_resolve-venv.sh is sourced, not executed, but install.skills makes
    every *.sh in scripts/ executable. The file must be shellcheck-clean and
    have the shebang so that behaviour is safe."""

    def test_has_bash_shebang(self) -> None:
        assert RESOLVER.read_text().startswith("#!/bin/bash"), (
            "Resolver must start with #!/bin/bash so shellcheck treats it as bash "
            "and the install step chmod +x leaves a valid script on disk."
        )

    def test_is_readable(self) -> None:
        mode = RESOLVER.stat().st_mode
        assert mode & stat.S_IRUSR, "Resolver must be owner-readable"
