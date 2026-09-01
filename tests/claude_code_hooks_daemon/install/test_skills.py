"""Tests for skill deployment system."""

import shutil
from collections.abc import Generator
from pathlib import Path

import pytest

from claude_code_hooks_daemon.install.skills import deploy_skills


@pytest.fixture
def temp_project(tmp_path: Path) -> Generator[Path, None, None]:
    """Create a temporary project directory."""
    project = tmp_path / "test-project"
    project.mkdir()

    # Create .claude directory
    claude_dir = project / ".claude"
    claude_dir.mkdir()

    yield project

    # Cleanup
    if project.exists():
        shutil.rmtree(project)


@pytest.fixture
def daemon_source(tmp_path: Path) -> Generator[Path, None, None]:
    """Create fake daemon source directory with skills."""
    source = tmp_path / "daemon-source"
    source.mkdir()

    # Create skills directory
    skills_dir = source / "skills" / "hooks-daemon"
    skills_dir.mkdir(parents=True)

    # Create skill files
    (skills_dir / "SKILL.md").write_text("# Hooks Daemon Skill\n")
    (skills_dir / "upgrade.md").write_text("# Upgrade\n")
    (skills_dir / "health.md").write_text("# Health\n")

    # Create scripts directory
    scripts_dir = skills_dir / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "upgrade.sh").write_text("#!/bin/bash\necho upgrade\n")
    (scripts_dir / "health-check.sh").write_text("#!/bin/bash\necho health\n")

    yield source

    # Cleanup
    if source.exists():
        shutil.rmtree(source)


class TestDeploySkills:
    """Test skill deployment to user projects."""

    def test_deploy_skills_creates_directory(self, temp_project: Path, daemon_source: Path) -> None:
        """Test that deploy_skills creates .claude/skills/hooks-daemon directory."""
        # Act
        deploy_skills(daemon_source, temp_project)

        # Assert
        target_dir = temp_project / ".claude" / "skills" / "hooks-daemon"
        assert target_dir.exists()
        assert target_dir.is_dir()

    def test_deploy_skills_copies_skill_files(
        self, temp_project: Path, daemon_source: Path
    ) -> None:
        """Test that deploy_skills copies all skill markdown files."""
        # Act
        deploy_skills(daemon_source, temp_project)

        # Assert
        target_dir = temp_project / ".claude" / "skills" / "hooks-daemon"
        assert (target_dir / "SKILL.md").exists()
        assert (target_dir / "upgrade.md").exists()
        assert (target_dir / "health.md").exists()

        # Verify content
        assert (target_dir / "SKILL.md").read_text() == "# Hooks Daemon Skill\n"

    def test_deploy_skills_copies_scripts(self, temp_project: Path, daemon_source: Path) -> None:
        """Test that deploy_skills copies script files."""
        # Act
        deploy_skills(daemon_source, temp_project)

        # Assert
        scripts_dir = temp_project / ".claude" / "skills" / "hooks-daemon" / "scripts"
        assert scripts_dir.exists()
        assert (scripts_dir / "upgrade.sh").exists()
        assert (scripts_dir / "health-check.sh").exists()

    def test_deploy_skills_makes_scripts_executable(
        self, temp_project: Path, daemon_source: Path
    ) -> None:
        """Test that deploy_skills makes script files executable."""
        # Act
        deploy_skills(daemon_source, temp_project)

        # Assert
        scripts_dir = temp_project / ".claude" / "skills" / "hooks-daemon" / "scripts"
        upgrade_script = scripts_dir / "upgrade.sh"
        health_script = scripts_dir / "health-check.sh"

        # Check executable bit is set (owner execute permission)
        assert upgrade_script.stat().st_mode & 0o100  # Owner execute
        assert health_script.stat().st_mode & 0o100

    def test_deploy_skills_overwrites_existing(
        self, temp_project: Path, daemon_source: Path
    ) -> None:
        """Test that deploy_skills overwrites existing skill files."""
        # Arrange - create old skill file
        target_dir = temp_project / ".claude" / "skills" / "hooks-daemon"
        target_dir.mkdir(parents=True)
        (target_dir / "SKILL.md").write_text("# Old Skill\n")

        # Act
        deploy_skills(daemon_source, temp_project)

        # Assert - content updated
        assert (target_dir / "SKILL.md").read_text() == "# Hooks Daemon Skill\n"

    def test_deploy_skills_raises_if_source_missing(
        self, temp_project: Path, tmp_path: Path
    ) -> None:
        """Test that deploy_skills raises error if source skills don't exist."""
        # Arrange - source without skills
        bad_source = tmp_path / "no-skills"
        bad_source.mkdir()

        # Act & Assert
        with pytest.raises(FileNotFoundError, match="Skills directory not found"):
            deploy_skills(bad_source, temp_project)

    @pytest.mark.skipif(
        Path("/").stat().st_uid == 0, reason="Running as root - permission test not applicable"
    )
    def test_deploy_skills_raises_if_target_not_writable(
        self, daemon_source: Path, tmp_path: Path
    ) -> None:
        """Test that deploy_skills raises error if target not writable."""
        # Arrange - read-only project
        readonly_project = tmp_path / "readonly"
        readonly_project.mkdir()
        readonly_project.chmod(0o444)  # Read-only

        try:
            # Act & Assert
            with pytest.raises(PermissionError):
                deploy_skills(daemon_source, readonly_project)
        finally:
            # Cleanup - restore permissions
            readonly_project.chmod(0o755)

    def test_deploy_skills_preserves_directory_structure(
        self, temp_project: Path, daemon_source: Path
    ) -> None:
        """Test that deploy_skills preserves nested directory structure."""
        # Arrange - add nested directory in source
        references_dir = daemon_source / "skills" / "hooks-daemon" / "references"
        references_dir.mkdir()
        (references_dir / "troubleshooting.md").write_text("# Troubleshooting\n")

        # Act
        deploy_skills(daemon_source, temp_project)

        # Assert
        target_refs = temp_project / ".claude" / "skills" / "hooks-daemon" / "references"
        assert target_refs.exists()
        assert (target_refs / "troubleshooting.md").exists()
        assert (target_refs / "troubleshooting.md").read_text() == "# Troubleshooting\n"

    def test_deploy_skills_version_alignment(self, temp_project: Path, daemon_source: Path) -> None:
        """Test that deployed skills match daemon version (placeholder test)."""
        # This will be implemented when version tracking is added
        # For now, just verify skills were deployed
        deploy_skills(daemon_source, temp_project)

        target_dir = temp_project / ".claude" / "skills" / "hooks-daemon"
        assert target_dir.exists()
        # TODO: Add version file check when implemented


class TestDeployMultipleSkills:
    """Plan 00284: the bundled skills/ directory now ships more than one
    skill (hooks-daemon + docs-qa) — every subdirectory must deploy."""

    @pytest.fixture
    def daemon_source_two_skills(self, tmp_path: Path) -> Generator[Path, None, None]:
        source = tmp_path / "daemon-source-two"
        source.mkdir()
        skills_root = source / "skills"

        hooks_daemon_dir = skills_root / "hooks-daemon"
        hooks_daemon_dir.mkdir(parents=True)
        (hooks_daemon_dir / "SKILL.md").write_text("# Hooks Daemon Skill\n")

        docs_qa_dir = skills_root / "docs-qa"
        docs_qa_dir.mkdir(parents=True)
        (docs_qa_dir / "SKILL.md").write_text("# Docs QA Skill\n")
        scripts_dir = docs_qa_dir / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "find-comment-blocks.sh").write_text("#!/bin/bash\necho blocks\n")

        yield source

        if source.exists():
            shutil.rmtree(source)

    def test_deploys_every_bundled_skill(
        self, temp_project: Path, daemon_source_two_skills: Path
    ) -> None:
        deploy_skills(daemon_source_two_skills, temp_project)

        skills_dir = temp_project / ".claude" / "skills"
        assert (skills_dir / "hooks-daemon" / "SKILL.md").read_text() == "# Hooks Daemon Skill\n"
        assert (skills_dir / "docs-qa" / "SKILL.md").read_text() == "# Docs QA Skill\n"

    def test_docs_qa_scripts_made_executable(
        self, temp_project: Path, daemon_source_two_skills: Path
    ) -> None:
        deploy_skills(daemon_source_two_skills, temp_project)

        script = (
            temp_project / ".claude" / "skills" / "docs-qa" / "scripts" / "find-comment-blocks.sh"
        )
        assert script.stat().st_mode & 0o100

    def test_real_bundled_skills_directory_deploys_both(self, temp_project: Path) -> None:
        """Acceptance check against the REAL repository layout, not a fixture."""
        real_daemon_source = Path(__file__).resolve().parents[3]
        deploy_skills(real_daemon_source, temp_project)

        skills_dir = temp_project / ".claude" / "skills"
        assert (skills_dir / "hooks-daemon" / "SKILL.md").is_file()
        assert (skills_dir / "docs-qa" / "SKILL.md").is_file()

    def test_real_bundled_skills_directory_deploys_optimise(self, temp_project: Path) -> None:
        """B2 fix (v3.59.0 release): the ``config_optimisation_reminder``
        SessionStart handler ships enabled-by-default and points clients at
        ``/optimise`` — that skill must actually be bundled and deployed, not
        exist only in this repo's self-install ``.claude/skills/``."""
        real_daemon_source = Path(__file__).resolve().parents[3]
        deploy_skills(real_daemon_source, temp_project)

        optimise_dir = temp_project / ".claude" / "skills" / "optimise"
        assert (optimise_dir / "SKILL.md").is_file()
        invoke_script = optimise_dir / "invoke.sh"
        assert invoke_script.is_file()
        assert invoke_script.stat().st_mode & 0o100
