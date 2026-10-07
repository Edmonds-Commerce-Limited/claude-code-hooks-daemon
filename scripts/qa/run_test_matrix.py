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

Each leg is a list of SHARDS (``scripts/qa/test_shards.yaml``: named slices of
``tests/``) run one after another, and each shard writes its own checkpoint
(:class:`LegCheckpoints`) the moment it finishes. ``--resume`` (what
``llm_qa.py all --resume`` passes down) runs only the shards with no checkpoint
that PASSED on the identical tree; the others run as normal. Without
``--resume`` no shard is ever reused.

Coverage is judged on the whole. Each primary shard writes its own coverage
data file (no fail-under) that is kept with its checkpoint; once every primary
shard has run or been reused they are combined (``coverage combine --keep``)
and the report and the ``fail_under`` verdict come from the combined data.
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
from claude_code_hooks_daemon.qa.suite_shards import (
    SCOPE_REST,
    SCOPE_UNIT,
    Shard,
    ShardError,
    load_shards,
    shards_in_scope,
)
from claude_code_hooks_daemon.utils.path_containment import path_is_relative_to

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parent.parent.parent
SCRIPTS_DIR: Final[Path] = PROJECT_ROOT / "scripts" / "qa"
SHARDS_FILE: Final[Path] = SCRIPTS_DIR / "test_shards.yaml"
QA_OUTPUT_DIR: Final[Path] = PROJECT_ROOT / "untracked" / "qa"
TESTS_JSON: Final[Path] = QA_OUTPUT_DIR / "tests.json"
COVERAGE_JSON_NAME: Final[str] = "coverage.json"
COVERAGE_COMBINED_NAME: Final[str] = "coverage-combined.data"
CI_WORKFLOW: Final[Path] = PROJECT_ROOT / ".github" / "workflows" / "qa.yml"
CI_JOB: Final[str] = "qa"
CI_MATRIX_KEY: Final[str] = "python-version"
EXTRA_VENVS_DIR: Final[Path] = PROJECT_ROOT / "untracked" / "qa-interpreters"
DAEMON_CLI: Final[Path] = PROJECT_ROOT / "bin" / "hooks-daemon"
DAEMON_CLI_TIMEOUT_SECONDS: Final[int] = 120

SCOPE_FULL: Final[str] = "full"
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
    """One matrix leg the stage owes: a pytest run of a scope, as a list of shards.

    ``shards`` names the leg's shards (empty: the leg is one unsharded run).
    The unit that actually launches and checkpoints is the leg with ``shards``
    cleared and ``shard`` set to one of those names.
    """

    version: str
    scope: str
    phase: int
    primary: bool
    shards: tuple[str, ...] = ()
    shard: str | None = None


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
    #: The coverage data file a primary shard wrote, kept with its checkpoint.
    coverage_data: Path | None = None


class ShardResult(NamedTuple):
    """One shard of a leg: what it reported, how long it took, and whether it was reused."""

    name: str
    outcome: RunOutcome
    duration_seconds: float
    reused: bool


class RunResult(NamedTuple):
    """A planned run and what became of it; ``outcome`` is None when it never ran.

    ``reused`` marks a result taken from a checkpoint (``--resume``); its
    ``duration_seconds`` is then the run that produced it. A sharded leg's
    ``outcome`` is the merge of its shards', listed in ``shards``; it is
    ``reused`` only when every shard was.
    """

    run: PlannedRun
    outcome: RunOutcome | None
    duration_seconds: float
    error: str | None
    reused: bool = False
    shards: tuple[ShardResult, ...] = ()


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
_CK_EXTRA_ARTEFACTS: Final[str] = "extra_artefacts"
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
        extra_artefacts: Sequence[Path] = (),
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
        if extra_artefacts:
            record[_CK_EXTRA_ARTEFACTS] = {
                str(path): _GATE.output_digest(path) for path in extra_artefacts
            }
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
        extras = record.get(_CK_EXTRA_ARTEFACTS, {})
        if not isinstance(extras, dict) or any(
            digest is None or _GATE.output_digest(Path(path)) != digest
            for path, digest in extras.items()
        ):
            return "a data file kept with that leg is not the one it wrote"
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


def plan_runs(
    ci_versions: Sequence[str], primary_version: str, shards: Sequence[Shard] = ()
) -> list[PlannedRun]:
    """Every leg the stage owes: the primary in full, each extra in two scopes.

    With ``shards`` each leg lists the shards it runs (the primary all of them,
    an extra those of its scope); without, each leg is one unsharded run.
    """
    extras = [version for version in ci_versions if version != primary_version]

    def names(scope: str | None) -> tuple[str, ...]:
        chosen = shards if scope is None else shards_in_scope(list(shards), scope)
        return tuple(shard.name for shard in chosen)

    plan = [PlannedRun(primary_version, SCOPE_FULL, PHASE_PARALLEL, True, names(None))]
    plan += [
        PlannedRun(version, SCOPE_UNIT, PHASE_PARALLEL, False, names(SCOPE_UNIT))
        for version in extras
    ]
    plan += [
        PlannedRun(version, SCOPE_REST, PHASE_SERIAL, False, names(SCOPE_REST))
        for version in extras
    ]
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


class _Leg:
    """One matrix leg executed unit by unit: each shard (or the whole leg, unsharded).

    ``start`` does everything up to the first launch on the caller's thread, so
    every phase-1 leg is running before the runner blocks on any; ``complete``
    waits for the running unit, checkpoints it the moment it ends, and goes on
    to the leg's remaining shards, one at a time.
    """

    def __init__(
        self,
        run: PlannedRun,
        deps: MatrixDeps,
        python_for: Callable[[PlannedRun], Path | None],
    ) -> None:
        self._run = run
        self._deps = deps
        self._python_for = python_for
        self._pending = [run._replace(shards=(), shard=name) for name in run.shards] or [run]
        self._done: list[RunResult] = []
        self._running: tuple[PlannedRun, Job, dict[str, str] | None, float] | None = None
        self.not_provisioned = False

    def start(self) -> None:
        """Reuse what ``--resume`` allows and launch the first unit that must run."""
        deps = self._deps
        checkpoints = deps.checkpoints
        while self._pending and self._running is None:
            unit = self._pending.pop(0)
            cached = self._reuse(unit)
            if cached is not None:
                self._done.append(cached)
                continue
            python = self._python_for(self._run)
            if python is None:
                self.not_provisioned = True
                self._pending.clear()
                return
            if self._run.phase == PHASE_SERIAL:
                # Before EVERY serial unit, not once: the daemon exits after
                # idle_timeout_seconds without traffic, and a run's later
                # directories can go longer than that without touching it
                # (00466 N196).
                daemon_note = deps.ensure_daemon()
                if daemon_note is not None:
                    print(daemon_note)
            before: dict[str, str] | None = None
            if checkpoints is not None:
                # Drop any old checkpoint as the unit starts: an interrupted
                # unit must leave none behind.
                checkpoints.invalidate(leg_key(unit))
                before = checkpoints.tree()
            self._running = (unit, deps.launch(unit, python), before, deps.clock())

    def complete(self) -> RunResult:
        """Wait for every remaining unit and return the leg's result."""
        deps = self._deps
        while self._running is not None:
            unit, job, before, began = self._running
            self._running = None
            outcome = job.wait()
            duration = deps.clock() - began
            if deps.checkpoints is not None:
                _checkpoint_leg(deps.checkpoints, unit, outcome, before, duration)
            self._done.append(RunResult(unit, outcome, duration, None))
            self.start()
        if self.not_provisioned:
            # Nothing ran; `run_matrix` replaces this with the provisioning error.
            return RunResult(self._run, None, 0.0, None)
        if len(self._done) == 1 and not self._run.shards:
            return self._done[0]
        return _merge_leg(self._run, self._done)

    def _reuse(self, unit: PlannedRun) -> RunResult | None:
        """The unit's checkpoint as a result, when ``--resume`` and the checkpoint allow it."""
        checkpoints = self._deps.checkpoints
        if checkpoints is None or not self._deps.resume:
            return None
        found = checkpoints.check(leg_key(unit))
        if isinstance(found, str):
            print(f"  {_label(unit)}: running ({found})")
            return None
        if unit.primary and unit.shard is None:
            _restore_primary_report(checkpoints, unit)
        print(f"  {_label(unit)}: reused, passed on this tree (took {found.duration_seconds}s)")
        return RunResult(
            unit, _outcome_from_payload(found.payload), found.duration_seconds, None, True
        )


def _merge_leg(run: PlannedRun, units: Sequence[RunResult]) -> RunResult:
    """One leg result over its shard results (``units`` is never empty here)."""
    shards = tuple(
        ShardResult(str(unit.run.shard), unit.outcome, unit.duration_seconds, unit.reused)
        for unit in units
        if unit.outcome is not None
    )
    outcome = merge_outcomes([shard.outcome for shard in shards])
    return RunResult(
        run,
        outcome,
        sum(shard.duration_seconds for shard in shards),
        None,
        all(shard.reused for shard in shards),
        shards,
    )


def run_matrix(
    plan: Sequence[PlannedRun], primary_python: Path, deps: MatrixDeps
) -> list[RunResult]:
    """Execute ``plan`` and return one result per planned leg, in plan order.

    The primary starts first and before any provisioning, since it is the
    longest run. An extra whose provisioning fails gets an error result for
    each of its legs and nothing is launched for it.
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

    started: list[tuple[PlannedRun, _Leg]] = []
    for run in (r for r in plan if r.phase == PHASE_PARALLEL):
        leg = _Leg(run, deps, python_for)
        leg.start()
        started.append((run, leg))
    if started:
        # One waiter per leg, so each shard is checkpointed the moment IT ends
        # rather than when the slowest leg before it in line does.
        with ThreadPoolExecutor(max_workers=len(started)) as pool:
            pending = [(run, pool.submit(leg.complete)) for run, leg in started]
            for (run, leg), (_, future) in zip(started, pending, strict=True):
                result = future.result()
                results[run] = not_run(run) if leg.not_provisioned else result

    for run in (r for r in plan if r.phase == PHASE_SERIAL):
        leg = _Leg(run, deps, python_for)
        leg.start()
        result = leg.complete()
        results[run] = not_run(run) if leg.not_provisioned else result

    return [results[run] for run in plan]


def leg_key(run: PlannedRun) -> str:
    """The checkpoint key of one leg, or of one shard of it."""
    key = f"py{run.version}-{run.scope}"
    return key if run.shard is None else f"{key}-{run.shard}"


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
        "coverage_data": None if outcome.coverage_data is None else str(outcome.coverage_data),
    }


def _outcome_from_payload(payload: Mapping[str, Any]) -> RunOutcome:
    return RunOutcome(
        exit_code=int(payload["exit_code"]),
        summary=dict(payload["summary"]),
        failed_tests=list(payload["failed_tests"]),
        log=Path(payload["log"]),
        first_error_lines=dict(payload["first_error_lines"]),
        slowest_tests=list(payload["slowest_tests"]),
        coverage_data=Path(payload["coverage_data"]) if payload.get("coverage_data") else None,
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
    if run.primary and run.shard is None and artefact is not None:
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
        extra_artefacts=[outcome.coverage_data] if outcome.coverage_data is not None else [],
    )


def _label(run: PlannedRun) -> str:
    label = f"py{run.version} {run.scope}"
    return label if run.shard is None else f"{label} [{run.shard}]"


_COUNT_KEYS: Final[tuple[str, ...]] = ("total", "passed", "failed", "skipped", "errors")


def build_report(
    results: Sequence[RunResult],
    primary_report: dict[str, Any],
    wall_seconds: float,
    coverage_failure: str | None = None,
) -> dict[str, Any]:
    """The stage's ``tests.json``: the primary's report, widened to every run.

    Counts are summed over every run, ``passed_all`` holds only when every
    planned run ran and passed, and each failure from an extra is named with
    the interpreter and scope it failed under. A sharded leg's entry lists its
    shards. ``coverage_failure`` (the combined coverage verdict, when it is not
    a pass) fails the report and is named as its unexplained failure.
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
        if result.shards:
            entry["shards"] = [_shard_entry(shard) for shard in result.shards]
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

    if coverage_failure is not None:
        passed_all = False
        errors.append(coverage_failure)
        summary["unnamed_failure_reason"] = coverage_failure
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


def _shard_entry(shard: ShardResult) -> dict[str, Any]:
    """One shard of a leg, as listed in the leg's ``tests.json`` entry."""
    outcome = shard.outcome
    return {
        "name": shard.name,
        "reused": shard.reused,
        "duration_seconds": round(shard.duration_seconds, 1),
        "passed_all": bool(outcome.summary.get("passed_all", False)),
        "exit_code": outcome.exit_code,
        "log": str(outcome.log),
        **{key: int(outcome.summary.get(key, 0)) for key in _COUNT_KEYS},
    }


def primary_report_from_shards(result: RunResult, coverage: dict[str, Any]) -> dict[str, Any]:
    """The primary leg's report in the shape ``run_tests.sh`` writes for a whole run.

    ``tests`` is every shard report's own list, joined in shard order;
    ``coverage`` is the combined verdict's totals.
    """
    tests: list[dict[str, Any]] = []
    for shard in result.shards:
        if shard.outcome.log.is_file():
            tests += json.loads(shard.outcome.log.read_text(encoding="utf-8")).get("tests", [])
    return {"tool": "pytest", "tests": tests, "coverage": coverage}


# ── Outcomes ───────────────────────────────────────────────────────

_SLOWEST_KEPT: Final[int] = int(SLOWEST_DURATIONS_ARGS[0].partition("=")[2])


def merge_outcomes(outcomes: Sequence[RunOutcome]) -> RunOutcome:
    """One outcome over several shards' (never empty).

    Counts are summed and ``passed_all`` needs every shard; the exit code is the
    first non-zero one; failed tests and first error lines are joined; the
    slowest tests are the slowest of all, capped as one run's would be. ``log``
    is the first failing shard's, else the last's.
    """
    summary: dict[str, Any] = {
        key: sum(int(o.summary.get(key, 0)) for o in outcomes) for key in _COUNT_KEYS
    }
    summary["passed_all"] = all(bool(o.summary.get("passed_all", False)) for o in outcomes)
    reasons = [
        str(o.summary["unnamed_failure_reason"])
        for o in outcomes
        if "unnamed_failure_reason" in o.summary
    ]
    if reasons:
        summary["unnamed_failure_reason"] = "; ".join(reasons)
    slowest = sorted(
        (record for o in outcomes for record in o.slowest_tests),
        key=lambda record: float(record.get("seconds", 0.0)),
        reverse=True,
    )
    failing = [o for o in outcomes if not o.summary.get("passed_all", False)]
    return RunOutcome(
        exit_code=next((o.exit_code for o in outcomes if o.exit_code != 0), 0),
        summary=summary,
        failed_tests=[name for o in outcomes for name in o.failed_tests],
        log=(failing[0] if failing else outcomes[-1]).log,
        first_error_lines={k: v for o in outcomes for k, v in o.first_error_lines.items()},
        slowest_tests=slowest[:_SLOWEST_KEPT],
    )


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


def outcome_from_primary_report(
    path: Path, exit_code: int, coverage_data: Path | None = None
) -> RunOutcome:
    """The primary run's outcome, read from the ``tests.json`` run_tests.sh wrote.

    run_tests.sh has already put each failure's first error line on its
    record, and ``build_report`` carries the primary's records through as
    they are, so none are collected here.
    """
    if not path.is_file():
        return RunOutcome(exit_code, _red_summary(), [], path, {}, (), coverage_data)
    report = json.loads(path.read_text(encoding="utf-8"))
    summary = dict(report.get("summary", {}))
    summary["passed_all"] = bool(summary.get("passed_all", False)) and exit_code == 0
    failed = [t.get("name", "") for t in report.get("tests", []) if t.get("outcome") == "failed"]
    return RunOutcome(
        exit_code, summary, failed, path, {}, report.get("slowest_tests", []), coverage_data
    )


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


def shard_report_path(shard: str) -> Path:
    """Where ``run_tests.sh`` writes one primary shard's ``tests.json``-shaped report."""
    return QA_OUTPUT_DIR / f"tests-shard-{shard}.json"


def shard_coverage_data_path(shard: str) -> Path:
    """One primary shard's coverage DATA file (coverage.py's ``COVERAGE_FILE``)."""
    return QA_OUTPUT_DIR / f".coverage.{shard}"


class _PrimaryJob:
    """``run_tests.sh`` under the primary interpreter; its output goes to ours.

    With a ``shard`` it runs only that shard's pytest paths, writes the
    shard's own report and coverage data file, and judges no coverage.
    """

    def __init__(self, lock_fd: int, shard: Shard | None = None) -> None:
        self._report = TESTS_JSON if shard is None else shard_report_path(shard.name)
        self._data = None if shard is None else shard_coverage_data_path(shard.name)
        argv = [str(SCRIPTS_DIR / "run_tests.sh")]
        if shard is not None and self._data is not None:
            argv += [
                "--shard",
                shard.name,
                "--output",
                str(self._report),
                "--coverage-data",
                str(self._data),
                "--",
                *shard.pytest_args,
            ]
            self._data.unlink(missing_ok=True)
        # A previous run's report must not stand in for this run's if
        # run_tests.sh dies before writing one.
        self._report.unlink(missing_ok=True)
        # run_tests.sh recognises the inherited descriptor as the held lock
        # instead of waiting on a second description of the same file.
        env = {**os.environ, "FULL_QA_LOCK_INHERITED_FD": str(lock_fd)}
        self._process = subprocess.Popen(
            argv,
            cwd=str(PROJECT_ROOT),
            env=env,
            pass_fds=(lock_fd,),
        )

    def wait(self) -> RunOutcome:
        return outcome_from_primary_report(self._report, self._process.wait(), self._data)


def extra_pytest_argv(
    python: Path, run: PlannedRun, lines: Path, shard: Shard | None = None
) -> list[str]:
    """The pytest command line for one extra run, recording first error lines to ``lines``."""
    targets = SCOPE_PYTEST_ARGS[run.scope] if shard is None else shard.pytest_args
    return [
        str(python),
        "-m",
        "pytest",
        "-p",
        "no:cacheprovider",
        f"{FIRST_ERROR_LINES_OPTION}={lines}",
        "--tb=short",
        *SLOWEST_DURATIONS_ARGS,
        *targets,
    ]


class _ExtraJob:
    """pytest over one scope (or one shard of it) under an extra interpreter, logged to a file."""

    def __init__(self, run: PlannedRun, python: Path, lock_fd: int, shard: Shard | None) -> None:
        stem = f"py{run.version}-{run.scope}" + ("" if shard is None else f"-{shard.name}")
        self._log = QA_OUTPUT_DIR / f"tests-{stem}.log"
        self._lines = QA_OUTPUT_DIR / f"first-error-lines-{stem}.jsonl"
        # The plugin appends, so a previous run's lines must not survive.
        self._lines.unlink(missing_ok=True)
        env = dict(os.environ)
        venv_bin = python.parent
        # As CI does: the matrix venv's tools come first on the search path.
        env["PATH"] = f"{venv_bin}{os.pathsep}{env.get('PATH', '')}"
        env["VIRTUAL_ENV"] = str(venv_bin.parent)
        # The acceptance tests' release-gate guard, as run_tests.sh sets it.
        env["HOOKS_DAEMON_RELEASE_GATE"] = "1"
        self._log.parent.mkdir(parents=True, exist_ok=True)
        self._handle: IO[bytes] = self._log.open("wb")
        self._process = subprocess.Popen(
            extra_pytest_argv(python, run, self._lines, shard),
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


def launch(
    run: PlannedRun, python: Path, *, lock_fd: int, shards: Mapping[str, Shard] | None = None
) -> Job:
    """Start ``run`` (a shard when ``run.shard`` names one); ``lock_fd`` is the held full-QA lock."""
    shard = None if run.shard is None else (shards or {})[run.shard]
    if run.primary:
        return _PrimaryJob(lock_fd, shard)
    return _ExtraJob(run, python, lock_fd, shard)


class CoverageVerdict(NamedTuple):
    """The combined coverage of every primary shard, judged against ``fail_under``."""

    passed: bool
    coverage: dict[str, Any]
    message: str | None


def _coverage(python: Path, *args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(python), "-m", "coverage", *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(cwd),
    )


def _last_output(completed: subprocess.CompletedProcess[str]) -> str:
    lines = (completed.stderr or completed.stdout).strip().splitlines()
    return lines[-1] if lines else ""


def combine_coverage(
    python: Path, data_files: Sequence[Path], qa_dir: Path, *, cwd: Path
) -> CoverageVerdict:
    """Combine the shards' coverage data (``--keep``) and judge the whole.

    The shard files stay where they are, for the checkpoints that hashed them.
    The report and its ``fail_under`` verdict come from coverage's own config
    (``[tool.coverage.report]`` in pyproject.toml), run from ``cwd``, so the
    threshold is the one a single whole-suite run has always been held to.
    """
    missing = [path for path in data_files if not path.is_file()]
    if missing:
        names = ", ".join(path.name for path in missing)
        return CoverageVerdict(False, {}, f"coverage not judged: no data file {names}")
    combined = qa_dir / COVERAGE_COMBINED_NAME
    data_option = f"--data-file={combined}"
    combine = _coverage(
        python, "combine", "--keep", data_option, *(str(p) for p in data_files), cwd=cwd
    )
    if combine.returncode != 0:
        return CoverageVerdict(False, {}, f"coverage combine failed: {_last_output(combine)}")
    json_report = qa_dir / COVERAGE_JSON_NAME
    # `coverage report` below is the verdict; the JSON export must not also judge.
    exported = _coverage(
        python, "json", data_option, "--fail-under=0", "-o", str(json_report), cwd=cwd
    )
    if exported.returncode != 0:
        return CoverageVerdict(False, {}, f"coverage json failed: {_last_output(exported)}")
    totals = json.loads(json_report.read_text(encoding="utf-8")).get("totals", {})
    coverage = {
        key: totals.get(key, 0) for key in ("percent_covered", "num_statements", "missing_lines")
    }
    report = _coverage(python, "report", data_option, cwd=cwd)
    print(report.stdout)
    if report.returncode == 0:
        return CoverageVerdict(True, coverage, None)
    # `coverage report` exits 2 when the total is below fail_under, saying so last.
    return CoverageVerdict(False, coverage, _last_output(report) or "coverage report failed")


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
        for shard in entry.get("shards", []):
            print(
                f"    {shard['name']}: {'PASSED' if shard['passed_all'] else 'FAILED'} "
                f"{shard['passed']} passed, {shard['failed']} failed in "
                f"{shard['duration_seconds']}s" + (" (reused)" if shard["reused"] else "")
            )


def judge_primary(
    results: Sequence[RunResult], python: Path, *, qa_dir: Path, cwd: Path
) -> tuple[dict[str, Any], str | None]:
    """The primary leg's report and the coverage failure to name, if any.

    A sharded primary is judged here: its shards' coverage data (run or reused)
    is combined and held to ``fail_under``. An unsharded primary wrote its own
    ``tests.json``, coverage verdict included, so that is read as it stands.
    """
    sharded = next((r for r in results if r.run.primary and r.shards), None)
    if sharded is None:
        report: dict[str, Any] = {}
        if TESTS_JSON.is_file():
            report = json.loads(TESTS_JSON.read_text(encoding="utf-8"))
        return report, None
    data_files = [
        shard.outcome.coverage_data or shard_coverage_data_path(shard.name)
        for shard in sharded.shards
    ]
    verdict = combine_coverage(python, data_files, qa_dir, cwd=cwd)
    return primary_report_from_shards(sharded, verdict.coverage), (
        None if verdict.passed else verdict.message
    )


def _refuse(reason: str) -> int:
    """Write a red report naming ``reason``, because no test run was attempted."""
    report = build_report([], {}, wall_seconds=0.0)
    report["summary"]["passed_all"] = False
    report["error"] = reason
    TESTS_JSON.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(reason, file=sys.stderr)
    return 1


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
        return _refuse(f"CI Python matrix unreadable, so no test run was attempted: {exc}")
    try:
        shards = load_shards(SHARDS_FILE)
    except ShardError as exc:
        return _refuse(f"test shards unreadable, so no test run was attempted: {exc}")

    plan = plan_runs(ci_versions, primary_version, shards)
    print(f"CI matrix {ci_versions}; primary interpreter {primary_version}")
    # Held for every child run: each is a whole-suite pytest the sink refuses
    # unless its ancestry holds this lock (Plan 00463).
    # Under `llm_qa.py` the parent already holds this lock and passes it down;
    # a second, fresh acquire would wait on its own parent for ever.
    with acquire_full_qa_lock(PROJECT_ROOT, reuse_inherited=True) as lock_fd:
        deps = MatrixDeps(
            provision=provision,
            launch=functools.partial(
                launch, lock_fd=lock_fd, shards={shard.name: shard for shard in shards}
            ),
            ensure_daemon=ensure_daemon,
            clock=time.monotonic,
            checkpoints=LegCheckpoints(QA_OUTPUT_DIR, tree=checkout_tree),
            resume=resume,
        )
        results = run_matrix(plan, Path(sys.executable), deps)

    primary_report, coverage_failure = judge_primary(
        results, Path(sys.executable), qa_dir=QA_OUTPUT_DIR, cwd=PROJECT_ROOT
    )
    report = build_report(
        results,
        primary_report,
        wall_seconds=time.monotonic() - began,
        coverage_failure=coverage_failure,
    )
    TESTS_JSON.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    _print_runs(report)
    if "error" in report:
        print(f"ERROR: {report['error']}", file=sys.stderr)
    return 0 if report["summary"]["passed_all"] else 1


if __name__ == "__main__":
    sys.exit(main())
