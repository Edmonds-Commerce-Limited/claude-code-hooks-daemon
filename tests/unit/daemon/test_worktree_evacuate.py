"""`worktree-reap --reap` evacuates a worktree's scratch before removing it (Plan 00627 Task 6.2).

Root-level entries only, all or nothing, and only on a human's typed phrase at
a terminal. Every test runs on a real repository with a real linked worktree,
the real classification, the real archive store and GNU tar, because the
defects this guards against live in what git and the filesystem do.
"""

from __future__ import annotations

import argparse
import io
import os
import time
from collections.abc import Callable
from pathlib import Path

import pytest
from tests.support.scratch_tree import ScratchTree, build_git_project, commit_file, git

from claude_code_hooks_daemon.core.worktree_scratch_evacuation import EvacuationGate
from claude_code_hooks_daemon.daemon.cli import build_parser, cmd_scratch_sweep, cmd_worktree_reap
from claude_code_hooks_daemon.daemon.worktree_evacuate import (
    EvacuateSeams,
    confirm_evacuate_interactively,
)

_DAY = 86400.0
_HOUR = 3600.0
_NAME = "agent-evac-1"
_RELATIVE = f".claude/worktrees/{_NAME}"
_SESSION = "s-20261121T000000Z-abcdefgh"

Confirm = Callable[[str, EvacuationGate], bool]


@pytest.fixture(autouse=True)
def _git_identity(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("GIT_AUTHOR_NAME", "Test Author")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "test@example.com")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "Test Author")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "test@example.com")
    monkeypatch.setenv("HOME", str(tmp_path))


@pytest.fixture
def tree(tmp_path: Path) -> ScratchTree:
    """The main checkout (``project``, pushed to ``origin``) and a linked agent worktree."""
    built = build_git_project(tmp_path)
    project = built.project
    commit_file(project, ".gitignore", "untracked/\n.claude/worktrees/\n", "ignore worktrees")
    git(project, "push", "-q", "origin", "main")
    git(project, "worktree", "add", "-q", "-b", _NAME, str(project / _RELATIVE))
    return built.tree


def _main(tree: ScratchTree) -> Path:
    return tree.base / "project"


def _worktree(tree: ScratchTree) -> Path:
    return _main(tree) / _RELATIVE


def _scratch(tree: ScratchTree) -> Path:
    return _worktree(tree) / "untracked" / "scratch"


def _store(tree: ScratchTree) -> Path:
    return _main(tree) / "untracked" / "scratch-archive"


def _write(path: Path, content: bytes, mtime: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    os.utime(path, (mtime, mtime))


def _set_mtime(path: Path, mtime: float) -> None:
    for dirpath, dirnames, filenames in os.walk(path):
        for name in dirnames + filenames:
            os.utime(Path(dirpath) / name, (mtime, mtime), follow_symlinks=False)
    os.utime(path, (mtime, mtime))


def _due_and_young(tree: ScratchTree, now: float) -> None:
    """``old/`` is past the 24h TTL; ``young.txt`` is idle past the minimum age but not due."""
    scratch = _scratch(tree)
    _write(scratch / "old" / "a.txt", b"alpha", now - 5 * _DAY)
    _write(scratch / "old" / "sub" / "b.txt", b"beta", now - 5 * _DAY)
    _set_mtime(scratch / "old", now - 5 * _DAY)
    _write(scratch / "young.txt", b"not yet due", now - 2 * _HOUR)


def _reap(
    tree: ScratchTree,
    *,
    reap: bool,
    now: float,
    confirm: Confirm | None = None,
) -> int:
    args = argparse.Namespace(
        project_root=str(_main(tree)),
        base_branch="main",
        reap=reap,
        only=_NAME,
        reap_branches=False,
    )
    return cmd_worktree_reap(
        args,
        age_fn=lambda _p: 999_999.0,
        process_cwds_fn=lambda: {},
        evacuate_seams=EvacuateSeams(
            confirm=confirm,
            wall_clock=lambda: now,
            process_cwds=lambda: {1: Path("/elsewhere")},
        ),
    )


def _never_asked(_relative: str, _gate: EvacuationGate) -> bool:
    raise AssertionError("the question was asked")


def _inodes(*roots: Path) -> list[tuple[str, int, int]]:
    found = []
    for root in roots:
        if not root.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            for name in sorted(dirnames + filenames):
                info = (Path(dirpath) / name).lstat()
                found.append((str(Path(dirpath) / name), info.st_ino, info.st_mtime_ns))
    return sorted(found)


def _restore_ids(out: str) -> list[str]:
    marker = "scratch-sweep restore "
    return [
        line.split(marker, 1)[1].split()[0].strip("`;,")
        for line in out.splitlines()
        if marker in line
    ]


class _Stream(io.StringIO):
    def __init__(self, text: str = "", *, tty: bool) -> None:
        super().__init__(text)
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


class TestMinimum:
    def test_the_happy_path_archives_reaps_and_restores_byte_for_byte(
        self, tree: ScratchTree, capsys: pytest.CaptureFixture[str]
    ) -> None:
        now = time.time() + 3 * _DAY
        _due_and_young(tree, now)
        asked: list[tuple[str, EvacuationGate]] = []

        def yes(relative: str, gate: EvacuationGate) -> bool:
            asked.append((relative, gate))
            return True

        _reap(tree, reap=True, now=now, confirm=yes)

        out = capsys.readouterr().out
        assert [relative for relative, _ in asked] == [_RELATIVE]
        assert asked[0][1].not_due == 1
        assert not _worktree(tree).exists(), out
        assert _NAME not in git(_main(tree), "branch", "--list", _NAME)
        ids = _restore_ids(out)
        assert len(ids) == 2, out
        main_scratch = _main(tree) / "untracked" / "scratch"
        main_scratch.mkdir(parents=True, exist_ok=True)
        for archive_id in ids:
            args = build_parser().parse_args(["scratch-sweep", "restore", archive_id])
            args.project_root = _main(tree)
            assert cmd_scratch_sweep(args, wall_clock=lambda: now) == 0
        assert (main_scratch / "old" / "a.txt").read_bytes() == b"alpha"
        assert (main_scratch / "old" / "sub" / "b.txt").read_bytes() == b"beta"
        assert (main_scratch / "young.txt").read_bytes() == b"not yet due"

    def test_no_terminal_keeps_the_worktree_and_creates_no_store(
        self,
        tree: ScratchTree,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        now = time.time() + 3 * _DAY
        _due_and_young(tree, now)
        monkeypatch.setattr("sys.stdin", _Stream(f"evacuate {_RELATIVE}\n", tty=False))

        rc = _reap(tree, reap=True, now=now)

        out = capsys.readouterr().out
        assert rc == 1
        assert _worktree(tree).is_dir()
        assert (_scratch(tree) / "young.txt").read_bytes() == b"not yet due"
        assert not _store(tree).exists()
        assert f"worktree-reap --reap --only {_NAME}" in out

    def test_session_children_keep_the_worktree_without_asking(
        self, tree: ScratchTree, capsys: pytest.CaptureFixture[str]
    ) -> None:
        now = time.time() + 3 * _DAY
        _due_and_young(tree, now)
        _write(_scratch(tree) / _SESSION / "child.txt", b"session work", now - 5 * _DAY)

        rc = _reap(tree, reap=True, now=now, confirm=_never_asked)

        out = capsys.readouterr().out
        assert rc == 1
        assert _worktree(tree).is_dir()
        assert not _store(tree).exists()
        line = next(line for line in out.splitlines() if _SESSION in line)
        assert line.startswith("KEEP")
        assert "by hand" in out

    def test_a_dry_run_changes_no_inode_and_never_asks(
        self, tree: ScratchTree, capsys: pytest.CaptureFixture[str]
    ) -> None:
        now = time.time() + 3 * _DAY
        _due_and_young(tree, now)
        before = _inodes(_worktree(tree), _main(tree) / "untracked")

        _reap(tree, reap=False, now=now, confirm=_never_asked)

        assert _inodes(_worktree(tree), _main(tree) / "untracked") == before
        assert not _store(tree).exists()
        out = capsys.readouterr().out
        assert "would remove" not in out.lower()
        assert "young.txt" in out or "2 entr" in out


class TestTheQuestion:
    def _gate(self) -> EvacuationGate:
        return EvacuationGate(
            blockers=(),
            consent=None,
            entries=2,
            not_due=1,
            by_verdict=(("DISPOSABLE", 2),),
        )

    @pytest.mark.parametrize(
        ("stdin_tty", "stdout_tty", "typed", "expected"),
        [
            (True, True, f"evacuate {_RELATIVE}\n", True),
            (False, True, f"evacuate {_RELATIVE}\n", False),
            (True, False, f"evacuate {_RELATIVE}\n", False),
            (True, True, "yes\n", False),
            (True, True, f"evacuate {_RELATIVE}/\n", False),
            (True, True, "\n", False),
            (True, True, "", False),
        ],
    )
    def test_only_the_exact_phrase_at_a_terminal_consents(
        self, stdin_tty: bool, stdout_tty: bool, typed: str, expected: bool
    ) -> None:
        prompt = io.StringIO()
        answer = confirm_evacuate_interactively(
            _RELATIVE,
            self._gate(),
            stdin=_Stream(typed, tty=stdin_tty),
            stdout=_Stream(tty=stdout_tty),
            prompt_stream=prompt,
        )
        assert answer is expected

    def test_the_prompt_states_what_happens(self) -> None:
        prompt = io.StringIO()
        confirm_evacuate_interactively(
            _RELATIVE,
            self._gate(),
            stdin=_Stream("no\n", tty=True),
            stdout=_Stream(tty=True),
            prompt_stream=prompt,
        )
        text = prompt.getvalue()
        assert _RELATIVE in text
        assert "2 entries" in text
        assert "1 not yet due" in text
        assert "DISPOSABLE 2" in text
        assert "restore" in text
        assert "removed" in text
        assert f"evacuate {_RELATIVE}" in text

    def test_no_option_stands_in_for_the_question(self) -> None:
        args = build_parser().parse_args(["worktree-reap"])
        keys = [key for key in vars(args) if "confirm" in key or "yes" in key]
        assert keys == []
