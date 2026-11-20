"""staged_lint_gate on a staged GitHub workflow, driven by a stub `actions-qa` (Plan 00621).

The commit gate shares the lint registry, so the workflow strategy reaches it
too. It must apply the same exit-code contract `lint_on_edit` does: only the
linter's findings code is a diagnosis; a fault (2, 3, 4, anything else) never
fails a commit, and neither does a missing tool.
"""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from claude_code_hooks_daemon.handlers.pre_tool_use.staged_lint_gate import (
    StagedLintGateHandler,
)
from claude_code_hooks_daemon.strategies.lint.github_workflow_strategy import (
    GitHubWorkflowLintStrategy,
)


def _workflow(root: Path) -> str:
    path = root / "repo" / ".github" / "workflows" / "ci.yml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("on: push\njobs: {}\n", encoding="utf-8")
    return str(path)


def _stub(bin_dir: Path, exit_code: int, output: str) -> None:
    stub = bin_dir / "actions-qa"
    stub.write_text(f"#!/bin/sh\nprintf '%s\\n' '{output}'\nexit {exit_code}\n", encoding="utf-8")
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR)


@pytest.fixture()
def stub_bin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    bin_dir = tmp_path / "stub-bin"
    bin_dir.mkdir()
    monkeypatch.setenv("PATH", str(bin_dir))
    return bin_dir


class TestWorkflowExitCodes:
    def test_exit_1_is_a_diagnosis(self, tmp_path: Path, stub_bin: Path) -> None:
        _stub(stub_bin, 1, "actionsqaci.scheduleBudget: too frequent")
        diagnosis = StagedLintGateHandler()._syntax_check(
            _workflow(tmp_path), GitHubWorkflowLintStrategy()
        )
        assert diagnosis is not None
        assert "scheduleBudget" in diagnosis

    @pytest.mark.parametrize("code", [2, 3, 4, 127])
    def test_a_fault_never_fails_the_commit(
        self, tmp_path: Path, stub_bin: Path, code: int
    ) -> None:
        _stub(stub_bin, code, "no verdict")
        assert (
            StagedLintGateHandler()._syntax_check(_workflow(tmp_path), GitHubWorkflowLintStrategy())
            is None
        )

    def test_a_missing_tool_never_fails_the_commit(self, tmp_path: Path, stub_bin: Path) -> None:
        assert (
            StagedLintGateHandler()._syntax_check(_workflow(tmp_path), GitHubWorkflowLintStrategy())
            is None
        )
