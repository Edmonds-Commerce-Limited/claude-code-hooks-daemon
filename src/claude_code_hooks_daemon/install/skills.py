"""Skill deployment system for hooks daemon.

Deploys user-facing skills to project .claude/skills/ directory.
"""

import logging
import shutil
import stat
from pathlib import Path

logger = logging.getLogger(__name__)


def deploy_skills(daemon_source: Path, project_root: Path) -> None:
    """Deploy hooks-daemon skill to user project.

    Args:
        daemon_source: Path to daemon source directory (contains src/)
        project_root: Path to user's project root

    Raises:
        FileNotFoundError: If source skills directory doesn't exist
        PermissionError: If target directory is not writable

    Example:
        >>> deploy_skills(Path("/path/to/daemon"), Path("/path/to/project"))
        # Creates /path/to/project/.claude/skills/hooks-daemon/
    """
    # Locate source skills directory
    source_skills = daemon_source / "src" / "claude_code_hooks_daemon" / "skills" / "hooks-daemon"
    if not source_skills.exists():
        # Try without src/ prefix (development mode)
        source_skills = daemon_source / "skills" / "hooks-daemon"

    if not source_skills.exists():
        raise FileNotFoundError(
            f"Skills directory not found in daemon source: {daemon_source}\n"
            f"Looked for: src/claude_code_hooks_daemon/skills/hooks-daemon/ or skills/hooks-daemon/"
        )

    # Target directory in user project
    target_skills = project_root / ".claude" / "skills" / "hooks-daemon"

    logger.info("Deploying skills from %s to %s", source_skills, target_skills)

    # Remove existing skills directory (for upgrade scenario)
    if target_skills.exists():
        logger.debug("Removing existing skills directory: %s", target_skills)
        shutil.rmtree(target_skills)

    # Copy entire skills directory tree
    shutil.copytree(source_skills, target_skills, dirs_exist_ok=False)

    # Make all scripts executable
    scripts_dir = target_skills / "scripts"
    if scripts_dir.exists():
        for script_file in scripts_dir.glob("*.sh"):
            _make_executable(script_file)
            logger.debug("Made executable: %s", script_file.name)

    logger.info("Skills deployed successfully to %s", target_skills)


def _make_executable(file_path: Path) -> None:
    """Make a file executable by adding owner execute permission.

    Args:
        file_path: Path to file to make executable
    """
    current_mode = file_path.stat().st_mode
    # Add owner execute permission (0o100)
    new_mode = current_mode | stat.S_IXUSR
    file_path.chmod(new_mode)
