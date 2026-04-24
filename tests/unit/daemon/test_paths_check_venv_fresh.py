"""Unit tests for ``_cli_check_venv_fresh`` (Plan 00100 Task 3.7).

Exit-code contract:

- 0 → venv's ``.daemon-metadata.json`` records a ``lock_hash`` that matches
  the current project's ``pyproject.toml`` (+ ``uv.lock``) state.
- 1 → any other state (venv missing, metadata missing/unreadable/wrong-shape,
  current project has no pyproject.toml, or lock_hashes differ).

The helper is invoked from ``scripts/install/venv.sh::venv_lock_hash_matches``
before the legacy ``.daemon-version`` stamp check, so correctness of the five
branches below directly drives the downgrade-safety fast path.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from claude_code_hooks_daemon.daemon.paths import _cli_check_venv_fresh


def _make_daemon_dir(tmp: Path) -> Path:
    """Minimal project layout: pyproject.toml only (uv.lock optional)."""
    daemon = tmp / "daemon"
    daemon.mkdir()
    (daemon / "pyproject.toml").write_text('[project]\nname = "fake"\n')
    return daemon


def _make_venv_with_metadata(venv_dir: Path, lock_hash: str) -> None:
    venv_dir.mkdir(parents=True)
    payload = {
        "python_path": str(venv_dir / "bin" / "python"),
        "fingerprint": "abcd1234",
        "lock_hash": lock_hash,
        "daemon_version": "v1.0.0",
        "written_at": "2026-01-01T00:00:00Z",
    }
    (venv_dir / ".daemon-metadata.json").write_text(json.dumps(payload))


def test_exit_0_when_lock_hash_matches(tmp_path: Path) -> None:
    daemon = _make_daemon_dir(tmp_path)
    venv = tmp_path / "venv"

    # Compute current lock_hash the same way the helper does.
    from claude_code_hooks_daemon.daemon.paths import _compute_project_lock_hash_stdlib

    current = _compute_project_lock_hash_stdlib(daemon)
    assert current is not None
    _make_venv_with_metadata(venv, lock_hash=current)

    args = argparse.Namespace(venv_path=str(venv), daemon_dir=str(daemon))
    assert _cli_check_venv_fresh(args) == 0


def test_exit_1_when_lock_hash_differs(tmp_path: Path) -> None:
    daemon = _make_daemon_dir(tmp_path)
    venv = tmp_path / "venv"
    _make_venv_with_metadata(venv, lock_hash="sha256:" + "0" * 64)

    args = argparse.Namespace(venv_path=str(venv), daemon_dir=str(daemon))
    assert _cli_check_venv_fresh(args) == 1


def test_exit_1_when_venv_dir_missing(tmp_path: Path) -> None:
    daemon = _make_daemon_dir(tmp_path)
    missing = tmp_path / "nope"

    args = argparse.Namespace(venv_path=str(missing), daemon_dir=str(daemon))
    assert _cli_check_venv_fresh(args) == 1


def test_exit_1_when_metadata_missing(tmp_path: Path) -> None:
    daemon = _make_daemon_dir(tmp_path)
    venv = tmp_path / "venv"
    venv.mkdir()  # exists, but no .daemon-metadata.json

    args = argparse.Namespace(venv_path=str(venv), daemon_dir=str(daemon))
    assert _cli_check_venv_fresh(args) == 1


def test_exit_1_when_project_has_no_pyproject(tmp_path: Path) -> None:
    daemon = tmp_path / "daemon_no_pyproject"
    daemon.mkdir()  # no pyproject.toml → cannot compute current lock_hash

    venv = tmp_path / "venv"
    _make_venv_with_metadata(venv, lock_hash="sha256:" + "a" * 64)

    args = argparse.Namespace(venv_path=str(venv), daemon_dir=str(daemon))
    assert _cli_check_venv_fresh(args) == 1


def test_daemon_dir_defaults_to_cwd(tmp_path: Path, monkeypatch) -> None:
    daemon = _make_daemon_dir(tmp_path)
    venv = tmp_path / "venv"

    from claude_code_hooks_daemon.daemon.paths import _compute_project_lock_hash_stdlib

    current = _compute_project_lock_hash_stdlib(daemon)
    assert current is not None
    _make_venv_with_metadata(venv, lock_hash=current)

    monkeypatch.chdir(daemon)
    args = argparse.Namespace(venv_path=str(venv), daemon_dir=None)
    assert _cli_check_venv_fresh(args) == 0
