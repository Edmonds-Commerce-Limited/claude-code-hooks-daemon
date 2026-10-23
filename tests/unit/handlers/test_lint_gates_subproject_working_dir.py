"""Both lint gates run a declared sub-project's file from the SAME directory.

`lint_on_edit` (write time) ran the linter from the file's declared
sub-project root while `staged_lint_gate` (commit time) ran it from the
repository root, so a file whose linter config lives in the sub-project could
pass at edit time and be denied at commit, or the other way round. The
subprocess is faked: only the directory it would run from is under test.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from claude_code_hooks_daemon.core.data_layer import reset_data_layer
from claude_code_hooks_daemon.core.workspace import DeclaredProject, ProjectRegistry
from claude_code_hooks_daemon.handlers.post_tool_use.lint_on_edit import LintOnEditHandler
from claude_code_hooks_daemon.handlers.pre_tool_use.staged_lint_gate import StagedLintGateHandler
from claude_code_hooks_daemon.strategies.lint.python_strategy import PythonLintStrategy

_FAKE_TOOL = "/fake/bin/ruff"
_LINT_ON_EDIT = "claude_code_hooks_daemon.handlers.post_tool_use.lint_on_edit"
_GATE = "claude_code_hooks_daemon.handlers.pre_tool_use.staged_lint_gate"
_ROOT_FN = "claude_code_hooks_daemon.utils.path_exclusion.resolve_project_root"


@pytest.fixture(autouse=True)
def _reset_data_layer() -> Iterator[None]:
    reset_data_layer()
    yield
    reset_data_layer()


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """A repository declaring ``frontend/`` as a sub-project holding one file."""
    root = tmp_path.resolve()
    (root / "frontend").mkdir()
    (root / "frontend" / "app.py").write_text("x = 1\n")
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


def _edit_cwd(repo: Path) -> Any:
    handler = LintOnEditHandler()
    handler._project_registry = _registry(repo)
    strategy = PythonLintStrategy()
    with (
        patch(_ROOT_FN, return_value=str(repo)),
        patch(f"{_LINT_ON_EDIT}.resolve_project_root", return_value=str(repo)),
        patch.object(handler, "_resolve_executable", return_value=_FAKE_TOOL),
        patch(f"{_LINT_ON_EDIT}.subprocess.run", return_value=_passed()) as run,
    ):
        handler._run_lint_command(
            {},
            strategy.default_lint_command,
            str(repo / "frontend" / "app.py"),
            strategy.language_name,
            strategy,
        )
    return run.call_args.kwargs["cwd"]


def _gate_cwd(repo: Path) -> Any:
    handler = StagedLintGateHandler()
    handler._project_registry = _registry(repo)
    strategy = PythonLintStrategy()
    with (
        patch(_ROOT_FN, return_value=str(repo)),
        patch(f"{_GATE}.resolve_project_root", return_value=str(repo)),
        patch.object(handler, "_resolve_executable", return_value=_FAKE_TOOL),
        patch(f"{_GATE}.subprocess.run", return_value=_passed()) as run,
    ):
        handler._syntax_check(str(repo / "frontend" / "app.py"), strategy)
    return run.call_args.kwargs["cwd"]


class TestSubProjectWorkingDirectory:
    def test_both_gates_run_a_subproject_file_from_the_same_directory(self, repo: Path) -> None:
        assert _edit_cwd(repo) == _gate_cwd(repo)

    def test_that_directory_is_the_declared_subproject_root(self, repo: Path) -> None:
        assert _gate_cwd(repo) == str(repo / "frontend")
        assert _edit_cwd(repo) == str(repo / "frontend")
