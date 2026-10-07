"""The tests stage runs each leg as named shards, each its own checkpoint (Plan 00500 Task 2.4).

A host reboot used to lose the whole primary leg (the longest, with coverage).
Now every leg is a list of shards run one after another; each is checkpointed as
it finishes, ``--resume`` re-runs only the shards not green on the identical
tree, and coverage is combined over every primary shard, run or reused, and
judged once against the unchanged threshold.
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.qa.suite_shards import Shard

PROJECT_ROOT = Path(__file__).resolve().parents[3]
MATRIX_SCRIPT = PROJECT_ROOT / "scripts" / "qa" / "run_test_matrix.py"
RUN_TESTS_SH = PROJECT_ROOT / "scripts" / "qa" / "run_tests.sh"
PYPROJECT = PROJECT_ROOT / "pyproject.toml"

_HEAD = "f" * 40
_SHARDS = [
    Shard("u-one", "unit", ("tests/unit/one",)),
    Shard("u-two", "unit", ("tests/unit/two",)),
    Shard("r-one", "rest", ("tests/integration",)),
]
_SLOW = [{"nodeid": "tests/x.py::t", "phase": "call", "seconds": 4.0}]


def _load_matrix() -> Any:
    spec = importlib.util.spec_from_file_location(
        "run_test_matrix_shards_under_test", MATRIX_SCRIPT
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {MATRIX_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _Tree:
    digest = "d1"

    def __call__(self) -> dict[str, str]:
        return {"head": _HEAD, "tree_digest": self.digest}


class _Job:
    def __init__(self, harness: _Harness, run: Any) -> None:
        self._harness = harness
        self._run = run

    def wait(self) -> Any:
        return self._harness.finish(self._run)


class _Harness:
    def __init__(self, matrix: Any, qa_dir: Path) -> None:
        self.matrix = matrix
        self.qa_dir = qa_dir
        self.tree = _Tree()
        self.store = matrix.LegCheckpoints(qa_dir, tree=self.tree)
        self.started: list[tuple[str, str, str | None]] = []
        self.red: set[tuple[str, str, str | None]] = set()
        self.daemon_checks = 0

    def provision(self, version: str) -> Path:
        return Path(f"/fake/py{version}/bin/python")

    def launch(self, run: Any, python: Path) -> _Job:
        self.started.append((run.version, run.scope, run.shard))
        return _Job(self, run)

    def ensure_daemon(self) -> str | None:
        self.daemon_checks += 1
        return None

    def finish(self, run: Any) -> Any:
        key = (run.version, run.scope, run.shard)
        failed = key in self.red
        names = [f"tests/{run.shard}.py::test_bad"] if failed else []
        summary = {
            "total": 10,
            "passed": 9 if failed else 10,
            "failed": 1 if failed else 0,
            "skipped": 1,
            "errors": 0,
            "passed_all": not failed,
        }
        data: Path | None = None
        if run.primary:
            log = self.qa_dir / f"tests-shard-{run.shard}.json"
            log.write_text(
                json.dumps({"summary": summary, "tests": [{"name": f"t-{run.shard}"}]}),
                encoding="utf-8",
            )
            data = self.qa_dir / f".coverage.{run.shard}"
            data.write_text(f"data {run.shard}", encoding="utf-8")
        else:
            log = self.qa_dir / f"tests-py{run.version}-{run.scope}-{run.shard}.log"
            log.write_text("output", encoding="utf-8")
        return self.matrix.RunOutcome(
            exit_code=1 if failed else 0,
            summary=summary,
            failed_tests=names,
            log=log,
            first_error_lines=dict.fromkeys(names, "boom"),
            slowest_tests=_SLOW,
            coverage_data=data,
        )

    def run(self, *, resume: bool) -> list[Any]:
        plan = self.matrix.plan_runs(["3.11", "3.12"], "3.11", _SHARDS)
        deps = self.matrix.MatrixDeps(
            provision=self.provision,
            launch=self.launch,
            ensure_daemon=self.ensure_daemon,
            clock=lambda: 2.0,
            checkpoints=self.store,
            resume=resume,
        )
        return list(self.matrix.run_matrix(plan, Path("/fake/py3.11/bin/python"), deps))


@pytest.fixture
def harness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> _Harness:
    matrix = _load_matrix()
    qa_dir = tmp_path / "qa"
    qa_dir.mkdir()
    monkeypatch.setattr(matrix, "QA_OUTPUT_DIR", qa_dir)
    monkeypatch.setattr(matrix, "TESTS_JSON", qa_dir / "tests.json")
    return _Harness(matrix, qa_dir)


class TestThePlan:
    def test_each_leg_lists_its_shards_in_declaration_order(self) -> None:
        matrix = _load_matrix()

        plan = matrix.plan_runs(["3.11", "3.12"], "3.11", _SHARDS)

        assert [(r.version, r.scope, r.shards) for r in plan] == [
            ("3.11", "full", ("u-one", "u-two", "r-one")),
            ("3.12", "unit", ("u-one", "u-two")),
            ("3.12", "rest", ("r-one",)),
        ]

    def test_without_shards_a_leg_is_one_unit_as_before(self) -> None:
        matrix = _load_matrix()

        plan = matrix.plan_runs(["3.11", "3.12"], "3.11")

        assert all(r.shards == () and r.shard is None for r in plan)

    def test_a_shard_has_its_own_checkpoint_key(self) -> None:
        matrix = _load_matrix()
        leg = matrix.PlannedRun("3.11", "full", 1, True, ("a",))

        assert matrix.leg_key(leg) == "py3.11-full"
        assert matrix.leg_key(leg._replace(shards=(), shard="a")) == "py3.11-full-a"


class TestShardedRun:
    def test_shards_run_one_after_another_and_each_is_checkpointed(self, harness: _Harness) -> None:
        harness.run(resume=False)

        assert sorted(harness.started) == sorted(
            [
                ("3.11", "full", "u-one"),
                ("3.11", "full", "u-two"),
                ("3.11", "full", "r-one"),
                ("3.12", "unit", "u-one"),
                ("3.12", "unit", "u-two"),
                ("3.12", "rest", "r-one"),
            ]
        )
        for key in (
            "py3.11-full-u-one",
            "py3.11-full-u-two",
            "py3.11-full-r-one",
            "py3.12-unit-u-one",
            "py3.12-unit-u-two",
            "py3.12-rest-r-one",
        ):
            assert not isinstance(harness.store.check(key), str), key

    def test_within_a_leg_the_shards_keep_declaration_order(self, harness: _Harness) -> None:
        harness.run(resume=False)

        primary = [s for v, scope, s in harness.started if v == "3.11"]
        assert primary == ["u-one", "u-two", "r-one"]

    def test_one_result_per_leg_with_summed_counts_and_a_shards_list(
        self, harness: _Harness
    ) -> None:
        results = harness.run(resume=False)

        assert len(results) == 3
        primary = results[0]
        assert primary.outcome.summary["total"] == 30
        assert primary.outcome.summary["skipped"] == 3
        assert primary.outcome.summary["passed_all"] is True
        assert [s.name for s in primary.shards] == ["u-one", "u-two", "r-one"]
        assert not any(s.reused for s in primary.shards)

    def test_a_red_shard_makes_the_leg_red_and_does_not_stop_the_later_shards(
        self, harness: _Harness
    ) -> None:
        harness.red.add(("3.11", "full", "u-one"))

        results = harness.run(resume=False)

        primary = results[0]
        assert primary.outcome.summary["passed_all"] is False
        assert primary.outcome.exit_code == 1
        assert primary.outcome.failed_tests == ["tests/u-one.py::test_bad"]
        assert primary.outcome.first_error_lines == {"tests/u-one.py::test_bad": "boom"}
        assert [s.name for s in primary.shards] == ["u-one", "u-two", "r-one"]

    def test_slowest_tests_are_merged_across_shards(self, harness: _Harness) -> None:
        results = harness.run(resume=False)

        assert len(results[0].outcome.slowest_tests) == 3

    def test_the_serial_leg_checks_the_daemon_before_each_shard_it_runs(
        self, harness: _Harness
    ) -> None:
        harness.run(resume=False)

        assert harness.daemon_checks == 1


class TestResume:
    def test_a_normal_run_never_reuses_a_shard(self, harness: _Harness) -> None:
        harness.run(resume=False)
        harness.started.clear()

        results = harness.run(resume=False)

        assert len(harness.started) == 6
        assert not any(r.reused or any(s.reused for s in r.shards) for r in results)

    def test_resume_reruns_only_the_shards_not_green_on_this_tree(self, harness: _Harness) -> None:
        harness.run(resume=False)
        harness.store.path("py3.11-full-u-two").unlink()
        harness.started.clear()

        results = harness.run(resume=True)

        assert harness.started == [("3.11", "full", "u-two")]
        primary = results[0]
        assert [(s.name, s.reused) for s in primary.shards] == [
            ("u-one", True),
            ("u-two", False),
            ("r-one", True),
        ]
        assert primary.reused is False
        assert results[2].reused is True

    def test_a_fully_reused_leg_is_reused(self, harness: _Harness) -> None:
        harness.run(resume=False)
        harness.started.clear()

        results = harness.run(resume=True)

        assert harness.started == []
        assert all(r.reused for r in results)
        assert harness.daemon_checks == 1, "a reused serial leg must not start the daemon"

    def test_a_changed_tree_reruns_every_shard(self, harness: _Harness) -> None:
        harness.run(resume=False)
        harness.started.clear()
        harness.tree.digest = "d2"

        harness.run(resume=True)

        assert len(harness.started) == 6

    def test_a_reused_primary_shard_whose_coverage_data_changed_is_rerun(
        self, harness: _Harness
    ) -> None:
        harness.run(resume=False)
        (harness.qa_dir / ".coverage.u-one").write_text("tampered", encoding="utf-8")
        harness.started.clear()

        harness.run(resume=True)

        assert harness.started == [("3.11", "full", "u-one")]

    def test_a_reused_shard_carries_its_coverage_data_and_counts(self, harness: _Harness) -> None:
        harness.run(resume=False)

        primary = harness.run(resume=True)[0]

        assert primary.outcome.summary["total"] == 30
        assert [s.outcome.coverage_data.name for s in primary.shards] == [
            ".coverage.u-one",
            ".coverage.u-two",
            ".coverage.r-one",
        ]


class TestTheReport:
    def test_the_leg_entry_lists_each_shard_with_a_reused_flag(self, harness: _Harness) -> None:
        harness.run(resume=False)
        harness.store.path("py3.11-full-r-one").unlink()
        results = harness.run(resume=True)

        report = harness.matrix.build_report(results, {}, wall_seconds=1.0)

        entry = report["interpreters"][0]
        assert [(s["name"], s["reused"]) for s in entry["shards"]] == [
            ("u-one", True),
            ("u-two", True),
            ("r-one", False),
        ]
        assert entry["total"] == 30
        assert report["summary"]["total"] == 30 + 20 + 10

    def test_an_unsharded_leg_has_no_shards_key(self) -> None:
        matrix = _load_matrix()
        outcome = matrix.RunOutcome(0, {"passed_all": True}, [], Path("/x.log"), {})
        result = matrix.RunResult(matrix.PlannedRun("3.12", "unit", 1, False), outcome, 1.0, None)

        report = matrix.build_report([result], {}, wall_seconds=1.0)

        assert "shards" not in report["interpreters"][0]

    def test_a_coverage_failure_reddens_the_report(self, harness: _Harness) -> None:
        results = harness.run(resume=False)

        report = harness.matrix.build_report(
            results, {}, wall_seconds=1.0, coverage_failure="coverage 90.00% is below 95.0%"
        )

        assert report["summary"]["passed_all"] is False
        assert report["summary"]["unnamed_failure_reason"] == "coverage 90.00% is below 95.0%"
        assert "below 95.0%" in report["error"]

    def test_the_primary_report_keeps_its_shape(self, harness: _Harness) -> None:
        results = harness.run(resume=False)

        primary_report = harness.matrix.primary_report_from_shards(
            results[0], {"percent_covered": 97.0}
        )

        assert primary_report["coverage"] == {"percent_covered": 97.0}
        assert [t["name"] for t in primary_report["tests"]] == ["t-u-one", "t-u-two", "t-r-one"]


def _measure(tmp_path: Path, data_file: Path, module: str, lines: str) -> None:
    """Run a tiny program under coverage into its own data file (no parallel mode)."""
    source = tmp_path / f"{module}.py"
    source.write_text(lines, encoding="utf-8")
    subprocess.run(
        [
            sys.executable,
            "-m",
            "coverage",
            "run",
            "--branch",
            f"--data-file={data_file}",
            str(source),
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )


class TestCombineCoverage:
    def test_two_shard_data_files_combine_into_one_verdict(self, tmp_path: Path) -> None:
        matrix = _load_matrix()
        first, second = tmp_path / ".coverage.a", tmp_path / ".coverage.b"
        _measure(tmp_path, first, "prog", "x = 1\nif x:\n    y = 2\n")
        _measure(tmp_path, second, "prog", "x = 0\nif x:\n    y = 2\n")
        (tmp_path / ".coveragerc").write_text("[report]\nfail_under = 100\n", encoding="utf-8")

        verdict = matrix.combine_coverage(
            Path(sys.executable), [first, second], tmp_path, cwd=tmp_path
        )

        assert verdict.passed, verdict.message
        assert verdict.coverage["percent_covered"] == 100.0
        assert (tmp_path / "coverage.json").is_file()
        assert first.is_file() and second.is_file(), "the shard data files are kept"

    def test_a_total_below_fail_under_is_a_failed_verdict(self, tmp_path: Path) -> None:
        matrix = _load_matrix()
        only = tmp_path / ".coverage.a"
        _measure(tmp_path, only, "prog", "x = 0\nif x:\n    y = 2\n")
        (tmp_path / ".coveragerc").write_text("[report]\nfail_under = 100\n", encoding="utf-8")

        verdict = matrix.combine_coverage(Path(sys.executable), [only], tmp_path, cwd=tmp_path)

        assert not verdict.passed
        assert "less than fail-under=100" in (verdict.message or "")
        assert verdict.coverage["percent_covered"] < 100.0

    def test_a_missing_data_file_is_not_judged_green(self, tmp_path: Path) -> None:
        matrix = _load_matrix()

        verdict = matrix.combine_coverage(
            Path(sys.executable), [tmp_path / ".coverage.absent"], tmp_path, cwd=tmp_path
        )

        assert not verdict.passed
        assert "absent" in (verdict.message or "")


class TestCoverageNaming:
    def test_the_shell_variable_for_the_json_report_is_not_the_data_file_variable(self) -> None:
        """``COVERAGE_FILE`` in the environment is coverage.py's DATA file path.

        run_tests.sh must never give that name to the JSON report path.
        """
        text = RUN_TESTS_SH.read_text(encoding="utf-8")

        assert not re.search(r"^\s*(export\s+)?COVERAGE_FILE=.*\.json", text, re.MULTILINE)
        assert re.search(r'^COVERAGE_JSON=".*coverage\.json"', text, re.MULTILINE)
        assert "COVERAGE_FILE=" in text, "shard mode exports the data file for coverage.py"

    def test_run_tests_sh_refuses_a_data_file_that_is_the_json_report(self) -> None:
        text = RUN_TESTS_SH.read_text(encoding="utf-8")

        assert re.search(r'"\$\{COVERAGE_DATA\}" = "\$\{COVERAGE_JSON\}"', text)

    def test_the_matrix_never_hands_a_shard_the_json_report_as_its_data_file(self) -> None:
        matrix = _load_matrix()

        report, data = matrix.shard_report_path("x"), matrix.shard_coverage_data_path("x")

        assert data != report
        assert data != matrix.QA_OUTPUT_DIR / "coverage.json"
        assert data.name == ".coverage.x"

    def test_pytest_cov_keeps_parallel_mode_off(self) -> None:
        text = PYPROJECT.read_text(encoding="utf-8")

        assert not re.search(r"^\s*parallel\s*=\s*true", text, re.MULTILINE)
        assert re.search(r"^fail_under = 95\.0$", text, re.MULTILINE)


class TestMergeOutcomes:
    def test_slowest_tests_are_capped_like_one_run(self) -> None:
        matrix = _load_matrix()
        many = [{"nodeid": f"t{i}", "phase": "call", "seconds": float(i)} for i in range(40)]
        outcome = matrix.RunOutcome(0, {"passed_all": True}, [], Path("/a"), {}, many)

        merged = matrix.merge_outcomes([outcome, outcome])

        assert len(merged.slowest_tests) == 50
        assert merged.slowest_tests[0]["seconds"] == 39.0

    def test_unnamed_failure_reasons_are_joined_and_the_failing_log_is_kept(self) -> None:
        matrix = _load_matrix()
        green = matrix.RunOutcome(0, {"passed_all": True}, [], Path("/green"), {})
        red = matrix.RunOutcome(
            1, {"passed_all": False, "unnamed_failure_reason": "why"}, [], Path("/red"), {}
        )

        merged = matrix.merge_outcomes([green, red, green])

        assert merged.log == Path("/red")
        assert merged.exit_code == 1
        assert merged.summary["unnamed_failure_reason"] == "why"


class TestJudgePrimary:
    def test_a_sharded_primary_is_judged_on_the_combined_coverage(
        self, harness: _Harness, tmp_path: Path
    ) -> None:
        results = harness.run(resume=False)
        for shard in ("u-one", "u-two", "r-one"):
            _measure(tmp_path, harness.qa_dir / f".coverage.{shard}", "prog", "x = 1\n")
        (tmp_path / ".coveragerc").write_text("[report]\nfail_under = 100\n", encoding="utf-8")

        report, failure = harness.matrix.judge_primary(
            results, Path(sys.executable), qa_dir=harness.qa_dir, cwd=tmp_path
        )

        assert failure is None
        assert report["coverage"]["percent_covered"] == 100.0
        assert len(report["tests"]) == 3

    def test_missing_shard_coverage_data_is_a_failure(self, harness: _Harness) -> None:
        results = harness.run(resume=False)
        (harness.qa_dir / ".coverage.u-two").unlink()

        _, failure = harness.matrix.judge_primary(
            results, Path(sys.executable), qa_dir=harness.qa_dir, cwd=harness.qa_dir
        )

        assert failure is not None
        assert ".coverage.u-two" in failure

    def test_an_unsharded_primary_reads_its_own_tests_json(self, harness: _Harness) -> None:
        harness.matrix.TESTS_JSON.write_text('{"coverage": {"percent_covered": 96}}', "utf-8")
        outcome = harness.matrix.RunOutcome(0, {"passed_all": True}, [], Path("/x"), {})
        leg = harness.matrix.PlannedRun("3.11", "full", 1, True)
        results = [harness.matrix.RunResult(leg, outcome, 1.0, None)]

        report, failure = harness.matrix.judge_primary(
            results, Path(sys.executable), qa_dir=harness.qa_dir, cwd=harness.qa_dir
        )

        assert failure is None
        assert report["coverage"]["percent_covered"] == 96
