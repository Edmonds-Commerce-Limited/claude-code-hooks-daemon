"""Process verification utilities for daemon enforcement.

This module provides system-wide daemon process detection, particularly useful
in container environments for single-process enforcement. Signalling a daemon
it finds is ``utils.safe_signal``'s job, which re-proves the pid first.
"""

import argparse
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Final, NoReturn

import psutil

from claude_code_hooks_daemon.daemon.paths import is_self_install_mode, prospective_socket_path

logger = logging.getLogger(__name__)

# The CLI module that, given a launch subcommand, becomes the daemon server.
# Matching requires this exact module token PLUS a launch subcommand (below) so
# that transient CLI helpers (status/stop/logs/...) and the per-event hook
# forwarders (the bash wrappers' python3 socket transport) are never mistaken
# for a daemon server. Public (no leading underscore): cli.py's own ``main()``
# re-execs itself via ``python -m {DAEMON_CLI_MODULE} ...`` (Plan 00466 N59
# gate fix) and imports this rather than duplicating the literal.
DAEMON_CLI_MODULE: Final = "claude_code_hooks_daemon.daemon.cli"

# The ONLY subcommands that daemonize. Daemonization (os.fork x2, os.setsid,
# HooksDaemon(...), asyncio.run(daemon.start())) lives solely in cmd_start,
# reachable only from the ``start`` subcommand and from cmd_restart (the
# ``restart`` subcommand), which calls cmd_start. os.fork does not rewrite argv,
# so a start-launched daemon's cmdline carries ``start`` and a restart-launched
# one carries ``restart``. This allowlist is therefore provably complete — every
# real daemon server is matched (zero false negatives). If a future subcommand
# daemonizes, add it here; a unit test guards this tuple.
_DAEMON_LAUNCH_SUBCOMMANDS = ("start", "restart")

# Command-line flag that explicitly names a daemon's project root.
_PROJECT_ROOT_FLAG = "--project-root"

# Env var a daemon server records in its OWN environment at startup, naming
# the project root ``cmd_start`` actually resolved (Plan 00466 N59 gate fix).
# ``cli.main`` launches every ``start``/``restart`` naming no root again with
# the flag and this set. Public (no leading underscore): ``cli.main`` sets
# it, this module only reads it.
PROJECT_ROOT_ENV_VAR = "CLAUDE_HOOKS_DAEMON_PROJECT_ROOT"

# Env var through which a launcher that names the root resolved hands the CLI
# its caller's logical root, links unresolved (round 9b): the spelling a
# daemon an older ``init.sh`` started carries. ``root_names_project`` takes it
# only as a spelling of the caller's own tree.
CALLER_ROOT_ENV_VAR = "CLAUDE_HOOKS_DAEMON_CALLER_ROOT"

# Where a client install keeps the daemon, below the project it serves.
_CLIENT_DAEMON_DIR = (".claude", "hooks-daemon")

# The kernel's process tables. ``/proc/<pid>/net/unix`` lists the unix
# sockets of the network namespace ``<pid>`` is in, one per line in fixed
# columns: Num RefCount Protocol Flags Type St Inode Path. Only the last,
# the path a socket is bound to, may hold whitespace, and a socket bound to
# none has no such column.
_PROC = Path("/proc")
_UNIX_TABLE_INODE_FIELD = 6
_UNIX_TABLE_FIELDS_WITH_PATH = 8
# What a descriptor that is a socket links to: ``socket:[<inode>]``.
_SOCKET_LINK_PREFIX = "socket:["
_SOCKET_LINK_SUFFIX = "]"


def add_global_arguments(parser: argparse.ArgumentParser) -> None:
    """Add the options ``cli.main`` accepts before its subcommand.

    One definition, so that a daemon's command line is read here exactly as
    the parser that launched it read it (Plan 00466 N203).

    The root has a SEPARATE dest, reconciled after parsing by
    ``cli.apply_global_project_root`` (Plan 00374). Sharing ``project_root``
    with the subparsers that declare their own lost this value: argparse
    writes a subparser's defaults into the namespace whether or not the flag
    was supplied, so the subparser's None overwrote the anchor
    ``bin/hooks-daemon`` passes ahead of the subcommand.
    """
    parser.add_argument(
        _PROJECT_ROOT_FLAG,
        dest="global_project_root",
        type=Path,
        help="Override project root path (auto-detected by default)",
    )
    parser.add_argument(
        "--pid-file",
        type=Path,
        help="Explicit PID file path (overrides auto-discovery)",
    )
    parser.add_argument(
        "--socket",
        type=Path,
        help="Explicit socket path (overrides auto-discovery)",
    )


class _UnreadableLaunch(Exception):
    """A daemon's arguments cannot be read as its own parser read them."""


class _LaunchParser(argparse.ArgumentParser):
    """``cli.main``'s global options, raising where argparse would exit."""

    def error(self, message: str) -> NoReturn:
        raise _UnreadableLaunch(message)

    def exit(self, status: int = 0, message: str | None = None) -> NoReturn:
        raise _UnreadableLaunch(message or f"its parser would exit with {status}")


def _launch_parser() -> _LaunchParser:
    """A parser that reads a daemon launch as ``cli.main``'s does.

    It carries the same option strings, so it resolves the same repeats,
    ``=`` forms and abbreviations. ``cli.main``'s help option is declared
    here as a flag rather than an action that prints; the subcommand and
    anything after it stand in for its subparsers, and ``start`` and
    ``restart`` accept no arguments of their own.
    """
    parser = _LaunchParser(add_help=False)
    parser.add_argument("-h", "--help", action="store_true")
    add_global_arguments(parser)
    parser.add_argument("command")
    parser.add_argument("after_command", nargs=argparse.REMAINDER)
    return parser


def find_all_daemon_processes(
    project_root: str | Path | None = None, *, logical_root: str | None = None
) -> list[int]:
    """Find daemon processes running on the system.

    Searches for processes with 'claude_code_hooks_daemon' in their name or command line.

    Args:
        project_root: When provided, the search is scoped to daemons whose own
            project root names this path, as :func:`root_names_project` matches
            it. Daemons serving a different project root — and daemons whose
            project root cannot be positively determined — are excluded. When
            ``None`` the search is system-wide (legacy behaviour).
        logical_root: The caller's unresolved spelling of ``project_root``,
            which a daemon an older version started through a link names
            (review 10, R10-2).

    Returns:
        List of PIDs for matching daemon processes (excluding current process).

    Note:
        - Ignores processes that raise AccessDenied or NoSuchProcess errors
        - Excludes the current process from results
        - Case-sensitive matching for 'claude_code_hooks_daemon'
        - Project-root scoping NEVER kills a daemon we cannot attribute to the
          requested project (fail-safe against cross-project termination).
    """
    daemon_pids: list[int] = []
    current_pid = os.getpid()

    for proc in psutil.process_iter():
        try:
            pid = proc.pid

            # Skip current process
            if pid == current_pid:
                continue

            # Matching is cmdline-only: a daemon server is identified by the cli
            # module token plus a launch subcommand. cmdline() also raises
            # NoSuchProcess/AccessDenied for inaccessible processes, which the
            # except below skips.
            cmdline = proc.cmdline()
            if not _is_daemon_server_process(cmdline):
                continue

            # Scope to our own project root when requested. A daemon whose root
            # cannot be determined is left alone — never terminated.
            if project_root is not None:
                proc_root = _extract_project_root(proc)
                if proc_root is None or not root_names_project(
                    proc_root, project_root, logical_root=logical_root
                ):
                    continue

            daemon_pids.append(pid)

        except (psutil.NoSuchProcess, psutil.AccessDenied):
            # Process disappeared or we don't have permission - skip it
            continue

    return daemon_pids


def _normalize_root(root: str | Path) -> str:
    """Normalise a project-root path for cross-process string comparison.

    Uses ``os.path.normpath`` only — never ``resolve()`` — because daemon
    processes may reference paths inside other mount namespaces (e.g. a
    container's ``/workspace``) that do not exist on this side of the boundary.
    """
    return os.path.normpath(str(root))


def root_names_project(
    process_root: str, project_root: Path | str, *, logical_root: str | None = None
) -> bool:
    """True when a daemon's normalised root text names ``project_root``.

    The daemon's text is never resolved (review 9, DR-1): a link it named
    may have been re-pointed since it started, and a path from another
    mount namespace resolves here to whatever this side holds there. The
    caller's own root is a path in this namespace, so it may be matched as
    given or resolved: a daemon started through a link is proven for a
    caller naming that link, and one naming the real tree for a caller
    naming it through a link.

    ``logical_root`` is the caller's own spelling of its root before its
    launcher resolved it (round 9b): a daemon an older ``init.sh`` started
    through a link names that. It is a candidate only when it is absolute,
    in normal form, and resolves to where ``project_root`` does; anything
    else names some other tree, or none, and proves nothing.
    """
    caller = Path(project_root).absolute()
    resolved = os.path.realpath(caller)
    candidates = {_normalize_root(caller), resolved}
    if (
        logical_root is not None
        and Path(logical_root).is_absolute()
        and logical_root == _normalize_root(logical_root)
        and os.path.realpath(logical_root) == resolved
    ):
        candidates.add(logical_root)
    return process_root in candidates


def _extract_project_root(proc: psutil.Process) -> str | None:
    """Derive a daemon process's project root, most authoritative source first.

    Resolution order (:func:`_attributed_root`):
        1. An explicit ``--project-root PATH`` (or ``--project-root=PATH``) flag
           on the command line.
        2. The ``CLAUDE_HOOKS_DAEMON_PROJECT_ROOT`` env var the daemon recorded
           in its own environment at startup (see ``PROJECT_ROOT_ENV_VAR``).
        3. The project whose natural socket it listens on.

    Returns:
        The normalised project root, or ``None`` when it cannot be determined
        by any of the above (including a process that has since disappeared).
    """
    try:
        cmdline = proc.cmdline()
    except (psutil.NoSuchProcess, psutil.AccessDenied) as exc:
        logger.debug("cmdline unavailable for pid %s (%s): %s", proc.pid, type(exc).__name__, exc)
        cmdline = []
    return _attributed_root(proc, cmdline).root


@dataclass(frozen=True)
class RootProof:
    """Which project a pid's daemon serves, or why that cannot be proven.

    Exactly one of ``root`` and ``refusal`` is set. ``source`` says where the
    root came from, so a caller refusing on a mismatch can say how the pid was
    attributed.
    """

    root: str | None
    refusal: str | None
    source: str | None = None


_FLAG_SOURCE: Final = f"its {_PROJECT_ROOT_FLAG} flag"
_ENV_SOURCE: Final = f"its {PROJECT_ROOT_ENV_VAR} environment variable"
_SOCKET_SOURCE: Final = "the socket it listens on"
_NO_SOURCE: Final = "names no project, nor do its environment or a socket it listens on"


def _attributed_root(proc: psutil.Process, cmdline: list[str]) -> RootProof:
    """The normalised root ``proc`` serves and where it came from.

    Its interpreter's venv is no source (Plan 00466 round 6, Sh-1): it names
    only the install the daemon runs from, which a worktree can share, while
    a daemon naming no root serves whatever its working directory found.

    A command line its own parser could not have read as it is read here
    proves nothing, and no later source is consulted for it (N203).
    """
    try:
        flag_root = _root_from_flag(cmdline)
    except _UnreadableLaunch as unreadable:
        return RootProof(
            root=None,
            refusal=f"its command line cannot be read as its own parser read it: {unreadable}",
        )
    if flag_root is not None:
        return RootProof(root=flag_root, refusal=None, source=_FLAG_SOURCE)
    env_root = _root_from_environ(proc)
    if env_root is not None:
        return RootProof(root=env_root, refusal=None, source=_ENV_SOURCE)
    socket_root = _root_from_listening_socket(proc)
    if socket_root is not None:
        return RootProof(root=socket_root, refusal=None, source=_SOCKET_SOURCE)
    return RootProof(root=None, refusal=f"its command line {_NO_SOURCE}")


def _root_from_environ(proc: psutil.Process) -> str | None:
    """Extract the project root a daemon recorded in its own environment.

    ``proc.environ()`` returns a real ``dict`` for an actual process; anything
    else (unreadable, or a test double that has not modelled it) is treated as
    "no answer" rather than misread.
    """
    try:
        env = proc.environ()
    except (psutil.NoSuchProcess, psutil.AccessDenied, OSError) as exc:
        logger.debug("environ unavailable for pid %s (%s): %s", proc.pid, type(exc).__name__, exc)
        env = None
    if env is None or not isinstance(env, dict):
        return None
    value = env.get(PROJECT_ROOT_ENV_VAR)
    if not value:
        return None
    return _normalize_root(value)


def _root_from_flag(cmdline: list[str]) -> str | None:
    """The root a daemon's ``--project-root`` names, read as ``cli.main`` read it.

    argparse keeps the LAST of several and accepts ``--project-root=PATH``
    and any unambiguous abbreviation, and ``bin/hooks-daemon`` relies on the
    first: it puts its own root ahead of the caller's (Plan 00466 N203).

    Returns:
        The normalised root, or None when the launch names none.

    Raises:
        _UnreadableLaunch: The arguments are not a ``start``/``restart`` its
            parser accepts, or name a relative root, which was resolved
            against a working directory the daemon has since left, or a
            root that is not its own normal form. ``cmd_start`` serves
            ``Path.resolve()``, which follows a link before it meets ``..``,
            where ``normpath`` collapses ``..`` first: the daemon launched
            with ``/var/run/../workspace`` serves ``/workspace``, not
            ``/var/workspace`` (review 8, S8-1).
    """
    module_index = _cli_module_index(cmdline)
    if module_index is None:
        raise _UnreadableLaunch(f"{DAEMON_CLI_MODULE} is not among its arguments")
    parsed = _launch_parser().parse_args(cmdline[module_index + 1 :])
    if parsed.help or parsed.after_command or parsed.command not in _DAEMON_LAUNCH_SUBCOMMANDS:
        raise _UnreadableLaunch(
            f"its parser accepts no {parsed.command!r} launch with these arguments"
        )
    root: Path | None = parsed.global_project_root
    if root is None:
        return None
    if not root.is_absolute():
        raise _UnreadableLaunch(f"{_PROJECT_ROOT_FLAG} {str(root)!r} is relative")
    if os.pardir in root.parts or str(root) != _normalize_root(root):
        raise _UnreadableLaunch(f"{_PROJECT_ROOT_FLAG} {str(root)!r} is not its own normal form")
    return str(root)


def _project_of_socket(path: Path) -> str | None:
    """The project whose daemon binds ``path`` as its natural socket, or None.

    A client install's socket is ``{root}/.claude/hooks-daemon/untracked/...``
    and a self-install's ``{root}/untracked/...``. A client install's daemon
    clone is itself a self-install tree, but ``get_project_path`` never
    serves it, so a socket there belongs to the project holding the clone.
    """
    untracked = path.parent
    if untracked.name != "untracked":
        return None
    candidate = untracked.parent
    if (candidate.parent.name, candidate.name) == _CLIENT_DAEMON_DIR:
        candidate = candidate.parent.parent
    natural = prospective_socket_path(candidate, self_install=is_self_install_mode(candidate))
    return _normalize_root(candidate) if natural == path else None


def bound_socket_paths(pid: int) -> list[str]:
    """The paths of the unix sockets ``pid`` holds that are bound to one.

    A server's socket, and each connection it has accepted, carries the
    path it is bound to; a client's socket, and each end of a socketpair,
    carries none. Read from the table of ``pid``'s own network namespace by
    its fixed columns (review 10, R10-1): psutil reads the reader's own
    namespace's table, and takes a path only from a line of exactly eight
    fields, so a path holding whitespace read as no path at all.

    Raises:
        OSError: ``pid``'s descriptors or its namespace's table cannot be
            read, so which sockets it has bound is unknown.
    """
    inodes: set[str] = set()
    for descriptor in (_PROC / str(pid) / "fd").iterdir():
        try:
            link = str(descriptor.readlink())
        except FileNotFoundError:
            logger.debug("%s closed since it was listed, so it is no socket held", descriptor)
            continue
        if link.startswith(_SOCKET_LINK_PREFIX) and link.endswith(_SOCKET_LINK_SUFFIX):
            inodes.add(link[len(_SOCKET_LINK_PREFIX) : -len(_SOCKET_LINK_SUFFIX)])
    table = (_PROC / str(pid) / "net" / "unix").read_text(errors="surrogateescape")
    paths: list[str] = []
    for line in table.splitlines()[1:]:
        fields = line.split(maxsplit=_UNIX_TABLE_FIELDS_WITH_PATH - 1)
        if (
            len(fields) == _UNIX_TABLE_FIELDS_WITH_PATH
            and fields[0].endswith(":")
            and fields[_UNIX_TABLE_INODE_FIELD] in inodes
        ):
            paths.append(fields[-1])
    return paths


def _root_from_listening_socket(process: psutil.Process) -> str | None:
    """The project whose natural socket ``process`` has bound, or None.

    A daemon started without ``--project-root`` serves the project its
    working directory finds, and leaves that directory at once
    (``os.chdir("/")``). Its interpreter's venv names only the install it
    runs from, which a worktree can share (Plan 00466 round 6, Sh-1). The
    socket it binds names the project it serves. A socket anywhere else (an
    override, the AF_UNIX-overflow fallback), or those of two projects,
    prove nothing.
    """
    try:
        paths = bound_socket_paths(process.pid)
    except OSError as exc:
        logger.debug(
            "Cannot read the sockets of PID %s, so none names its root: %s", process.pid, exc
        )
        paths = []
    roots: set[str] = set()
    for path in paths:
        if path.startswith("/"):
            root = _project_of_socket(Path(path))
            if root is not None:
                roots.add(root)
    if len(roots) != 1:
        return None
    return roots.pop()


def is_this_users_process(pid: int) -> bool:
    """True when ``pid``'s real and effective uids are both this process's
    effective uid.

    Ownership is the owner's uid, never permission to signal (Plan 00466
    round 6, P5-1): root may signal every process, so a process of another
    user's passed as this user's whenever the hook ran as root.
    """
    # type() rather than isinstance(): see daemon_process_project_root.
    if type(pid) is not int or pid <= 1:
        return False
    try:
        uids = psutil.Process(pid).uids()
    except psutil.Error as e:
        logger.debug("Cannot read the owner of PID %d: %s", pid, e)
        return False
    euid = os.geteuid()
    return bool(uids.real == euid and uids.effective == euid)


def daemon_process_project_root(pid: int) -> RootProof:
    """Prove which real project root a live daemon SERVER pid serves.

    This is the proof a caller needs before it signals ``pid`` on behalf of one
    project: match ``root`` to that project with :func:`root_names_project`.
    ``root`` is the daemon's own normalised text, never resolved (review 9,
    DR-1).

    Args:
        pid: Candidate process id.

    Returns:
        A proof with the resolved root, or with the reason there is none:
        ``pid`` is not a real ``int`` above 1, is this process, is gone or
        inaccessible, is not a daemon server, or neither its command line nor
        the socket it listens on names a project.
    """
    # type() rather than isinstance(): a bool is an int, and a MagicMock pid
    # coerces to 1 through __index__ (Plan 00466 N59), so neither is a pid.
    if type(pid) is not int or pid <= 1 or pid == os.getpid():
        return RootProof(root=None, refusal=f"{pid!r} is not a pid another process can own")
    try:
        process = psutil.Process(pid)
        cmdline = process.cmdline()
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess) as e:
        logger.debug("Cannot inspect PID %d cmdline: %s", pid, e)
        return RootProof(root=None, refusal=f"PID {pid} cannot be inspected ({type(e).__name__})")
    if not _is_daemon_server_process(cmdline):
        return RootProof(root=None, refusal=f"PID {pid} is not a hooks daemon server")
    attributed = _attributed_root(process, cmdline)
    if attributed.root is None:
        return RootProof(
            root=None, refusal=f"PID {pid} is a daemon server, but {attributed.refusal}"
        )
    return attributed


def _is_daemon_server_process(cmdline: list[str] | None) -> bool:
    """Check if a command line identifies a daemon SERVER process.

    A daemon server is launched via ``python -m {cli module} [global flags]
    {start|restart}``. We require BOTH the cli module token AND a launch
    subcommand appearing after it. This deliberately excludes:

    - transient CLI helpers (``status``, ``stop``, ``logs``, ``health``,
      ``repair``, ``check-truth-changes``, ``generate-docs``, ``validate-*``, …)
    - the per-event hook forwarders (the bash wrappers' python3 socket transport)
    - a bare ``cli`` invocation with no subcommand

    none of which are daemon servers and so must never be terminated by
    single-daemon enforcement.

    Args:
        cmdline: Command line arguments from psutil.

    Returns:
        True only if the cmdline is a daemon server invocation.

    Note:
        Case-sensitive matching. See ``_DAEMON_LAUNCH_SUBCOMMANDS`` for why the
        allowlist is provably complete (zero false negatives).
    """
    if not cmdline:
        return False

    module_index = _cli_module_index(cmdline)
    if module_index is None:
        return False

    # A launch subcommand must appear AFTER the module token (global flags such
    # as ``--project-root PATH`` may sit between the module and the subcommand).
    return any(token in _DAEMON_LAUNCH_SUBCOMMANDS for token in cmdline[module_index + 1 :])


def _cli_module_index(cmdline: list[str]) -> int | None:
    """The index of the first argument naming the cli module, or None."""
    for index, token in enumerate(cmdline):
        if DAEMON_CLI_MODULE in token:
            return index
    return None
