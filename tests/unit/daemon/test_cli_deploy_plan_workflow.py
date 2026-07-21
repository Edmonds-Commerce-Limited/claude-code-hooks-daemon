"""Tests for the ``deploy-plan-workflow`` CLI subcommand (Plan 00185)."""

import argparse
from pathlib import Path

from claude_code_hooks_daemon.daemon.cli import cmd_deploy_plan_workflow


def _ns(project_root: Path) -> argparse.Namespace:
    return argparse.Namespace(project_root=project_root)


class TestCmdDeployPlanWorkflow:
    def test_deploys_mkplan_when_enabled(self, tmp_path: Path) -> None:
        (tmp_path / ".claude").mkdir()
        (tmp_path / ".claude" / "hooks-daemon.yaml").write_text(
            "plan_workflow:\n  enabled: true\n  directory: CLAUDE/Plan\n"
        )

        result = cmd_deploy_plan_workflow(_ns(tmp_path))

        assert result == 0
        assert (tmp_path / "CLAUDE" / "Plan" / "mkplan.bash").exists()
        # The journal marker that turns on JOURNAL/ scaffolding must be seeded.
        assert (tmp_path / "CLAUDE" / "Plan" / "_JOURNAL_TEMPLATE_.md").exists()

    def test_disabled_config_is_noop_exit_zero(self, tmp_path: Path) -> None:
        (tmp_path / ".claude").mkdir()
        (tmp_path / ".claude" / "hooks-daemon.yaml").write_text(
            "plan_workflow:\n  enabled: false\n"
        )

        result = cmd_deploy_plan_workflow(_ns(tmp_path))

        assert result == 0
        assert not (tmp_path / "CLAUDE" / "Plan" / "mkplan.bash").exists()

    def test_missing_config_defaults_to_disabled_noop(self, tmp_path: Path) -> None:
        # No hooks-daemon.yaml → model default is plan_workflow.enabled=False,
        # so deployment is a clean no-op (exit 0, nothing written).
        (tmp_path / ".claude").mkdir()
        result = cmd_deploy_plan_workflow(_ns(tmp_path))
        assert result == 0
        assert not (tmp_path / "CLAUDE" / "Plan" / "mkplan.bash").exists()
