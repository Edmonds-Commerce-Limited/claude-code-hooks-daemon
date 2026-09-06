"""Create the sanctioned scratch directory, rather than assuming it (Plan 00333).

``project_containment`` denies a write outside the repository root and points
the agent at ``untracked/scratch/``. In a project where that directory does not
exist the guidance names nothing: the guard blocks a real need and offers a path
that is not there, which is how a guard earns a reputation for obstruction and
gets switched off.

Two properties are needed, and the second is the one that is easy to forget: the
directory must EXIST, and it must be IGNORED. A scratch directory that is
tracked is worse than none at all — it puts throwaway work into review and into
history, which is the opposite of what the convention is for.

The ignore file is written only when absent. A project may already ignore
``untracked/`` from the repository root (this one does), or carry its own rules
here; overwriting them would be a silent policy change the daemon has no
business making.
"""

from __future__ import annotations

import logging
from pathlib import Path

from claude_code_hooks_daemon.constants.paths import DaemonPath, ProjectPath

logger = logging.getLogger(__name__)

#: ``*`` keeps every scratch file out of git; ``!.gitignore`` keeps the rule
#: itself tracked, so a fresh checkout arrives with the policy already in place
#: rather than depending on the daemon having run first.
SCRATCH_IGNORE_CONTENT = "*\n!.gitignore\n"


def ensure_scratch_dir(project_root: Path) -> bool:
    """Ensure ``untracked/scratch/`` exists and is ignored.

    Args:
        project_root: Repository root the scratch directory belongs to.

    Returns:
        True when something was created, False when it was already in place.
        The caller can use this to log a one-off rather than on every start.
    """
    scratch = project_root / ProjectPath.SCRATCH_DIR
    ignore_file = project_root / DaemonPath.UNTRACKED_DIR / ".gitignore"

    created = not scratch.is_dir()
    scratch.mkdir(parents=True, exist_ok=True)

    if not ignore_file.exists():
        ignore_file.write_text(SCRATCH_IGNORE_CONTENT, encoding="utf-8")
        created = True

    if created:
        logger.info("Ensured scratch directory at %s", scratch)

    return created
