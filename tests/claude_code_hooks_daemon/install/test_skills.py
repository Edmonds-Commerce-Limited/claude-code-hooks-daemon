"""Tests for skill deployment system."""

import errno
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

    def test_deploy_skills_raises_if_target_not_writable(
        self, daemon_source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """deploy_skills propagates PermissionError when the target can't be written.

        Root bypasses the filesystem's own permission bits, so `chmod(0o444)`
        no longer faults this path when the process is root — this container
        runs as root (Plan 00466 N56). Inject the fault at the write call
        itself instead: `shutil.copytree` raising `PermissionError` is exactly
        what a genuinely-unwritable target reports, whoever is running.
        """
        unwritable_project = tmp_path / "unwritable"
        unwritable_project.mkdir()

        def _raise_permission_error(*args: object, **kwargs: object) -> None:
            raise PermissionError(errno.EACCES, "Permission denied")

        monkeypatch.setattr(shutil, "copytree", _raise_permission_error)

        with pytest.raises(PermissionError):
            deploy_skills(daemon_source, unwritable_project)

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

    def test_real_bundled_skills_deploy_optimise_as_a_subcommand(self, temp_project: Path) -> None:
        """B2 fix (v3.59.0) kept, relocated by Plan 00322.

        The ``config_optimisation_reminder`` SessionStart handler ships
        enabled-by-default and points clients at the config-optimisation
        step, so that step must actually be bundled and deployed — not exist
        only in this repo's self-install ``.claude/skills/``. It now lives in
        the daemon's own namespace rather than squatting the generic
        top-level name ``optimise``, which collides with whatever else a
        project or plugin calls the same thing.
        """
        real_daemon_source = Path(__file__).resolve().parents[3]
        deploy_skills(real_daemon_source, temp_project)

        hooks_daemon_dir = temp_project / ".claude" / "skills" / "hooks-daemon"
        assert (hooks_daemon_dir / "optimise.md").is_file()
        invoke_script = hooks_daemon_dir / "scripts" / "optimise-invoke.sh"
        assert invoke_script.is_file()
        assert invoke_script.stat().st_mode & 0o100
        assert not (temp_project / ".claude" / "skills" / "optimise").exists()


class TestDeploymentDoesNotDestroyWhatItDidNotWrite:
    """Plan 00412 F-DEPL-2: the sibling twenty lines below already knows this.

    `_remove_retired_skills` refuses to delete a same-named directory that
    does not look daemon-deployed, and its docstring gives the reason:
    deleting it "would destroy project work with no backup, which is far worse
    than leaving an orphan". `_deploy_one_skill` called `rmtree` on its target
    with no provenance test at all.

    The realistic loss is not a name collision — it is a user CUSTOMISING a
    deployed skill and losing the edit silently on the next upgrade.

    Provenance cannot come from a marker here: a deployed skill is a byte
    copy of the shipped source, so there is nothing in it the daemon wrote and
    a user did not. It comes from comparing the trees instead, which also
    survives a version bump: identical means the daemon wrote it, different
    means it may not have.
    """

    def test_a_customised_skill_is_preserved_rather_than_deleted(
        self, temp_project: Path, daemon_source: Path
    ) -> None:
        deploy_skills(daemon_source, temp_project)
        deployed = temp_project / ".claude" / "skills" / "hooks-daemon" / "SKILL.md"
        deployed.write_text("# Hooks Daemon Skill\n\nMy own local notes.\n")

        deploy_skills(daemon_source, temp_project)

        backups = list((temp_project / ".claude" / "hooks-daemon-backups" / "skills").iterdir())
        assert len(backups) == 1
        assert "My own local notes." in (backups[0] / "SKILL.md").read_text()

    def test_the_skill_itself_is_still_upgraded(
        self, temp_project: Path, daemon_source: Path
    ) -> None:
        """Preserving the old copy must not mean declining the upgrade."""
        deploy_skills(daemon_source, temp_project)
        deployed = temp_project / ".claude" / "skills" / "hooks-daemon" / "SKILL.md"
        deployed.write_text("stale local edit\n")

        deploy_skills(daemon_source, temp_project)

        assert deployed.read_text() == "# Hooks Daemon Skill\n"

    def test_an_extra_file_the_user_added_is_preserved_too(
        self, temp_project: Path, daemon_source: Path
    ) -> None:
        deploy_skills(daemon_source, temp_project)
        extra = temp_project / ".claude" / "skills" / "hooks-daemon" / "my-notes.md"
        extra.write_text("notes\n")

        deploy_skills(daemon_source, temp_project)

        backups = list((temp_project / ".claude" / "hooks-daemon-backups" / "skills").iterdir())
        assert (backups[0] / "my-notes.md").read_text() == "notes\n"

    def test_an_unchanged_skill_leaves_no_backup(
        self, temp_project: Path, daemon_source: Path
    ) -> None:
        """An identical tree IS the daemon's own copy, so nothing is at risk.

        Backing up on every upgrade regardless would bury the real warnings
        under clutter, which is how a signal stops being read.
        """
        deploy_skills(daemon_source, temp_project)
        deploy_skills(daemon_source, temp_project)

        assert not (temp_project / ".claude" / "hooks-daemon-backups").exists()

    def test_the_backup_lives_outside_the_skills_root(
        self, temp_project: Path, daemon_source: Path
    ) -> None:
        """A backup inside `.claude/skills/` would register as a bogus skill.

        Claude Code discovers skills by directory, so preserving the old copy
        beside the new one would hand the user a duplicate slash command.
        """
        deploy_skills(daemon_source, temp_project)
        (temp_project / ".claude" / "skills" / "hooks-daemon" / "SKILL.md").write_text("edited\n")

        deploy_skills(daemon_source, temp_project)

        skill_dirs = [p.name for p in (temp_project / ".claude" / "skills").iterdir()]
        assert skill_dirs == ["hooks-daemon"]

    def test_two_upgrades_do_not_collide_on_one_backup_name(
        self, temp_project: Path, daemon_source: Path
    ) -> None:
        """The second rescue must not overwrite the first one."""
        skill_md = temp_project / ".claude" / "skills" / "hooks-daemon" / "SKILL.md"
        deploy_skills(daemon_source, temp_project)
        skill_md.write_text("first edit\n")
        deploy_skills(daemon_source, temp_project)
        skill_md.write_text("second edit\n")
        deploy_skills(daemon_source, temp_project)

        backups = sorted((temp_project / ".claude" / "hooks-daemon-backups" / "skills").iterdir())
        assert len(backups) == 2
        assert {(b / "SKILL.md").read_text() for b in backups} == {"first edit\n", "second edit\n"}


class TestRetiredSkillRemoval:
    """Plan 00322: a skill that stops shipping must stop being installed.

    ``deploy_skills`` only ever wrote the skills it bundles, so a renamed or
    retired skill kept working from the copy an earlier install left behind —
    an orphan no upgrade could reach, still owning its slash command.
    """

    @pytest.fixture
    def daemon_source_one_skill(self, tmp_path: Path) -> Generator[Path, None, None]:
        source = tmp_path / "daemon-source-retired"
        (source / "skills" / "hooks-daemon").mkdir(parents=True)
        (source / "skills" / "hooks-daemon" / "SKILL.md").write_text("# Hooks Daemon Skill\n")

        yield source

        if source.exists():
            shutil.rmtree(source)

    def test_removes_the_retired_standalone_optimise_skill(
        self, temp_project: Path, daemon_source_one_skill: Path
    ) -> None:
        orphan = temp_project / ".claude" / "skills" / "optimise"
        orphan.mkdir(parents=True)
        (orphan / "SKILL.md").write_text(
            "# /optimise - Configuration Optimiser Skill\n\n"
            "Analyse hooks daemon configuration and recommend improvements.\n"
        )

        deploy_skills(daemon_source_one_skill, temp_project)

        assert not orphan.exists()

    def test_leaves_a_same_named_skill_the_daemon_did_not_write(
        self, temp_project: Path, daemon_source_one_skill: Path
    ) -> None:
        """`optimise` is a generic name — the delete must check provenance.

        The whole reason this skill was renamed is that `optimise` collides
        with whatever else a project or plugin calls `optimise`. That makes an
        unconditional `rmtree` of the deployed path most dangerous in exactly
        the case the rename exists to address: deleting work the daemon never
        wrote, with no backup and only an info-level log line.
        """
        theirs = temp_project / ".claude" / "skills" / "optimise"
        theirs.mkdir(parents=True)
        (theirs / "SKILL.md").write_text(
            "# optimise\n\nRuns our image-compression pipeline over static assets.\n"
        )
        (theirs / "compress.py").write_text("# our own tooling\n")

        deploy_skills(daemon_source_one_skill, temp_project)

        assert theirs.exists(), "a project's own optimise skill was destroyed"
        assert (theirs / "compress.py").exists()

    def test_leaves_a_project_owned_skill_alone(
        self, temp_project: Path, daemon_source_one_skill: Path
    ) -> None:
        """Only NAMED retirements are removed — never 'anything not bundled'."""
        mine = temp_project / ".claude" / "skills" / "my-project-skill"
        mine.mkdir(parents=True)
        (mine / "SKILL.md").write_text("# mine\n")

        deploy_skills(daemon_source_one_skill, temp_project)

        assert (mine / "SKILL.md").read_text() == "# mine\n"

    def test_no_skills_directory_is_not_an_error(
        self, temp_project: Path, daemon_source_one_skill: Path
    ) -> None:
        deploy_skills(daemon_source_one_skill, temp_project)

        assert (temp_project / ".claude" / "skills" / "hooks-daemon" / "SKILL.md").is_file()
