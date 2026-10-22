"""``run_test_matrix.py --shard``: one CI job runs a chosen slice of the suite (Plan 00476 Task 2.1).

The release-gate workflow splits the ``tests`` stage over runners, one job per
(Python, shard group). Each job selects its shards by name and runs them under
its own interpreter only; ``--coverage`` makes it the coverage leg, keeping each
shard's coverage data for a later combine instead of judging a partial total.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.qa.suite_shards import Shard

PROJECT_ROOT = Path(__file__).resolve().parents[3]
MATRIX_SCRIPT = PROJECT_ROOT / "scripts" / "qa" / "run_test_matrix.py"

_SHARDS = [
    Shard("u-one", "unit", ("tests/unit/one",)),
    Shard("u-two", "unit", ("tests/unit/two",)),
    Shard("r-one", "rest", ("tests/integration",)),
]


def _load_matrix() -> Any:
    spec = importlib.util.spec_from_file_location(
        "run_test_matrix_shard_selection_under_test", MATRIX_SCRIPT
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {MATRIX_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


matrix = _load_matrix()


class TestArguments:
    def test_no_arguments_selects_nothing(self) -> None:
        parsed = matrix.parse_matrix_args([])
        assert parsed == matrix.MatrixArgs(resume=False, shards=(), coverage=False)

    def test_shards_coverage_and_resume_are_read(self) -> None:
        parsed = matrix.parse_matrix_args(
            ["--shard", "u-one", "--resume", "--shard", "r-one", "--coverage"]
        )
        assert parsed == matrix.MatrixArgs(resume=True, shards=("u-one", "r-one"), coverage=True)

    def test_coverage_without_a_shard_is_refused(self) -> None:
        with pytest.raises(SystemExit, match="--coverage"):
            matrix.parse_matrix_args(["--coverage"])

    def test_shard_without_a_name_is_refused(self) -> None:
        with pytest.raises(SystemExit, match="--shard"):
            matrix.parse_matrix_args(["--shard"])

    def test_an_unknown_argument_is_refused(self) -> None:
        with pytest.raises(SystemExit, match="--bogus"):
            matrix.parse_matrix_args(["--bogus"])

    def test_resume_requested_still_reads_resume(self) -> None:
        assert matrix.resume_requested(["--shard", "u-one", "--resume"]) is True


class TestPlanSelected:
    def test_unit_shards_with_coverage_are_one_primary_parallel_leg(self) -> None:
        plan = matrix.plan_selected("3.13", _SHARDS, ("u-two", "u-one"), coverage=True)
        assert plan == [
            matrix.PlannedRun(
                "3.13", "unit", matrix.PHASE_PARALLEL, True, shards=("u-one", "u-two")
            )
        ]

    def test_a_rest_shard_without_coverage_is_a_serial_leg_on_this_interpreter(self) -> None:
        plan = matrix.plan_selected("3.11", _SHARDS, ("r-one",), coverage=False)
        assert plan == [
            matrix.PlannedRun("3.11", "rest", matrix.PHASE_SERIAL, False, shards=("r-one",))
        ]

    def test_mixed_scopes_are_a_full_serial_leg(self) -> None:
        plan = matrix.plan_selected("3.12", _SHARDS, ("r-one", "u-one"), coverage=False)
        assert plan == [
            matrix.PlannedRun("3.12", "full", matrix.PHASE_SERIAL, False, shards=("u-one", "r-one"))
        ]

    def test_an_unknown_shard_name_is_refused_by_name(self) -> None:
        with pytest.raises(matrix.MatrixError, match="nope"):
            matrix.plan_selected("3.13", _SHARDS, ("u-one", "nope"), coverage=False)


class TestSelectedPrimaryReport:
    def test_a_coverage_slice_reports_its_shards_tests_and_no_coverage(
        self, tmp_path: Path
    ) -> None:
        report = tmp_path / "tests-shard-u-one.json"
        report.write_text('{"tests": [{"name": "t", "outcome": "passed"}]}', encoding="utf-8")
        outcome = matrix.RunOutcome(0, {"passed_all": True}, [], report, {})
        run = matrix.PlannedRun("3.13", "unit", matrix.PHASE_PARALLEL, True, ("u-one",))
        result = matrix.RunResult(
            run, outcome, 1.0, None, shards=(matrix.ShardResult("u-one", outcome, 1.0, False),)
        )
        assert matrix.selected_primary_report([result]) == {
            "tool": "pytest",
            "tests": [{"name": "t", "outcome": "passed"}],
            "coverage": {},
        }

    def test_a_slice_without_coverage_has_no_primary_report(self) -> None:
        assert matrix.selected_primary_report([]) == {}


class TestThisInterpreterOnly:
    def test_the_running_interpreter_serves_its_own_version(self) -> None:
        provision = matrix.this_interpreter_only("3.13")
        assert provision("3.13") == Path(sys.executable)

    def test_any_other_version_is_a_provision_error(self) -> None:
        provision = matrix.this_interpreter_only("3.13")
        with pytest.raises(matrix.ProvisionError, match="3.11"):
            provision("3.11")
