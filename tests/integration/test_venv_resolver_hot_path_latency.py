"""Plan 00104 Phase 3 Task 3.3 — hot-path latency benchmark (xfail driver for Phase 8).

PLAN.md Success Criteria #5: ``init.sh::_resolve_python_cmd`` median resolve
must be ``<5ms`` post-consolidation. The resolver runs on every hook fire,
so wall-clock cost is multiplicative across a session.

Today's resolver in ``init.sh`` lines 255-328:

  1. ``HOOKS_DAEMON_VENV_PATH`` short-circuit (fast).
  2. Fingerprint path: ``source python_fingerprint.sh`` and call
     ``python_venv_fingerprint``, which spawns ``python3`` to compute an
     MD5 — Python startup alone is ~50-100ms.
  3. Scan-fallback: pure bash file-existence checks (fast).

The fingerprint path dominates because the test fixture has a venv
matching the host's fingerprint, so step 2 succeeds on the first try and
the scan-fallback is never exercised. Median resolve is therefore
Python-startup-bound, well above 5ms.

Phase 4/5 consolidate the five sites onto a canonical library; Phase 8
Task 8.1 then closes this gap by caching the fingerprint result via the
existing ``untracked/.python-cmd-cache`` mechanism (or equivalent), so
subsequent hook fires skip the Python spawn. When that lands the median
drops below 5ms and this xfail-strict flips to xpass — exactly the TDD
gate the plan requires.

The benchmark uses ``$EPOCHREALTIME`` (microsecond precision) inside a
single bash session to amortise bash-startup cost out of the
measurement. Each iteration sources the helper (mirroring how a real
hook fires from a fresh shell), times the function call, and prints the
delta. Python parses the deltas and asserts on the median.
"""

from __future__ import annotations

import os
import statistics
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
INIT_SH = REPO_ROOT / "init.sh"
FINGERPRINT_HELPER = REPO_ROOT / "scripts" / "install" / "python_fingerprint.sh"

ITERATIONS = 25
LATENCY_BUDGET_MS = 5.0


def _extract_init_sh_resolver(tmp_path: Path) -> Path:
    """Carve ``_resolve_python_cmd`` out of ``init.sh`` for isolated sourcing.

    Mirrors the helper used in
    ``test_venv_resolver_parity_matrix.py::_extract_init_sh_resolver``.
    Sourcing ``init.sh`` whole pulls in socket-path computation, env-file
    loading, and ``set -euo pipefail`` side effects we don't want in a
    timing benchmark.
    """
    text = INIT_SH.read_text()
    start = text.index("_resolve_python_cmd() {")
    depth = 0
    end = -1
    for i in range(start, len(text)):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end == -1:
        raise RuntimeError("could not find matching brace for _resolve_python_cmd")
    helper = tmp_path / "init_resolver.sh"
    helper.write_text(
        "#!/bin/bash\n"
        'PYTHON_CMD=""\n'
        'HOOKS_DAEMON_ROOT_DIR="${HOOKS_DAEMON_ROOT_DIR:-}"\n'
        'PROJECT_PATH="${PROJECT_PATH:-$HOOKS_DAEMON_ROOT_DIR}"\n' + text[start:end] + "\n"
    )
    return helper


def _build_fingerprint_keyed_fixture(tmp_path: Path) -> Path:
    """Plant a venv matching the host's fingerprint so step 2 succeeds.

    The fingerprint path is the realistic hot-path: a successfully-keyed
    venv is what every hook fire encounters in steady state. Forcing the
    scan-fallback would understate the latency cost.
    """
    daemon_dir = tmp_path / "daemon"
    daemon_dir.mkdir()
    install_dir = daemon_dir / "scripts" / "install"
    install_dir.mkdir(parents=True)
    (install_dir / "python_fingerprint.sh").symlink_to(FINGERPRINT_HELPER)

    lib_dir = daemon_dir / "scripts" / "lib"
    lib_dir.mkdir(parents=True)
    (lib_dir / "resolve_venv.sh").symlink_to(REPO_ROOT / "scripts" / "lib" / "resolve_venv.sh")
    ssot_parent = daemon_dir / "src" / "claude_code_hooks_daemon" / "daemon"
    ssot_parent.mkdir(parents=True)
    (ssot_parent / "paths.py").symlink_to(
        REPO_ROOT / "src" / "claude_code_hooks_daemon" / "daemon" / "paths.py"
    )

    untracked = daemon_dir / "untracked"
    untracked.mkdir()

    from claude_code_hooks_daemon.daemon.paths import python_venv_fingerprint

    fingerprint = python_venv_fingerprint(daemon_dir)
    venv = untracked / f"venv-{fingerprint}"
    (venv / "bin").mkdir(parents=True)
    (venv / "bin" / "python").symlink_to(sys.executable)

    return daemon_dir


def _measure_resolver_latency(daemon_dir: Path, helper: Path) -> list[float]:
    """Time ``_resolve_python_cmd`` ITERATIONS times in one bash session.

    Returns a list of per-iteration durations in milliseconds.
    """
    script = f"""
        source "{helper}"
        for _ in $(seq 1 {ITERATIONS}); do
            t0=$EPOCHREALTIME
            _resolve_python_cmd > /dev/null 2>&1
            t1=$EPOCHREALTIME
            python3 -c "print(($t1 - $t0) * 1000)"
        done
    """
    env = os.environ.copy()
    env["HOOKS_DAEMON_ROOT_DIR"] = str(daemon_dir)
    env["PROJECT_PATH"] = str(daemon_dir)
    env.pop("HOOKS_DAEMON_VENV_PATH", None)
    env.pop("HOOKS_DAEMON_PYTHON", None)

    result = subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    return [float(line) for line in result.stdout.strip().splitlines() if line.strip()]


def test_resolver_harness_produces_measurements(tmp_path: Path) -> None:
    """Smoke: the benchmark harness runs and emits ITERATIONS samples.

    Pins down that the bash-side timing scaffold is intact before the
    latency-budget assertion fires. Stays in place after Phase 8 makes
    the budget assertion pass.
    """
    daemon_dir = _build_fingerprint_keyed_fixture(tmp_path)
    helper = _extract_init_sh_resolver(tmp_path)

    latencies = _measure_resolver_latency(daemon_dir, helper)

    assert len(latencies) == ITERATIONS, (
        f"Harness produced {len(latencies)} samples, expected {ITERATIONS}. "
        "Check the bash loop and the EPOCHREALTIME formatter."
    )
    assert all(t > 0 for t in latencies), f"All latencies must be positive. Got: {latencies}"


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Plan 00104 Phase 3 Task 3.3 — drives Phase 8 Task 8.1 "
        "(post-consolidation latency optimisation). Today's "
        "_resolve_python_cmd takes >5ms median because the fingerprint "
        "path spawns python3 to compute the MD5. Phase 8 closes the gap "
        "by caching the fingerprint output (untracked/.python-cmd-cache "
        "or equivalent), letting steady-state hook fires skip the "
        "Python spawn. When that lands, median drops below 5ms and "
        "this xfail-strict flips to xpass."
    ),
)
def test_resolver_median_latency_under_budget(tmp_path: Path) -> None:
    """Steady-state hot-path: median resolve must be ``<5ms``.

    Runs ``_resolve_python_cmd`` ITERATIONS times against a fingerprint-
    keyed venv (the realistic post-bootstrap state) and asserts the
    median measured wall time is below the 5ms budget defined in
    PLAN.md Success Criteria #5.
    """
    daemon_dir = _build_fingerprint_keyed_fixture(tmp_path)
    helper = _extract_init_sh_resolver(tmp_path)

    latencies = _measure_resolver_latency(daemon_dir, helper)
    median_ms = statistics.median(latencies)

    assert median_ms < LATENCY_BUDGET_MS, (
        f"Median resolve latency {median_ms:.2f}ms exceeds the {LATENCY_BUDGET_MS}ms budget.\n"
        f"All samples: {[f'{t:.2f}' for t in latencies]}\n"
        "Phase 8 Task 8.1: cache the fingerprint output so steady-state "
        "hook fires skip the python3 spawn."
    )
