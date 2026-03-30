"""Unit tests for the smoke_test QA check (live daemon probe).

Tests cover:
- run_smoke_test.sh exists and is executable
- llm_qa.py TOOL_REGISTRY contains smoke_test entry
- _summarize_smoke_test produces correct summaries
- _is_passed correctly reads smoke_test JSON
- JSON output schema is valid (all required keys present)
"""

from __future__ import annotations

import importlib.util
import stat
import types
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = PROJECT_ROOT / "scripts" / "qa"


# ── Helpers ────────────────────────────────────────────────────────


def _load_llm_qa() -> types.ModuleType:
    """Dynamically import llm_qa module (not on sys.path by default)."""
    spec = importlib.util.spec_from_file_location("llm_qa", SCRIPTS_DIR / "llm_qa.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _make_smoke_json(
    passed: bool,
    passed_probes: int = 3,
    failed_probes: int = 0,
    probes: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a minimal valid smoke_test JSON output."""
    return {
        "tool": "smoke_test",
        "summary": {
            "total_probes": passed_probes + failed_probes,
            "passed_probes": passed_probes,
            "failed_probes": failed_probes,
            "passed": passed,
        },
        "probes": probes or [],
    }


# ── Script existence & permissions ────────────────────────────────


class TestSmokeTestScript:
    """Verify the bash script exists and has correct permissions."""

    def test_script_exists(self) -> None:
        script = SCRIPTS_DIR / "run_smoke_test.sh"
        assert script.exists(), f"run_smoke_test.sh not found at {script}"

    def test_script_is_executable(self) -> None:
        script = SCRIPTS_DIR / "run_smoke_test.sh"
        assert script.exists(), "Script missing — cannot check permissions"
        mode = script.stat().st_mode
        assert bool(mode & stat.S_IXUSR), "run_smoke_test.sh is not executable (chmod +x needed)"

    def test_script_is_bash(self) -> None:
        script = SCRIPTS_DIR / "run_smoke_test.sh"
        assert script.exists(), "Script missing"
        first_line = script.read_text().splitlines()[0]
        assert first_line.startswith(
            "#!/bin/bash"
        ), f"Expected #!/bin/bash shebang, got: {first_line!r}"


# ── llm_qa.py registry integration ────────────────────────────────


class TestLlmQaRegistry:
    """Verify smoke_test appears in the llm_qa TOOL_REGISTRY."""

    def test_smoke_test_in_registry(self) -> None:
        module = _load_llm_qa()
        registry: dict[str, Any] = module.TOOL_REGISTRY
        assert (
            "smoke_test" in registry
        ), f"'smoke_test' missing from TOOL_REGISTRY. Keys: {list(registry)}"

    def test_smoke_test_in_all_tool_names(self) -> None:
        module = _load_llm_qa()
        all_names: list[str] = module.ALL_TOOL_NAMES
        assert (
            "smoke_test" in all_names
        ), "'smoke_test' not in ALL_TOOL_NAMES — won't run with 'llm_qa.py all'"

    def test_smoke_test_registry_has_required_fields(self) -> None:
        module = _load_llm_qa()
        registry: dict[str, Any] = module.TOOL_REGISTRY
        if "smoke_test" not in registry:
            pytest.skip("smoke_test not in registry yet")
        config = registry["smoke_test"]
        assert config.command, "command must be non-empty"
        assert (
            config.json_file == "smoke_test.json"
        ), f"json_file should be 'smoke_test.json', got {config.json_file!r}"
        assert config.jq_hint, "jq_hint must be non-empty"

    def test_smoke_test_has_summarizer(self) -> None:
        module = _load_llm_qa()
        summarizers: dict[str, Callable[[dict[str, Any]], str]] = module.SUMMARIZERS
        assert "smoke_test" in summarizers, "'smoke_test' missing from SUMMARIZERS dict"

    def test_smoke_test_is_last_in_registry(self) -> None:
        """smoke_test should be the last check (check 9)."""
        module = _load_llm_qa()
        all_names: list[str] = module.ALL_TOOL_NAMES
        if "smoke_test" not in all_names:
            pytest.skip("smoke_test not in registry yet")
        assert (
            all_names[-1] == "smoke_test"
        ), f"smoke_test should be the last tool, but order is: {all_names}"


# ── Summarizer output ──────────────────────────────────────────────


class TestSmokeTestSummarizer:
    """Verify the summarizer produces human-readable output."""

    def test_all_pass_summary(self) -> None:
        module = _load_llm_qa()
        summarizers: dict[str, Callable[[dict[str, Any]], str]] = module.SUMMARIZERS
        data = _make_smoke_json(passed=True, passed_probes=3, failed_probes=0)
        result = summarizers["smoke_test"](data)
        assert (
            "3/3" in result or "3 passed" in result
        ), f"Expected pass count in summary, got: {result!r}"

    def test_partial_fail_summary(self) -> None:
        module = _load_llm_qa()
        summarizers: dict[str, Callable[[dict[str, Any]], str]] = module.SUMMARIZERS
        data = _make_smoke_json(passed=False, passed_probes=2, failed_probes=1)
        result = summarizers["smoke_test"](data)
        assert (
            "2/3" in result or "1 failed" in result
        ), f"Expected fail info in summary, got: {result!r}"

    def test_all_fail_summary(self) -> None:
        module = _load_llm_qa()
        summarizers: dict[str, Callable[[dict[str, Any]], str]] = module.SUMMARIZERS
        data = _make_smoke_json(passed=False, passed_probes=0, failed_probes=3)
        result = summarizers["smoke_test"](data)
        assert (
            "0/3" in result or "3 failed" in result
        ), f"Expected fail count in summary, got: {result!r}"


# ── JSON schema ────────────────────────────────────────────────────


class TestSmokeTestJsonSchema:
    """Verify the expected JSON output schema is valid for llm_qa.py."""

    @pytest.mark.parametrize(
        "passed,p,f",
        [
            (True, 3, 0),
            (False, 2, 1),
            (False, 0, 3),
        ],
    )
    def test_is_passed_reads_summary_correctly(self, passed: bool, p: int, f: int) -> None:
        module = _load_llm_qa()
        is_passed_fn: Callable[[dict[str, Any]], bool] = module._is_passed
        data = _make_smoke_json(passed=passed, passed_probes=p, failed_probes=f)
        result = is_passed_fn(data)
        assert (
            result is passed
        ), f"_is_passed({data['summary']}) returned {result!r}, expected {passed!r}"

    def test_required_top_level_keys(self) -> None:
        data = _make_smoke_json(passed=True)
        for key in ("tool", "summary", "probes"):
            assert key in data, f"Missing required key: {key!r}"

    def test_required_summary_keys(self) -> None:
        data = _make_smoke_json(passed=True)
        summary = data["summary"]
        for key in ("total_probes", "passed_probes", "failed_probes", "passed"):
            assert key in summary, f"Missing required summary key: {key!r}"
