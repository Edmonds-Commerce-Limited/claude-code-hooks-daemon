"""Plan 00476 Design 6: CPU-timing sweeps are marked and run in their own CI job.

A test whose assertion is a CPU-time bound (``scaled_cpu_seconds``) misses it
when the full suite loads the runner, so it carries ``perf_sweep``; the whole-
suite CI steps deselect that marker and a dedicated job runs only it. Thresholds
are never loosened.
"""

from __future__ import annotations

import ast
import tomllib
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[3]
TESTS = REPO / "tests"
WORKFLOW = REPO / ".github" / "workflows" / "qa.yml"
FALLBACK_SCRIPT = REPO / "scripts" / "ci" / "full_suite_if_unmapped.bash"

MARKER = "perf_sweep"
BOUND_HELPER = "scaled_cpu_seconds"

#: Files that define or unit-test the helper rather than assert a time bound.
_NOT_SWEEPS = frozenset({"load_scaling.py", "unit/test_load_scaling.py"})


def _marker_names(decorators: list[ast.expr]) -> set[str]:
    """Names of ``pytest.mark.<name>`` decorators (called or bare)."""
    names: set[str] = set()
    for decorator in decorators:
        node = decorator.func if isinstance(decorator, ast.Call) else decorator
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Attribute)
            and node.value.attr == "mark"
        ):
            names.add(node.attr)
    return names


def _uses_bound_helper(function: ast.FunctionDef) -> bool:
    return any(
        isinstance(node, ast.Name) and node.id == BOUND_HELPER for node in ast.walk(function)
    )


def unmarked_sweeps(source: str) -> list[str]:
    """Test functions that call the CPU bound helper without the marker."""
    tree = ast.parse(source)
    offenders: list[str] = []

    def visit(body: list[ast.stmt], inherited: set[str]) -> None:
        for node in body:
            if isinstance(node, ast.ClassDef):
                visit(node.body, inherited | _marker_names(node.decorator_list))
            elif isinstance(node, ast.FunctionDef) and node.name.startswith("test"):
                carried = inherited | _marker_names(node.decorator_list)
                if _uses_bound_helper(node) and MARKER not in carried:
                    offenders.append(node.name)

    visit(tree.body, set())
    return offenders


class TestEveryCpuTimingTestCarriesTheMarker:
    def test_no_test_using_the_cpu_bound_is_unmarked(self) -> None:
        offenders: list[str] = []
        for path in sorted(TESTS.rglob("*.py")):
            relative = path.relative_to(TESTS).as_posix()
            if relative in _NOT_SWEEPS or relative.startswith("fixtures/"):
                continue
            offenders.extend(f"{relative}::{name}" for name in unmarked_sweeps(path.read_text()))
        assert not offenders, (
            f"these tests assert a {BOUND_HELPER} bound but lack @pytest.mark.{MARKER}, so "
            "they would run in the loaded full-suite step:\n  " + "\n  ".join(offenders)
        )

    def test_the_scan_sees_a_bare_unmarked_test(self) -> None:
        source = "def test_x():\n    assert t < scaled_cpu_seconds(1)\n"
        assert unmarked_sweeps(source) == ["test_x"]

    def test_the_scan_accepts_a_function_marker(self) -> None:
        source = (
            "import pytest\n@pytest.mark.perf_sweep\n"
            "def test_x():\n    assert t < scaled_cpu_seconds(1)\n"
        )
        assert unmarked_sweeps(source) == []

    def test_the_scan_accepts_a_class_marker(self) -> None:
        source = (
            "import pytest\n@pytest.mark.perf_sweep\nclass TestX:\n"
            "    def test_x(self):\n        assert t < scaled_cpu_seconds(1)\n"
        )
        assert unmarked_sweeps(source) == []

    def test_at_least_one_sweep_is_marked(self) -> None:
        marked = [
            path
            for path in TESTS.rglob("test_*.py")
            if path != Path(__file__) and f"pytest.mark.{MARKER}" in path.read_text()
        ]
        assert marked


class TestTheMarkerIsRegistered:
    def test_pyproject_registers_it(self) -> None:
        config = tomllib.loads((REPO / "pyproject.toml").read_text())
        markers = config["tool"]["pytest"]["ini_options"]["markers"]
        assert any(entry.startswith(f"{MARKER}:") for entry in markers)


def _steps(job: str) -> list[dict[str, str]]:
    document = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps: list[dict[str, str]] = document["jobs"][job]["steps"]
    return steps


class TestTheLoadedStepsDeselectTheSweeps:
    def test_the_full_suite_fallback_deselects_them(self) -> None:
        text = FALLBACK_SCRIPT.read_text()
        assert f'pytest tests/ -rs -m "not {MARKER}"' in text

    def test_the_matrix_whole_suite_step_deselects_them(self) -> None:
        run = next(s["run"] for s in _steps("qa") if s.get("name") == "Tests + coverage")
        assert f'-m "not {MARKER}"' in run


class TestTheDedicatedJob:
    def test_it_exists_and_runs_only_the_marked_tests_serially(self) -> None:
        document = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
        job = document["jobs"]["perf-sweep"]
        runs = "\n".join(s.get("run", "") for s in job["steps"])
        assert f"-m {MARKER}" in runs
        assert "-n " not in runs and "xdist" not in runs
        assert "--cov" not in runs
        assert job["needs"] == "classify"
        assert "if" not in job, "every tier can reach a whole-suite step, so it always runs"
        assert isinstance(job["timeout-minutes"], int)
