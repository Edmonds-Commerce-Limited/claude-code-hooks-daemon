"""One composite action provisions the CI Python environment (Plan 00572 Task 2.3).

The uv-from-lockfile install block had been pasted into nine jobs. Each copy
had to be edited together, and a drifted copy ran an unpinned toolchain. The
block lives in ``.github/actions/setup-env`` and every job uses it.
"""

from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = REPO / ".github" / "workflows"
ACTION = REPO / ".github" / "actions" / "setup-env" / "action.yml"
USES = "./.github/actions/setup-env"
#: release-assets.yml builds Rust only and carries no Python environment.
WORKFLOWS = ("qa.yml", "test-shards.yml", "release-gate.yml")
#: Fragments that identify an inline copy of the install block.
INLINE_MARKERS = ("uv sync", "pip install --user uv", "pip install uv")


def _jobs() -> dict[str, dict[str, Any]]:
    jobs: dict[str, dict[str, Any]] = {}
    for name in WORKFLOWS:
        document = yaml.safe_load((WORKFLOWS_DIR / name).read_text(encoding="utf-8"))
        for job_name, job in document["jobs"].items():
            if "uses" not in job:
                jobs[f"{name}:{job_name}"] = job
    return jobs


def test_the_composite_action_exists_and_is_composite() -> None:
    action = yaml.safe_load(ACTION.read_text(encoding="utf-8"))

    assert action["runs"]["using"] == "composite"
    assert "python-version" in action["inputs"]


def test_the_action_keys_its_uv_cache_on_uv_lock() -> None:
    action = yaml.safe_load(ACTION.read_text(encoding="utf-8"))

    cache_steps = [
        s for s in action["runs"]["steps"] if str(s.get("uses", "")).startswith("actions/cache")
    ]
    assert cache_steps, "the action has no cache step"
    assert "hashFiles('uv.lock')" in str(cache_steps[0]["with"]["key"])


def test_no_job_carries_an_inline_copy_of_the_install_block() -> None:
    offenders = [
        f"{name}:{step.get('name', step.get('uses'))}"
        for name, job in _jobs().items()
        for step in job["steps"]
        if any(marker in str(step.get("run", "")) for marker in INLINE_MARKERS)
    ]

    assert offenders == [], f"inline install blocks remain: {offenders}"


def test_every_job_that_sets_up_the_suite_environment_uses_the_action() -> None:
    users = [
        name for name, job in _jobs().items() if any(s.get("uses") == USES for s in job["steps"])
    ]

    # qa.yml: targeted, qa, map, perf-sweep, daemon-load; release-gate: two;
    # test-shards: two.
    assert len(users) == 9, users


def test_checkout_precedes_the_action_in_every_job() -> None:
    bad = []
    for name, job in _jobs().items():
        steps = job["steps"]
        for index, step in enumerate(steps):
            if step.get("uses") == USES and not any(
                str(s.get("uses", "")).startswith("actions/checkout") for s in steps[:index]
            ):
                bad.append(name)

    assert bad == [], f"action used before checkout: {bad}"


def test_every_use_passes_a_python_version() -> None:
    missing = [
        name
        for name, job in _jobs().items()
        for step in job["steps"]
        if step.get("uses") == USES and "python-version" not in step.get("with", {})
    ]

    assert missing == []
