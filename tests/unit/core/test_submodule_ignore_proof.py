"""A submodule pointer change is content every "nothing is lost" proof must see.

Git drops a gitlink's row from ``git diff`` and ``git status`` when the tracked
``.gitmodules`` says ``submodule.<name>.ignore = all`` or any git config level sets
``diff.ignoreSubmodules = all``; ``git cherry``'s patch-ids drop it too, and that has
no flag. A branch that bumps a submodule pointer and adds one file the default already
holds then looked proven (``patch-equivalent``, ``content-preserved`` or
``surviving-content``) and its delete lost the pointer change. Real repositories; the
gitlink is written with ``update-index --cacheinfo`` so no second repository is needed.

Every test pins git's config: ``GIT_CONFIG_NOSYSTEM`` and a temp ``GIT_CONFIG_GLOBAL``,
so a developer's own ``diff.ignoreSubmodules`` can neither pass nor fail them.
"""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.config.models import BranchesConfig
from claude_code_hooks_daemon.constants import Timeout
from claude_code_hooks_daemon.core import remote_branch_proof
from claude_code_hooks_daemon.core.branch_cleanup import worktree_blocker_groups
from claude_code_hooks_daemon.core.branch_inventory import build_inventory
from claude_code_hooks_daemon.core.branch_records import TOUCHED_KEY
from claude_code_hooks_daemon.core.branch_stop_guard import StopCheck, judge_stop
from claude_code_hooks_daemon.core.remote_branch_proof import (
    ProofUnavailableError,
    _net_change,
    gitlink_change_held,
    holds_net_change,
    prove_remote_merged,
)
from claude_code_hooks_daemon.core.worktree_reaping import collect_worktree_states, is_reapable
from claude_code_hooks_daemon.daemon.branch_safety import (
    TIER_PATCH_EQUIVALENT,
    _gitlinks_held,
    classify_branch,
)
from tests.support.git_fixtures import git_setup_timeout

_OLD_POINTER = "1" * 40
_NEW_POINTER = "2" * 40
_GITLINK = "160000"
_IGNORE_ALL_GITMODULES = '[submodule "sub"]\n\tpath = sub\n\turl = ./sub.git\n\tignore = all\n'
_PLAIN_GITMODULES = '[submodule "sub"]\n\tpath = sub\n\turl = ./sub.git\n'
_IGNORE_ALL_CONFIG = "[diff]\n\tignoreSubmodules = all\n"


@pytest.fixture(autouse=True)
def _isolated_git_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """No system config, and an empty global config each test may fill."""
    global_config = tmp_path / "gitconfig"
    global_config.write_text("", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(global_config))
    monkeypatch.setenv("GIT_AUTHOR_NAME", "Test Author")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "test@example.com")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "Test Author")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "test@example.com")
    return global_config


def _ignore_all_globally(tmp_path: Path) -> None:
    """Set ``diff.ignoreSubmodules = all`` in the (isolated) global config."""
    (tmp_path / "gitconfig").write_text(_IGNORE_ALL_CONFIG, encoding="utf-8")


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        env=dict(os.environ),
    ).stdout


def _write(repo: Path, name: str, content: str) -> None:
    (repo / name).write_text(content, encoding="utf-8")
    _git(repo, "add", name)


def _point_sub_at(repo: Path, sha: str) -> None:
    _git(repo, "update-index", "--add", "--cacheinfo", f"{_GITLINK},{sha},sub")


def _repo(tmp_path: Path, gitmodules: str) -> Path:
    """``main`` with ``.gitmodules`` and a gitlink ``sub`` at the old pointer, pushed."""
    bare = tmp_path / "remote.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(bare))
    path = tmp_path / "repo"
    path.mkdir()
    _git(path, "init", "-q", "-b", "main")
    _write(path, ".gitmodules", gitmodules)
    _write(path, "base.txt", "base\n")
    _point_sub_at(path, _OLD_POINTER)
    _git(path, "commit", "-q", "-m", "base")
    _git(path, "remote", "add", "origin", str(bare))
    _git(path, "push", "-q", "origin", "main")
    _git(path, "remote", "set-head", "origin", "main")
    return path


def _bump_and_add_held_file(repo: Path) -> None:
    """``feat``: bump ``sub`` and add ``f.txt``; ``main`` then lands ``f.txt`` alone."""
    _git(repo, "checkout", "-q", "-b", "feat", "main")
    _write(repo, "f.txt", "f\n")
    _point_sub_at(repo, _NEW_POINTER)
    _git(repo, "commit", "-q", "-m", "f and bump")
    _git(repo, "push", "-q", "origin", "feat")
    _git(repo, "checkout", "-q", "main")
    _write(repo, "f.txt", "f\n")
    _git(repo, "commit", "-q", "-m", "f only")
    _git(repo, "push", "-q", "origin", "main")


@pytest.fixture(params=["gitmodules", "global-config"])
def ignoring_repo(request: pytest.FixtureRequest, tmp_path: Path) -> Path:
    """The bump-plus-held-file shape under each way git can be told to ignore ``sub``."""
    if request.param == "gitmodules":
        repo = _repo(tmp_path, _IGNORE_ALL_GITMODULES)
    else:
        repo = _repo(tmp_path, _PLAIN_GITMODULES)
        _ignore_all_globally(tmp_path)
    _bump_and_add_held_file(repo)
    return repo


class TestNetChange:
    def test_the_gitlink_row_is_returned(self, ignoring_repo: Path) -> None:
        base = _git(ignoring_repo, "merge-base", "main", "feat").strip()
        changes = _net_change(ignoring_repo, base, "feat", timeout=git_setup_timeout())
        by_path = {change.path: change for change in changes}
        assert set(by_path) == {"f.txt", "sub"}
        assert (by_path["sub"].mode, by_path["sub"].blob) == (_GITLINK, _NEW_POINTER)

    def test_the_default_holding_only_the_file_does_not_hold_the_net_change(
        self, ignoring_repo: Path
    ) -> None:
        assert holds_net_change(ignoring_repo, "main", "feat") is False

    def test_the_flag_wins_over_config_and_gitmodules_together(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path, _IGNORE_ALL_GITMODULES)
        _ignore_all_globally(tmp_path)
        _bump_and_add_held_file(repo)
        base = _git(repo, "merge-base", "main", "feat").strip()
        changes = _net_change(repo, base, "feat", timeout=git_setup_timeout())
        assert "sub" in {c.path for c in changes}


class TestRemoteDelete:
    def test_a_pointer_bump_is_not_proven_deletable(self, ignoring_repo: Path) -> None:
        proof = prove_remote_merged(
            ignoring_repo, "origin", ["feat"], "main", BranchesConfig(default="main")
        )
        assert proof.tips == {}
        assert proof.evidence == {}
        assert "`sub`" in proof.problems["feat"]

    def test_the_pointer_held_on_the_default_is_still_proven(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path, _IGNORE_ALL_GITMODULES)
        _bump_and_add_held_file(repo)
        _point_sub_at(repo, _NEW_POINTER)
        _git(repo, "commit", "-q", "-m", "main bumps sub too")
        _git(repo, "push", "-q", "origin", "main")
        proof = prove_remote_merged(
            repo, "origin", ["feat"], "main", BranchesConfig(default="main")
        )
        assert list(proof.tips) == ["feat"]


class TestLocalDelete:
    def test_a_pointer_bump_is_not_classified_safe(self, ignoring_repo: Path) -> None:
        classification = classify_branch(ignoring_repo, "feat", protected_ref="main")
        assert classification.tier != TIER_PATCH_EQUIVALENT
        assert classification.is_safe is False

    def test_a_branch_without_a_gitlink_change_stays_patch_equivalent(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path, _IGNORE_ALL_GITMODULES)
        _git(repo, "checkout", "-q", "-b", "feat", "main")
        _write(repo, "f.txt", "f\n")
        _git(repo, "commit", "-q", "-m", "f")
        _git(repo, "checkout", "-q", "main")
        _write(repo, "other.txt", "other\n")
        _git(repo, "commit", "-q", "-m", "main moves on")
        _git(repo, "cherry-pick", "feat")
        assert classify_branch(repo, "feat", protected_ref="main").tier == TIER_PATCH_EQUIVALENT


class TestGitlinkGateFailsClosed:
    def test_no_merge_base_is_not_held(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path, _IGNORE_ALL_GITMODULES)
        _git(repo, "checkout", "-q", "--orphan", "lone")
        _git(repo, "commit", "-q", "-m", "lone")
        assert gitlink_change_held(repo, "main", "lone") is False

    def test_an_unknown_ref_is_unavailable(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path, _IGNORE_ALL_GITMODULES)
        with pytest.raises(ProofUnavailableError):
            gitlink_change_held(repo, "main", "refs/heads/no-such-branch")

    def test_an_unavailable_proof_is_not_held(
        self, ignoring_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def unavailable(*_args: object, **_kwargs: object) -> bool:
            raise ProofUnavailableError("git failed")

        monkeypatch.setattr(remote_branch_proof, "gitlink_change_held", unavailable)
        assert _gitlinks_held(ignoring_repo, "main", "refs/heads/feat") is False

    def test_an_unavailable_proof_is_logged_as_a_refusal(
        self,
        ignoring_repo: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        def unavailable(*_args: object, **_kwargs: object) -> bool:
            raise ProofUnavailableError("git failed")

        monkeypatch.setattr(remote_branch_proof, "gitlink_change_held", unavailable)
        with caplog.at_level(logging.INFO, logger="claude_code_hooks_daemon.daemon.branch_safety"):
            _gitlinks_held(ignoring_repo, "main", "refs/heads/feat")
        messages = [record.getMessage() for record in caplog.records]
        assert any("stays refused" in m and "git failed" in m for m in messages), messages

    def test_no_repository_is_not_held(self, tmp_path: Path) -> None:
        outside = tmp_path / "not-a-repo"
        outside.mkdir()
        assert _gitlinks_held(outside, "main", "refs/heads/feat") is False


def _worktree_with_moved_submodule(
    tmp_path: Path, gitmodules: str, relative: str | None = None
) -> Path:
    """A worktree whose populated ``sub`` is checked out at a commit the index does not record.

    ``relative`` places it inside the repository (an agent worktree path) instead of beside it.
    """
    repo = _repo(tmp_path, gitmodules)
    _git(repo, "branch", "work", "main")
    worktree = tmp_path / "wt" if relative is None else repo / relative
    _git(repo, "worktree", "add", "-q", str(worktree), "work")
    sub = worktree / "sub"
    sub.mkdir(exist_ok=True)
    _git(sub, "init", "-q", "-b", "main")
    _write(sub, "inner.txt", "unpushed submodule work\n")
    _git(sub, "commit", "-q", "-m", "inner")
    return worktree


class TestWorktreeRemoval:
    def test_a_moved_submodule_blocks_removal_under_gitmodules_ignore(self, tmp_path: Path) -> None:
        worktree = _worktree_with_moved_submodule(tmp_path, _IGNORE_ALL_GITMODULES)
        dirty, _ignored = worktree_blocker_groups(worktree, ())
        assert "sub" in dirty

    def test_a_moved_submodule_blocks_removal_under_global_ignore(self, tmp_path: Path) -> None:
        worktree = _worktree_with_moved_submodule(tmp_path, _PLAIN_GITMODULES)
        _ignore_all_globally(tmp_path)
        dirty, _ignored = worktree_blocker_groups(worktree, ())
        assert "sub" in dirty

    def test_a_moved_submodule_keeps_an_agent_worktree_from_being_reaped(
        self, tmp_path: Path
    ) -> None:
        _worktree_with_moved_submodule(
            tmp_path, _IGNORE_ALL_GITMODULES, ".claude/worktrees/agent-abc123"
        )
        (state,) = collect_worktree_states(tmp_path / "repo", "main")
        assert "sub" in state.uncommitted_paths
        assert is_reapable(state) is False


class TestStopGuard:
    def test_a_moved_submodule_is_a_dirty_worktree(self, tmp_path: Path) -> None:
        _worktree_with_moved_submodule(tmp_path, _IGNORE_ALL_GITMODULES)
        repo = tmp_path / "repo"
        (repo / ".git" / "info" / "exclude").write_text("untracked/\n", encoding="utf-8")
        _git(repo, "config", "--add", f"branch.work.{TOUCHED_KEY}", "sess-1:")
        config = BranchesConfig(default="main")
        judgement = judge_stop(
            repo,
            build_inventory(repo, config),
            config,
            session_id="sess-1",
            agent_id=None,
            handoff=False,
            budget=Timeout.GIT_STOP_GUARD_BUDGET,
        )
        assert ("work", StopCheck.DIRTY) in {(f.branch, f.check) for f in judgement.findings}
