"""The CI shard legs (Plan 00572 Task 2.1): one declaration, two workflows.

``scripts/ci/shard_legs.yaml`` names, per profile, the runner legs the test
suite is split over. ``.github/workflows/test-shards.yml`` turns a profile into
its job matrix, and both ``release-gate.yml`` and ``qa.yml`` call that
workflow. These tests pin the rules every profile must keep: each Python runs
every shard of ``scripts/qa/test_shards.yaml`` exactly once, and coverage is
one Python's legs, all of them.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _REPO_ROOT / "scripts" / "ci" / "shard_legs.py"
_LEGS = _REPO_ROOT / "scripts" / "ci" / "shard_legs.yaml"
_SHARDS = _REPO_ROOT / "scripts" / "qa" / "test_shards.yaml"
_REUSABLE = _REPO_ROOT / ".github" / "workflows" / "test-shards.yml"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("shard_legs", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["shard_legs"] = module
    spec.loader.exec_module(module)
    return module


shard_legs = _load()

_NAMES = ["a", "b", "c"]


def _leg(name: str, python: str, shards: list[str], **extra: Any) -> dict[str, Any]:
    return {
        "name": name,
        "python": python,
        "shards": shards,
        "coverage": extra.get("coverage", False),
        "daemon": extra.get("daemon", False),
    }


class TestTheCommittedDeclaration:
    def test_every_profile_passes_the_check(self) -> None:
        profiles = shard_legs.load_profiles(_LEGS)
        names = shard_legs.load_shard_names(_SHARDS)
        problems = [
            p for name, legs in profiles.items() for p in shard_legs.check(name, legs, names)
        ]
        assert problems == []

    def test_both_callers_profiles_exist(self) -> None:
        assert {"full", "fallback"} <= set(shard_legs.load_profiles(_LEGS))

    def test_the_full_profile_collects_coverage_and_the_fallback_does_not(self) -> None:
        profiles = shard_legs.load_profiles(_LEGS)
        assert shard_legs.coverage_shards(profiles["full"])
        assert shard_legs.coverage_shards(profiles["fallback"]) == []

    def test_the_full_profile_runs_every_python_the_project_supports(self) -> None:
        pythons = {leg["python"] for leg in shard_legs.load_profiles(_LEGS)["full"]}
        assert pythons == {"3.11", "3.12", "3.13"}

    def test_the_check_command_passes(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert shard_legs.main(["--check"]) == 0


class TestTheCheck:
    def test_a_python_missing_a_shard_is_named(self) -> None:
        legs = [_leg("x", "3.11", ["a", "b"])]
        problems = shard_legs.check("p", legs, _NAMES)
        assert any("3.11" in p and "c" in p for p in problems)

    def test_a_shard_run_twice_is_named(self) -> None:
        legs = [_leg("x", "3.11", ["a", "b", "c"]), _leg("y", "3.11", ["a"])]
        assert shard_legs.check("p", legs, _NAMES)

    def test_an_unknown_shard_is_named(self) -> None:
        legs = [_leg("x", "3.11", ["a", "b", "c", "zz"])]
        assert any("zz" in p for p in shard_legs.check("p", legs, _NAMES))

    def test_coverage_on_two_pythons_is_refused(self) -> None:
        legs = [
            _leg("x", "3.11", _NAMES, coverage=True),
            _leg("y", "3.12", _NAMES, coverage=True),
        ]
        assert shard_legs.check("p", legs, _NAMES)

    def test_a_coverage_python_with_a_leg_that_skips_coverage_is_refused(self) -> None:
        legs = [_leg("x", "3.13", ["a", "b"], coverage=True), _leg("y", "3.13", ["c"])]
        assert shard_legs.check("p", legs, _NAMES)

    def test_duplicate_leg_names_are_refused(self) -> None:
        legs = [_leg("x", "3.11", ["a", "b"]), _leg("x", "3.11", ["c"])]
        assert shard_legs.check("p", legs, _NAMES)

    def test_an_empty_profile_is_refused(self) -> None:
        assert shard_legs.check("p", [], _NAMES)

    def test_a_sound_profile_passes(self) -> None:
        legs = [
            _leg("x", "3.11", ["a", "b"]),
            _leg("y", "3.11", ["c"], daemon=True),
            _leg("z", "3.13", _NAMES, coverage=True),
        ]
        assert shard_legs.check("p", legs, _NAMES) == []


class TestTheLoader:
    def test_an_unknown_key_is_refused(self, tmp_path: Path) -> None:
        path = tmp_path / "legs.yaml"
        bad = _leg("x", "3.11", _NAMES) | {"colour": "red"}
        path.write_text(yaml.safe_dump({"profiles": {"p": [bad]}}))
        with pytest.raises(shard_legs.LegsError, match="colour"):
            shard_legs.load_profiles(path)

    def test_a_missing_key_is_refused(self, tmp_path: Path) -> None:
        path = tmp_path / "legs.yaml"
        bad = _leg("x", "3.11", _NAMES)
        del bad["daemon"]
        path.write_text(yaml.safe_dump({"profiles": {"p": [bad]}}))
        with pytest.raises(shard_legs.LegsError, match="daemon"):
            shard_legs.load_profiles(path)

    def test_a_numeric_python_is_refused(self, tmp_path: Path) -> None:
        """YAML reads 3.10 as the float 3.1, so a version must be quoted."""
        path = tmp_path / "legs.yaml"
        path.write_text(
            "profiles:\n  p:\n    - {name: x, python: 3.11, shards: [a], coverage: false, daemon: false}\n"
        )
        with pytest.raises(shard_legs.LegsError, match="python"):
            shard_legs.load_profiles(path)


class TestTheWorkflowOutputs:
    def test_the_matrix_carries_each_leg_with_space_joined_shards(self) -> None:
        legs = [_leg("x", "3.11", ["a", "b"], daemon=True)]
        matrix = shard_legs.matrix_for(legs)
        assert matrix == {
            "include": [
                {"name": "x", "python": "3.11", "shards": "a b", "coverage": False, "daemon": True}
            ]
        }

    def test_coverage_shards_are_every_coverage_legs_shards_in_order(self) -> None:
        legs = [
            _leg("x", "3.11", _NAMES),
            _leg("y", "3.13", ["b"], coverage=True),
            _leg("z", "3.13", ["a", "c"], coverage=True),
        ]
        assert shard_legs.coverage_shards(legs) == ["b", "a", "c"]

    def test_the_profile_command_prints_github_output_lines(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert shard_legs.main(["--profile", "full"]) == 0
        lines = dict(line.split("=", 1) for line in capsys.readouterr().out.splitlines())
        assert set(lines) == {"matrix", "coverage-shards"}
        assert json.loads(lines["matrix"])["include"]
        assert lines["coverage-shards"].split()

    def test_an_unknown_profile_fails(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert shard_legs.main(["--profile", "nope"]) != 0


class TestTheReusableWorkflowReadsThePlan:
    """The workflow must take its matrix and coverage list from this script."""

    def test_the_tests_matrix_comes_from_the_plan_job(self) -> None:
        workflow = yaml.safe_load(_REUSABLE.read_text(encoding="utf-8"))
        matrix = workflow["jobs"]["tests"]["strategy"]["matrix"]
        assert "needs.plan.outputs.matrix" in str(matrix)
        plan_runs = "\n".join(s.get("run", "") for s in workflow["jobs"]["plan"]["steps"])
        assert "scripts/ci/shard_legs.py" in plan_runs

    def test_the_coverage_job_combines_the_plans_shards(self) -> None:
        workflow = yaml.safe_load(_REUSABLE.read_text(encoding="utf-8"))
        assert "needs.plan.outputs.coverage-shards" in str(workflow["jobs"]["coverage"])
