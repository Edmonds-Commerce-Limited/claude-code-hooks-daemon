"""Resolve the runnable daemon-CLI command for the current install mode.

Plan 00192. Agent-facing guidance previously emitted
``$PYTHON -m claude_code_hooks_daemon.daemon.cli <subcommand>``. That line is
unrunnable in the shell an agent actually uses:

- ``$PYTHON`` is only ever set inside the process scope of the skill wrapper
  scripts that source ``_resolve-venv.sh``. It is deliberately NOT exported into
  the hook environment either — ``init.sh`` resolves into ``PYTHON_CMD`` and
  documents that the hot path stays on the system ``python3``.
- The PATH ``python3`` cannot import the package, because the daemon venv is
  built with ``include-system-site-packages = false``.

So the documented command expanded to ``-m claude_code_hooks_daemon.daemon.cli
…`` and bash reported ``-m: command not found`` (exit 127) — an error naming
neither Python, nor the venv, nor the daemon. Agents concluded the package was
not installed and attempted to "repair" a working installation.

The daemon knows its own layout, so it emits an ABSOLUTE path to a deployed
wrapper instead of asking the reader to supply an interpreter. This mirrors the
pattern already proven by ``pipe_blocker``, which prints the resolved absolute
path to ``echd-capture`` rather than a bare command name.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.core.project_context import ProjectContext

#: Name of the deployed wrapper script. Deliberately short and stable — it is
#: read by agents and typed by humans, and must not churn when the venv
#: fingerprint changes.
WRAPPER_NAME: Final[str] = "hooks-daemon"

#: Directory (relative to the daemon root) the wrapper is deployed into.
BIN_DIR_NAME: Final[str] = "bin"

#: Path segments from a CLIENT project root to the daemon clone. In client
#: installs the daemon lives here; in self-install mode the daemon root IS the
#: project root.
_CLIENT_DAEMON_SEGMENTS: Final[tuple[str, ...]] = (".claude", "hooks-daemon")

#: Separator used when joining the wrapper path with its arguments.
_ARG_SEPARATOR: Final[str] = " "


def daemon_root() -> Path:
    """Return the directory the daemon itself occupies.

    Self-install mode runs the daemon from the project root. A client install
    keeps it in ``.claude/hooks-daemon/``. The wrapper is deployed inside the
    daemon root in BOTH cases, so a client's own repository root never gains a
    daemon-owned ``bin/`` directory.
    """
    project_root = ProjectContext.project_root()
    if ProjectContext.self_install_mode():
        return project_root
    return project_root.joinpath(*_CLIENT_DAEMON_SEGMENTS)


def daemon_bin_path() -> Path:
    """Return the absolute path to the deployed daemon-CLI wrapper."""
    return daemon_root() / BIN_DIR_NAME / WRAPPER_NAME


def _fallback_relative_path() -> str:
    """Wrapper path relative to the project root.

    Used only when :class:`ProjectContext` is not initialised — unit tests, and
    any tooling that renders handler guidance outside a running daemon.

    This is a deliberate, narrow exception to FAIL FAST. The alternative is
    raising from a *documentation-string builder*, which would take a caller
    down over cosmetics. The relative path is still runnable from the project
    root — the documented working directory for every daemon command — and is
    strictly better than emitting a variable that is never set.
    """
    return "/".join((*_CLIENT_DAEMON_SEGMENTS, BIN_DIR_NAME, WRAPPER_NAME))


def daemon_cli_command(*args: str) -> str:
    """Return a copy-paste runnable daemon-CLI invocation.

    Args:
        *args: Subcommand and flags, e.g. ``("plan-qa", "--sweep")``.

    Returns:
        An absolute command string that runs as printed, such as
        ``/project/.claude/hooks-daemon/bin/hooks-daemon plan-qa --sweep``.
        Never contains a shell variable.
    """
    try:
        wrapper = str(daemon_bin_path())
    except RuntimeError:
        # ProjectContext not initialised — see _fallback_relative_path().
        wrapper = _fallback_relative_path()
    parts: tuple[str, ...] = (wrapper, *args)
    return _ARG_SEPARATOR.join(parts)
