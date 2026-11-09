"""``worktree-reap --reap-branches`` reports the merged branches it leaves alone.

Plan 00571 Task 2.4 (issue #165). Orphan pruning considers only agent-owned
names (Plans 00048/00349, widened to WorktreeCreate-recorded names by Plan 00558).
That scope stays. What changes is that a merged branch with no worktree, skipped
because of its name, is now named in the output with the command that does
delete it, instead of vanishing from the report.
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.core import worktree_reaping
from claude_code_hooks_daemon.core.branch_cleanup import sweep_clean_command
from claude_code_hooks_daemon.core.worktree_reaping import collect_skipped_merged_branches
from claude_code_hooks_daemon.daemon.branch_safety import DeletionReport
from claude_code_hooks_daemon.daemon.cli import build_parser, cmd_worktree_reap

_LISTING = """worktree /repo
HEAD aaa
branch refs/heads/main
"""

_ALL = (
    "refs/heads/main\nrefs/heads/agent-orphan-2\nrefs/heads/worktree-issue-174-screen-arch\n"
    "refs/heads/feature-x\nrefs/heads/develop\n"
)
_MERGED = (
    "refs/heads/main\nrefs/heads/agent-orphan-2\nrefs/heads/worktree-issue-174-screen-arch\n"
    "refs/heads/develop\n"
)


def _fake(cwd: Path, *args: str, **_: object) -> subprocess.CompletedProcess[str]:
    if args[:2] == ("worktree", "list"):
        return subprocess.CompletedProcess([], 0, _LISTING, "")
    if args[0] == "branch" and "--merged" in args:
        return subprocess.CompletedProcess([], 0, _MERGED, "")
    if args[0] == "branch" and "--list" in args:
        return subprocess.CompletedProcess([], 0, _ALL, "")
    if args[0] == "config":
        return subprocess.CompletedProcess([], 1, "", "")
    return subprocess.CompletedProcess([], 0, "", "")


def _args(**overrides: object) -> argparse.Namespace:
    defaults: dict[str, object] = {
        "project_root": "/repo",
        "base_branch": "main",
        "reap": False,
        "only": None,
        "reap_branches": True,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


@pytest.fixture(autouse=True)
def _delete_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    """The delete engine is real-git work, covered in test_cli_worktree_reap_merged_unpushed."""

    def fake(_repo: Path, names: list[str], **_kwargs: object) -> DeletionReport:
        return DeletionReport(deleted=tuple(names))

    monkeypatch.setattr(worktree_reaping, "delete_branches", fake)


def _reap(args: argparse.Namespace) -> int:
    return cmd_worktree_reap(
        args, run_fn=_fake, age_fn=lambda _p: 999_999.0, process_cwds_fn=lambda: {}
    )


class TestSkippedMergedBranches:
    def test_collects_only_merged_unattached_out_of_scope_names(self) -> None:
        skipped = collect_skipped_merged_branches(Path("/repo"), "main", run_fn=_fake)
        # agent-orphan-2 is in scope, feature-x is unmerged, main and develop are policy.
        assert skipped == ("worktree-issue-174-screen-arch",)

    def test_reap_branches_names_each_skip_and_the_clean_command(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _reap(_args())
        out = capsys.readouterr().out
        line = next(line for line in out.splitlines() if "worktree-issue-174-screen-arch" in line)
        assert line.startswith("SKIPPED")
        assert "not agent-owned" in line
        assert sweep_clean_command() in line
        assert "feature-x" not in out

    def test_without_reap_branches_no_skip_line(self, capsys: pytest.CaptureFixture[str]) -> None:
        _reap(_args(reap_branches=False))
        assert "SKIPPED" not in capsys.readouterr().out

    def test_a_skip_alone_does_not_change_the_exit_code(self) -> None:
        assert _reap(_args()) == 0

    def test_only_suppresses_the_skip_report(self, capsys: pytest.CaptureFixture[str]) -> None:
        _reap(_args(only="nothing-by-this-name"))
        assert "SKIPPED" not in capsys.readouterr().out


class TestHelpText:
    def test_reap_branches_help_names_both_scopes(self) -> None:
        parser = build_parser()
        sub = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
        reap = sub.choices["worktree-reap"]
        action = next(a for a in reap._actions if a.dest == "reap_branches")
        assert "WorktreeCreate" in (action.help or "")
        assert "branch-sweep --clean" in (action.help or "")
