"""Per-leg checkpoints in the tests stage (Plan 00500 Task 2.3).

A host reboot mid-tests used to lose every leg. Each matrix leg now records its
own checkpoint the moment it finishes, and ``run_test_matrix.py --resume`` (what
``llm_qa.py all --resume`` passes down) re-runs only the legs that did not
finish green on the identical tree. Coverage is judged on the whole: the primary
leg (full suite, with coverage) is reused or re-run as one unit.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import threading
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
MATRIX_SCRIPT = PROJECT_ROOT / "scripts" / "qa" / "run_test_matrix.py"

_HEAD = "e" * 40
_SLOW = [{"nodeid": "tests/unit/test_a.py::test_slow", "phase": "call", "seconds": 9.5}]
_PRIMARY = ("3.11", "full")
_UNIT_12 = ("3.12", "unit")
_UNIT_13 = ("3.13", "unit")
_REST_12 = ("3.12", "rest")
_REST_13 = ("3.13", "rest")
_ALL_LEGS = [_PRIMARY, _UNIT_12, _UNIT_13, _REST_12, _REST_13]


def _load_matrix() -> Any:
    spec = importlib.util.spec_from_file_location(
        "run_test_matrix_resume_under_test", MATRIX_SCRIPT
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {MATRIX_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _Tree:
    def __init__(self) -> None:
        self.digest = "d1"

    def __call__(self) -> dict[str, str]:
        return {"head": _HEAD, "tree_digest": self.digest}


class _Job:
    def __init__(self, harness: _Harness, run: Any) -> None:
        self._harness = harness
        self._run = run

    def wait(self) -> Any:
        return self._harness.finish(self._run)


class _Harness:
    """Fake provisioning and launching over real files in ``qa_dir``."""

    def __init__(self, matrix: Any, qa_dir: Path) -> None:
        self.matrix = matrix
        self.qa_dir = qa_dir
        self.tree = _Tree()
        self.store = matrix.LegCheckpoints(qa_dir, tree=self.tree)
        self.started: list[tuple[str, str]] = []
        self.provisioned: list[str] = []
        self.red: set[tuple[str, str]] = set()
        self.hold: dict[tuple[str, str], Any] = {}
        self.mutate_tree_during: tuple[str, str] | None = None
        self.interrupt: tuple[str, str] | None = None

    def provision(self, version: str) -> Path:
        self.provisioned.append(version)
        return Path(f"/fake/py{version}/bin/python")

    def launch(self, run: Any, python: Path) -> _Job:
        self.started.append((run.version, run.scope))
        return _Job(self, run)

    def ensure_daemon(self) -> str | None:
        return None

    def finish(self, run: Any) -> Any:
        key = (run.version, run.scope)
        gate = self.hold.get(key)
        if gate is not None:
            gate()
        if self.interrupt == key:
            raise KeyboardInterrupt
        if self.mutate_tree_during == key:
            self.tree.digest = "mutated"
        failed = key in self.red
        names = [f"tests/unit/test_x.py::test_{run.version}"] if failed else []
        summary = {
            "total": 10,
            "passed": 9 if failed else 10,
            "failed": 1 if failed else 0,
            "skipped": 0,
            "errors": 0,
            "passed_all": not failed,
        }
        if run.primary:
            log = self.matrix.TESTS_JSON
            log.write_text(
                json.dumps({"summary": summary, "tests": [], "coverage": {"percent": 96.0}}),
                encoding="utf-8",
            )
        else:
            log = self.qa_dir / f"tests-py{run.version}-{run.scope}.log"
            log.write_text(f"leg {key} output", encoding="utf-8")
        return self.matrix.RunOutcome(
            exit_code=1 if failed else 0,
            summary=summary,
            failed_tests=names,
            log=log,
            first_error_lines=dict.fromkeys(names, "boom"),
            slowest_tests=_SLOW,
        )

    def deps(self, *, resume: bool) -> Any:
        return self.matrix.MatrixDeps(
            provision=self.provision,
            launch=self.launch,
            ensure_daemon=self.ensure_daemon,
            clock=lambda: 3.0,
            checkpoints=self.store,
            resume=resume,
        )

    def run(self, *, resume: bool) -> list[Any]:
        plan = self.matrix.plan_runs(["3.11", "3.12", "3.13"], "3.11")
        return list(
            self.matrix.run_matrix(plan, Path("/fake/py3.11/bin/python"), self.deps(resume=resume))
        )


@pytest.fixture
def harness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> _Harness:
    matrix = _load_matrix()
    qa_dir = tmp_path / "qa"
    qa_dir.mkdir()
    monkeypatch.setattr(matrix, "QA_OUTPUT_DIR", qa_dir)
    monkeypatch.setattr(matrix, "TESTS_JSON", qa_dir / "tests.json")
    return _Harness(matrix, qa_dir)


class TestEveryLegCheckpointsItself:
    def test_a_normal_run_records_one_checkpoint_per_leg(self, harness: _Harness) -> None:
        harness.run(resume=False)

        assert len(list(harness.qa_dir.glob("leg-*.checkpoint.json"))) == 5
        for version, scope in _ALL_LEGS:
            found = harness.store.check(f"py{version}-{scope}")
            assert not isinstance(found, str), found

    def test_a_normal_run_never_reuses_a_leg(self, harness: _Harness) -> None:
        harness.run(resume=False)
        harness.started.clear()

        results = harness.run(resume=False)

        assert sorted(harness.started) == sorted(_ALL_LEGS)
        assert not any(r.reused for r in results)

    def test_a_leg_is_recorded_the_moment_it_finishes_not_when_the_phase_ends(
        self, harness: _Harness
    ) -> None:
        """The primary leg is held open: the extras' checkpoints must already exist."""
        seen: dict[str, bool] = {}

        def primary_waits_for_the_extras() -> None:
            deadline = threading.Event()
            for _ in range(200):
                if all(harness.store.path(f"py{v}-unit").exists() for v in ("3.12", "3.13")):
                    seen["extras_recorded_first"] = True
                    return
                deadline.wait(0.025)
            seen["extras_recorded_first"] = False

        harness.hold[_PRIMARY] = primary_waits_for_the_extras
        harness.run(resume=False)

        assert seen == {"extras_recorded_first": True}

    def test_a_leg_that_never_finishes_leaves_no_checkpoint(self, harness: _Harness) -> None:
        harness.run(resume=False)
        harness.interrupt = _REST_12

        with pytest.raises(KeyboardInterrupt):
            harness.run(resume=False)

        assert not harness.store.path("py3.12-rest").exists(), "an old pass must not survive"
        assert harness.store.path("py3.12-unit").exists()

    def test_a_failed_leg_is_recorded_as_failed(self, harness: _Harness) -> None:
        harness.red.add(_UNIT_12)
        harness.run(resume=False)
        assert "did not pass" in str(harness.store.check("py3.12-unit"))


class TestResume:
    def test_nothing_is_run_when_every_leg_passed_on_this_tree(self, harness: _Harness) -> None:
        harness.run(resume=False)
        harness.started.clear()
        harness.provisioned.clear()

        results = harness.run(resume=True)

        assert harness.started == []
        assert harness.provisioned == [], "a reused leg must not provision its interpreter"
        assert all(r.reused for r in results)
        assert all(r.outcome.summary["passed_all"] for r in results)

    def test_only_the_legs_that_did_not_finish_green_are_re_run(self, harness: _Harness) -> None:
        harness.red.add(_REST_13)
        harness.run(resume=False)
        harness.red.clear()
        harness.started.clear()

        results = harness.run(resume=True)

        assert harness.started == [_REST_13]
        assert [r.reused for r in results] == [True, True, True, True, False]

    def test_an_interrupted_run_resumes_from_the_legs_that_finished(
        self, harness: _Harness
    ) -> None:
        harness.interrupt = _REST_12
        with pytest.raises(KeyboardInterrupt):
            harness.run(resume=False)
        harness.interrupt = None
        harness.started.clear()

        harness.run(resume=True)

        assert sorted(harness.started) == sorted([_REST_12, _REST_13])

    def test_a_missing_checkpoint_is_run(self, harness: _Harness) -> None:
        harness.run(resume=False)
        harness.store.path("py3.13-unit").unlink()
        harness.started.clear()

        harness.run(resume=True)

        assert harness.started == [_UNIT_13]

    def test_another_tree_re_runs_every_leg(self, harness: _Harness) -> None:
        harness.run(resume=False)
        harness.tree.digest = "edited"
        harness.started.clear()

        harness.run(resume=True)

        assert sorted(harness.started) == sorted(_ALL_LEGS)

    def test_a_leg_that_saw_the_tree_change_certifies_nothing(self, harness: _Harness) -> None:
        harness.mutate_tree_during = _UNIT_12
        harness.run(resume=False)
        harness.tree.digest = "d1"
        harness.mutate_tree_during = None
        harness.started.clear()

        harness.run(resume=True)

        assert _UNIT_12 in harness.started

    def test_a_rewritten_log_is_not_the_one_the_leg_wrote(self, harness: _Harness) -> None:
        harness.run(resume=False)
        (harness.qa_dir / "tests-py3.12-unit.log").write_text("someone else", encoding="utf-8")
        harness.started.clear()

        harness.run(resume=True)

        assert harness.started == [_UNIT_12]

    def test_the_primary_is_reused_only_as_a_unit_and_re_runs_when_it_failed(
        self, harness: _Harness
    ) -> None:
        harness.red.add(_PRIMARY)
        harness.run(resume=False)
        harness.red.clear()
        harness.started.clear()

        results = harness.run(resume=True)

        assert harness.started == [_PRIMARY]
        assert [r.reused for r in results] == [False, True, True, True, True]

    def test_a_reused_primary_restores_its_report_for_the_coverage_verdict(
        self, harness: _Harness
    ) -> None:
        harness.run(resume=False)
        harness.matrix.TESTS_JSON.unlink()

        harness.run(resume=True)

        restored = json.loads(harness.matrix.TESTS_JSON.read_text(encoding="utf-8"))
        assert restored["coverage"] == {"percent": 96.0}

    def test_a_reused_primary_whose_saved_report_was_tampered_with_is_re_run(
        self, harness: _Harness
    ) -> None:
        harness.run(resume=False)
        saved = next(harness.qa_dir.glob("tests-py3.11-full.report.json"))
        saved.write_text("{}", encoding="utf-8")
        harness.started.clear()

        harness.run(resume=True)

        assert harness.started == [_PRIMARY]


class TestTheReportKeepsItsShape:
    def test_reused_legs_stay_in_interpreters_marked_reused_with_their_slowest_tests(
        self, harness: _Harness
    ) -> None:
        harness.red.add(_REST_13)
        harness.run(resume=False)
        harness.red.clear()
        results = harness.run(resume=True)
        harness.matrix.TESTS_JSON.write_text(
            json.dumps({"tests": [], "coverage": {"percent": 96.0}}), encoding="utf-8"
        )

        report = harness.matrix.build_report(results, {"coverage": {"percent": 96.0}}, 1.0)

        entries = {(e["version"], e["scope"]): e for e in report["interpreters"]}
        assert set(entries) == set(_ALL_LEGS)
        assert entries[_UNIT_12]["reused"] is True
        assert entries[_REST_13]["reused"] is False
        assert entries[_UNIT_12]["slowest_tests"] == _SLOW
        assert entries[_UNIT_12]["passed_all"] is True
        assert entries[_UNIT_12]["passed"] == 10
        assert report["summary"]["passed_all"] is True
        assert report["summary"]["total"] == 50

    def test_the_summary_line_marks_a_reused_leg(
        self, harness: _Harness, capsys: pytest.CaptureFixture[str]
    ) -> None:
        harness.run(resume=False)
        results = harness.run(resume=True)
        report = harness.matrix.build_report(results, {}, 1.0)

        harness.matrix._print_runs(report)

        assert capsys.readouterr().out.count("(reused)") == 5


class TestResumeIsOptIn:
    def test_the_flag_is_read_from_the_arguments(self) -> None:
        matrix = _load_matrix()
        assert matrix.resume_requested([]) is False
        assert matrix.resume_requested([matrix.RESUME_ARG]) is True
        assert matrix.RESUME_ARG == "--resume"

    def test_an_unknown_argument_fails_fast(self) -> None:
        matrix = _load_matrix()
        with pytest.raises(SystemExit):
            matrix.resume_requested(["--bogus"])


_TREE = {"head": _HEAD, "tree_digest": "d1"}


class TestLegCheckpointStore:
    """The store itself: atomic write, and the conditions under which a leg is reusable."""

    @pytest.fixture
    def tree(self) -> _Tree:
        return _Tree()

    @pytest.fixture
    def store(self, tmp_path: Path, tree: _Tree) -> Any:
        return _load_matrix().LegCheckpoints(tmp_path, tree=tree)

    @pytest.fixture
    def log(self, tmp_path: Path) -> Path:
        path = tmp_path / "leg.log"
        path.write_text("42 passed", encoding="utf-8")
        return path

    @staticmethod
    def _save(store: Any, **overrides: Any) -> None:
        arguments: dict[str, Any] = {
            "before": _TREE,
            "after": _TREE,
            "exit_code": 0,
            "passed": True,
            "duration_seconds": 12.34,
            "artefact": None,
            "payload": {"k": "v"},
        }
        store.save("py3.12-unit", **{**arguments, **overrides})

    def test_a_passed_leg_on_the_same_tree_is_reusable(self, store: Any, log: Path) -> None:
        self._save(store, artefact=log)
        found = store.check("py3.12-unit")
        assert (found.payload, found.duration_seconds) == ({"k": "v"}, 12.3)

    def test_a_leg_without_an_artefact_is_reusable_on_its_verdict_alone(self, store: Any) -> None:
        self._save(store)
        assert not isinstance(store.check("py3.12-unit"), str)

    @pytest.mark.parametrize(
        ("overrides", "reason"),
        [
            ({"passed": False}, "did not pass"),
            ({"exit_code": 1}, "did not pass"),
            ({"after": {"head": _HEAD, "tree_digest": "other"}}, "changed during"),
            ({"artefact": Path("/nonexistent/never-written.log")}, "not the one"),
        ],
    )
    def test_a_leg_that_cannot_certify_the_tree_is_not_reusable(
        self, store: Any, log: Path, overrides: dict[str, Any], reason: str
    ) -> None:
        self._save(store, **{"artefact": log, **overrides})
        assert reason in str(store.check("py3.12-unit"))

    def test_no_checkpoint_says_so(self, store: Any) -> None:
        assert "no checkpoint" in str(store.check("py3.12-unit"))

    def test_another_tree_is_stale_and_an_unreadable_tree_reuses_nothing(
        self, store: Any, tree: _Tree
    ) -> None:
        self._save(store)
        tree.digest = "edited"
        assert "uncommitted" in str(store.check("py3.12-unit"))
        tree.digest = "d1"
        store.tree = lambda: None
        assert isinstance(store.check("py3.12-unit"), str)

    def test_an_unreadable_tree_before_the_leg_records_nothing(self, store: Any) -> None:
        self._save(store, before=None)
        assert not store.path("py3.12-unit").exists()

    def test_an_artefact_rewritten_or_removed_since_is_not_the_one_the_leg_wrote(
        self, store: Any, log: Path
    ) -> None:
        self._save(store, artefact=log)
        log.write_text("a different run", encoding="utf-8")
        assert "not the one" in str(store.check("py3.12-unit"))
        log.unlink()
        assert "not the one" in str(store.check("py3.12-unit"))

    def test_a_torn_or_foreign_file_reads_as_no_checkpoint(self, store: Any) -> None:
        store.path("py3.12-unit").write_text("{not json", encoding="utf-8")
        assert "no checkpoint" in str(store.check("py3.12-unit"))
        store.path("py3.12-unit").write_text("[1]", encoding="utf-8")
        assert "no checkpoint" in str(store.check("py3.12-unit"))

    def test_a_record_missing_its_payload_or_duration_is_not_reusable(self, store: Any) -> None:
        self._save(store)
        record = store.read("py3.12-unit")
        del record["payload"]
        store.write("py3.12-unit", record)
        assert "incomplete" in str(store.check("py3.12-unit"))
        self._save(store)
        record = store.read("py3.12-unit")
        del record["duration_seconds"]
        store.write("py3.12-unit", record)
        assert "incomplete" in str(store.check("py3.12-unit"))

    def test_the_write_is_a_temp_file_and_a_replace_leaving_no_temp(
        self, store: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        replaced: list[tuple[str, str]] = []
        real = os.replace

        def spy(src: Any, dst: Any) -> None:
            replaced.append((str(src), str(dst)))
            real(src, dst)

        monkeypatch.setattr(os, "replace", spy)
        self._save(store)

        assert replaced and replaced[0][1] == str(store.path("py3.12-unit"))
        assert replaced[0][0] != replaced[0][1]
        assert [p.name for p in tmp_path.iterdir()] == [store.path("py3.12-unit").name]

    def test_invalidate_removes_a_checkpoint_and_tolerates_none(self, store: Any) -> None:
        self._save(store)
        store.invalidate("py3.12-unit")
        assert not store.path("py3.12-unit").exists()
        store.invalidate("py3.12-unit")
