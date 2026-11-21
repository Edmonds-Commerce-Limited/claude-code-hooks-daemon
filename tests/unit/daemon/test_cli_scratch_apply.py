"""``scratch-sweep --apply``, ``restore`` and ``keep`` (Plan 00627 Task 3.8 unit C).

The default stays a dry run, and a dry run never creates the archive store.
``--apply`` runs only in the main checkout (the store lives there alone) and
every refusal comes before the store is opened, because opening creates it.
The end-to-end test goes through the real parser, the real ``run_sweep`` on a
real git project, the real store and GNU tar.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import time
from collections.abc import Callable
from pathlib import Path

import pytest
from tests.support.scratch_tree import ScratchTree, build_git_project, git

from claude_code_hooks_daemon.daemon.cli import (
    build_parser,
    cmd_scratch_sweep,
    confirm_apply_interactively,
)

_DAY = 86400.0


@pytest.fixture
def tree(tmp_path: Path) -> ScratchTree:
    tree = build_git_project(tmp_path).tree
    (tmp_path / "project" / ".claude" / "hooks-daemon").mkdir(parents=True)
    return tree


def _project(tree: ScratchTree) -> Path:
    return tree.base / "project"


def _store(project: Path) -> Path:
    return project / "untracked" / "scratch-archive"


def _parse(project: Path, *argv: str) -> argparse.Namespace:
    args = build_parser().parse_args(["scratch-sweep", *argv])
    args.project_root = project
    return args


def _run(
    args: argparse.Namespace,
    *,
    now: float,
    cwds: Callable[[], dict[int, Path]] | None = None,
    confirm: Callable[[str], bool] | None = None,
) -> int:
    return int(
        args.func(
            args,
            wall_clock=lambda: now,
            process_cwds=cwds or (lambda: {1: Path("/elsewhere")}),
            confirm_apply=confirm or (lambda _root: True),
        )
    )


def _untracked_snapshot(project: Path) -> list[tuple[str, int, int]]:
    found = []
    for dirpath, dirnames, filenames in os.walk(project / "untracked"):
        for name in sorted(dirnames + filenames):
            path = Path(dirpath) / name
            info = path.lstat()
            found.append((str(path), info.st_ino, info.st_mtime_ns))
    return sorted(found)


def _linked_worktree(tree: ScratchTree) -> Path:
    linked = tree.base / "linked"
    git(_project(tree), "worktree", "add", "-q", "-b", "side", str(linked))
    (linked / ".claude" / "hooks-daemon").mkdir(parents=True, exist_ok=True)
    return linked


def _old_entry(tree: ScratchTree, now: float) -> None:
    tree.file("old/a.txt", b"alpha")
    tree.file("old/sub/b.txt", b"beta")
    tree.set_tree_mtime("old", now - 5 * _DAY)


class TestFlagSurface:
    def test_exactly_these_flags_and_subcommands(self) -> None:
        parser = build_parser()
        (top,) = [a for a in parser._actions if isinstance(a, argparse._SubParsersAction)]
        sweep = top.choices["scratch-sweep"]
        flags = {opt for action in sweep._actions for opt in action.option_strings}
        assert flags == {
            "-h",
            "--help",
            "--json",
            "--root",
            "--budget-seconds",
            "--max-inodes",
            "--apply",
        }
        (sub,) = [a for a in sweep._actions if isinstance(a, argparse._SubParsersAction)]
        assert set(sub.choices) == {"restore", "keep"}

        def surface(name: str) -> tuple[set[str], list[str]]:
            actions = sub.choices[name]._actions
            options = {opt for action in actions for opt in action.option_strings}
            positionals = [action.dest for action in actions if not action.option_strings]
            return options, positionals

        assert surface("restore") == ({"-h", "--help", "--entry"}, ["archive_id"])
        assert surface("keep") == (
            {"-h", "--help", "--reason", "--hours", "--entry"},
            ["archive_id"],
        )

    def test_the_default_is_a_dry_run(self) -> None:
        args = build_parser().parse_args(["scratch-sweep"])
        assert args.apply is False
        assert args.scratch_action is None
        assert args.func is cmd_scratch_sweep

    def test_keep_needs_a_reason(self) -> None:
        with pytest.raises(SystemExit):
            build_parser().parse_args(["scratch-sweep", "keep", "x"])


class TestDryRunNeverCreatesTheStore:
    def test_no_store_and_untracked_unchanged(
        self, tree: ScratchTree, capsys: pytest.CaptureFixture[str]
    ) -> None:
        now = time.time() + 3 * _DAY
        _old_entry(tree, now)
        project = _project(tree)
        before = _untracked_snapshot(project)
        assert _run(_parse(project), now=now) == 0
        assert not _store(project).exists()
        assert _untracked_snapshot(project) == before
        assert "old" in capsys.readouterr().out


class TestRefusals:
    def test_apply_with_a_subcommand_is_refused(
        self, tree: ScratchTree, capsys: pytest.CaptureFixture[str]
    ) -> None:
        project = _project(tree)
        assert _run(_parse(project, "--apply", "restore", "x"), now=time.time()) == 1
        assert not _store(project).exists()
        assert "--apply" in capsys.readouterr().err

    def test_apply_from_a_linked_worktree_is_refused(
        self, tree: ScratchTree, capsys: pytest.CaptureFixture[str]
    ) -> None:
        project = _project(tree)
        linked = _linked_worktree(tree)
        (linked / "untracked" / "scratch").mkdir(parents=True)
        (linked / "untracked" / "scratch" / "f.log").write_text("x")
        assert _run(_parse(linked, "--apply"), now=time.time() + 3 * _DAY) == 1
        assert not _store(linked).exists()
        assert not _store(project).exists()
        assert (linked / "untracked" / "scratch" / "f.log").exists()
        assert "main checkout" in capsys.readouterr().err

    @pytest.mark.parametrize("action", [("restore", "x"), ("keep", "x", "--reason", "r")])
    def test_restore_and_keep_from_a_linked_worktree_are_refused(
        self, tree: ScratchTree, action: tuple[str, ...]
    ) -> None:
        linked = _linked_worktree(tree)
        assert _run(_parse(linked, *action), now=time.time()) == 1
        assert not _store(linked).exists()

    def test_a_refused_root_creates_no_store(
        self, tree: ScratchTree, capsys: pytest.CaptureFixture[str]
    ) -> None:
        project = _project(tree)
        other = tree.base / "other"
        other.mkdir()
        assert _run(_parse(project, "--apply", "--root", str(other)), now=time.time()) == 1
        assert not _store(project).exists()
        assert "never swept" in capsys.readouterr().err

    def test_a_missing_root_creates_no_store(self, tree: ScratchTree) -> None:
        project = _project(tree)
        tree.root.rmdir()
        assert _run(_parse(project, "--apply"), now=time.time()) == 1
        assert not _store(project).exists()
        assert not tree.root.exists()

    @pytest.mark.parametrize("action", [("restore", "x"), ("keep", "x", "--reason", "r")])
    def test_restore_and_keep_without_a_store_create_none(
        self, tree: ScratchTree, action: tuple[str, ...]
    ) -> None:
        project = _project(tree)
        assert _run(_parse(project, *action), now=time.time()) == 1
        assert not _store(project).exists()


class TestFirstLevelRootsOnly:
    """F-BYPS F1: a protection whose source is outside a narrower root is invisible from it."""

    def _lend(self, tree: ScratchTree, now: float) -> Path:
        tree.file("lend/lender/a.txt", b"alpha")
        tree.set_tree_mtime("lend", now - 5 * _DAY)
        return tree.root / "lend"

    def test_apply_at_a_deeper_root_is_refused_before_the_store_exists(
        self, tree: ScratchTree, capsys: pytest.CaptureFixture[str]
    ) -> None:
        now = time.time() + 3 * _DAY
        lend = self._lend(tree, now)
        project = _project(tree)
        assert _run(_parse(project, "--apply", "--root", str(lend)), now=now) == 1
        assert not _store(project).exists()
        assert (lend / "lender" / "a.txt").read_bytes() == b"alpha"
        assert "first-level" in capsys.readouterr().err

    def test_restore_into_a_deeper_root_is_refused(
        self, tree: ScratchTree, capsys: pytest.CaptureFixture[str]
    ) -> None:
        now = time.time() + 3 * _DAY
        lend = self._lend(tree, now)
        project = _project(tree)
        _store(project).mkdir(mode=0o700)
        assert _run(_parse(project, "--root", str(lend), "restore", "x"), now=now) == 1
        assert "first-level" in capsys.readouterr().err

    @pytest.mark.parametrize("as_json", [False, True])
    def test_a_dry_run_at_a_deeper_root_says_it_is_not_apply_eligible(
        self, tree: ScratchTree, capsys: pytest.CaptureFixture[str], as_json: bool
    ) -> None:
        now = time.time() + 3 * _DAY
        lend = self._lend(tree, now)
        project = _project(tree)
        flags = ("--json",) if as_json else ()
        assert _run(_parse(project, *flags, "--root", str(lend)), now=now) == 0
        out = capsys.readouterr().out
        assert "not apply-eligible" in out
        if as_json:
            assert any("not apply-eligible" in note for note in json.loads(out)["notes"])

    def test_a_dry_run_at_the_first_level_root_has_no_such_note(
        self, tree: ScratchTree, capsys: pytest.CaptureFixture[str]
    ) -> None:
        now = time.time() + 3 * _DAY
        self._lend(tree, now)
        assert _run(_parse(_project(tree)), now=now) == 0
        assert "not apply-eligible" not in capsys.readouterr().out


class _Stream(io.StringIO):
    def __init__(self, text: str = "", *, tty: bool) -> None:
        super().__init__(text)
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


class TestHumanConfirmationGate:
    """F-BYPS F2: until KEPT and the expiry notice exist, a human types the go-ahead."""

    def test_a_declined_confirmation_refuses_before_the_store_exists(
        self, tree: ScratchTree, capsys: pytest.CaptureFixture[str]
    ) -> None:
        now = time.time() + 3 * _DAY
        _old_entry(tree, now)
        project = _project(tree)
        assert _run(_parse(project, "--apply"), now=now, confirm=lambda _root: False) == 1
        assert not _store(project).exists()
        assert (tree.root / "old" / "a.txt").read_bytes() == b"alpha"
        assert "confirmation" in capsys.readouterr().err

    def test_the_default_gate_refuses_without_a_terminal(
        self, tree: ScratchTree, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        now = time.time() + 3 * _DAY
        _old_entry(tree, now)
        project = _project(tree)
        monkeypatch.setattr("sys.stdin", _Stream("apply untracked/scratch\n", tty=False))
        args = _parse(project, "--apply")
        code = cmd_scratch_sweep(
            args, wall_clock=lambda: now, process_cwds=lambda: {1: Path("/elsewhere")}
        )
        assert code == 1
        assert not _store(project).exists()
        assert (tree.root / "old").is_dir()

    @pytest.mark.parametrize(
        ("stdin_tty", "stdout_tty", "typed"),
        [
            (False, True, "apply untracked/scratch\n"),
            (True, False, "apply untracked/scratch\n"),
            (True, True, ""),
            (True, True, "yes\n"),
            (True, True, "apply untracked/other\n"),
        ],
    )
    def test_the_real_gate_refuses(self, stdin_tty: bool, stdout_tty: bool, typed: str) -> None:
        assert not confirm_apply_interactively(
            "untracked/scratch",
            stdin=_Stream(typed, tty=stdin_tty),
            stdout=_Stream(tty=stdout_tty),
            prompt_stream=_Stream(tty=True),
        )

    def test_the_real_gate_accepts_the_exact_phrase_on_a_terminal(self) -> None:
        prompt = _Stream(tty=True)
        assert confirm_apply_interactively(
            "untracked/scratch",
            stdin=_Stream("apply untracked/scratch\n", tty=True),
            stdout=_Stream(tty=True),
            prompt_stream=prompt,
        )
        assert "apply untracked/scratch" in prompt.getvalue()

    def test_no_flag_reaches_the_gate(self) -> None:
        args = build_parser().parse_args(["scratch-sweep", "--apply"])
        assert not any("confirm" in key or "yes" in key for key in vars(args))


class TestEndToEnd:
    def test_apply_restore_keep_through_the_real_sweep(
        self, tree: ScratchTree, capsys: pytest.CaptureFixture[str]
    ) -> None:
        now = time.time() + 3 * _DAY
        _old_entry(tree, now)
        project = _project(tree)

        assert _run(_parse(project, "--apply", "--json"), now=now) == 0
        document = json.loads(capsys.readouterr().out)
        (outcome,) = [row for row in document["entries"] if row["name"] == "old"]
        assert outcome["outcome"] == "archived", document
        archive_id = outcome["archive_id"]
        assert not (tree.root / "old").exists()
        assert not (tree.root / ".sweeping-old").exists()
        assert _store(project).is_dir()

        # A keep must extend the expiry, so it is taken a day after the pack.
        later = now + _DAY
        assert _run(_parse(project, "keep", archive_id, "--reason", "need it"), now=later) == 0
        assert _run(_parse(project, "keep", archive_id, "--reason", "Need  it"), now=later) == 1
        capsys.readouterr()

        assert _run(_parse(project, "restore", archive_id), now=now) == 0
        assert (tree.root / "old" / "a.txt").read_bytes() == b"alpha"
        assert (tree.root / "old" / "sub" / "b.txt").read_bytes() == b"beta"
        assert archive_id in capsys.readouterr().out

    def test_the_keep_cap_comes_from_scratch_keep_max_keeps(
        self, tree: ScratchTree, capsys: pytest.CaptureFixture[str]
    ) -> None:
        now = time.time() + 3 * _DAY
        _old_entry(tree, now)
        project = _project(tree)
        (project / ".claude" / "hooks-daemon.yaml").write_text(
            'version: "2.0"\nscratch:\n  keep:\n    max_keeps: 1\n'
        )
        assert _run(_parse(project, "--apply", "--json"), now=now) == 0
        document = json.loads(capsys.readouterr().out)
        (outcome,) = [row for row in document["entries"] if row["name"] == "old"]
        archive_id = outcome["archive_id"]
        # Each keep must extend the expiry (held up to 168 hours from the pack).
        later = now + _DAY
        first = ("keep", archive_id, "--reason", "first", "--hours", "150")
        second = ("keep", archive_id, "--reason", "second", "--hours", "160")
        assert _run(_parse(project, *first), now=later) == 0
        assert _run(_parse(project, *second), now=later) == 1
        assert "cap of 1 keeps" in capsys.readouterr().err

    def test_a_malformed_ttl_refuses_apply_and_creates_no_store(
        self, tree: ScratchTree, capsys: pytest.CaptureFixture[str]
    ) -> None:
        now = time.time() + 3 * _DAY
        _old_entry(tree, now)
        project = _project(tree)
        (project / ".claude" / "hooks-daemon.yaml").write_text(
            'version: "2.0"\nscratch:\n  untracked_ttl:\n    scratch: "7 days"\n'
        )
        assert _run(_parse(project, "--apply"), now=now) == 1
        assert not _store(project).exists()
        assert (tree.root / "old" / "a.txt").read_bytes() == b"alpha"
        assert "7 days" in capsys.readouterr().err

    def test_a_live_entry_is_not_archived(
        self, tree: ScratchTree, capsys: pytest.CaptureFixture[str]
    ) -> None:
        now = time.time() + 3 * _DAY
        _old_entry(tree, now)
        project = _project(tree)
        held = tree.root.resolve() / "old" / "sub"
        assert _run(_parse(project, "--apply", "--json"), now=now, cwds=lambda: {4: held}) == 0
        assert (tree.root / "old" / "a.txt").read_bytes() == b"alpha"
        document = json.loads(capsys.readouterr().out)
        assert all(row["outcome"] != "archived" for row in document["entries"])
