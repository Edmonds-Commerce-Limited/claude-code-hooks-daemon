"""Integration tests for scripts/install/venv_resolver.sh.

The bash SSOT helper that all install/upgrade/verify scripts source so they
find the same venv skill wrappers do. It MUST implement the same precedence
as `_resolve-venv.sh` (shipped alongside the skill):

  1. $HOOKS_DAEMON_VENV_PATH                    — explicit override
  2. $DAEMON_DIR/untracked/venv-{fingerprint}/  — recomputed fingerprint
  3. $DAEMON_DIR/untracked/venv-*/              — any existing fingerprint venv

When none of the above resolve, the resolver fails loudly with exit 5 + a
stderr directive (Plan 00103 Decision 2). The pre-v3.7.0 unversioned legacy
``untracked/venv/`` path is no longer accepted as a silent fallback because
that hid the v3.9.0 field-bug regression — operators got "venv not found"
when the real cause was a 3.9-vs-3.11 ``import tomllib`` crash.

These tests exercise the resolver directly by sourcing it in a bash harness.
They mirror tests/integration/test_skill_scripts_venv_resolution.py so parity
between the two helpers is auditable at test level.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RESOLVER = REPO_ROOT / "scripts" / "install" / "venv_resolver.sh"
FINGERPRINT_HELPER = REPO_ROOT / "scripts" / "install" / "python_fingerprint.sh"

HARNESS = (
    "set -euo pipefail\n"
    'DAEMON_DIR="$1"\n'
    'source "$2"\n'
    'source "$3"\n'
    'resolve_existing_venv_python "$DAEMON_DIR"\n'
)


def _make_venv_skeleton(path: Path) -> None:
    (path / "bin").mkdir(parents=True)
    (path / "bin" / "python").symlink_to(sys.executable)


def _run_resolver(daemon_dir: Path, env_overrides: dict[str, str] | None = None) -> str:
    env = os.environ.copy()
    env.pop("HOOKS_DAEMON_VENV_PATH", None)
    env["PATH"] = os.environ["PATH"]
    if env_overrides:
        env.update(env_overrides)
    result = subprocess.run(
        [
            "bash",
            "-c",
            HARNESS,
            "_",
            str(daemon_dir),
            str(FINGERPRINT_HELPER),
            str(RESOLVER),
        ],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    return result.stdout.strip().splitlines()[-1]


class TestResolverExists:
    def test_resolver_is_shipped(self) -> None:
        assert RESOLVER.is_file(), (
            f"Expected bash SSOT resolver at {RESOLVER} so install-time scripts "
            "can share fingerprint-keyed venv resolution with the skill wrappers."
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

        fingerprint = python_venv_fingerprint()
        keyed_venv = daemon_dir / "untracked" / f"venv-{fingerprint}"
        _make_venv_skeleton(keyed_venv)
        legacy_venv = daemon_dir / "untracked" / "venv"
        _make_venv_skeleton(legacy_venv)

        result = _run_resolver(daemon_dir)
        assert result == f"{keyed_venv}/bin/python"


class TestScanFallback:
    """Step 3 of the precedence: when the installer used a Python whose
    fingerprint differs from the current `python3`, the venv dir still exists
    on disk — resolver must scan rather than falling straight to legacy."""

    def test_foreign_fingerprint_venv_used_when_no_match(self, tmp_path: Path) -> None:
        daemon_dir = tmp_path / "daemon"
        daemon_dir.mkdir()

        foreign_venv = daemon_dir / "untracked" / "venv-py313-deadbeef"
        _make_venv_skeleton(foreign_venv)

        result = _run_resolver(daemon_dir)
        assert result == f"{foreign_venv}/bin/python", (
            "Resolver must scan existing venv-*/ dirs rather than falling "
            "through to legacy when the recomputed fingerprint does not match."
        )

    def test_matching_fingerprint_preferred_over_foreign(self, tmp_path: Path) -> None:
        from claude_code_hooks_daemon.daemon.paths import python_venv_fingerprint

        daemon_dir = tmp_path / "daemon"
        daemon_dir.mkdir()

        fingerprint = python_venv_fingerprint()
        matching_venv = daemon_dir / "untracked" / f"venv-{fingerprint}"
        _make_venv_skeleton(matching_venv)
        foreign_venv = daemon_dir / "untracked" / "venv-py313-deadbeef"
        _make_venv_skeleton(foreign_venv)

        result = _run_resolver(daemon_dir)
        assert result == f"{matching_venv}/bin/python"


class TestLegacyFallback:
    """Plan 00103 Decision 2: when no venv exists, the resolver MUST fail
    loudly with exit 5 + stderr directive. The pre-v3.7.0 silent fallback to
    ``$DAEMON_DIR/untracked/venv/bin/python`` is gone because it hid real
    failures (ModuleNotFoundError, broken venvs) behind a generic "venv
    missing" message."""

    def test_no_venv_exits_nonzero_with_install_directive(self, tmp_path: Path) -> None:
        daemon_dir = tmp_path / "daemon"
        daemon_dir.mkdir()

        env = os.environ.copy()
        env.pop("HOOKS_DAEMON_VENV_PATH", None)
        env.pop("HOOKS_DAEMON_PYTHON", None)
        env["PATH"] = os.environ["PATH"]

        result = subprocess.run(
            [
                "bash",
                "-c",
                HARNESS,
                "_",
                str(daemon_dir),
                str(FINGERPRINT_HELPER),
                str(RESOLVER),
            ],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )

        assert result.returncode != 0, (
            "Resolver must exit non-zero when no venv exists anywhere. "
            f"returncode={result.returncode}, stdout={result.stdout!r}, "
            f"stderr={result.stderr!r}"
        )
        assert "no usable venv" in result.stderr or "install" in result.stderr.lower(), (
            f"stderr must reference the missing venv and the install directive. "
            f"Got stderr=\n{result.stderr}"
        )
        # The unversioned legacy path must NEVER be emitted to stdout.
        assert f"{daemon_dir}/untracked/venv/bin/python" not in result.stdout, (
            "Resolver must not silently emit the unversioned legacy path. "
            f"Got stdout={result.stdout!r}"
        )


class TestPrecedenceInteraction:
    def test_override_beats_keyed_and_legacy(self, tmp_path: Path) -> None:
        from claude_code_hooks_daemon.daemon.paths import python_venv_fingerprint

        daemon_dir = tmp_path / "daemon"
        daemon_dir.mkdir()

        fingerprint = python_venv_fingerprint()
        keyed_venv = daemon_dir / "untracked" / f"venv-{fingerprint}"
        _make_venv_skeleton(keyed_venv)
        legacy_venv = daemon_dir / "untracked" / "venv"
        _make_venv_skeleton(legacy_venv)

        override = tmp_path / "explicit"
        _make_venv_skeleton(override)

        result = _run_resolver(daemon_dir, env_overrides={"HOOKS_DAEMON_VENV_PATH": str(override)})
        assert result == f"{override}/bin/python"
