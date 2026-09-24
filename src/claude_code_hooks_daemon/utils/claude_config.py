"""Where Claude Code keeps its own configuration (Plan 00468, audit G13).

Claude Code keeps its user settings, user agents and skills, session
transcripts and installed plugins under ``$CLAUDE_CONFIG_DIR`` when that is
set, else ``~/.claude``. Every daemon component that looks there asks this
module, so no two of them can disagree about where the directory is.

**Whose environment.** Called inside the daemon, this reads the DAEMON's
environment, which is fixed when the daemon starts. A session started with a
different ``CLAUDE_CONFIG_DIR`` or ``HOME`` is not visible here: the hook
payload does not carry either value.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Final

#: The environment variable Claude Code reads for its config directory.
CLAUDE_CONFIG_DIR_ENV: Final[str] = "CLAUDE_CONFIG_DIR"

#: The documented default, relative to the home directory.
DEFAULT_CLAUDE_CONFIG_DIRNAME: Final[str] = ".claude"


def claude_config_dir(
    *, environ: Mapping[str, str] | None = None, home: Path | None = None
) -> Path:
    """Claude Code's config directory: ``$CLAUDE_CONFIG_DIR``, else ``~/.claude``.

    Args:
        environ: The environment to read; defaults to the process environment.
        home: The home directory for the default; defaults to
            :meth:`Path.home`. Tests pass both so nothing real is consulted.

    Returns:
        The directory, unresolved: a symlinked home stays a symlink, so a
        caller that compares paths must resolve both sides itself.
    """
    source = os.environ if environ is None else environ
    configured = source.get(CLAUDE_CONFIG_DIR_ENV)
    base_home = home if home is not None else Path.home()
    if configured:
        if configured == "~" or configured.startswith("~/"):
            return base_home / configured[2:]
        return Path(configured).expanduser()
    return base_home / DEFAULT_CLAUDE_CONFIG_DIRNAME


def config_dir_within(project_root: Path, *, config_dir: Path | None = None) -> str | None:
    """The config dir as a project-relative POSIX path, when it lies inside.

    Under ccy the Claude home is a symlink into the project tree, so both
    paths are resolved before comparing. A config dir equal to the project
    root is refused: every project file would then count as config.

    Args:
        project_root: The project to test against.
        config_dir: Defaults to :func:`claude_config_dir`.

    Returns:
        e.g. ``".claude/ccy"``, or None when the directory is elsewhere.
    """
    directory = config_dir if config_dir is not None else claude_config_dir()
    resolved_root = project_root.resolve()
    resolved_dir = directory.resolve()
    if resolved_dir == resolved_root or not resolved_dir.is_relative_to(resolved_root):
        return None
    return resolved_dir.relative_to(resolved_root).as_posix()
