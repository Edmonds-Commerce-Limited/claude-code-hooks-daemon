"""staged_lint_gate vets Go from the file's module root (GitHub #118)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from tests.support.git_fixtures import git_setup_timeout

from claude_code_hooks_daemon.core.data_layer import reset_data_layer
from claude_code_hooks_daemon.handlers.pre_tool_use.staged_lint_gate import StagedLintGateHandler

pytestmark = pytest.mark.skipif(shutil.which("go") is None, reason="go toolchain not installed")

_GO_MOD = "module m\n\ngo 1.19\n"
_UTIL = "package util\n\nfunc Double(n int) int { return n * 2 }\n"
_APP_OK = 'package app\n\nimport "m/util"\n\nfunc Run() int { return util.Double(2) }\n'
_APP_BAD = (
    'package app\n\nimport (\n\t"fmt"\n\n\t"m/util"\n)\n\n'
    'func Run() int {\n\tfmt.Printf("%d\\n", "str")\n\treturn util.Double(2)\n}\n'
)


@pytest.fixture(autouse=True)
def _reset_data_layer() -> Any:
    reset_data_layer()
    yield
    reset_data_layer()


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        check=True,
        timeout=git_setup_timeout(),
    )


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """A repository with NO root go.mod and a nested module under ``sub/``."""
    root = tmp_path / "repo"
    root.mkdir()
    (root / "README.md").write_text("# repo\n")
    _git(root, "init")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "T")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "initial")
    return root


def _stage_module(repo: Path, app_source: str) -> None:
    for relpath, content in {
        "sub/go.mod": _GO_MOD,
        "sub/util/util.go": _UTIL,
        "sub/app/app.go": app_source,
    }.items():
        path = repo / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        _git(repo, "add", relpath)


def _commit(repo: Path) -> Any:
    handler = StagedLintGateHandler()
    handler._mode = "block"
    target = (
        "claude_code_hooks_daemon.handlers.pre_tool_use.staged_lint_gate."
        "ProjectContext.project_root"
    )
    hook_input = {"tool_name": "Bash", "tool_input": {"command": 'git commit -m "x"'}}
    with patch(target, return_value=repo):
        return handler.handle(hook_input)


class TestNestedGoModule:
    def test_a_correct_package_in_a_nested_module_is_allowed(self, repo: Path) -> None:
        _stage_module(repo, _APP_OK)

        result = _commit(repo)

        assert result.decision == "allow", result.reason

    def test_a_real_vet_finding_is_denied_and_names_the_file(self, repo: Path) -> None:
        _stage_module(repo, _APP_BAD)

        result = _commit(repo)

        assert result.decision == "deny"
        assert "app.go" in (result.reason or "")
        assert "Printf" in (result.reason or "")
        assert "# m/app" not in (result.reason or "")


class TestHeadline:
    def test_skips_the_package_banner(self) -> None:
        from claude_code_hooks_daemon.handlers.pre_tool_use.staged_lint_gate import _headline

        assert _headline("# m/app\napp/app.go:9:2: bad\n") == "app/app.go:9:2: bad"

    def test_keeps_the_first_line_when_only_banners_exist(self) -> None:
        from claude_code_hooks_daemon.handlers.pre_tool_use.staged_lint_gate import _headline

        assert _headline("# m/app\n# more") == "# m/app"
