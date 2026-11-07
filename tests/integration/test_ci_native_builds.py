"""The native-builds job builds and runs the relay and hooks-screen natively.

Plan 00572 Task 3.1. Both binaries are static musl builds; cross-compiling
proves they link, not that they run. A native leg per architecture executes
each one, so an arm64 regression fails on an arm64 runner.
"""

from pathlib import Path
from typing import Any

import yaml

QA_YML = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "qa.yml"


def _workflow() -> dict[str, Any]:
    return yaml.safe_load(QA_YML.read_text(encoding="utf-8"))


def _job() -> dict[str, Any]:
    return _workflow()["jobs"]["native-builds"]


def _runs() -> str:
    return "\n".join(step.get("run", "") for step in _job()["steps"])


def test_the_matrix_covers_both_architectures_on_native_runners() -> None:
    legs = _job()["strategy"]["matrix"]["include"]
    pairs = {(leg["runner"], leg["triple_arch"]) for leg in legs}
    assert pairs == {
        ("ubuntu-latest", "x86_64"),
        ("ubuntu-24.04-arm", "aarch64"),
    }


def test_the_matrix_does_not_cancel_the_other_leg() -> None:
    assert _job()["strategy"]["fail-fast"] is False


def test_the_job_skips_the_docs_tier() -> None:
    assert _job()["needs"] == "classify"
    assert "!= 'docs'" in _job()["if"]


def test_the_job_builds_and_runs_both_binaries() -> None:
    runs = _runs()
    assert "relay/build.sh" in runs
    assert "screen/build.sh" in runs
    assert "hooks-relay-" in runs
    assert "hooks-screen-" in runs


def test_the_job_checks_the_binary_is_for_the_runner_architecture() -> None:
    assert "readelf -h" in _runs()


def test_the_aggregator_needs_the_job() -> None:
    assert "native-builds" in _workflow()["jobs"]["qa-gate"]["needs"]


def test_the_job_declares_a_timeout() -> None:
    assert "timeout-minutes" in _job()
