"""Tests for the seed-worktree CLI command (Plan 00613 Task 3.3).

The command re-applies the project's configured seed list to a worktree made
by hand. Its argument surface is pinned: one positional, the worktree, and no
option that could name a path to link or widen what is placed. Exit 0 when the
seeding succeeded (including nothing to place), 1 when it was refused.
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.daemon.cli import build_parser, cmd_seed_worktree

VAULT = "." + "vault" + "-pass"


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


@pytest.fixture
def worktree(tmp_path: Path) -> Path:
    root = tmp_path / "main"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "commit", "-q", "--allow-empty", "-m", "init", "--no-gpg-sign")
    (root / VAULT).write_text("not-a-real-secret\n", encoding="utf-8")
    (root / ".claude").mkdir()
    (root / ".claude" / "hooks-daemon.yaml").write_text(
        "version: '2.0'\nhandlers:\n  worktree_create:\n    worktree_create:\n"
        "      options:\n        seed:\n          entries:\n"
        f"            - path: {VAULT}\n              mode: symlink\n",
        encoding="utf-8",
    )
    # A protected link is placed only when the committed config lists it.
    _git(root, "add", ".claude/hooks-daemon.yaml")
    _git(root, "commit", "-q", "-m", "config", "--no-gpg-sign")
    path = tmp_path / "hand-made"
    _git(root, "worktree", "add", "-q", "-b", "hand", str(path))
    return path


def _seed_parser() -> argparse.ArgumentParser:
    parser = build_parser()
    sub = next(
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)  # argparse exposes no public accessor
    )
    return sub.choices["seed-worktree"]


class TestArgumentSurface:
    def test_exactly_one_positional_and_no_options_but_help(self) -> None:
        actions = [a for a in _seed_parser()._actions if not isinstance(a, argparse._HelpAction)]
        assert [(a.dest, a.option_strings) for a in actions] == [("worktree", [])]

    def test_an_extra_path_is_rejected_by_the_parser(self) -> None:
        with pytest.raises(SystemExit):
            build_parser().parse_args(["seed-worktree", "a", "b"])


class TestExitCodes:
    def test_success_places_the_link_and_exits_zero(
        self, worktree: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert cmd_seed_worktree(argparse.Namespace(worktree=str(worktree))) == 0
        assert (worktree / VAULT).is_symlink()
        assert "not-a-real-secret" not in capsys.readouterr().out

    def test_refusal_exits_one_and_says_why(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        stray = tmp_path / "stray"
        stray.mkdir()
        assert cmd_seed_worktree(argparse.Namespace(worktree=str(stray))) == 1
        assert "REFUSED" in capsys.readouterr().err
