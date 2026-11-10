"""Every remote delete the sweep prints passes the guard that judges it (Plan 00594 Task 4.7).

Real repositories with a bare remote. The sweep's report and ``--clean`` advice are
rendered, each ``git push ... --delete`` line is fed to the destructive_git handler as a
Bash command from that repository, and every one must be allowed. A branch the guard's
proof cannot establish gets owner-only wording, never a runnable line.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.config.models import BranchesConfig
from claude_code_hooks_daemon.core import branch_cleanup, branch_inventory, branch_sweep
from claude_code_hooks_daemon.core.data_layer import reset_data_layer
from claude_code_hooks_daemon.handlers.pre_tool_use.destructive_git import DestructiveGitHandler

_ENV = {
    "GIT_AUTHOR_NAME": "Test Author",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "Test Author",
    "GIT_COMMITTER_EMAIL": "test@example.com",
    "PATH": "/usr/bin:/bin",
}
_CONFIG = BranchesConfig(default="main")
_DELETE_LINE = re.compile(r"git push \S+ --delete \S+")


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        env={**_ENV, "HOME": str(repo)},
    ).stdout


def _commit(repo: Path, filename: str, text: str) -> None:
    (repo / filename).write_text(text, encoding="utf-8")
    _git(repo, "add", filename)
    _git(repo, "commit", "-m", f"Add {filename}")


@pytest.fixture(autouse=True)
def _reset_tracker() -> Any:
    reset_data_layer()
    yield
    reset_data_layer()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    bare = tmp_path / "remote.git"
    _git(tmp_path, "init", "--quiet", "--bare", "-b", "main", str(bare))
    path = tmp_path / "repo"
    path.mkdir()
    _git(path, "init", "-b", "main")
    _git(path, "config", "user.email", "test@example.com")
    _commit(path, "base.txt", "base\n")
    _git(path, "remote", "add", "origin", str(bare))
    _git(path, "push", "--quiet", "origin", "main")
    _git(path, "remote", "set-head", "origin", "main")
    return path


def _squash_merged(repo: Path, name: str) -> None:
    """Push ``name``, squash it into main (patch-equivalent, not an ancestor), push main."""
    _git(repo, "checkout", "-q", "-b", name)
    _commit(repo, f"{name}.txt", f"{name}\n")
    _git(repo, "push", "--quiet", "origin", name)
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "--squash", name)
    _git(repo, "commit", "-m", f"Squash {name}")
    _git(repo, "push", "--quiet", "origin", "main")


def _merged_then_remote_moved(repo: Path, name: str, tmp_path: Path) -> None:
    """Merge ``name`` (no-ff), then let another clone push onto it: the tracking ref is stale."""
    _git(repo, "checkout", "-q", "-b", name)
    _commit(repo, f"{name}.txt", f"{name}\n")
    _git(repo, "push", "--quiet", "origin", name)
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "--no-ff", "-q", "-m", f"Merge {name}", name)
    _git(repo, "push", "--quiet", "origin", "main")
    other = tmp_path / "other"
    _git(tmp_path, "clone", "--quiet", str(tmp_path / "remote.git"), str(other))
    _git(other, "checkout", "-q", name)
    _commit(other, "extra.txt", "unmerged work\n")
    _git(other, "push", "--quiet", "origin", name)


def _printed_deletes(repo: Path, tmp_path: Path) -> tuple[list[str], str]:
    """The delete lines of the report and of the ``--clean --dry-run`` advice, plus the text."""
    inventory = branch_inventory.build_inventory(repo, _CONFIG)
    proven = branch_cleanup.proven_remote_only(repo, _CONFIG, inventory)
    report = "\n".join(branch_sweep.render_report(inventory, _CONFIG, cap=10, remote_proven=proven))
    cleaned = branch_cleanup.clean_sweep(
        repo, _CONFIG, dry_run=True, bundle_dir=tmp_path / "b", remote=False
    )
    text = report + "\n" + "\n".join(branch_cleanup.render(cleaned))
    return _DELETE_LINE.findall(text), text


def _allowed(command: str, repo: Path) -> bool:
    hook_input = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(repo)}
    return DestructiveGitHandler().handle(hook_input).decision == "allow"


class TestPrintedRemoteDeletesPassTheGuard:
    def test_a_squash_merged_remote_only_branch_gets_a_line_the_guard_allows(
        self, repo: Path, tmp_path: Path
    ) -> None:
        _squash_merged(repo, "squashed")
        _git(repo, "branch", "-q", "-D", "squashed")
        lines, _text = _printed_deletes(repo, tmp_path)
        assert lines == ["git push origin --delete squashed"]
        assert all(_allowed(line, repo) for line in lines)

    def test_a_branch_the_proof_refuses_gets_owner_wording_not_a_runnable_line(
        self, repo: Path, tmp_path: Path
    ) -> None:
        _merged_then_remote_moved(repo, "moved", tmp_path)
        _git(repo, "fetch", "--quiet", "origin", "refs/heads/main:refs/remotes/origin/main")
        # The tracking ref still shows the merged tip; the remote has moved on.
        lines, text = _printed_deletes(repo, tmp_path)
        assert not _allowed("git push origin --delete moved", repo)
        assert lines == []
        assert "is for the owner" in text

    def test_every_printed_line_is_allowed_with_a_mix_of_branches(
        self, repo: Path, tmp_path: Path
    ) -> None:
        _squash_merged(repo, "squashed")
        _git(repo, "branch", "-q", "-D", "squashed")
        _merged_then_remote_moved(repo, "moved", tmp_path)
        lines, _text = _printed_deletes(repo, tmp_path)
        assert lines
        assert all(_allowed(line, repo) for line in lines)

    def test_the_report_alone_prints_no_remote_delete_without_a_proof(self, repo: Path) -> None:
        _squash_merged(repo, "squashed")
        _git(repo, "branch", "-q", "-D", "squashed")
        inventory = branch_inventory.build_inventory(repo, _CONFIG)
        text = "\n".join(branch_sweep.render_report(inventory, _CONFIG, cap=10))
        assert _DELETE_LINE.findall(text) == []
        assert "is for the owner" in text
