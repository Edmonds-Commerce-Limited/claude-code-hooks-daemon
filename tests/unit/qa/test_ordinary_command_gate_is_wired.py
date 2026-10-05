"""``llm_qa.py changed`` runs the ordinary-command gate when a guard file changes.

Plan 00483 R2. The gate (``tests/integration/test_ordinary_command_regression_gate.py``)
names no guard module, so the name-and-import mapping of ``run_changed_tests.py``
cannot reach it from a change to ``secret_file_guard.py`` or to the shell reader.
The declared rules in ``scripts/qa/changed_tests_map.yaml`` must, or the gate
exists and never runs where it matters.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
GATE = "tests/integration/test_ordinary_command_regression_gate.py"
MAP_FILE = PROJECT_ROOT / "scripts" / "qa" / "changed_tests_map.yaml"
_PACKAGE = "src/claude_code_hooks_daemon"

#: Files whose change can flip an ordinary command to a deny.
GUARD_FILES = (
    f"{_PACKAGE}/handlers/pre_tool_use/secret_file_guard.py",
    f"{_PACKAGE}/handlers/pre_tool_use/quarantine_artefact_read_guard.py",
    f"{_PACKAGE}/handlers/pre_tool_use/flaggable_content_channel_guard.py",
    f"{_PACKAGE}/handlers/pre_tool_use/project_containment.py",
    f"{_PACKAGE}/handlers/pre_tool_use/bash_safe_mode.py",
    f"{_PACKAGE}/utils/secret_file_matching.py",
    f"{_PACKAGE}/utils/shell_expansion.py",
    f"{_PACKAGE}/utils/shell_segmentation.py",
    f"{_PACKAGE}/utils/recursive_search.py",
    f"{_PACKAGE}/utils/protected_file_index.py",
    f"{_PACKAGE}/utils/command_position.py",
    "tests/fixtures/ordinary_command_corpus.yaml",
)


def _load_changed_tests() -> Any:
    module_path = PROJECT_ROOT / "scripts" / "qa" / "run_changed_tests.py"
    spec = importlib.util.spec_from_file_location("run_changed_tests_for_gate_wiring", module_path)
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


class TestGateRunsWhenGuardFilesChange:
    """A change to any guard file selects the gate."""

    @pytest.mark.parametrize("relative", GUARD_FILES)
    def test_guard_file_selects_the_gate(self, relative: str) -> None:
        assert GATE in _tests_selected_for(relative)

    def test_the_gate_exists(self) -> None:
        assert (PROJECT_ROOT / GATE).is_file()

    def test_an_unrelated_util_does_not_select_the_gate(self) -> None:
        assert GATE not in _tests_selected_for(f"{_PACKAGE}/utils/git_repo.py")
