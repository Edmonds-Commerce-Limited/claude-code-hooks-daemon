"""Every printed branch-cleanup remediation command survives a shell round trip.

The commands ``delete-branch``, ``cleanup_after_merge`` and the branch stop guard
print are pasted into a shell by a human or an agent. A worktree path with a space
(common under ``~/My Projects``) or a branch name with an apostrophe
(``fix/don't-retry``, a valid ref name) must reach git as ONE argument each, so
``shlex.split`` of the printed command must give back the original arguments.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from shlex import split as shlex_split

import pytest

from claude_code_hooks_daemon.config.models import BranchesConfig
from claude_code_hooks_daemon.core import branch_inventory
from claude_code_hooks_daemon.core.branch_cleanup import cleanup_after_merge
from claude_code_hooks_daemon.core.branch_stop_guard import _merged_commands
from claude_code_hooks_daemon.daemon.branch_safety import REFUSAL_WORKTREE, delete_branches
from tests.conftest import HERMETIC_GIT_EMAIL
from tests.support.git_fixtures import git_setup_timeout

_NAME = "fix/don't-retry"
_CONFIG = BranchesConfig(default="main")
_BACKTICKED = re.compile(r"`([^`]*)`")


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=True,
        capture_output=True,
        text=True,
        timeout=git_setup_timeout(),
    ).stdout.strip()


@pytest.fixture
def spaced(tmp_path: Path) -> tuple[Path, Path]:
    """``(repo, worktree)``: ``_NAME`` is merged into main and held by a worktree
    whose path contains a space."""
    root = tmp_path / "My Projects"
    remote = root / "remote.git"
    repo = root / "app"
    remote.mkdir(parents=True)
    repo.mkdir()
    _git(remote, "init", "-q", "--bare", "-b", "main")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", HERMETIC_GIT_EMAIL)
    _git(repo, "config", "user.name", "t")
    (repo / "a.txt").write_text("a\n", encoding="utf-8")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-q", "-m", "base")
    _git(repo, "remote", "add", "origin", str(remote))
    _git(repo, "push", "-q", "origin", "main")
    _git(repo, "remote", "set-head", "origin", "main")
    _git(repo, "branch", _NAME)
    tree = root / "work trees" / "dont retry"
    _git(repo, "worktree", "add", "-q", str(tree), _NAME)
    return repo, tree


def _is_wrapper_call(argv: list[str], *tail: str) -> bool:
    return argv[0].endswith("hooks-daemon") and argv[1:] == list(tail)


class TestDeleteBranchWorktreeStep:
    def test_the_linked_worktree_step_round_trips(self, spaced: tuple[Path, Path]) -> None:
        repo, tree = spaced
        report = delete_branches(repo, [_NAME], protected_ref="main", dry_run=True)
        (verdict,) = report.classifications
        assert verdict.refusal == REFUSAL_WORKTREE
        remove, rerun = _BACKTICKED.findall(verdict.detail)
        assert shlex_split(remove) == ["git", "worktree", "remove", str(tree)]
        assert _is_wrapper_call(shlex_split(rerun), "delete-branch", _NAME)

    def test_the_main_checkout_rerun_round_trips(self, spaced: tuple[Path, Path]) -> None:
        repo, tree = spaced
        _git(repo, "worktree", "remove", str(tree))
        _git(repo, "switch", "-q", _NAME)
        linked = repo.parent / "main tree"
        _git(repo, "worktree", "add", "-q", str(linked), "main")
        report = delete_branches(linked, [_NAME], protected_ref="main", dry_run=True)
        (rerun,) = _BACKTICKED.findall(report.classifications[0].detail)
        assert _is_wrapper_call(shlex_split(rerun), "delete-branch", _NAME)


class TestCleanupAfterMergeCommands:
    def test_the_held_branch_commands_round_trip(self, spaced: tuple[Path, Path]) -> None:
        repo, tree = spaced
        report = cleanup_after_merge(repo, [_NAME], config=_CONFIG, target="main", mode="act")
        remove, delete = report.commands[:2]
        assert shlex_split(remove) == ["git", "worktree", "remove", str(tree)]
        assert _is_wrapper_call(
            shlex_split(delete), "delete-branch", _NAME, "--protected-ref", "main"
        )

    def test_the_advised_delete_round_trips(self, spaced: tuple[Path, Path]) -> None:
        repo, tree = spaced
        _git(repo, "worktree", "remove", str(tree))
        report = cleanup_after_merge(repo, [_NAME], config=_CONFIG, target="main", mode="advise")
        assert _is_wrapper_call(
            shlex_split(report.commands[0]), "delete-branch", _NAME, "--protected-ref", "main"
        )

    def test_the_restore_line_round_trips(self, spaced: tuple[Path, Path]) -> None:
        repo, tree = spaced
        _git(repo, "worktree", "remove", str(tree))
        tip = _git(repo, "rev-parse", f"refs/heads/{_NAME}")
        report = cleanup_after_merge(repo, [_NAME], config=_CONFIG, target="main", mode="act")
        assert report.deleted == (_NAME,), report.skipped
        assert ["git", "branch", _NAME, tip] in [shlex_split(c) for c in report.commands]


class TestStopGuardMergedCommands:
    def test_every_merged_command_round_trips(self, spaced: tuple[Path, Path]) -> None:
        repo, tree = spaced
        _git(repo, "push", "-q", "origin", _NAME)
        record = branch_inventory.build_inventory(repo, _CONFIG).records[_NAME]
        assert record.worktree is not None
        commands = [shlex_split(c) for c in _merged_commands(record, "origin")]
        assert commands == [
            ["git", "worktree", "remove", str(record.worktree)],
            ["git", "branch", "-d", _NAME],
            ["git", "push", "origin", "--delete", _NAME],
        ]
        assert Path(record.worktree).resolve() == tree.resolve()
