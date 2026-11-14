"""A branch sharing no history with the default branch is unmerged work (GitHub #203).

``git diff target...tip`` exits non-zero when there is no merge base, which used to
leave the branch UNCLASSIFIED with a reason that blamed the sweep budget.
"""

from __future__ import annotations

import os
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
    _git(tmp_path, "checkout", "-q", "-b", "shared")
    _write_commit(tmp_path, "shared-work", 2)
    _git(tmp_path, "checkout", "-q", "main")
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
        record = build_inventory(repo, BranchesConfig()).records["shared"]
        assert record.state == BranchState.UNCLASSIFIED
        assert record.reason is not None
        assert "budget ran out" not in record.reason
        assert "git failed" in record.reason
        assert "main" in record.reason

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
        assert record.reason is not None and "budget ran out" not in record.reason
        assert "git failed" in record.reason
        assert "main" in record.reason

    def test_git_failure_reason_does_not_claim_time_is_irrelevant(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(branch_safety, "cherry_unique_shas", lambda *_a, **_k: None)
        record = build_inventory(repo, BranchesConfig()).records["shared"]
        assert record.reason is not None
        assert "larger time limit" not in record.reason
        assert "raising branches.sweep.budget_ms will not help" in record.reason


def _same_root_patch_orphan(repo: Path) -> None:
    """main: a, then b. orphan: one root commit adding exactly main's root patch."""
    _git(repo, "init", "-q", "-b", "main")
    (repo / "a").write_text("a\n")
    _git(repo, "add", "a")
    _git(repo, "commit", "-q", "-m", "root")
    _write_commit(repo, "b", 1)
    _git(repo, "checkout", "-q", "--orphan", "orphan")
    _git(repo, "rm", "-q", "-rf", "--cached", ".")
    (repo / "b").unlink()
    _git(repo, "add", "a")
    _git(repo, "commit", "-q", "-m", "a different message")
    _git(repo, "checkout", "-q", "main")


class TestNoMergeBaseNeverPatchEquivalent:
    def test_orphan_with_matching_root_patch_is_live(self, tmp_path: Path) -> None:
        _same_root_patch_orphan(tmp_path)
        record = build_inventory(tmp_path, BranchesConfig()).records["orphan"]
        assert record.state == BranchState.LIVE, record.reason
        assert record.ahead == 1

    def test_orphan_with_matching_root_patch_against_an_integration_line(
        self, tmp_path: Path
    ) -> None:
        _same_root_patch_orphan(tmp_path)
        _git(tmp_path, "branch", "release/1", "main")
        facts = branch_inventory._pair_facts(tmp_path, "orphan", "release/1", want_lines=False)
        assert isinstance(facts, branch_inventory._PairFacts)
        assert (facts.ahead, facts.unique, facts.lines) == (1, 1, None)

    def test_metadata_only_rewrite_strands_a_live_branch(self, tmp_path: Path) -> None:
        _git(tmp_path, "init", "-q", "-b", "main")
        for n in range(3):
            _write_commit(tmp_path, f"f{n}", 1)
        _git(tmp_path, "checkout", "-q", "-b", "old-feature")
        _write_commit(tmp_path, "feat", 1)
        _git(tmp_path, "checkout", "-q", "main")
        _git(tmp_path, "merge", "-q", "--ff-only", "old-feature")
        _git(tmp_path, "branch", "release/1", "main")
        env = {**os.environ, "FILTER_BRANCH_SQUELCH_WARNING": "1"}
        for target in ("main", "release/1"):
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(tmp_path),
                    "filter-branch",
                    "-f",
                    "--env-filter",
                    "GIT_AUTHOR_EMAIL=new@e.com; GIT_COMMITTER_EMAIL=new@e.com",
                    target,
                ],
                check=True,
                capture_output=True,
                env=env,
            )
        record = build_inventory(tmp_path, BranchesConfig()).records["old-feature"]
        assert record.state == BranchState.LIVE, record.reason
        assert record.ahead == 4
        facts = branch_inventory._pair_facts(tmp_path, "old-feature", "release/1", want_lines=False)
        assert isinstance(facts, branch_inventory._PairFacts)
        assert facts.unique == facts.ahead == 4


class TestShallowClone:
    def test_missing_fork_point_is_unclassified_not_orphan(self, tmp_path: Path) -> None:
        origin = tmp_path / "origin"
        origin.mkdir()
        _git(origin, "init", "-q", "-b", "main")
        _write_commit(origin, "c1", 1)
        _git(origin, "checkout", "-q", "-b", "feature")
        _write_commit(origin, "c3", 1)
        _git(origin, "checkout", "-q", "main")
        _write_commit(origin, "c2", 1)
        clone = tmp_path / "clone"
        subprocess.run(
            [
                "git",
                "clone",
                "-q",
                "--depth",
                "1",
                "--no-single-branch",
                origin.as_uri(),
                str(clone),
            ],
            check=True,
            capture_output=True,
        )
        _git(clone, "branch", "feature", "origin/feature")
        record = build_inventory(clone, BranchesConfig()).records["feature"]
        assert record.state == BranchState.UNCLASSIFIED
        assert record.reason is not None
        assert "history not fetched" in record.reason
        assert "main" in record.reason
