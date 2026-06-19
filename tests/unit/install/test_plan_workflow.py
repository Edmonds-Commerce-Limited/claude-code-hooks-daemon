"""Tests for plan workflow bootstrapping."""

import stat
from pathlib import Path

from claude_code_hooks_daemon.install.plan_workflow import (
    MKPLAN_SCRIPT_NAME,
    bootstrap_plan_workflow,
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
