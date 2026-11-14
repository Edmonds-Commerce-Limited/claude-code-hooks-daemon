"""A branch sharing no history with the default branch is unmerged work (GitHub #203).

``git diff target...tip`` exits non-zero when there is no merge base, which used to
leave the branch UNCLASSIFIED with a reason that blamed the sweep budget.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.config.models import BranchesConfig
from claude_code_hooks_daemon.core import branch_inventory
from claude_code_hooks_daemon.core.branch_inventory import BranchState, build_inventory
from claude_code_hooks_daemon.daemon import branch_safety
from claude_code_hooks_daemon.utils.git_repo import run_git
from tests.support.git_fixtures import git_setup_timeout


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@example.com",
            "-c",
            "commit.gpgsign=false",
            *args,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _write_commit(repo: Path, name: str, lines: int) -> None:
    (repo / name).write_text("".join(f"{name} {n}\n" for n in range(lines)))
    _git(repo, "add", name)
    _git(repo, "commit", "-q", "-m", name)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q", "-b", "main")
    _write_commit(tmp_path, "base", 1)
    _git(tmp_path, "checkout", "-q", "--orphan", "orphan")
    _git(tmp_path, "rm", "-q", "-rf", ".")
    _write_commit(tmp_path, "unrelated", 4)
    _git(tmp_path, "checkout", "-q", "main")
    return tmp_path


class TestNoMergeBase:
    def test_orphan_branch_is_unmerged_work(self, repo: Path) -> None:
        record = build_inventory(repo, BranchesConfig()).records["orphan"]
        assert record.state != BranchState.UNCLASSIFIED, record.reason
        assert record.state == BranchState.LIVE
        assert record.ahead == 1

    def test_orphan_lines_are_the_whole_tip(self, repo: Path) -> None:
        record = build_inventory(repo, BranchesConfig()).records["orphan"]
        assert record.lines == 4

    def test_orphan_is_never_contained_or_equivalent(self, repo: Path) -> None:
        record = build_inventory(repo, BranchesConfig()).records["orphan"]
        assert record.state not in {
            BranchState.MERGED_DEFAULT,
            BranchState.MERGED_LINE,
            BranchState.PATCH_EQUIVALENT,
        }

    def test_lines_helper_handles_no_merge_base(self, repo: Path) -> None:
        assert branch_inventory._lines(repo, "main", "orphan") == 4

    def test_lines_helper_still_fails_on_a_bad_ref(self, repo: Path) -> None:
        assert branch_inventory._lines(repo, "main", "no-such") is None


class TestUnmeasuredReason:
    def test_budget_reason(self, repo: Path) -> None:
        config = BranchesConfig.model_validate({"sweep": {"budget_ms": 0}})
        record = build_inventory(repo, config).records["orphan"]
        assert record.state == BranchState.UNCLASSIFIED
        assert record.reason == branch_inventory.BUDGET_REASON
        assert "budget" in (record.reason or "")

    def test_git_failure_reason_does_not_blame_the_budget(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(branch_safety, "cherry_unique_shas", lambda *_a, **_k: None)
        record = build_inventory(repo, BranchesConfig()).records["orphan"]
        assert record.state == BranchState.UNCLASSIFIED
        assert record.reason is not None
        assert "budget" not in record.reason
        assert "git failed" in record.reason

    def test_failing_diff_is_a_git_failure_not_a_measured_branch(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        real = run_git

        def failing_diff(
            cwd: Path, *args: str, timeout: float = git_setup_timeout()
        ) -> subprocess.CompletedProcess[str]:
            if args and args[0] == "diff":
                return subprocess.CompletedProcess(list(args), 128, "", "boom")
            return real(cwd, *args, timeout=timeout)

        monkeypatch.setattr(branch_inventory, "run_git", failing_diff)
        record = build_inventory(repo, BranchesConfig()).records["orphan"]
        assert record.state == BranchState.UNCLASSIFIED
        assert record.reason is not None and "budget" not in record.reason
