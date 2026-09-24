"""The targeted test runner behind ``llm_qa.py changed`` (Plan 00463).

Sub-agents run targeted QA; the coordinator runs the full suite, once per
delivery. The allowed path has to be ONE command rather than a judgement call,
or each agent reinvents its own subset and some reinvent nothing. This runner
is that command's test half: pytest on the tests mapped from what changed
since the merge base.

It is a heuristic by design. The mapping is by module NAME, not by import
graph, because the coordinator's full gate is the backstop for everything a
name cannot see. What the report must never do is overstate: a run that
selected nothing says so, and a source file with no mapped test is listed
rather than quietly dropped.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
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


changed_tests = _load("run_changed_tests.py", "run_changed_tests_under_test")

_MERGE_BASE = "0" * 40


def _touch(root: Path, *relative: str) -> None:
    for path in relative:
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("", encoding="utf-8")


def _git_answering(diff: str = "", untracked: str = "", merge_base_code: int = 0) -> Any:
    """A ``run_git`` stand-in that answers the three calls the runner makes."""

    def run(args: list[str], root: Path) -> tuple[int, str, str]:
        assert root.is_absolute()
        if args[0] == "merge-base":
            if merge_base_code:
                return merge_base_code, "", "fatal: Not a valid object name main"
            return 0, f"{_MERGE_BASE}\n", ""
        if args[0] == "diff":
            assert args[-1] == _MERGE_BASE, "the diff must be taken against the merge base"
            return 0, diff, ""
        if args[0] == "ls-files":
            return 0, untracked, ""
        raise AssertionError(f"unexpected git call: {args}")

    return run


class TestChangedFiles:
    def test_committed_working_tree_and_untracked_changes_are_all_seen(
        self, tmp_path: Path
    ) -> None:
        git = _git_answering(diff="src/pkg/a.py\nREADME.md\n", untracked="tests/unit/test_b.py\n")
        files, error = changed_tests.changed_files(tmp_path, "main", git=git)
        assert error is None
        assert files == ["README.md", "src/pkg/a.py", "tests/unit/test_b.py"]

    def test_no_merge_base_is_an_error_not_an_empty_change_set(self, tmp_path: Path) -> None:
        """An empty list would read as 'nothing changed' and select nothing."""
        files, error = changed_tests.changed_files(
            tmp_path, "main", git=_git_answering(merge_base_code=128)
        )
        assert files is None
        assert error is not None
        assert "main" in error


class TestSelection:
    def test_a_changed_test_file_selects_itself(self, tmp_path: Path) -> None:
        _touch(tmp_path, "tests/unit/test_thing.py")
        index = changed_tests.build_test_index(tmp_path)
        selected, unmapped = changed_tests.select_tests(
            ["tests/unit/test_thing.py"], index, tmp_path
        )
        assert selected == ["tests/unit/test_thing.py"]
        assert unmapped == []

    def test_a_source_module_selects_its_named_tests_and_their_variants(
        self, tmp_path: Path
    ) -> None:
        _touch(
            tmp_path,
            "src/pkg/utils/shell_segmentation.py",
            "tests/unit/utils/test_shell_segmentation.py",
            "tests/unit/handlers/test_shell_segmentation_heredocs.py",
            "tests/unit/utils/test_shell.py",
        )
        index = changed_tests.build_test_index(tmp_path)
        selected, unmapped = changed_tests.select_tests(
            ["src/pkg/utils/shell_segmentation.py"], index, tmp_path
        )
        assert selected == [
            "tests/unit/handlers/test_shell_segmentation_heredocs.py",
            "tests/unit/utils/test_shell_segmentation.py",
        ]
        assert unmapped == []

    def test_a_script_maps_the_same_way(self, tmp_path: Path) -> None:
        _touch(tmp_path, "scripts/qa/llm_qa.py", "tests/unit/qa/test_llm_qa_run_lock.py")
        index = changed_tests.build_test_index(tmp_path)
        selected, _ = changed_tests.select_tests(["scripts/qa/llm_qa.py"], index, tmp_path)
        assert selected == ["tests/unit/qa/test_llm_qa_run_lock.py"]

    def test_a_module_with_no_named_test_is_listed_as_unmapped(self, tmp_path: Path) -> None:
        _touch(tmp_path, "src/pkg/orphan.py")
        index = changed_tests.build_test_index(tmp_path)
        selected, unmapped = changed_tests.select_tests(["src/pkg/orphan.py"], index, tmp_path)
        assert selected == []
        assert unmapped == ["src/pkg/orphan.py"]

    def test_a_package_init_is_unmapped_rather_than_matched_by_name(self, tmp_path: Path) -> None:
        _touch(tmp_path, "src/pkg/__init__.py", "tests/unit/test___init__.py")
        index = changed_tests.build_test_index(tmp_path)
        _, unmapped = changed_tests.select_tests(["src/pkg/__init__.py"], index, tmp_path)
        assert unmapped == ["src/pkg/__init__.py"]

    def test_a_non_test_file_under_tests_is_unmapped(self, tmp_path: Path) -> None:
        """A conftest or helper change can affect any test, so it is not silently skipped."""
        _touch(tmp_path, "tests/conftest.py")
        index = changed_tests.build_test_index(tmp_path)
        selected, unmapped = changed_tests.select_tests(["tests/conftest.py"], index, tmp_path)
        assert selected == []
        assert unmapped == ["tests/conftest.py"]

    def test_non_python_and_deleted_files_are_not_candidates(self, tmp_path: Path) -> None:
        _touch(tmp_path, "CLAUDE/QA.md")
        index = changed_tests.build_test_index(tmp_path)
        selected, unmapped = changed_tests.select_tests(
            ["CLAUDE/QA.md", "src/pkg/deleted.py"], index, tmp_path
        )
        assert (selected, unmapped) == ([], [])

    def test_project_handler_files_are_left_to_the_project_handler_tool(
        self, tmp_path: Path
    ) -> None:
        _touch(tmp_path, ".claude/project-handlers/pre_tool_use/enforce_llm_qa.py")
        index = changed_tests.build_test_index(tmp_path)
        selected, unmapped = changed_tests.select_tests(
            [".claude/project-handlers/pre_tool_use/enforce_llm_qa.py"], index, tmp_path
        )
        assert (selected, unmapped) == ([], [])


class TestTheReport:
    def test_a_green_run_passes_and_counts_its_inputs(self) -> None:
        report = changed_tests.build_report(
            base=_MERGE_BASE,
            changed=["src/pkg/a.py", "README.md"],
            selected=["tests/unit/test_a.py"],
            unmapped=[],
            exit_code=0,
            output="3 passed in 0.10s\n",
        )
        summary = report["summary"]
        assert summary["passed_all"] is True
        assert summary["passed"] == 3
        assert summary["files_considered"] == 2
        assert summary["test_files_selected"] == 1

    def test_a_failure_is_named(self) -> None:
        output = (
            "=========================== short test summary info ============================\n"
            "FAILED tests/unit/test_a.py::test_x - AssertionError\n"
            "1 failed, 2 passed in 0.10s\n"
        )
        report = changed_tests.build_report(
            base=_MERGE_BASE,
            changed=["src/pkg/a.py"],
            selected=["tests/unit/test_a.py"],
            unmapped=[],
            exit_code=1,
            output=output,
        )
        assert report["summary"]["passed_all"] is False
        assert report["tests"] == [{"name": "tests/unit/test_a.py::test_x", "outcome": "failed"}]

    def test_selected_tests_that_collected_nothing_is_a_failure(self) -> None:
        """Zero tests from a non-empty selection has not passed; it has not run."""
        report = changed_tests.build_report(
            base=_MERGE_BASE,
            changed=["src/pkg/a.py"],
            selected=["tests/unit/test_a.py"],
            unmapped=[],
            exit_code=5,
            output="no tests ran in 0.01s\n",
        )
        assert report["summary"]["passed_all"] is False

    def test_nothing_selected_passes_but_says_nothing_ran(self) -> None:
        report = changed_tests.build_report(
            base=_MERGE_BASE,
            changed=["CLAUDE/QA.md"],
            selected=[],
            unmapped=["src/pkg/orphan.py"],
            exit_code=None,
            output="",
        )
        assert report["summary"]["passed_all"] is True
        assert report["summary"]["test_files_selected"] == 0
        assert report["unmapped"] == ["src/pkg/orphan.py"]

    def test_a_failure_report_never_passes(self) -> None:
        report = changed_tests.failure_report("no merge base")
        assert report["summary"]["passed_all"] is False
        assert report["summary"]["error"] == "no merge base"


class TestMain:
    def _run(
        self,
        tmp_path: Path,
        *,
        git: Any,
        pytest_result: tuple[int, str] = (0, "1 passed in 0.01s\n"),
    ) -> tuple[int, dict[str, Any], list[list[str]]]:
        calls: list[list[str]] = []

        def run_pytest(paths: list[str], root: Path) -> tuple[int, str]:
            calls.append(paths)
            return pytest_result

        code = changed_tests.main(
            ["--json", "--root", str(tmp_path)], run_git=git, run_pytest=run_pytest
        )
        report = json.loads((tmp_path / "untracked" / "qa" / "changed_tests.json").read_text())
        return code, report, calls

    def test_a_green_targeted_run(self, tmp_path: Path) -> None:
        _touch(tmp_path, "src/pkg/a.py", "tests/unit/test_a.py")
        code, report, calls = self._run(tmp_path, git=_git_answering(diff="src/pkg/a.py\n"))
        assert code == changed_tests.EXIT_SUCCESS
        assert calls == [["tests/unit/test_a.py"]]
        assert report["summary"]["passed_all"] is True

    def test_a_red_targeted_run(self, tmp_path: Path) -> None:
        _touch(tmp_path, "src/pkg/a.py", "tests/unit/test_a.py")
        code, _, _ = self._run(
            tmp_path,
            git=_git_answering(diff="src/pkg/a.py\n"),
            pytest_result=(1, "1 failed in 0.01s\n"),
        )
        assert code == changed_tests.EXIT_ISSUES

    def test_nothing_selected_runs_no_pytest(self, tmp_path: Path) -> None:
        _touch(tmp_path, "CLAUDE/QA.md")
        code, _, calls = self._run(tmp_path, git=_git_answering(diff="CLAUDE/QA.md\n"))
        assert code == changed_tests.EXIT_SUCCESS
        assert calls == []

    def test_an_unresolvable_base_is_an_operational_failure(self, tmp_path: Path) -> None:
        code, report, calls = self._run(tmp_path, git=_git_answering(merge_base_code=128))
        assert code == changed_tests.EXIT_OPERATIONAL
        assert report["summary"]["passed_all"] is False
        assert calls == []


@pytest.mark.parametrize("flag", ["--base", "--root"])
def test_the_cli_documents_its_options(flag: str) -> None:
    assert flag in (changed_tests.__doc__ or "")
