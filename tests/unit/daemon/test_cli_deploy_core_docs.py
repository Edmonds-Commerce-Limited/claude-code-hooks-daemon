"""Tests for the ``deploy-core-docs`` CLI subcommand (Plan 00377 N5).

Core documents are daemon-owned and deployed from
``install/templates/core/*.core.md``, but the only callers of
``deploy_core_docs_if_enabled`` were ``scripts/install_version.sh`` and
``scripts/upgrade_version.sh``. Editing a template therefore left the deployed
``CLAUDE/core/*.core.md`` stale until the next install or upgrade, with nothing
reporting the drift — ``deploy-plan-workflow`` does not cover core docs and a
daemon restart does not either.

Agents already had ``agents install`` as their dev-loop refresh. This is the
equivalent for core docs.
"""

import argparse
from pathlib import Path

import pytest

from claude_code_hooks_daemon.daemon.cli import cmd_deploy_core_docs


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / ".claude").mkdir(parents=True)
    # plan_workflow must be ON: deploy_core_docs_if_enabled narrows the set to
    # the documents whose gating config is enabled, so PlanWorkflow.core.md is
    # deliberately absent from a project that does not use plan workflow.
    (root / ".claude" / "hooks-daemon.yaml").write_text(
        "version: '2.0'\nplan_workflow:\n  enabled: true\n"
    )
    (root / "CLAUDE").mkdir()
    return root


def _args(project_root: Path | None) -> argparse.Namespace:
    return argparse.Namespace(project_root=project_root)


class TestDeployCoreDocs:
    def test_it_writes_the_core_documents(self, tmp_path: Path) -> None:
        root = _project(tmp_path)
        assert cmd_deploy_core_docs(_args(root)) == 0
        assert (root / "CLAUDE" / "core" / "PlanWorkflow.core.md").is_file()

    def test_it_refreshes_a_stale_deployed_copy(self, tmp_path: Path) -> None:
        """The whole point of N5: a stale deployed copy is brought back."""
        root = _project(tmp_path)
        cmd_deploy_core_docs(_args(root))
        deployed = root / "CLAUDE" / "core" / "PlanWorkflow.core.md"
        fresh = deployed.read_text()
        deployed.write_text("stale\n")

        assert cmd_deploy_core_docs(_args(root)) == 0
        assert deployed.read_text() == fresh

    def test_it_reports_what_it_refreshed(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = _project(tmp_path)
        cmd_deploy_core_docs(_args(root))
        assert "PlanWorkflow.core.md" in capsys.readouterr().out

    def test_it_is_idempotent(self, tmp_path: Path) -> None:
        root = _project(tmp_path)
        assert cmd_deploy_core_docs(_args(root)) == 0
        assert cmd_deploy_core_docs(_args(root)) == 0

    def test_a_missing_project_root_falls_back_to_cwd(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Mirrors Plan 00374: resolved here, never as an argparse default."""
        root = _project(tmp_path)
        monkeypatch.chdir(root)
        assert cmd_deploy_core_docs(_args(None)) == 0
        assert (root / "CLAUDE" / "core" / "PlanWorkflow.core.md").is_file()
