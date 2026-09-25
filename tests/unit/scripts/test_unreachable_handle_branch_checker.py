"""The `unreachable-handle-branch` Detector — Plan 00422 N29 (Defence Before Fix, RED first).

The class: **work placed in a handler's ``handle()`` under
``if not self.matches(...)``**. The chain calls ``handle()`` only after
``matches()`` returned True, so that branch runs only when a test calls
``handle()`` directly. A bare ``return`` there is a harmless defensive guard;
anything else is behaviour the product never executes.

The originating instance: ``write_clobber_guard`` recorded a successful
``Write`` in that branch, so a file a session created with ``Write`` was never
recorded, and rewriting it was denied as a clobber. Its unit test called
``handle()`` directly and passed.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CHECKER = _REPO_ROOT / "scripts" / "qa" / "check_unreachable_handle_branch.py"


@pytest.fixture(scope="module")
def checker() -> ModuleType:
    """The Detector, imported from its script path."""
    spec = importlib.util.spec_from_file_location("check_unreachable_handle_branch", _CHECKER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _scan(checker: ModuleType, tmp_path: Path, source: str) -> list[int]:
    """Scan ``source`` as a handler module; return the reported line numbers."""
    module_dir = tmp_path / "handlers" / "pre_tool_use"
    module_dir.mkdir(parents=True)
    (module_dir / "sample.py").write_text(source, encoding="utf-8")
    return [violation.line for violation in checker.scan_tree(tmp_path)]


_RECORDS_IN_THE_BRANCH = """\
class Sample:
    def handle(self, hook_input):
        if not self.matches(hook_input):
            self._record(hook_input)
            return ALLOW
        return DENY
"""

_BARE_RETURN_ONLY = """\
class Sample:
    def handle(self, hook_input):
        if not self.matches(hook_input):
            return GatingResult(decision=Decision.ALLOW)
        return DENY
"""

_NESTED_WORK = """\
class Sample:
    def handle(self, hook_input):
        if not self.matches(hook_input):
            if hook_input.get("tool_name") == "Write":
                self._record(hook_input)
            return ALLOW
        return DENY
"""

_OUTSIDE_HANDLE = """\
class Sample:
    def advise(self, hook_input):
        if not self.matches(hook_input):
            self._record(hook_input)
        return ALLOW
"""


class TestTheRuleFires:
    def test_on_work_before_the_return(self, checker: ModuleType, tmp_path: Path) -> None:
        assert _scan(checker, tmp_path, _RECORDS_IN_THE_BRANCH) == [3]

    def test_on_nested_work(self, checker: ModuleType, tmp_path: Path) -> None:
        assert _scan(checker, tmp_path, _NESTED_WORK) == [3]


class TestTheRuleStaysQuiet:
    def test_on_a_bare_defensive_return(self, checker: ModuleType, tmp_path: Path) -> None:
        assert _scan(checker, tmp_path, _BARE_RETURN_ONLY) == []

    def test_outside_handle(self, checker: ModuleType, tmp_path: Path) -> None:
        """Only ``handle()`` is gated by ``matches()`` in the chain."""
        assert _scan(checker, tmp_path, _OUTSIDE_HANDLE) == []


class TestTheRepository:
    def test_the_source_tree_is_clean(self, checker: ModuleType) -> None:
        """Every instance in the shipped handlers is fixed."""
        scan_root = _REPO_ROOT / "src" / "claude_code_hooks_daemon"
        assert [f"{v.file}:{v.line}" for v in checker.scan_tree(scan_root)] == []
