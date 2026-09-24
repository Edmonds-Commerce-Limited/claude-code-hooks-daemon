"""Self-install/untracked-dir resolution rule -- ONE definition (Plan 00457).

Deliberately standard-library-only with NO ``claude_code_hooks_daemon``
imports of its own, so the venv-free ``signal`` entry point
(``daemon/signal_standalone.py``) can load this file directly by path
without dragging in anything else -- unlike ``daemon/paths.py`` (1,800+
lines, unrelated deferred third-party/package imports elsewhere in the
file) which used to be that entry point's only route to this rule and set
its Python floor purely as a side effect of code this rule never touches.

``daemon/paths.py`` and ``core/project_context.py`` both call this instead
of keeping their own copy of the check.
"""

from __future__ import annotations

from pathlib import Path

#: Relative to a project root, the daemon SOURCE tree present here means
#: this checkout self-installs (dogfoods) rather than vendoring a client
#: install under ``.claude/hooks-daemon/``.
_DAEMON_SOURCE_MARKER = ("src", "claude_code_hooks_daemon")


def is_self_install_mode(project_path: Path) -> bool:
    """Whether ``project_path`` is a self-install (dogfood) checkout.

    True iff the daemon SOURCE tree is present at the project root
    (``{project_path}/src/claude_code_hooks_daemon``).
    """
    return project_path.joinpath(*_DAEMON_SOURCE_MARKER).is_dir()


def get_untracked_dir(project_path: Path) -> Path:
    """The daemon's untracked runtime dir for an already-resolved project root.

    - Self-install mode: ``{project_path}/untracked``
    - Normal mode: ``{project_path}/.claude/hooks-daemon/untracked``

    ``project_path`` must already be the resolved project root -- this
    function does no path resolution of its own (callers that accept a
    relative path or a string, e.g. ``daemon.paths.get_untracked_dir``,
    resolve before calling this).
    """
    if is_self_install_mode(project_path):
        return project_path / "untracked"
    return project_path / ".claude" / "hooks-daemon" / "untracked"
