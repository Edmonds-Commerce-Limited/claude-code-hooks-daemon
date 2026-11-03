"""The branch inventory (Plan 00558 Task 2.1, DESIGN.md sections 2, 4 and 5).

Built on a real fixture: a bare "remote" and a clone holding one branch per
state of DESIGN.md section 2. Commit dates are pinned with
``GIT_COMMITTER_DATE`` against a fixed ``NOW`` so ages and dormancy stages are
exact.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pytest

from claude_code_hooks_daemon.config.models import BranchesConfig
from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.core import branch_inventory
from claude_code_hooks_daemon.core.branch_inventory import (
    CACHE_RELATIVE_PATH,
    BranchInventory,
    BranchState,
    Containment,
    DormancyStage,
    build_inventory,
)
from claude_code_hooks_daemon.daemon import branch_safety
from claude_code_hooks_daemon.utils.git_repo import run_git

NOW = 1_800_000_000
DAY = 86_400

_CONFIG = BranchesConfig.model_validate({"integration_lines": ["release/*"], "exempt": ["users/*"]})


def _env(days_ago: float) -> dict[str, str]:
    stamp = f"@{int(NOW - days_ago * DAY)} +0000"
    return {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
        "GIT_AUTHOR_DATE": stamp,
        "GIT_COMMITTER_DATE": stamp,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
    }


def _git(repo: Path, *args: str, days_ago: float = 0) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), "-c", "commit.gpgsign=false", *args],
        check=True,
        capture_output=True,
        text=True,
        env=_env(days_ago),
    )
    return result.stdout.strip()


def _commit(repo: Path, name: str, days_ago: float, lines: int = 1, message: str = "") -> None:
    (repo / f"{name}.txt").write_text("".join(f"{name} {n}\n" for n in range(lines)))
    _git(repo, "add", f"{name}.txt")
    _git(repo, "commit", "-q", "-m", message or name, days_ago=days_ago)


def _branch_from(repo: Path, name: str, start: str = "main") -> None:
    _git(repo, "checkout", "-q", "-b", name, start)


def _park(repo: Path, days_ago: float) -> None:
    _git(
        repo,
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "Park branch",
        "-m",
        "Parked-Reason: waiting on review\nParked-By: t",
        days_ago=days_ago,
    )


@pytest.fixture(scope="module")
def fixture_repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("inventory")
    remote = root / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
    repo = root / "clone"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "remote", "add", "origin", str(remote))

    _commit(repo, "base", 60)

    _branch_from(repo, "release/x")
    _commit(repo, "rel", 50)

    _branch_from(repo, "users/alice")
    _commit(repo, "alice", 45)
    _git(repo, "push", "-q", "origin", "users/alice")

    _branch_from(repo, "merged-default")
    _commit(repo, "md", 44)
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "-q", "--ff-only", "merged-default")

    _branch_from(repo, "parked-merged")
    _commit(repo, "pm", 43)
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "-q", "--ff-only", "parked-merged")
    _git(repo, "checkout", "-q", "parked-merged")
    _park(repo, 42)

    _branch_from(repo, "merged-line", "release/x")
    _commit(repo, "ml", 41)
    _git(repo, "checkout", "-q", "release/x")
    _git(repo, "merge", "-q", "--ff-only", "merged-line")

    _branch_from(repo, "cherry")
    _commit(repo, "ch", 40)
    picked = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", "main")
    _git(repo, "cherry-pick", picked, days_ago=39)

    _branch_from(repo, "parked")
    _commit(repo, "pk", 40, lines=3)
    _park(repo, 35)

    _branch_from(repo, "dormant-nowhere")
    _commit(repo, "dn", 31)

    _branch_from(repo, "dormant-own-remote")
    _commit(repo, "dor", 15)
    _git(repo, "push", "-q", "origin", "dormant-own-remote")

    _branch_from(repo, "dormant-other-ref")
    _commit(repo, "dot", 8)
    _git(repo, "push", "-q", "origin", "dormant-other-ref:backup-copy")

    _branch_from(repo, "twin-a")
    _commit(repo, "tw", 1)
    _git(repo, "branch", "twin-b", "twin-a")

    _branch_from(repo, "live")
    _commit(repo, "live", 1, lines=3)

    _branch_from(repo, "worktree-558-thing")
    _commit(repo, "w558", 1, message="Tidy the sweep (Addresses #152)")

    _branch_from(repo, "gh-77-fix")
    _commit(repo, "gh77", 1, message="Plan 00123: fix the thing")

    # Local copy merged into main; the remote copy carries one more, unique commit.
    _branch_from(repo, "divergent")
    _commit(repo, "dv", 20)
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "-q", "--no-ff", "divergent", "-m", "merge divergent", days_ago=20)
    _git(repo, "checkout", "-q", "divergent")
    _commit(repo, "dv-extra", 20)
    _git(repo, "push", "-q", "origin", "divergent")
    _git(repo, "checkout", "-q", "main")
    _git(repo, "branch", "-f", "divergent", "main^2")

    # Evil merge: every plain commit is cherry-picked into main, but the merge
    # commit adds a file main never receives.
    _branch_from(repo, "evil")
    _commit(repo, "ev-a", 2)
    _branch_from(repo, "side")
    _commit(repo, "ev-y", 2)
    _git(repo, "checkout", "-q", "evil")
    _git(repo, "merge", "-q", "--no-commit", "--no-ff", "side", days_ago=2)
    (repo / "evil-only.txt").write_text("only in the merge\n")
    _git(repo, "add", "evil-only.txt")
    _git(repo, "commit", "-q", "-m", "evil merge", days_ago=2)
    _git(repo, "checkout", "-q", "main")
    _git(repo, "cherry-pick", _git(repo, "rev-parse", "evil^1"), days_ago=2)
    _git(repo, "cherry-pick", _git(repo, "rev-parse", "side"), days_ago=2)

    # A folded (multi-line) trailer value on the tip.
    _branch_from(repo, "multiline")
    (repo / "ml-folded.txt").write_text("m\n")
    _git(repo, "add", "ml-folded.txt")
    _git(
        repo,
        "commit",
        "-q",
        "-m",
        "work",
        "-m",
        "Parked-Reason: waiting on\n the owner to decide",
        days_ago=2,
    )

    # Dormant work contained only in a protected (non-work) remote branch.
    _branch_from(repo, "dormant-in-develop")
    _commit(repo, "did", 9)
    _git(repo, "push", "-q", "origin", "dormant-in-develop:develop")

    # Dormant work contained only in a tag.
    _branch_from(repo, "dormant-tagged")
    _commit(repo, "dtg", 9)
    _git(repo, "tag", "keep-me")

    # Two dormant work branches, both pushed, at one tip.
    _branch_from(repo, "pair-a")
    _commit(repo, "pair", 9)
    _git(repo, "branch", "pair-b", "pair-a")
    _git(repo, "push", "-q", "origin", "pair-a", "pair-b")

    _git(repo, "checkout", "-q", "main")
    _commit(repo, "m2", 0.5)
    _git(repo, "push", "-q", "origin", "main", "release/x")

    # Merged only into the LOCAL main, which is not pushed.
    _branch_from(repo, "local-merged")
    _commit(repo, "lm", 0.4)
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "-q", "--ff-only", "local-merged")

    _git(repo, "worktree", "add", "-q", str(root / "wt-live"), "live")
    return repo


@pytest.fixture
def repo(fixture_repo: Path) -> Path:
    """The shared fixture with a fresh (absent) cache for each test."""
    cache = fixture_repo / CACHE_RELATIVE_PATH
    if cache.exists():
        cache.unlink()
    return fixture_repo


@pytest.fixture
def inventory(repo: Path) -> BranchInventory:
    return build_inventory(repo, _CONFIG, now=NOW)


def _with(section: str, **values: object) -> BranchesConfig:
    current = getattr(_CONFIG, section)
    return _CONFIG.model_copy(update={section: current.model_copy(update=values)})


class TestStates:
    @pytest.mark.parametrize(
        ("name", "state"),
        [
            ("users/alice", BranchState.EXEMPT),
            ("main", BranchState.DEFAULT),
            ("release/x", BranchState.INTEGRATION_LINE),
            ("merged-default", BranchState.MERGED_DEFAULT),
            ("merged-line", BranchState.MERGED_LINE),
            ("cherry", BranchState.PATCH_EQUIVALENT),
            ("parked", BranchState.PARKED),
            ("dormant-nowhere", BranchState.DORMANT),
            ("dormant-own-remote", BranchState.DORMANT),
            ("dormant-other-ref", BranchState.DORMANT),
            ("backup-copy", BranchState.DORMANT),
            ("twin-a", BranchState.LIVE),
            ("twin-b", BranchState.LIVE),
            ("live", BranchState.LIVE),
            ("worktree-558-thing", BranchState.LIVE),
            ("develop", BranchState.PROTECTED),
            ("side", BranchState.PATCH_EQUIVALENT),
            ("local-merged", BranchState.MERGED_DEFAULT),
        ],
    )
    def test_state(self, inventory: BranchInventory, name: str, state: BranchState) -> None:
        assert inventory.records[name].state == state

    def test_default_branch_is_resolved(self, inventory: BranchInventory) -> None:
        assert inventory.default_branch == "main"
        assert inventory.default_ref == "refs/remotes/origin/main"

    def test_merged_into_names_the_target(self, inventory: BranchInventory) -> None:
        assert inventory.records["merged-default"].merged_into == "main"
        assert inventory.records["merged-line"].merged_into == "release/x"
        assert inventory.records["cherry"].merged_into == "main"

    def test_proven_by_names_the_ref_that_proved_it(self, inventory: BranchInventory) -> None:
        assert inventory.records["merged-default"].proven_by == "origin/main"
        assert inventory.records["merged-line"].proven_by == "origin/release/x"
        assert inventory.records["cherry"].proven_by == "origin/main"

    def test_a_merge_into_the_unpushed_local_default_says_so(
        self, inventory: BranchInventory
    ) -> None:
        record = inventory.records["local-merged"]
        assert (record.merged_into, record.proven_by) == ("main", "main")

    def test_work_states_carry_no_proof(self, inventory: BranchInventory) -> None:
        assert inventory.records["live"].proven_by is None


class TestBothTips:
    """A name whose local and remote copies differ is done only when EVERY copy is."""

    def test_merged_local_copy_does_not_vouch_for_a_divergent_remote_copy(
        self, repo: Path, inventory: BranchInventory
    ) -> None:
        record = inventory.records["divergent"]
        assert record.local_tip != record.remote_tip
        assert record.state == BranchState.DORMANT
        assert (record.merged_into, record.proven_by) == (None, None)
        assert record.ahead == 1
        assert record.age_days == pytest.approx(20)
        assert record.containment == Containment.OWN_REMOTE

    def test_combined_verdict_takes_the_weakest_copy(self) -> None:
        merged_remote = branch_inventory._Verdict(
            state=BranchState.MERGED_DEFAULT,
            merged_into="main",
            proven_ref="refs/remotes/origin/main",
            ahead=0,
            lines=0,
        )
        merged_local = replace(merged_remote, proven_ref="refs/heads/main")
        equivalent = replace(merged_remote, state=BranchState.PATCH_EQUIVALENT, ahead=1)
        combine = branch_inventory._weakest
        assert combine([merged_remote, merged_local]) == merged_local
        assert combine([merged_local, equivalent]) == equivalent
        assert combine([merged_remote]) == merged_remote


class TestMergeCommits:
    def test_content_only_in_a_merge_commit_is_not_patch_equivalent(
        self, inventory: BranchInventory
    ) -> None:
        record = inventory.records["evil"]
        assert record.state == BranchState.LIVE
        assert record.merged_into is None


class TestFoldedTrailer:
    def test_a_folded_park_reason_keeps_the_branch_and_unfolds_the_reason(
        self, inventory: BranchInventory
    ) -> None:
        record = inventory.records["multiline"]
        assert record.state == BranchState.PARKED
        assert record.parked_reason == "waiting on the owner to decide"

    def test_origin_head_is_never_a_branch(self, repo: Path) -> None:
        _git(repo, "remote", "set-head", "origin", "main")
        try:
            assert "HEAD" not in build_inventory(repo, _CONFIG, now=NOW).records
        finally:
            _git(repo, "remote", "set-head", "origin", "--delete")


class TestParkCommits:
    def test_parked_reason_is_read(self, inventory: BranchInventory) -> None:
        assert inventory.records["parked"].parked_reason == "waiting on review"

    def test_park_commit_is_not_counted_in_ahead_or_lines(self, inventory: BranchInventory) -> None:
        record = inventory.records["parked"]
        assert record.ahead == 1
        assert record.lines == 3

    def test_park_commit_does_not_make_a_merged_branch_unique(
        self, inventory: BranchInventory
    ) -> None:
        record = inventory.records["parked-merged"]
        assert record.state == BranchState.MERGED_DEFAULT
        assert record.ahead == 0


class TestCounts:
    def test_live_branch(self, inventory: BranchInventory) -> None:
        record = inventory.records["live"]
        # Behind origin/main: dv, the divergent merge, two cherry-picks and m2.
        assert (record.ahead, record.behind, record.lines) == (1, 5, 3)

    def test_age_from_committer_date(self, inventory: BranchInventory) -> None:
        assert inventory.records["dormant-nowhere"].age_days == pytest.approx(31)
        assert inventory.records["live"].age_days == pytest.approx(1)

    def test_tips(self, repo: Path, inventory: BranchInventory) -> None:
        record = inventory.records["dormant-own-remote"]
        tip = _git(repo, "rev-parse", "dormant-own-remote")
        assert (record.local_tip, record.remote_tip) == (tip, tip)
        remote_only = inventory.records["backup-copy"]
        assert remote_only.local_tip is None
        assert remote_only.remote_tip == _git(repo, "rev-parse", "dormant-other-ref")

    def test_worktree_path(self, repo: Path, inventory: BranchInventory) -> None:
        assert inventory.records["live"].worktree == (repo.parent / "wt-live").resolve()
        assert inventory.records["twin-a"].worktree is None


class TestSameTip:
    def test_twins_point_at_each_other(self, inventory: BranchInventory) -> None:
        assert inventory.records["twin-a"].same_tip_as == ("twin-b",)
        assert inventory.records["twin-b"].same_tip_as == ("twin-a",)

    def test_local_and_remote_copy_of_one_name_are_one_record(
        self, inventory: BranchInventory
    ) -> None:
        assert inventory.records["dormant-own-remote"].same_tip_as == ()

    def test_remote_only_copy_under_another_name_is_grouped(
        self, inventory: BranchInventory
    ) -> None:
        assert inventory.records["dormant-other-ref"].same_tip_as == ("backup-copy",)


class TestDormancy:
    @pytest.mark.parametrize(
        ("name", "stage"),
        [
            ("dormant-nowhere", DormancyStage.BLOCK),
            ("dormant-own-remote", DormancyStage.NOISY),
            ("dormant-other-ref", DormancyStage.ADVISORY),
        ],
    )
    def test_standard_stages(
        self, inventory: BranchInventory, name: str, stage: DormancyStage
    ) -> None:
        assert inventory.records[name].dormancy_stage == stage

    def test_strict_preset(self, repo: Path) -> None:
        records = build_inventory(repo, _with("dormancy", preset="strict"), now=NOW).records
        assert records["dormant-other-ref"].dormancy_stage == DormancyStage.BLOCK
        assert records["dormant-own-remote"].dormancy_stage == DormancyStage.BLOCK

    def test_warn_mode_caps_at_noisy(self, repo: Path) -> None:
        records = build_inventory(repo, _with("dormancy", mode="warn"), now=NOW).records
        assert records["dormant-nowhere"].dormancy_stage == DormancyStage.NOISY

    def test_off_mode_has_no_dormant_state(self, repo: Path) -> None:
        records = build_inventory(repo, _with("dormancy", mode="off"), now=NOW).records
        assert records["dormant-nowhere"].state == BranchState.LIVE

    def test_parked_and_live_branches_have_no_stage(self, inventory: BranchInventory) -> None:
        assert inventory.records["parked"].dormancy_stage is None
        assert inventory.records["live"].dormancy_stage is None


class TestContainment:
    def test_nowhere(self, inventory: BranchInventory) -> None:
        record = inventory.records["dormant-nowhere"]
        assert (record.containment, record.contained_in) == (Containment.NOWHERE, None)

    def test_own_remote_only(self, inventory: BranchInventory) -> None:
        record = inventory.records["dormant-own-remote"]
        assert record.containment == Containment.OWN_REMOTE
        assert record.contained_in == "origin/dormant-own-remote"

    def test_a_work_branch_never_vouches_for_another(self, inventory: BranchInventory) -> None:
        """Both sides of a backup pair: neither is a cleanup candidate."""
        record = inventory.records["dormant-other-ref"]
        assert record.containment == Containment.OTHER_WORK_BRANCH
        assert record.contained_in == "origin/backup-copy"
        backup = inventory.records["backup-copy"]
        assert backup.containment == Containment.OWN_REMOTE
        assert backup.contained_in == "origin/backup-copy"

    @pytest.mark.parametrize("name", ["pair-a", "pair-b"])
    def test_twins_both_pushed_are_each_on_their_own_remote(
        self, inventory: BranchInventory, name: str
    ) -> None:
        record = inventory.records[name]
        assert (record.containment, record.contained_in) == (
            Containment.OWN_REMOTE,
            f"origin/{name}",
        )

    def test_a_protected_remote_branch_vouches(self, inventory: BranchInventory) -> None:
        record = inventory.records["dormant-in-develop"]
        assert record.containment == Containment.REMOTE_REF
        assert record.contained_in == "origin/develop"

    def test_an_unpushed_local_tag_does_not_vouch(self, inventory: BranchInventory) -> None:
        """Containment is remote-tracking refs only (DESIGN.md section 4).

        A local tag may never have been pushed, so counting it would hide a
        branch whose commits no remote holds behind a CONTAINED NOWHERE that
        never prints.
        """
        record = inventory.records["dormant-tagged"]
        assert record.containment == Containment.NOWHERE
        assert record.contained_in is None

    def test_in_default(self, repo: Path) -> None:
        """Reachable only through the helper: a branch in the default is merged first."""
        tip = _git(repo, "rev-parse", "merged-default")
        assert branch_inventory.containment_of(
            repo, name="merged-default", tip=tip, config=_CONFIG, default="main"
        ) == (Containment.DEFAULT, "origin/main")

    def test_non_dormant_branches_carry_none(self, inventory: BranchInventory) -> None:
        assert inventory.records["live"].containment is None


class TestLinks:
    def test_plan_from_branch_name_issue_from_subject(self, inventory: BranchInventory) -> None:
        record = inventory.records["worktree-558-thing"]
        assert (record.plan, record.issue) == ("00558", 152)

    def test_issue_from_branch_name_plan_from_subject(self, inventory: BranchInventory) -> None:
        record = inventory.records["gh-77-fix"]
        assert (record.plan, record.issue) == ("00123", 77)

    def test_no_link(self, inventory: BranchInventory) -> None:
        record = inventory.records["live"]
        assert (record.plan, record.issue) == (None, None)


class TestBudgetAndCache:
    def test_zero_budget_leaves_unmerged_branches_unclassified(self, repo: Path) -> None:
        records = build_inventory(repo, _with("sweep", budget_ms=0), now=NOW).records
        for name in ("cherry", "live", "dormant-nowhere", "parked", "twin-a"):
            assert records[name].state == BranchState.UNCLASSIFIED, name
            assert records[name].ahead is None
        # The bulk steps still prove what they can.
        assert records["merged-default"].state == BranchState.MERGED_DEFAULT
        assert records["merged-line"].state == BranchState.MERGED_LINE
        assert records["main"].state == BranchState.DEFAULT
        assert records["users/alice"].state == BranchState.EXEMPT

    def test_cache_is_written(self, repo: Path, inventory: BranchInventory) -> None:
        data = json.loads((repo / CACHE_RELATIVE_PATH).read_text())
        live = _git(repo, "rev-parse", "live")
        target = _git(repo, "rev-parse", "origin/main")
        entry = data["pairs"][f"{live}:{target}:lines"]
        assert (entry["ahead"], entry["unique"], entry["merges"], entry["lines"]) == (1, 1, 0, 3)

    def test_cache_key_separates_line_and_default_targets(self, repo: Path) -> None:
        """One target sha read first as a line (no lines) must not answer for the default."""
        run = branch_inventory._Pass(repo, _CONFIG, branch_inventory._Cache())
        sha = _git(repo, "rev-parse", "origin/main")
        tip = _git(repo, "rev-parse", "live")
        line = branch_inventory._Target("release/y", "refs/heads/release/y", sha, is_default=False)
        default = branch_inventory._Target("main", "refs/remotes/origin/main", sha, is_default=True)
        first = run.facts(tip, line)
        assert first is not None and first.lines is None
        second = run.facts(tip, default)
        assert second is not None and second.lines == 3

    def test_second_pass_reads_the_cache_without_git_cherry(
        self, repo: Path, inventory: BranchInventory, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def forbidden(*_: object, **__: object) -> None:
            raise AssertionError("git cherry ran on a cached (tip, target) pair")

        monkeypatch.setattr(branch_safety, "cherry_unique_shas", forbidden)
        again = build_inventory(repo, _CONFIG, now=NOW)
        assert {n: r.state for n, r in again.records.items()} == {
            n: r.state for n, r in inventory.records.items()
        }
        assert again.records["parked"].ahead == 1

    def test_zero_budget_still_classifies_from_the_cache(
        self, repo: Path, inventory: BranchInventory
    ) -> None:
        records = build_inventory(repo, _with("sweep", budget_ms=0), now=NOW).records
        assert records["cherry"].state == BranchState.PATCH_EQUIVALENT
        assert records["dormant-nowhere"].containment == Containment.NOWHERE

    def test_corrupt_cache_is_ignored(self, repo: Path) -> None:
        cache = repo / CACHE_RELATIVE_PATH
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text("{not json")
        records = build_inventory(repo, _CONFIG, now=NOW).records
        assert records["cherry"].state == BranchState.PATCH_EQUIVALENT


class TestFailClosed:
    def test_a_cherry_failure_is_unclassified_never_merged(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(branch_safety, "cherry_unique_shas", lambda *_a, **_k: None)
        records = build_inventory(repo, _CONFIG, now=NOW).records
        assert records["cherry"].state == BranchState.UNCLASSIFIED
        assert records["live"].state == BranchState.UNCLASSIFIED

    def test_not_a_repository_raises(self, tmp_path: Path) -> None:
        with pytest.raises(branch_inventory.BranchInventoryError):
            build_inventory(tmp_path, _CONFIG, now=NOW)

    def test_merged_listing_failure_proves_nothing_wrongly(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        real = run_git

        def failing_merged(
            cwd: Path, *args: str, timeout: float = Timeout.GIT_CONTEXT
        ) -> subprocess.CompletedProcess[str]:
            if any(arg.startswith("--merged") for arg in args):
                return subprocess.CompletedProcess(list(args), 1, "", "boom")
            return real(cwd, *args, timeout=timeout)

        monkeypatch.setattr(branch_inventory, "run_git", failing_merged)
        records = build_inventory(repo, _CONFIG, now=NOW).records
        # Ancestry is still found by the per-branch step, never assumed.
        assert records["merged-default"].state == BranchState.MERGED_DEFAULT
        assert records["live"].state == BranchState.LIVE


class TestEdges:
    """Each fail-closed path of the helpers, one at a time."""

    def test_old_git_without_ahead_behind_leaves_behind_unknown(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        real = run_git

        def no_atom(
            cwd: Path, *args: str, timeout: float = Timeout.GIT_CONTEXT
        ) -> subprocess.CompletedProcess[str]:
            if any("ahead-behind" in arg for arg in args):
                return subprocess.CompletedProcess(list(args), 128, "", "unknown field")
            return real(cwd, *args, timeout=timeout)

        monkeypatch.setattr(branch_inventory, "run_git", no_atom)
        records = build_inventory(repo, _CONFIG, now=NOW).records
        assert records["live"].behind is None
        assert records["live"].state == BranchState.LIVE

    @staticmethod
    def _rewrite_listing(monkeypatch: pytest.MonkeyPatch, rewrite: Callable[[str], str]) -> None:
        """Pass the step-1 ``for-each-ref`` output through ``rewrite``."""
        real = run_git

        def patched(
            cwd: Path, *args: str, timeout: float = Timeout.GIT_CONTEXT
        ) -> subprocess.CompletedProcess[str]:
            result = real(cwd, *args, timeout=timeout)
            if args[0] == "for-each-ref" and any("committerdate" in a for a in args):
                return subprocess.CompletedProcess(result.args, 0, rewrite(result.stdout), "")
            return result

        monkeypatch.setattr(branch_inventory, "run_git", patched)

    def test_an_unparseable_date_is_unclassified_never_epoch_zero(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._rewrite_listing(
            monkeypatch,
            lambda out: re.sub(r"(refs/heads/live\x00[0-9a-f]+\x00)\d+", r"\1garbage", out),
        )
        record = build_inventory(repo, _CONFIG, now=NOW).records["live"]
        assert record.state == BranchState.UNCLASSIFIED
        assert record.reason is not None and "date" in record.reason
        assert (record.committed_at, record.age_days, record.dormancy_stage) == (None, None, None)

    def test_an_unparseable_remote_copy_makes_the_name_unclassified(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._rewrite_listing(
            monkeypatch,
            lambda out: re.sub(
                r"(refs/remotes/origin/dormant-own-remote\x00)[0-9a-f]+", r"\1zz", out
            ),
        )
        record = build_inventory(repo, _CONFIG, now=NOW).records["dormant-own-remote"]
        assert record.state == BranchState.UNCLASSIFIED
        assert record.reason is not None and "object name" in record.reason

    def test_misaligned_listing_raises(self, repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self._rewrite_listing(monkeypatch, lambda out: out + "stray\x00")
        with pytest.raises(branch_inventory.BranchInventoryError):
            build_inventory(repo, _CONFIG, now=NOW)

    def test_a_listing_that_loses_its_ref_name_raises(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._rewrite_listing(
            monkeypatch, lambda out: out.replace("\nrefs/heads/live\x00", "\nnot-a-ref\x00", 1)
        )
        with pytest.raises(branch_inventory.BranchInventoryError):
            build_inventory(repo, _CONFIG, now=NOW)

    def test_worktree_listing_failure_makes_worktrees_unknown(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        real = run_git

        def no_worktrees(
            cwd: Path, *args: str, timeout: float = Timeout.GIT_CONTEXT
        ) -> subprocess.CompletedProcess[str]:
            if args[0] == "worktree":
                return subprocess.CompletedProcess(list(args), 1, "", "boom")
            return real(cwd, *args, timeout=timeout)

        monkeypatch.setattr(branch_inventory, "run_git", no_worktrees)
        inventory = build_inventory(repo, _CONFIG, now=NOW)
        assert inventory.worktrees_known is False
        record = inventory.records["live"]
        assert (record.worktree, record.worktree_known) == (None, False)

    def test_worktree_listing_success_is_known(self, inventory: BranchInventory) -> None:
        assert inventory.worktrees_known is True
        assert inventory.records["twin-a"].worktree_known is True

    def test_a_named_default_that_does_not_exist_merges_nothing(self, repo: Path) -> None:
        config = _CONFIG.model_copy(update={"default": "no-such-branch"})
        inventory = build_inventory(repo, config, now=NOW)
        assert inventory.default_branch == "no-such-branch"
        assert inventory.default_ref is None
        # Protected names stay out of the work states whatever the default resolved to.
        assert inventory.records["main"].state == BranchState.PROTECTED
        assert inventory.records["main"].dormancy_stage is None
        assert inventory.records["merged-default"].state == BranchState.DORMANT
        assert inventory.records["merged-line"].state == BranchState.MERGED_LINE
        assert inventory.records["live"].ahead is None

    def test_malformed_log_is_no_facts(self, repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        assert branch_inventory._park_shas("only\x1ftwo\n") is None
        monkeypatch.setattr(branch_inventory, "_park_shas", lambda _out: None)
        assert branch_inventory._pair_facts(repo, "live", "main", want_lines=True) is None

    def test_an_empty_listing_has_no_rows(self) -> None:
        assert branch_inventory._parse_listing("") == []

    def test_a_record_not_started_by_the_record_end_raises(self) -> None:
        sha = "a" * 40
        row = f"refs/heads/a\x00{sha}\x001\x00\x00\x00\x00s\x00"
        with pytest.raises(branch_inventory.BranchInventoryError):
            branch_inventory._parse_listing(row + row + "\n")

    def test_no_git_call_reads_tags(self, repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Tags are neither containment nor part of its cache key, so none is listed."""
        real = run_git
        calls: list[tuple[str, ...]] = []

        def recording(
            cwd: Path, *args: str, timeout: float = Timeout.GIT_CONTEXT
        ) -> subprocess.CompletedProcess[str]:
            calls.append(args)
            return real(cwd, *args, timeout=timeout)

        monkeypatch.setattr(branch_inventory, "run_git", recording)
        cache = repo / CACHE_RELATIVE_PATH
        if cache.exists():
            cache.unlink()
        build_inventory(repo, _CONFIG, now=NOW)
        assert not [args for args in calls if any("refs/tags" in arg for arg in args)]

    def test_containment_cache_key_ignores_tags(self, repo: Path) -> None:
        rows = branch_inventory._list_refs(repo, "origin", None)
        before = branch_inventory._refs_hash(rows)
        _git(repo, "tag", "cache-key-probe", "live")
        try:
            assert branch_inventory._refs_hash(rows) == before
        finally:
            _git(repo, "tag", "-d", "cache-key-probe")

    def test_log_failure_is_no_facts(self, repo: Path) -> None:
        assert branch_inventory._pair_facts(repo, "live", "no-such", want_lines=True) is None

    def test_lines_failure_is_no_facts(self, repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(branch_inventory, "_lines", lambda *_a: None)
        assert branch_inventory._pair_facts(repo, "live", "main", want_lines=True) is None

    def test_lines_of_a_bad_range_is_none(self, repo: Path) -> None:
        assert branch_inventory._lines(repo, "no-such", "live") is None

    def test_containment_failure_is_none(self, tmp_path: Path) -> None:
        assert (
            branch_inventory.containment_of(
                tmp_path, name="x", tip="abc", config=_CONFIG, default=None
            )
            is None
        )

    def test_containment_without_a_default(self, repo: Path) -> None:
        tip = _git(repo, "rev-parse", "dormant-nowhere")
        assert branch_inventory.containment_of(
            repo, name="dormant-nowhere", tip=tip, config=_CONFIG, default=None
        ) == (Containment.NOWHERE, None)

    @pytest.mark.parametrize(
        "document",
        ['{"version": 99, "pairs": {}}', "[1, 2]", '{"version": 1, "pairs": [], "containment": 3}'],
    )
    def test_unusable_cache_documents_are_empty(self, tmp_path: Path, document: str) -> None:
        path = tmp_path / "cache.json"
        path.write_text(document)
        cache = branch_inventory._load_cache(path)
        assert (cache.pairs, cache.containment) == ({}, {})

    @pytest.mark.parametrize(
        "entry",
        [
            None,
            {"ahead": "1", "unique": 0, "merges": 0},
            {"ahead": 1, "unique": 0, "merges": 0, "lines": "3"},
            {"ahead": 1, "unique": 0, "lines": None},
        ],
    )
    def test_unusable_cache_entries_are_ignored(self, entry: dict[str, object] | None) -> None:
        assert branch_inventory._facts_from_cache(entry) is None

    def test_unwritable_cache_does_not_raise(self, tmp_path: Path) -> None:
        blocker = tmp_path / "file"
        blocker.write_text("x")
        branch_inventory._save_cache(blocker / "cache.json", branch_inventory._Cache(), set())
        assert not (blocker / "cache.json").exists()

    def test_containment_cut_off_by_the_budget_is_unknown(self, repo: Path) -> None:
        """Facts cached, containment not: a zero budget leaves containment None."""
        build_inventory(repo, _CONFIG, now=NOW)
        cache = repo / CACHE_RELATIVE_PATH
        data = json.loads(cache.read_text())
        data["containment"] = {}
        cache.write_text(json.dumps(data))
        records = build_inventory(repo, _with("sweep", budget_ms=0), now=NOW).records
        assert records["dormant-nowhere"].state == BranchState.DORMANT
        assert records["dormant-nowhere"].containment is None


class TestCherryUniqueShas:
    def test_lists_only_unique_commits(self, repo: Path) -> None:
        main = _git(repo, "rev-parse", "main")
        live = _git(repo, "rev-parse", "live")
        cherry = _git(repo, "rev-parse", "cherry")
        assert branch_safety.cherry_unique_shas(repo, main, live) == [live]
        assert branch_safety.cherry_unique_shas(repo, main, cherry) == []

    def test_failure_is_none(self, tmp_path: Path) -> None:
        assert branch_safety.cherry_unique_shas(tmp_path, "a", "b") is None
