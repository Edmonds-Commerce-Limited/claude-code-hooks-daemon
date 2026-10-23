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


class TestShardMatrix:
    def test_every_python_runs_every_shard(self, workflow: dict[str, Any]) -> None:
        include: list[dict[str, Any]] = workflow["jobs"]["tests"]["strategy"]["matrix"]["include"]
        by_python: dict[str, list[str]] = {}
        for entry in include:
            by_python.setdefault(str(entry["python"]), []).extend(entry["shards"].split())
        names = sorted(_shard_names())
        for python, chosen in by_python.items():
            assert sorted(chosen) == names, f"Python {python} runs the wrong shards"

    def test_coverage_is_one_python_and_combines_every_shard(
        self, workflow: dict[str, Any]
    ) -> None:
        include: list[dict[str, Any]] = workflow["jobs"]["tests"]["strategy"]["matrix"]["include"]
        coverage_pythons = {str(entry["python"]) for entry in include if entry["coverage"]}
        assert len(coverage_pythons) == 1
        for entry in include:
            assert bool(entry["coverage"]) == (str(entry["python"]) in coverage_pythons), entry[
                "name"
            ]
        combined = workflow["jobs"]["coverage"]["env"]["SHARDS"].split()
        assert sorted(combined) == sorted(_shard_names())
