"""Deploy the ``hooks-daemon`` bin wrapper into a daemon root (Plan 00192).

The wrapper is the single entry point agents and humans are told to run. It is
**daemon-owned**: overwritten on every install and upgrade, exactly like
``mkplan.bash`` and the skill scripts, so a stale copy can never outlive a fix.

It is deployed to ``{daemon_root}/bin/hooks-daemon``, which resolves to
``<project>/.claude/hooks-daemon/bin/hooks-daemon`` for a client install and
``<project>/bin/hooks-daemon`` in self-install mode. Because the wrapper
anchors to its own location rather than the caller's CWD, one deployed file
serves both modes and keeps working inside a git worktree.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Final

logger = logging.getLogger(__name__)

#: Deployed wrapper filename. Kept in lockstep with
#: ``utils.cli_command.WRAPPER_NAME``, which emits the path into guidance.
WRAPPER_NAME: Final[str] = "hooks-daemon"

#: Directory beneath the daemon root that holds the wrapper.
BIN_DIR_NAME: Final[str] = "bin"

#: Deployed output-capture helper filename (Plan 00362 Task 1.3). Kept in
#: lockstep with ``utils.cli_command.ECHD_CAPTURE_NAME``, which emits the path
#: into pipe_blocker's guidance and block reasons.
ECHD_CAPTURE_NAME: Final[str] = "echd-capture"

#: Directory holding bundled install templates.
_TEMPLATES_DIR_NAME: Final[str] = "templates"

#: Least-privilege executable mode: owner rwx, group/other rx. Never
#: world-writable — deployed tooling must not be modifiable by other users.
_WRAPPER_MODE: Final[int] = 0o755


def _template_path(name: str) -> Path:
    return Path(__file__).resolve().parent / _TEMPLATES_DIR_NAME / name


def wrapper_template_path() -> Path:
    """Return the absolute path to the bundled ``hooks-daemon`` template."""
    return _template_path(WRAPPER_NAME)


def echd_capture_template_path() -> Path:
    """Return the absolute path to the bundled ``echd-capture`` template."""
    return _template_path(ECHD_CAPTURE_NAME)


def _deploy_template(daemon_root: Path, name: str) -> Path:
    """Copy bundled template ``name`` into ``daemon_root/bin/`` as executable.

    Overwrites any existing copy and always (re)applies the execute bit — a
    non-executable file would reproduce the "command not found" confusion
    these deployments exist to eliminate.

    Raises:
        FileNotFoundError: If the bundled template is missing, which means a
            broken package build. Failing loudly beats deploying nothing.
    """
    template = _template_path(name)
    if not template.is_file():
        raise FileNotFoundError(f"Bundled {name} template missing at {template}")

    bin_dir = daemon_root / BIN_DIR_NAME
    bin_dir.mkdir(parents=True, exist_ok=True)

    target = bin_dir / name
    shutil.copyfile(template, target)
    target.chmod(_WRAPPER_MODE)

    logger.info("Deployed %s to %s (mode %o)", name, target, _WRAPPER_MODE)
    return target


def deploy_bin_wrapper(daemon_root: Path) -> Path:
    """Deploy the wrapper into ``daemon_root/bin/`` and return its path.

    Args:
        daemon_root: Directory the daemon occupies. In a client install this is
            ``<project>/.claude/hooks-daemon``; in self-install mode it is the
            project root.

    Returns:
        Absolute path to the deployed wrapper.
    """
    return _deploy_template(daemon_root, WRAPPER_NAME)


def deploy_echd_capture(daemon_root: Path) -> Path:
    """Deploy the ``echd-capture`` helper beside the wrapper (Plan 00362 Task 1.3).

    The helper is what ``pipe_blocker``'s guidance and block reasons name as
    the alternative to ``| tail``. Deploying it to the same stable ``bin/``
    the wrapper uses, on every install and upgrade, is what lets that guidance
    name a path that exists — rather than a bare command that is on nobody's
    ``PATH``.

    Args:
        daemon_root: Same meaning as for :func:`deploy_bin_wrapper`.

    Returns:
        Absolute path to the deployed helper.
    """
    return _deploy_template(daemon_root, ECHD_CAPTURE_NAME)
