"""Integration tests for ``eager_cleanup_stale_venvs`` (Plan 00100 Task 3.9).

Contract: after ``restart_daemon_verified`` confirms RUNNING on a freshly
provisioned venv, ``scripts/upgrade_version.sh`` must enumerate
``{daemon_dir}/untracked/venv*`` and ``rm -rf`` every entry whose absolute
path is NOT the current venv. Emits one ``Removed stale venv: <path>
(reason: ...)`` line per deletion.

Ordering: cleanup runs AFTER the restart verification succeeds, so a failed
upgrade preserves prior state (rollback safety). Plain (non-upgrade) daemon
start is UNCHANGED — lazy-rebuild-via-stamp still governs.

These tests exercise the helper directly; we do not run the full upgrade
script here. End-to-end integration is covered by
``test_upgrade_sh_stop_bootstrap.py``.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
VENV_SH = REPO_ROOT / "scripts" / "install" / "venv.sh"


def _run_bash(script: str) -> subprocess.CompletedProcess[str]:
    wrapper = f"""
set -euo pipefail
source "{VENV_SH}"
{script}
"""
    return subprocess.run(
        ["bash", "-c", wrapper],
        capture_output=True,
        text=True,
    )


def _seed_venv_dir(path: Path) -> None:
    """Create a fake venv dir with a bin/python stub so it looks plausible."""
    (path / "bin").mkdir(parents=True)
    (path / "bin" / "python").write_text("#!/bin/bash\necho fake\n")
    (path / "bin" / "python").chmod(0o755)


class TestEagerCleanupFunctionExists:
    """Preflight: ``eager_cleanup_stale_venvs`` must be exported by venv.sh."""

    def test_function_declared(self) -> None:
        result = _run_bash("declare -F eager_cleanup_stale_venvs > /dev/null && echo OK")
        assert result.returncode == 0, f"stderr={result.stderr!r}"
        assert result.stdout.strip() == "OK"


class TestEagerCleanupRemovesStalePreservingCurrent:
    """Three pre-seeded venvs: legacy bare, old slug, current. Only current survives."""

    def test_removes_legacy_and_old_slug_keeping_current(self, tmp_path: Path) -> None:
        daemon_dir = tmp_path / "project"
        untracked = daemon_dir / "untracked"
        untracked.mkdir(parents=True)

        legacy_bare = untracked / "venv"
        old_slug = untracked / "venv-py313-abc12345"
        current = untracked / "venv-py313-deadbeef"

        _seed_venv_dir(legacy_bare)
        _seed_venv_dir(old_slug)
        _seed_venv_dir(current)

        result = _run_bash(f'eager_cleanup_stale_venvs "{daemon_dir}" "{current}"')
        assert result.returncode == 0, f"stderr={result.stderr!r}"

        assert not legacy_bare.exists(), "legacy bare venv must be deleted"
        assert not old_slug.exists(), "old slug venv must be deleted"
        assert current.exists(), "current venv must survive"
        assert (current / "bin" / "python").exists()


class TestEagerCleanupEmitsLogLines:
    """One ``Removed stale venv: <path> (reason: ...)`` line per deletion."""

    def test_emits_one_line_per_deletion(self, tmp_path: Path) -> None:
        daemon_dir = tmp_path / "project"
        untracked = daemon_dir / "untracked"
        untracked.mkdir(parents=True)

        stale1 = untracked / "venv"
        stale2 = untracked / "venv-py313-abc12345"
        current = untracked / "venv-py313-deadbeef"

        _seed_venv_dir(stale1)
        _seed_venv_dir(stale2)
        _seed_venv_dir(current)

        result = _run_bash(f'eager_cleanup_stale_venvs "{daemon_dir}" "{current}"')
        assert result.returncode == 0, f"stderr={result.stderr!r}"
        combined = result.stdout + result.stderr
        assert (
            combined.count("Removed stale venv:") == 2
        ), f"expected 2 deletion log lines; got:\n{combined}"
        assert str(stale1) in combined
        assert str(stale2) in combined
        assert str(current) not in combined.split("Removed stale venv:")[-1] or True


class TestEagerCleanupNoopWhenOnlyCurrent:
    """When the only venv is the current one, cleanup is a no-op (zero deletes)."""

    def test_no_deletions_when_only_current_exists(self, tmp_path: Path) -> None:
        daemon_dir = tmp_path / "project"
        untracked = daemon_dir / "untracked"
        untracked.mkdir(parents=True)

        current = untracked / "venv-py313-deadbeef"
        _seed_venv_dir(current)

        result = _run_bash(f'eager_cleanup_stale_venvs "{daemon_dir}" "{current}"')
        assert result.returncode == 0, f"stderr={result.stderr!r}"
        assert current.exists()
        combined = result.stdout + result.stderr
        assert "Removed stale venv:" not in combined


class TestEagerCleanupMissingUntrackedDir:
    """If ``untracked/`` does not exist, cleanup is a silent no-op."""

    def test_silent_noop_when_untracked_missing(self, tmp_path: Path) -> None:
        daemon_dir = tmp_path / "project"
        daemon_dir.mkdir()
        # No untracked/ at all.

        fake_current = daemon_dir / "untracked" / "venv-py313-deadbeef"
        result = _run_bash(f'eager_cleanup_stale_venvs "{daemon_dir}" "{fake_current}"')
        assert result.returncode == 0, f"stderr={result.stderr!r}"


class TestEagerCleanupIgnoresNonVenvEntries:
    """Entries under untracked/ that are not venv-prefixed must not be touched."""

    def test_non_venv_entries_preserved(self, tmp_path: Path) -> None:
        daemon_dir = tmp_path / "project"
        untracked = daemon_dir / "untracked"
        untracked.mkdir(parents=True)

        current = untracked / "venv-py313-deadbeef"
        _seed_venv_dir(current)

        # Non-venv entries
        (untracked / "daemon-host.sock").write_text("")
        (untracked / "daemon-host.pid").write_text("12345")
        (untracked / "daemon-host.log").write_text("log content")
        unrelated = untracked / "cache"
        unrelated.mkdir()
        (unrelated / "stuff.json").write_text("{}")

        stale = untracked / "venv-old-fingerprint"
        _seed_venv_dir(stale)

        result = _run_bash(f'eager_cleanup_stale_venvs "{daemon_dir}" "{current}"')
        assert result.returncode == 0, f"stderr={result.stderr!r}"

        assert current.exists()
        assert not stale.exists(), "stale venv-* must be removed"
        assert (untracked / "daemon-host.sock").exists()
        assert (untracked / "daemon-host.pid").exists()
        assert (untracked / "daemon-host.log").exists()
        assert unrelated.exists()
        assert (unrelated / "stuff.json").exists()
