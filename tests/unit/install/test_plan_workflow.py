"""Tests for plan workflow bootstrapping."""

import stat
import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.install import plan_workflow as _plan_workflow_module
from claude_code_hooks_daemon.install.plan_workflow import (
    JOURNAL_TEMPLATE_NAME,
    MKPLAN_SCRIPT_NAME,
    PLAN_JOURNALLING_DOC_NAME,
    PLAN_TEMPLATE_NAME,
    TEMPLATE_SNAPSHOT_NAME,
    bootstrap_plan_workflow,
    deploy_plan_workflow_if_enabled,
    journal_template_path,
    mkplan_template_path,
    plan_journalling_doc_path,
    plan_template_default_path,
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


class TestPlanTemplateDeployment:
    """Tests for the tracked plan template `_TEMPLATE_.md` (Plan 00144 Phase 5).

    Projects manage their own plan template; the daemon seeds a default when
    none exists and — via a daemon-owned snapshot of the default it last
    deployed — surfaces upstream template changes on upgrade so the project
    can adopt them if wanted. The project's template is NEVER overwritten.
    """

    def test_bundled_default_template_exists_with_placeholders(self) -> None:
        """The canonical default template is bundled inside the package."""
        template = plan_template_default_path()
        assert template.is_file()
        body = template.read_text()
        for placeholder in (
            "{{PLAN_NUMBER}}",
            "{{PLAN_TITLE}}",
            "{{CREATED_DATE}}",
            "{{OWNER}}",
        ):
            assert placeholder in body
        assert "**Status**: Not Started" in body

    def test_creates_template_when_missing(self, tmp_path: Path) -> None:
        """Bootstrap seeds _TEMPLATE_.md from the bundled default."""
        result = bootstrap_plan_workflow(tmp_path)
        deployed = tmp_path / "CLAUDE" / "Plan" / PLAN_TEMPLATE_NAME
        assert deployed.is_file()
        assert deployed.read_text() == plan_template_default_path().read_text()
        assert result.created_template is True

    def test_preserves_existing_template(self, tmp_path: Path) -> None:
        """A project-customised template is client-owned: never overwritten."""
        plan_dir = tmp_path / "CLAUDE" / "Plan"
        plan_dir.mkdir(parents=True)
        custom = plan_dir / PLAN_TEMPLATE_NAME
        custom.write_text("# Plan {{PLAN_NUMBER}}: {{PLAN_TITLE}}\n\ncustom body\n")

        result = bootstrap_plan_workflow(tmp_path)

        assert custom.read_text() == "# Plan {{PLAN_NUMBER}}: {{PLAN_TITLE}}\n\ncustom body\n"
        assert result.created_template is False

    def test_snapshot_written_and_daemon_owned(self, tmp_path: Path) -> None:
        """The default-template snapshot is written on every bootstrap."""
        bootstrap_plan_workflow(tmp_path)
        snapshot = tmp_path / "CLAUDE" / "Plan" / TEMPLATE_SNAPSHOT_NAME
        assert snapshot.is_file()
        assert snapshot.read_text() == plan_template_default_path().read_text()

    def test_stale_snapshot_surfaces_default_change(self, tmp_path: Path) -> None:
        """Upgrade with a changed daemon default reports what changed.

        Simulates: previous daemon version deployed default X (snapshot holds
        X), project customised its template, new daemon ships default Y — the
        bootstrap must surface the X→Y change without touching the project's
        template.
        """
        plan_dir = tmp_path / "CLAUDE" / "Plan"
        plan_dir.mkdir(parents=True)
        (plan_dir / PLAN_TEMPLATE_NAME).write_text("# project-owned template\n")
        (plan_dir / TEMPLATE_SNAPSHOT_NAME).write_text("# old daemon default\n")

        result = bootstrap_plan_workflow(tmp_path)

        assert result.template_default_changed is True
        assert any("template" in m.lower() and "changed" in m.lower() for m in result.messages)
        # Snapshot is refreshed to the new default afterwards.
        snapshot_text = (plan_dir / TEMPLATE_SNAPSHOT_NAME).read_text()
        assert snapshot_text == plan_template_default_path().read_text()
        # Project template untouched.
        assert (plan_dir / PLAN_TEMPLATE_NAME).read_text() == "# project-owned template\n"

    def test_unchanged_default_is_quiet(self, tmp_path: Path) -> None:
        """Re-running with an up-to-date snapshot reports no template change."""
        bootstrap_plan_workflow(tmp_path)
        result = bootstrap_plan_workflow(tmp_path)
        assert result.template_default_changed is False


class TestMkplanUsesProjectTemplate:
    """mkplan.bash renders `_TEMPLATE_.md` when present (Plan 00144 Phase 5)."""

    def _scaffold_repo(self, tmp_path: Path) -> tuple[Path, Path]:
        """Create a git repo with a deployed plan dir + mkplan script."""
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(
            ["git", "init", str(repo)],
            capture_output=True,
            check=True,
            timeout=Timeout.GIT_CONTEXT,
        )
        subprocess.run(
            ["git", "-C", str(repo), "config", "user.name", "Template Tester"],
            capture_output=True,
            check=True,
            timeout=Timeout.GIT_CONTEXT,
        )
        bootstrap_plan_workflow(repo)
        plan_dir = repo / "CLAUDE" / "Plan"
        return repo, plan_dir

    def _run_mkplan(self, plan_dir: Path, name: str) -> Path:
        """Invoke the deployed mkplan.bash and return the created plan folder."""
        result = subprocess.run(
            ["bash", str(plan_dir / MKPLAN_SCRIPT_NAME), name],
            capture_output=True,
            text=True,
            check=True,
            timeout=Timeout.REQUEST_DEFAULT,
        )
        return Path(result.stdout.strip())

    def test_custom_template_is_rendered_with_substitutions(self, tmp_path: Path) -> None:
        """A project template's placeholders are substituted into PLAN.md."""
        _, plan_dir = self._scaffold_repo(tmp_path)
        (plan_dir / PLAN_TEMPLATE_NAME).write_text(
            "# Plan {{PLAN_NUMBER}}: {{PLAN_TITLE}}\n\n"
            "**Status**: Not Started\n"
            "**Created**: {{CREATED_DATE}}\n"
            "**Owner**: {{OWNER}}\n\n"
            "## Custom Project Section\n"
        )

        target = self._run_mkplan(plan_dir, "widget-frobnication")
        content = (target / "PLAN.md").read_text()

        assert "# Plan 00001: widget frobnication" in content
        assert "**Owner**: Template Tester" in content
        assert "## Custom Project Section" in content
        assert "{{" not in content

    def test_missing_template_falls_back_to_builtin(self, tmp_path: Path) -> None:
        """Without _TEMPLATE_.md the script scaffolds from its built-in skeleton."""
        _, plan_dir = self._scaffold_repo(tmp_path)
        (plan_dir / PLAN_TEMPLATE_NAME).unlink()

        target = self._run_mkplan(plan_dir, "fallback-check")
        content = (target / "PLAN.md").read_text()

        assert "# Plan 00001: fallback check" in content
        assert "**Status**: Not Started" in content
        assert "## Success Criteria" in content


class TestMkplanScaffoldsJournal:
    """mkplan.bash scaffolds JOURNAL/ when _JOURNAL_TEMPLATE_.md is present (Plan 00163)."""

    _JOURNAL_TEMPLATE_NAME = "_JOURNAL_TEMPLATE_.md"

    def _scaffold_repo(self, tmp_path: Path) -> tuple[Path, Path]:
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(
            ["git", "init", str(repo)],
            capture_output=True,
            check=True,
            timeout=Timeout.GIT_CONTEXT,
        )
        subprocess.run(
            ["git", "-C", str(repo), "config", "user.name", "Journal Tester"],
            capture_output=True,
            check=True,
            timeout=Timeout.GIT_CONTEXT,
        )
        bootstrap_plan_workflow(repo)
        return repo, repo / "CLAUDE" / "Plan"

    def _run_mkplan(self, plan_dir: Path, name: str) -> Path:
        result = subprocess.run(
            ["bash", str(plan_dir / MKPLAN_SCRIPT_NAME), name],
            capture_output=True,
            text=True,
            check=True,
            timeout=Timeout.REQUEST_DEFAULT,
        )
        return Path(result.stdout.strip())

    def test_scaffolds_journal_when_template_present(self, tmp_path: Path) -> None:
        """A _JOURNAL_TEMPLATE_.md triggers JOURNAL/NNNNN-Journal-YY-MM-DD.md creation."""
        _, plan_dir = self._scaffold_repo(tmp_path)
        (plan_dir / self._JOURNAL_TEMPLATE_NAME).write_text(
            "# Plan {{PLAN_NUMBER}} — Journal {{DATE}}\n\n"
            "## {{TIME}} · action · — — scaffolded\n"
            "By {{OWNER}} on plan {{PLAN_NUMBER}}.\n"
        )

        target = self._run_mkplan(plan_dir, "journalled-plan")

        journal_dir = target / "JOURNAL"
        assert journal_dir.is_dir(), "JOURNAL/ folder should be scaffolded"
        day_files = list(journal_dir.glob("00001-Journal-*.md"))
        assert len(day_files) == 1, f"expected one day-file, got {day_files}"

        name = day_files[0].name
        # NNNNN-Journal-YY-MM-DD.md
        assert name.startswith("00001-Journal-") and name.endswith(".md")
        date_part = name[len("00001-Journal-") : -len(".md")]
        chunks = date_part.split("-")
        assert len(chunks) == 3 and all(len(c) == 2 and c.isdigit() for c in chunks), name

        content = day_files[0].read_text()
        assert "# Plan 00001 — Journal" in content
        assert "By Journal Tester on plan 00001." in content
        assert "{{" not in content

    def test_no_journal_when_template_absent(self, tmp_path: Path) -> None:
        """Without _JOURNAL_TEMPLATE_.md, plans are created journal-less (gated)."""
        _, plan_dir = self._scaffold_repo(tmp_path)
        template = plan_dir / self._JOURNAL_TEMPLATE_NAME
        if template.exists():
            template.unlink()

        target = self._run_mkplan(plan_dir, "unjournalled-plan")

        assert not (target / "JOURNAL").exists(), "no JOURNAL/ without the template marker"


class TestJournalAssetDeployment:
    """bootstrap seeds journal assets so client projects journal by default.

    Plan 00163 Phase 4 (Decision 11): journalling ships enabled-by-default and
    fully deployed. Both assets are CLIENT-owned (created when absent, never
    overwritten): ``_JOURNAL_TEMPLATE_.md`` (its presence is the marker that
    gates mkplan's JOURNAL/ scaffolding) and ``PlanJournalling.md`` (the
    copy-and-customise reference doc).
    """

    def test_bundled_journal_template_exists(self) -> None:
        template = journal_template_path()
        assert template.is_file()
        assert "{{PLAN_NUMBER}}" in template.read_text()

    def test_bundled_journalling_doc_exists(self) -> None:
        doc = plan_journalling_doc_path()
        assert doc.is_file()

    def test_bundled_journalling_doc_matches_repo_canonical(self) -> None:
        """SSoT: the bundled reference is byte-identical to this repo's own copy."""
        repo_root = Path(__file__).resolve().parents[3]
        canonical = repo_root / "CLAUDE" / PLAN_JOURNALLING_DOC_NAME
        assert plan_journalling_doc_path().read_text() == canonical.read_text()

    def test_deploys_journal_template_when_missing(self, tmp_path: Path) -> None:
        result = bootstrap_plan_workflow(tmp_path)
        deployed = tmp_path / "CLAUDE" / "Plan" / JOURNAL_TEMPLATE_NAME
        assert deployed.is_file()
        assert deployed.read_text() == journal_template_path().read_text()
        assert result.created_journal_template is True

    def test_preserves_existing_journal_template(self, tmp_path: Path) -> None:
        plan_dir = tmp_path / "CLAUDE" / "Plan"
        plan_dir.mkdir(parents=True)
        (plan_dir / JOURNAL_TEMPLATE_NAME).write_text("# custom journal template\n")
        result = bootstrap_plan_workflow(tmp_path)
        assert (plan_dir / JOURNAL_TEMPLATE_NAME).read_text() == "# custom journal template\n"
        assert result.created_journal_template is False

    def test_deploys_journalling_doc_to_plan_dir_parent_when_missing(self, tmp_path: Path) -> None:
        # The reference doc lands in the plan dir's PARENT (CLAUDE/), NOT the
        # plan root — the plan root only accepts _EXPECTED_ROOT_FILES, so a doc
        # there would be flagged as a stray by the sweep.
        result = bootstrap_plan_workflow(tmp_path)
        deployed = tmp_path / "CLAUDE" / PLAN_JOURNALLING_DOC_NAME
        assert deployed.is_file()
        assert deployed.read_text() == plan_journalling_doc_path().read_text()
        assert result.created_journalling_doc is True
        # Must NOT be seeded into the plan root (regression: stray-file flag).
        assert not (tmp_path / "CLAUDE" / "Plan" / PLAN_JOURNALLING_DOC_NAME).exists()

    def test_preserves_existing_journalling_doc(self, tmp_path: Path) -> None:
        parent_dir = tmp_path / "CLAUDE"
        parent_dir.mkdir(parents=True)
        (parent_dir / PLAN_JOURNALLING_DOC_NAME).write_text("# customised reference\n")
        result = bootstrap_plan_workflow(tmp_path)
        assert (parent_dir / PLAN_JOURNALLING_DOC_NAME).read_text() == "# customised reference\n"
        assert result.created_journalling_doc is False

    def test_journal_assets_deployed_via_enabled_config(self, tmp_path: Path) -> None:
        config_dir = tmp_path / ".claude"
        config_dir.mkdir(parents=True)
        config_path = config_dir / "hooks-daemon.yaml"
        config_path.write_text("plan_workflow:\n  enabled: true\n")
        deploy_plan_workflow_if_enabled(tmp_path, config_path)
        plan_dir = tmp_path / "CLAUDE" / "Plan"
        assert (plan_dir / JOURNAL_TEMPLATE_NAME).is_file()
        assert (plan_dir.parent / PLAN_JOURNALLING_DOC_NAME).is_file()

    def test_no_journal_assets_when_disabled(self, tmp_path: Path) -> None:
        config_dir = tmp_path / ".claude"
        config_dir.mkdir(parents=True)
        config_path = config_dir / "hooks-daemon.yaml"
        config_path.write_text("plan_workflow:\n  enabled: false\n")
        deploy_plan_workflow_if_enabled(tmp_path, config_path)
        plan_dir = tmp_path / "CLAUDE" / "Plan"
        assert not (plan_dir / JOURNAL_TEMPLATE_NAME).exists()
        assert not (plan_dir.parent / PLAN_JOURNALLING_DOC_NAME).exists()


class TestMissingBundledAssetsFailFast:
    """Every bundled deploy source is required — a missing one FAILS FAST.

    These guard the packaging contract: if the wheel/sdist ever ships without
    one of the bundled templates, bootstrap must raise loudly rather than
    silently produce a half-scaffolded plan directory.
    """

    @pytest.mark.parametrize(
        ("helper_name", "match"),
        [
            ("mkplan_template_path", "plan-scaffolding script"),
            ("plan_template_default_path", "plan template"),
            ("journal_template_path", "journal template"),
            ("plan_journalling_doc_path", "journalling reference"),
        ],
    )
    def test_missing_bundled_source_raises(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        helper_name: str,
        match: str,
    ) -> None:
        monkeypatch.setattr(
            _plan_workflow_module,
            helper_name,
            lambda: tmp_path / "does-not-exist.md",
        )
        with pytest.raises(FileNotFoundError, match=match):
            bootstrap_plan_workflow(tmp_path)


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
