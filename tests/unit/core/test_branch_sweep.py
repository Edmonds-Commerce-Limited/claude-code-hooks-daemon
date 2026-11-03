"""The branch sweep report (Plan 00558 Tasks 2.2 and 2.3).

Grouping, the open-work count, the CLI text and JSON, and the SessionStart
summary, all over a real fixture repository with commit dates pinned against a
fixed ``NOW``.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.config.models import BranchesConfig
from claude_code_hooks_daemon.core import branch_sweep
from claude_code_hooks_daemon.core.branch_inventory import (
    BranchInventory,
    BranchRecord,
    BranchState,
    Containment,
    DormancyStage,
    build_inventory,
)

NOW = 1_800_000_000
DAY = 86_400

_CONFIG = BranchesConfig.model_validate({"exempt": ["users/*"]})

_BASE = BranchRecord(
    name="base",
    state=BranchState.LIVE,
    local_tip="a" * 40,
    remote_tip=None,
    upstream=None,
    worktree=None,
    ahead=None,
    behind=None,
    lines=None,
    committed_at=None,
    age_days=None,
    parked_reason=None,
    plan=None,
    issue=None,
)


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


def _commit(repo: Path, name: str, days_ago: float) -> None:
    (repo / f"{name}.txt").write_text(f"{name}\n")
    _git(repo, "add", f"{name}.txt")
    _git(repo, "commit", "-q", "-m", name, days_ago=days_ago)


def _branch(repo: Path, name: str, start: str = "main") -> None:
    _git(repo, "checkout", "-q", "-b", name, start)


@pytest.fixture(scope="module")
def repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("sweep")
    remote = root / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
    clone = root / "clone"
    clone.mkdir()
    _git(clone, "init", "-q", "-b", "main")
    _git(clone, "remote", "add", "origin", str(remote))
    _commit(clone, "base", 60)

    _branch(clone, "users/alice")
    _commit(clone, "alice", 50)

    _branch(clone, "merged-a")
    _commit(clone, "ma", 40)
    _git(clone, "checkout", "-q", "main")
    _git(clone, "merge", "-q", "--ff-only", "merged-a")

    _branch(clone, "lost")
    _commit(clone, "lost", 20)

    _branch(clone, "idle-pushed")
    _commit(clone, "ip", 9)
    _git(clone, "push", "-q", "origin", "idle-pushed")

    _branch(clone, "parked")
    _commit(clone, "pk", 3)
    _git(
        clone,
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "park",
        "-m",
        "Parked-Reason: waiting on review",
        days_ago=2,
    )

    _branch(clone, "live")
    _commit(clone, "live", 1)
    _git(clone, "branch", "live-twin", "live")

    _git(clone, "checkout", "-q", "main")
    _git(clone, "push", "-q", "origin", "main")
    return clone


@pytest.fixture(scope="module")
def inventory(repo: Path) -> BranchInventory:
    return build_inventory(repo, _CONFIG, now=NOW)


def _record(name: str, state: BranchState, **extra: Any) -> BranchRecord:
    return replace(_BASE, name=name, state=state, **extra)


def _inventory(*records: BranchRecord) -> BranchInventory:
    return BranchInventory(
        default_branch="main",
        default_ref="refs/remotes/origin/main",
        records={r.name: r for r in records},
    )


class TestGroups:
    def test_each_state_lands_in_its_group(self, inventory: BranchInventory) -> None:
        groups = branch_sweep.group_records(inventory)
        assert [r.name for r in groups.contained_nowhere] == ["lost"]
        assert [r.name for r in groups.merged] == ["merged-a"]
        assert [r.name for r in groups.dormant] == ["idle-pushed"]
        assert [r.name for r in groups.parked] == ["parked"]
        assert [r.name for r in groups.live] == ["live", "live-twin"]
        assert {r.name for r in groups.never_work} == {"main", "users/alice"}

    def test_open_work_counts_identical_tips_once(self, inventory: BranchInventory) -> None:
        # merged-a, lost, idle-pushed, parked, and live/live-twin as one.
        assert branch_sweep.open_work_count(inventory) == 5

    def test_unmeasured_dormant_containment_is_dormant_not_nowhere(self) -> None:
        unknown = _record("x", BranchState.DORMANT, dormancy_stage=DormancyStage.ADVISORY)
        groups = branch_sweep.group_records(_inventory(unknown))
        assert groups.contained_nowhere == ()
        assert [r.name for r in groups.dormant] == ["x"]


class TestEffectiveCap:
    def test_explicit_key_wins(self) -> None:
        config = BranchesConfig.model_validate({"wip": {"cap": 4}})
        assert branch_sweep.effective_wip_cap(config, {"max_open_branches": 2}) == 4

    def test_legacy_option_is_the_fallback(self) -> None:
        assert branch_sweep.effective_wip_cap(BranchesConfig(), {"max_open_branches": 2}) == 2

    def test_model_default_without_either(self) -> None:
        assert branch_sweep.effective_wip_cap(BranchesConfig(), {}) == 10

    def test_deprecation_names_only_unmigrated_options(self) -> None:
        config = BranchesConfig.model_validate({"wip": {"cap": 4}})
        line = branch_sweep.deprecation_line(
            config, {"max_open_branches": 2, "behind_main_threshold": 9}
        )
        assert line is not None
        assert "behind_main_threshold" in line
        assert "branches.sweep.behind_threshold" in line
        assert "max_open_branches" not in line

    def test_no_deprecation_without_old_options(self) -> None:
        assert branch_sweep.deprecation_line(BranchesConfig(), {}) is None


class TestReport:
    def test_actionable_groups_first_and_in_order(self, inventory: BranchInventory) -> None:
        text = "\n".join(branch_sweep.render_report(inventory, _CONFIG, cap=10, show_all=False))
        order = [
            text.index("CONTAINED NOWHERE"),
            text.index("Merged, not deleted"),
            text.index("Dormant"),
            text.index("Live work"),
            text.index("Parked"),
        ]
        assert order == sorted(order)
        assert "git push -u origin lost" in text
        assert "bin/hooks-daemon delete-branch merged-a" in text
        assert "branch -D" not in text
        assert "Open work: 5 of 10 (branches.wip.cap)" in text

    def test_exempt_only_with_all(self, inventory: BranchInventory) -> None:
        plain = "\n".join(branch_sweep.render_report(inventory, _CONFIG, cap=10, show_all=False))
        full = "\n".join(branch_sweep.render_report(inventory, _CONFIG, cap=10, show_all=True))
        assert "users/alice" not in plain
        assert "users/alice" in full

    def test_unclassified_shows_its_reason(self) -> None:
        record = _record("u", BranchState.UNCLASSIFIED, reason="budget ran out")
        text = "\n".join(branch_sweep.render_report(_inventory(record), _CONFIG, cap=10))
        assert "Not yet classified" in text
        assert "budget ran out" in text

    def test_merged_into_a_line_names_the_proving_ref(self) -> None:
        record = _record(
            "f", BranchState.MERGED_LINE, merged_into="release/x", proven_by="origin/release/x"
        )
        text = "\n".join(branch_sweep.render_report(_inventory(record), _CONFIG, cap=10))
        assert "bin/hooks-daemon delete-branch f --protected-ref origin/release/x" in text

    def test_remote_only_merged_branch_gets_no_local_delete(self) -> None:
        record = _record(
            "r",
            BranchState.MERGED_DEFAULT,
            local_tip=None,
            remote_tip="b" * 40,
            merged_into="main",
            proven_by="main",
        )
        text = "\n".join(branch_sweep.render_report(_inventory(record), _CONFIG, cap=10))
        assert "delete-branch r" not in text
        assert "push main first" in text

    def test_unresolved_default_is_reported(self) -> None:
        inventory = BranchInventory(default_branch=None, default_ref=None, records={})
        text = "\n".join(branch_sweep.render_report(inventory, _CONFIG, cap=10))
        assert "default branch could not be resolved" in text


class TestJson:
    def test_full_records_with_stable_keys(self, inventory: BranchInventory) -> None:
        document = json.loads(json.dumps(branch_sweep.report_json(inventory, cap=10)))
        assert document["open_work"] == 5
        assert document["cap"] == 10
        assert document["default_branch"] == "main"
        by_name = {b["name"]: b for b in document["branches"]}
        assert set(by_name) >= {"main", "users/alice", "lost", "merged-a"}
        lost = by_name["lost"]
        assert set(lost) == set(branch_sweep.JSON_RECORD_KEYS)
        assert lost["state"] == "dormant"
        assert lost["containment"] == Containment.NOWHERE.value
        assert lost["group"] == "contained-nowhere"
        assert by_name["live"]["same_tip_as"] == ["live-twin"]


class TestSessionSummary:
    def test_silent_when_clean(self) -> None:
        clean = _inventory(_record("w", BranchState.LIVE))
        assert branch_sweep.session_summary(clean, _CONFIG, cap=10, new_session=True) == []

    def test_new_session_reports_everything(self, inventory: BranchInventory) -> None:
        text = "\n".join(branch_sweep.session_summary(inventory, _CONFIG, cap=10, new_session=True))
        assert "CONTAINED NOWHERE: lost" in text
        assert "git push -u origin lost" in text
        assert "1 merged branch" in text
        assert "bin/hooks-daemon branch-sweep" in text
        assert "Dormant: idle-pushed: advisory, 9d old" in text

    def test_resume_reports_only_contained_nowhere(self, inventory: BranchInventory) -> None:
        text = "\n".join(
            branch_sweep.session_summary(inventory, _CONFIG, cap=10, new_session=False)
        )
        assert "CONTAINED NOWHERE: lost" in text
        assert "idle-pushed" not in text
        assert "merged branch" not in text

    def test_over_cap_is_reported(self, inventory: BranchInventory) -> None:
        text = "\n".join(branch_sweep.session_summary(inventory, _CONFIG, cap=5, new_session=True))
        assert "Open work: 5 of 5" in text

    def test_output_is_capped(self) -> None:
        many = [
            _record(
                f"n{i:02d}",
                BranchState.DORMANT,
                dormancy_stage=DormancyStage.ADVISORY,
                containment=Containment.NOWHERE,
                age_days=8.0,
            )
            for i in range(30)
        ]
        lines = branch_sweep.session_summary(_inventory(*many), _CONFIG, cap=100, new_session=True)
        assert len(lines) <= branch_sweep.MAX_SUMMARY_LINES + 3
        overflow = [line for line in lines if "more: run `bin/hooks-daemon branch-sweep`" in line]
        assert overflow == [
            f"  and {30 - branch_sweep.MAX_SUMMARY_LINES} more: run "
            "`bin/hooks-daemon branch-sweep`"
        ]

    def test_deprecation_line_alone_is_not_silent(self) -> None:
        clean = _inventory(_record("w", BranchState.LIVE))
        lines = branch_sweep.session_summary(
            clean, _CONFIG, cap=10, new_session=True, deprecation="old option"
        )
        assert lines == ["old option"]


class TestBehindDefault:
    """The far-behind-default line, restored (Plan 00558 Task 3.3)."""

    def test_a_work_branch_past_the_threshold_is_named_on_a_new_session(self) -> None:
        far = _inventory(
            _record("w", BranchState.LIVE, behind=80), _record("ok", BranchState.LIVE, behind=3)
        )
        lines = branch_sweep.session_summary(far, _CONFIG, cap=10, new_session=True)
        assert [line for line in lines if "behind" in line] == [
            "Behind main: w is 80 commits behind (branches.sweep.behind_threshold: 50); "
            "rebase or merge main into it, or delete it if it is done."
        ]

    def test_not_on_resume(self) -> None:
        far = _inventory(_record("w", BranchState.LIVE, behind=80))
        assert branch_sweep.session_summary(far, _CONFIG, cap=10, new_session=False) == []

    def test_the_threshold_is_exclusive_and_configurable(self) -> None:
        far = _inventory(_record("w", BranchState.LIVE, behind=50))
        assert branch_sweep.session_summary(far, _CONFIG, cap=10, new_session=True) == []
        lines = branch_sweep.session_summary(
            far, _CONFIG, cap=10, new_session=True, behind_threshold=49
        )
        assert any("w is 50 commits behind" in line for line in lines)

    def test_merged_never_work_and_unknown_are_not_named(self) -> None:
        records = (
            _record("done", BranchState.MERGED_DEFAULT, behind=500),
            _record("users/x", BranchState.EXEMPT, behind=500),
            _record("unknown", BranchState.LIVE, behind=None),
        )
        lines = branch_sweep.session_summary(
            _inventory(*records), _CONFIG, cap=10, new_session=True
        )
        assert not any("commits behind" in line for line in lines)

    def test_behind_lines_share_the_line_cap(self) -> None:
        many = [_record(f"b{i:02d}", BranchState.LIVE, behind=99) for i in range(30)]
        lines = branch_sweep.session_summary(_inventory(*many), _CONFIG, cap=100, new_session=True)
        assert sum("commits behind" in line for line in lines) == branch_sweep.MAX_SUMMARY_LINES

    def test_the_legacy_option_is_the_fallback(self) -> None:
        assert branch_sweep.effective_behind_threshold(BranchesConfig(), {}) == 50
        legacy = {"behind_main_threshold": 7}
        assert branch_sweep.effective_behind_threshold(BranchesConfig(), legacy) == 7
        explicit = BranchesConfig.model_validate({"sweep": {"behind_threshold": 9}})
        assert branch_sweep.effective_behind_threshold(explicit, legacy) == 9
