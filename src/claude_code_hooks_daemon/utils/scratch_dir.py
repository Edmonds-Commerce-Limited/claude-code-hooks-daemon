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

#: Separator for assembled path strings. These are agent-facing text, not
#: filesystem operations, so they are joined rather than built with Path --
#: which would render backslashes if this ever ran on Windows.
_PATH_SEPARATOR = "/"

#: Claude Code sets this in the hook environment. Used UNEXPANDED so the text
#: stays identical on every machine while still resolving absolutely for the
#: reader -- see :func:`scratch_path` for why both properties are required.
_PROJECT_DIR_VAR = "$CLAUDE_PROJECT_DIR"

#: ``*`` keeps every scratch file out of git; ``!.gitignore`` keeps the rule
#: itself tracked, so a fresh checkout arrives with the policy already in place
#: rather than depending on the daemon having run first.
SCRATCH_IGNORE_CONTENT = "*\n!.gitignore\n"


def scratch_path(*segments: str) -> str:
    """Return a scratch path that resolves ABSOLUTELY on whatever machine runs it.

    Use for any scratch path quoted in agent-facing text — most importantly an
    ``AcceptanceTest.command``, which the playbook renders verbatim for a
    tester to follow.

    Two constraints pull in opposite directions here, and satisfying only one
    is how both known defects happened:

    - It must be ABSOLUTE when executed. A relative ``untracked/scratch/x.py``
      in a Write instruction is denied by ``AbsolutePathHandler`` (terminal,
      priority 12) before the handler under test is consulted, so the test
      observes the wrong rule and can never pass. The original ``/tmp``
      spelling worked because it was absolute, not merely because it existed.
    - It must NOT name the RENDERING machine's root. The playbook is followed
      in client installs too, so a baked-in ``/workspace/...`` instructs a
      tester to write to a path outside their own project — pinned by
      ``tests/integration/test_generated_docs_are_path_agnostic.py``.

    ``$CLAUDE_PROJECT_DIR`` satisfies both: it is machine-independent as text
    and expands to the reader's own project root, which is the convention the
    surrounding acceptance tests already use (``markdown_organization``,
    ``sed_blocker``).

    Do NOT use this in ``get_claude_md()``. That text is committed into tracked
    docs as prose rather than executed, so it names the plain relative
    ``ProjectPath.SCRATCH_DIR``.

    Args:
        *segments: Path segments below the scratch directory, e.g.
            ``("acceptance-test-lint-python", "valid.py")``.

    Returns:
        A path rooted at ``$CLAUDE_PROJECT_DIR``, e.g.
        ``$CLAUDE_PROJECT_DIR/untracked/scratch/fixture/x.py``.
    """
    base = f"{_PROJECT_DIR_VAR}{_PATH_SEPARATOR}{ProjectPath.SCRATCH_DIR}"
    return _PATH_SEPARATOR.join((base, *segments))


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
