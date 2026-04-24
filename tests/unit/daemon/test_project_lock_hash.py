"""Tests for ``compute_project_lock_hash()``.

Plan 00100 Phase 3: the metadata's ``lock_hash`` field must be stable, file-
content-deterministic, and collapse any change in ``pyproject.toml`` or
``uv.lock`` into a detectable hash change. The daemon compares this hash on
startup; mismatch → venv is stale → rebuild.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from claude_code_hooks_daemon.daemon.metadata import compute_project_lock_hash


class TestComputeProjectLockHash:
    """``compute_project_lock_hash()`` returns a stable sha256 of the lock inputs."""

    def _write_inputs(self, root: Path, pyproject: str, uv_lock: str | None = None) -> None:
        (root / "pyproject.toml").write_text(pyproject)
        if uv_lock is not None:
            (root / "uv.lock").write_text(uv_lock)

    def test_returns_sha256_prefixed_64_hex(self, tmp_path: Path) -> None:
        self._write_inputs(tmp_path, "[project]\nname='demo'\n", "version=1\n")
        result = compute_project_lock_hash(tmp_path)
        assert re.fullmatch(r"sha256:[0-9a-f]{64}", result)

    def test_is_stable_across_calls(self, tmp_path: Path) -> None:
        self._write_inputs(tmp_path, "[project]\nname='demo'\n", "version=1\n")
        assert compute_project_lock_hash(tmp_path) == compute_project_lock_hash(tmp_path)

    def test_changes_when_pyproject_changes(self, tmp_path: Path) -> None:
        self._write_inputs(tmp_path, "[project]\nname='a'\n", "lock\n")
        first = compute_project_lock_hash(tmp_path)
        (tmp_path / "pyproject.toml").write_text("[project]\nname='b'\n")
        second = compute_project_lock_hash(tmp_path)
        assert first != second

    def test_changes_when_uv_lock_changes(self, tmp_path: Path) -> None:
        self._write_inputs(tmp_path, "[project]\nname='x'\n", "lock-v1\n")
        first = compute_project_lock_hash(tmp_path)
        (tmp_path / "uv.lock").write_text("lock-v2\n")
        second = compute_project_lock_hash(tmp_path)
        assert first != second

    def test_missing_pyproject_raises(self, tmp_path: Path) -> None:
        """No pyproject.toml → cannot compute hash; fail fast."""
        with pytest.raises(FileNotFoundError):
            compute_project_lock_hash(tmp_path)

    def test_missing_uv_lock_is_tolerated(self, tmp_path: Path) -> None:
        """Projects may not yet have a uv.lock; hash covers pyproject alone."""
        (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n")
        result = compute_project_lock_hash(tmp_path)
        assert re.fullmatch(r"sha256:[0-9a-f]{64}", result)

    def test_presence_of_uv_lock_changes_hash(self, tmp_path: Path) -> None:
        """Adding a uv.lock changes the hash (otherwise stale venvs survive)."""
        (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n")
        without = compute_project_lock_hash(tmp_path)
        (tmp_path / "uv.lock").write_text("fresh-lock\n")
        with_lock = compute_project_lock_hash(tmp_path)
        assert without != with_lock
