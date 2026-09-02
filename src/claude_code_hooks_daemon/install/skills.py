"""Skill deployment system for hooks daemon.

Deploys ALL daemon-shipped skills (Plan 00284 added ``docs-qa`` alongside the
original ``hooks-daemon`` skill) to a project's ``.claude/skills/`` directory
— one subdirectory per skill, mirroring the bundled ``skills/`` layout.
"""

import logging
import shutil
import stat
from pathlib import Path
from typing import Final

logger = logging.getLogger(__name__)

#: Skills this daemon used to deploy and no longer does. Deploying only ever
#: WROTE the bundled skills, so a retired one kept working from the copy an
#: earlier install left behind — an orphan no upgrade could reach, still
#: owning its slash command. Named retirements only: never "anything not
#: bundled", which would delete a project's own skills (Plan 00322).
#:
#: ``optimise`` was retired into the ``hooks-daemon`` skill as the
#: ``optimise`` subcommand — a top-level name that generic collides with
#: whatever else a project or plugin calls it.
_RETIRED_SKILLS: Final[tuple[str, ...]] = ("optimise",)


def _skills_source_root(daemon_source: Path) -> Path:
    """Locate the bundled ``skills/`` directory, containing one subdir per skill."""
    source_skills_root = daemon_source / "src" / "claude_code_hooks_daemon" / "skills"
    if not source_skills_root.exists():
        # Try without src/ prefix (development mode)
        source_skills_root = daemon_source / "skills"

    if not source_skills_root.exists():
        raise FileNotFoundError(
            f"Skills directory not found in daemon source: {daemon_source}\n"
            f"Looked for: src/claude_code_hooks_daemon/skills/ or skills/"
        )
    return source_skills_root


def _deploy_one_skill(source_skill_dir: Path, project_root: Path) -> None:
    """Deploy one skill directory tree to ``.claude/skills/<name>/``."""
    target_skill_dir = project_root / ".claude" / "skills" / source_skill_dir.name

    logger.info("Deploying skill from %s to %s", source_skill_dir, target_skill_dir)

    # Remove existing skill directory (for upgrade scenario)
    if target_skill_dir.exists():
        logger.debug("Removing existing skill directory: %s", target_skill_dir)
        shutil.rmtree(target_skill_dir)

    # Copy entire skill directory tree
    shutil.copytree(source_skill_dir, target_skill_dir, dirs_exist_ok=False)

    # Make all scripts executable
    scripts_dir = target_skill_dir / "scripts"
    if scripts_dir.exists():
        for script_file in scripts_dir.glob("*.sh"):
            _make_executable(script_file)
            logger.debug("Made executable: %s", script_file.name)

    logger.info("Skill deployed successfully to %s", target_skill_dir)


def deploy_skills(daemon_source: Path, project_root: Path) -> None:
    """Deploy every daemon-shipped skill to the user's project.

    Args:
        daemon_source: Path to daemon source directory (contains src/)
        project_root: Path to user's project root

    Raises:
        FileNotFoundError: If the bundled skills directory doesn't exist
        PermissionError: If target directory is not writable

    Example:
        >>> deploy_skills(Path("/path/to/daemon"), Path("/path/to/project"))
        # Creates /path/to/project/.claude/skills/hooks-daemon/,
        # /path/to/project/.claude/skills/docs-qa/, etc. — one per bundled skill.
    """
    source_skills_root = _skills_source_root(daemon_source)
    skill_dirs = sorted(p for p in source_skills_root.iterdir() if p.is_dir())
    for source_skill_dir in skill_dirs:
        _deploy_one_skill(source_skill_dir, project_root)
    _remove_retired_skills(project_root)


def _remove_retired_skills(project_root: Path) -> None:
    """Delete deployed copies of skills this daemon no longer ships."""
    skills_root = project_root / ".claude" / "skills"
    for retired in _RETIRED_SKILLS:
        orphan = skills_root / retired
        if not orphan.is_dir():
            continue
        logger.info("Removing retired skill directory: %s", orphan)
        shutil.rmtree(orphan)


def _make_executable(file_path: Path) -> None:
    """Make a file executable by adding owner execute permission.

    Args:
        file_path: Path to file to make executable
    """
    current_mode = file_path.stat().st_mode
    # Add owner execute permission (0o100)
    new_mode = current_mode | stat.S_IXUSR
    file_path.chmod(new_mode)
