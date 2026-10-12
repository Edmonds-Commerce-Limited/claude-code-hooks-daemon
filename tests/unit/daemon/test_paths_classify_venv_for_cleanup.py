"""Unit tests for ``classify_venv_for_cleanup`` and ``list-stale-venvs`` (N441)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from claude_code_hooks_daemon.daemon.paths import (
    classify_venv_for_cleanup,
    main,
    project_path_slug,
)

CURRENT_HASH = "sha256:" + "a" * 64
OTHER_HASH = "sha256:" + "b" * 64


def _venv(untracked: Path, name: str, lock_hash: str | None) -> Path:
    path = untracked / name
    path.mkdir(parents=True)
    if lock_hash is not None:
        (path / ".daemon-metadata.json").write_text(
            json.dumps({"python_path": "/x/bin/python", "lock_hash": lock_hash})
        )
    return path


class TestClassifyVenvForCleanup:
    """Removal needs a positive finding; everything else is kept with a reason."""

    def test_same_slug_mismatched_hash_removed(self, tmp_path: Path) -> None:
        venv = _venv(tmp_path, "venv-me-py311-abc12345", OTHER_HASH)
        assert classify_venv_for_cleanup(venv, "me", CURRENT_HASH)[0] is True

    def test_legacy_name_mismatched_hash_removed(self, tmp_path: Path) -> None:
        venv = _venv(tmp_path, "venv-py311-abc12345", OTHER_HASH)
        assert classify_venv_for_cleanup(venv, "me", CURRENT_HASH)[0] is True

    def test_other_slug_kept(self, tmp_path: Path) -> None:
        venv = _venv(tmp_path, "venv-them-py311-abc12345", OTHER_HASH)
        remove, reason = classify_venv_for_cleanup(venv, "me", CURRENT_HASH)
        assert remove is False
        assert "slug" in reason

    def test_matching_hash_kept(self, tmp_path: Path) -> None:
        venv = _venv(tmp_path, "venv-me-py311-abc12345", CURRENT_HASH)
        assert classify_venv_for_cleanup(venv, "me", CURRENT_HASH) == (
            False,
            "lock_hash matches the current source",
        )

    def test_missing_metadata_kept(self, tmp_path: Path) -> None:
        venv = _venv(tmp_path, "venv-me-py311-abc12345", None)
        remove, reason = classify_venv_for_cleanup(venv, "me", CURRENT_HASH)
        assert remove is False
        assert "metadata" in reason

    def test_uncomputable_current_hash_keeps_everything(self, tmp_path: Path) -> None:
        venv = _venv(tmp_path, "venv-me-py311-abc12345", OTHER_HASH)
        remove, reason = classify_venv_for_cleanup(venv, "me", None)
        assert remove is False
        assert "cannot compute" in reason


class TestListStaleVenvsCli:
    """The subcommand prints one verdict line per non-current venv-* directory."""

    def test_prints_verdicts_and_skips_current(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        daemon_dir = tmp_path / "proj"
        untracked = daemon_dir / "untracked"
        (daemon_dir / "pyproject.toml").parent.mkdir(parents=True)
        (daemon_dir / "pyproject.toml").write_text("[project]\n")
        slug = project_path_slug(daemon_dir)
        current = _venv(untracked, f"venv-{slug}-py311-deadbeef", OTHER_HASH)
        stale = _venv(untracked, f"venv-{slug}-py310-abc12345", OTHER_HASH)
        (untracked / "venv-notadir").write_text("file")

        code = main(
            [
                "list-stale-venvs",
                "--daemon-dir",
                str(daemon_dir),
                "--current-venv",
                str(current),
            ]
        )

        out = capsys.readouterr().out.splitlines()
        assert code == 0
        assert out == [f"remove\t{stale.resolve()}\tlock_hash differs from the current source"]
