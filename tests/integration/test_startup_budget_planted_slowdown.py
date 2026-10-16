"""Plan 00495 Task 3.1: the start-up budget check really measures a daemon start.

A real run on a throwaway project passes against a generous budget, and the same run
fails once a slowdown is planted in the start path. The slowdown is a
``sitecustomize.py`` on ``PYTHONPATH`` that burns CPU in every Python process the check
starts, so nothing in the script under test is switched or stubbed.

The budget here is the test's own (``cpu_seconds`` 4): a clean start costs about 1 s of
CPU and the planted burn adds 6 s, so both verdicts keep a wide margin on a loaded host
(CPU seconds, unlike wall time, do not grow with the host's run queue).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "release" / "check_startup_budget.py"
TEST_BUDGET_CPU_SECONDS = 4.0
PLANTED_BURN_SECONDS = 6.0
RUN_TIMEOUT_SECONDS = 600

pytestmark = pytest.mark.slow


def _run(tmp_path: Path, *, plant: bool) -> subprocess.CompletedProcess[str]:
    budget = tmp_path / "budget.json"
    budget.write_text(
        json.dumps({"cpu_seconds": TEST_BUDGET_CPU_SECONDS, "samples": 1, "attempts": 1}),
        encoding="utf-8",
    )
    env = {**os.environ}
    if plant:
        plant_dir = tmp_path / "plant"
        plant_dir.mkdir()
        (plant_dir / "sitecustomize.py").write_text(
            "import time\n"
            f"_end = time.process_time() + {PLANTED_BURN_SECONDS}\n"
            "while time.process_time() < _end:\n"
            "    pass\n",
            encoding="utf-8",
        )
        env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(plant_dir), env.get("PYTHONPATH")]))
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--budget-file", str(budget)],
        capture_output=True,
        text=True,
        env=env,
        timeout=RUN_TIMEOUT_SECONDS,
        check=False,
    )


def test_an_unplanted_start_passes(tmp_path: Path) -> None:
    result = _run(tmp_path, plant=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS" in result.stdout


def test_a_planted_slowdown_fails(tmp_path: Path) -> None:
    result = _run(tmp_path, plant=True)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "FAIL" in result.stdout
