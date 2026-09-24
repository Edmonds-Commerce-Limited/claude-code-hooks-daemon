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

Acceptance probe fixtures do NOT live in the scratch directory: they have their
own root beside it, built by :func:`acceptance_path` (Plan 00422 N11). That
root needs no creation step -- a probe's ``mkdir -p`` setup, or the Write tool
itself, creates each fixture directory -- and the same ``untracked/.gitignore``
already ignores it.
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
#: reader -- see :func:`acceptance_path` for why both properties are required.
_PROJECT_DIR_VAR = "$CLAUDE_PROJECT_DIR"

#: ``*`` keeps every scratch file out of git; ``!.gitignore`` keeps the rule
#: itself tracked, so a fresh checkout arrives with the policy already in place
#: rather than depending on the daemon having run first.
SCRATCH_IGNORE_CONTENT = "*\n!.gitignore\n"


def acceptance_path(*segments: str) -> str:
    """Return an acceptance-fixture path that resolves ABSOLUTELY on any machine.

    Use for every path an acceptance probe writes, reads or cleans up -- most
    importantly in an ``AcceptanceTest.command``, which the playbook renders
    verbatim for a tester to follow.

    The root is ``ProjectPath.ACCEPTANCE_DIR``, deliberately NOT the human
    scratch directory (Plan 00422 N11). Sharing that directory meant an
    exclusion written for working notes also covered the probes' fixtures,
    and ``lint_on_edit`` stopped denying its own declared DENY inputs.

    Two constraints pull in opposite directions here, and satisfying only one
    is how both known defects happened:

    - It must be ABSOLUTE when executed. A relative ``untracked/...`` path in
      a Write instruction is denied by ``AbsolutePathHandler`` (terminal,
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
    docs as prose rather than executed.

    Args:
        *segments: Path segments below the acceptance root, e.g.
            ``("acceptance-test-lint-python", "valid.py")``.

    Returns:
        A path rooted at ``$CLAUDE_PROJECT_DIR``, e.g.
        ``$CLAUDE_PROJECT_DIR/untracked/acceptance/fixture/x.py``.
    """
    base = f"{_PROJECT_DIR_VAR}{_PATH_SEPARATOR}{ProjectPath.ACCEPTANCE_DIR}"
    return _PATH_SEPARATOR.join((base, *segments))


def project_dir_path(*segments: str) -> str:
    """Return a project-rooted path that resolves ABSOLUTELY on any machine.

    The sibling of :func:`acceptance_path`, for the handful of acceptance
    probes whose target must NOT be under ``untracked/`` --
    ``markdown_organization``'s wrong-location test being the case in point,
    since ``untracked/`` is itself an ALLOWED markdown location and a fixture
    path there would quietly stop the test exercising anything.

    Both constraints from :func:`acceptance_path` still apply and pull the same
    two ways: absolute when executed, and never naming the RENDERING machine's
    root. Resolving ``ProjectContext.project_root()`` here would satisfy only
    the first -- it bakes this checkout's ``/workspace`` into a playbook a
    client install has to follow, the defect
    ``tests/integration/test_generated_docs_are_path_agnostic.py`` exists to
    catch.

    Args:
        *segments: Path segments below the project root, e.g. ``("notes.md",)``.

    Returns:
        A path rooted at ``$CLAUDE_PROJECT_DIR``, e.g.
        ``$CLAUDE_PROJECT_DIR/notes.md``.
    """
    return _PATH_SEPARATOR.join((_PROJECT_DIR_VAR, *segments))


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
