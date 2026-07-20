"""Regression tests for Plan 00184: symlinked venv double-counting / deletion.

Covers the data-loss incident where a symlink venv dir (e.g.
``untracked/venv-py311-66bbc57c`` -> ``untracked/venv``) caused
``_enumerate_venvs``/``disk-usage`` to double-count the same bytes under two
entries, and ``prune-venvs --legacy`` to delete the real target directory
even though the daemon's bootstrap resolver (``resolve_existing_venv_python``)
was actively serving it via the symlink.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.daemon import cli


def _make_venv(path: Path, stamp_version: str | None = None) -> None:
    """Materialise a fake venv on disk that looks healthy enough for listing."""
    (path / "bin").mkdir(parents=True)
    (path / "bin" / "python").write_text('#!/bin/sh\nexec /usr/bin/python3 "$@"\n')
    (path / "bin" / "python").chmod(0o755)
    if stamp_version is not None:
        (path / ".daemon-version").write_text(stamp_version)


def _mark_self_install(project_root: Path) -> None:
    (project_root / "src" / "claude_code_hooks_daemon").mkdir(parents=True, exist_ok=True)


def _args(
    project_root: Path,
    *,
    json_output: bool = False,
    legacy: bool = False,
    stale: bool = False,
    all_except_current: bool = False,
    dry_run: bool = False,
    force: bool = False,
) -> argparse.Namespace:
    return argparse.Namespace(
        project_root=project_root,
        json=json_output,
        legacy=legacy,
        stale=stale,
        all_except_current=all_except_current,
        dry_run=dry_run,
        force=force,
    )


@pytest.fixture
def symlinked_project(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Build a project with a legacy real ``venv/`` and a symlink pointing at it.

    The symlink is named like a fingerprint-keyed venv (but NOT the current
    fingerprint, mirroring the real incident where the fingerprint scheme had
    migrated and left a stale-named symlink behind). Returns
    ``(project_root, real_venv_dir, symlink_venv_dir)``.
    """
    _mark_self_install(tmp_path)
    untracked = tmp_path / "untracked"
    untracked.mkdir()

    real_venv = untracked / "venv"
    _make_venv(real_venv, stamp_version="v3.5.0")

    symlink_venv = untracked / "venv-py311-66bbc57c"
    symlink_venv.symlink_to(real_venv, target_is_directory=True)

    return tmp_path, real_venv, symlink_venv


class TestEnumerateVenvsDedup:
    def test_symlink_and_target_dedup_to_one_entry(
        self, symlinked_project: tuple[Path, Path, Path]
    ) -> None:
        project_root, real_venv, symlink_venv = symlinked_project

        with patch(
            "claude_code_hooks_daemon.daemon.cli.resolve_existing_venv_python",
            return_value=symlink_venv / "bin" / "python",
        ):
            entries = cli._enumerate_venvs(project_root)

        matching = [e for e in entries if Path(e["real_path"]) == real_venv.resolve()]
        assert len(matching) == 1, f"expected exactly one deduped entry, got {matching}"

    def test_resolver_active_entry_marked_current_even_if_fingerprint_differs(
        self, symlinked_project: tuple[Path, Path, Path]
    ) -> None:
        project_root, real_venv, symlink_venv = symlinked_project

        with patch(
            "claude_code_hooks_daemon.daemon.cli.resolve_existing_venv_python",
            return_value=symlink_venv / "bin" / "python",
        ):
            entries = cli._enumerate_venvs(project_root)

        matching = [e for e in entries if Path(e["real_path"]) == real_venv.resolve()]
        assert len(matching) == 1
        assert matching[0]["is_current"] is True


class TestReclaimableExcludesActive:
    def test_reclaimable_entries_excludes_resolver_active_venv(
        self, symlinked_project: tuple[Path, Path, Path]
    ) -> None:
        project_root, real_venv, symlink_venv = symlinked_project

        with patch(
            "claude_code_hooks_daemon.daemon.cli.resolve_existing_venv_python",
            return_value=symlink_venv / "bin" / "python",
        ):
            entries = cli._enumerate_venvs(project_root)
            reclaimable = cli._reclaimable_venv_entries(entries, current_stamp="")

        reclaimable_realpaths = {Path(e["real_path"]) for e in reclaimable}
        assert real_venv.resolve() not in reclaimable_realpaths


class TestPruneVenvsNeverDeletesActive:
    def test_prune_legacy_force_does_not_delete_resolver_active_venv(
        self, symlinked_project: tuple[Path, Path, Path]
    ) -> None:
        project_root, real_venv, symlink_venv = symlinked_project

        with (
            patch(
                "claude_code_hooks_daemon.daemon.cli.resolve_existing_venv_python",
                return_value=symlink_venv / "bin" / "python",
            ),
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_project_path",
                return_value=project_root,
            ),
        ):
            rc = cli.cmd_prune_venvs(_args(project_root, legacy=True, force=True))

        assert rc == 0
        assert real_venv.is_dir(), "resolver-active real venv dir was deleted!"
        assert symlink_venv.is_symlink(), "symlink to active venv was removed!"

    def test_prune_stale_force_does_not_delete_resolver_active_venv(
        self, symlinked_project: tuple[Path, Path, Path]
    ) -> None:
        project_root, real_venv, symlink_venv = symlinked_project

        with (
            patch(
                "claude_code_hooks_daemon.daemon.cli.resolve_existing_venv_python",
                return_value=symlink_venv / "bin" / "python",
            ),
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_project_path",
                return_value=project_root,
            ),
        ):
            rc = cli.cmd_prune_venvs(_args(project_root, stale=True, force=True))

        assert rc == 0
        assert real_venv.is_dir(), "resolver-active real venv dir was deleted!"


class TestDiskUsageNoDoubleCount:
    def test_disk_usage_venvs_row_not_double_counted(
        self, symlinked_project: tuple[Path, Path, Path]
    ) -> None:
        project_root, real_venv, symlink_venv = symlinked_project

        with (
            patch(
                "claude_code_hooks_daemon.daemon.cli.resolve_existing_venv_python",
                return_value=symlink_venv / "bin" / "python",
            ),
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_project_path",
                return_value=project_root,
            ),
        ):
            rows = cli._collect_disk_usage(project_root)

        venv_row = next(row for row in rows if row["name"] == "venvs")
        actual_size = cli._directory_size_bytes(real_venv)

        assert venv_row["size_bytes"] == actual_size, (
            f"expected single-dir size {actual_size}, got {venv_row['size_bytes']} "
            "(likely double-counted symlink + target)"
        )
        assert venv_row["reclaimable_bytes"] == 0
