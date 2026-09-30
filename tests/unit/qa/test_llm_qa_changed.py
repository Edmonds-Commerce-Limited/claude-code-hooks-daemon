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
from types import SimpleNamespace
from typing import Any

import pytest

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

    @pytest.mark.parametrize(
        "tool",
        [
            "eacces_safe",
            "shell_audit",
            "repo_hygiene",
            "doc_truth",
            "doc_snippets",
            "generated_doc_drift",
            "handler_reference",
            "hook_contract",
            "input_contract",
            "skill_refs",
            "canonical_callers",
            "authored_path_stat",
            "signal_targets",
            "unreachable_handle_branch",
            "fail_open_inventory",
            "security",
        ],
    )
    def test_the_cheap_repo_wide_static_checks_run_every_time(self, tool: str) -> None:
        """Ledger 00466: an `eacces_safe` break reached main because `changed` skipped it."""
        assert tool in llm_qa.CHANGED_TOOL_NAMES

    def test_no_changed_tool_needs_a_live_daemon(self) -> None:
        live = [n for n in llm_qa.CHANGED_TOOL_NAMES if llm_qa.TOOL_REGISTRY[n].live_daemon]
        assert live == []

    def test_every_changed_tool_is_registered(self) -> None:
        assert set(llm_qa.CHANGED_TOOL_NAMES) <= set(llm_qa.TOOL_REGISTRY)

    def test_all_does_not_run_the_targeted_tests_beside_the_whole_suite(self) -> None:
        assert "changed_tests" not in llm_qa.ALL_TOOL_NAMES
        tools, _ = llm_qa.resolve_tools(["all"])
        assert tools == llm_qa.ALL_TOOL_NAMES

    def test_a_named_tool_beside_changed_is_added_once(self) -> None:
        tools, _ = llm_qa.resolve_tools(["changed", "lint", "dependencies"])
        assert tools.count("lint") == 1
        assert tools[-1] == "dependencies"

    def test_an_unknown_name_is_reported(self) -> None:
        tools, unknown = llm_qa.resolve_tools(["lint", "bogus"])
        assert unknown == ["bogus"]
        assert tools == ["lint"]

    def test_changed_tests_can_be_named_on_its_own(self) -> None:
        tools, unknown = llm_qa.resolve_tools(["changed_tests"])
        assert (tools, unknown) == (["changed_tests"], [])


class TestTheChangedTestsTool:
    def test_an_empty_selection_says_nothing_ran_and_names_the_unmapped(self) -> None:
        line = llm_qa.SUMMARIZERS["changed_tests"](
            {
                "summary": {
                    "passed_all": False,
                    "total": 0,
                    "passed": 0,
                    "failed": 0,
                    "skipped": 0,
                    "errors": 0,
                    "files_considered": 4,
                    "test_files_selected": 0,
                },
                "unmapped": ["src/pkg/orphan.py"],
                "unmapped_allowed": False,
                "tests": [],
            }
        )
        assert "no tests ran" in line
        assert "4 changed files" in line
        assert "1 unmapped" in line
        assert "src/pkg/orphan.py" in line

    def test_an_allowed_unmapped_file_is_still_shown(self) -> None:
        line = llm_qa.SUMMARIZERS["changed_tests"](
            {
                "summary": {"files_considered": 1, "test_files_selected": 0},
                "unmapped": [".claude/hooks-daemon.yaml"],
                "unmapped_allowed": True,
                "tests": [],
            }
        )
        assert "allowed" in line
        assert ".claude/hooks-daemon.yaml" in line

    def test_each_unmapped_file_carries_its_reason(self) -> None:
        """Delta review N3f: "too broad" landed in `unmapped` with no reason given."""
        line = llm_qa.SUMMARIZERS["changed_tests"](
            {
                "summary": {"files_considered": 1, "test_files_selected": 0},
                "unmapped": ["src/pkg/hub.py"],
                "unmapped_reasons": {"src/pkg/hub.py": {"reason": "too-broad", "detail": "d"}},
                "unmapped_allowed": False,
                "tests": [],
            }
        )
        assert "src/pkg/hub.py [too-broad]" in line

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


class TestChangedOptions:
    """Review finding 11: `--base` and `--allow-unmapped` reach the runner."""

    def test_the_options_are_forwarded_to_changed_tests(self) -> None:
        args, extra, error = llm_qa.split_changed_options(
            ["changed", "--base", "trunk", "--allow-unmapped"]
        )
        assert error is None
        assert args == ["changed"]
        assert extra == ["--base", "trunk", "--allow-unmapped"]

    def test_the_equals_form_is_accepted(self) -> None:
        _, extra, error = llm_qa.split_changed_options(["changed", "--base=trunk"])
        assert (extra, error) == (["--base", "trunk"], None)

    def test_a_base_with_no_value_is_an_error(self) -> None:
        _, _, error = llm_qa.split_changed_options(["changed", "--base"])
        assert error is not None

    def test_the_options_without_changed_tests_are_an_error(self) -> None:
        _, _, error = llm_qa.split_changed_options(["lint", "--allow-unmapped"])
        assert error is not None

    def test_a_range_is_forwarded(self) -> None:
        """The batched gate's targeted recheck: exactly what a move of main brought in."""
        args, extra, error = llm_qa.split_changed_options(
            ["changed", "british_english", "--range", "a..b"]
        )
        assert error is None
        assert args == ["changed", "british_english"]
        assert extra == ["--range", "a..b"]

    def test_the_range_equals_form_is_accepted(self) -> None:
        _, extra, error = llm_qa.split_changed_options(["changed", "--range=a..b"])
        assert (extra, error) == (["--range", "a..b"], None)

    @pytest.mark.parametrize("args", [["changed", "--range"], ["lint", "--range", "a..b"]])
    def test_a_range_with_no_value_or_no_changed_is_an_error(self, args: list[str]) -> None:
        _, _, error = llm_qa.split_changed_options(args)
        assert error is not None

    def test_run_tool_puts_the_forwarded_options_on_the_command_it_runs(
        self, monkeypatch: Any
    ) -> None:
        launched: list[list[str]] = []

        def fake_run(argv: list[str], **_: Any) -> Any:
            launched.append(argv)
            return SimpleNamespace(returncode=0)

        monkeypatch.setattr(llm_qa, "venv_python", lambda: Path("/venv/bin/python"))
        monkeypatch.setattr(llm_qa.subprocess, "run", fake_run)
        assert llm_qa.run_tool("changed_tests", ["--base", "trunk"]) == 0
        (argv,) = launched
        assert argv[0] == "/venv/bin/python"
        assert argv[-2:] == ["--base", "trunk"]
        assert "run_changed_tests.py" in " ".join(argv)


def test_the_usage_line_names_changed(capsys: Any, monkeypatch: Any) -> None:
    monkeypatch.setattr(sys, "argv", ["llm_qa.py", "--help"])
    assert llm_qa.main() == llm_qa.EXIT_SUCCESS
    assert "changed" in capsys.readouterr().out
