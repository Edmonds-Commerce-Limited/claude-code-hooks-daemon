"""Tests for ``branch-park`` (Plan 00558 Task 4.3, DESIGN section 5)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.config.models import BranchesConfig
from claude_code_hooks_daemon.core.branch_creation import (
    clear_label_stage,
    read_labels,
    write_labels,
)
from claude_code_hooks_daemon.core.branch_inventory import BranchState, build_inventory
from claude_code_hooks_daemon.core.branch_park import (
    BranchParkError,
    BranchParkSameReason,
    park_branch,
)
from tests.conftest import HERMETIC_GIT_EMAIL
from tests.support.git_fixtures import git_setup_timeout


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        timeout=git_setup_timeout(),
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    bare = tmp_path / "origin.git"
    subprocess.run(
        ["git", "init", "-q", "--bare", "-b", "main", str(bare)],
        check=True,
        timeout=git_setup_timeout(),
    )
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", HERMETIC_GIT_EMAIL)
    _git(root, "config", "user.name", "Tess")
    _git(root, "remote", "add", "origin", str(bare))
    _git(root, "commit", "-q", "--allow-empty", "-m", "root")
    _git(root, "push", "-q", "origin", "main")
    _git(root, "checkout", "-q", "-b", "work")
    (root / "f.txt").write_text("x")
    _git(root, "add", "f.txt")
    _git(root, "commit", "-q", "-m", "work")
    _git(root, "push", "-q", "-u", "origin", "work")
    _git(root, "checkout", "-q", "main")
    return root


def _config() -> BranchesConfig:
    return BranchesConfig(default="main")


class TestPark:
    def test_park_writes_trailer_commit_and_pushes(self, repo: Path) -> None:
        old = _git(repo, "rev-parse", "work")
        result = park_branch(repo, "work", reason="waiting on review", remote="origin")
        new = _git(repo, "rev-parse", "work")
        assert new != old and result.sha == new
        assert _git(repo, "rev-parse", f"{new}^") == old
        assert _git(repo, "rev-parse", f"{new}^{{tree}}") == _git(
            repo, "rev-parse", f"{old}^{{tree}}"
        )
        message = _git(repo, "log", "-1", "--format=%B", "work")
        assert "Parked-Reason: waiting on review" in message
        assert "Parked-By: Tess" in message
        assert result.pushed is True
        assert _git(repo, "rev-parse", "origin/work") == new

    def test_inventory_reports_parked_with_reason(self, repo: Path) -> None:
        park_branch(repo, "work", reason="waiting on review", remote="origin")
        record = build_inventory(repo, _config()).records["work"]
        assert record.state == BranchState.PARKED
        assert record.parked_reason == "waiting on review"

    def test_clear_writes_unparked_trailer_and_resumes(self, repo: Path) -> None:
        park_branch(repo, "work", reason="waiting", remote="origin")
        park_branch(repo, "work", reason=None, remote="origin", clear=True)
        assert "Unparked:" in _git(repo, "log", "-1", "--format=%B", "work")
        record = build_inventory(repo, _config()).records["work"]
        assert record.state != BranchState.PARKED

    def test_push_failure_keeps_local_park_and_gives_retry_command(self, repo: Path) -> None:
        _git(repo, "remote", "set-url", "origin", str(repo / "missing.git"))
        result = park_branch(repo, "work", reason="r", remote="origin")
        assert result.pushed is False
        assert result.retry_command == "git push origin work"
        assert "Parked-Reason: r" in _git(repo, "log", "-1", "--format=%B", "work")

    def test_unknown_branch_fails(self, repo: Path) -> None:
        with pytest.raises(BranchParkError, match="nope"):
            park_branch(repo, "nope", reason="r", remote="origin")

    def test_remote_only_branch_is_parked_without_a_local_branch(self, repo: Path) -> None:
        old = _git(repo, "rev-parse", "origin/work")
        _git(repo, "branch", "-D", "work")
        result = park_branch(repo, "work", reason="remote only", remote="origin")
        assert result.pushed is True and result.sha != old
        assert _git(repo, "rev-parse", f"{result.sha}^") == old
        assert _git(repo, "rev-parse", "origin/work") == result.sha
        local = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--verify", "--quiet", "refs/heads/work"],
            capture_output=True,
            text=True,
            timeout=git_setup_timeout(),
        )
        assert local.returncode != 0
        bare = repo.parent / "origin.git"
        assert _git(bare, "rev-parse", "refs/heads/work") == result.sha
        assert "Parked-Reason: remote only" in _git(repo, "log", "-1", "--format=%B", "origin/work")

    def test_remote_only_park_is_seen_as_parked_by_the_inventory(self, repo: Path) -> None:
        _git(repo, "branch", "-D", "work")
        park_branch(repo, "work", reason="remote only", remote="origin")
        record = build_inventory(repo, _config()).records["work"]
        assert record.state == BranchState.PARKED
        assert record.parked_reason == "remote only"

    def test_remote_only_push_failure_keeps_the_park_locally(self, repo: Path) -> None:
        old = _git(repo, "rev-parse", "origin/work")
        _git(repo, "branch", "-D", "work")
        _git(repo, "remote", "set-url", "origin", str(repo / "missing.git"))
        result = park_branch(repo, "work", reason="r", remote="origin")
        assert result.pushed is False and result.retry_command == "git push origin work"
        assert _git(repo, "rev-parse", "origin/work") == old
        assert _git(repo, "rev-parse", "refs/heads/work") == result.sha

    def test_remote_only_clear_unparks(self, repo: Path) -> None:
        _git(repo, "branch", "-D", "work")
        park_branch(repo, "work", reason="r", remote="origin")
        park_branch(repo, "work", reason=None, remote="origin", clear=True)
        assert "Unparked:" in _git(repo, "log", "-1", "--format=%B", "origin/work")

    def test_a_same_reason_repark_is_refused_and_changes_nothing(self, repo: Path) -> None:
        park_branch(repo, "work", reason="waiting", remote="origin")
        parked = _git(repo, "rev-parse", "work")
        with pytest.raises(BranchParkSameReason, match="new reason"):
            park_branch(repo, "work", reason="waiting", remote="origin")
        assert _git(repo, "rev-parse", "work") == parked

    def test_a_new_reason_repark_is_accepted(self, repo: Path) -> None:
        park_branch(repo, "work", reason="waiting", remote="origin")
        park_branch(repo, "work", reason="still waiting on legal", remote="origin")
        assert "Parked-Reason: still waiting on legal" in _git(
            repo, "log", "-1", "--format=%B", "work"
        )

    def test_the_same_reason_is_fine_after_an_unpark(self, repo: Path) -> None:
        park_branch(repo, "work", reason="waiting", remote="origin")
        park_branch(repo, "work", reason=None, remote="origin", clear=True)
        park_branch(repo, "work", reason="waiting", remote="origin")

    def test_a_same_reason_remote_only_repark_is_refused(self, repo: Path) -> None:
        _git(repo, "branch", "-D", "work")
        park_branch(repo, "work", reason="waiting", remote="origin")
        with pytest.raises(BranchParkSameReason):
            park_branch(repo, "work", reason="waiting", remote="origin")

    @pytest.mark.parametrize("reason", ["", "  ", "two\nlines", None])
    def test_bad_reason_fails_before_any_change(self, repo: Path, reason: str | None) -> None:
        old = _git(repo, "rev-parse", "work")
        with pytest.raises(BranchParkError, match="reason"):
            park_branch(repo, "work", reason=reason, remote="origin")
        assert _git(repo, "rev-parse", "work") == old


def test_clear_label_stage_removes_the_stage(tmp_path: Path) -> None:
    path = tmp_path / "labels.json"
    write_labels(path, [{"name": "a", "group": "dormant", "dormancy_stage": "block"}])
    clear_label_stage(path, "a")
    assert read_labels(path)["a"]["stage"] is None
    assert read_labels(path)["a"]["group"] == "parked"


def test_clear_label_stage_without_snapshot_is_a_noop(tmp_path: Path) -> None:
    clear_label_stage(tmp_path / "none.json", "a")
    assert not (tmp_path / "none.json").exists()
