"""Refuse to run a test session against another checkout's source (Plan 00358).

A worktree created by the harness has no venv. An agent that symlinks
``untracked/venv`` to the main checkout's venv gets a Python whose editable
install points at ``/workspace/src`` — so ``pytest`` in the worktree imports
``claude_code_hooks_daemon`` from MAIN while running the worktree's tests. A
correct fix then fails its own tests, a green run proves nothing about the
branch, and neither failure names the cause.

The check runs once per session from ``tests/conftest.py`` and compares the
package's RESOLVED location against the repository the tests live in. It is a
hard error: a silent wrong answer is the whole defect. The nested pytest runs
that some integration tests spawn write their own ``conftest.py`` and never
load this one, so they are unaffected.
"""

from __future__ import annotations

from pathlib import Path

import claude_code_hooks_daemon

#: The one-line remedy, spelled the way `CLAUDE/Worktree.md` mandates it.
SETUP_WORKTREE_REMEDY = "./scripts/setup_worktree.sh"

_SRC_DIR = "src"
_PACKAGE_NAME = "claude_code_hooks_daemon"


class SourceTreeMismatch(RuntimeError):
    """The imported package does not live under the invoking checkout's ``src/``."""


def package_root_for(repo_root: Path) -> Path:
    """Where the package MUST resolve for a session run from ``repo_root``."""
    return repo_root.resolve() / _SRC_DIR


def assert_package_is_this_checkout(*, repo_root: Path, package_file: Path | None = None) -> None:
    """Raise :class:`SourceTreeMismatch` unless the package is under ``repo_root/src``.

    ``package_file`` defaults to the package actually imported by this
    interpreter; the parameter exists so the check itself can be tested against
    a made-up layout. Both sides are RESOLVED, because the incident shape is a
    path that looks local until its symlinks are followed.
    """
    imported = package_file if package_file is not None else Path(claude_code_hooks_daemon.__file__)
    resolved_package = imported.resolve().parent
    expected_root = package_root_for(repo_root)
    if resolved_package.parent == expected_root and resolved_package.name == _PACKAGE_NAME:
        return
    raise SourceTreeMismatch(
        "This test session is importing the package from ANOTHER checkout, so "
        "every result it produces is about that checkout's code, not this one's.\n"
        f"  imported from : {resolved_package.parent}\n"
        f"  expected under: {expected_root}\n"
        "A worktree's untracked/venv is probably a symlink to the main checkout's "
        "venv, whose editable install points at main's src/. Remedy: build this "
        f"checkout's own venv with `{SETUP_WORKTREE_REMEDY}` (never hand-link one), "
        "then re-run."
    )
