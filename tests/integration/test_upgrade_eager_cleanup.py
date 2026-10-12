"""Integration tests for ``eager_cleanup_stale_venvs`` (Plan 00100 Task 3.9, N441).

Contract: after ``restart_daemon_verified`` confirms RUNNING on a freshly
provisioned venv, ``scripts/upgrade_version.sh`` calls
``eager_cleanup_stale_venvs``. A ``venv-*`` entry is removed ONLY on a
positive finding that it is stale:

- it is not the current venv;
- its ``.daemon-metadata.json`` is readable and its ``lock_hash`` differs from
  the current source's lock hash;
- its name carries THIS view's path slug, or is a legacy un-slugged name.

Another view's slugged venv, a venv whose lock hash matches, and a venv with
missing or unreadable metadata are kept, each with a log line saying why. If
the current lock hash cannot be computed nothing is removed. The pre-v3.7.0
``untracked/venv`` directory is still removed unconditionally.

Ordering: cleanup runs AFTER the restart verification succeeds on both the
slow path and the already-at-target path, so a failed upgrade preserves prior
state (rollback safety). Plain (non-upgrade) daemon start is UNCHANGED.

These tests exercise the helper directly; we do not run the full upgrade
script here. End-to-end integration is covered by
``test_upgrade_sh_stop_bootstrap.py``.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

from claude_code_hooks_daemon.daemon.paths import (
    _compute_project_lock_hash_stdlib,
    project_path_slug,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
VENV_SH = REPO_ROOT / "scripts" / "install" / "venv.sh"
UPGRADE_VERSION_SH = REPO_ROOT / "scripts" / "upgrade_version.sh"
PATHS_PY = REPO_ROOT / "src" / "claude_code_hooks_daemon" / "daemon" / "paths.py"

STALE_HASH = "sha256:" + "0" * 64
FP_TAIL = "py313-abc12345"


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


def _seed_venv_dir(path: Path, lock_hash: str | None = None) -> None:
    """Create a fake venv dir with a bin/python stub; optionally stamp metadata."""
    (path / "bin").mkdir(parents=True)
    (path / "bin" / "python").write_text("#!/bin/bash\necho fake\n")
    (path / "bin" / "python").chmod(0o755)
    if lock_hash is not None:
        (path / ".daemon-metadata.json").write_text(
            json.dumps({"python_path": str(path / "bin" / "python"), "lock_hash": lock_hash})
        )


def _make_daemon_dir(tmp_path: Path, with_pyproject: bool = True) -> Path:
    """Create a daemon dir holding paths.py and (optionally) a pyproject.toml."""
    daemon_dir = tmp_path / "project"
    (daemon_dir / "untracked").mkdir(parents=True)
    paths_dir = daemon_dir / "src" / "claude_code_hooks_daemon" / "daemon"
    paths_dir.mkdir(parents=True)
    shutil.copy(PATHS_PY, paths_dir / "paths.py")
    if with_pyproject:
        (daemon_dir / "pyproject.toml").write_text('[project]\nname = "x"\n')
    return daemon_dir


def _current_hash(daemon_dir: Path) -> str:
    value = _compute_project_lock_hash_stdlib(daemon_dir)
    assert value is not None
    return value


def _own_slug(daemon_dir: Path) -> str:
    return project_path_slug(daemon_dir)


def _cleanup(daemon_dir: Path, current: Path) -> subprocess.CompletedProcess[str]:
    result = _run_bash(f'eager_cleanup_stale_venvs "{daemon_dir}" "{current}"')
    assert result.returncode == 0, f"stderr={result.stderr!r}"
    return result


class TestEagerCleanupFunctionExists:
    """Preflight: ``eager_cleanup_stale_venvs`` must be exported by venv.sh."""

    def test_function_declared(self) -> None:
        result = _run_bash("declare -F eager_cleanup_stale_venvs > /dev/null && echo OK")
        assert result.returncode == 0, f"stderr={result.stderr!r}"
        assert result.stdout.strip() == "OK"


class TestEagerCleanupRemovesPositivelyStale:
    """Only a venv with a readable, mismatched lock_hash and an eligible name goes."""

    def test_removes_same_slug_mismatched_hash(self, tmp_path: Path) -> None:
        daemon_dir = _make_daemon_dir(tmp_path)
        untracked = daemon_dir / "untracked"
        current = untracked / f"venv-{_own_slug(daemon_dir)}-py313-deadbeef"
        stale = untracked / f"venv-{_own_slug(daemon_dir)}-py312-abc12345"
        _seed_venv_dir(current, _current_hash(daemon_dir))
        _seed_venv_dir(stale, STALE_HASH)

        result = _cleanup(daemon_dir, current)

        assert not stale.exists(), "same-slug venv with a mismatched lock_hash must go"
        assert current.exists(), "current venv must survive"
        assert (current / "bin" / "python").exists()
        assert f"Removed stale venv: {stale}" in result.stdout + result.stderr

    def test_removes_legacy_unslugged_mismatched_hash(self, tmp_path: Path) -> None:
        daemon_dir = _make_daemon_dir(tmp_path)
        untracked = daemon_dir / "untracked"
        current = untracked / f"venv-{_own_slug(daemon_dir)}-py313-deadbeef"
        legacy = untracked / f"venv-{FP_TAIL}"
        _seed_venv_dir(current, _current_hash(daemon_dir))
        _seed_venv_dir(legacy, STALE_HASH)

        _cleanup(daemon_dir, current)

        assert not legacy.exists(), "legacy un-slugged venv with a mismatched hash must go"
        assert current.exists()

    def test_removes_pre_v370_bare_venv_unconditionally(self, tmp_path: Path) -> None:
        daemon_dir = _make_daemon_dir(tmp_path)
        untracked = daemon_dir / "untracked"
        current = untracked / f"venv-{_own_slug(daemon_dir)}-py313-deadbeef"
        bare = untracked / "venv"
        _seed_venv_dir(current, _current_hash(daemon_dir))
        _seed_venv_dir(bare)

        result = _cleanup(daemon_dir, current)

        assert not bare.exists(), "pre-v3.7.0 untracked/venv must be removed"
        assert "legacy-name" in result.stdout + result.stderr


class TestEagerCleanupKeepsEverythingElse:
    """No positive finding of staleness means the venv stays, with a reason logged."""

    def test_keeps_other_views_slugged_venv(self, tmp_path: Path) -> None:
        daemon_dir = _make_daemon_dir(tmp_path)
        untracked = daemon_dir / "untracked"
        current = untracked / f"venv-{_own_slug(daemon_dir)}-py313-deadbeef"
        other_view = untracked / "venv-some_other_view-py313-abc12345"
        _seed_venv_dir(current, _current_hash(daemon_dir))
        _seed_venv_dir(other_view, STALE_HASH)

        result = _cleanup(daemon_dir, current)

        assert other_view.exists(), "another view's live venv must survive"
        combined = result.stdout + result.stderr
        assert "Removed stale venv:" not in combined
        assert f"Kept venv: {other_view}" in combined
        assert "slug" in combined

    def test_keeps_same_slug_matching_hash(self, tmp_path: Path) -> None:
        daemon_dir = _make_daemon_dir(tmp_path)
        untracked = daemon_dir / "untracked"
        current = untracked / f"venv-{_own_slug(daemon_dir)}-py313-deadbeef"
        sibling = untracked / f"venv-{_own_slug(daemon_dir)}-py312-abc12345"
        _seed_venv_dir(current, _current_hash(daemon_dir))
        _seed_venv_dir(sibling, _current_hash(daemon_dir))

        result = _cleanup(daemon_dir, current)

        assert sibling.exists(), "a venv built for the current source must survive"
        combined = result.stdout + result.stderr
        assert f"Kept venv: {sibling}" in combined
        assert "lock_hash matches" in combined

    def test_keeps_missing_metadata(self, tmp_path: Path) -> None:
        daemon_dir = _make_daemon_dir(tmp_path)
        untracked = daemon_dir / "untracked"
        current = untracked / f"venv-{_own_slug(daemon_dir)}-py313-deadbeef"
        no_meta = untracked / f"venv-{_own_slug(daemon_dir)}-py312-abc12345"
        _seed_venv_dir(current, _current_hash(daemon_dir))
        _seed_venv_dir(no_meta)

        result = _cleanup(daemon_dir, current)

        assert no_meta.exists()
        combined = result.stdout + result.stderr
        assert f"Kept venv: {no_meta}" in combined
        assert "metadata" in combined

    def test_keeps_corrupt_metadata(self, tmp_path: Path) -> None:
        daemon_dir = _make_daemon_dir(tmp_path)
        untracked = daemon_dir / "untracked"
        current = untracked / f"venv-{_own_slug(daemon_dir)}-py313-deadbeef"
        corrupt = untracked / f"venv-{FP_TAIL}"
        _seed_venv_dir(current, _current_hash(daemon_dir))
        _seed_venv_dir(corrupt)
        (corrupt / ".daemon-metadata.json").write_text("{not json")

        _cleanup(daemon_dir, current)

        assert corrupt.exists(), "unreadable metadata is not a positive finding"

    def test_removes_nothing_when_current_hash_not_computable(self, tmp_path: Path) -> None:
        daemon_dir = _make_daemon_dir(tmp_path, with_pyproject=False)
        untracked = daemon_dir / "untracked"
        current = untracked / f"venv-{_own_slug(daemon_dir)}-py313-deadbeef"
        stale = untracked / f"venv-{_own_slug(daemon_dir)}-py312-abc12345"
        _seed_venv_dir(current, STALE_HASH)
        _seed_venv_dir(stale, STALE_HASH)

        result = _cleanup(daemon_dir, current)

        assert stale.exists()
        combined = result.stdout + result.stderr
        assert "Removed stale venv:" not in combined
        assert "cannot compute" in combined

    def test_keeps_when_python_helper_unavailable(self, tmp_path: Path) -> None:
        daemon_dir = _make_daemon_dir(tmp_path)
        (daemon_dir / "src" / "claude_code_hooks_daemon" / "daemon" / "paths.py").unlink()
        untracked = daemon_dir / "untracked"
        current = untracked / f"venv-{_own_slug(daemon_dir)}-py313-deadbeef"
        stale = untracked / f"venv-{_own_slug(daemon_dir)}-py312-abc12345"
        _seed_venv_dir(current, _current_hash(daemon_dir))
        _seed_venv_dir(stale, STALE_HASH)

        _cleanup(daemon_dir, current)

        assert stale.exists(), "no decision available means no deletion"


class TestEagerCleanupEmitsLogLines:
    """One ``Removed stale venv: <path> (reason: ...)`` line per deletion."""

    def test_emits_one_line_per_deletion(self, tmp_path: Path) -> None:
        daemon_dir = _make_daemon_dir(tmp_path)
        untracked = daemon_dir / "untracked"
        current = untracked / f"venv-{_own_slug(daemon_dir)}-py313-deadbeef"
        stale1 = untracked / "venv"
        stale2 = untracked / f"venv-{FP_TAIL}"
        _seed_venv_dir(stale1)
        _seed_venv_dir(stale2, STALE_HASH)
        _seed_venv_dir(current, _current_hash(daemon_dir))

        result = _cleanup(daemon_dir, current)

        combined = result.stdout + result.stderr
        assert (
            combined.count("Removed stale venv:") == 2
        ), f"expected 2 deletion log lines; got:\n{combined}"
        assert str(stale1) in combined
        assert str(stale2) in combined


class TestEagerCleanupNoopWhenOnlyCurrent:
    """When the only venv is the current one, cleanup is a no-op (zero deletes)."""

    def test_no_deletions_when_only_current_exists(self, tmp_path: Path) -> None:
        daemon_dir = _make_daemon_dir(tmp_path)
        current = daemon_dir / "untracked" / "venv-py313-deadbeef"
        _seed_venv_dir(current, STALE_HASH)

        result = _cleanup(daemon_dir, current)

        assert current.exists()
        assert "Removed stale venv:" not in result.stdout + result.stderr


class TestEagerCleanupMissingUntrackedDir:
    """If ``untracked/`` does not exist, cleanup is a silent no-op."""

    def test_silent_noop_when_untracked_missing(self, tmp_path: Path) -> None:
        daemon_dir = tmp_path / "project"
        daemon_dir.mkdir()

        fake_current = daemon_dir / "untracked" / "venv-py313-deadbeef"
        _cleanup(daemon_dir, fake_current)


class TestEagerCleanupIgnoresNonVenvEntries:
    """Entries under untracked/ that are not venv-prefixed must not be touched."""

    def test_non_venv_entries_preserved(self, tmp_path: Path) -> None:
        daemon_dir = _make_daemon_dir(tmp_path)
        untracked = daemon_dir / "untracked"
        current = untracked / f"venv-{_own_slug(daemon_dir)}-py313-deadbeef"
        _seed_venv_dir(current, _current_hash(daemon_dir))

        (untracked / "daemon-host.sock").write_text("")
        (untracked / "daemon-host.pid").write_text("12345")
        (untracked / "daemon-host.log").write_text("log content")
        unrelated = untracked / "cache"
        unrelated.mkdir()
        (unrelated / "stuff.json").write_text("{}")

        stale = untracked / "venv-old-fingerprint"
        _seed_venv_dir(stale, STALE_HASH)

        _cleanup(daemon_dir, current)

        assert current.exists()
        assert not stale.exists(), "stale venv-* with a mismatched hash must be removed"
        assert (untracked / "daemon-host.sock").exists()
        assert (untracked / "daemon-host.pid").exists()
        assert (untracked / "daemon-host.log").exists()
        assert unrelated.exists()
        assert (unrelated / "stuff.json").exists()


class TestUpgradeVersionAlreadyAtTargetWiring:
    """The already-at-target branch cleans up after the verified restart.

    Driving the whole branch needs a git checkout, a network-free target and a
    live daemon, so this asserts the script's structure: inside the branch that
    starts at the ``ROLLBACK_REF`` comparison, the cleanup call follows the
    verified restart and the post-install checks and precedes ``exit 0``.
    """

    def test_cleanup_between_post_install_checks_and_exit(self) -> None:
        text = UPGRADE_VERSION_SH.read_text()
        start = text.index('if [ "$ROLLBACK_REF" = "$TARGET_VERSION" ]')
        end = text.index("\nfi\n", start)
        branch = text[start:end]

        restart = branch.index("restart_daemon_verified")
        checks = branch.index("run_post_install_checks")
        cleanup = branch.index('eager_cleanup_stale_venvs "$DAEMON_DIR" "$VENV_PATH"')
        exit_zero = branch.rindex("exit 0")
        assert restart < checks < cleanup < exit_zero

    def test_cleanup_call_not_nested_in_a_failure_branch(self) -> None:
        text = UPGRADE_VERSION_SH.read_text()
        start = text.index('if [ "$ROLLBACK_REF" = "$TARGET_VERSION" ]')
        end = text.index("\nfi\n", start)
        call = re.search(r"^ {4}eager_cleanup_stale_venvs ", text[start:end], re.MULTILINE)
        assert call is not None, "cleanup must sit at the branch's top level of indentation"
