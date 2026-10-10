"""Report-only detection of old scratch files and changed-green refs of gone branches.

Plan 00470 Task 4.1 follow-ups. Nothing under test deletes anything: each finding
carries a command a human may choose to run.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.utils.stale_litter import (
    CHANGED_GREEN_PREFIX,
    collect_gone_branch_ref_report,
    collect_scratch_report,
)

_DAY = 86400.0
_NOW = 1_000_000_000.0


def _age(path: Path, days: float) -> None:
    stamp = _NOW - days * _DAY
    os.utime(path, (stamp, stamp))


def _write(path: Path, size: int, days: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    _age(path, days)


class TestScratchReport:
    def test_missing_directory_is_quiet(self, tmp_path: Path) -> None:
        assert collect_scratch_report(tmp_path / "nope", 14, now=_NOW) is None

    def test_nothing_old_is_quiet(self, tmp_path: Path) -> None:
        _write(tmp_path / "a.txt", 10, 1)
        assert collect_scratch_report(tmp_path, 14, now=_NOW) is None

    def test_reports_count_size_and_oldest_age(self, tmp_path: Path) -> None:
        _write(tmp_path / "a.txt", 100, 20)
        _write(tmp_path / "deep" / "b.txt", 50, 40)
        _write(tmp_path / "new.txt", 999, 1)

        report = collect_scratch_report(tmp_path, 14, now=_NOW)

        assert report is not None
        assert "2 files" in report
        assert "150 B" in report
        assert "oldest 40 days" in report
        assert "never runs" in report

    def test_suggested_command_is_offered_not_run(self, tmp_path: Path) -> None:
        old = tmp_path / "a.txt"
        _write(old, 1, 30)

        report = collect_scratch_report(tmp_path, 14, now=_NOW)

        assert report is not None
        assert f"find {tmp_path} -type f -mmin +{14 * 1440} -delete" in report
        assert old.exists()

    def test_path_with_a_space_is_quoted(self, tmp_path: Path) -> None:
        scratch = tmp_path / "my scratch"
        _write(scratch / "a.txt", 1, 30)

        report = collect_scratch_report(scratch, 14, now=_NOW)

        assert report is not None
        assert f"'{scratch}'" in report

    def test_symlinks_are_not_followed(self, tmp_path: Path) -> None:
        outside = tmp_path / "outside"
        _write(outside / "big.txt", 500, 90)
        scratch = tmp_path / "scratch"
        scratch.mkdir()
        (scratch / "link").symlink_to(outside, target_is_directory=True)

        assert collect_scratch_report(scratch, 14, now=_NOW) is None

    def test_entry_limit_stops_the_scan_and_says_so(self, tmp_path: Path) -> None:
        for index in range(10):
            _write(tmp_path / f"f{index}.txt", 1, 30)

        report = collect_scratch_report(tmp_path, 14, now=_NOW, max_entries=3)

        assert report is not None
        assert "SCAN INCOMPLETE" in report
        assert "10 files" not in report

    def test_time_budget_stops_the_scan_and_says_so(self, tmp_path: Path) -> None:
        for index in range(5):
            _write(tmp_path / f"f{index}.txt", 1, 30)
        ticks = iter(range(0, 1000))

        report = collect_scratch_report(
            tmp_path, 14, now=_NOW, budget_seconds=2.0, clock=lambda: float(next(ticks))
        )

        assert report is not None
        assert "SCAN INCOMPLETE" in report

    def test_incomplete_scan_with_nothing_found_is_not_quiet(self, tmp_path: Path) -> None:
        for index in range(5):
            _write(tmp_path / f"f{index}.txt", 1, 1)

        report = collect_scratch_report(tmp_path, 14, now=_NOW, max_entries=2)

        assert report is not None
        assert "SCAN INCOMPLETE" in report


def _git(repo: Path, *args: str) -> str:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.invalid",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.invalid",
    }
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        timeout=Timeout.QA_TEST_TIMEOUT,
        check=True,
        env=env,
    )
    return result.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "f.txt").write_text("x", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "base")
    return tmp_path


def _record(repo: Path, branch: str) -> str:
    ref = f"{CHANGED_GREEN_PREFIX}{branch}"
    _git(repo, "update-ref", ref, _git(repo, "rev-parse", "HEAD"))
    return ref


class TestGoneBranchRefReport:
    def test_not_a_repository_is_quiet(self, tmp_path: Path) -> None:
        assert collect_gone_branch_ref_report(tmp_path / "missing") is None

    def test_no_refs_is_quiet(self, repo: Path) -> None:
        assert collect_gone_branch_ref_report(repo) is None

    def test_ref_of_a_live_local_branch_is_kept(self, repo: Path) -> None:
        _git(repo, "branch", "feature")
        _record(repo, "feature")

        assert collect_gone_branch_ref_report(repo) is None

    def test_ref_of_a_branch_with_a_slash_in_its_name_is_kept(self, repo: Path) -> None:
        _git(repo, "branch", "worktree/feature")
        _record(repo, "worktree/feature")

        assert collect_gone_branch_ref_report(repo) is None

    def test_ref_of_a_branch_only_a_remote_still_holds_is_kept(self, repo: Path) -> None:
        _git(repo, "update-ref", "refs/remotes/origin/remote-only", "HEAD")
        _record(repo, "remote-only")

        assert collect_gone_branch_ref_report(repo) is None

    def test_ref_of_a_gone_branch_is_reported_with_its_command(self, repo: Path) -> None:
        ref = _record(repo, "deleted-branch")

        report = collect_gone_branch_ref_report(repo)

        assert report is not None
        assert ref in report
        assert f"git update-ref -d {ref}" in report
        assert "never runs" in report

    def test_reporting_deletes_nothing(self, repo: Path) -> None:
        ref = _record(repo, "deleted-branch")
        _record(repo, "main")

        report = collect_gone_branch_ref_report(repo)

        assert report is not None
        assert _git(repo, "for-each-ref", "--format=%(refname)", ref) == ref
        assert f"update-ref -d {CHANGED_GREEN_PREFIX}main" not in report

    def test_a_same_named_tag_does_not_keep_the_ref(self, repo: Path) -> None:
        _git(repo, "tag", "ghost")
        ref = _record(repo, "ghost")

        report = collect_gone_branch_ref_report(repo)

        assert report is not None
        assert ref in report
