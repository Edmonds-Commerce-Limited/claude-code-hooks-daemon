"""``llm_qa.py changed``: the one targeted command a sub-agent runs (Plan 00463).

``subagent_full_qa_blocker`` denies a sub-agent's full-suite run and names
what to run instead. That only works if the alternative is ONE command. Left
to judgement, each agent picks its own subset, and some pick nothing.
``changed`` is that command: the fast static tools plus pytest on the tests
mapped from what changed since the merge base.

Two things must hold, or the split costs more than it saves:

- ``changed`` is not a smaller ``all``. It must not drag in the whole suite
  through the ``tests`` tool, and ``all`` must not run the targeted tests a
  second time beside the whole suite.
- The summary line says when the targeted run ran nothing, because "0 failed"
  for an empty selection reads as a pass.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _load(script: str, name: str) -> Any:
    """Import a file under ``scripts/qa/``, which is a script rather than a module."""
    module_path = PROJECT_ROOT / "scripts" / "qa" / script
    spec = importlib.util.spec_from_file_location(name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


llm_qa = _load("llm_qa.py", "llm_qa_for_changed_test")


class TestTheChangedSelection:
    def test_changed_expands_to_the_targeted_tool_list(self) -> None:
        tools, unknown = llm_qa.resolve_tools(["changed"])
        assert unknown == []
        assert tools == llm_qa.CHANGED_TOOL_NAMES

    def test_changed_never_includes_the_whole_suite(self) -> None:
        assert "tests" not in llm_qa.CHANGED_TOOL_NAMES

    def test_changed_carries_the_fast_static_tools_and_the_targeted_tests(self) -> None:
        expected = {
            "format",
            "lint",
            "type_check",
            "pyright",
            "magic_values",
            "error_hiding",
            "project_handlers",
            "changed_tests",
        }
        assert set(llm_qa.CHANGED_TOOL_NAMES) == expected

    def test_every_changed_tool_is_registered(self) -> None:
        assert set(llm_qa.CHANGED_TOOL_NAMES) <= set(llm_qa.TOOL_REGISTRY)

    def test_all_does_not_run_the_targeted_tests_beside_the_whole_suite(self) -> None:
        assert "changed_tests" not in llm_qa.ALL_TOOL_NAMES
        tools, _ = llm_qa.resolve_tools(["all"])
        assert tools == llm_qa.ALL_TOOL_NAMES

    def test_a_named_tool_beside_changed_is_added_once(self) -> None:
        tools, _ = llm_qa.resolve_tools(["changed", "lint", "security"])
        assert tools.count("lint") == 1
        assert tools[-1] == "security"

    def test_an_unknown_name_is_reported(self) -> None:
        tools, unknown = llm_qa.resolve_tools(["lint", "bogus"])
        assert unknown == ["bogus"]
        assert tools == ["lint"]

    def test_changed_tests_can_be_named_on_its_own(self) -> None:
        tools, unknown = llm_qa.resolve_tools(["changed_tests"])
        assert (tools, unknown) == (["changed_tests"], [])


class TestTheChangedTestsTool:
    def test_it_writes_its_own_report(self) -> None:
        config = llm_qa.TOOL_REGISTRY["changed_tests"]
        assert config.json_file == "changed_tests.json"
        assert "run_changed_tests.py" in " ".join(config.command)

    def test_it_is_summarised(self) -> None:
        assert "changed_tests" in llm_qa.SUMMARIZERS

    def test_an_empty_selection_says_nothing_ran(self) -> None:
        line = llm_qa.SUMMARIZERS["changed_tests"](
            {
                "summary": {
                    "passed_all": True,
                    "total": 0,
                    "passed": 0,
                    "failed": 0,
                    "skipped": 0,
                    "errors": 0,
                    "files_considered": 4,
                    "test_files_selected": 0,
                },
                "unmapped": ["src/pkg/orphan.py"],
                "tests": [],
            }
        )
        assert "no tests ran" in line
        assert "4 changed files" in line
        assert "1 unmapped" in line

    def test_a_failure_is_named_in_the_summary(self) -> None:
        line = llm_qa.SUMMARIZERS["changed_tests"](
            {
                "summary": {
                    "passed_all": False,
                    "total": 3,
                    "passed": 2,
                    "failed": 1,
                    "skipped": 0,
                    "errors": 0,
                    "files_considered": 1,
                    "test_files_selected": 1,
                },
                "unmapped": [],
                "tests": [{"name": "tests/unit/test_a.py::test_x", "outcome": "failed"}],
            }
        )
        assert "2 passed, 1 failed" in line
        assert "tests/unit/test_a.py::test_x" in line
        assert "1 test files from 1 changed files" in line

    def test_smoke_test_stays_last(self) -> None:
        assert list(llm_qa.TOOL_REGISTRY)[-1] == "smoke_test"


def test_the_usage_line_names_changed(capsys: Any, monkeypatch: Any) -> None:
    monkeypatch.setattr(sys, "argv", ["llm_qa.py", "--help"])
    assert llm_qa.main() == llm_qa.EXIT_SUCCESS
    assert "changed" in capsys.readouterr().out
