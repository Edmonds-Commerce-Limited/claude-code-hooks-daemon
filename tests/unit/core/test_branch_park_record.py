"""The park record survives a refused push, and a merge clears it visibly (Plan 00594 Task 4.3)."""

from __future__ import annotations

import stat
import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.config.models import BranchesConfig
from claude_code_hooks_daemon.core.branch_cleanup import (
    clean_sweep,
    cleanup_after_merge,
    delete_if_merged,
    render,
)
from claude_code_hooks_daemon.core.branch_park import (
    clear_park_record,
    park_branch,
    read_park_record,
)
from tests.support.git_fixtures import git_setup_timeout

_REASON = "waiting on a full-QA verdict"
_HOOK_REFUSAL = "gate: a fresh full-QA verdict is required"
_CONFIG = BranchesConfig(default="main")


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), "-c", "commit.gpgsign=false", *args],
        check=True,
        capture_output=True,
        text=True,
        timeout=git_setup_timeout(),
    ).stdout.strip()


def _refuse_pushes(repo: Path) -> None:
    hook = repo / ".git" / "hooks" / "pre-push"
    hook.write_text(f"#!/bin/sh\necho '{_HOOK_REFUSAL}' >&2\nexit 1\n", encoding="utf-8")
    hook.chmod(hook.stat().st_mode | stat.S_IXUSR)


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
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "Tess")
    _git(root, "remote", "add", "origin", str(bare))
    _git(root, "commit", "-q", "--allow-empty", "-m", "root")
    _git(root, "checkout", "-q", "-b", "work")
    (root / "f.txt").write_text("x")
    _git(root, "add", "f.txt")
    _git(root, "commit", "-q", "-m", "work")
    _git(root, "checkout", "-q", "main")
    return root


def _merge_work(repo: Path) -> None:
    _git(repo, "merge", "--no-ff", "-q", "-m", "Merge work", "work")


class TestRecordSurvivesRefusedPush:
    def test_record_holds_reason_time_owner_and_sha(self, repo: Path) -> None:
        result = park_branch(repo, "work", reason=_REASON, remote="origin")
        record = read_park_record(repo, "work")
        assert record is not None
        assert record.sha == result.sha
        assert record.reason == _REASON
        assert record.parked_by == "Tess"
        assert record.parked_at > 0

    def test_a_pre_push_gate_refusal_leaves_the_record_and_reports_git_reason(
        self, repo: Path
    ) -> None:
        _refuse_pushes(repo)
        result = park_branch(repo, "work", reason=_REASON, remote="origin")
        assert result.pushed is False
        assert result.push_error is not None and _HOOK_REFUSAL in result.push_error
        assert result.retry_command == "git push origin work"
        record = read_park_record(repo, "work")
        assert record is not None and record.reason == _REASON
        assert record.sha == _git(repo, "rev-parse", "work")

    def test_no_record_for_an_unparked_branch(self, repo: Path) -> None:
        assert read_park_record(repo, "work") is None


class TestClearing:
    def test_clear_returns_the_record_and_removes_it(self, repo: Path) -> None:
        park_branch(repo, "work", reason=_REASON, remote="origin")
        cleared = clear_park_record(repo, "work")
        assert cleared is not None and cleared.reason == _REASON
        assert read_park_record(repo, "work") is None
        assert clear_park_record(repo, "work") is None

    def test_unpark_removes_the_record(self, repo: Path) -> None:
        park_branch(repo, "work", reason=_REASON, remote="origin")
        park_branch(repo, "work", reason=None, remote="origin", clear=True)
        assert read_park_record(repo, "work") is None

    def test_cleanup_after_merge_act_says_the_park_is_cleared(self, repo: Path) -> None:
        park_branch(repo, "work", reason=_REASON, remote="origin")
        _merge_work(repo)
        report = cleanup_after_merge(repo, ["work"], config=_CONFIG, target="main", mode="act")
        assert report.park_cleared == (f"work: {_REASON}",)
        assert f"Park cleared: work ({_REASON})" in render(report)
        assert read_park_record(repo, "work") is None

    def test_cleanup_after_merge_advise_clears_it_too(self, repo: Path) -> None:
        park_branch(repo, "work", reason=_REASON, remote="origin")
        _merge_work(repo)
        report = cleanup_after_merge(repo, ["work"], config=_CONFIG, target="main", mode="advise")
        assert f"Park cleared: work ({_REASON})" in render(report)
        assert read_park_record(repo, "work") is None

    def test_an_unmerged_parked_branch_keeps_its_record(self, repo: Path) -> None:
        park_branch(repo, "work", reason=_REASON, remote="origin")
        report = cleanup_after_merge(repo, ["work"], config=_CONFIG, target="main", mode="act")
        assert report.park_cleared == ()
        assert read_park_record(repo, "work") is not None

    def test_delete_if_merged_says_the_park_is_cleared(self, repo: Path) -> None:
        park_branch(repo, "work", reason=_REASON, remote="origin")
        _merge_work(repo)
        report = delete_if_merged(repo, "work", config=_CONFIG, default="main")
        assert f"Park cleared: work ({_REASON})" in render(report)

    def test_clean_sweep_says_the_park_is_cleared(self, repo: Path, tmp_path: Path) -> None:
        park_branch(repo, "work", reason=_REASON, remote="origin")
        _merge_work(repo)
        report = clean_sweep(repo, _CONFIG, dry_run=False, bundle_dir=tmp_path / "b")
        assert f"Park cleared: work ({_REASON})" in render(report)
