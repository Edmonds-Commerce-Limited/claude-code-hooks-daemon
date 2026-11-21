"""`worktree-reap --reap` evacuates a worktree's scratch before removing it (Plan 00627 Task 6.2).

Root-level entries only, all or nothing, and only on a human's typed phrase at
a terminal. Every test runs on a real repository with a real linked worktree,
the real classification, the real archive store and GNU tar, because the
defects this guards against live in what git and the filesystem do.
"""

from __future__ import annotations

import argparse
import dataclasses
import io
import json
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from tests.support.scratch_tree import ScratchTree, build_git_project, commit_file, git

from claude_code_hooks_daemon.core.scratch_archive import ArchiveRecord, ArchiveStore
from claude_code_hooks_daemon.core.worktree_reaping import WorktreeState
from claude_code_hooks_daemon.core.worktree_scratch_evacuation import EvacuationGate
from claude_code_hooks_daemon.daemon.cli import (
    _daemon_untracked_dir,
    build_parser,
    cmd_scratch_sweep,
    cmd_worktree_reap,
)
from claude_code_hooks_daemon.daemon.worktree_evacuate import (
    EvacuateSeams,
    confirm_evacuate_interactively,
    evacuate_scratch,
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
    (project / ".claude" / "hooks-daemon").mkdir(parents=True, exist_ok=True)
    return built.tree


def _main(tree: ScratchTree) -> Path:
    return tree.base / "project"


def _worktree(tree: ScratchTree) -> Path:
    return _main(tree) / _RELATIVE


def _scratch(tree: ScratchTree) -> Path:
    return _worktree(tree) / "untracked" / "scratch"


def _store(tree: ScratchTree) -> Path:
    return _main(tree) / "untracked" / "scratch-archive"


_YOUNG_AHEAD = 3.0


def _wait_for_young_mtime(now: float) -> None:
    """Restore's tar refuses an mtime in the real future; wait until ``young.txt``'s is past."""
    time.sleep(max(0.0, now - _DAY - 1 + _YOUNG_AHEAD + 1 - time.time()))


def _write(path: Path, content: bytes, mtime: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    os.utime(path, (mtime, mtime))


def _set_mtime(path: Path, mtime: float) -> None:
    for dirpath, dirnames, filenames in os.walk(path):
        for name in dirnames + filenames:
            os.utime(Path(dirpath) / name, (mtime, mtime), follow_symlinks=False)
    os.utime(path, (mtime, mtime))


def _due_and_young(tree: ScratchTree) -> float:
    """``old/`` is past the 24h TTL; ``young.txt`` is not due. Returns the clock to run at.

    An entry's activity is the later of its mtime and its ctime, and a ctime cannot
    be set, so the only not-due entry beside a due one has an mtime a few seconds
    ahead; the clock is one second past the TTL from the ctimes.
    """
    base = time.time()
    scratch = _scratch(tree)
    _write(scratch / "old" / "a.txt", b"alpha", base - 5 * _DAY)
    _write(scratch / "old" / "sub" / "b.txt", b"beta", base - 5 * _DAY)
    _set_mtime(scratch / "old", base - 5 * _DAY)
    _write(scratch / "young.txt", b"not yet due", base + _YOUNG_AHEAD)
    return base + _DAY + 1


def _reap(
    tree: ScratchTree,
    *,
    reap: bool,
    now: float,
    confirm: Confirm | None = None,
    after_step: Callable[[str, str], None] | None = None,
    tar_path: str | None = None,
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
            after_step=after_step,
            tar_path=tar_path,
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
        now = _due_and_young(tree)
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
        _wait_for_young_mtime(now)
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
        now = _due_and_young(tree)
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
        now = _due_and_young(tree)
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
        now = _due_and_young(tree)
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


class _Killed(Exception):
    """A kill between two steps; deliberately not an OSError, which ``_pack`` reports."""


def _yes(_relative: str, _gate: EvacuationGate) -> bool:
    return True


def _all_due(tree: ScratchTree) -> dict[str, bytes]:
    """Two due entries; returns each file's content by path relative to the scratch root."""
    base = time.time()
    scratch = _scratch(tree)
    files = {"old/a.txt": b"alpha", "old/sub/b.txt": b"beta", "two.txt": b"second"}
    for relative, content in files.items():
        _write(scratch / relative, content, base - 5 * _DAY)
    _set_mtime(scratch / "old", base - 5 * _DAY)
    return files


def _due_clock() -> float:
    """Past the TTL measured from every ctime set so far."""
    return time.time() + _DAY + 60


def _restore_all(tree: ScratchTree, ids: list[str], now: float) -> Path:
    main_scratch = _main(tree) / "untracked" / "scratch"
    main_scratch.mkdir(parents=True, exist_ok=True)
    for archive_id in ids:
        args = build_parser().parse_args(["scratch-sweep", "restore", archive_id])
        args.project_root = _main(tree)
        assert cmd_scratch_sweep(args, wall_clock=lambda: now) == 0
    return main_scratch


class TestConvergence:
    @pytest.mark.parametrize(
        ("step", "occurrence"),
        [("claim", 1), ("pack", 1), ("append", 1), ("append", 2)],
        ids=["claim", "pack", "append", "after-the-last-archive"],
    )
    def test_a_kill_after_each_step_keeps_the_worktree_and_a_rerun_converges(
        self,
        tree: ScratchTree,
        capsys: pytest.CaptureFixture[str],
        step: str,
        occurrence: int,
    ) -> None:
        files = _all_due(tree)
        seen: list[str] = []

        def kill(at: str, _name: str) -> None:
            seen.append(at)
            if at == step and seen.count(step) == occurrence:
                raise _Killed(at)

        with pytest.raises(_Killed):
            _reap(tree, reap=True, now=_due_clock(), confirm=_yes, after_step=kill)
        assert _worktree(tree).is_dir()
        assert _NAME in git(_main(tree), "branch", "--list", _NAME)
        recorded = _store_records(tree)
        for entry in ("old", "two.txt"):
            on_disk = (_scratch(tree) / entry).exists() or (
                _scratch(tree) / f".sweeping-{entry}"
            ).exists()
            assert on_disk or f"untracked/scratch/{entry}" in recorded, entry
        capsys.readouterr()

        rc = _reap(tree, reap=True, now=_due_clock(), confirm=_yes)

        out = capsys.readouterr().out
        assert rc == 0, out
        assert not _worktree(tree).exists(), out
        store_ids = _store_ids(tree)
        printed = set(_restore_ids(out))
        if occurrence == 1:
            assert printed == set(store_ids), out
        else:
            assert len(printed) == 1 and printed <= set(store_ids), out
        main_scratch = _restore_all(tree, store_ids, _due_clock())
        for relative, content in files.items():
            assert (main_scratch / relative).read_bytes() == content, relative


def _store_records(tree: ScratchTree) -> dict[str, ArchiveRecord]:
    """The main store's latest record for each original path."""
    with ArchiveStore.open(_store(tree), create=False) as store:
        return {record.original_path: record for record in store.read_index().records}


def _store_ids(tree: ScratchTree) -> list[str]:
    return sorted(record.archive_id for record in _store_records(tree).values())


class TestThroughTheRealPrompt:
    @pytest.mark.parametrize(
        "typed",
        [f"evacuate {_RELATIVE}x\n", "evacuate\n", "\n", ""],
        ids=["wrong-phrase", "bare-word", "empty-line", "end-of-input"],
    )
    def test_anything_but_the_phrase_keeps_everything(
        self, tree: ScratchTree, monkeypatch: pytest.MonkeyPatch, typed: str
    ) -> None:
        now = _due_and_young(tree)
        before = _inodes(_worktree(tree))
        prompt = io.StringIO()
        out = _Stream(tty=True)
        monkeypatch.setattr("sys.stdin", _Stream(typed, tty=True))
        monkeypatch.setattr("sys.stdout", out)
        monkeypatch.setattr("sys.stderr", prompt)

        rc = _reap(tree, reap=True, now=now)

        assert f"Type 'evacuate {_RELATIVE}'" in prompt.getvalue()
        assert rc == 1
        assert _inodes(_worktree(tree)) == before
        assert not _store(tree).exists()
        assert f"worktree-reap --reap --only {_NAME}" in out.getvalue()

    def test_the_phrase_itself_reaps(
        self, tree: ScratchTree, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        now = _due_and_young(tree)
        monkeypatch.setattr("sys.stdin", _Stream(f"evacuate {_RELATIVE}\n", tty=True))
        monkeypatch.setattr("sys.stdout", _Stream(tty=True))
        monkeypatch.setattr("sys.stderr", io.StringIO())

        assert _reap(tree, reap=True, now=now) == 0
        assert not _worktree(tree).exists()


def _state(tree: ScratchTree) -> WorktreeState:
    return WorktreeState(
        name=_NAME,
        path=_worktree(tree),
        branch=_NAME,
        uncommitted_paths=(),
        commits_ahead_of_base=0,
        unlanded_patches=0,
        live_process_pids=(),
        age_seconds=999_999.0,
    )


def _seams(now: float, *, confirm: Confirm | None = None, **overrides: Any) -> EvacuateSeams:
    base = EvacuateSeams(
        confirm=confirm, wall_clock=lambda: now, process_cwds=lambda: {1: Path("/elsewhere")}
    )
    return dataclasses.replace(base, **overrides)


def _keep_text(out: str) -> str:
    return "\n".join(line for line in out.splitlines() if line.startswith("KEEP"))


def _background_file(checkout: Path) -> Path:
    return _daemon_untracked_dir(checkout) / "background-processes.jsonl"


class TestBackgroundRecords:
    @pytest.mark.parametrize("checkout", ["main", "worktree"])
    def test_a_record_in_either_checkout_naming_an_entry_blocks(
        self, tree: ScratchTree, checkout: str
    ) -> None:
        """Called directly: through the CLI the worktree's own record file sits
        under its ``.claude/``, itself a blocker that keeps the worktree first."""
        now = _due_and_young(tree)
        record = _background_file(_main(tree) if checkout == "main" else _worktree(tree))
        record.parent.mkdir(parents=True, exist_ok=True)
        command = f"tail -f {_scratch(tree).resolve()}/old/a.txt"
        record.write_text(json.dumps({"command": command}) + "\n", encoding="utf-8")

        result = evacuate_scratch(
            _main(tree), _state(tree), reap=True, seams=_seams(now, confirm=_never_asked)
        )

        assert not result.evacuated
        assert (_scratch(tree) / "old" / "a.txt").read_bytes() == b"alpha"
        assert not _store(tree).exists()
        assert any("old: LIVE" in line for line in result.lines), result.lines


class TestChangedWhileAsked:
    def test_a_not_due_entry_replaced_while_asked_is_not_packed(
        self, tree: ScratchTree, capsys: pytest.CaptureFixture[str]
    ) -> None:
        now = _due_and_young(tree)
        young = _scratch(tree) / "young.txt"
        mtime = young.stat().st_mtime

        def replace_then_yes(_relative: str, _gate: EvacuationGate) -> bool:
            swap = _scratch(tree) / "young.swap"
            _write(swap, b"replaced", mtime)
            swap.replace(young)
            return True

        rc = _reap(tree, reap=True, now=now, confirm=replace_then_yes)

        out = capsys.readouterr().out
        assert rc == 1
        assert _worktree(tree).is_dir()
        assert young.read_bytes() == b"replaced"
        assert "untracked/scratch/young.txt" not in _store_records(tree)
        assert "young.txt" in _keep_text(out), out

    def test_an_entry_created_while_asked_is_not_packed(
        self, tree: ScratchTree, capsys: pytest.CaptureFixture[str]
    ) -> None:
        now = _due_and_young(tree)
        mtime = (_scratch(tree) / "young.txt").stat().st_mtime

        def create_then_yes(_relative: str, _gate: EvacuationGate) -> bool:
            _write(_scratch(tree) / "new.txt", b"appeared", mtime)
            return True

        rc = _reap(tree, reap=True, now=now, confirm=create_then_yes)

        out = capsys.readouterr().out
        assert rc == 1
        assert _worktree(tree).is_dir()
        assert (_scratch(tree) / "new.txt").read_bytes() == b"appeared"
        assert "untracked/scratch/new.txt" not in _store_records(tree)
        assert "new.txt" in _keep_text(out), out
