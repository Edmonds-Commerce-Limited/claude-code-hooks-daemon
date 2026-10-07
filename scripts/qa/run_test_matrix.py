#!/usr/bin/env python3
"""The QA tests stage: the suite under every Python version CI runs (00466 N110).

CI's QA job runs the suite under each version in its matrix. A gate that runs
one interpreter passes a defect that only exists on another, and the merge it
approved turns CI red (N24: a stdlib cost that is quadratic only from 3.12).
So this stage reads the matrix out of ``.github/workflows/qa.yml`` at run
time and runs the whole suite under every version in it:

- The PRIMARY interpreter (the one running this script: the checkout's venv)
  runs ``run_tests.sh`` exactly as before -- all of ``tests/`` with coverage,
  writing ``tests.json``.
- Every other matrix version is an EXTRA. It gets its own venv under
  ``untracked/qa-interpreters/`` (never under the ``untracked/venv-*`` glob the
  daemon's venv resolver scans), provisioned from ``uv.lock`` with ``uv``.
- Phase 1 runs the primary and each extra's ``tests/unit`` at the same time.
  Phase 2 then runs each extra's remaining directories, one interpreter at a
  time: they drive the checkout's one live daemon (acceptance tests toggle its
  transport), so two of them at once would contend. The daemon is started
  before each of them if it has idled out.
- Every run records each failed test's first error line (the
  ``first_error_lines`` pytest plugin, which ``tests/conftest.py`` loads), and
  the report carries it as that test's ``reason``.

An extra interpreter that cannot be provisioned FAILS the stage and says so;
the stage never quietly runs fewer versions than CI. Its report is written
over ``tests.json`` with a per-run ``interpreters`` list.

Each leg also writes its own checkpoint (:class:`LegCheckpoints`) the moment it
finishes. ``--resume`` (what ``llm_qa.py all --resume`` passes down) runs only
the legs with no checkpoint that PASSED on the identical tree; the others run
as normal. Coverage is judged on the whole: the primary leg is the only one
with coverage and is reused or re-run as one unit. Without ``--resume`` no leg
is ever reused.
"""

from __future__ import annotations

import functools
import importlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import ModuleType
from typing import IO, Any, Final, NamedTuple, Protocol

import yaml

from claude_code_hooks_daemon.qa.first_error_lines import (
    OPTION as FIRST_ERROR_LINES_OPTION,
)
from claude_code_hooks_daemon.qa.first_error_lines import read_first_error_lines
from claude_code_hooks_daemon.qa.full_qa_lock import acquire_full_qa_lock
from claude_code_hooks_daemon.qa.pytest_text_report import (
    SLOWEST_DURATIONS_ARGS,
    finalize_passed_all,
    parse_pytest_text_output,
    parse_slowest_durations,
)
from claude_code_hooks_daemon.utils.path_containment import path_is_relative_to

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parent.parent.parent
SCRIPTS_DIR: Final[Path] = PROJECT_ROOT / "scripts" / "qa"
QA_OUTPUT_DIR: Final[Path] = PROJECT_ROOT / "untracked" / "qa"
TESTS_JSON: Final[Path] = QA_OUTPUT_DIR / "tests.json"
CI_WORKFLOW: Final[Path] = PROJECT_ROOT / ".github" / "workflows" / "qa.yml"
CI_JOB: Final[str] = "qa"
CI_MATRIX_KEY: Final[str] = "python-version"
EXTRA_VENVS_DIR: Final[Path] = PROJECT_ROOT / "untracked" / "qa-interpreters"
DAEMON_CLI: Final[Path] = PROJECT_ROOT / "bin" / "hooks-daemon"
DAEMON_CLI_TIMEOUT_SECONDS: Final[int] = 120

SCOPE_FULL: Final[str] = "full"
SCOPE_UNIT: Final[str] = "unit"
SCOPE_REST: Final[str] = "rest"
PHASE_PARALLEL: Final[int] = 1
PHASE_SERIAL: Final[int] = 2

#: The two extra-interpreter scopes. Together they are exactly ``tests/``:
#: ``unit`` is the hermetic bulk that can overlap the primary run, ``rest`` is
#: everything else, which reaches the live daemon.
SCOPE_PYTEST_ARGS: Final[dict[str, list[str]]] = {
    SCOPE_UNIT: ["tests/unit"],
    SCOPE_REST: ["tests", "--ignore=tests/unit"],
}

_VERSION_PATTERN: Final[re.Pattern[str]] = re.compile(r"^\d+\.\d+$")
_VERSION_PROBE: Final[str] = "import sys; print('%d.%d' % sys.version_info[:2])"
_VENV_PROBE: Final[str] = (
    "import sys, pytest, claude_code_hooks_daemon as p; "
    "print('%d.%d' % sys.version_info[:2]); print(p.__file__)"
)


class MatrixError(RuntimeError):
    """CI's Python matrix could not be read, so no plan can be trusted."""


class ProvisionError(RuntimeError):
    """An extra interpreter or its venv could not be provisioned."""


class PlannedRun(NamedTuple):
    """One pytest invocation the stage owes."""

    version: str
    scope: str
    phase: int
    primary: bool


class RunOutcome(NamedTuple):
    """What one finished run reported.

    ``first_error_lines`` maps a failed test's node id to the first line of
    its error, as the ``first_error_lines`` pytest plugin recorded it.
    """

    exit_code: int
    summary: dict[str, Any]
    failed_tests: list[str]
    log: Path
    first_error_lines: dict[str, str]
    #: ``{nodeid, phase, seconds}`` records for the run's slowest tests.
    slowest_tests: Sequence[dict[str, Any]] = ()


class RunResult(NamedTuple):
    """A planned run and what became of it; ``outcome`` is None when it never ran.

    ``reused`` marks a result taken from a checkpoint (``--resume``); its
    ``duration_seconds`` is then the run that produced it.
    """

    run: PlannedRun
    outcome: RunOutcome | None
    duration_seconds: float
    error: str | None
    reused: bool = False


class Job(Protocol):
    """A started run the stage can wait on."""

    def wait(self) -> RunOutcome: ...


# ── Per-leg checkpoints ────────────────────────────────────────────

#: The argument ``llm_qa.py all --resume`` passes to this stage.
RESUME_ARG: Final[str] = "--resume"

#: What a leg records when the tree changed while it ran: matches no tree.
TREE_CHANGED: Final[str] = "changed-during-run"

_STATE_DIGEST: Final[str] = "tree_digest"
_CK_PASSED: Final[str] = "passed"
_CK_EXIT_CODE: Final[str] = "exit_code"
_CK_DURATION: Final[str] = "duration_seconds"
_CK_ARTEFACT: Final[str] = "artefact"
_CK_ARTEFACT_SHA: Final[str] = "artefact_sha256"
_CK_PAYLOAD: Final[str] = "payload"
_DURATION_DECIMALS: Final[int] = 1


def _load_gate_provenance() -> ModuleType:
    """``llm_qa``: the one definition of the identical tree, shared with the per-step provenance.

    It is a sibling script rather than a package module (it must run under any
    python3, before a venv), so it is imported by its directory.
    """
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))
    return importlib.import_module("llm_qa")


_GATE: Final[ModuleType] = _load_gate_provenance()


def checkout_tree() -> dict[str, str] | None:
    """HEAD plus a digest of every uncommitted change of this checkout; None when unreadable."""
    state: dict[str, str] | None = _GATE.worktree_state(PROJECT_ROOT)
    return state


class LegCheckpoint(NamedTuple):
    """A reusable leg: what it reported, and how long the run that produced it took."""

    payload: dict[str, Any]
    duration_seconds: float


class LegCheckpoints:
    """The checkpoint files of one QA output directory, one per leg key.

    A checkpoint is reused only when the tree is the one the leg judged (and
    was unchanged from just before to just after the leg), the leg exited 0
    and passed, and the artefact it points at hashes to what the leg wrote.
    """

    def __init__(self, qa_dir: Path, *, tree: Callable[[], dict[str, str] | None]) -> None:
        self.qa_dir = qa_dir
        self.tree = tree

    def path(self, key: str) -> Path:
        """The checkpoint file of the leg ``key``."""
        return self.qa_dir / f"leg-{key}.checkpoint.json"

    def read(self, key: str) -> dict[str, Any]:
        """The recorded checkpoint; missing, torn or foreign reads as none at all."""
        try:
            data = json.loads(self.path(key).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def write(self, key: str, record: Mapping[str, Any]) -> None:
        """Write ``record`` to a temp file and rename it over the checkpoint.

        A run killed part-way leaves the previous complete file, never a torn one.
        """
        self.qa_dir.mkdir(parents=True, exist_ok=True)
        target = self.path(key)
        temp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
        temp.write_text(json.dumps(record, indent=2), encoding="utf-8")
        temp.replace(target)

    def invalidate(self, key: str) -> None:
        """Drop the checkpoint as a leg starts: an interrupted leg must leave none behind."""
        self.path(key).unlink(missing_ok=True)

    def save(
        self,
        key: str,
        *,
        before: dict[str, str] | None,
        after: dict[str, str] | None,
        exit_code: int,
        passed: bool,
        duration_seconds: float,
        artefact: Path | None,
        payload: Mapping[str, Any],
    ) -> None:
        """Record a finished leg, judged on the tree just before and just after it.

        A leg that saw the tree change certifies no tree. A tree that could not
        be read before the leg records nothing.
        """
        if before is None:
            return
        state = before if after == before else {**before, _STATE_DIGEST: TREE_CHANGED}
        record: dict[str, Any] = {
            **state,
            _CK_PASSED: passed,
            _CK_EXIT_CODE: exit_code,
            _CK_DURATION: round(duration_seconds, _DURATION_DECIMALS),
            _CK_PAYLOAD: dict(payload),
        }
        if artefact is not None:
            record[_CK_ARTEFACT] = str(artefact)
            record[_CK_ARTEFACT_SHA] = _GATE.output_digest(artefact)
        self.write(key, record)

    def check(self, key: str) -> LegCheckpoint | str:
        """The reusable leg, or the reason it must run again."""
        record = self.read(key)
        if not record:
            return "no checkpoint for this leg"
        stale: str | None = _GATE.stale_reason(record, self.tree())
        if stale is not None:
            return stale
        if record.get(_CK_PASSED) is not True or record.get(_CK_EXIT_CODE) != 0:
            return "the recorded leg did not pass"
        payload = record.get(_CK_PAYLOAD)
        duration = record.get(_CK_DURATION)
        if (
            not isinstance(payload, dict)
            or isinstance(duration, bool)
            or not isinstance(duration, (int, float))
        ):
            return "the checkpoint is incomplete"
        if _CK_ARTEFACT in record and (
            record.get(_CK_ARTEFACT_SHA) is None
            or _GATE.output_digest(Path(str(record[_CK_ARTEFACT]))) != record[_CK_ARTEFACT_SHA]
        ):
            return "the artefact on disk is not the one that leg wrote"
        return LegCheckpoint(payload=payload, duration_seconds=float(duration))


def resume_requested(argv: Sequence[str]) -> bool:
    """Whether ``argv`` asks to resume; any other argument fails fast."""
    unknown = [argument for argument in argv if argument != RESUME_ARG]
    if unknown:
        raise SystemExit(
            f"run_test_matrix.py: unknown arguments {unknown}; the only option is {RESUME_ARG}"
        )
    return RESUME_ARG in argv


class MatrixDeps(NamedTuple):
    """The side effects ``run_matrix`` needs, injectable so tests need no interpreters.

    ``checkpoints`` records every leg as it finishes; with ``resume`` a leg
    that passed on the identical tree is reused instead of run.
    """

    provision: Callable[[str], Path]
    launch: Callable[[PlannedRun, Path], Job]
    ensure_daemon: Callable[[], str | None]
    clock: Callable[[], float]
    checkpoints: LegCheckpoints | None = None
    resume: bool = False


# ── The plan ───────────────────────────────────────────────────────


def ci_python_versions(workflow: Path = CI_WORKFLOW) -> list[str]:
    """CI's QA-job Python matrix, read from the workflow file.

    Raises:
        MatrixError: the file is missing, unparseable, has no such matrix, an
            empty one, or an entry that is not a quoted ``X.Y`` string. An
            unquoted ``3.10`` is the YAML float ``3.1``, so it is refused
            rather than read as a different version.
    """
    try:
        document = yaml.safe_load(workflow.read_text(encoding="utf-8"))
    except OSError as exc:
        raise MatrixError(f"cannot read CI workflow {workflow}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise MatrixError(f"cannot parse CI workflow {workflow}: {exc}") from exc

    versions: Any = document
    for key in ("jobs", CI_JOB, "strategy", "matrix", CI_MATRIX_KEY):
        if not isinstance(versions, dict) or key not in versions:
            raise MatrixError(f"{workflow} has no jobs.{CI_JOB}.strategy.matrix.{CI_MATRIX_KEY}")
        versions = versions[key]

    if not isinstance(versions, list) or not versions:
        raise MatrixError(f"{workflow}: the {CI_MATRIX_KEY} matrix is empty or not a list")
    for version in versions:
        if not isinstance(version, str):
            raise MatrixError(
                f"{workflow}: matrix entry {version!r} is not a string; quote it, or "
                "YAML reads 3.10 as 3.1"
            )
        if not _VERSION_PATTERN.match(version):
            raise MatrixError(f"{workflow}: matrix entry {version!r} is not an X.Y version")
    return list(versions)


def plan_runs(ci_versions: Sequence[str], primary_version: str) -> list[PlannedRun]:
    """Every run the stage owes: the primary in full, each extra in two scopes."""
    extras = [version for version in ci_versions if version != primary_version]
    plan = [PlannedRun(primary_version, SCOPE_FULL, PHASE_PARALLEL, True)]
    plan += [PlannedRun(version, SCOPE_UNIT, PHASE_PARALLEL, False) for version in extras]
    plan += [PlannedRun(version, SCOPE_REST, PHASE_SERIAL, False) for version in extras]
    return plan


def fully_covered_versions(plan: Sequence[PlannedRun]) -> set[str]:
    """The versions the plan runs ALL of ``tests/`` under."""
    scopes: dict[str, set[str]] = {}
    for run in plan:
        scopes.setdefault(run.version, set()).add(run.scope)
    return {
        version
        for version, have in scopes.items()
        if SCOPE_FULL in have or set(SCOPE_PYTEST_ARGS) <= have
    }


# ── Running it ─────────────────────────────────────────────────────


def _provision_or_error(deps: MatrixDeps, version: str) -> Path | ProvisionError:
    """The venv interpreter for ``version``, or the reason there is none.

    The error is RETURNED, not swallowed: ``run_matrix`` turns it into a
    not-run result that fails the stage and is printed with the verdict.
    """
    try:
        return deps.provision(version)
    except ProvisionError as exc:
        return exc


def run_matrix(
    plan: Sequence[PlannedRun], primary_python: Path, deps: MatrixDeps
) -> list[RunResult]:
    """Execute ``plan`` and return one result per planned run, in plan order.

    The primary starts first and before any provisioning, since it is the
    longest run. An extra whose provisioning fails gets an error result for
    each of its runs and nothing is launched for it.
    """
    provisioned: dict[str, Path | ProvisionError] = {}
    results: dict[PlannedRun, RunResult] = {}

    def python_for(run: PlannedRun) -> Path | None:
        if run.primary:
            return primary_python
        if run.version not in provisioned:
            provisioned[run.version] = _provision_or_error(deps, run.version)
        found = provisioned[run.version]
        return found if isinstance(found, Path) else None

    def not_run(run: PlannedRun) -> RunResult:
        reason = provisioned.get(run.version, "not provisioned")
        return RunResult(run, None, 0.0, f"Python {run.version} was NOT tested: {reason}")

    checkpoints = deps.checkpoints

    def reuse(run: PlannedRun) -> RunResult | None:
        """The leg's checkpoint as a result, when ``--resume`` and the checkpoint allow it."""
        if checkpoints is None or not deps.resume:
            return None
        found = checkpoints.check(leg_key(run))
        if isinstance(found, str):
            print(f"  {_label(run)}: running ({found})")
            return None
        if run.primary:
            _restore_primary_report(checkpoints, run)
        print(f"  {_label(run)}: reused, passed on this tree (took {found.duration_seconds}s)")
        return RunResult(
            run, _outcome_from_payload(found.payload), found.duration_seconds, None, True
        )

    def begin(run: PlannedRun) -> dict[str, str] | None:
        """Drop any old checkpoint as the leg starts; return the tree it starts on."""
        if checkpoints is None:
            return None
        checkpoints.invalidate(leg_key(run))
        return checkpoints.tree()

    def finish(run: PlannedRun, job: Job, before: dict[str, str] | None, began: float) -> RunResult:
        """Wait for the leg and checkpoint it at once, whatever else is still running."""
        outcome = job.wait()
        duration = deps.clock() - began
        if checkpoints is not None:
            _checkpoint_leg(checkpoints, run, outcome, before, duration)
        return RunResult(run, outcome, duration, None)

    started: list[tuple[PlannedRun, Job, dict[str, str] | None, float]] = []
    for run in (r for r in plan if r.phase == PHASE_PARALLEL):
        cached = reuse(run)
        if cached is not None:
            results[run] = cached
            continue
        python = python_for(run)
        if python is None:
            results[run] = not_run(run)
            continue
        before = begin(run)
        started.append((run, deps.launch(run, python), before, deps.clock()))
    if started:
        # One waiter per leg, so each leg is checkpointed the moment IT ends
        # rather than when the slowest leg before it in line does.
        with ThreadPoolExecutor(max_workers=len(started)) as pool:
            pending = [
                (run, pool.submit(finish, run, job, before, began))
                for run, job, before, began in started
            ]
            for run, future in pending:
                results[run] = future.result()

    for run in (r for r in plan if r.phase == PHASE_SERIAL):
        cached = reuse(run)
        if cached is not None:
            results[run] = cached
            continue
        python = python_for(run)
        if python is None:
            results[run] = not_run(run)
            continue
        # Before EVERY serial run, not once: the daemon exits after
        # idle_timeout_seconds without traffic, and a run's later directories
        # can go longer than that without touching it (00466 N196).
        daemon_note = deps.ensure_daemon()
        if daemon_note is not None:
            print(daemon_note)
        before = begin(run)
        began = deps.clock()
        results[run] = finish(run, deps.launch(run, python), before, began)

    return [results[run] for run in plan]


def leg_key(run: PlannedRun) -> str:
    """The checkpoint key of one leg."""
    return f"py{run.version}-{run.scope}"


def _primary_report_copy(checkpoints: LegCheckpoints, run: PlannedRun) -> Path:
    """Where the primary leg's report is kept for reuse.

    ``tests.json`` is overwritten by the merged report when the stage ends, so
    the primary's own report (the only one with coverage) needs a copy the
    checkpoint can hash.
    """
    return checkpoints.qa_dir / f"tests-py{run.version}-{run.scope}.report.json"


def _restore_primary_report(checkpoints: LegCheckpoints, run: PlannedRun) -> None:
    """Put the primary's checkpointed report back as ``tests.json``, for the coverage verdict."""
    shutil.copyfile(_primary_report_copy(checkpoints, run), TESTS_JSON)


def _payload_from_outcome(outcome: RunOutcome) -> dict[str, Any]:
    return {
        "exit_code": outcome.exit_code,
        "summary": outcome.summary,
        "failed_tests": outcome.failed_tests,
        "log": str(outcome.log),
        "first_error_lines": outcome.first_error_lines,
        "slowest_tests": list(outcome.slowest_tests),
    }


def _outcome_from_payload(payload: Mapping[str, Any]) -> RunOutcome:
    return RunOutcome(
        exit_code=int(payload["exit_code"]),
        summary=dict(payload["summary"]),
        failed_tests=list(payload["failed_tests"]),
        log=Path(payload["log"]),
        first_error_lines=dict(payload["first_error_lines"]),
        slowest_tests=list(payload["slowest_tests"]),
    )


def _checkpoint_leg(
    checkpoints: LegCheckpoints,
    run: PlannedRun,
    outcome: RunOutcome,
    before: dict[str, str] | None,
    duration: float,
) -> None:
    """Record a finished leg, judged on the tree just before and just after it."""
    artefact: Path | None = outcome.log if outcome.log.is_file() else None
    if run.primary and artefact is not None:
        # Atomic like the checkpoint itself, so a kill leaves no torn copy.
        copy = _primary_report_copy(checkpoints, run)
        temp = copy.with_name(f".{copy.name}.{os.getpid()}.tmp")
        shutil.copyfile(artefact, temp)
        temp.replace(copy)
        artefact = copy
    checkpoints.save(
        leg_key(run),
        before=before,
        after=checkpoints.tree(),
        exit_code=outcome.exit_code,
        passed=bool(outcome.summary.get("passed_all", False)),
        duration_seconds=duration,
        artefact=artefact,
        payload=_payload_from_outcome(outcome),
    )


def _label(run: PlannedRun) -> str:
    return f"py{run.version} {run.scope}"


_COUNT_KEYS: Final[tuple[str, ...]] = ("total", "passed", "failed", "skipped", "errors")


def build_report(
    results: Sequence[RunResult], primary_report: dict[str, Any], wall_seconds: float
) -> dict[str, Any]:
    """The stage's ``tests.json``: the primary's report, widened to every run.

    Counts are summed over every run, ``passed_all`` holds only when every
    planned run ran and passed, and each failure from an extra is named with
    the interpreter and scope it failed under.
    """
    summary: dict[str, Any] = dict.fromkeys(_COUNT_KEYS, 0)
    tests: list[dict[str, Any]] = list(primary_report.get("tests", []))
    interpreters: list[dict[str, Any]] = []
    errors: list[str] = []
    passed_all = True

    for result in results:
        run = result.run
        entry: dict[str, Any] = {
            "version": run.version,
            "scope": run.scope,
            "primary": run.primary,
            "duration_seconds": round(result.duration_seconds, 1),
            "error": result.error,
            "reused": result.reused,
        }
        if result.outcome is None:
            passed_all = False
            errors.append(result.error or f"{_label(run)} did not run")
            interpreters.append(entry)
            continue

        run_summary = result.outcome.summary
        run_passed = bool(run_summary.get("passed_all", False))
        passed_all = passed_all and run_passed
        for key in _COUNT_KEYS:
            summary[key] += int(run_summary.get(key, 0))
        entry.update({key: int(run_summary.get(key, 0)) for key in _COUNT_KEYS})
        entry.update(
            {
                "passed_all": run_passed,
                "exit_code": result.outcome.exit_code,
                "log": str(result.outcome.log),
                "slowest_tests": list(result.outcome.slowest_tests),
            }
        )
        interpreters.append(entry)

        if run.primary:
            continue
        named: list[dict[str, Any]] = []
        for node_id in result.outcome.failed_tests:
            record: dict[str, Any] = {"name": f"[{_label(run)}] {node_id}", "outcome": "failed"}
            reason = result.outcome.first_error_lines.get(node_id)
            if reason:
                record["reason"] = reason
            named.append(record)
        if not run_passed and not named:
            named = [
                {
                    "name": f"[{_label(run)}] run exited {result.outcome.exit_code} naming "
                    f"no failing test; see {result.outcome.log}",
                    "outcome": "failed",
                }
            ]
        tests += named

    summary["passed_all"] = passed_all
    report: dict[str, Any] = {
        "tool": "pytest",
        "summary": summary,
        "tests": tests,
        "coverage": primary_report.get("coverage", {}),
        "interpreters": interpreters,
        "wall_seconds": round(wall_seconds, 1),
    }
    if errors:
        report["error"] = "; ".join(errors)
    return report


# ── Outcomes ───────────────────────────────────────────────────────


def _red_summary() -> dict[str, Any]:
    return dict.fromkeys(_COUNT_KEYS, 0) | {"passed_all": False}


def outcome_from_log(log: Path, exit_code: int, *, lines: Path) -> RunOutcome:
    """An extra run's outcome, parsed from its console log.

    Uses the parser ``run_tests.sh`` uses for its own text fallback, combined
    with the exit status the same way, so a missing log or a non-zero exit over
    a clean-looking summary is red. ``lines`` is the run's
    ``--first-error-lines`` file.
    """
    content = log.read_text(encoding="utf-8", errors="replace") if log.is_file() else ""
    parsed = parse_pytest_text_output(content)
    summary = {key: parsed[key] for key in _COUNT_KEYS}
    summary["passed_all"] = finalize_passed_all(parsed["passed_all"], exit_code)
    return RunOutcome(
        exit_code,
        summary,
        list(parsed["failed_tests"]),
        log,
        read_first_error_lines(lines),
        parse_slowest_durations(content),
    )


def outcome_from_primary_report(path: Path, exit_code: int) -> RunOutcome:
    """The primary run's outcome, read from the ``tests.json`` run_tests.sh wrote.

    run_tests.sh has already put each failure's first error line on its
    record, and ``build_report`` carries the primary's records through as
    they are, so none are collected here.
    """
    if not path.is_file():
        return RunOutcome(exit_code, _red_summary(), [], path, {})
    report = json.loads(path.read_text(encoding="utf-8"))
    summary = dict(report.get("summary", {}))
    summary["passed_all"] = bool(summary.get("passed_all", False)) and exit_code == 0
    failed = [t.get("name", "") for t in report.get("tests", []) if t.get("outcome") == "failed"]
    return RunOutcome(exit_code, summary, failed, path, {}, report.get("slowest_tests", []))


# ── Real side effects ──────────────────────────────────────────────


def _uv() -> str:
    uv = shutil.which("uv")
    if uv is None:
        raise ProvisionError("`uv` is not on PATH, so no extra interpreter can be provisioned")
    return uv


def _checked(argv: list[str], what: str, env: dict[str, str] | None = None) -> str:
    completed = subprocess.run(argv, capture_output=True, text=True, check=False, env=env)
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip() or "(no output)"
        raise ProvisionError(f"{what} failed (exit {completed.returncode}): {detail}")
    return completed.stdout.strip()


def _find_interpreter(uv: str, version: str) -> Path:
    """uv's interpreter for ``version``, installing a managed one if none is found."""
    found = subprocess.run(
        [uv, "python", "find", "--no-project", version],
        capture_output=True,
        text=True,
        check=False,
    )
    if found.returncode != 0:
        _checked([uv, "python", "install", version], f"`uv python install {version}`")
        return Path(
            _checked([uv, "python", "find", "--no-project", version], f"`uv python find {version}`")
        )
    return Path(found.stdout.strip())


def provision(version: str) -> Path:
    """A venv for ``version`` synced from ``uv.lock``; returns its interpreter.

    Every step is verified rather than trusted: the interpreter uv found must
    BE ``version``, and the venv must import pytest and this checkout's own
    package.
    """
    uv = _uv()
    interpreter = _find_interpreter(uv, version)
    actual = _checked([str(interpreter), "-c", _VERSION_PROBE], f"probing {interpreter}")
    if actual != version:
        raise ProvisionError(f"uv offered {interpreter} for Python {version}, but it is {actual}")

    venv = EXTRA_VENVS_DIR / f"py{version}"
    env = dict(os.environ)
    env["UV_PROJECT_ENVIRONMENT"] = str(venv)
    # A copy works on every filesystem; uv's default hardlink fails when its
    # cache and this checkout are on different devices, as in a container.
    env.setdefault("UV_LINK_MODE", "copy")
    env.pop("VIRTUAL_ENV", None)
    _checked(
        [
            uv,
            "sync",
            "--frozen",
            "--all-extras",
            "--quiet",
            "--python",
            str(interpreter),
            "--project",
            str(PROJECT_ROOT),
        ],
        f"`uv sync` of the Python {version} venv at {venv}",
        env=env,
    )

    python = venv / "bin" / "python"
    probe = _checked([str(python), "-c", _VENV_PROBE], f"probing {python}").splitlines()
    package_root = PROJECT_ROOT / "src"
    if (
        len(probe) != 2
        or probe[0] != version
        or not path_is_relative_to(Path(probe[1]), package_root)
    ):
        raise ProvisionError(
            f"{venv} is not a Python {version} venv importing {package_root}: {probe}"
        )
    return python


class _PrimaryJob:
    """``run_tests.sh`` under the primary interpreter; its output goes to ours."""

    def __init__(self, lock_fd: int) -> None:
        # A previous run's report must not stand in for this run's if
        # run_tests.sh dies before writing one.
        TESTS_JSON.unlink(missing_ok=True)
        # run_tests.sh recognises the inherited descriptor as the held lock
        # instead of waiting on a second description of the same file.
        env = {**os.environ, "FULL_QA_LOCK_INHERITED_FD": str(lock_fd)}
        self._process = subprocess.Popen(
            [str(SCRIPTS_DIR / "run_tests.sh")],
            cwd=str(PROJECT_ROOT),
            env=env,
            pass_fds=(lock_fd,),
        )

    def wait(self) -> RunOutcome:
        return outcome_from_primary_report(TESTS_JSON, self._process.wait())


def extra_pytest_argv(python: Path, run: PlannedRun, lines: Path) -> list[str]:
    """The pytest command line for one extra run, recording first error lines to ``lines``."""
    return [
        str(python),
        "-m",
        "pytest",
        "-p",
        "no:cacheprovider",
        f"{FIRST_ERROR_LINES_OPTION}={lines}",
        "--tb=short",
        *SLOWEST_DURATIONS_ARGS,
        *SCOPE_PYTEST_ARGS[run.scope],
    ]


class _ExtraJob:
    """pytest over one scope under an extra interpreter, logged to a file."""

    def __init__(self, run: PlannedRun, python: Path, lock_fd: int) -> None:
        self._log = QA_OUTPUT_DIR / f"tests-py{run.version}-{run.scope}.log"
        self._lines = QA_OUTPUT_DIR / f"first-error-lines-py{run.version}-{run.scope}.jsonl"
        # The plugin appends, so a previous run's lines must not survive.
        self._lines.unlink(missing_ok=True)
        env = dict(os.environ)
        venv_bin = python.parent
        # As CI does: the matrix venv's tools come first on PATH.
        env["PATH"] = f"{venv_bin}{os.pathsep}{env.get('PATH', '')}"
        env["VIRTUAL_ENV"] = str(venv_bin.parent)
        # The acceptance tests' release-gate guard, as run_tests.sh sets it.
        env["HOOKS_DAEMON_RELEASE_GATE"] = "1"
        self._log.parent.mkdir(parents=True, exist_ok=True)
        self._handle: IO[bytes] = self._log.open("wb")
        self._process = subprocess.Popen(
            extra_pytest_argv(python, run, self._lines),
            cwd=str(PROJECT_ROOT),
            env=env,
            stdout=self._handle,
            stderr=subprocess.STDOUT,
            # The whole-suite sink in pytest refuses a run whose ancestry does
            # not hold the host-wide full-QA lock; the descriptor is the proof.
            pass_fds=(lock_fd,),
        )

    def wait(self) -> RunOutcome:
        exit_code = self._process.wait()
        self._handle.close()
        return outcome_from_log(self._log, exit_code, lines=self._lines)


def launch(run: PlannedRun, python: Path, *, lock_fd: int) -> Job:
    """Start ``run``; ``lock_fd`` is the held host-wide full-QA lock, handed to the child."""
    if run.primary:
        return _PrimaryJob(lock_fd)
    return _ExtraJob(run, python, lock_fd)


def ensure_daemon() -> str | None:
    """Start this checkout's daemon if it has idled out; run before each serial run."""
    status = subprocess.run(
        [str(DAEMON_CLI), "status"],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
        timeout=DAEMON_CLI_TIMEOUT_SECONDS,
        check=False,
    )
    if status.returncode == 0:
        return None
    started = subprocess.run(
        [str(DAEMON_CLI), "start"],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
        timeout=DAEMON_CLI_TIMEOUT_SECONDS,
        check=False,
    )
    output = f"{started.stdout}{started.stderr}".strip()
    return (
        f"daemon was not running before a serial run; `start` exited {started.returncode}: {output}"
    )


def _print_runs(report: dict[str, Any]) -> None:
    print("")
    print(f"Interpreter matrix ({report['wall_seconds']}s wall):")
    for entry in report["interpreters"]:
        role = "primary" if entry["primary"] else "extra"
        head = f"  py{entry['version']} {entry['scope']} ({role})"
        if entry["error"]:
            print(f"{head}: NOT RUN -- {entry['error']}")
            continue
        verdict = "PASSED" if entry["passed_all"] else "FAILED"
        print(
            f"{head}: {verdict} {entry['passed']} passed, {entry['failed']} failed, "
            f"{entry['errors']} errors, {entry['skipped']} skipped "
            f"in {entry['duration_seconds']}s" + (" (reused)" if entry.get("reused") else "")
        )


def main() -> int:
    resume = resume_requested(sys.argv[1:])
    QA_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    primary_version = f"{sys.version_info.major}.{sys.version_info.minor}"
    began = time.monotonic()
    try:
        ci_versions = ci_python_versions()
    except MatrixError as exc:
        # Refuse to run a narrower stage than CI: without the matrix there is
        # no way to know which versions are owed.
        report = build_report([], {}, wall_seconds=0.0)
        report["summary"]["passed_all"] = False
        report["error"] = f"CI Python matrix unreadable, so no test run was attempted: {exc}"
        TESTS_JSON.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(report["error"], file=sys.stderr)
        return 1

    plan = plan_runs(ci_versions, primary_version)
    print(f"CI matrix {ci_versions}; primary interpreter {primary_version}")
    # Held for every child run: each is a whole-suite pytest the sink refuses
    # unless its ancestry holds this lock (Plan 00463).
    # Under `llm_qa.py` the parent already holds this lock and passes it down;
    # a second, fresh acquire would wait on its own parent for ever.
    with acquire_full_qa_lock(PROJECT_ROOT, reuse_inherited=True) as lock_fd:
        deps = MatrixDeps(
            provision=provision,
            launch=functools.partial(launch, lock_fd=lock_fd),
            ensure_daemon=ensure_daemon,
            clock=time.monotonic,
            checkpoints=LegCheckpoints(QA_OUTPUT_DIR, tree=checkout_tree),
            resume=resume,
        )
        results = run_matrix(plan, Path(sys.executable), deps)

    primary_report: dict[str, Any] = {}
    if TESTS_JSON.is_file():
        primary_report = json.loads(TESTS_JSON.read_text(encoding="utf-8"))
    report = build_report(results, primary_report, wall_seconds=time.monotonic() - began)
    TESTS_JSON.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    _print_runs(report)
    if "error" in report:
        print(f"ERROR: {report['error']}", file=sys.stderr)
    return 0 if report["summary"]["passed_all"] else 1


if __name__ == "__main__":
    sys.exit(main())
