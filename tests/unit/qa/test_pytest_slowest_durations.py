"""Tests for recording every pytest leg's slowest tests (Plan 00500 Task 1.3).

The gate's `tests` step is about 90% of its wall time and nothing recorded which
tests make it so. Every leg now passes ``--durations``; the parser reads the
"slowest durations" section back out of the captured console output (no
``pytest-json-report``, which this project does not install) and the records
are stored in ``tests.json`` per leg and shown, top 10, in the tests summary.

The captured output below is REAL pytest output (``pytest --durations=6
--durations-min=0.0 --color=yes``), colour escapes included.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from claude_code_hooks_daemon.qa.pytest_text_report import (
    SLOWEST_DURATIONS_ARGS,
    parse_slowest_durations,
)

if TYPE_CHECKING:
    import types

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = PROJECT_ROOT / "scripts" / "qa"
_TEST_PATH = "tests/unit/qa/test_pytest_text_report.py"

_REAL_OUTPUT = (
    "\x1b[32m.\x1b[0m\x1b[32m.\x1b[0m\x1b[32m                         [100%]\x1b[0m\n"
    "\n"
    "============================= slowest 6 durations ==============================\n"
    f"12.50s call     {_TEST_PATH}::TestA::test_slow_call\n"
    f"3.01s setup    {_TEST_PATH}::TestB::test_slow_setup\n"
    f"0.01s teardown {_TEST_PATH}::TestC::test_param[a b-1]\n"
    f"0.01s call     {_TEST_PATH}::TestD::test_fast\n"
    "(2 durations < 0.005s hidden.  Use -vv to show these durations.)\n"
    "\x1b[32m============================== \x1b[32m\x1b[1m36 passed\x1b[0m\x1b[32m in 0.41s"
    "\x1b[0m\x1b[32m ==============================\x1b[0m\n"
)


def _load(name: str, path: Path) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class TestParseSlowestDurations:
    def test_every_listed_duration_becomes_a_record(self) -> None:
        records = parse_slowest_durations(_REAL_OUTPUT)

        assert records == [
            {"nodeid": f"{_TEST_PATH}::TestA::test_slow_call", "phase": "call", "seconds": 12.5},
            {
                "nodeid": f"{_TEST_PATH}::TestB::test_slow_setup",
                "phase": "setup",
                "seconds": 3.01,
            },
            {
                "nodeid": f"{_TEST_PATH}::TestC::test_param[a b-1]",
                "phase": "teardown",
                "seconds": 0.01,
            },
            {"nodeid": f"{_TEST_PATH}::TestD::test_fast", "phase": "call", "seconds": 0.01},
        ]

    def test_the_hidden_footer_and_totals_line_are_not_records(self) -> None:
        records = parse_slowest_durations(_REAL_OUTPUT)

        assert len(records) == 4

    def test_colour_around_the_section_is_tolerated(self) -> None:
        coloured = _REAL_OUTPUT.replace("=== slowest 6", "=== \x1b[1mslowest 6").replace(
            "durations ===", "durations\x1b[0m ==="
        )

        assert len(parse_slowest_durations(coloured)) == 4

    def test_output_with_no_section_gives_no_records(self) -> None:
        assert parse_slowest_durations("36 passed in 0.41s\n") == []
        assert parse_slowest_durations("") == []

    def test_a_duration_shaped_line_outside_the_section_is_ignored(self) -> None:
        """Captured streams carry subprocess logs; only pytest's own section counts."""
        noise = "9.99s call     fake/test_noise.py::test_x\n"

        assert parse_slowest_durations(noise + _REAL_OUTPUT)[0]["seconds"] == 12.5
        assert parse_slowest_durations(noise) == []

    def test_records_after_the_section_ends_are_ignored(self) -> None:
        after = _REAL_OUTPUT + "8.00s call     fake/test_after.py::test_y\n"

        assert len(parse_slowest_durations(after)) == 4


class TestEveryLegAsksPytestForDurations:
    def test_the_shared_arguments_are_durations_with_a_floor(self) -> None:
        assert SLOWEST_DURATIONS_ARGS == ("--durations=50", "--durations-min=1.0")

    def test_an_extra_interpreters_argv_carries_them(self, tmp_path: Path) -> None:
        matrix = _load("matrix_for_durations", SCRIPTS_DIR / "run_test_matrix.py")
        run = matrix.PlannedRun("3.13", "unit", 1, False)

        argv = matrix.extra_pytest_argv(Path("/fake/python"), run, tmp_path / "l.jsonl")

        for argument in SLOWEST_DURATIONS_ARGS:
            assert argument in argv

    def test_run_tests_sh_passes_them_on_its_pytest_command_lines(self) -> None:
        script = (SCRIPTS_DIR / "run_tests.sh").read_text(encoding="utf-8")

        assert "SLOWEST_DURATIONS_ARGS" in script
        # Both the json-report and the text-fallback pytest invocations.
        assert script.count('"${SLOWEST_DURATIONS_ARGS[@]}"') == 2


class TestMatrixStoresTheSlowestTests:
    @pytest.fixture
    def matrix(self) -> Any:
        return _load("matrix_for_durations_store", SCRIPTS_DIR / "run_test_matrix.py")

    def test_a_log_outcome_carries_the_parsed_durations(self, matrix: Any, tmp_path: Path) -> None:
        log = tmp_path / "run.log"
        log.write_text(_REAL_OUTPUT, encoding="utf-8")

        outcome = matrix.outcome_from_log(log, exit_code=0, lines=tmp_path / "none.jsonl")

        assert [r["seconds"] for r in outcome.slowest_tests] == [12.5, 3.01, 0.01, 0.01]

    def test_a_primary_report_outcome_carries_the_stored_durations(
        self, matrix: Any, tmp_path: Path
    ) -> None:
        stored = [{"nodeid": "a::b", "phase": "call", "seconds": 4.0}]
        path = tmp_path / "tests.json"
        path.write_text(
            json.dumps({"summary": {"passed_all": True}, "tests": [], "slowest_tests": stored}),
            encoding="utf-8",
        )

        outcome = matrix.outcome_from_primary_report(path, exit_code=0)

        assert list(outcome.slowest_tests) == stored

    def test_each_legs_entry_in_tests_json_lists_its_own_slowest_tests(
        self, matrix: Any, tmp_path: Path
    ) -> None:
        records = ({"nodeid": "a::b", "phase": "call", "seconds": 4.0},)
        run = matrix.PlannedRun("3.13", "unit", 1, False)
        outcome = matrix.RunOutcome(
            0,
            {"total": 1, "passed": 1, "failed": 0, "skipped": 0, "errors": 0, "passed_all": True},
            [],
            tmp_path / "run.log",
            {},
            records,
        )
        result = matrix.RunResult(run, outcome, 2.0, None)

        report = matrix.build_report([result], {}, wall_seconds=2.0)

        assert report["interpreters"][0]["slowest_tests"] == list(records)

    def test_an_outcome_built_without_durations_has_none(self, matrix: Any, tmp_path: Path) -> None:
        outcome = matrix.RunOutcome(0, {}, [], tmp_path, {})

        assert list(outcome.slowest_tests) == []


class TestTheTestsSummaryShowsTheTopTen:
    @pytest.fixture
    def llm_qa(self) -> Any:
        return _load("llm_qa_for_durations", SCRIPTS_DIR / "llm_qa.py")

    @staticmethod
    def _records(count: int, offset: float = 0.0) -> list[dict[str, Any]]:
        return [
            {"nodeid": f"t/test_{i}.py::test", "phase": "call", "seconds": offset + i}
            for i in range(1, count + 1)
        ]

    def _report(self, **extra: Any) -> dict[str, Any]:
        return {
            "summary": {"passed": 5, "failed": 0, "skipped": 0},
            "tests": [],
            "coverage": {"percent_covered": 96.0},
            **extra,
        }

    def test_only_ten_are_shown_slowest_first_across_legs(self, llm_qa: Any) -> None:
        data = self._report(
            interpreters=[
                {
                    "version": "3.13",
                    "scope": "full",
                    "slowest_tests": self._records(8),
                },
                {
                    "version": "3.11",
                    "scope": "unit",
                    "slowest_tests": self._records(8, offset=100.0),
                },
            ]
        )

        summary = llm_qa._summarize_tests(data)

        shown = [line for line in summary.splitlines() if " call " in line]
        assert len(shown) == 10
        assert "108.0s call t/test_8.py::test [py3.11 unit]" in shown[0]
        assert "slowest tests" in summary
        assert "t/test_1.py::test [py3.13 full]" not in summary

    def test_a_report_with_no_durations_prints_no_section(self, llm_qa: Any) -> None:
        assert "slowest tests" not in llm_qa._summarize_tests(self._report())

    def test_a_direct_run_tests_sh_report_is_shown_without_a_leg_label(self, llm_qa: Any) -> None:
        summary = llm_qa._summarize_tests(self._report(slowest_tests=self._records(2)))

        assert "2.0s call t/test_2.py::test" in summary
        assert "[py" not in summary
