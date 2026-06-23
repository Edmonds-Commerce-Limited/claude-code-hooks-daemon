"""Tests for plan workflow bootstrapping."""

import stat
from pathlib import Path

from claude_code_hooks_daemon.install.plan_workflow import (
    MKPLAN_SCRIPT_NAME,
    bootstrap_plan_workflow,
    deploy_plan_workflow_if_enabled,
    mkplan_template_path,
)


class TestBootstrapPlanWorkflow:
    """Tests for bootstrap_plan_workflow()."""

    def test_creates_plan_directory(self, tmp_path: Path) -> None:
        """Creates CLAUDE/Plan/ directory if missing."""
        result = bootstrap_plan_workflow(tmp_path)
        assert result.success is True
        assert (tmp_path / "CLAUDE" / "Plan").is_dir()

    def test_creates_readme(self, tmp_path: Path) -> None:
        """Creates CLAUDE/Plan/README.md with plan index template."""
        bootstrap_plan_workflow(tmp_path)
        readme = tmp_path / "CLAUDE" / "Plan" / "README.md"
        assert readme.exists()
        content = readme.read_text()
        assert "Plans Index" in content
        assert "Active Plans" in content
        assert "Completed Plans" in content

    def test_preserves_existing_readme(self, tmp_path: Path) -> None:
        """Does not overwrite existing CLAUDE/Plan/README.md."""
        plan_dir = tmp_path / "CLAUDE" / "Plan"
        plan_dir.mkdir(parents=True)
        readme = plan_dir / "README.md"
        readme.write_text("# My existing plans\n")

        result = bootstrap_plan_workflow(tmp_path)
        assert result.skipped_readme is True
        assert readme.read_text() == "# My existing plans\n"

    def test_creates_completed_directory(self, tmp_path: Path) -> None:
        """Creates CLAUDE/Plan/Completed/ subdirectory."""
        bootstrap_plan_workflow(tmp_path)
        assert (tmp_path / "CLAUDE" / "Plan" / "Completed").is_dir()

    def test_claude_md_completion_guidance_uses_commit_hash_not_date(self, tmp_path: Path) -> None:
        """Deployed CLAUDE.md must align with the no-completion-date doctrine.

        Regression: the template instructed "Update plan status to Complete
        with date", contradicting PlanWorkflow.md and the plan_time_estimates
        handler (git history is authoritative for "when"; cite the delivery
        commit hash, never a date).
        """
        bootstrap_plan_workflow(tmp_path)
        claude_md = tmp_path / "CLAUDE" / "Plan" / "CLAUDE.md"
        content = claude_md.read_text()
        assert "Complete` with date" not in content
        assert "commit hash" in content

    def test_result_messages(self, tmp_path: Path) -> None:
        """Result contains descriptive messages."""
        result = bootstrap_plan_workflow(tmp_path)
        assert len(result.messages) > 0
        assert any("README.md" in m for m in result.messages)

    def test_idempotent(self, tmp_path: Path) -> None:
        """Running twice doesn't error or duplicate content."""
        bootstrap_plan_workflow(tmp_path)
        result = bootstrap_plan_workflow(tmp_path)
        assert result.success is True
        assert result.skipped_readme is True

    def test_creates_claude_md(self, tmp_path: Path) -> None:
        """Creates CLAUDE/Plan/CLAUDE.md with lifecycle instructions."""
        bootstrap_plan_workflow(tmp_path)
        claude_md = tmp_path / "CLAUDE" / "Plan" / "CLAUDE.md"
        assert claude_md.exists()
        content = claude_md.read_text()
        assert "Plan Lifecycle" in content

    def test_preserves_existing_claude_md(self, tmp_path: Path) -> None:
        """Does not overwrite existing CLAUDE/Plan/CLAUDE.md."""
        plan_dir = tmp_path / "CLAUDE" / "Plan"
        plan_dir.mkdir(parents=True)
        claude_md = plan_dir / "CLAUDE.md"
        claude_md.write_text("# Custom lifecycle\n")

        bootstrap_plan_workflow(tmp_path)
        assert claude_md.read_text() == "# Custom lifecycle\n"


class TestMkplanDeployment:
    """Tests for deploying the mkplan.bash scaffolding script (Plan 00130)."""

    def test_bundled_template_exists_and_is_runnable(self) -> None:
        """The canonical mkplan.bash is bundled inside the package."""
        template = mkplan_template_path()
        assert template.is_file()
        assert template.name == MKPLAN_SCRIPT_NAME
        body = template.read_text()
        assert body.startswith("#!/usr/bin/env bash")
        assert "hooksdaemon.latestPlanNumber" in body

    def test_deploys_mkplan_script(self, tmp_path: Path) -> None:
        """bootstrap deploys mkplan.bash into the plan directory."""
        bootstrap_plan_workflow(tmp_path)
        deployed = tmp_path / "CLAUDE" / "Plan" / MKPLAN_SCRIPT_NAME
        assert deployed.is_file()

    def test_deployed_mkplan_matches_bundled_template(self, tmp_path: Path) -> None:
        """Deployed script is byte-identical to the bundled canonical template."""
        bootstrap_plan_workflow(tmp_path)
        deployed = tmp_path / "CLAUDE" / "Plan" / MKPLAN_SCRIPT_NAME
        assert deployed.read_text() == mkplan_template_path().read_text()

    def test_mkplan_script_is_executable(self, tmp_path: Path) -> None:
        """Deployed script has the owner execute bit (0o755)."""
        bootstrap_plan_workflow(tmp_path)
        deployed = tmp_path / "CLAUDE" / "Plan" / MKPLAN_SCRIPT_NAME
        mode = stat.S_IMODE(deployed.stat().st_mode)
        assert mode & stat.S_IXUSR, "owner execute bit must be set"
        assert mode == 0o755

    def test_mkplan_overwritten_on_upgrade(self, tmp_path: Path) -> None:
        """Unlike README/CLAUDE.md, mkplan.bash is daemon-owned: overwrite on upgrade."""
        plan_dir = tmp_path / "CLAUDE" / "Plan"
        plan_dir.mkdir(parents=True)
        stale = plan_dir / MKPLAN_SCRIPT_NAME
        stale.write_text("#!/usr/bin/env bash\n# stale forked copy\n")

        bootstrap_plan_workflow(tmp_path)

        assert stale.read_text() == mkplan_template_path().read_text()

    def test_mkplan_deploy_recorded_in_result(self, tmp_path: Path) -> None:
        """The result reports the mkplan deployment."""
        result = bootstrap_plan_workflow(tmp_path)
        assert result.deployed_mkplan is True
        assert any(MKPLAN_SCRIPT_NAME in m for m in result.messages)

    def test_honours_custom_plan_dir_name(self, tmp_path: Path) -> None:
        """A configured (non-default) plan dir receives the structure + script.

        Regression for the pre-existing hardcoded-'CLAUDE/Plan' SSOT bug:
        bootstrap must honour track_plans_in_project, not assume CLAUDE/Plan.
        """
        result = bootstrap_plan_workflow(tmp_path, plan_dir_name="docs/plans")
        assert result.success is True
        target = tmp_path / "docs" / "plans"
        assert (target / "README.md").is_file()
        assert (target / "Completed").is_dir()
        assert (target / MKPLAN_SCRIPT_NAME).is_file()
        # Default location is NOT created when a custom dir is configured.
        assert not (tmp_path / "CLAUDE" / "Plan").exists()

    def test_idempotent_redeploys_mkplan(self, tmp_path: Path) -> None:
        """Running twice keeps the script in place and identical."""
        bootstrap_plan_workflow(tmp_path)
        bootstrap_plan_workflow(tmp_path)
        deployed = tmp_path / "CLAUDE" / "Plan" / MKPLAN_SCRIPT_NAME
        assert deployed.read_text() == mkplan_template_path().read_text()


class TestDeployPlanWorkflowIfEnabled:
    """Tests for config-SSoT-driven deployment (Plan 00136).

    Regression for the v3.24.0 field bug: mkplan.bash was only deployed by
    install_version.sh behind PLAN_WORKFLOW=yes, and never on upgrade — so
    plan_number_helper guidance referenced a script that did not exist. The
    fix derives deployment from config.plan_workflow.enabled (the SSoT the
    daemon already reads), via a single entrypoint shared by install + both
    upgrade paths.
    """

    def _write_config(self, project_root: Path, body: str) -> Path:
        config_dir = project_root / ".claude"
        config_dir.mkdir(parents=True, exist_ok=True)
        config_path = config_dir / "hooks-daemon.yaml"
        config_path.write_text(body)
        return config_path

    def test_enabled_config_deploys_mkplan(self, tmp_path: Path) -> None:
        """plan_workflow.enabled: true → mkplan deployed into the plan dir."""
        config_path = self._write_config(tmp_path, "plan_workflow:\n  enabled: true\n")

        result = deploy_plan_workflow_if_enabled(tmp_path, config_path)

        assert result.success is True
        assert result.deployed_mkplan is True
        deployed = tmp_path / "CLAUDE" / "Plan" / MKPLAN_SCRIPT_NAME
        assert deployed.read_text() == mkplan_template_path().read_text()

    def test_enabled_config_mkplan_is_executable(self, tmp_path: Path) -> None:
        """Deployed script keeps the owner execute bit (0o755)."""
        config_path = self._write_config(tmp_path, "plan_workflow:\n  enabled: true\n")

        deploy_plan_workflow_if_enabled(tmp_path, config_path)

        deployed = tmp_path / "CLAUDE" / "Plan" / MKPLAN_SCRIPT_NAME
        assert stat.S_IMODE(deployed.stat().st_mode) == 0o755

    def test_disabled_config_is_noop(self, tmp_path: Path) -> None:
        """plan_workflow.enabled: false → no deployment, mkplan absent."""
        config_path = self._write_config(tmp_path, "plan_workflow:\n  enabled: false\n")

        result = deploy_plan_workflow_if_enabled(tmp_path, config_path)

        assert result.deployed_mkplan is False
        assert not (tmp_path / "CLAUDE" / "Plan" / MKPLAN_SCRIPT_NAME).exists()
        assert any("disabled" in m.lower() for m in result.messages)

    def test_honours_configured_directory(self, tmp_path: Path) -> None:
        """A non-default plan_workflow.directory receives the script."""
        config_path = self._write_config(
            tmp_path, "plan_workflow:\n  enabled: true\n  directory: docs/plans\n"
        )

        deploy_plan_workflow_if_enabled(tmp_path, config_path)

        assert (tmp_path / "docs" / "plans" / MKPLAN_SCRIPT_NAME).is_file()
        assert not (tmp_path / "CLAUDE" / "Plan").exists()

    def test_missing_config_uses_opt_in_default(self, tmp_path: Path) -> None:
        """No config file → model default (disabled, F-PLANDEF) → no deploy.

        Plan 00137 flipped the plan_workflow default to opt-in. A project with
        no config on disk therefore does NOT get CLAUDE/Plan/ scattered — the
        deploy matches the opt-in plan handlers. (Pre-00137 this deployed by
        default; the change is intentional and carries config/truth-change
        notes.)
        """
        missing = tmp_path / ".claude" / "hooks-daemon.yaml"

        result = deploy_plan_workflow_if_enabled(tmp_path, missing)

        assert result.deployed_mkplan is False
        assert not (tmp_path / "CLAUDE" / "Plan").exists()

    def test_migrated_legacy_option_enables_deploy(self, tmp_path: Path) -> None:
        """Legacy track_plans_in_project handler option drives deployment too.

        Config.migrate_plan_handler_options promotes the legacy handler option
        into plan_workflow, so deployment honours projects that still configure
        the plan dir the old way.
        """
        config_path = self._write_config(
            tmp_path,
            "handlers:\n"
            "  pre_tool_use:\n"
            "    markdown_organization:\n"
            "      options:\n"
            "        track_plans_in_project: docs/legacy-plans\n",
        )

        result = deploy_plan_workflow_if_enabled(tmp_path, config_path)

        assert result.deployed_mkplan is True
        assert (tmp_path / "docs" / "legacy-plans" / MKPLAN_SCRIPT_NAME).is_file()
