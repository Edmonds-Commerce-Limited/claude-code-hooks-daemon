"""N357: a change to a PreToolUse handler selects the hostile-input performance test.

That test finds its handlers through the registry, so the name-and-import mapping
of ``run_changed_tests.py`` cannot reach it from a new handler file. The declared
rules in ``scripts/qa/changed_tests_map.yaml`` must, or a guard that turns a
linear shape quadratic passes ``llm_qa.py changed``.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PERFORMANCE_TEST = "tests/unit/handlers/test_safety_handlers_hostile_input_performance.py"
MAP_FILE = PROJECT_ROOT / "scripts" / "qa" / "changed_tests_map.yaml"
_PACKAGE = "src/claude_code_hooks_daemon"


def _load_changed_tests() -> Any:
    module_path = PROJECT_ROOT / "scripts" / "qa" / "run_changed_tests.py"
    spec = importlib.util.spec_from_file_location("run_changed_tests_for_performance", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


changed_tests = _load_changed_tests()


def _tests_selected_for(relative: str) -> set[str]:
    rules, problems = changed_tests.load_declared_rules(MAP_FILE)
    assert not problems, problems
    return {test for rule in rules if rule.matches(relative) for test in rule.tests}


class TestPerformanceTestRunsWhenAGuardChanges:
    @pytest.mark.parametrize(
        "relative",
        [
            f"{_PACKAGE}/handlers/pre_tool_use/a_brand_new_guard.py",
            f"{_PACKAGE}/handlers/pre_tool_use/host_command_guard.py",
            f"{_PACKAGE}/utils/git_commit_parsing.py",
            f"{_PACKAGE}/utils/linear_shlex.py",
            f"{_PACKAGE}/utils/shell_segmentation.py",
            f"{_PACKAGE}/utils/shell_expansion.py",
            f"{_PACKAGE}/utils/simple_commands.py",
            f"{_PACKAGE}/utils/command_evasion.py",
        ],
    )
    def test_the_change_selects_it(self, relative: str) -> None:
        assert PERFORMANCE_TEST in _tests_selected_for(relative)

    def test_the_test_exists(self) -> None:
        assert (PROJECT_ROOT / PERFORMANCE_TEST).is_file()

    def test_an_unrelated_util_does_not_select_it(self) -> None:
        assert PERFORMANCE_TEST not in _tests_selected_for(f"{_PACKAGE}/utils/git_repo.py")

    def test_a_post_tool_use_handler_does_not_select_it(self) -> None:
        assert PERFORMANCE_TEST not in _tests_selected_for(
            f"{_PACKAGE}/handlers/post_tool_use/some_handler.py"
        )
