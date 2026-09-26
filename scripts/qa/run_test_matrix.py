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
  ``first_error_lines`` pytest plugin), and the report carries it as that
  test's ``reason``.

An extra interpreter that cannot be provisioned FAILS the stage and says so;
the stage never quietly runs fewer versions than CI. Its report is written
over ``tests.json`` with a per-run ``interpreters`` list.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import IO, Any, Final, NamedTuple, Protocol

import yaml

from claude_code_hooks_daemon.qa.first_error_lines import (
    OPTION as FIRST_ERROR_LINES_OPTION,
)
from claude_code_hooks_daemon.qa.first_error_lines import (
    PLUGIN as FIRST_ERROR_LINES_PLUGIN,
)
from claude_code_hooks_daemon.qa.first_error_lines import read_first_error_lines
from claude_code_hooks_daemon.qa.pytest_text_report import (
    finalize_passed_all,
    parse_pytest_text_output,
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


class RunResult(NamedTuple):
    """A planned run and what became of it; ``outcome`` is None when it never ran."""

    run: PlannedRun
    outcome: RunOutcome | None
    duration_seconds: float
    error: str | None


class Job(Protocol):
    """A started run the stage can wait on."""

    def wait(self) -> RunOutcome: ...


class MatrixDeps(NamedTuple):
    """The side effects ``run_matrix`` needs, injectable so tests need no interpreters."""

    provision: Callable[[str], Path]
    launch: Callable[[PlannedRun, Path], Job]
    ensure_daemon: Callable[[], str | None]
    clock: Callable[[], float]


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

    started: list[tuple[PlannedRun, Job, float]] = []
    for run in (r for r in plan if r.phase == PHASE_PARALLEL):
        python = python_for(run)
        if python is None:
            results[run] = not_run(run)
            continue
        started.append((run, deps.launch(run, python), deps.clock()))
    for run, job, began in started:
        outcome = job.wait()
        results[run] = RunResult(run, outcome, deps.clock() - began, None)

    for run in (r for r in plan if r.phase == PHASE_SERIAL):
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
        began = deps.clock()
        outcome = deps.launch(run, python).wait()
        results[run] = RunResult(run, outcome, deps.clock() - began, None)

    return [results[run] for run in plan]


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
        exit_code, summary, list(parsed["failed_tests"]), log, read_first_error_lines(lines)
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
    return RunOutcome(exit_code, summary, failed, path, {})


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

    def __init__(self) -> None:
        # A previous run's report must not stand in for this run's if
        # run_tests.sh dies before writing one.
        TESTS_JSON.unlink(missing_ok=True)
        self._process = subprocess.Popen([str(SCRIPTS_DIR / "run_tests.sh")], cwd=str(PROJECT_ROOT))

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
        "-p",
        FIRST_ERROR_LINES_PLUGIN,
        f"{FIRST_ERROR_LINES_OPTION}={lines}",
        "--tb=short",
        *SCOPE_PYTEST_ARGS[run.scope],
    ]


class _ExtraJob:
    """pytest over one scope under an extra interpreter, logged to a file."""

    def __init__(self, run: PlannedRun, python: Path) -> None:
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
        )

    def wait(self) -> RunOutcome:
        exit_code = self._process.wait()
        self._handle.close()
        return outcome_from_log(self._log, exit_code, lines=self._lines)


def launch(run: PlannedRun, python: Path) -> Job:
    if run.primary:
        return _PrimaryJob()
    return _ExtraJob(run, python)


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
            f"in {entry['duration_seconds']}s"
        )


def main() -> int:
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
    deps = MatrixDeps(
        provision=provision, launch=launch, ensure_daemon=ensure_daemon, clock=time.monotonic
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
