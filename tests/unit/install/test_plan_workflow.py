"""Tests for plan workflow bootstrapping."""

from pathlib import Path

from claude_code_hooks_daemon.install.plan_workflow import bootstrap_plan_workflow


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
