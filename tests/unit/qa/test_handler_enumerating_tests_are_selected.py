"""N382: a change under ``handlers/`` always selects the tests that enumerate every handler.

Those tests find their handlers with ``pkgutil.walk_packages`` or
``HandlerRegistry.discover()``, never by importing the changed module, so the
import-based selector cannot reach them. ``changed_tests_map.yaml`` therefore
pins them in one declared rule. This file keeps that pinned list honest in
both directions: every listed file really enumerates handlers, and no
enumerating integration test is missing from the list.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
RULES_PATH = PROJECT_ROOT / "scripts" / "qa" / "changed_tests_map.yaml"
HANDLERS_GLOB = "src/claude_code_hooks_daemon/handlers/*"
#: A test that walks the handlers package module by module.
WALKS_HANDLERS = re.compile(
    r"(?:walk_packages\(\s*handlers\w*|iter_modules\(\s*event\w*)\.__path__"
)
#: A test that asks the registry for every built-in handler. Only counted as
#: whole-repo under tests/integration: a unit test's ``discover()`` exercises
#: the registry itself, which its own mirror tests already select.
DISCOVERS_HANDLERS = re.compile(
    r"HandlerRegistry\b[\s\S]*\bregistry\.discover\(\)|\biter_builtin_handler_classes\(\)"
)


def _load_runner() -> Any:
    path = PROJECT_ROOT / "scripts" / "qa" / "run_changed_tests.py"
    spec = importlib.util.spec_from_file_location("run_changed_tests_for_n382", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


runner = _load_runner()


def _pinned_tests() -> tuple[str, ...]:
    rules, problems = runner.load_declared_rules(RULES_PATH)
    assert problems == [], problems
    pinned = [rule for rule in rules if rule.glob == HANDLERS_GLOB]
    assert len(pinned) == 1, f"expected exactly one rule for {HANDLERS_GLOB}"
    return tuple(pinned[0].tests)


class TestAHandlerChangeSelectsTheEnumeratingTests:
    @pytest.mark.parametrize(
        "changed",
        [
            "src/claude_code_hooks_daemon/handlers/pre_tool_use/some_handler.py",
            "src/claude_code_hooks_daemon/handlers/stop/nested/other.py",
            "src/claude_code_hooks_daemon/handlers/base.py",
        ],
    )
    def test_every_pinned_test_is_selected(self, tmp_path: Path, changed: str) -> None:
        pinned = _pinned_tests()
        for relative in (changed, *pinned):
            target = tmp_path / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("x = 1\n", encoding="utf-8")
        tree = sorted(
            p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file()
        )
        rules, _ = runner.load_declared_rules(RULES_PATH)
        selection = runner.select_tests(
            [changed], runner.build_corpus(tmp_path, tree), tmp_path, rules
        )
        assert set(pinned) <= set(selection.selected)


#: Adding a handler also edits these: its id, priority and audit-reason
#: constants. Each is read by the registry-wide tests, so a change to one must
#: select them even though no handler file changed (N463).
HANDLER_CONSTANTS = (
    "src/claude_code_hooks_daemon/constants/handlers.py",
    "src/claude_code_hooks_daemon/constants/priority.py",
    "src/claude_code_hooks_daemon/constants/rule_ids.py",
)
#: Registry-wide unit tests that no regex below can tell from a test of the
#: registry itself. N463: CI caught the one the targeted run missed.
KNOWN_UNIT_INVARIANTS = (
    "tests/unit/handlers/test_pretooluse_fail_closed_tagging.py",
    "tests/unit/handlers/test_config_key_consistency.py",
)


def _select(tmp_path: Path, changed: str, wanted: tuple[str, ...]) -> set[str]:
    for relative in (changed, *wanted):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("x = 1\n", encoding="utf-8")
    tree = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file())
    rules, _ = runner.load_declared_rules(RULES_PATH)
    selection = runner.select_tests([changed], runner.build_corpus(tmp_path, tree), tmp_path, rules)
    return set(selection.selected)


class TestAddingAHandlerSelectsTheRegistryWideInvariants:
    @pytest.mark.parametrize("changed", HANDLER_CONSTANTS)
    def test_a_handler_constants_change_selects_the_pinned_tests(
        self, tmp_path: Path, changed: str
    ) -> None:
        pinned = _pinned_tests()
        assert set(pinned) <= _select(tmp_path, changed, pinned)

    def test_a_new_stop_handler_selects_the_fail_closed_tagging_test(self, tmp_path: Path) -> None:
        changed = "src/claude_code_hooks_daemon/handlers/stop/brand_new_gate.py"
        selected = _select(tmp_path, changed, KNOWN_UNIT_INVARIANTS)
        assert set(KNOWN_UNIT_INVARIANTS) <= selected

    def test_an_unrelated_constants_file_does_not_select_them(self, tmp_path: Path) -> None:
        changed = "src/claude_code_hooks_daemon/constants/timeout.py"
        selected = _select(tmp_path, changed, KNOWN_UNIT_INVARIANTS)
        assert not set(KNOWN_UNIT_INVARIANTS) & selected

    def test_the_known_invariants_are_pinned_and_exist(self) -> None:
        assert set(KNOWN_UNIT_INVARIANTS) <= set(_pinned_tests())
        for relative in KNOWN_UNIT_INVARIANTS:
            assert (PROJECT_ROOT / relative).is_file()


class TestThePinnedListCannotRotSilently:
    def test_the_list_is_not_empty(self) -> None:
        assert len(_pinned_tests()) >= 3

    def test_every_listed_file_exists_and_enumerates_handlers(self) -> None:
        for relative in _pinned_tests():
            path = PROJECT_ROOT / relative
            assert path.is_file(), f"{relative} is pinned but does not exist"
            text = path.read_text(encoding="utf-8")
            assert WALKS_HANDLERS.search(text) or DISCOVERS_HANDLERS.search(
                text
            ), f"{relative} is pinned but no longer walks or discovers the handlers"

    def test_no_enumerating_test_is_missing_from_the_list(self) -> None:
        pinned = set(_pinned_tests())
        enumerating = set()
        for path in (PROJECT_ROOT / "tests").rglob("test_*.py"):
            relative = path.relative_to(PROJECT_ROOT)
            if "fixtures" in relative.parts:
                continue
            text = path.read_text(encoding="utf-8")
            whole_repo = WALKS_HANDLERS.search(text) or (
                relative.parts[:2] == ("tests", "integration") and DISCOVERS_HANDLERS.search(text)
            )
            if whole_repo:
                enumerating.add(relative.as_posix())
        assert enumerating <= pinned, sorted(enumerating - pinned)
