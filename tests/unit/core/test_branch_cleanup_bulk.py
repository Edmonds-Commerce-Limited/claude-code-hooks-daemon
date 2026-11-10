"""Bulk ``branch-sweep --clean``: batched, resumable, dry-run first (Plan 00594 Task 3.4).

One real repository with several hundred branches and a bare remote, built with
``git fast-import`` so the fixture costs a fraction of a second. The subject is the
final state of the refs, never a mock's call list.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.config.models import BranchesConfig
from claude_code_hooks_daemon.core import branch_cleanup
from claude_code_hooks_daemon.core.branch_cleanup import (
    BULK_BATCH_SIZE,
    CleanupReport,
    clean_sweep,
    render,
)
from claude_code_hooks_daemon.core.branch_keep import keep_branch
from claude_code_hooks_daemon.core.branch_park import park_branch
from claude_code_hooks_daemon.daemon.branch_safety import DeletionReport

_ENV = {
    "GIT_AUTHOR_NAME": "Test Author",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "Test Author",
    "GIT_COMMITTER_EMAIL": "test@example.com",
    "PATH": "/usr/bin:/bin",
}
_CONFIG = BranchesConfig(default="main", exempt=["users/*"])
_MAIN_COMMITS = 76
_UNMERGED = 250
_KEPT = ("done/003", "done/004")
_PARKED = ("wip/001", "wip/002")
_DAY = 86400
_BATCHES = 2


def _git(repo: Path, *args: str, stdin: str | None = None) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        input=stdin,
        env={**_ENV, "HOME": str(repo)},
    ).stdout


def _fast_import_stream() -> str:
    """Main with a linear history, a branch at every commit but the last, plus wip branches."""
    ident = "Test Author <test@example.com> 1700000000 +0000"
    lines: list[str] = []
    for mark in range(1, _MAIN_COMMITS + 1):
        lines += [
            "commit refs/heads/main",
            f"mark :{mark}",
            f"committer {ident}",
            "data 3",
            f"c{mark % 10}",
            *([f"from :{mark - 1}"] if mark > 1 else []),
            f"M 644 inline f{mark}.txt",
            "data 2",
            "x",
        ]
    for mark in range(1, _MAIN_COMMITS):
        lines += [f"reset refs/heads/done/{mark:03d}", f"from :{mark}", ""]
    for index in range(1, _UNMERGED + 1):
        lines += [
            f"commit refs/heads/wip/{index:03d}",
            f"committer {ident}",
            "data 3",
            "wp",
            "from :1",
            f"M 644 inline wip{index}.txt",
            "data 2",
            "y",
        ]
    return "\n".join(lines) + "\n"


@pytest.fixture(scope="module")
def template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A repo + bare remote holding every branch, kept and parked ones recorded."""
    root = tmp_path_factory.mktemp("bulk-template")
    bare = root / "remote.git"
    repo = root / "repo"
    repo.mkdir()
    _git(root, "init", "--quiet", "--bare", "-b", "main", str(bare))
    _git(repo, "init", "--quiet", "-b", "main")
    _git(repo, "fast-import", "--quiet", stdin=_fast_import_stream())
    _git(repo, "checkout", "-q", "-f", "main")
    _git(repo, "remote", "add", "origin", str(bare))
    _git(repo, "push", "--quiet", "origin", "refs/heads/*:refs/heads/*")
    _git(repo, "fetch", "--quiet", "origin")
    for name in _KEPT:
        keep_branch(
            repo,
            [_git(repo, "rev-parse", f"refs/heads/{name}").strip()],
            reason="needed for the audit",
            remote="origin",
            user="Tess",
            now=time.time() - _DAY,
        )
    for name in _PARKED:
        park_branch(repo, name, reason="waiting on review", remote="origin")
    return root


@pytest.fixture
def world(template: Path, tmp_path: Path) -> tuple[Path, Path]:
    """A private copy of the template: ``(repo, bare)``."""
    shutil.copytree(template, tmp_path / "w", symlinks=True)
    repo, bare = tmp_path / "w" / "repo", tmp_path / "w" / "remote.git"
    _git(repo, "remote", "set-url", "origin", str(bare))
    return repo, bare


def _heads(repo: Path) -> set[str]:
    out = _git(repo, "for-each-ref", "--format=%(refname:short)", "refs/heads")
    return set(out.split())


def _sweep(repo: Path, tmp_path: Path, *, dry_run: bool = False) -> CleanupReport:
    return clean_sweep(repo, _CONFIG, dry_run=dry_run, bundle_dir=tmp_path / "bundles", remote=True)


def _bundled(bundles: tuple[Path, ...]) -> set[str]:
    heads: set[str] = set()
    for bundle in bundles:
        out = subprocess.run(
            ["git", "bundle", "list-heads", str(bundle)],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        heads |= {line.split()[1].removeprefix("refs/heads/") for line in out.splitlines()}
    return heads


def _expected_deleted() -> set[str]:
    return {f"done/{n:03d}" for n in range(1, _MAIN_COMMITS)} - set(_KEPT)


def _fail_nth_batch(
    monkeypatch: pytest.MonkeyPatch, nth: int, error: BaseException
) -> Callable[[], None]:
    """Make the ``nth`` batch's delete raise ``error``; returns a function that undoes it."""
    real = branch_cleanup.delete_branches
    calls = {"n": 0}

    def flaky(*args: Any, **kwargs: Any) -> DeletionReport:
        calls["n"] += 1
        if calls["n"] == nth:
            raise error
        return real(*args, **kwargs)

    monkeypatch.setattr(branch_cleanup, "delete_branches", flaky)
    return lambda: monkeypatch.setattr(branch_cleanup, "delete_branches", real)


class TestDryRun:
    def test_deletes_nothing_and_lists_every_branch_with_its_proof(
        self, world: tuple[Path, Path], tmp_path: Path
    ) -> None:
        repo, bare = world
        before = (_heads(repo), _heads(bare))
        report = _sweep(repo, tmp_path, dry_run=True)
        assert (_heads(repo), _heads(bare)) == before
        assert not (tmp_path / "bundles").exists()
        lines = "\n".join(report.commands)
        for name in sorted(_expected_deleted()):
            assert f"would delete {name} (" in lines
            assert f"would delete remote origin/{name} (tip " in lines
        assert all(kept not in lines for kept in _KEPT)
        assert "proven" in lines
        assert report.next_command is not None
        assert "--clean --remote --apply" in report.next_command
        assert any("--apply" in line for line in render(report))


@dataclass(frozen=True)
class _FullRun:
    """One uninterrupted apply, shared by the assertions below (it is the slow part)."""

    before: set[str]
    after: set[str]
    after_remote: set[str]
    report: CleanupReport
    again: CleanupReport


@pytest.fixture(scope="module")
def full_run(template: Path, tmp_path_factory: pytest.TempPathFactory) -> _FullRun:
    root = tmp_path_factory.mktemp("bulk-full")
    shutil.copytree(template, root / "w", symlinks=True)
    repo, bare = root / "w" / "repo", root / "w" / "remote.git"
    _git(repo, "remote", "set-url", "origin", str(bare))
    before = _heads(repo)
    report = _sweep(repo, root)
    return _FullRun(before, _heads(repo), _heads(bare), report, _sweep(repo, root))


class TestFullRun:
    def test_deletes_exactly_the_proven_merged_ones(self, full_run: _FullRun) -> None:
        gone = full_run.before - full_run.after
        assert gone == _expected_deleted()
        assert set(full_run.report.deleted) == gone
        assert {f"origin/{n}" for n in gone} == set(full_run.report.deleted_remote)
        assert full_run.after_remote == full_run.before - gone
        assert set(_KEPT) <= full_run.after and set(_PARKED) <= full_run.after
        assert {f"wip/{n:03d}" for n in range(1, _UNMERGED + 1)} <= full_run.after

    def test_runs_in_bounded_batches_with_a_bundle_each(self, full_run: _FullRun) -> None:
        total = len(_expected_deleted())
        assert len(full_run.report.bundles) == -(-total // BULK_BATCH_SIZE) == _BATCHES
        assert full_run.report.remaining == ()
        assert full_run.report.next_command is None

    def test_every_deleted_branch_is_recoverable_from_a_bundle(self, full_run: _FullRun) -> None:
        assert _bundled(full_run.report.bundles) >= set(full_run.report.deleted)

    def test_a_second_run_has_nothing_left_to_do(self, full_run: _FullRun) -> None:
        again = full_run.again
        assert again.deleted == () and again.bundles == () and again.remaining == ()


class TestResume:
    def test_a_failed_batch_stops_the_run_and_reports_what_remains(
        self, world: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo, _ = world
        before = _heads(repo)
        _fail_nth_batch(monkeypatch, 2, subprocess.CalledProcessError(1, "git bundle", "", "full"))
        report = _sweep(repo, tmp_path)
        assert report.stopped is not None and "batch 2 of 2 failed" in report.stopped
        assert before - _heads(repo) == set(report.deleted)
        assert len(report.deleted) == BULK_BATCH_SIZE
        assert set(report.remaining) == _expected_deleted() - set(report.deleted)
        assert report.next_command is not None

    def test_an_interrupted_run_resumes_to_the_uninterrupted_final_state(
        self, world: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo, bare = world
        everything = _heads(repo)
        undo = _fail_nth_batch(monkeypatch, 2, KeyboardInterrupt())
        first = _sweep(repo, tmp_path)
        assert first.stopped is not None
        assert len(first.deleted) == BULK_BATCH_SIZE
        assert len(first.remaining) == len(_expected_deleted()) - BULK_BATCH_SIZE
        assert first.next_command is not None and "--apply" in first.next_command
        assert "Resume with" in "\n".join(render(first))
        undo()
        second = _sweep(repo, tmp_path)
        assert second.stopped is None and second.remaining == ()
        assert set(first.deleted) | set(second.deleted) == _expected_deleted()
        assert set(first.deleted).isdisjoint(second.deleted)
        assert _heads(repo) == everything - _expected_deleted()
        assert _heads(bare) == everything - _expected_deleted()
        assert _bundled(first.bundles + second.bundles) >= _expected_deleted()

    def test_a_refused_push_and_a_branch_deleted_meanwhile_resume_cleanly(
        self, world: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo, bare = world
        hook = bare / "hooks" / "pre-receive"
        hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
        hook.chmod(0o755)
        everything = _heads(repo)
        real = branch_cleanup.delete_branches
        victim = "done/060"
        seen = {"n": 0}

        def racing(*args: Any, **kwargs: Any) -> DeletionReport:
            seen["n"] += 1
            if seen["n"] == 1:
                _git(repo, "branch", "-q", "-D", victim)
            return real(*args, **kwargs)

        monkeypatch.setattr(branch_cleanup, "delete_branches", racing)
        first = _sweep(repo, tmp_path)
        assert first.stopped is None
        assert victim not in first.deleted
        assert any(line.startswith(f"{victim}: already deleted") for line in first.skipped)
        assert first.deleted_remote == ()
        assert _heads(bare) == everything
        assert first.remaining and first.next_command is not None
        hook.unlink()
        second = _sweep(repo, tmp_path)
        assert _heads(bare) == everything - _expected_deleted()
        assert _heads(repo) == everything - _expected_deleted()
        assert second.remaining == ()
        assert _bundled(first.bundles + second.bundles) >= _expected_deleted() - {victim}
