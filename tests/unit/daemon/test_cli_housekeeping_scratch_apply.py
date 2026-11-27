"""``housekeeping --run scratch-sweep-apply``: the unconfirmed scratch apply (Plan 00627 R13).

The owner ruled that expired scratch may be cleaned without a confirmation
each time (Plan 00474 ledger). The housekeeping step therefore runs the SAME
apply core as ``scratch-sweep --apply`` -- the same classification, pressure
rules, hold window and archive store -- with no terminal question, and acts
only on what that core finds due. The ``scratch-sweep --apply`` verb keeps its
terminal gate: the unconfirmed path is this step alone.

Everything runs through the real parser, the real sweep on a real git project,
the real store and GNU tar (the fixtures of ``test_cli_scratch_apply.py``).
"""

from __future__ import annotations

import argparse
import io
import os
import re
import time
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from tests.support.scratch_tree import ScratchTree, build_git_project

from claude_code_hooks_daemon.core.scratch_archive_expire import ExpiryOutcome
from claude_code_hooks_daemon.daemon import cli
from claude_code_hooks_daemon.daemon.cli import (
    build_parser,
    cmd_housekeeping,
    cmd_scratch_sweep,
    run_scratch_sweep_apply_step,
)

_DAY = 86400.0
_HOUR = 3600.0
_SESSION = "s-20261101T000000Z-abcdefgh"
_ARCHIVE_LINE = re.compile(r"^\s+- (?P<path>\S+) archive (?P<id>\S+)$", re.MULTILINE)


class _Stream(io.StringIO):
    def __init__(self, text: str = "", *, tty: bool) -> None:
        super().__init__(text)
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


@pytest.fixture
def tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ScratchTree:
    tree = build_git_project(tmp_path).tree
    (tmp_path / "project" / ".claude" / "hooks-daemon").mkdir(parents=True)
    # No terminal anywhere: the step must act without one.
    monkeypatch.setattr("sys.stdin", _Stream("", tty=False))
    return tree


def _project(tree: ScratchTree) -> Path:
    return tree.base / "project"


def _store(project: Path) -> Path:
    return project / "untracked" / "scratch-archive"


def _step(
    tree: ScratchTree,
    *,
    now: float,
    cwds: Callable[[], dict[int, Path]] | None = None,
    scandir: Callable[[str], Any] = os.scandir,
) -> int:
    return run_scratch_sweep_apply_step(
        _project(tree),
        scandir=scandir,
        wall_clock=lambda: now,
        process_cwds=cwds or (lambda: {1: Path("/elsewhere")}),
    )


def _due(tree: ScratchTree, rel: str, now: float) -> None:
    tree.file(f"{rel}/a.txt", b"alpha")
    tree.set_tree_mtime(rel, now - 5 * _DAY)


def _archived(out: str) -> dict[str, str]:
    return {match["path"]: match["id"] for match in _ARCHIVE_LINE.finditer(out)}


class TestTheStepActsWithoutATerminal:
    def test_a_due_entry_is_archived_and_removed(
        self, tree: ScratchTree, capsys: pytest.CaptureFixture[str]
    ) -> None:
        now = time.time() + 3 * _DAY
        _due(tree, "old", now)
        assert _step(tree, now=now) == 0
        out = capsys.readouterr().out
        assert not (tree.root / "old").exists()
        assert _store(_project(tree)).is_dir()
        assert "removed 1 entry" in out
        assert "untracked/scratch/old" in _archived(out)
        # Names, never contents.
        assert "alpha" not in out

    def test_a_removed_entry_restores(
        self, tree: ScratchTree, capsys: pytest.CaptureFixture[str]
    ) -> None:
        now = time.time() + 3 * _DAY
        _due(tree, "old", now)
        assert _step(tree, now=now) == 0
        archive_id = _archived(capsys.readouterr().out)["untracked/scratch/old"]
        args = build_parser().parse_args(["scratch-sweep", "restore", archive_id])
        args.project_root = _project(tree)
        assert (
            cmd_scratch_sweep(args, wall_clock=lambda: now, process_cwds=lambda: {1: Path("/x")})
            == 0
        )
        assert (tree.root / "old" / "a.txt").read_bytes() == b"alpha"

    def test_nothing_due_removes_nothing_and_says_so(
        self, tree: ScratchTree, capsys: pytest.CaptureFixture[str]
    ) -> None:
        now = time.time()
        tree.file("fresh/a.txt", b"alpha", mtime=now - _HOUR)
        assert _step(tree, now=now) == 0
        assert (tree.root / "fresh" / "a.txt").read_bytes() == b"alpha"
        assert "removed 0 entries" in capsys.readouterr().out


class TestTheStepNeverTouchesWhatTheSweepProtects:
    def test_a_scratch_keep_entry_is_never_removed(
        self, tree: ScratchTree, capsys: pytest.CaptureFixture[str]
    ) -> None:
        now = time.time() + 3 * _DAY
        tree.file("pinned/a.txt", b"alpha")
        tree.file("pinned/.scratch-keep", b"hold\n")
        tree.set_tree_mtime("pinned", now - 5 * _DAY)
        assert _step(tree, now=now) == 0
        assert (tree.root / "pinned" / "a.txt").read_bytes() == b"alpha"
        assert "untracked/scratch/pinned" not in _archived(capsys.readouterr().out)

    def test_a_kept_child_of_a_session_is_never_removed(
        self, tree: ScratchTree, capsys: pytest.CaptureFixture[str]
    ) -> None:
        now = time.time() + 3 * _DAY
        tree.file(f"{_SESSION}/old/a.txt", b"alpha")
        tree.file(f"{_SESSION}/kept/a.txt", b"kept")
        tree.file(f"{_SESSION}/kept/.scratch-keep", b"hold\n")
        tree.set_tree_mtime(_SESSION, now - 5 * _DAY)
        assert _step(tree, now=now) == 0
        archived = _archived(capsys.readouterr().out)
        assert f"untracked/scratch/{_SESSION}/old" in archived
        assert (tree.root / _SESSION / "kept" / "a.txt").read_bytes() == b"kept"

    def test_a_live_session_directory_is_never_removed(
        self, tree: ScratchTree, capsys: pytest.CaptureFixture[str]
    ) -> None:
        now = time.time() + 3 * _DAY
        _due(tree, f"{_SESSION}/old", now)
        held = tree.root.resolve() / _SESSION
        assert _step(tree, now=now, cwds=lambda: {4: held}) == 0
        assert (tree.root / _SESSION / "old" / "a.txt").read_bytes() == b"alpha"
        assert _archived(capsys.readouterr().out) == {}

    def test_an_entry_inside_its_ttl_is_never_removed(
        self, tree: ScratchTree, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Three days ahead so the files' real birth time is past the TTL too.
        now = time.time() + 3 * _DAY
        tree.file("young/a.txt", b"alpha", mtime=now - _HOUR)
        _due(tree, "old", now)
        assert _step(tree, now=now) == 0
        archived = _archived(capsys.readouterr().out)
        assert set(archived) == {"untracked/scratch/old"}
        assert (tree.root / "young" / "a.txt").read_bytes() == b"alpha"


class TestTheStepNeverUsesPressureMode:
    """Review of PR 296, blocking 1: pressure mode packs IN-TTL entries, which the ruling excludes."""

    def test_caps_at_block_with_fresh_entries_remove_nothing(
        self, tree: ScratchTree, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Ahead of the real clock so each entry is idle (born days ago, touched an hour ago):
        # the shape pressure mode packs. Inside the TTL, so the step must leave them.
        now = time.time() + 3 * _DAY
        project = _project(tree)
        (project / ".claude" / "hooks-daemon.yaml").write_text(
            'version: "2.0"\nscratch:\n  caps:\n    entries:\n      warn: 2\n      block: 3\n'
        )
        for name in ("one", "two", "three", "four"):
            tree.file(f"{name}/a.txt", b"alpha", mtime=now - _HOUR)
        assert _step(tree, now=now) == 0
        for name in ("one", "two", "three", "four"):
            assert (tree.root / name / "a.txt").read_bytes() == b"alpha"
        assert _archived(capsys.readouterr().out) == {}

    def test_caps_at_block_still_remove_only_the_due_entry(
        self, tree: ScratchTree, capsys: pytest.CaptureFixture[str]
    ) -> None:
        now = time.time() + 3 * _DAY
        project = _project(tree)
        (project / ".claude" / "hooks-daemon.yaml").write_text(
            'version: "2.0"\nscratch:\n  caps:\n    entries:\n      warn: 2\n      block: 3\n'
        )
        for name in ("one", "two", "three"):
            tree.file(f"{name}/a.txt", b"alpha", mtime=now - _HOUR)
        _due(tree, "old", now)
        assert _step(tree, now=now) == 0
        assert set(_archived(capsys.readouterr().out)) == {"untracked/scratch/old"}
        for name in ("one", "two", "three"):
            assert (tree.root / name / "a.txt").read_bytes() == b"alpha"


class TestTheStepReadsTheProjectsOwnConfig:
    """Second review of PR 296, minor 1: a ``.yml`` config is the daemon's config too."""

    def test_a_yml_ttl_keeps_an_entry_the_default_ttl_would_remove(
        self, tree: ScratchTree, capsys: pytest.CaptureFixture[str]
    ) -> None:
        now = time.time() + 3 * _DAY
        project = _project(tree)
        (project / ".claude" / "hooks-daemon.yml").write_text(
            'version: "2.0"\nscratch:\n  untracked_ttl:\n    scratch: "30d"\n'
        )
        _due(tree, "old", now)
        assert _step(tree, now=now) == 0
        assert (tree.root / "old" / "a.txt").read_bytes() == b"alpha"
        assert _archived(capsys.readouterr().out) == {}

    def test_an_unreadable_config_removes_nothing(
        self, tree: ScratchTree, capsys: pytest.CaptureFixture[str]
    ) -> None:
        now = time.time() + 3 * _DAY
        project = _project(tree)
        (project / ".claude" / "hooks-daemon.yaml").write_text("scratch: [unclosed\n")
        _due(tree, "old", now)
        assert _step(tree, now=now) == 1
        assert not _store(project).exists()
        assert (tree.root / "old" / "a.txt").read_bytes() == b"alpha"
        assert "nothing was removed" in capsys.readouterr().err


class TestTheStepFailsClosed:
    def test_a_store_refusal_removes_nothing(
        self, tree: ScratchTree, capsys: pytest.CaptureFixture[str]
    ) -> None:
        now = time.time() + 3 * _DAY
        _due(tree, "old", now)
        project = _project(tree)
        (project / ".claude" / "hooks-daemon.yaml").write_text(
            'version: "2.0"\nscratch:\n  untracked_ttl:\n    scratch: "7 days"\n'
        )
        assert _step(tree, now=now) == 1
        assert not _store(project).exists()
        assert (tree.root / "old" / "a.txt").read_bytes() == b"alpha"
        err = capsys.readouterr().err
        assert "refused" in err
        assert "nothing was removed" in err

    def test_an_unreadable_directory_removes_nothing(
        self, tree: ScratchTree, capsys: pytest.CaptureFixture[str]
    ) -> None:
        now = time.time() + 3 * _DAY
        _due(tree, "old", now)
        _due(tree, "locked", now)
        assert _step(tree, now=now, scandir=tree.refusing_scandir("locked")) == 1
        assert not _store(_project(tree)).exists()
        assert (tree.root / "old" / "a.txt").read_bytes() == b"alpha"
        err = capsys.readouterr().err
        assert "incomplete" in err
        assert "nothing was removed" in err


class TestTheCliVerbKeepsItsGate:
    def test_scratch_sweep_apply_still_refuses_without_a_terminal(self, tree: ScratchTree) -> None:
        now = time.time() + 3 * _DAY
        _due(tree, "old", now)
        args = build_parser().parse_args(["scratch-sweep", "--apply"])
        args.project_root = _project(tree)
        code = cmd_scratch_sweep(
            args, wall_clock=lambda: now, process_cwds=lambda: {1: Path("/elsewhere")}
        )
        assert code == 1
        assert not _store(_project(tree)).exists()
        assert (tree.root / "old" / "a.txt").read_bytes() == b"alpha"

    def test_the_scratch_sweep_verb_gained_no_unconfirmed_flag(self) -> None:
        args = build_parser().parse_args(["scratch-sweep", "--apply"])
        assert not any(key in {"run", "unconfirmed", "yes"} for key in vars(args))


class _Recorder:
    """A stand-in step that records the root it was given and does nothing."""

    def __init__(self) -> None:
        self.roots: list[Path] = []

    def __call__(self, repo: Path) -> int:
        self.roots.append(repo)
        return 0


def _housekeeping_args(root: Path, *argv: str) -> argparse.Namespace:
    args = build_parser().parse_args(["housekeeping", *argv])
    args.project_root = str(root)
    return args


class TestTheHousekeepingRunFlag:
    def test_run_dispatches_the_step_for_this_project(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: list[Path] = []

        def fake(repo: Path) -> int:
            seen.append(repo)
            return 0

        monkeypatch.setattr(cli, "run_scratch_sweep_apply_step", fake)
        args = _housekeeping_args(tmp_path, "--run", "scratch-sweep-apply")
        assert cmd_housekeeping(args) == 0
        assert seen == [tmp_path]

    def test_the_global_project_root_reaches_the_step_through_main(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Review of PR 296, blocking 2: the real entry, global flag BEFORE the verb."""
        seen: list[Path] = []

        def fake(repo: Path) -> int:
            seen.append(repo)
            return 0

        monkeypatch.setattr(cli, "run_scratch_sweep_apply_step", fake)
        argv = ["claude-hooks-daemon", "--project-root", str(tmp_path), "housekeeping"]
        monkeypatch.setattr("sys.argv", [*argv, "--run", "scratch-sweep-apply"])
        assert cli.main() == 0
        assert seen == [tmp_path]

    def test_run_refuses_without_a_named_project_root(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """N768: a parse that dropped the root must never fall back to the working directory."""
        step = _Recorder()
        monkeypatch.setattr(cli, "run_scratch_sweep_apply_step", step)
        monkeypatch.chdir(tmp_path)
        args = build_parser().parse_args(["housekeeping", "--run", "scratch-sweep-apply"])
        assert cmd_housekeeping(args) == 2
        assert step.roots == []
        assert "--project-root" in capsys.readouterr().err

    def test_every_subcommand_project_root_leaves_room_for_the_global_anchor(self) -> None:
        """N766: a subparser default other than None or SUPPRESS would beat the wrapper's root."""
        parser = build_parser()
        (top,) = [a for a in parser._actions if isinstance(a, argparse._SubParsersAction)]
        pending = list(top.choices.items())
        offenders: list[str] = []
        while pending:
            name, sub = pending.pop()
            for action in sub._actions:
                if isinstance(action, argparse._SubParsersAction):
                    pending.extend((f"{name} {n}", p) for n, p in action.choices.items())
                elif "--project-root" in action.option_strings and action.default not in (
                    None,
                    argparse.SUPPRESS,
                ):
                    offenders.append(name)
        assert offenders == []

    @pytest.mark.parametrize(
        "extra", [("--list",), ("--apply", "prune-venvs")], ids=["list", "apply"]
    )
    def test_run_refuses_to_combine_with_list_or_apply(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        extra: tuple[str, ...],
    ) -> None:
        step = _Recorder()
        monkeypatch.setattr(cli, "run_scratch_sweep_apply_step", step)
        args = _housekeeping_args(tmp_path, "--run", "scratch-sweep-apply", *extra)
        assert cmd_housekeeping(args) == 2
        assert step.roots == []
        assert "--run cannot be combined" in capsys.readouterr().err

    def test_run_refuses_a_step_it_cannot_run_in_process(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        args = _housekeeping_args(tmp_path, "--run", "prune-venvs")
        assert cmd_housekeeping(args) == 2
        assert "scratch-sweep-apply" in capsys.readouterr().err


class TestTheExpiryReport:
    """Review of PR 296, minor: label each expiry by its outcome, and say it once."""

    @staticmethod
    def _result(*expired: ExpiryOutcome) -> SimpleNamespace:
        return SimpleNamespace(
            complete=True, incomplete_reasons=(), entries=(), expired=expired, notes=()
        )

    def test_a_held_archive_is_not_called_expired_and_each_is_listed_once(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        held = ExpiryOutcome("a-1", "held", "still named")
        gone = ExpiryOutcome("a-2", "expired", "")
        parts = [
            ("untracked/scratch", self._result(held, gone)),
            (f"untracked/scratch/{_SESSION}", self._result(held, gone)),
        ]
        cli._print_unconfirmed_apply(parts)
        out = capsys.readouterr().out
        assert out.count("a-1") == 1
        assert out.count("a-2") == 1
        held_line = next(line for line in out.splitlines() if "a-1" in line)
        assert "held" in held_line
        assert "expired" not in held_line
        assert "still named" in held_line
