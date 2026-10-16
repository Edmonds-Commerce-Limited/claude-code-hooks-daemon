"""Plan 00474 N469: is the venv a daemon runs from built for the current source?

A dependency change (pyproject.toml + uv.lock) leaves the old venv in place, and
the resolver still returns it when no venv matches the new lock. ``restart`` and
a cold start never build one, so the daemon keeps running without the new
dependency. ``venv_lock_drift`` is the one question the SessionStart advisory,
``restart`` and ``status`` ask to say so, naming ``repair``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from claude_code_hooks_daemon.daemon.paths import (
    _compute_project_lock_hash_stdlib,
    venv_lock_drift,
    venv_lock_drift_lines,
)

OLD_HASH = "sha256:" + "0" * 64


def _venv(path: Path, lock_hash: str | None) -> Path:
    (path / "bin").mkdir(parents=True)
    (path / "bin" / "python").symlink_to(Path(sys.executable).resolve())
    if lock_hash is not None:
        (path / ".daemon-metadata.json").write_text(
            json.dumps({"python_path": str(path / "bin" / "python"), "lock_hash": lock_hash})
        )
    return path


@pytest.fixture
def daemon_dir(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    (tmp_path / "uv.lock").write_text("version = 1\n")
    (tmp_path / "untracked").mkdir()
    return tmp_path


def _current(daemon_dir: Path) -> str:
    current = _compute_project_lock_hash_stdlib(daemon_dir)
    assert current is not None
    return current


class TestVenvLockDrift:
    def test_none_when_the_venv_was_built_for_this_source(self, daemon_dir: Path) -> None:
        venv = _venv(daemon_dir / "untracked" / "venv-x-py311-aaaaaaaa", _current(daemon_dir))

        assert venv_lock_drift(daemon_dir, venv) is None

    def test_names_both_hashes_when_the_lock_changed_since_the_build(
        self, daemon_dir: Path
    ) -> None:
        venv = _venv(daemon_dir / "untracked" / "venv-x-py311-aaaaaaaa", OLD_HASH)

        reason = venv_lock_drift(daemon_dir, venv)

        assert reason is not None
        assert str(venv) in reason
        assert OLD_HASH[:19] in reason
        assert _current(daemon_dir)[:19] in reason

    def test_a_dependency_change_turns_a_matching_venv_into_drift(self, daemon_dir: Path) -> None:
        venv = _venv(daemon_dir / "untracked" / "venv-x-py311-aaaaaaaa", _current(daemon_dir))
        (daemon_dir / "uv.lock").write_text("version = 1\n[[package]]\nname = 'new-dep'\n")

        assert venv_lock_drift(daemon_dir, venv) is not None

    def test_a_venv_with_no_metadata_is_not_proven_built_for_this_source(
        self, daemon_dir: Path
    ) -> None:
        venv = _venv(daemon_dir / "untracked" / "venv-x-py311-aaaaaaaa", None)

        reason = venv_lock_drift(daemon_dir, venv)

        assert reason is not None
        assert ".daemon-metadata.json" in reason

    def test_none_for_a_venv_that_is_not_one_of_the_daemons_own(
        self, daemon_dir: Path, tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        elsewhere = _venv(tmp_path_factory.mktemp("other") / "venv-x-py311-aaaaaaaa", OLD_HASH)

        assert venv_lock_drift(daemon_dir, elsewhere) is None

    def test_none_when_the_current_lock_hash_cannot_be_computed(self, daemon_dir: Path) -> None:
        venv = _venv(daemon_dir / "untracked" / "venv-x-py311-aaaaaaaa", OLD_HASH)
        (daemon_dir / "pyproject.toml").unlink()

        assert venv_lock_drift(daemon_dir, venv) is None


class TestVenvLockDriftLines:
    def test_lines_carry_the_reason_and_the_repair_command(self) -> None:
        lines = venv_lock_drift_lines("REASON-TEXT", "/abs/bin/hooks-daemon repair")

        text = "\n".join(lines)
        assert "REASON-TEXT" in text
        assert "/abs/bin/hooks-daemon repair" in text
        assert "NOT BUILT FOR THIS SOURCE" in text
