"""Both lint gates run a declared sub-project's file with the SAME linter binary.

`lint_on_edit` (write time) searched the file's declared sub-project tool
directories (``node_modules/.bin``, ``vendor/bin``) before the interpreter's
``bin`` and ``PATH``; `staged_lint_gate` (commit time) skipped the sub-project
directories. With a global copy of the tool on ``PATH`` and a pinned copy in
the sub-project, the two gates ran different binaries on the same file and
could disagree about it. The subprocess is faked: only the executable each gate
would launch is under test.
"""

from __future__ import annotations

import stat
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from claude_code_hooks_daemon.core.data_layer import reset_data_layer
from claude_code_hooks_daemon.core.workspace import DeclaredProject, ProjectRegistry
from claude_code_hooks_daemon.handlers.post_tool_use.lint_on_edit import LintOnEditHandler
from claude_code_hooks_daemon.handlers.pre_tool_use.staged_lint_gate import StagedLintGateHandler
from claude_code_hooks_daemon.strategies.lint.python_strategy import PythonLintStrategy

_TOOL = "n538-fake-linter"
_LINT_ON_EDIT = "claude_code_hooks_daemon.handlers.post_tool_use.lint_on_edit"
_GATE = "claude_code_hooks_daemon.handlers.pre_tool_use.staged_lint_gate"
_ROOT_FN = "claude_code_hooks_daemon.utils.path_exclusion.resolve_project_root"


class _FakeToolStrategy(PythonLintStrategy):
    """A Python strategy whose cheap command names a bare tool, as most strategies do."""

    @property
    def default_lint_command(self) -> str:
        return f"{_TOOL} {{file}}"


@pytest.fixture(autouse=True)
def _reset_data_layer() -> Iterator[None]:
    reset_data_layer()
    yield
    reset_data_layer()


def _make_tool(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    tool = directory / _TOOL
    tool.write_text("#!/bin/sh\nexit 0\n")
    tool.chmod(tool.stat().st_mode | stat.S_IXUSR)
    return tool


@pytest.fixture()
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A repo whose ``frontend/`` sub-project pins its own copy of the tool.

    A second, global copy sits on ``PATH`` - the copy a gate that skips the
    sub-project's tool directory would pick instead.
    """
    root = (tmp_path / "repo").resolve()
    (root / "frontend").mkdir(parents=True)
    (root / "frontend" / "package.json").write_text("{}\n")
    (root / "frontend" / "app.py").write_text("x = 1\n")
    _make_tool(root / "frontend" / "node_modules" / ".bin")
    global_bin = (tmp_path / "global-bin").resolve()
    _make_tool(global_bin)
    monkeypatch.setenv("PATH", str(global_bin))
    return root


def _registry(repo: Path) -> ProjectRegistry:
    return ProjectRegistry(
        project_root=repo,
        projects=(DeclaredProject(name="frontend", root=repo / "frontend"),),
    )


def _passed() -> MagicMock:
    result = MagicMock()
    result.returncode = 0
    result.stdout = ""
    result.stderr = ""
    return result


def _edit_executable(repo: Path) -> str:
    handler = LintOnEditHandler()
    handler._project_registry = _registry(repo)
    strategy = _FakeToolStrategy()
    with (
        patch(_ROOT_FN, return_value=str(repo)),
        patch(f"{_LINT_ON_EDIT}.resolve_project_root", return_value=str(repo)),
        patch(f"{_LINT_ON_EDIT}.subprocess.run", return_value=_passed()) as run,
    ):
        handler._run_lint_command(
            {},
            strategy.default_lint_command,
            str(repo / "frontend" / "app.py"),
            strategy.language_name,
            strategy,
        )
    return str(run.call_args.args[0][0])


def _gate_executable(repo: Path) -> str:
    handler = StagedLintGateHandler()
    handler._project_registry = _registry(repo)
    with (
        patch(_ROOT_FN, return_value=str(repo)),
        patch(f"{_GATE}.resolve_project_root", return_value=str(repo)),
        patch(f"{_GATE}.subprocess.run", return_value=_passed()) as run,
    ):
        handler._syntax_check(str(repo / "frontend" / "app.py"), _FakeToolStrategy())
    return str(run.call_args.args[0][0])


class TestSubProjectLinterExecutable:
    def test_both_gates_launch_the_same_linter_binary_for_a_subproject_file(
        self, repo: Path
    ) -> None:
        assert _edit_executable(repo) == _gate_executable(repo)

    def test_that_binary_is_the_subprojects_own_pinned_copy(self, repo: Path) -> None:
        pinned = str(repo / "frontend" / "node_modules" / ".bin" / _TOOL)
        assert _gate_executable(repo) == pinned
        assert _edit_executable(repo) == pinned
