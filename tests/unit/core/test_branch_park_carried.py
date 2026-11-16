"""One classification for a park commit over work the default already holds (Plan 00594).

A park marker (an empty commit with ``Parked-*`` trailers) on top of work a merged
release line carries holds nothing: the work is in the default, only the marker is
unique. The sweep, the creation guard and the remote-delete guard each judged such a
tip by a different rule, so a clone read ``Parked: 4 of 10`` in the sweep while the
guard refused at ``Parked branches: 10 (cap 10)``. These tests build real repositories
with a bare remote and pin all three consumers to ONE answer.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.config.models import (
    BranchesConfig,
    BranchMergedConfig,
    BranchParkedConfig,
    BranchWipConfig,
)
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import (
    branch_cleanup,
    branch_creation,
    branch_inventory,
    branch_sweep,
)
from claude_code_hooks_daemon.core.branch_inventory import BranchState, Pool
from claude_code_hooks_daemon.core.remote_branch_proof import prove_remote_merged
from tests.conftest import HERMETIC_GIT_EMAIL

_DAY = 86_400
_CARRIED_REASON = "carried by the release line release/x (PR 12); merges with it"


def _git(repo: Path, *args: str, env: dict[str, str] | None = None) -> str:
    import os

    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, **(env or {})},
    ).stdout


def _commit(repo: Path, filename: str, text: str) -> None:
    (repo / filename).write_text(text, encoding="utf-8")
    _git(repo, "add", filename)
    _git(repo, "commit", "-q", "-m", f"Add {filename}")


def _park(repo: Path, reason: str, *, days_old: float = 0.0) -> None:
    """An empty park commit on the checked-out branch, dated ``days_old`` days ago."""
    when = f"{int(time.time() - days_old * _DAY)} +0000"
    _git(
        repo,
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "Park",
        "--trailer",
        f"Parked-Reason: {reason}",
        "--trailer",
        "Parked-By: tester",
        env={"GIT_COMMITTER_DATE": when, "GIT_AUTHOR_DATE": when},
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    bare = tmp_path / "remote.git"
    _git(tmp_path, "init", "--quiet", "--bare", "-b", "main", str(bare))
    path = tmp_path / "repo"
    path.mkdir()
    _git(path, "init", "-q", "-b", "main")
    _git(path, "config", "user.email", HERMETIC_GIT_EMAIL)
    _git(path, "config", "user.name", "t")
    _commit(path, "base.txt", "base\n")
    _git(path, "remote", "add", "origin", str(bare))
    _git(path, "push", "-q", "origin", "main")
    _git(path, "remote", "set-head", "origin", "main")
    return path


def _parked_over_merged(
    repo: Path, name: str, *, keep_local: bool = False, days_old: float = 0.0
) -> None:
    """``name`` merged into main (no-ff), then parked on top, pushed; local copy dropped."""
    _git(repo, "checkout", "-q", "-b", name, "main")
    _commit(repo, f"{name}.txt", f"{name}\n")
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "--no-ff", "-q", "-m", f"Merge {name}", name)
    _git(repo, "push", "-q", "origin", "main")
    _git(repo, "checkout", "-q", name)
    _park(repo, _CARRIED_REASON, days_old=days_old)
    _git(repo, "push", "-q", "-u", "origin", name)
    _git(repo, "checkout", "-q", "main")
    if not keep_local:
        _git(repo, "branch", "-q", "-D", name)


def _parked_over_unmerged(repo: Path, name: str, *, keep_local: bool = True) -> None:
    """``name`` with work main does not hold, parked on top and pushed."""
    _git(repo, "checkout", "-q", "-b", name, "main")
    _commit(repo, f"{name}.txt", f"{name}\n")
    _park(repo, "waiting on a design decision")
    _git(repo, "push", "-q", "-u", "origin", name)
    _git(repo, "checkout", "-q", "main")
    if not keep_local:
        _git(repo, "branch", "-q", "-D", name)


def _config(parked_cap: int = 3, merged_cap: int = 3) -> BranchesConfig:
    return BranchesConfig(
        default="main",
        wip=BranchWipConfig(cap=20, count_remote=True, creation_grace=0),
        parked=BranchParkedConfig(cap=parked_cap),
        merged=BranchMergedConfig(cap=merged_cap),
    )


def _rules(repo: Path, config: BranchesConfig) -> set[str]:
    report = branch_creation.creation_report(repo, config, "brand-new-work")
    return {str(s.rule_id) for s in report.blockers if s.rule_id is not None}


def _inventory(repo: Path, config: BranchesConfig) -> branch_inventory.BranchInventory:
    return branch_inventory.build_inventory(repo, config)


class TestAcceptance:
    """Six remote-only park refs over merged work beside two real parks (the reported shape)."""

    @pytest.fixture
    def cloned(self, repo: Path) -> Path:
        for index in range(2):
            _parked_over_unmerged(repo, f"real-park-{index}")
        for index in range(6):
            _parked_over_merged(repo, f"carried-{index}")
        _git(repo, "fetch", "-q", "--prune", "origin")
        return repo

    def test_the_guard_does_not_refuse_on_the_carried_refs(self, cloned: Path) -> None:
        config = _config(parked_cap=3, merged_cap=3)
        refused = _rules(cloned, config)
        assert str(RuleID.BRANCH_PARKED_POOL) not in refused
        assert str(RuleID.BRANCH_MERGED_POOL) not in refused

    def test_the_sweep_counts_only_the_real_parks(self, cloned: Path) -> None:
        inventory = _inventory(cloned, _config())
        assert branch_sweep.pool_count(inventory, Pool.PARKED) == 2
        assert branch_sweep.pool_count(inventory, Pool.MERGED) == 0

    def test_the_sweep_gives_the_carried_refs_one_defined_status(self, cloned: Path) -> None:
        inventory = _inventory(cloned, _config())
        states = {name: r.state for name, r in inventory.records.items() if "carried" in name}
        assert states == {f"carried-{i}": BranchState.PARK_CARRIED for i in range(6)}
        assert branch_sweep.group_records(inventory).park_carried

    def test_the_real_parks_stay_parked_in_both(self, cloned: Path) -> None:
        inventory = _inventory(cloned, _config())
        assert inventory.records["real-park-0"].state == BranchState.PARKED
        report = "\n".join(branch_sweep.render_report(inventory, _config(), cap=10))
        assert "real-park-0" in report

    def test_the_remote_delete_proof_accepts_the_carried_refs(self, cloned: Path) -> None:
        names = [f"carried-{i}" for i in range(6)]
        proof = prove_remote_merged(cloned, "origin", names, "main", _config())
        assert sorted(proof.tips) == names, proof.problems
        assert set(proof.evidence.values()) == {"park-carried"}

    def test_a_park_over_unmerged_work_is_still_refused_by_the_remote_delete_proof(
        self, cloned: Path
    ) -> None:
        _git(cloned, "branch", "-q", "-D", "real-park-1")
        proof = prove_remote_merged(cloned, "origin", ["real-park-1"], "main", _config())
        assert not proof.tips
        assert "real-park-1" in proof.problems

    def test_the_sweep_prints_a_runnable_delete_for_each_carried_ref(self, cloned: Path) -> None:
        inventory = _inventory(cloned, _config())
        proven = branch_cleanup.proven_remote_only(cloned, _config(), inventory)
        assert proven == frozenset(f"carried-{i}" for i in range(6))
        text = "\n".join(
            branch_sweep.render_report(inventory, _config(), cap=10, remote_proven=proven)
        )
        assert "git push origin --delete carried-0" in text
        assert "Park-carried" in text

    def test_clean_remote_deletes_the_carried_refs_only(self, cloned: Path) -> None:
        report = branch_cleanup.clean_sweep(cloned, _config(), dry_run=False, remote=True)
        assert sorted(report.deleted_remote) == [f"origin/carried-{i}" for i in range(6)]
        remaining = _git(cloned, "ls-remote", "--heads", "origin")
        assert "real-park-0" in remaining and "carried-0" not in remaining


class TestAge:
    def test_age_is_the_tip_committer_date_in_sweep_and_guard(self, repo: Path) -> None:
        _parked_over_unmerged(repo, "old-park", keep_local=False)
        _git(repo, "checkout", "-q", "-b", "scratch", "main")
        _git(repo, "checkout", "-q", "main")
        inventory = _inventory(repo, _config())
        assert inventory.records["old-park"].age_days is not None
        assert inventory.records["old-park"].age_days < 1

    def test_a_three_day_old_remote_only_tip_reads_three_days(self, repo: Path) -> None:
        _parked_over_merged(repo, "aged", days_old=3.2)
        inventory = _inventory(repo, _config())
        record = inventory.records["aged"]
        assert record.age_days is not None and 3 <= record.age_days < 4
        text = "\n".join(branch_sweep.render_report(inventory, _config(), cap=10))
        assert "3d old" in text


class TestOneClassifier:
    """The guard's pool membership equals the sweep's, over varied fixtures."""

    @pytest.mark.parametrize("state", list(BranchState))
    def test_the_state_mapping_is_the_shared_rule(self, state: BranchState) -> None:
        by_rule = {
            BranchState.PARK_CARRIED: branch_inventory.pool_for_ref(
                merged=True, park_carried=True, parked=True
            ),
            BranchState.MERGED_DEFAULT: branch_inventory.pool_for_ref(
                merged=True, park_carried=False, parked=False
            ),
            BranchState.PARKED: branch_inventory.pool_for_ref(
                merged=False, park_carried=False, parked=True
            ),
            BranchState.LIVE: branch_inventory.pool_for_ref(
                merged=False, park_carried=False, parked=False
            ),
        }
        if state in by_rule:
            assert branch_inventory.pool_of(state) == by_rule[state]

    @staticmethod
    def _sweep_pools(
        inventory: branch_inventory.BranchInventory,
    ) -> dict[Pool, set[frozenset[str]]]:
        pools: dict[Pool, set[frozenset[str]]] = {p: set() for p in Pool}
        for name, record in inventory.records.items():
            pool = branch_inventory.pool_of(record.state)
            if pool is not None:
                pools[pool].add(frozenset({name, *record.same_tip_as}))
        return pools

    @staticmethod
    def _guard_pools(
        repo: Path, config: BranchesConfig, labels: Any
    ) -> dict[Pool, set[frozenset[str]]]:
        found = branch_creation.work_pools(repo, config, labels=labels)
        return {pool: {work.names for work in works} for pool, works in found.items()}

    @staticmethod
    def _fixtures() -> dict[str, Any]:
        def live_branch(repo: Path) -> None:
            _git(repo, "checkout", "-q", "-b", "live-1", "main")
            _commit(repo, "live.txt", "live\n")
            _git(repo, "checkout", "-q", "main")

        def carried_only(repo: Path) -> None:
            live_branch(repo)
            _parked_over_merged(repo, "c1")
            _parked_over_merged(repo, "c2", keep_local=True)

        def mixed(repo: Path) -> None:
            _parked_over_merged(repo, "c1")
            _parked_over_unmerged(repo, "p1")
            _parked_over_unmerged(repo, "p2", keep_local=False)
            _git(repo, "checkout", "-q", "-b", "live-1", "main")
            _commit(repo, "live.txt", "live\n")
            _git(repo, "checkout", "-q", "main")

        def merged_plain(repo: Path) -> None:
            _git(repo, "checkout", "-q", "-b", "done-1", "main")
            _commit(repo, "d.txt", "d\n")
            _git(repo, "checkout", "-q", "main")
            _git(repo, "merge", "--no-ff", "-q", "-m", "Merge d", "done-1")
            _git(repo, "push", "-q", "origin", "main")
            _git(repo, "push", "-q", "origin", "done-1")

        def repark(repo: Path) -> None:
            live_branch(repo)
            _parked_over_merged(repo, "c1", keep_local=True)
            _git(repo, "checkout", "-q", "c1")
            _park(repo, "parked again")
            _git(repo, "push", "-q", "origin", "c1")
            _git(repo, "checkout", "-q", "main")

        return {
            "carried-only": carried_only,
            "mixed": mixed,
            "merged-plain": merged_plain,
            "re-parked": repark,
        }

    @pytest.mark.parametrize("fixture", ["carried-only", "mixed", "merged-plain", "re-parked"])
    @pytest.mark.parametrize("stale_label", [False, True])
    def test_guard_and_sweep_build_the_same_pools(
        self, repo: Path, fixture: str, stale_label: bool
    ) -> None:
        self._fixtures()[fixture](repo)
        _git(repo, "fetch", "-q", "--prune", "origin")
        config = _config()
        inventory = _inventory(repo, config)
        labels: dict[str, dict[str, str | None]] | None = None
        if stale_label:
            # A snapshot written before the park: a label at the pre-park tip.
            labels = {
                name: {"group": "live", "local_tip": "0" * 40, "remote_tip": "0" * 40}
                for name in inventory.records
            }
        sweep = self._sweep_pools(inventory)
        guard = self._guard_pools(repo, config, labels)
        assert guard == sweep
        assert any(sweep.values()), "a fixture with no pooled branch proves nothing"


def _push_remote_only(repo: Path, name: str) -> None:
    """Push ``name`` and drop the local copy, leaving only ``refs/remotes/origin/<name>``."""
    _git(repo, "push", "-q", "-u", "origin", name)
    _git(repo, "checkout", "-q", "main")
    _git(repo, "branch", "-q", "-D", name)


def _merge_work_into_main(repo: Path, name: str) -> None:
    """``name`` carries one file, merged into main (no-ff) and pushed; ``name`` checked out."""
    _git(repo, "checkout", "-q", "-b", name, "main")
    _commit(repo, f"{name}.txt", f"{name}\n")
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "--no-ff", "-q", "-m", f"Merge {name}", name)
    _git(repo, "push", "-q", "origin", "main")
    _git(repo, "checkout", "-q", name)


def _real_work_under_park(repo: Path, name: str) -> None:
    """Unmerged work, then a park commit on top; remote-only."""
    _parked_over_unmerged(repo, name, keep_local=False)


def _real_work_above_park(repo: Path, name: str) -> None:
    """A park commit, then a non-empty commit on top of it; remote-only."""
    _git(repo, "checkout", "-q", "-b", name, "main")
    _park(repo, "waiting")
    _commit(repo, f"{name}.txt", f"{name}\n")
    _push_remote_only(repo, name)


def _non_park_empty_over_merged(repo: Path, name: str) -> None:
    """An empty commit WITHOUT a Parked-* trailer over merged work; remote-only."""
    _merge_work_into_main(repo, name)
    _git(repo, "commit", "-q", "--allow-empty", "-m", "Nothing to see")
    _push_remote_only(repo, name)


def _park_over_merged_then_work(repo: Path, name: str) -> None:
    """A park commit over merged work, then a later non-empty commit; remote-only."""
    _merge_work_into_main(repo, name)
    _park(repo, _CARRIED_REASON)
    _commit(repo, f"{name}-more.txt", "more\n")
    _push_remote_only(repo, name)


class TestParkCarriedIsOnlyParkCommits:
    """A ref with real work beyond the default is never park-carried: it stays counted."""

    def test_remote_only_park_over_real_work_stays_parked_and_counted(self, repo: Path) -> None:
        _real_work_under_park(repo, "forgotten")
        _git(repo, "fetch", "-q", "--prune", "origin")
        assert _git(repo, "branch", "--list", "forgotten").strip() == ""
        config = _config(parked_cap=1)
        inventory = _inventory(repo, config)
        assert inventory.records["forgotten"].state == BranchState.PARKED
        assert branch_sweep.pool_count(inventory, Pool.PARKED) == 1
        assert str(RuleID.BRANCH_PARKED_POOL) in _rules(repo, config)
        guard = branch_creation.work_pools(repo, config)
        assert [w.names for w in guard[Pool.PARKED]] == [frozenset({"forgotten"})]

    @pytest.mark.parametrize(
        "build",
        [_real_work_above_park, _park_over_merged_then_work],
        ids=["work-above-park", "park-over-merged-then-work"],
    )
    def test_real_work_above_a_park_commit_is_not_park_carried(
        self, repo: Path, build: Any
    ) -> None:
        build(repo, "work-above")
        _git(repo, "fetch", "-q", "--prune", "origin")
        config = _config()
        inventory = _inventory(repo, config)
        state = inventory.records["work-above"].state
        assert state != BranchState.PARK_CARRIED
        assert state in {BranchState.PARKED, BranchState.LIVE}
        assert not branch_sweep.group_records(inventory).park_carried
        tip = _git(repo, "rev-parse", "origin/work-above").strip()
        assert not branch_inventory.is_park_residue(repo, tip, "main")
        guard = branch_creation.work_pools(repo, config)
        counted = {n for works in guard.values() for w in works for n in w.names}
        assert "work-above" in counted

    def test_a_non_park_empty_commit_over_merged_work_is_not_park_carried(self, repo: Path) -> None:
        _non_park_empty_over_merged(repo, "plain-empty")
        _git(repo, "fetch", "-q", "--prune", "origin")
        inventory = _inventory(repo, _config())
        assert inventory.records["plain-empty"].state != BranchState.PARK_CARRIED
        assert branch_sweep.pool_count(inventory, Pool.PARKED) == 0
        tip = _git(repo, "rev-parse", "origin/plain-empty").strip()
        assert not branch_inventory.is_park_residue(repo, tip, "main")

    def test_the_guard_and_the_sweep_agree_on_the_mixed_fixture(self, repo: Path) -> None:
        for index in range(6):
            _parked_over_merged(repo, f"carried-{index}")
        for index in range(2):
            _real_work_under_park(repo, f"remote-real-{index}")
        for index in range(2):
            _parked_over_unmerged(repo, f"local-real-{index}")
        _real_work_above_park(repo, "above")
        _park_over_merged_then_work(repo, "merged-then-work")
        _non_park_empty_over_merged(repo, "plain-empty")
        _git(repo, "fetch", "-q", "--prune", "origin")
        config = _config(parked_cap=4)
        inventory = _inventory(repo, config)
        sweep = TestOneClassifier._sweep_pools(inventory)
        guard = TestOneClassifier._guard_pools(repo, config, None)
        assert guard == sweep
        parked = {n for group in sweep[Pool.PARKED] for n in group}
        assert {"remote-real-0", "remote-real-1", "local-real-0", "local-real-1"} <= parked
        assert not {f"carried-{i}" for i in range(6)} & parked
        assert str(RuleID.BRANCH_PARKED_POOL) in _rules(repo, config)
