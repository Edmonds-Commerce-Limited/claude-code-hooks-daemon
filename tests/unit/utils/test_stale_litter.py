"""Report-only detection of changed-green refs of gone branches.

Plan 00470 Task 4.1 follow-ups. Nothing under test deletes anything: each finding
carries a command a human may choose to run.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.utils.stale_checkouts import ScanDeadline
from claude_code_hooks_daemon.utils.stale_litter import (
    CHANGED_GREEN_PREFIX,
    MAX_LISTED_REFS,
    collect_gone_branch_ref_report,
)


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
        assert f"printf 'delete %s\\n' {ref} | git update-ref --stdin" in report
        assert "never runs" in report

    def test_reporting_deletes_nothing(self, repo: Path) -> None:
        ref = _record(repo, "deleted-branch")
        _record(repo, "main")

        report = collect_gone_branch_ref_report(repo)

        assert report is not None
        assert _git(repo, "for-each-ref", "--format=%(refname)", ref) == ref
        assert f"{CHANGED_GREEN_PREFIX}main" not in report

    def test_a_long_list_is_capped_and_one_command_covers_every_ref(self, repo: Path) -> None:
        refs = [_record(repo, f"gone-{index:02d}") for index in range(MAX_LISTED_REFS + 3)]

        report = collect_gone_branch_ref_report(repo)

        assert report is not None
        assert "and 3 more" in report
        assert f"{len(refs)} changed-green refs" in report
        listed = [line for line in report.splitlines() if line.startswith("  - ")]
        assert len(listed) == MAX_LISTED_REFS
        commands = [line for line in report.splitlines() if "git update-ref" in line]
        assert len(commands) == 1
        assert all(ref in commands[0] for ref in refs)

    def test_the_batched_command_deletes_exactly_the_reported_refs(self, repo: Path) -> None:
        _git(repo, "branch", "alive")
        alive = _record(repo, "alive")
        _record(repo, "gone/1")
        _record(repo, "gone-2")

        report = collect_gone_branch_ref_report(repo)

        assert report is not None
        command = next(line for line in report.splitlines() if "git update-ref" in line).strip()
        subprocess.run(["bash", "-c", command], cwd=repo, check=True)
        left = _git(repo, "for-each-ref", "--format=%(refname)", CHANGED_GREEN_PREFIX)
        assert left == alive

    def test_a_remote_name_containing_a_slash_is_split_on_the_remote(self, repo: Path) -> None:
        _git(repo, "remote", "add", "team/fork", "https://example.invalid/x.git")
        _git(repo, "update-ref", "refs/remotes/team/fork/feature", "HEAD")
        _record(repo, "feature")

        assert collect_gone_branch_ref_report(repo) is None

    def test_a_remote_branch_with_a_slash_is_kept_and_its_tail_is_not(self, repo: Path) -> None:
        _git(repo, "remote", "add", "origin", "https://example.invalid/x.git")
        _git(repo, "update-ref", "refs/remotes/origin/user/topic", "HEAD")
        _record(repo, "user/topic")
        gone = _record(repo, "topic")

        report = collect_gone_branch_ref_report(repo)

        assert report is not None
        assert gone in report
        assert f"{CHANGED_GREEN_PREFIX}user/topic" not in report

    def test_a_spent_shared_budget_makes_the_ref_scan_incomplete(self, repo: Path) -> None:
        _record(repo, "gone")
        deadline = ScanDeadline(0.0)

        report = collect_gone_branch_ref_report(repo, deadline=deadline)

        assert report is not None
        assert "SCAN INCOMPLETE" in report
        assert deadline.exhausted

    def test_a_same_named_tag_does_not_keep_the_ref(self, repo: Path) -> None:
        _git(repo, "tag", "ghost")
        ref = _record(repo, "ghost")

        report = collect_gone_branch_ref_report(repo)

        assert report is not None
        assert ref in report
