"""NPM utility functions.

Shared utilities for detecting LLM command patterns in package.json.
Used by NpmCommandHandler and ValidateEslintOnWriteHandler to determine
whether to enforce (DENY) or advise (ALLOW) npm command usage.
"""

import json
import logging
from pathlib import Path

from claude_code_hooks_daemon.core.project_context import ProjectContext

logger = logging.getLogger(__name__)


def has_llm_commands_in_package_json(project_root: Path | None = None) -> bool:
    """Detect if package.json contains any llm: prefixed scripts.

    Reads package.json at the given project root (or ProjectContext.project_root())
    and checks if any script keys start with "llm:".

    Args:
        project_root: Path to project root directory. If None, uses ProjectContext.

    Returns:
        True if at least one llm: prefixed script exists, False otherwise.
        Returns False gracefully for missing, malformed, or non-Node.js projects.
    """
    if project_root is None:
        project_root = ProjectContext.project_root()

    package_json_path = project_root / "package.json"

    if not package_json_path.exists():
        logger.debug("No package.json found at %s", package_json_path)
        return False

    try:
        content = package_json_path.read_text(encoding="utf-8")
        data = json.loads(content)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to parse package.json at %s: %s", package_json_path, e)
        return False

    scripts = data.get("scripts")
    if not isinstance(scripts, dict):
        logger.debug("No valid scripts section in package.json at %s", package_json_path)
        return False

    return any(key.startswith("llm:") for key in scripts)
