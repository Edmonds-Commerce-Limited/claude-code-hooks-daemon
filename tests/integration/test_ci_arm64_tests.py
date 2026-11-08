"""The arm64 unit-test job is informative, never a gate.

Plan 00572 Task 3.3. The unit suite runs on an arm64 runner so an
architecture-specific regression is seen, but the leg is new and its flakes
are not yet known: it must not be able to fail a run or the QA gate.
"""

from pathlib import Path
from typing import Any

import yaml

QA_YML = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "qa.yml"


def _workflow() -> dict[str, Any]:
    return yaml.safe_load(QA_YML.read_text(encoding="utf-8"))


def _job() -> dict[str, Any]:
    return _workflow()["jobs"]["arm64-tests"]


def _runs() -> str:
    return "\n".join(step.get("run", "") for step in _job()["steps"])


def test_the_job_runs_on_the_arm64_runner() -> None:
    assert _job()["runs-on"] == "ubuntu-24.04-arm"


def test_the_job_is_non_blocking() -> None:
    assert _job()["continue-on-error"] is True


def test_the_gate_does_not_wait_on_the_job() -> None:
    assert "arm64-tests" not in _workflow()["jobs"]["qa-gate"]["needs"]


def test_the_job_skips_the_docs_tier() -> None:
    assert _job()["needs"] == "classify"
    assert "!= 'docs'" in _job()["if"]


def test_the_job_provisions_through_the_shared_action() -> None:
    uses = [step.get("uses", "") for step in _job()["steps"]]
    assert "./.github/actions/setup-env" in uses


def test_the_job_builds_the_relay_for_the_host_architecture() -> None:
    runs = _runs()
    assert "aarch64-unknown-linux-musl" in runs
    assert "x86_64" not in runs


def test_the_job_runs_the_unit_shards() -> None:
    runs = _runs()
    assert "run_test_matrix.py" in runs
    assert "unit-core" in runs


def test_the_job_declares_a_timeout() -> None:
    assert "timeout-minutes" in _job()
