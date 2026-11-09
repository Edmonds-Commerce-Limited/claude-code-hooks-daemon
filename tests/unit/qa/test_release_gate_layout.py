"""The release-gate workflow's check lists and shard matrix agree with llm_qa (Plan 00474 N539).

The workflow's own `layout` job makes the same comparison, but only on a release pull request, so a check added
to `llm_qa.py` without a line in the workflow surfaced there and nowhere earlier. These tests fail the commit
that causes the drift instead.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "release-gate.yml"
SHARDS_WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "test-shards.yml"
SHARD_LEGS_SCRIPT = REPO_ROOT / "scripts" / "ci" / "shard_legs.py"
SHARDS_PATH = REPO_ROOT / "scripts" / "qa" / "test_shards.yaml"
QA_SCRIPTS_DIR = REPO_ROOT / "scripts" / "qa"
CHECK_GROUPS = ("CHECKS_STATIC", "CHECKS_PYRIGHT", "CHECKS_DOCS", "CHECKS_CONTRACTS")
TESTS_JOB_CHECK = "tests"


@pytest.fixture(scope="module")
def workflow() -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    return loaded


@pytest.fixture(scope="module")
def all_tool_names() -> set[str]:
    """Import `scripts/qa/llm_qa.py`, which is a script rather than a module."""
    module_path = QA_SCRIPTS_DIR / "llm_qa.py"
    spec = importlib.util.spec_from_file_location("llm_qa_for_release_gate_layout", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return set(module.ALL_TOOL_NAMES)


def _listed_checks(workflow: dict[str, Any]) -> list[str]:
    env: dict[str, str] = workflow["env"]
    return [check for group in CHECK_GROUPS for check in env[group].split()] + [TESTS_JOB_CHECK]


def _shard_names() -> set[str]:
    shards: list[dict[str, Any]] = yaml.safe_load(SHARDS_PATH.read_text(encoding="utf-8"))["shards"]
    return {shard["name"] for shard in shards}


class TestCheckLists:
    def test_every_llm_qa_check_is_listed_and_nothing_else(
        self, workflow: dict[str, Any], all_tool_names: set[str]
    ) -> None:
        listed = set(_listed_checks(workflow))
        assert sorted(all_tool_names - listed) == [], "llm_qa checks missing from release-gate.yml"
        assert (
            sorted(listed - all_tool_names) == []
        ), "release-gate.yml lists checks llm_qa does not have"

    def test_no_check_is_listed_twice(self, workflow: dict[str, Any]) -> None:
        listed = _listed_checks(workflow)
        assert sorted({check for check in listed if listed.count(check) > 1}) == []


def _shard_legs() -> Any:
    spec = importlib.util.spec_from_file_location("shard_legs_for_release_gate", SHARD_LEGS_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {SHARD_LEGS_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class TestShardMatrix:
    """The gate's tests run the `full` profile of scripts/ci/shard_legs.yaml (Plan 00572)."""

    def test_the_tests_job_calls_the_shared_workflow_with_the_full_profile(
        self, workflow: dict[str, Any]
    ) -> None:
        job = workflow["jobs"]["tests"]
        assert job["uses"] == "./.github/workflows/test-shards.yml"
        assert job["with"]["profile"] == "full"

    def test_every_python_runs_every_shard_and_coverage_is_one_python(self) -> None:
        legs = _shard_legs()
        full = legs.load_profiles()["full"]
        assert legs.check("full", full, sorted(_shard_names())) == []
        assert sorted(legs.coverage_shards(full)) == sorted(_shard_names())

    def test_the_layout_job_runs_the_legs_check(self, workflow: dict[str, Any]) -> None:
        runs = "\n".join(s.get("run", "") for s in workflow["jobs"]["layout"]["steps"])
        assert "scripts/ci/shard_legs.py --check" in runs

    def test_the_aggregator_still_needs_the_tests(self, workflow: dict[str, Any]) -> None:
        assert "tests" in workflow["jobs"]["release-gate"]["needs"]
        assert workflow["jobs"]["release-gate"]["name"] == "Release gate"


class TestASupersededRunIsCancelled:
    """Plan 00576: a new push to the release branch cancels the run it supersedes.

    Every fix during a release is a push, and each push starts a run of the better part of an hour. Without
    the group, the stale run keeps its runners until it ends, and Step 8c must tell it apart from the live one.
    The group is keyed on the pull request (a manual run falls back to the ref) and prefixed with the
    workflow's own name, so it never cancels a `qa.yml` run on the same branch.
    """

    def test_the_workflow_cancels_in_progress_runs_of_the_same_pull_request(
        self, workflow: dict[str, Any]
    ) -> None:
        concurrency: dict[str, Any] = workflow["concurrency"]
        assert concurrency["cancel-in-progress"] is True
        group = str(concurrency["group"])
        assert group.startswith("release-gate-")
        assert "github.event.pull_request.number" in group
        assert "github.ref" in group


TMPDIR_EXPORT ='echo "TMPDIR=/ci-tmp" >> "$GITHUB_ENV"'


class TestTemporaryFilesLiveOnTheRootDisk:
    """Runner image ubuntu26/20261101.64 caps /tmp, and the integration shard's tmp_path trees outgrew it.

    Every test leg on that image failed with EDQUOT under /tmp/pytest-of-runner, while the same commit
    passed on the previous image. TMPDIR must still be short, and must have no ancestor but `/`. RUNNER_TEMP
    failed both tests: it sits under /home/runner, which holds a `.claude` directory that root-discovery
    tests found, and its length broke the AF_UNIX socket path limit.
    """

    def test_the_tests_job_exports_tmpdir_before_running_the_shards(self) -> None:
        shards_workflow = yaml.safe_load(SHARDS_WORKFLOW_PATH.read_text(encoding="utf-8"))
        steps: list[dict[str, Any]] = shards_workflow["jobs"]["tests"]["steps"]
        names = [str(step.get("name", "")) for step in steps]
        exporting = [i for i, step in enumerate(steps) if TMPDIR_EXPORT in str(step.get("run", ""))]
        assert exporting, "no step of the tests job exports TMPDIR=/ci-tmp"
        assert exporting[0] < names.index("Run the shards")
