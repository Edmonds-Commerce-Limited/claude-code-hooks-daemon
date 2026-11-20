"""lint_on_edit on a GitHub workflow file, driven by a stub `actions-qa` (Plan 00621).

The real linter is optional and young, so it must never block an edit for any
reason other than a finding about the file: exit 1 denies, every other
non-zero exit allows with a "NOT checked" advisory, a missing tool allows and
prints NOTHING (the session-start advisory is the one place that suggests it),
and a timeout allows. The stub is an executable named `actions-qa` placed first
on PATH; the "missing" cases empty PATH so a real install on the host cannot
answer instead.
"""

from __future__ import annotations

import shutil
import stat
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.post_tool_use.lint_on_edit import LintOnEditHandler

_SUBPROCESS_RUN = "claude_code_hooks_daemon.handlers.post_tool_use.lint_on_edit.subprocess.run"
_SLEEP = shutil.which("sleep") or "/bin/sleep"
_WORKFLOW = "on: push\njobs:\n  build:\n    runs-on: ubuntu-latest\n    steps: []\n"


def _workflow(root: Path) -> Path:
    path = root / "repo" / ".github" / "workflows" / "ci.yml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_WORKFLOW, encoding="utf-8")
    return path


def _stub_linter(bin_dir: Path, *, exit_code: int, output: str = "", sleep: float = 0) -> Path:
    """An executable `actions-qa` that prints ``output`` and exits ``exit_code``."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    stub = bin_dir / "actions-qa"
    body = "#!/bin/sh\n"
    if sleep:
        # Absolute (PATH holds only the stub dir) and `exec`, so the timeout's
        # kill reaches the sleeper and no orphan holds the output pipe open.
        body += f"exec {_SLEEP} {sleep}\n"
    body += f"printf '%s\\n' '{output}'\n" if output else ""
    body += f"exit {exit_code}\n"
    stub.write_text(body, encoding="utf-8")
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
    return stub


def _hook_input(path: Path) -> dict[str, Any]:
    return {"tool_name": "Write", "tool_input": {"file_path": str(path)}}


@pytest.fixture()
def handler() -> LintOnEditHandler:
    return LintOnEditHandler()


@pytest.fixture()
def stub_bin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A bin directory that is the ONLY entry on PATH."""
    bin_dir = tmp_path / "stub-bin"
    bin_dir.mkdir()
    monkeypatch.setenv("PATH", str(bin_dir))
    return bin_dir


class TestWorkflowIsLinted:
    def test_a_workflow_write_matches(self, handler: LintOnEditHandler, tmp_path: Path) -> None:
        assert handler.matches(_hook_input(_workflow(tmp_path))) is True

    def test_exit_0_is_silent(
        self, handler: LintOnEditHandler, tmp_path: Path, stub_bin: Path
    ) -> None:
        _stub_linter(stub_bin, exit_code=0, output="all good")
        result = handler.handle(_hook_input(_workflow(tmp_path)))
        assert result.decision == Decision.ALLOW
        assert not result.context

    def test_exit_1_denies_with_the_linters_output(
        self, handler: LintOnEditHandler, tmp_path: Path, stub_bin: Path
    ) -> None:
        _stub_linter(stub_bin, exit_code=1, output="actionsqaci.pushConcurrency: no concurrency")
        result = handler.handle(_hook_input(_workflow(tmp_path)))
        assert result.decision == Decision.DENY
        assert "actionsqaci.pushConcurrency: no concurrency" in result.reason
        assert "GitHub Workflow lint FAILED for ci.yml" in result.reason

    @pytest.mark.parametrize("code", [2, 3, 4, 127])
    def test_any_other_non_zero_exit_allows_with_a_not_checked_advisory(
        self, handler: LintOnEditHandler, tmp_path: Path, stub_bin: Path, code: int
    ) -> None:
        _stub_linter(stub_bin, exit_code=code, output=f"fault line {code}\nsecond line")
        result = handler.handle(_hook_input(_workflow(tmp_path)))
        assert result.decision == Decision.ALLOW
        joined = " ".join(result.context)
        assert "NOT checked" in joined
        assert f"fault line {code}" in joined
        assert "second line" not in joined, "only the first line of a fault is quoted"
        assert f"exit {code}" in joined

    def test_a_fault_with_no_output_still_explains(
        self, handler: LintOnEditHandler, tmp_path: Path, stub_bin: Path
    ) -> None:
        _stub_linter(stub_bin, exit_code=2)
        result = handler.handle(_hook_input(_workflow(tmp_path)))
        assert result.decision == Decision.ALLOW
        assert "NOT checked" in " ".join(result.context)

    def test_timeout_allows_with_the_timeout_advisory(
        self, handler: LintOnEditHandler, tmp_path: Path, stub_bin: Path
    ) -> None:
        _stub_linter(stub_bin, exit_code=1, output="never reached", sleep=5)
        handler._timeouts = {"GitHub Workflow": 0.2}
        result = handler.handle(_hook_input(_workflow(tmp_path)))
        assert result.decision == Decision.ALLOW
        joined = " ".join(result.context)
        assert "timed out" in joined
        assert "timeouts.GitHub Workflow" in joined


class TestMissingOptionalToolIsSilent:
    def test_an_unresolvable_tool_allows_and_prints_nothing(
        self, handler: LintOnEditHandler, tmp_path: Path, stub_bin: Path
    ) -> None:
        """stub_bin is the only PATH entry and holds no actions-qa."""
        result = handler.handle(_hook_input(_workflow(tmp_path)))
        assert result.decision == Decision.ALLOW
        assert not result.context

    def test_a_tool_that_vanishes_at_launch_allows_and_prints_nothing(
        self, handler: LintOnEditHandler, tmp_path: Path, stub_bin: Path
    ) -> None:
        """Resolved, then FileNotFoundError at exec: the second not-found route."""
        _stub_linter(stub_bin, exit_code=0)
        with patch(_SUBPROCESS_RUN, side_effect=FileNotFoundError("actions-qa")):
            result = handler.handle(_hook_input(_workflow(tmp_path)))
        assert result.decision == Decision.ALLOW
        assert not result.context

    def test_an_existing_languages_missing_tool_still_prints_its_line(
        self, handler: LintOnEditHandler
    ) -> None:
        """The silence is the optional tool's alone; no other language changes."""
        result = handler._run_lint_command(
            {}, "definitely-not-a-real-linter-xyzzy check {file}", "/tmp/example.py", "Python"
        )
        assert result is not None
        assert result.decision == Decision.ALLOW
        assert "lint tool not found" in " ".join(result.context)

    def test_an_existing_languages_launch_failure_still_prints_its_line(
        self, handler: LintOnEditHandler, tmp_path: Path
    ) -> None:
        target = tmp_path / "x.py"
        target.write_text("x = 1\n", encoding="utf-8")
        with patch(_SUBPROCESS_RUN, side_effect=FileNotFoundError("python")):
            result = handler._run_lint_command(
                {}, "python3 -m py_compile {file}", str(target), "Python"
            )
        assert result is not None
        assert "lint tool not found" in " ".join(result.context)


class TestExistingLanguagesUnchanged:
    def test_a_non_zero_exit_other_than_1_still_denies_for_a_strategy_without_codes(
        self, handler: LintOnEditHandler, tmp_path: Path
    ) -> None:
        """No existing strategy declares findings codes, so exit 2 still denies."""
        target = tmp_path / "x.py"
        target.write_text("x = 1\n", encoding="utf-8")
        completed = subprocess.CompletedProcess(args=[], returncode=2, stdout="E1 bad", stderr="")
        with patch(_SUBPROCESS_RUN, return_value=completed):
            result = handler._run_lint_command(
                {}, "python3 -m py_compile {file}", str(target), "Python"
            )
        assert result is not None
        assert result.decision == Decision.DENY


class TestAcceptanceAggregation:
    def test_the_workflow_strategy_contributes_acceptance_tests(
        self, handler: LintOnEditHandler
    ) -> None:
        titles = [test.title for test in handler.get_acceptance_tests()]
        assert any("GitHub Workflow" in title for title in titles)

    def test_each_language_contributes_once(self, handler: LintOnEditHandler) -> None:
        titles = [test.title for test in handler.get_acceptance_tests()]
        assert len(titles) == len(set(titles))
