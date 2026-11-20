"""Stacked pull-request branches count once against the open cap (Plan 00594 Task 4.6).

DESIGN.md section 7.1: a stack is a chain of this owner's open branches where each
tip is a strict ancestor of the next. It counts 1 against ``branches.wip.cap`` up to
``branches.wip.stack_max_depth`` links, and each link past that counts 1 more. A
fork ends the chain: each arm is its own stream and the shared base counts with the
first arm. Grouping reads tips only. Parked, merged, park-carried and unowned
branches are classified before grouping. The sweep, the preflight, the creation
guard and the ladder read one count from one function.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.config.models import BranchesConfig, BranchWipConfig
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import (
    branch_creation,
    branch_inventory,
    branch_ladder,
    branch_stacks,
    branch_sweep,
)
from claude_code_hooks_daemon.core.branch_inventory import Pool
from claude_code_hooks_daemon.core.branch_stacks import WorkUnit
from tests.conftest import HERMETIC_GIT_EMAIL

# --- pure grouping -----------------------------------------------------------------------


def _units(*names: str) -> list[WorkUnit]:
    return [WorkUnit(name, frozenset({f"tip-{name}"})) for name in names]


def _chain_ancestry(*names: str) -> dict[str, frozenset[str]]:
    """Each name's tip has every earlier name's tip as a strict ancestor."""
    return {f"tip-{name}": frozenset(f"tip-{n}" for n in names[:i]) for i, name in enumerate(names)}


class TestStackCharge:
    @pytest.mark.parametrize(
        ("depth", "max_depth", "charge"),
        [(1, 5, 1), (2, 5, 1), (5, 5, 1), (6, 5, 2), (7, 5, 3), (3, 1, 3)],
    )
    def test_charge_is_one_up_to_the_cap_then_one_per_extra_link(
        self, depth: int, max_depth: int, charge: int
    ) -> None:
        assert branch_stacks.stack_charge(depth, max_depth) == charge

    def test_a_depth_below_one_is_refused(self) -> None:
        with pytest.raises(ValueError):
            branch_stacks.stack_charge(0, 5)


class TestGroupStacks:
    def test_a_five_deep_chain_is_one_stack_bottom_first(self) -> None:
        names = ("s1", "s2", "s3", "s4", "s5")
        stacks = branch_stacks.group_stacks(_units(*names), _chain_ancestry(*names))
        assert [s.links for s in stacks] == [names]
        assert stacks[0].bottom == "s1"
        assert stacks[0].top == "s5"
        assert stacks[0].depth == 5
        assert branch_stacks.open_work_charge(stacks, 5) == 1

    def test_unrelated_branches_are_each_their_own_stream(self) -> None:
        stacks = branch_stacks.group_stacks(_units("a", "b", "c"), {})
        assert sorted(s.links for s in stacks) == [("a",), ("b",), ("c",)]
        assert branch_stacks.open_work_charge(stacks, 5) == 3

    def test_unknown_ancestry_groups_nothing(self) -> None:
        names = ("s1", "s2", "s3")
        stacks = branch_stacks.group_stacks(_units(*names), None)
        assert branch_stacks.open_work_charge(stacks, 5) == 3

    def test_a_too_deep_stack_is_pressed_one_per_extra_link(self) -> None:
        names = tuple(f"s{i}" for i in range(1, 8))
        stacks = branch_stacks.group_stacks(_units(*names), _chain_ancestry(*names))
        assert len(stacks) == 1
        assert branch_stacks.open_work_charge(stacks, 5) == 3

    def test_a_fork_ends_the_chain_and_the_base_goes_with_the_first_arm(self) -> None:
        ancestry = {
            "tip-base": frozenset(),
            "tip-arm-a": frozenset({"tip-base"}),
            "tip-arm-a2": frozenset({"tip-base", "tip-arm-a"}),
            "tip-arm-b": frozenset({"tip-base"}),
        }
        stacks = branch_stacks.group_stacks(_units("base", "arm-a", "arm-a2", "arm-b"), ancestry)
        assert sorted(s.links for s in stacks) == [("arm-b",), ("base", "arm-a", "arm-a2")]
        assert branch_stacks.open_work_charge(stacks, 5) == 2

    def test_a_unit_is_linked_to_its_nearest_descendant_not_a_distant_one(self) -> None:
        names = ("s1", "s2", "s3")
        stacks = branch_stacks.group_stacks(_units(*reversed(names)), _chain_ancestry(*names))
        assert [s.links for s in stacks] == [names]

    def test_mutual_ancestry_between_two_units_groups_neither(self) -> None:
        units = [
            WorkUnit("a", frozenset({"a1", "a2"})),
            WorkUnit("b", frozenset({"b1", "b2"})),
        ]
        ancestry = {"a2": frozenset({"b1"}), "b2": frozenset({"a1"})}
        stacks = branch_stacks.group_stacks(units, ancestry)
        assert sorted(s.links for s in stacks) == [("a",), ("b",)]

    def test_every_unit_appears_in_exactly_one_stream(self) -> None:
        names = ("s1", "s2", "s3", "s4")
        ancestry = _chain_ancestry(*names)
        ancestry["tip-x"] = frozenset({"tip-s1"})
        stacks = branch_stacks.group_stacks(_units(*names, "x"), ancestry)
        seen = [name for stack in stacks for name in stack.links]
        assert sorted(seen) == sorted([*names, "x"])


# --- real repositories ----------------------------------------------------------------


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ},
    ).stdout


def _commit(repo: Path, filename: str) -> None:
    (repo / filename).write_text(f"{filename}\n", encoding="utf-8")
    _git(repo, "add", filename)
    _git(repo, "commit", "-q", "-m", f"Add {filename}")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    bare = tmp_path / "remote.git"
    _git(tmp_path, "init", "--quiet", "--bare", "-b", "main", str(bare))
    path = tmp_path / "repo"
    path.mkdir()
    _git(path, "init", "-q", "-b", "main")
    _git(path, "config", "user.email", HERMETIC_GIT_EMAIL)
    _git(path, "config", "user.name", "t")
    _commit(path, "base.txt")
    _git(path, "remote", "add", "origin", str(bare))
    _git(path, "push", "-q", "origin", "main")
    _git(path, "remote", "set-head", "origin", "main")
    return path


def _stack(repo: Path, prefix: str, depth: int, *, push: bool = False) -> list[str]:
    """``depth`` branches, each one commit on top of the previous, starting from main."""
    names = [f"{prefix}-{i}" for i in range(1, depth + 1)]
    base = "main"
    for name in names:
        _git(repo, "checkout", "-q", "-b", name, base)
        _commit(repo, f"{name}.txt")
        if push:
            _git(repo, "push", "-q", "-u", "origin", name)
        base = name
    _git(repo, "checkout", "-q", "main")
    return names


def _single(repo: Path, name: str) -> None:
    _stack(repo, name, 1)


def _config(cap: int, *, max_depth: int = 5) -> BranchesConfig:
    return BranchesConfig(
        default="main",
        wip=BranchWipConfig(
            cap=cap, count_remote=True, creation_grace=0, stack_max_depth=max_depth
        ),
    )


def _counts(repo: Path, config: BranchesConfig) -> dict[str, int]:
    """The open-work count as each consumer reads it."""
    inventory = branch_inventory.build_inventory(repo, config)
    ladder = {
        p.pool: p.count
        for p in branch_ladder.pool_pressures(repo, config, {})
        if p.pool == Pool.OPEN
    }
    return {
        "sweep": branch_sweep.pool_count(inventory, Pool.OPEN),
        "stop": branch_sweep.open_work_count(inventory),
        "guard": branch_creation.open_work_charge(repo, config),
        "ladder": ladder.get(Pool.OPEN, -1),
    }


class TestOneCount:
    def test_config_default_depth_is_five(self) -> None:
        assert BranchWipConfig().stack_max_depth == 5

    def test_a_five_deep_stack_and_two_singles_count_three_everywhere(self, repo: Path) -> None:
        _stack(repo, "stack", 5)
        _single(repo, "solo-a")
        _single(repo, "solo-b")
        # cap 3: the ladder reports the open pool at 100 percent, so every consumer speaks.
        counts = _counts(repo, _config(cap=3))
        assert counts == {"sweep": 3, "stop": 3, "guard": 3, "ladder": 3}

    def test_a_pushed_stack_groups_from_remote_tips_alone(self, repo: Path) -> None:
        names = _stack(repo, "pr", 3, push=True)
        for name in names:
            _git(repo, "branch", "-q", "-D", name)
        _single(repo, "solo")
        counts = _counts(repo, _config(cap=2))
        assert counts == {"sweep": 2, "stop": 2, "guard": 2, "ladder": 2}

    def test_a_seven_deep_stack_counts_three_past_a_depth_of_five(self, repo: Path) -> None:
        _stack(repo, "deep", 7)
        counts = _counts(repo, _config(cap=3))
        assert counts == {"sweep": 3, "stop": 3, "guard": 3, "ladder": 3}

    def test_a_fork_counts_each_arm(self, repo: Path) -> None:
        _stack(repo, "base", 1)
        _git(repo, "checkout", "-q", "-b", "arm-a", "base-1")
        _commit(repo, "arm-a.txt")
        _git(repo, "checkout", "-q", "-b", "arm-b", "base-1")
        _commit(repo, "arm-b.txt")
        _git(repo, "checkout", "-q", "main")
        counts = _counts(repo, _config(cap=2))
        assert counts == {"sweep": 2, "stop": 2, "guard": 2, "ladder": 2}

    def test_a_merged_bottom_link_does_not_join_the_stack(self, repo: Path) -> None:
        names = _stack(repo, "landed", 3)
        _git(repo, "merge", "-q", "--no-ff", "-m", "Merge landed-1", names[0])
        _git(repo, "push", "-q", "origin", "main")
        _git(repo, "fetch", "-q", "origin")
        inventory = branch_inventory.build_inventory(repo, _config(cap=1))
        assert inventory.records[names[0]].state in {
            branch_inventory.BranchState.MERGED_DEFAULT,
        }
        assert branch_sweep.pool_count(inventory, Pool.OPEN) == 1
        assert branch_creation.open_work_charge(repo, _config(cap=1)) == 1


class TestCreationGuard:
    def test_a_five_deep_stack_no_longer_fills_a_cap_of_three(self, repo: Path) -> None:
        _stack(repo, "stack", 5)
        _single(repo, "solo")
        report = branch_creation.creation_report(repo, _config(cap=3), "brand-new")
        assert report.may_create
        assert not report.blockers

    def test_the_cap_still_refuses_when_the_streams_fill_it(self, repo: Path) -> None:
        _stack(repo, "stack", 5)
        _single(repo, "solo")
        report = branch_creation.creation_report(repo, _config(cap=2), "brand-new")
        rules = {str(s.rule_id) for s in report.blockers}
        assert str(RuleID.BRANCH_WIP_CAP) in rules
        assert not report.may_create

    def test_the_preflight_prints_a_stack_as_one_line_with_its_bottom(self, repo: Path) -> None:
        _stack(repo, "stack", 5)
        _single(repo, "solo")
        report = branch_creation.creation_report(repo, _config(cap=2), "brand-new")
        lines = branch_creation.render_creation_report(report)
        assert any(line.startswith("Open work branches: 2 (cap 2;") for line in lines)
        stack_lines = [line for line in lines if "stack-" in line]
        assert len(stack_lines) == 1
        assert "stack of 5" in stack_lines[0]
        assert "bottom stack-1" in stack_lines[0]
        assert "land the bottom first" in stack_lines[0]
        assert any("solo-1" in line for line in lines)


class TestSweepReport:
    def test_the_sweep_prints_a_stack_as_one_line_naming_depth_and_bottom(self, repo: Path) -> None:
        _stack(repo, "stack", 3)
        _single(repo, "solo")
        config = _config(cap=10)
        inventory = branch_inventory.build_inventory(repo, config)
        lines = branch_sweep.render_report(inventory, config, cap=10)
        stack_lines = [line for line in lines if "stack-" in line]
        assert len(stack_lines) == 1
        assert "stack of 3" in stack_lines[0]
        assert "bottom stack-1" in stack_lines[0]
        assert "land the bottom first" in stack_lines[0]
        assert "Open work: 2 of 10 (branches.wip.cap)" in lines

    def test_the_json_open_work_is_the_shared_count(self, repo: Path) -> None:
        _stack(repo, "stack", 4)
        config = _config(cap=10)
        inventory = branch_inventory.build_inventory(repo, config)
        document = branch_sweep.report_json(inventory, cap=10, config=config)
        assert document["open_work"] == 1
        assert document["pools"]["open"]["count"] == 1


class TestReadAncestry:
    def test_reads_strict_ancestors_among_the_given_tips(self, repo: Path) -> None:
        names = _stack(repo, "s", 3)
        tips = {name: _git(repo, "rev-parse", name).strip() for name in names}
        ancestry = branch_stacks.read_tip_ancestry(
            repo, frozenset(tips.values()), ("refs/heads/main",)
        )
        assert ancestry is not None
        assert ancestry[tips["s-1"]] == frozenset()
        assert ancestry[tips["s-2"]] == frozenset({tips["s-1"]})
        assert ancestry[tips["s-3"]] == frozenset({tips["s-1"], tips["s-2"]})

    def test_no_exclusion_is_unknown_not_a_whole_history_walk(self, repo: Path) -> None:
        names = _stack(repo, "s", 2)
        tips = frozenset(_git(repo, "rev-parse", name).strip() for name in names)
        assert branch_stacks.read_tip_ancestry(repo, tips, ()) is None

    def test_a_git_failure_is_unknown(self, tmp_path: Path) -> None:
        assert branch_stacks.read_tip_ancestry(tmp_path, frozenset({"0" * 40}), ("main",)) is None
