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

Two builders, deliberately (Plan 00244)
---------------------------------------

:func:`daemon_cli_command` and :func:`daemon_cli_command_for_docs` look nearly
identical and are NOT interchangeable. They serve audiences with opposite
requirements, so collapsing them into one reintroduces a shipped bug — which
direction depends on which one survives.

===============  ==========================  ==============================
Destination      Audience                    Correct form
===============  ==========================  ==============================
Block reasons,   the live agent, on THIS     **absolute** — runnable from
advisory context machine; never written      any cwd (Plan 00192)
Generated docs   every reader of every       **path-agnostic** — the file is
(``CLAUDE.md``,  clone, on every machine     tracked, committed and shared
``HOOKS-DAEMON``)                            (Plan 00244)
===============  ==========================  ==============================

``ClaudeMdInjector`` writes each handler's ``get_claude_md()`` verbatim into the
tracked ``<hooksdaemon>`` block and auto-commits it. An absolute path there
publishes the author's home directory, is wrong in every other clone, and
rewrites itself per machine so the file conflicts on merge.

Self-install mode hides this: the project root is ``/workspace``, so our own
committed artifacts render an absolute path that happens to be identical for
everyone. ``tests/integration/test_generated_docs_are_path_agnostic.py`` renders
in CLIENT mode for exactly that reason, and is the guard that keeps both forms
honest.
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

#: Path segments from a SELF-INSTALL project root to the daemon clone: none, by
#: definition — the daemon root and the project root are the same directory.
_SELF_INSTALL_DAEMON_SEGMENTS: Final[tuple[str, ...]] = ()

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


def _relative_wrapper_path(daemon_segments: tuple[str, ...]) -> str:
    """Join daemon-root segments with the wrapper's own location.

    Sole definition of what a project-root-relative wrapper path looks like, so
    the uninitialised fallback and the documentation builder cannot drift apart.
    """
    return "/".join((*daemon_segments, BIN_DIR_NAME, WRAPPER_NAME))


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
    return _relative_wrapper_path(_CLIENT_DAEMON_SEGMENTS)


def _docs_daemon_segments() -> tuple[str, ...]:
    """Daemon-root segments relative to the project root, for documentation.

    Client form is the degraded default when :class:`ProjectContext` is not
    initialised: it is what the overwhelming majority of readers have, and a
    path-builder must never take its caller down over cosmetics.
    """
    try:
        self_install = ProjectContext.self_install_mode()
    except RuntimeError:
        return _CLIENT_DAEMON_SEGMENTS
    return _SELF_INSTALL_DAEMON_SEGMENTS if self_install else _CLIENT_DAEMON_SEGMENTS


def daemon_path(*segments: str) -> str:
    """Return a reader-resolvable path to something inside the daemon's tree.

    Use for any daemon-owned path quoted in agent- or user-facing text — docs,
    guides, error messages. A bare relative path like ``CLAUDE/UPGRADES/`` is
    wrong in a CLIENT install, where the daemon lives at
    ``.claude/hooks-daemon/`` and no such directory exists at the project root.

    Args:
        *segments: Path segments below the daemon root, e.g.
            ``("CLAUDE", "UPGRADES")``.

    Returns:
        An absolute path, or the client-relative path when
        :class:`ProjectContext` is not initialised. Never a bare project-root
        relative path.
    """
    try:
        base: tuple[str, ...] = (str(daemon_root()),)
    except RuntimeError:
        # ProjectContext not initialised — see _fallback_relative_path(). A
        # path-builder must never take its caller down over cosmetics.
        base = _CLIENT_DAEMON_SEGMENTS
    return "/".join((*base, *segments))


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


def daemon_cli_command_for_docs(*args: str) -> str:
    """Return a daemon-CLI invocation safe to write into a TRACKED file.

    Use this — never :func:`daemon_cli_command` — for anything that ends up in
    generated documentation: every ``get_claude_md()`` body, and the docs
    generator. Those strings are committed and read by every clone, so a path
    resolved against the generating machine leaks the author's home directory,
    names a directory no other clone has, and rewrites itself per machine.

    The result stays copy-paste runnable from the project root, which is the
    documented working directory for every daemon command, and never contains a
    shell variable (Plan 00192's contract holds for both builders).

    Args:
        *args: Subcommand and flags, e.g. ``("plan-qa", "--sweep")``.

    Returns:
        A project-root-relative command string, such as
        ``.claude/hooks-daemon/bin/hooks-daemon plan-qa --sweep`` in a client
        install, or ``bin/hooks-daemon plan-qa --sweep`` in self-install mode.
    """
    parts: tuple[str, ...] = (_relative_wrapper_path(_docs_daemon_segments()), *args)
    return _ARG_SEPARATOR.join(parts)
