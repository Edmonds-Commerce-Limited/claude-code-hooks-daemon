#!/usr/bin/env python3
"""Fail when a daemon start spends more CPU before binding its socket than the budget allows.

A slow start is what the owner saw first (Plan 00495): the status bar waits on the
daemon, and start CPU had grown from 1.0 s to 2.5 s over thirty releases with nothing
to say so. This check measures the same work ``cmd_start`` does before it binds the
socket (import the CLI, load the config, build and initialise the controller with the
non-essential steps deferred) in a fresh process on a throwaway project holding the
shipped example config, and compares the median CPU seconds with
``CLAUDE/Performance/startup-budget.json``.

CPU seconds, not wall time: CPU does not grow with the host's run queue, so the
verdict does not flake when other agents are running tests. A failing round is
measured again (``attempts`` rounds in all) and the check fails only when every round
is over budget, since a real slowdown shows in all of them and load noise does not.

It runs as a release gate (CLAUDE/development/RELEASING.md, Step 8b), not in the
per-commit suite: a start-up measurement spends several CPU seconds per sample.

Usage:
    scripts/release/check_startup_budget.py [--budget-file PATH] [--python PATH]

``--python`` must be an interpreter that can import ``claude_code_hooks_daemon``
(default: the one running this script).

Exit codes:
    0 - median start CPU within budget
    1 - over budget in every round
    2 - the measurement itself failed
"""

from __future__ import annotations

import argparse
import json
import shutil
import statistics
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BUDGET_FILE = REPO_ROOT / "CLAUDE" / "Performance" / "startup-budget.json"
EXAMPLE_CONFIG = REPO_ROOT / ".claude" / "hooks-daemon.yaml.example"
PROBE_TIMEOUT_SECONDS = 300
THROWAWAY_REMOTE = "https://example.invalid/throwaway.git"

# The work cmd_start does before the socket is bound. Total process CPU is printed, so
# interpreter start-up counts too.
_PROBE = """
import importlib, os, sys, time
from pathlib import Path
project = Path(sys.argv[1])
os.chdir(project)
cli = importlib.import_module("claude_code_hooks_daemon.daemon.cli")
config = cli.Config.find_and_load(project)
cli._build_initialised_controller(config, project, defer_nonessential_startup=True)
print(time.process_time())
"""


class MeasurementError(RuntimeError):
    """The start-up probe could not produce a CPU reading."""


@dataclass(frozen=True)
class Budget:
    """The recorded budget and how it is measured."""

    cpu_seconds: float
    samples: int
    attempts: int


@dataclass(frozen=True)
class Verdict:
    """The outcome of one round of samples."""

    passed: bool
    median_cpu: float
    budget_cpu: float
    samples: tuple[float, ...]


def load_budget(path: Path) -> Budget:
    """Read and validate the budget file.

    Raises:
        FileNotFoundError: the file does not exist.
        ValueError: a field is missing or not positive.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    values: dict[str, float] = {}
    for field in ("cpu_seconds", "samples", "attempts"):
        if field not in data:
            raise ValueError(f"{path}: missing field {field!r}")
        if data[field] <= 0:
            raise ValueError(f"{path}: {field} must be positive, got {data[field]!r}")
        values[field] = data[field]
    return Budget(
        cpu_seconds=float(values["cpu_seconds"]),
        samples=int(values["samples"]),
        attempts=int(values["attempts"]),
    )


def evaluate(samples: list[float], budget: Budget) -> Verdict:
    """Judge one round: the median of ``samples`` against the budget."""
    if not samples:
        raise ValueError("no samples to evaluate")
    median = statistics.median(samples)
    return Verdict(
        passed=median <= budget.cpu_seconds,
        median_cpu=median,
        budget_cpu=budget.cpu_seconds,
        samples=tuple(samples),
    )


def check(budget: Budget, measure: Callable[[], float]) -> Verdict:
    """Run up to ``budget.attempts`` rounds; pass on the first round within budget."""
    verdict: Verdict | None = None
    for _ in range(budget.attempts):
        verdict = evaluate([measure() for _ in range(budget.samples)], budget)
        if verdict.passed:
            break
    assert verdict is not None  # attempts is validated positive
    return verdict


def make_project(root: Path) -> Path:
    """Create the throwaway client project: a git repo holding the shipped example config."""
    project = root / "project"
    (project / ".claude").mkdir(parents=True)
    shutil.copy(EXAMPLE_CONFIG, project / ".claude" / "hooks-daemon.yaml")
    for command in (["init", "-q"], ["remote", "add", "origin", THROWAWAY_REMOTE]):
        subprocess.run(["git", "-C", str(project), *command], check=True, capture_output=True)
    return project


def measure_start_cpu(python: str, project: Path) -> float:
    """CPU seconds one fresh process spends on the daemon's pre-bind start-up work."""
    result = subprocess.run(
        [python, "-c", _PROBE, str(project)],
        capture_output=True,
        text=True,
        timeout=PROBE_TIMEOUT_SECONDS,
        check=False,
    )
    if result.returncode != 0:
        raise MeasurementError(f"probe exited {result.returncode}: {result.stderr.strip()}")
    try:
        return float(result.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError) as exc:
        raise MeasurementError(f"probe printed no CPU reading: {result.stdout!r}") from exc


def main(argv: list[str] | None = None) -> int:
    """Measure, compare, print the verdict; return the exit code."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--budget-file", type=Path, default=DEFAULT_BUDGET_FILE)
    parser.add_argument("--python", default=sys.executable)
    args = parser.parse_args(argv)

    budget = load_budget(args.budget_file)
    with tempfile.TemporaryDirectory(prefix="startup-budget-") as tmp:
        project = make_project(Path(tmp))
        try:
            measure_start_cpu(args.python, project)  # warm the file cache; not counted
            verdict = check(budget, lambda: measure_start_cpu(args.python, project))
        except (MeasurementError, subprocess.TimeoutExpired) as exc:
            print(f"startup-budget: MEASUREMENT FAILED: {exc}", file=sys.stderr)
            return 2

    readings = ", ".join(f"{s:.2f}" for s in verdict.samples)
    print(
        f"startup-budget: {'PASS' if verdict.passed else 'FAIL'}: median {verdict.median_cpu:.2f} s CPU "
        f"against a budget of {verdict.budget_cpu:g} s ({readings})"
    )
    return 0 if verdict.passed else 1


if __name__ == "__main__":
    sys.exit(main())
