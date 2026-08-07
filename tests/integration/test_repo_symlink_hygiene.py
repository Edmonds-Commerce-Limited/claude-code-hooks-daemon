"""Repo-hygiene regression: every tracked symlink must be relative and resolve.

MT-1/MT-1a (Plan 00198): the deprecated ``install.py`` self-install helpers
had no ``source == dest`` guard, so ``copy_slash_commands()`` unlinked the
real ``.claude/commands/hooks-daemon-update.md`` and replaced it with a
symlink pointing AT ITSELF, and ``copy_init_script()`` stored an ABSOLUTE
symlink target (the author's container path ``/workspace/init.sh``) instead
of a repo-relative one. Both defects are invisible to anyone working from the
same checkout the symlink was created in — they only surface in a fresh
clone on a different machine, which is exactly when a reviewer or a new
contributor hits them.

This test walks the tracked tree via git plumbing (not the working-copy
symlink, which may have been hand-patched without re-staging) so it catches
the defect class from the artifact every clone actually receives.
"""

import os
import subprocess
from pathlib import Path
from typing import Final

import pytest

_PROJECT_ROOT: Final[Path] = Path(__file__).parent.parent.parent
_SYMLINK_MODE: Final[str] = "120000"


def _repo_root() -> Path:
    """The git repository root — same value as ``_PROJECT_ROOT`` in this repo."""
    return _PROJECT_ROOT


def _tracked_symlinks(repo_root: Path) -> list[tuple[str, str]]:
    """Every tracked symlink as ``(repo_relative_path, blob_object_id)``.

    Uses ``git ls-files -s`` — the same plumbing that determines what a
    fresh ``git clone`` receives — rather than scanning the working copy,
    so a locally hand-fixed symlink that was never re-staged still fails.
    """
    # SECURITY: list-form subprocess, no shell=True, trusted system tool (git).
    result = subprocess.run(
        ["git", "-C", str(repo_root), "ls-files", "-s"],
        capture_output=True,
        text=True,
        check=True,
    )
    symlinks: list[tuple[str, str]] = []
    for line in result.stdout.splitlines():
        # Format: "<mode> <object> <stage>\t<path>"
        meta, path = line.split("\t", 1)
        mode, object_id, _stage = meta.split(" ")
        if mode == _SYMLINK_MODE:
            symlinks.append((path, object_id))
    return symlinks


def _blob_content(repo_root: Path, object_id: str) -> str:
    """The stored symlink target — the exact bytes a fresh clone receives."""
    # SECURITY: list-form subprocess, no shell=True, trusted system tool (git).
    result = subprocess.run(
        ["git", "-C", str(repo_root), "cat-file", "-p", object_id],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def _single_hop_target(link_path: Path, target: str) -> Path:
    """Where the stored target points, one hop, WITHOUT following filesystem symlinks.

    Deliberately pure path arithmetic (``os.path.normpath``), never
    ``Path.resolve()``/``os.path.realpath`` — a self-referential symlink
    resolves those via an actual ``stat()`` syscall chain that raises
    ``OSError: Too many levels of symbolic links`` (ELOOP), which would
    crash the test itself instead of reporting the defect as a finding.
    """
    raw = Path(target) if target.startswith("/") else link_path.parent / target
    return Path(os.path.normpath(str(raw)))


class TestTrackedSymlinksAreRelativeAndResolve:
    """Every git-tracked symlink must survive being cloned onto another machine."""

    def test_repo_has_at_least_one_tracked_symlink(self) -> None:
        """Guard the guard: if this ever hits zero, the test below is vacuous."""
        symlinks = _tracked_symlinks(_repo_root())
        assert symlinks, "Expected at least one tracked symlink (e.g. .claude/init.sh)"

    def test_no_tracked_symlink_stores_an_absolute_target(self) -> None:
        repo_root = _repo_root()
        offenders = []
        for path, object_id in _tracked_symlinks(repo_root):
            target = _blob_content(repo_root, object_id)
            if target.startswith("/"):
                offenders.append((path, target))

        assert not offenders, (
            "Tracked symlink(s) store an ABSOLUTE target — this leaks the "
            "author's local path and dangles on every other machine:\n"
            + "\n".join(f"  {path} -> {target}" for path, target in offenders)
        )

    def test_every_tracked_symlink_resolves_within_the_repo(self) -> None:
        """The stored target must resolve to a real path inside the clone.

        Resolved purely by path arithmetic against the stored blob target
        (never ``os.readlink``/``Path.resolve()`` on the working copy) so
        this test exercises exactly what a fresh clone would receive, and
        never crashes on a self-referential loop (see ``_single_hop_target``).
        """
        repo_root = _repo_root()
        dangling = []
        for path, object_id in _tracked_symlinks(repo_root):
            target = _blob_content(repo_root, object_id)
            link_path = repo_root / path
            resolved = _single_hop_target(link_path, target)
            if not resolved.exists():
                dangling.append((path, target, resolved))

        assert (
            not dangling
        ), "Tracked symlink(s) do not resolve to a real file in this clone:\n" + "\n".join(
            f"  {path} -> {target}  (resolved: {resolved}, does not exist)"
            for path, target, resolved in dangling
        )

    def test_no_tracked_symlink_is_self_referential(self) -> None:
        """A symlink resolving back to its own path is always a bug.

        This is the exact shape of the MT-1a defect: ``copy_slash_commands()``
        unlinked the real file and symlinked the path to itself, so every
        later run silently no-ops against a dangling self-loop.
        """
        repo_root = _repo_root()
        self_referential = []
        for path, object_id in _tracked_symlinks(repo_root):
            target = _blob_content(repo_root, object_id)
            link_path = repo_root / path
            resolved = _single_hop_target(link_path, target)
            if resolved == Path(os.path.normpath(str(link_path))):
                self_referential.append((path, target))

        assert (
            not self_referential
        ), "Tracked symlink(s) point AT THEMSELVES (dangling self-loop):\n" + "\n".join(
            f"  {path} -> {target}" for path, target in self_referential
        )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
