"""The full gate's tests stage runs every Python version CI runs (ledger 00466 N110).

CI's QA job runs the suite under a matrix of interpreters. The local gate
(`llm_qa.py all`) ran it under the checkout's one venv, so a defect that only
exists on a newer interpreter passed the gate and turned CI red after the
merge: N24 relied on a stdlib cost that is quadratic only from Python 3.12.

The central assertion reads the matrix out of the CI workflow ITSELF, not out
of anything the runner declares, and fails when the set of versions the
gate's tests stage runs is narrower. The rest pins the behaviour that makes
that set real: an interpreter that cannot be provisioned FAILS the stage
(it never quietly runs fewer versions), a red extra-interpreter run fails the
stage and is named, and the extra runs overlap the primary run instead of
being queued behind it.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, ClassVar

import pytest
import yaml

from claude_code_hooks_daemon.qa.first_error_lines import OPTION, PLUGIN
from claude_code_hooks_daemon_full_qa_gate_loader import GATE_PLUGIN as FULL_QA_GATE

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = PROJECT_ROOT / "scripts" / "qa"
CI_WORKFLOW = PROJECT_ROOT / ".github" / "workflows" / "qa.yml"
RUN_ALL_SH = SCRIPTS_DIR / "run_all.sh"
MATRIX_SCRIPT = SCRIPTS_DIR / "run_test_matrix.py"

# Deliberately nonexistent: nothing in these tests sends a signal, but a fake
# job must never carry a pid that could reach one (agent rule, 00466 N59).
_FAKE_PID = 2**22 + 7


def _load(module_name: str, path: Path) -> Any:
    """Import a script under `scripts/qa/`, which is not a package."""
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_matrix() -> Any:
    return _load("run_test_matrix_under_test", MATRIX_SCRIPT)


def _ci_matrix_versions() -> list[str]:
    """CI's QA-job Python matrix, read independently of the code under test."""
    workflow = yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))
    versions = workflow["jobs"]["qa"]["strategy"]["matrix"]["python-version"]
    return [str(v) for v in versions]


class TestTheGateCoversEveryCiPythonVersion:
    """The N110 guard: gate set narrower than CI's matrix is a failure."""

    def test_ci_matrix_is_readable_and_not_trivial(self) -> None:
        """Vacuity guard: a one-entry matrix would make the check below empty."""
        assert len(_ci_matrix_versions()) >= 2

    def test_llm_qa_tests_stage_runs_the_matrix_runner(self) -> None:
        llm_qa = _load("llm_qa_matrix_wiring_under_test", SCRIPTS_DIR / "llm_qa.py")
        command = llm_qa.TOOL_REGISTRY["tests"].command

        assert str(MATRIX_SCRIPT) in command, (
            f"llm_qa.py's tests stage runs {command}, which is one interpreter; "
            f"CI runs {_ci_matrix_versions()}"
        )

    def test_run_all_tests_stage_runs_the_matrix_runner(self) -> None:
        text = RUN_ALL_SH.read_text(encoding="utf-8")

        assert '"${SCRIPT_DIR}/run_test_matrix.py"' in text
        assert '"${SCRIPT_DIR}/run_tests.sh"' not in text

    @pytest.mark.parametrize("primary", ["3.11", "3.12", "3.13", "3.14"])
    def test_every_ci_version_runs_the_whole_suite(self, primary: str) -> None:
        """Whatever the local venv's version, every CI version gets all of tests/."""
        matrix = _load_matrix()
        ci_versions = _ci_matrix_versions()

        plan = matrix.plan_runs(matrix.ci_python_versions(CI_WORKFLOW), primary)
        gate_versions = matrix.fully_covered_versions(plan)

        missing = set(ci_versions) - gate_versions
        assert not missing, (
            f"the gate's tests stage runs {sorted(gate_versions)} but CI's matrix is "
            f"{ci_versions}: {sorted(missing)} would only ever be tested by CI"
        )

    def test_the_plan_reads_the_workflow_rather_than_a_copy_of_it(self, tmp_path: Path) -> None:
        """Adding a version to CI must widen the gate with no second edit."""
        matrix = _load_matrix()
        workflow = tmp_path / "qa.yml"
        workflow.write_text(
            "jobs:\n  qa:\n    strategy:\n      matrix:\n"
            '        python-version: ["3.11", "3.12", "3.13", "3.14"]\n',
            encoding="utf-8",
        )

        plan = matrix.plan_runs(matrix.ci_python_versions(workflow), "3.11")

        assert matrix.fully_covered_versions(plan) == {"3.11", "3.12", "3.13", "3.14"}

    def test_the_coverage_check_has_teeth(self) -> None:
        """A plan that drops the rest-of-suite run for one version is NOT covered."""
        matrix = _load_matrix()
        plan = matrix.plan_runs(["3.11", "3.12"], "3.11")
        narrowed = [run for run in plan if not (run.version == "3.12" and run.scope == "rest")]

        assert matrix.fully_covered_versions(narrowed) == {"3.11"}


class TestCiMatrixParsingFailsClosed:
    @pytest.mark.parametrize(
        "content",
        [
            "jobs: {}\n",
            "jobs:\n  qa:\n    strategy:\n      matrix: {}\n",
            "jobs:\n  qa:\n    strategy:\n      matrix:\n        python-version: []\n",
            "jobs:\n  qa:\n    strategy:\n      matrix:\n        python-version: [3.1x]\n",
            "- not a mapping\n",
        ],
    )
    def test_an_unusable_matrix_is_an_error_not_an_empty_plan(
        self, tmp_path: Path, content: str
    ) -> None:
        matrix = _load_matrix()
        workflow = tmp_path / "qa.yml"
        workflow.write_text(content, encoding="utf-8")

        with pytest.raises(matrix.MatrixError):
            matrix.ci_python_versions(workflow)

    def test_a_missing_workflow_is_an_error(self, tmp_path: Path) -> None:
        matrix = _load_matrix()

        with pytest.raises(matrix.MatrixError, match="qa.yml"):
            matrix.ci_python_versions(tmp_path / "qa.yml")

    def test_unquoted_yaml_floats_are_rejected_not_misread(self, tmp_path: Path) -> None:
        """`3.10` unquoted is the float 3.1 -- reading it would test the wrong version."""
        matrix = _load_matrix()
        workflow = tmp_path / "qa.yml"
        workflow.write_text(
            "jobs:\n  qa:\n    strategy:\n      matrix:\n        python-version: [3.10]\n",
            encoding="utf-8",
        )

        with pytest.raises(matrix.MatrixError, match="string"):
            matrix.ci_python_versions(workflow)


class TestThePlan:
    def test_the_primary_runs_everything_once_and_extras_are_split(self) -> None:
        matrix = _load_matrix()

        plan = matrix.plan_runs(["3.11", "3.12", "3.13"], "3.11")

        described = [(r.version, r.scope, r.phase, r.primary) for r in plan]
        assert described == [
            ("3.11", "full", 1, True),
            ("3.12", "unit", 1, False),
            ("3.13", "unit", 1, False),
            ("3.12", "rest", 2, False),
            ("3.13", "rest", 2, False),
        ]

    def test_a_primary_outside_the_matrix_still_runs_and_every_ci_version_is_extra(
        self,
    ) -> None:
        matrix = _load_matrix()

        plan = matrix.plan_runs(["3.12", "3.13"], "3.11")

        assert [(r.version, r.scope) for r in plan if r.primary] == [("3.11", "full")]
        assert {r.version for r in plan if not r.primary} == {"3.12", "3.13"}

    def test_the_two_extra_scopes_partition_the_suite(self) -> None:
        """`unit` + `rest` must be exactly tests/, with no directory run twice or never."""
        matrix = _load_matrix()

        assert matrix.SCOPE_PYTEST_ARGS["unit"] == ["tests/unit"]
        assert matrix.SCOPE_PYTEST_ARGS["rest"] == ["tests", "--ignore=tests/unit"]


class _FakeJob:
    def __init__(self, events: list[str], label: str, outcome: Any) -> None:
        self.pid = _FAKE_PID
        self._events = events
        self._label = label
        self._outcome = outcome

    def wait(self) -> Any:
        self._events.append(f"wait {self._label}")
        return self._outcome


class _Harness:
    """Records the order in which the runner provisions, starts and waits."""

    def __init__(
        self,
        matrix: Any,
        *,
        unprovisionable: frozenset[str] = frozenset(),
        red: frozenset[tuple[str, str]] = frozenset(),
    ) -> None:
        self.matrix = matrix
        self.events: list[str] = []
        self.unprovisionable = unprovisionable
        self.red = red

    def provision(self, version: str) -> Path:
        self.events.append(f"provision {version}")
        if version in self.unprovisionable:
            raise self.matrix.ProvisionError(f"uv python install {version} failed: offline")
        return Path(f"/fake/py{version}/bin/python")

    def launch(self, run: Any, python: Path) -> _FakeJob:
        label = f"{run.version} {run.scope}"
        self.events.append(f"start {label}")
        failed = 1 if (run.version, run.scope) in self.red else 0
        failed_tests = [f"tests/unit/test_x.py::test_{run.version}"] if failed else []
        outcome = self.matrix.RunOutcome(
            exit_code=1 if failed else 0,
            summary={
                "total": 10,
                "passed": 10 - failed,
                "failed": failed,
                "skipped": 0,
                "errors": 0,
                "passed_all": not failed,
            },
            failed_tests=failed_tests,
            log=Path(f"/fake/{run.version}-{run.scope}.log"),
            first_error_lines=dict.fromkeys(failed_tests, "Daemon not running"),
        )
        return _FakeJob(self.events, label, outcome)

    def ensure_daemon(self) -> str | None:
        self.events.append("ensure daemon")
        return None

    def deps(self) -> Any:
        return self.matrix.MatrixDeps(
            provision=self.provision,
            launch=self.launch,
            ensure_daemon=self.ensure_daemon,
            clock=lambda: 0.0,
        )


class TestTheRunnerExecutesThePlan:
    def test_extras_overlap_the_primary_and_the_daemon_phase_is_serial(self) -> None:
        matrix = _load_matrix()
        harness = _Harness(matrix)
        plan = matrix.plan_runs(["3.11", "3.12", "3.13"], "3.11")

        matrix.run_matrix(plan, Path("/fake/py3.11/bin/python"), harness.deps())

        events = harness.events
        first_wait = min(i for i, e in enumerate(events) if e.startswith("wait"))
        # Every phase-1 run is started before the runner blocks on any of them.
        for label in ("start 3.11 full", "start 3.12 unit", "start 3.13 unit"):
            assert events.index(label) < first_wait
        assert events[0] == "start 3.11 full", "the longest run must not wait on provisioning"
        # Phase 2 shares the checkout's one daemon, so it runs after phase 1 and
        # one interpreter at a time.
        phase_one_done = max(
            events.index(f"wait {v}") for v in ("3.11 full", "3.12 unit", "3.13 unit")
        )
        assert events.index("ensure daemon") > phase_one_done
        assert events.index("start 3.12 rest") > events.index("ensure daemon")
        assert events.index("wait 3.12 rest") < events.index("start 3.13 rest")

    def test_the_daemon_is_ensured_before_every_serial_run(self) -> None:
        """00466 N196: the daemon idles out after ``idle_timeout_seconds``.
        py3.12 rest's last daemon traffic was 11 minutes before it ended, so
        the daemon ensured before it had exited by the time py3.13 rest
        started, and py3.13's declared release gates ERRORED on the skip.
        Each serial run needs its own check."""
        matrix = _load_matrix()
        harness = _Harness(matrix)
        plan = matrix.plan_runs(["3.11", "3.12", "3.13"], "3.11")

        matrix.run_matrix(plan, Path("/fake/py3.11/bin/python"), harness.deps())

        serial = [e for e in harness.events if e == "ensure daemon" or e.endswith(" rest")]
        assert serial == [
            "ensure daemon",
            "start 3.12 rest",
            "wait 3.12 rest",
            "ensure daemon",
            "start 3.13 rest",
            "wait 3.13 rest",
        ]

    def test_an_extra_runs_failure_carries_its_first_error_line(self) -> None:
        matrix = _load_matrix()
        harness = _Harness(matrix, red=frozenset({("3.13", "rest")}))
        plan = matrix.plan_runs(["3.11", "3.13"], "3.11")

        results = matrix.run_matrix(plan, Path("/fake/py3.11/bin/python"), harness.deps())
        report = matrix.build_report(results, _primary_report(), wall_seconds=1.0)

        failed = [t for t in report["tests"] if t["outcome"] == "failed"]
        assert failed == [
            {
                "name": "[py3.13 rest] tests/unit/test_x.py::test_3.13",
                "outcome": "failed",
                "reason": "Daemon not running",
            }
        ]

    def test_an_unprovisionable_interpreter_fails_the_stage_and_says_so(self) -> None:
        matrix = _load_matrix()
        harness = _Harness(matrix, unprovisionable=frozenset({"3.13"}))
        plan = matrix.plan_runs(["3.11", "3.12", "3.13"], "3.11")

        results = matrix.run_matrix(plan, Path("/fake/py3.11/bin/python"), harness.deps())
        report = matrix.build_report(results, _primary_report(), wall_seconds=1.0)

        assert report["summary"]["passed_all"] is False
        assert "3.13" in report["error"] and "offline" in report["error"]
        not_run = [e for e in report["interpreters"] if e["version"] == "3.13"]
        assert not_run and all(e["error"] for e in not_run)
        # Nothing was launched for it: a stage that cannot run a version must
        # not report a partial run of that version as a result.
        assert not any(e.startswith("start 3.13") for e in harness.events)
        # The other extra still ran in full.
        assert "start 3.12 unit" in harness.events and "start 3.12 rest" in harness.events

    def test_a_red_extra_run_fails_the_stage_and_names_the_test(self) -> None:
        matrix = _load_matrix()
        harness = _Harness(matrix, red=frozenset({("3.13", "unit")}))
        plan = matrix.plan_runs(["3.11", "3.12", "3.13"], "3.11")

        results = matrix.run_matrix(plan, Path("/fake/py3.11/bin/python"), harness.deps())
        report = matrix.build_report(results, _primary_report(), wall_seconds=1.0)

        assert report["summary"]["passed_all"] is False
        assert report["summary"]["failed"] == 1
        names = [t["name"] for t in report["tests"] if t["outcome"] == "failed"]
        assert names == ["[py3.13 unit] tests/unit/test_x.py::test_3.13"]

    def test_all_green_is_green_and_every_run_is_reported(self) -> None:
        matrix = _load_matrix()
        harness = _Harness(matrix)
        plan = matrix.plan_runs(["3.11", "3.12", "3.13"], "3.11")

        results = matrix.run_matrix(plan, Path("/fake/py3.11/bin/python"), harness.deps())
        report = matrix.build_report(results, _primary_report(), wall_seconds=12.5)

        assert report["summary"]["passed_all"] is True
        assert "error" not in report
        assert [(e["version"], e["scope"]) for e in report["interpreters"]] == [
            ("3.11", "full"),
            ("3.12", "unit"),
            ("3.13", "unit"),
            ("3.12", "rest"),
            ("3.13", "rest"),
        ]
        assert report["wall_seconds"] == 12.5
        # The primary's coverage is carried through untouched.
        assert report["coverage"] == {"percent_covered": 96.0}

    def test_a_red_primary_fails_the_stage(self) -> None:
        matrix = _load_matrix()
        harness = _Harness(matrix, red=frozenset({("3.11", "full")}))
        plan = matrix.plan_runs(["3.11", "3.12"], "3.11")

        results = matrix.run_matrix(plan, Path("/fake/py3.11/bin/python"), harness.deps())
        report = matrix.build_report(results, _primary_report(), wall_seconds=1.0)

        assert report["summary"]["passed_all"] is False

    def test_a_run_that_exits_red_with_no_named_failure_still_carries_detail(self) -> None:
        """A crash after collection names no test; the reader must still see which run."""
        matrix = _load_matrix()
        outcome = matrix.RunOutcome(
            exit_code=2,
            summary={
                "total": 0,
                "passed": 0,
                "failed": 0,
                "skipped": 0,
                "errors": 0,
                "passed_all": False,
            },
            failed_tests=[],
            log=Path("/fake/3.12-unit.log"),
            first_error_lines={},
        )
        result = matrix.RunResult(
            run=matrix.PlannedRun("3.12", "unit", 1, False),
            outcome=outcome,
            duration_seconds=3.0,
            error=None,
        )

        report = matrix.build_report([result], _primary_report(), wall_seconds=3.0)

        assert report["summary"]["passed_all"] is False
        names = [t["name"] for t in report["tests"] if t["outcome"] == "failed"]
        assert names and "3.12" in names[0] and "3.12-unit.log" in names[0]


def _primary_report() -> dict[str, Any]:
    """What run_tests.sh writes to tests.json for a green primary run."""
    return {
        "tool": "pytest",
        "summary": {
            "total": 10,
            "passed": 10,
            "failed": 0,
            "skipped": 0,
            "errors": 0,
            "passed_all": True,
        },
        "tests": [],
        "coverage": {"percent_covered": 96.0},
    }


class TestTheSummaryStatesTheVersionsTested:
    def test_every_run_and_every_unrun_version_is_on_the_summary(self) -> None:
        llm_qa = _load("llm_qa_matrix_summary_under_test", SCRIPTS_DIR / "llm_qa.py")
        matrix = _load_matrix()
        harness = _Harness(matrix, unprovisionable=frozenset({"3.13"}))
        plan = matrix.plan_runs(["3.11", "3.12", "3.13"], "3.11")
        results = matrix.run_matrix(plan, Path("/fake/py3.11/bin/python"), harness.deps())
        report = matrix.build_report(results, _primary_report(), wall_seconds=1.0)

        summary = llm_qa._summarize_tests(report)

        assert "py3.11 full: ok" in summary
        assert "py3.12 unit: ok" in summary and "py3.12 rest: ok" in summary
        assert "py3.13 unit: NOT RUN" in summary and "offline" in summary

    def test_a_named_failure_is_followed_by_its_first_error_line(self) -> None:
        llm_qa = _load("llm_qa_matrix_reason_under_test", SCRIPTS_DIR / "llm_qa.py")
        matrix = _load_matrix()
        harness = _Harness(matrix, red=frozenset({("3.13", "rest")}))
        plan = matrix.plan_runs(["3.11", "3.13"], "3.11")
        results = matrix.run_matrix(plan, Path("/fake/py3.11/bin/python"), harness.deps())
        report = matrix.build_report(results, _primary_report(), wall_seconds=1.0)

        summary = llm_qa._summarize_tests(report)

        assert "[py3.13 rest] tests/unit/test_x.py::test_3.13 - Daemon not running" in summary


class TestThePrimaryRunRecordsFirstErrorLines:
    """run_tests.sh is the primary's runner; its failures must carry a reason too."""

    def test_both_pytest_invocations_pass_the_option(self) -> None:
        script = (SCRIPTS_DIR / "run_tests.sh").read_text(encoding="utf-8")
        assert script.count('"${FIRST_ERROR_ARGS[@]}"') == 2
        assert f"{OPTION}=" in script

    def test_the_plugin_is_not_loaded_with_dash_p(self) -> None:
        """``-p`` imports the package before pytest-cov starts; see the class below."""
        script = (SCRIPTS_DIR / "run_tests.sh").read_text(encoding="utf-8")
        assert f"-p {PLUGIN}" not in script

    def test_both_report_builders_attach_the_lines(self) -> None:
        script = (SCRIPTS_DIR / "run_tests.sh").read_text(encoding="utf-8")
        assert script.count("attach_first_error_lines(tests, ") == 2


# Import-only modules: every line runs when the module is imported, so any line
# coverage reports missing was executed before measurement started.
_IMPORT_ONLY_MODULES = (
    "src/claude_code_hooks_daemon/core/__init__.py",
    "src/claude_code_hooks_daemon/qa/__init__.py",
)
_SMALL_TARGET = "tests/unit/constants/test_tools.py"


def _run_tests_sh_plugin_args(lines: Path) -> list[str]:
    """run_tests.sh's own FIRST_ERROR_ARGS, evaluated by bash as the script does."""
    script = (SCRIPTS_DIR / "run_tests.sh").read_text(encoding="utf-8")
    assignments = [line for line in script.splitlines() if line.startswith("FIRST_ERROR_ARGS=(")]
    assert len(assignments) == 1, assignments
    completed = subprocess.run(
        ["bash", "-c", f'{assignments[0]}\nprintf "%s\\n" "${{FIRST_ERROR_ARGS[@]}}"'],
        env={"PATH": os.environ["PATH"], "FIRST_ERROR_LINES_FILE": str(lines)},
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout.splitlines()


def _missing_import_time_lines(plugin_args: list[str], tmp_path: Path) -> dict[str, int]:
    """Measure a small target with the given plugin arguments, as the QA stage does."""
    report = tmp_path / "coverage.json"
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("COVERAGE_") and key != "PYTEST_ADDOPTS"
    }
    env["COVERAGE_FILE"] = str(tmp_path / ".coverage")
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            *plugin_args,
            "--cov=src/claude_code_hooks_daemon",
            "--cov-branch",
            "--cov-fail-under=0",
            f"--cov-report=json:{report}",
            _SMALL_TARGET,
        ],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, f"{completed.stdout}\n{completed.stderr}"
    files = json.loads(report.read_text(encoding="utf-8"))["files"]
    return {name: int(files[name]["summary"]["missing_lines"]) for name in _IMPORT_ONLY_MODULES}


class TestThePluginLoadsAfterCoverageStarts:
    """Import-time code is measured in the QA stage (00466 N110 round 3).

    ``-p claude_code_hooks_daemon.qa.first_error_lines`` imports the plugin
    while pytest parses its arguments, before pytest-cov starts measuring. The
    import runs the package ``__init__``, which imports ``core`` and more, so
    every module-level line of those modules went unmeasured: the primary run
    reported 92.61% over tests that cover 95%. The suite's conftest loads the
    plugin instead, after coverage has started.

    Both measurements run under this project's own ``addopts``, so they also
    cover the full-QA sink that ``addopts`` force-loads (Plan 00463): naming
    ``claude_code_hooks_daemon.qa.full_qa_gate`` there imports ``qa/__init__``
    before coverage starts, which is why ``addopts`` names a loader outside
    the package instead.
    """

    def test_the_primary_runs_plugin_arguments_leave_import_time_code_measured(
        self, tmp_path: Path
    ) -> None:
        plugin_args = _run_tests_sh_plugin_args(tmp_path / "lines.jsonl")

        missing = _missing_import_time_lines(plugin_args, tmp_path)

        assert missing == dict.fromkeys(_IMPORT_ONLY_MODULES, 0), (
            f"run_tests.sh's plugin arguments {plugin_args} import the package "
            "before coverage starts"
        )

    def test_an_extra_runs_plugin_arguments_leave_import_time_code_measured(
        self, tmp_path: Path
    ) -> None:
        matrix = _load_matrix()
        run = matrix.PlannedRun("3.13", "unit", 1, False)
        argv = matrix.extra_pytest_argv(Path(sys.executable), run, tmp_path / "lines.jsonl")
        plugin_args = argv[3 : len(argv) - len(matrix.SCOPE_PYTEST_ARGS[run.scope])]

        missing = _missing_import_time_lines(plugin_args, tmp_path)

        assert missing == dict.fromkeys(_IMPORT_ONLY_MODULES, 0)

    def test_the_suites_conftest_registers_the_plugin(self, pytestconfig: pytest.Config) -> None:
        assert pytestconfig.pluginmanager.get_plugin(PLUGIN) is not None

    def test_the_measurements_run_with_the_full_qa_sink_force_loaded(
        self, pytestconfig: pytest.Config
    ) -> None:
        """The two runs above inherit ``addopts``; this pins what it loads."""
        addopts: list[str] = pytestconfig.getini("addopts")
        assert "claude_code_hooks_daemon_full_qa_gate_loader" in addopts
        assert pytestconfig.pluginmanager.get_plugin(FULL_QA_GATE) is not None


class TestPytestLogParsing:
    def test_a_log_is_parsed_with_the_same_parser_run_tests_sh_uses(self, tmp_path: Path) -> None:
        matrix = _load_matrix()
        log = tmp_path / "run.log"
        log.write_text(
            "=========== short test summary info ===========\n"
            "FAILED tests/unit/test_a.py::test_b - AssertionError\n"
            "=========== 1 failed, 4 passed, 1 skipped in 0.50s ===========\n",
            encoding="utf-8",
        )

        outcome = matrix.outcome_from_log(log, exit_code=1, lines=tmp_path / "none.jsonl")

        assert outcome.summary["failed"] == 1
        assert outcome.summary["passed_all"] is False
        assert outcome.failed_tests == ["tests/unit/test_a.py::test_b"]

    def test_a_missing_log_is_red(self, tmp_path: Path) -> None:
        matrix = _load_matrix()

        outcome = matrix.outcome_from_log(
            tmp_path / "never-written.log", exit_code=0, lines=tmp_path / "none.jsonl"
        )

        assert outcome.summary["passed_all"] is False

    def test_the_recorded_first_error_lines_are_read_back(self, tmp_path: Path) -> None:
        matrix = _load_matrix()
        log = tmp_path / "run.log"
        log.write_text(
            "=========== short test summary info ===========\n"
            "ERROR tests/acceptance/test_a.py::test_b - test_a.py is a BLOCKING rel...\n"
            "=========== 4 passed, 1 error in 0.50s ===========\n",
            encoding="utf-8",
        )
        lines = tmp_path / "lines.jsonl"
        lines.write_text(
            json.dumps(
                {
                    "nodeid": "tests/acceptance/test_a.py::test_b",
                    "when": "setup",
                    "line": "test_a.py is a BLOCKING release gate and skipped: no daemon",
                }
            )
            + "\n",
            encoding="utf-8",
        )

        outcome = matrix.outcome_from_log(log, exit_code=1, lines=lines)

        assert outcome.first_error_lines == {
            "tests/acceptance/test_a.py::test_b": (
                "test_a.py is a BLOCKING release gate and skipped: no daemon"
            )
        }

    def test_an_extra_run_records_first_error_lines(self, tmp_path: Path) -> None:
        matrix = _load_matrix()
        run = matrix.PlannedRun("3.13", "rest", 2, False)
        lines = tmp_path / "lines.jsonl"

        argv = matrix.extra_pytest_argv(Path("/fake/py3.13/bin/python"), run, lines)

        assert argv[:3] == ["/fake/py3.13/bin/python", "-m", "pytest"]
        assert PLUGIN not in argv
        assert f"{OPTION}={lines}" in argv
        assert argv[-2:] == ["tests", "--ignore=tests/unit"]

    def test_a_nonzero_exit_over_a_clean_summary_is_red(self, tmp_path: Path) -> None:
        matrix = _load_matrix()
        log = tmp_path / "run.log"
        log.write_text("=========== 5 passed in 0.50s ===========\n", encoding="utf-8")

        outcome = matrix.outcome_from_log(log, exit_code=1, lines=tmp_path / "none.jsonl")
        assert outcome.summary["passed_all"] is False


class TestThePrimaryReport:
    def test_a_missing_tests_json_is_red(self, tmp_path: Path) -> None:
        matrix = _load_matrix()

        outcome = matrix.outcome_from_primary_report(tmp_path / "tests.json", exit_code=0)

        assert outcome.summary["passed_all"] is False

    def test_the_primary_report_is_read_back(self, tmp_path: Path) -> None:
        matrix = _load_matrix()
        path = tmp_path / "tests.json"
        path.write_text(json.dumps(_primary_report()), encoding="utf-8")

        outcome = matrix.outcome_from_primary_report(path, exit_code=0)

        assert outcome.summary["passed_all"] is True
        assert outcome.summary["passed"] == 10


class _RecordedPopen:
    """Stands in for ``subprocess.Popen``; records how each child was launched."""

    launches: ClassVar[list[dict[str, Any]]] = []

    def __init__(self, argv: list[str], **kwargs: Any) -> None:
        self.launches.append({"argv": argv, **kwargs})


class TestEveryChildRunCarriesTheFullQaLockProof:
    """Plan 00463: the extra-interpreter runs died with REFUSED (no lock held).

    The primary run took the host lock inside ``run_tests.sh``; the extra
    interpreters' whole-suite pytest runs were launched with no descriptor for
    it, so the sink refused them. The matrix runner now holds the lock itself
    and hands its descriptor to every child.
    """

    LOCK_FD = 41

    @pytest.fixture
    def matrix(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
        module = _load_matrix()
        monkeypatch.setattr(module, "QA_OUTPUT_DIR", tmp_path)
        monkeypatch.setattr(module, "TESTS_JSON", tmp_path / "tests.json")
        _RecordedPopen.launches = []
        monkeypatch.setattr(module.subprocess, "Popen", _RecordedPopen)
        return module

    def test_an_extra_interpreter_run_is_handed_the_lock_descriptor(self, matrix: Any) -> None:
        run = matrix.PlannedRun("3.12", "unit", 1, False)

        matrix.launch(run, Path("/fake/py3.12/bin/python"), lock_fd=self.LOCK_FD)

        assert _RecordedPopen.launches[0]["pass_fds"] == (self.LOCK_FD,)

    def test_the_primary_run_is_handed_the_descriptor_and_told_which_one(self, matrix: Any) -> None:
        run = matrix.PlannedRun("3.11", "all", 0, True)

        matrix.launch(run, Path(sys.executable), lock_fd=self.LOCK_FD)

        launch = _RecordedPopen.launches[0]
        assert launch["pass_fds"] == (self.LOCK_FD,)
        assert launch["env"]["FULL_QA_LOCK_INHERITED_FD"] == str(self.LOCK_FD)

    def test_the_runner_acquires_the_host_lock_and_passes_it_to_every_launch(self) -> None:
        text = MATRIX_SCRIPT.read_text(encoding="utf-8")

        assert "acquire_full_qa_lock(PROJECT_ROOT, reuse_inherited=True)" in text
        assert "lock_fd=" in text
