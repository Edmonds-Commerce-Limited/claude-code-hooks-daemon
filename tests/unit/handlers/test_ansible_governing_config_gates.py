"""Both lint gates run Ansible under the SAME governing config and directory (GitHub #128).

`lint_on_edit` (write time) and `staged_lint_gate` (commit time) resolved a
play outside its config's tree differently: one ran from the workspace root,
the other from the daemon's own cwd, and neither had the config in effect.
`ansible-playbook` is not installed in CI, so the subprocess is faked.
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.data_layer import reset_data_layer
from claude_code_hooks_daemon.core.project_layout import ProjectLayout
from claude_code_hooks_daemon.handlers.post_tool_use.lint_on_edit import LintOnEditHandler
from claude_code_hooks_daemon.handlers.pre_tool_use.staged_lint_gate import StagedLintGateHandler
from claude_code_hooks_daemon.strategies.lint.ansible_strategy import AnsibleLintStrategy

_FAKE_TOOL = "/fake/bin/ansible-playbook"
_LINT_ON_EDIT = "claude_code_hooks_daemon.handlers.post_tool_use.lint_on_edit"
_GATE = "claude_code_hooks_daemon.handlers.pre_tool_use.staged_lint_gate"
_ROOT_FN = "claude_code_hooks_daemon.utils.path_exclusion.resolve_project_root"
_CONTEXT_FAILURE = "ERROR! 'dirname' filter failed on None"


@pytest.fixture(autouse=True)
def _reset_data_layer() -> Iterator[None]:
    reset_data_layer()
    yield
    reset_data_layer()


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    """A project with its config in ``infra/`` and a play kept in ``plays/``."""
    (tmp_path / "infra").mkdir()
    (tmp_path / "infra" / "ansible.cfg").write_text("[defaults]\n")
    (tmp_path / "plays").mkdir()
    (tmp_path / "plays" / "site.yml").write_text("- hosts: all\n  tasks: []\n")
    return tmp_path


def _layout(declared: dict[str, str]) -> ProjectLayout:
    return replace(ProjectLayout.built_in_default(), ansible_configs=declared)


def _completed(returncode: int) -> MagicMock:
    result = MagicMock()
    result.returncode = returncode
    result.stdout = ""
    result.stderr = _CONTEXT_FAILURE if returncode else ""
    return result


def _run_lint_on_edit(project: Path, layout: ProjectLayout, returncode: int) -> tuple[Any, Any]:
    """Run lint_on_edit's Ansible check; return (result, the faked subprocess.run)."""
    handler = LintOnEditHandler()
    handler._project_layout = layout
    play = str(project / "plays" / "site.yml")
    strategy = AnsibleLintStrategy()
    with (
        patch(_ROOT_FN, return_value=str(project)),
        patch(f"{_LINT_ON_EDIT}.resolve_project_root", return_value=str(project)),
        patch.object(handler, "_resolve_executable", return_value=_FAKE_TOOL),
        patch(f"{_LINT_ON_EDIT}.subprocess.run", return_value=_completed(returncode)) as run,
    ):
        result = handler._run_lint_command(
            {}, strategy.default_lint_command, play, "Ansible", strategy
        )
    return result, run


def _run_gate(project: Path, layout: ProjectLayout, returncode: int) -> tuple[str | None, Any]:
    """Run the commit gate's Ansible syntax check; return (diagnosis, faked run)."""
    handler = StagedLintGateHandler()
    handler._project_layout = layout
    play = str(project / "plays" / "site.yml")
    strategy = AnsibleLintStrategy()
    with (
        patch(_ROOT_FN, return_value=str(project)),
        patch(f"{_GATE}.resolve_project_root", return_value=str(project)),
        patch.object(handler, "_resolve_executable", return_value=_FAKE_TOOL),
        patch(f"{_GATE}.subprocess.run", return_value=_completed(returncode)) as run,
    ):
        diagnosis = handler._syntax_check(play, strategy)
    return diagnosis, run


class TestDeclaredConfigIsHonouredByBothGates:
    def test_lint_on_edit_runs_under_the_declared_config(self, project: Path) -> None:
        layout = _layout({"plays/**": "infra/ansible.cfg"})

        result, run = _run_lint_on_edit(project, layout, returncode=0)

        assert result is None
        kwargs = run.call_args.kwargs
        assert kwargs["cwd"] == str(project / "infra")
        assert kwargs["env"]["ANSIBLE_CONFIG"] == str(project / "infra" / "ansible.cfg")

    def test_the_commit_gate_runs_under_the_declared_config(self, project: Path) -> None:
        layout = _layout({"plays/**": "infra/ansible.cfg"})

        diagnosis, run = _run_gate(project, layout, returncode=0)

        assert diagnosis is None
        kwargs = run.call_args.kwargs
        assert kwargs["cwd"] == str(project / "infra")
        assert kwargs["env"]["ANSIBLE_CONFIG"] == str(project / "infra" / "ansible.cfg")

    def test_a_declared_config_that_is_missing_denies_loudly_in_lint_on_edit(
        self, project: Path
    ) -> None:
        layout = _layout({"plays/**": "infra/missing.cfg"})

        result, run = _run_lint_on_edit(project, layout, returncode=0)

        assert result is not None
        assert result.decision == Decision.DENY
        assert "infra/missing.cfg" in result.reason
        run.assert_not_called()

    def test_a_declared_config_that_is_missing_fails_the_commit_gate_loudly(
        self, project: Path
    ) -> None:
        layout = _layout({"plays/**": "infra/missing.cfg"})

        diagnosis, run = _run_gate(project, layout, returncode=0)

        assert diagnosis is not None
        assert "infra/missing.cfg" in diagnosis
        run.assert_not_called()


class TestNoDeclarationAgreesOnTheWorkspaceRoot:
    def test_both_gates_use_the_same_working_directory(self, project: Path) -> None:
        layout = _layout({})

        _, edit_run = _run_lint_on_edit(project, layout, returncode=0)
        _, gate_run = _run_gate(project, layout, returncode=0)

        assert edit_run.call_args.kwargs["cwd"] == str(project)
        assert gate_run.call_args.kwargs["cwd"] == str(project)


class TestFailureWithoutAConfigStillDenies:
    def test_lint_on_edit_denies_and_names_the_option(self, project: Path) -> None:
        result, _ = _run_lint_on_edit(project, _layout({}), returncode=1)

        assert result is not None
        assert result.decision == Decision.DENY
        assert _CONTEXT_FAILURE in result.reason
        assert "no ansible.cfg was in effect" in result.reason
        assert "layout.ansible_configs" in result.reason

    def test_the_commit_gate_denies_and_names_the_option(self, project: Path) -> None:
        diagnosis, _ = _run_gate(project, _layout({}), returncode=1)

        assert diagnosis is not None
        assert _CONTEXT_FAILURE in diagnosis
        assert "no ansible.cfg was in effect" in diagnosis
        assert "layout.ansible_configs" in diagnosis

    def test_a_failure_under_a_declared_config_carries_no_such_note(self, project: Path) -> None:
        layout = _layout({"plays/**": "infra/ansible.cfg"})

        result, _ = _run_lint_on_edit(project, layout, returncode=1)
        diagnosis, _ = _run_gate(project, layout, returncode=1)

        assert result is not None
        assert "no ansible.cfg was in effect" not in result.reason
        assert diagnosis is not None
        assert "no ansible.cfg was in effect" not in diagnosis


def test_timeout_is_still_an_allow_not_a_context_error(project: Path) -> None:
    """The note belongs to a FAILED check only; a timeout keeps its own path."""
    handler = LintOnEditHandler()
    handler._project_layout = _layout({})
    strategy = AnsibleLintStrategy()
    with (
        patch(_ROOT_FN, return_value=str(project)),
        patch(f"{_LINT_ON_EDIT}.resolve_project_root", return_value=str(project)),
        patch.object(handler, "_resolve_executable", return_value=_FAKE_TOOL),
        patch(
            f"{_LINT_ON_EDIT}.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="x", timeout=Timeout.LINT_CHECK),
        ),
    ):
        result = handler._run_lint_command(
            {},
            strategy.default_lint_command,
            str(project / "plays" / "site.yml"),
            "Ansible",
            strategy,
        )

    assert result is not None
    assert result.decision == Decision.ALLOW
