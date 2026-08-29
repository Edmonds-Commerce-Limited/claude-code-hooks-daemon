"""CLI commands for daemon lifecycle management.

Provides:
- start: Start daemon in background (daemonise)
- stop: Send SIGTERM to daemon PID
- status: Check if daemon is running
- restart: Stop and start daemon
- logs: Query in-memory logs from running daemon
- health: Check daemon health status
- handlers: List registered handlers
- config: Show loaded configuration
- init-config: Generate configuration template
- generate-playbook: Generate acceptance test playbook from handler definitions
- generate-docs: Generate .claude/HOOKS-DAEMON.md from live config and handler metadata
- regenerate-docs: Force-regenerate HOOKS-DAEMON.md AND the CLAUDE.md <hooksdaemon> block
- repair: Repair broken venv (runs uv sync)
- config-diff: Compare user config against default
- config-merge: Merge user customizations onto new default
- config-validate: Validate config against Pydantic schema
- init-project-handlers: Scaffold project-handlers directory structure
- validate-project-handlers: Validate project handler files
- test-project-handlers: Run project handler tests
- bug-report: Generate comprehensive bug report with diagnostics
- format-markdown: Format markdown files via mdformat + mdformat-gfm
"""

import argparse
import asyncio
import datetime
import importlib.util
import json
import logging
import os
import platform
import shutil
import signal
import socket
import subprocess  # nosec B404 - subprocess used for daemon management (systemctl) only
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast

logger = logging.getLogger(__name__)

from pydantic import ValidationError as PydanticValidationError

from claude_code_hooks_daemon.config.loader import ConfigLoader
from claude_code_hooks_daemon.config.models import Config
from claude_code_hooks_daemon.constants import Timeout
from claude_code_hooks_daemon.constants.modes import DaemonMode
from claude_code_hooks_daemon.constants.permissions import FileMode
from claude_code_hooks_daemon.core.event import EventType
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.daemon.enforcement import enforce_single_daemon
from claude_code_hooks_daemon.daemon.metadata import (
    DaemonVenvMetadata,
    compute_project_lock_hash,
    write_daemon_metadata,
)
from claude_code_hooks_daemon.daemon.paths import (
    cleanup_pid_file,
    cleanup_socket,
    cleanup_stale_daemon_files,
    cleanup_stale_session_dirs,
    get_pid_path,
    get_socket_path,
    get_venv_path,
    python_venv_fingerprint,
    read_pid_file,
    read_socket_discovery_file,
    resolve_existing_venv_python,
    resolve_hostname,
    write_cleanup_status,
)
from claude_code_hooks_daemon.daemon.permission_audit import (
    audit_untracked_permissions,
    tighten_permissions,
)
from claude_code_hooks_daemon.daemon.server import (
    DaemonAlreadyRunningError,
    _socket_liveness_sync,
    _SocketLiveness,
)
from claude_code_hooks_daemon.daemon.validation import (
    check_for_nested_installation,
    is_hooks_daemon_repo,
    is_inside_daemon_directory,
)
from claude_code_hooks_daemon.docs_qa.comment_finder import DEFAULT_MIN_BLOCK_LINES
from claude_code_hooks_daemon.utils.cli_command import daemon_cli_command
from claude_code_hooks_daemon.utils.git_repo import run_git
from claude_code_hooks_daemon.utils.hook_registration import (
    detect_duplicate_hooks,
    detect_legacy_hook_commands,
    detect_local_hooks_misplacement,
    reconcile_settings_hooks,
    validate_hook_commands,
    validate_settings_hooks,
)
from claude_code_hooks_daemon.utils.markdown_format import format_markdown_text
from claude_code_hooks_daemon.utils.settings_repair import repair_settings_registrations

from .init_config import generate_config

if TYPE_CHECKING:
    from collections.abc import Sequence

    from claude_code_hooks_daemon.daemon.branch_safety import BranchClassification
    from claude_code_hooks_daemon.daemon.controller import DaemonController
    from claude_code_hooks_daemon.daemon.project_handler_health import (
        ProjectHandlerHealthState,
    )

# Test-runner module ``test-project-handlers`` shells out to. It is a dev-only
# extra (see pyproject ``[project.optional-dependencies].dev``), so it is
# deliberately absent from client installs and its presence must be probed
# before use rather than assumed.
_PYTEST_MODULE = "pytest"

# Milliseconds in one second. ``Timeout.BASH_DEFAULT`` is expressed in
# milliseconds (see constants/timeout.py), but ``subprocess.run(timeout=...)``
# expects SECONDS. Named here so the conversion is not a magic ``/ 1000``.
_MILLISECONDS_PER_SECOND = 1000

# ``uv sync`` timeout for ``cmd_repair``, in SECONDS — derived from the shared
# millisecond BASH default so there is a single source of truth for the value
# while honouring subprocess.run's seconds unit.
_UV_SYNC_TIMEOUT_SECONDS = Timeout.BASH_DEFAULT // _MILLISECONDS_PER_SECOND

# Post-repair import-verification timeout for ``cmd_repair``, in SECONDS. The
# import is a cheap sanity check, but a deadlocked C-extension or NFS stall
# could make it hang forever — bound it so ``repair`` always terminates.
_VERIFY_IMPORT_TIMEOUT_SECONDS = Timeout.BASH_DEFAULT // _MILLISECONDS_PER_SECOND


def get_project_path(override_path: Path | None = None) -> Path:
    """Detect project path from current working directory.

    Walks up directory tree to find .claude directory and validates installation
    based on self_install_mode configuration.

    Args:
        override_path: Optional path to use instead of auto-detection

    Returns:
        Path to project root directory

    Raises:
        SystemExit if .claude directory not found or installation invalid
    """
    if override_path:
        override_path = override_path.resolve()
        if not (override_path / ".claude").is_dir():
            print(f"ERROR: No .claude directory at: {override_path}", file=sys.stderr)
            sys.exit(1)
        return _validate_installation(override_path)

    current = Path.cwd()

    while current != current.parent:
        claude_dir = current / ".claude"
        if claude_dir.is_dir():
            # Skip if this candidate is inside a .claude/hooks-daemon/ directory tree.
            # The daemon repo's own .claude/ (from self-install dogfooding) must not
            # be mistaken for the real project's .claude/ directory.
            if is_inside_daemon_directory(current):
                current = current.parent
                continue
            # Validate installation based on config
            try:
                return _validate_installation(current)
            except SystemExit:
                # Invalid installation - keep searching upward
                logger.debug("Invalid installation at %s, searching upward", current)
        current = current.parent

    print(
        "ERROR: Could not find .claude directory with valid hooks daemon installation\n"
        "You must run this command from the project root or any subdirectory.\n"
        f"Current directory: {Path.cwd()}",
        file=sys.stderr,
    )
    sys.exit(1)


def resolve_tree_root(args: argparse.Namespace) -> Path | None:
    """Resolve a project root for a command that needs a TREE, not an install.

    :func:`get_project_path` additionally insists on a git remote and a loadable
    config, and terminates the process when either is absent. That is right for
    a command that talks to a daemon, and wrong for one that only reads a
    directory: an operator who named a root explicitly has already answered the
    question that validation exists to ask.

    Args:
        args: Parsed CLI arguments, optionally carrying ``project_root``.

    Returns:
        The resolved root, or ``None`` when an explicit override is not a
        directory — the caller turns that into its own operational exit code,
        because the error message belongs with the command's contract.
    """
    override = getattr(args, "project_root", None)
    if override is None:
        return get_project_path(None)

    project_root = Path(override)
    if not project_root.is_dir():
        print(f"ERROR: Project root does not exist: {project_root}", file=sys.stderr)
        return None
    return project_root


def _validate_installation(project_root: Path) -> Path:
    """Validate hooks daemon installation at project root.

    Checks:
    1. No nested installation detected
    2. Not the hooks-daemon repo without self_install_mode
    3. .claude/hooks-daemon/ directory exists unless in self_install_mode

    Args:
        project_root: Path to project root with .claude directory

    Returns:
        project_root if valid

    Raises:
        SystemExit: If installation is invalid
    """
    # Check for nested installation
    nested_error = check_for_nested_installation(project_root)
    if nested_error:
        print(f"ERROR: {nested_error}", file=sys.stderr)
        sys.exit(1)

    claude_dir = project_root / ".claude"
    config_file = claude_dir / "hooks-daemon.yaml"

    # Load config to check self_install_mode
    # FAIL FAST: Invalid config must be surfaced immediately
    self_install = False
    config_dict: dict[str, Any] | None = None
    if config_file.exists():
        try:
            # Initialize ProjectContext BEFORE config validation
            # (Config validation instantiates handlers which may use ProjectContext)
            if not ProjectContext._initialized:
                ProjectContext.initialize(config_file)

            config_dict = ConfigLoader.load(config_file)
            config = Config.model_validate(config_dict)
            self_install = config.daemon.self_install_mode
        except PydanticValidationError as e:
            # FAIL FAST: Format Pydantic errors with user-friendly messages
            from claude_code_hooks_daemon.config.validation_ux import format_validation_error

            friendly_msg = format_validation_error(e, config_dict)
            print(
                f"ERROR: Invalid configuration in {config_file}:\n\n{friendly_msg}\n\n"
                "Fix the configuration file and try again.",
                file=sys.stderr,
            )
            sys.exit(1)
        except Exception as e:
            # FAIL FAST: Config validation errors must abort with clear message
            print(
                f"ERROR: Invalid configuration in {config_file}:\n\n{e}\n\n"
                "Fix the configuration file and try again.",
                file=sys.stderr,
            )
            sys.exit(1)

    # Check if this is the hooks-daemon repo without self_install_mode
    if (project_root / ".git").exists() and is_hooks_daemon_repo(project_root):
        if not self_install:
            print(
                "ERROR: This is the hooks-daemon repository.\n"
                "To run the daemon for development, add to .claude/hooks-daemon.yaml:\n"
                "  daemon:\n"
                "    self_install_mode: true",
                file=sys.stderr,
            )
            sys.exit(1)

    # In normal install mode, verify hooks-daemon directory exists
    if not self_install:
        hooks_daemon_dir = claude_dir / "hooks-daemon"
        if not hooks_daemon_dir.is_dir():
            print(
                f"ERROR: hooks-daemon not installed at: {project_root}\n"
                f"Expected directory: {hooks_daemon_dir}\n"
                f"Hint: Run 'python install.py' or set 'self_install_mode: true' in config",
                file=sys.stderr,
            )
            sys.exit(1)

    return project_root


def send_daemon_request(
    socket_path: Path,
    request: dict[str, Any],
    timeout: int = 5,
) -> dict[str, Any] | None:
    """Send a request to the daemon and get response.

    Args:
        socket_path: Path to Unix socket
        request: Request dictionary to send
        timeout: Timeout in seconds

    Returns:
        Response dictionary or None if failed
    """
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect(str(socket_path))

        # Send request
        request_json = json.dumps(request) + "\n"
        sock.sendall(request_json.encode("utf-8"))
        sock.shutdown(socket.SHUT_WR)

        # Read response
        response = b""
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            response += chunk

        sock.close()
        return cast("dict[str, Any]", json.loads(response.decode("utf-8")))

    except Exception:
        logger.exception("Failed to communicate with daemon")
        return None


def _resolve_pid_path(args: argparse.Namespace, project_path: Path) -> Path:
    """Resolve PID file path with CLI flag override support.

    Precedence: CLI flag > auto-discovery (env vars honored by get_pid_path).

    Args:
        args: Parsed command-line arguments
        project_path: Project root directory

    Returns:
        Resolved PID file path
    """
    if hasattr(args, "pid_file") and args.pid_file is not None:
        return Path(args.pid_file)
    return get_pid_path(project_path)


def _resolve_socket_path(args: argparse.Namespace, project_path: Path) -> Path:
    """Resolve socket path with CLI flag override support.

    Precedence: CLI flag > auto-discovery (env vars honored by get_socket_path).

    Args:
        args: Parsed command-line arguments
        project_path: Project root directory

    Returns:
        Resolved socket path
    """
    if hasattr(args, "socket") and args.socket is not None:
        return Path(args.socket)
    return get_socket_path(project_path)


# Plan 00187: split-brain drift warning. A stale, git-tracked
# ``.claude/hooks-daemon.env`` can pin a non-canonical socket name as an AF_UNIX
# length-limit workaround. ``init.sh`` sources that env and binds/looks-up that
# name; the management CLI, invoked without the env, computes the deterministic
# hash name and would report NOT RUNNING even though a daemon is live. This
# message is emitted when the CLI adopts the daemon's own discovery-file socket
# because it differs from the computed one.
_SPLIT_BRAIN_WARNING_TEMPLATE = (
    "WARNING: daemon socket mismatch (split-brain).\n"
    "  A live daemon is serving on:  {discovered}\n"
    "  but this CLI computes:        {computed}\n"
    "  Reporting on the live daemon (discovered via the socket-path file the\n"
    "  daemon publishes at startup). This usually means a stale\n"
    "  CLAUDE_HOOKS_SOCKET_PATH override in .claude/hooks-daemon.env pins a\n"
    "  non-canonical socket name. Update that override to the computed path\n"
    "  above (or remove it) so the hook forwarders and the management CLI agree."
)


def _resolve_effective_daemon(
    args: argparse.Namespace, project_path: Path
) -> tuple[Path, Path, str | None]:
    """Resolve the socket/PID paths of the daemon that is ACTUALLY running.

    Mirrors ``init.sh``'s discovery-file fallback (both consult the same
    ``daemon{suffix}.socket-path`` file the daemon publishes at startup) so the
    Python management CLI agrees with the hook forwarders when a stale
    ``hooks-daemon.env`` override pins a non-canonical socket name (Plan 00187).

    Resolution order:

    1. An explicit ``--socket`` flag or a set ``CLAUDE_HOOKS_SOCKET_PATH`` env is
       honoured verbatim — never second-guessed (mirrors ``init.sh``'s guard).
    2. Otherwise, if the computed PID path already names a live daemon, use the
       computed paths.
    3. Otherwise, consult the socket discovery file. If it names a DIFFERENT
       socket whose sibling PID file is a live daemon, adopt that socket/PID and
       return a split-brain drift warning. A stale (dead-daemon) or same-path
       discovery file is ignored.

    Returns:
        ``(socket_path, pid_path, drift_warning)`` — ``drift_warning`` is None
        unless a split-brain was detected and the discovered daemon adopted.
    """
    socket_path = _resolve_socket_path(args, project_path)
    pid_path = _resolve_pid_path(args, project_path)

    # An explicit override (flag or env) pins the target — respect it verbatim.
    explicit = (getattr(args, "socket", None) is not None) or bool(
        os.environ.get("CLAUDE_HOOKS_SOCKET_PATH")
    )
    if explicit:
        return socket_path, pid_path, None

    # Computed path already has a live daemon — nothing to reconcile.
    if read_pid_file(str(pid_path), verify_daemon=True) is not None:
        return socket_path, pid_path, None

    discovered_socket = read_socket_discovery_file(project_path)
    if discovered_socket is None or discovered_socket == socket_path:
        return socket_path, pid_path, None

    # The daemon publishes only its socket path; its PID file is the sibling.
    discovered_pid = discovered_socket.with_suffix(".pid")
    if read_pid_file(str(discovered_pid), verify_daemon=True) is None:
        # Stale discovery file (its daemon is dead) — do not adopt.
        return socket_path, pid_path, None

    warning = _SPLIT_BRAIN_WARNING_TEMPLATE.format(
        discovered=discovered_socket, computed=socket_path
    )
    return discovered_socket, discovered_pid, warning


def _reap_stale_runtime_files(project_path: Path, config: Config) -> None:
    """Age-out stale daemon + per-session runtime files (Plan 00181 Task 4.1).

    Runs on EVERY start attempt — including the Plan 00127 reuse path, which
    returns before the fork — so orphaned files are reaped even when a healthy
    incumbent is reused. Age-based and scoped to THIS project's untracked dir: a
    live incumbent's freshly-touched files are never removed and other projects
    are untouched. Never touches the socket (that stays on the fork path only).
    """
    stale_days = config.daemon.stale_file_days
    # Stale daemon runtime files from dead containers (age-based, not hostname-based).
    stale_daemon = cleanup_stale_daemon_files(project_path, max_age_days=stale_days)
    # Per-session runtime subdirs (thread-registry/, context-sidecar/,
    # payload-capture/) whose writers never delete their own dead-session files.
    stale_sessions = cleanup_stale_session_dirs(project_path, max_age_days=stale_days)
    stale_total = stale_daemon + stale_sessions
    write_cleanup_status(project_path, stale_total)
    if stale_total > 0:
        print(f"Cleaned up {stale_total} stale file(s) older than {stale_days} days")

    # Plan 00181 Task 4.2 (Decision 1): SURFACE reclaimable stale/legacy venvs
    # (~187 MB each) — the biggest disk offender — but never auto-delete them
    # (unsafe in the multi-container shared-untracked model). Deletion stays the
    # operator's guarded `prune-venvs` call.
    venv_advisory = _stale_venv_advisory(project_path)
    if venv_advisory is not None:
        print(venv_advisory)


def cmd_start(args: argparse.Namespace) -> int:
    """Start daemon in background.

    Args:
        args: Command-line arguments

    Returns:
        0 if daemon started successfully, 1 otherwise
    """
    project_path = get_project_path(getattr(args, "project_root", None))
    socket_path = _resolve_socket_path(args, project_path)
    pid_path = _resolve_pid_path(args, project_path)

    # Load config for enforcement check
    config_path = project_path / ".claude" / "hooks-daemon.yaml"
    try:
        config = Config.load(config_path)
    except FileNotFoundError:
        config = Config()  # Use defaults if no config file

    # Plan 00181 Task 4.1: reap stale runtime files BEFORE the reuse gate so the
    # common shared-daemon reuse path (which returns below without forking) still
    # cleans up. Age-based and scoped to this project's untracked dir, so a live
    # incumbent's freshly-touched files are never removed. Never touches the
    # socket (that stays on the fork path only).
    _reap_stale_runtime_files(project_path, config)

    # REUSE gate (Plan 00127, Decision 1): if a LIVE, HEALTHY same-root daemon
    # already owns our socket, reuse it — return 0 and leave the incumbent
    # untouched. This runs FIRST, before enforce_single_daemon, so a healthy
    # shared daemon is never killed. A THREE-STATE probe is used (not a boolean):
    # collapsing INDETERMINATE (timeout against a busy-but-live daemon, or a
    # transient fd-exhaustion OSError in THIS process) to "not live" would make
    # the parent unlink a live incumbent's socket downstream (re-review Finding).
    pid = read_pid_file(str(pid_path))
    liveness = _socket_liveness_sync(Path(socket_path))
    socket_live = liveness is _SocketLiveness.LIVE
    socket_indeterminate = liveness is _SocketLiveness.INDETERMINATE

    # Reuse a healthy incumbent (LIVE) or a healthy-but-busy one (INDETERMINATE
    # with a live PID): in both cases a daemon owns the socket and must not be
    # disturbed. Requires the live PID so a leftover socket inode cannot be
    # mistaken for a healthy incumbent.
    if pid is not None and (socket_live or socket_indeterminate):
        print(f"Daemon already running (PID: {pid})")
        return 0

    # Degenerate contention: a LIVE socket whose owner is not our PID file
    # (foreign listener / no matching alive PID). Do NOT unlink a live socket —
    # fail fast per Decision 1's unhealthy/contended safety net.
    if socket_live:
        print(
            "ERROR: A live daemon owns the socket but is not ours "
            f"(socket: {socket_path}); refusing to steal it",
            file=sys.stderr,
        )
        return 1

    # INDETERMINATE with no live PID: the socket cannot be PROVEN dead (a dead
    # daemon leaves a ConnectionRefused = NOT_LIVE socket, not an indeterminate
    # one), so unlinking it risks stealing a live socket. Fail fast rather than
    # steal; a genuinely stale socket file can be removed manually.
    if socket_indeterminate:
        print(
            "ERROR: socket exists but its liveness is indeterminate and no live "
            f"PID is recorded (socket: {socket_path}); refusing to unlink a "
            "possibly-live socket. Retry, or remove the stale socket file if no "
            "daemon is running.",
            file=sys.stderr,
        )
        return 1

    # No live incumbent on our socket — now enforce single daemon (if enabled).
    # (Runs AFTER the reuse gate so a healthy shared daemon is never killed.)
    enforce_single_daemon(
        config=config,
        pid_path=pid_path,
        project_root=project_path,
        socket_path=Path(socket_path),
    )

    # Stale-socket cleanup is DELIBERATELY NOT done here (Plan 00127, Finding 3).
    # The liveness probe above was taken BEFORE the start lock is held; a peer
    # that binds its socket in the probe->fork window would have its LIVE socket
    # unlinked if we cleaned up here, violating "a LIVE socket is NEVER
    # unlinked". The child daemon re-probes and unlinks the socket ONLY on a
    # DEFINITIVE NOT_LIVE outcome inside the flock-protected critical section
    # (server._reuse_or_clear_socket), which is the single race-safe place to
    # do it. Removing this unconditional parent unlink closes that window.
    #
    # (Stale-file reaping — daemon files + per-session runtime dirs — already ran
    # above via _reap_stale_runtime_files, before the reuse gate, so it covers
    # the reuse path too. Plan 00181 Task 4.1.)

    # Flush BEFORE forking. fork() copies the process's unflushed stdio buffer,
    # so the first child inherits everything printed so far and re-emits it when
    # it exits — every prior line appears TWICE. Only reproduces when stdout is
    # block-buffered (redirected to a file or pipe), so it is invisible at an
    # interactive terminal and corrupts exactly the captured output that tooling
    # parses. `restart` showed "Sent SIGTERM (PID: N) / Daemon stopped" twice
    # with the same pid, reading as two daemons killed.
    sys.stdout.flush()
    sys.stderr.flush()

    # Daemonise process (fork and detach from terminal)
    try:
        # First fork
        pid = os.fork()
        if pid > 0:
            # Parent process - poll for PID file (child startup time is
            # variable on slow hosts: imports + config load + handler init).
            # Plan 00100 Task 0.2: replace fixed 0.5s sleep with polling.
            daemon_pid = None
            for _ in range(Timeout.DAEMON_PID_POLL_MAX_ITERATIONS):
                time.sleep(Timeout.DAEMON_PID_POLL_INTERVAL_SEC)
                daemon_pid = read_pid_file(str(pid_path))
                if daemon_pid is not None:
                    break
            if daemon_pid is not None:
                print(f"Daemon started successfully (PID: {daemon_pid})")
                print(f"Socket: {socket_path}")
                print("Logs: in-memory (query with 'logs' command)")
                return 0
            else:
                print("ERROR: Daemon failed to start (no PID file created)", file=sys.stderr)
                return 1
    except OSError as e:
        print(f"ERROR: Fork failed: {e}", file=sys.stderr)
        return 1

    # First child - decouple from parent environment
    os.chdir("/")
    os.setsid()
    # Plan 00239: NOT the textbook umask(0). Clearing the mask is only safe for a
    # daemon that passes an explicit mode to every create, and this one does so at
    # exactly one of 98 sites — so umask(0) shipped a world-writable verdict log,
    # payload-capture/ and PID file. See constants/permissions.py for why the mask
    # is 0o077 rather than the group-preserving 0o007.
    os.umask(FileMode.DAEMON_UMASK)

    # Second fork
    try:
        pid = os.fork()
        if pid > 0:
            # Exit first child
            sys.exit(0)
    except OSError as e:
        print(f"ERROR: Second fork failed: {e}", file=sys.stderr)
        sys.exit(1)

    # Second child - this becomes the daemon process
    # Redirect stdin to /dev/null
    sys.stdin.close()

    # Redirect stdout AND stderr to /dev/null
    # CRITICAL: Both must be redirected. If stderr is kept open, any caller using
    # $() command substitution with 2>&1 (e.g. start_daemon_safe in daemon_control.sh)
    # will block forever because the pipe stays open as long as the daemon runs.
    # The in-memory log system (MemoryLogHandler) captures all errors — stderr is
    # not needed for a properly daemonized background process.
    devnull_fd = os.open(os.devnull, os.O_WRONLY)
    os.dup2(devnull_fd, sys.stdout.fileno())
    os.dup2(devnull_fd, sys.stderr.fileno())
    os.close(devnull_fd)

    # Now run the daemon server
    from claude_code_hooks_daemon.daemon.server import HooksDaemon

    # Load configuration
    config = Config.find_and_load(project_path)

    # Create and fully initialise the daemon controller. Initialising also
    # regenerates the CLAUDE.md <hooksdaemon> block (via the injector). Shared
    # single source of truth with cmd_regenerate_docs.
    controller = _build_initialised_controller(config, project_path)

    # Get the daemon config with proper paths
    daemon_config = config.daemon

    # Ensure paths are set (use getters if not set)
    if daemon_config.socket_path is None:
        daemon_config.socket_path = str(daemon_config.get_socket_path(project_path))
    if daemon_config.pid_file_path is None:
        daemon_config.pid_file_path = str(daemon_config.get_pid_file_path(project_path))

    daemon = HooksDaemon(daemon_config, controller)

    # Write socket discovery file so bash hook forwarders (init.sh)
    # can find the daemon when the socket path differs from the default
    # (e.g., AF_UNIX path length fallback to XDG_RUNTIME_DIR)
    from claude_code_hooks_daemon.daemon.paths import (
        cleanup_socket_discovery_file,
        write_socket_discovery_file,
    )

    write_socket_discovery_file(project_path, daemon_config.socket_path)

    # Plan 00127 (Finding 2): the socket-discovery file is SHARED between the
    # incumbent and any losing same-root start (deterministic per untracked dir
    # + hostname). It must be deleted ONLY by the process that actually OWNED
    # the daemon, never by a reuse-race loser — on long-path (fallback-socket)
    # setups init.sh relies on this file to find the live incumbent's socket,
    # and the incumbent only writes it once at its own startup. Deleting it in a
    # blanket `finally` would silently break the incumbent's hook forwarding.
    i_owned_the_daemon = False
    try:
        asyncio.run(daemon.start())
        # start() returned normally => this process owned and then shut the
        # daemon down cleanly. Its discovery file is now stale and ours to clear.
        i_owned_the_daemon = True
    except DaemonAlreadyRunningError as e:
        # A live incumbent won the race. This is a benign REUSE, NOT a crash —
        # the winning daemon already wrote the PID file the parent polls for, so
        # overall start is a clean exit 0 with exactly one daemon. We did NOT own
        # the daemon, so we must NOT delete the incumbent's discovery file.
        print(
            f"Daemon already running on {daemon_config.socket_path}; "
            f"reusing existing instance: {e}"
        )
        sys.exit(0)
    except Exception as e:
        # A genuine crash AFTER we bound and published our own discovery file:
        # we owned it, so clear it on the way out.
        i_owned_the_daemon = True
        print(f"ERROR: Daemon crashed: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        sys.exit(1)
    finally:
        if i_owned_the_daemon:
            cleanup_socket_discovery_file(project_path)

    sys.exit(0)


def cmd_stop(args: argparse.Namespace) -> int:
    """Stop running daemon.

    Args:
        args: Command-line arguments

    Returns:
        0 if daemon stopped successfully, 1 otherwise
    """
    project_path = get_project_path(getattr(args, "project_root", None))
    pid_path = _resolve_pid_path(args, project_path)
    socket_path = _resolve_socket_path(args, project_path)

    # Read PID. verify_daemon guards against a stale PID file (after reboot /
    # PID reuse) pointing at an unrelated live process we would otherwise
    # SIGTERM.
    pid = read_pid_file(str(pid_path), verify_daemon=True)
    if pid is None:
        print("Daemon not running")
        return 0

    # Send SIGTERM
    try:
        os.kill(pid, signal.SIGTERM)
        print(f"Sent SIGTERM to daemon (PID: {pid})")

        # Wait for process to exit (up to 5 seconds)
        timeout = Timeout.SOCKET_CONNECT
        interval = 0.1
        elapsed = 0.0

        while elapsed < timeout:
            try:
                os.kill(pid, 0)  # Check if still alive
                time.sleep(interval)
                elapsed += interval
            except ProcessLookupError:
                # Process exited
                break

        # Check if still running
        try:
            os.kill(pid, 0)
            print(f"WARNING: Daemon still running after {timeout}s", file=sys.stderr)
            print(f"Try: kill -9 {pid}", file=sys.stderr)
            return 1
        except ProcessLookupError:
            # Process exited successfully
            print("Daemon stopped")
            cleanup_pid_file(str(pid_path))
            cleanup_socket(str(socket_path))
            return 0

    except ProcessLookupError:
        print(f"Process {pid} not found (stale PID file)")
        cleanup_pid_file(str(pid_path))
        cleanup_socket(str(socket_path))
        return 0
    except PermissionError:
        print(f"ERROR: Permission denied to signal PID {pid}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


def cmd_status(args: argparse.Namespace) -> int:
    """Check daemon status.

    Args:
        args: Command-line arguments

    Returns:
        0 if daemon is running, 1 otherwise
    """
    project_path = get_project_path(getattr(args, "project_root", None))
    # Plan 00187: reconcile the computed socket/PID with the daemon's own
    # discovery file so a stale hooks-daemon.env override does not make us
    # report NOT RUNNING while hooks fire fine on a differently-named socket.
    socket_path, pid_path, drift_warning = _resolve_effective_daemon(args, project_path)
    if drift_warning is not None:
        print(drift_warning, file=sys.stderr)

    # Read PID. verify_daemon guards against a stale PID file (after reboot /
    # PID reuse) whose PID now belongs to an unrelated live process, which
    # would otherwise be falsely reported as a RUNNING daemon.
    pid = read_pid_file(str(pid_path), verify_daemon=True)

    if pid is None:
        print("Daemon: NOT RUNNING")
        print(f"Socket: {socket_path}")
        print(f"PID file: {pid_path}")
        return 1

    # Check socket exists
    socket_exists = socket_path.exists()

    print("Daemon: RUNNING")
    print(f"PID: {pid}")
    print(f"Socket: {socket_path} ({'exists' if socket_exists else 'MISSING'})")
    print(f"PID file: {pid_path}")

    # Project-handler protection signal (Plan 00143). Surfaced for visibility;
    # the exit code stays liveness-based so existing "status == RUNNING" checks
    # keep working — `health` is the command that returns a non-zero on degrade.
    health_state = _read_project_handler_health(project_path)
    if health_state.is_degraded:
        print("\n🚨 PROJECT PROTECTION DEGRADED 🚨")
        for line in _format_project_handler_health_lines(health_state):
            print(line)

    if not socket_exists:
        print("\nWARNING: Daemon running but socket not found", file=sys.stderr)
        return 1

    return 0


def cmd_logs(args: argparse.Namespace) -> int:
    """Query in-memory logs from running daemon.

    Args:
        args: Command-line arguments with optional count, level, follow

    Returns:
        0 if successful, 1 otherwise
    """
    project_path = get_project_path(getattr(args, "project_root", None))
    socket_path = _resolve_socket_path(args, project_path)
    pid_path = _resolve_pid_path(args, project_path)

    # Check if daemon is running
    pid = read_pid_file(str(pid_path))
    if pid is None:
        print("Daemon not running - no logs available", file=sys.stderr)
        return 1

    # Build request
    request: dict[str, Any] = {
        "event": "_system",
        "hook_input": {
            "action": "get_logs",
            "count": args.count,
        },
    }

    if args.level:
        request["hook_input"]["level"] = args.level.upper()

    # Follow mode - poll for new logs
    if args.follow:
        print("Following logs (Ctrl+C to stop)...")
        last_count = 0
        try:
            while True:
                response = send_daemon_request(socket_path, request)
                if response is None:
                    return 1

                if "error" in response:
                    print(f"ERROR: {response['error']}", file=sys.stderr)
                    return 1

                result = response.get("result", {})
                logs = result.get("logs", [])
                current_count = result.get("count", 0)

                # Print new logs
                if current_count > last_count:
                    new_logs = logs[-(current_count - last_count) :]
                    for log_line in new_logs:
                        print(log_line)
                    last_count = current_count

                time.sleep(1)  # Poll interval

        except KeyboardInterrupt:
            print("\nStopped following logs")
            return 0

    # Single query mode
    response = send_daemon_request(socket_path, request)
    if response is None:
        return 1

    if "error" in response:
        print(f"ERROR: {response['error']}", file=sys.stderr)
        return 1

    # Print logs
    result = response.get("result", {})
    logs = result.get("logs", [])
    count = result.get("count", 0)

    if not logs:
        print("No logs in buffer")
        return 0

    print(f"=== Daemon Logs ({count} records) ===\n")
    for log_line in logs:
        print(log_line)

    return 0


def check_hook_registration_warnings(project_path: Path) -> list[str]:
    """Collect hook-registration warnings for `health` output.

    Reads .claude/settings.json and .claude/settings.local.json and returns
    a flat list of warning strings covering:

    - missing hook events in settings.json
    - duplicate entries across settings.json and settings.local.json
    - ANY hook entries in settings.local.json (policy violation)
    - hook commands that don't match the expected daemon wrapper
    - legacy-style commands that bypass the daemon entirely

    Args:
        project_path: Project root containing the .claude directory

    Returns:
        List of warning strings (empty if everything is clean). Unreadable
        or missing files are treated as empty, so they don't break health.
    """
    claude_dir = project_path / ".claude"
    settings_path = claude_dir / "settings.json"
    local_path = claude_dir / "settings.local.json"

    def _read(path: Path) -> dict[str, object]:
        if not path.exists():
            return {}
        try:
            with path.open() as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    settings = _read(settings_path)
    local_settings = _read(local_path)

    # No settings at all → project isn't a hooks-daemon consumer yet.
    if not settings:
        return []

    warnings: list[str] = []
    warnings.extend(validate_settings_hooks(settings))
    warnings.extend(detect_duplicate_hooks(settings, local_settings))
    warnings.extend(detect_local_hooks_misplacement(local_settings))
    warnings.extend(validate_hook_commands(settings))
    warnings.extend(detect_legacy_hook_commands(settings))
    warnings.extend(detect_legacy_hook_commands(local_settings))
    return warnings


def cmd_health(args: argparse.Namespace) -> int:
    """Check daemon health status.

    Args:
        args: Command-line arguments

    Returns:
        0 if healthy, 1 otherwise
    """
    project_path = get_project_path(getattr(args, "project_root", None))
    # Plan 00187: reconcile with the daemon's discovery file (see cmd_status)
    # so a stale hooks-daemon.env socket-name override does not mask a live
    # daemon behind a bare NOT RUNNING.
    socket_path, pid_path, drift_warning = _resolve_effective_daemon(args, project_path)
    if drift_warning is not None:
        print(drift_warning, file=sys.stderr)

    # Check if daemon is running
    pid = read_pid_file(str(pid_path))
    if pid is None:
        print("Daemon: NOT RUNNING")
        return 1

    # Request health info
    request = {"event": "_system", "hook_input": {"action": "health"}}
    response = send_daemon_request(socket_path, request)

    if response is None:
        print("Daemon: UNHEALTHY (no response)")
        return 1

    if "error" in response:
        print(f"Daemon: UNHEALTHY ({response['error']})")
        return 1

    result = response.get("result", {})
    status = result.get("status", "unknown")
    stats = result.get("stats", {})
    handlers = result.get("handlers", {})

    print(f"Daemon: {status.upper()}")
    print(f"PID: {pid}")
    print(f"Uptime: {stats.get('uptime_seconds', 0):.1f}s")
    print(f"Requests processed: {stats.get('requests_processed', 0)}")
    print(f"Average latency: {stats.get('avg_processing_time_ms', 0):.2f}ms")
    print(f"Errors: {stats.get('errors', 0)}")

    total_handlers = sum(handlers.values())
    print(f"\nHandlers registered: {total_handlers}")
    for event_type, count in handlers.items():
        if count > 0:
            print(f"  {event_type}: {count}")

    # Hook-registration drift (advisory — never changes the exit code).
    hook_warnings = check_hook_registration_warnings(project_path)
    print("\nHook registration:")
    if not hook_warnings:
        print("  OK — all hooks registered correctly in settings.json")
    else:
        print(f"  {len(hook_warnings)} issue(s) found:")
        for warning in hook_warnings:
            print(f"  ⚠️  {warning}")
        print(
            "\n  Fix: consolidate ALL hooks into .claude/settings.json "
            "(settings.local.json must contain ZERO hooks entries). "
            "Port legacy-style scripts to project-level handlers via "
            "`init-project-handlers`."
        )

    # Project-handler protection signal (Plan 00143). Unlike hook-registration
    # drift, this DOES drive the exit code: a skipped project handler is a
    # silently-disabled protection, so CI / the session-start audit can detect
    # the regression mechanically (non-zero exit).
    health_state = _read_project_handler_health(project_path)
    print("\nProject handlers:")
    for line in _format_project_handler_health_lines(health_state):
        print(line)

    healthy = status == "healthy" and not health_state.is_degraded
    return 0 if healthy else 1


def cmd_check(args: argparse.Namespace) -> int:
    """Run a verbose environment & configuration audit on demand (Plan 00128).

    SessionStart deliberately stays quiet about healthy state — it only speaks
    when something needs action. This command surfaces the FULL report on
    demand: Claude Code optimal-config settings (max output tokens, bash working
    directory, effort level, etc.), the container runtime, git ``core.fileMode``,
    and hook-registration drift. It reuses the SessionStart handlers' own check
    logic so there is a single source of truth.

    Args:
        args: Command-line arguments.

    Returns:
        0 always — this is an advisory report and never fails the shell.
    """
    from claude_code_hooks_daemon.handlers.session_start.git_filemode_checker import (
        GitFilemodeCheckerHandler,
    )
    from claude_code_hooks_daemon.handlers.session_start.optimal_config_checker import (
        OptimalConfigCheckerHandler,
    )
    from claude_code_hooks_daemon.utils import container_detection

    project_path = get_project_path(getattr(args, "project_root", None))

    print("Hooks Daemon — Environment Check\n")

    # 1. Claude Code optimal configuration (the verbose report SessionStart hides)
    checks = OptimalConfigCheckerHandler()._run_checks()
    passed = [c for c in checks if c["passed"]]
    print(f"Claude Code configuration: {len(passed)}/{len(checks)} optimal")
    for check in checks:
        marker = "OK  " if check["passed"] else "MISS"
        print(f"  [{marker}] {check['name']}: {check['current']}")
        if not check["passed"]:
            print(f"         Why:   {check['why']}")
            print(f"         Fix:   {check['fix']}")
            print(f"         Where: {check['where']}")
            print(f"         Docs:  {check['docs']}")

    # 2. Container runtime (shown by the status-line icon; spelled out here)
    print("\nContainer runtime:")
    runtime = container_detection.detect_container_runtime()
    if runtime:
        print(f"  In a {runtime} container")
    elif container_detection.in_container():
        print("  In a container (runtime unknown)")
    else:
        print("  Not in a container (desktop/host)")

    # 3. Git core.fileMode
    print("\nGit core.fileMode:")
    filemode = GitFilemodeCheckerHandler()._get_filemode_setting()
    if filemode is None:
        print("  Not in a git repository or unable to check")
    elif filemode == "false":
        print(
            "  false — WARNING: hooks may lose executable permissions. "
            "Fix: git config core.fileMode true"
        )
    else:
        print(f"  {filemode} (OK)")

    # 4. Hook-registration drift
    print("\nHook registration:")
    warnings = check_hook_registration_warnings(project_path)
    if not warnings:
        print("  OK — all hooks registered correctly in settings.json")
    else:
        print(f"  {len(warnings)} issue(s):")
        for warning in warnings:
            print(f"  ⚠️  {warning}")

    # 5. Project-handler protection (Plan 00143): are any project handlers
    # silently skipped by the running daemon?
    print("\nProject handlers:")
    for line in _format_project_handler_health_lines(_read_project_handler_health(project_path)):
        print(line)

    return 0


def cmd_get_mode(args: argparse.Namespace) -> int:
    """Get current daemon mode.

    Args:
        args: Command-line arguments

    Returns:
        0 if successful, 1 otherwise
    """
    project_path = get_project_path(getattr(args, "project_root", None))
    socket_path = _resolve_socket_path(args, project_path)
    pid_path = _resolve_pid_path(args, project_path)

    pid = read_pid_file(str(pid_path))
    if pid is None:
        print("Daemon not running", file=sys.stderr)
        return 1

    request = {"event": "_system", "hook_input": {"action": "get_mode"}}
    response = send_daemon_request(socket_path, request)

    if response is None:
        print("No response from daemon", file=sys.stderr)
        return 1

    if "error" in response:
        print(f"ERROR: {response['error']}", file=sys.stderr)
        return 1

    result = response.get("result", {})
    mode = result.get("mode", "unknown")
    custom_message = result.get("custom_message")

    if getattr(args, "json", False):
        print(json.dumps(result, indent=2))
    else:
        print(f"Mode: {mode}")
        if custom_message:
            print(f"Message: {custom_message}")

    return 0


def cmd_set_mode(args: argparse.Namespace) -> int:
    """Set daemon mode.

    Args:
        args: Command-line arguments

    Returns:
        0 if successful, 1 otherwise
    """
    project_path = get_project_path(getattr(args, "project_root", None))
    socket_path = _resolve_socket_path(args, project_path)
    pid_path = _resolve_pid_path(args, project_path)

    pid = read_pid_file(str(pid_path))
    if pid is None:
        print("Daemon not running", file=sys.stderr)
        return 1

    hook_input: dict[str, Any] = {
        "action": "set_mode",
        "mode": args.mode,
    }
    if getattr(args, "message", None):
        hook_input["custom_message"] = args.message

    request = {"event": "_system", "hook_input": hook_input}
    response = send_daemon_request(socket_path, request)

    if response is None:
        print("No response from daemon", file=sys.stderr)
        return 1

    if "error" in response:
        print(f"ERROR: {response['error']}", file=sys.stderr)
        return 1

    result = response.get("result", {})
    status = result.get("status", "unknown")
    mode = result.get("mode", "unknown")
    custom_message = result.get("custom_message")

    print(f"Mode: {mode} ({status})")
    if custom_message:
        print(f"Message: {custom_message}")

    return 0


def cmd_handlers(args: argparse.Namespace) -> int:
    """List registered handlers.

    Args:
        args: Command-line arguments

    Returns:
        0 if successful, 1 otherwise
    """
    project_path = get_project_path(getattr(args, "project_root", None))
    socket_path = _resolve_socket_path(args, project_path)
    pid_path = _resolve_pid_path(args, project_path)

    # Check if daemon is running
    pid = read_pid_file(str(pid_path))
    if pid is None:
        print("Daemon not running", file=sys.stderr)
        return 1

    # Request handlers info
    request = {"event": "_system", "hook_input": {"action": "handlers"}}
    response = send_daemon_request(socket_path, request)

    if response is None:
        return 1

    if "error" in response:
        print(f"ERROR: {response['error']}", file=sys.stderr)
        return 1

    result = response.get("result", {})
    handlers = result.get("handlers", {})

    # Machine-readable count for shell consumers (e.g. health-check.sh) so they
    # never have to scrape the human-formatted handler list.
    if getattr(args, "count", False):
        total = sum(len(handler_list) for handler_list in handlers.values())
        print(total)
        return 0

    if args.json:
        print(json.dumps(handlers, indent=2))
        return 0

    print("=== Registered Handlers ===\n")
    for event_type, handler_list in handlers.items():
        if not handler_list:
            continue
        print(f"{event_type}:")
        for handler in handler_list:
            terminal = "T" if handler.get("terminal", True) else "-"
            priority = handler.get("priority", 50)
            name = handler.get("name", "unknown")
            print(f"  [{terminal}] {priority:3d} {name}")
        print()

    return 0


def cmd_config(args: argparse.Namespace) -> int:
    """Show loaded configuration.

    Args:
        args: Command-line arguments

    Returns:
        0 if successful, 1 otherwise
    """
    try:
        project_path = get_project_path(getattr(args, "project_root", None))
    except SystemExit:
        # get_project_path already printed error message
        return 1

    config_path = project_path / ".claude" / "hooks-daemon.yaml"

    if not config_path.exists():
        print(f"No configuration file found at: {config_path}", file=sys.stderr)
        print("Run 'init-config' to create one", file=sys.stderr)
        return 1

    try:
        config = Config.load(config_path)
    except Exception as e:
        print(f"ERROR: Failed to load configuration: {e}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(config.model_dump(exclude_none=True), indent=2))
    else:
        print(f"Configuration file: {config_path}")
        print(f"Version: {config.version}")
        print("\n[Daemon]")
        print(f"  idle_timeout_seconds: {config.daemon.idle_timeout_seconds}")
        print(f"  log_level: {config.daemon.log_level.value}")
        print(f"  log_buffer_size: {config.daemon.log_buffer_size}")
        print(f"  request_timeout_seconds: {config.daemon.request_timeout_seconds}")

        from claude_code_hooks_daemon.config.models import HandlerConfig, HandlersConfig

        print("\n[Handlers]")
        # Derive the event-type list from the model class's own fields (SSoT) so
        # a group like status_line can never be silently dropped from the summary
        # (which previously hid the effective enabled/disabled state of every
        # status-line handler from introspection). Referencing the class rather
        # than ``type(config.handlers)`` keeps this working regardless of how the
        # config was constructed.
        for event_type in HandlersConfig.model_fields:
            handlers = getattr(config.handlers, event_type, {})
            if not isinstance(handlers, dict) or not handlers:
                continue
            print(f"  {event_type}:")
            for name, handler_config in handlers.items():
                # Tag-filter keys (enable_tags / disable_tags) are lists, not
                # HandlerConfig — surface them without the enabled/priority shape.
                if not isinstance(handler_config, HandlerConfig):
                    print(f"    {name}: {handler_config}")
                    continue
                enabled = "enabled" if handler_config.enabled else "disabled"
                priority = (
                    f"priority={handler_config.priority}" if handler_config.priority else "default"
                )
                print(f"    {name}: {enabled}, {priority}")

        if config.plugins.paths or config.plugins.plugins:
            print("\n[Plugins]")
            for path in config.plugins.paths:
                print(f"  path: {path}")
            for plugin in config.plugins.plugins:
                enabled = "enabled" if plugin.enabled else "disabled"
                print(f"  plugin: {plugin.path} ({enabled})")

    return 0


def _get_current_mode(args: argparse.Namespace) -> dict[str, Any] | None:
    """Best-effort query of current daemon mode before restart.

    Returns the mode result dict or None on any failure.
    Uses early returns for each failure point — restart must always proceed.

    Args:
        args: Command-line arguments (for project_root, socket/pid overrides)

    Returns:
        Mode result dict with 'mode' and 'custom_message' keys, or None
    """
    project_path = get_project_path(getattr(args, "project_root", None))
    socket_path = _resolve_socket_path(args, project_path)
    pid_path = _resolve_pid_path(args, project_path)

    pid = read_pid_file(str(pid_path))
    if pid is None:
        return None

    request = {"event": "_system", "hook_input": {"action": "get_mode"}}
    response = send_daemon_request(socket_path, request)

    if response is None or "error" in response:
        return None

    return cast("dict[str, Any]", response.get("result"))


def _print_mode_advisory(pre_mode: dict[str, Any]) -> None:
    """Print mode status advisory after restart.

    Only prints when the pre-restart mode was non-default, since that means
    the mode was lost during restart and the user needs to know.

    Args:
        pre_mode: Mode result dict from _get_current_mode
    """
    mode = pre_mode.get("mode", DaemonMode.DEFAULT.value)
    if mode == DaemonMode.DEFAULT.value:
        return

    custom_message = pre_mode.get("custom_message")

    print(f"\nMode before restart: {mode}", end="")
    if custom_message:
        print(f' (message: "{custom_message}")')
    else:
        print()
    print(f"Mode after restart:  {DaemonMode.DEFAULT.value} (reset to config default)")

    restore_cmd = f"  set-mode {mode}"
    if custom_message:
        restore_cmd += f' -m "{custom_message}"'
    print(f"\nTo restore previous mode:\n{restore_cmd}")


def cmd_restart(args: argparse.Namespace) -> int:
    """Restart daemon (stop + start).

    Queries the current mode before stopping so it can print an advisory
    if a non-default mode was active (since mode resets on restart).

    Args:
        args: Command-line arguments

    Returns:
        0 if daemon restarted successfully, 1 otherwise
    """
    # Query current mode before stopping (best-effort, ignore failures)
    pre_mode = _get_current_mode(args)

    # Stop daemon. If stop fails the old daemon may still be alive; starting
    # then would hit cmd_start's REUSE gate ("Daemon already running", exit 0)
    # and restart would FALSELY report success while the OLD code keeps
    # running. Fail fast: abort with the stop return code and never start.
    stop_rc = cmd_stop(args)
    if stop_rc != 0:
        print(
            "ERROR: failed to stop the running daemon; aborting restart so a "
            "stale daemon is not left running undetected",
            file=sys.stderr,
        )
        return stop_rc

    # Start daemon
    time.sleep(0.5)  # Brief delay between stop and start
    result = cmd_start(args)

    # After successful start, print mode advisory if non-default mode was lost
    if result == 0 and pre_mode is not None:
        _print_mode_advisory(pre_mode)

    return result


def cmd_repair(args: argparse.Namespace) -> int:
    """Repair venv by running uv sync.

    Fixes broken venvs caused by environment switching (container/host),
    Python version changes, or stale editable install .pth files.

    Args:
        args: Command-line arguments

    Returns:
        0 if repair succeeded, 1 otherwise
    """
    project_root = get_project_path(getattr(args, "project_root", None))

    print("Repairing venv...")

    # Stop daemon first if running
    pid_path = _resolve_pid_path(args, project_root)
    pid = read_pid_file(str(pid_path))
    if pid is not None:
        print("Stopping running daemon first...")
        cmd_stop(args)
        time.sleep(0.5)

    # Plan 00099: target the current Python-environment's fingerprint-keyed
    # venv so concurrent environments (container vs host, different Pythons)
    # each repair their own venv without clobbering the other.
    venv_path = get_venv_path(project_root)
    env = os.environ.copy()
    env["UV_PROJECT_ENVIRONMENT"] = str(venv_path)

    try:
        result = subprocess.run(  # nosec B603 B607 - uv is trusted tool, no user input
            ["uv", "sync"],
            cwd=str(project_root),
            env=env,
            capture_output=True,
            text=True,
            timeout=_UV_SYNC_TIMEOUT_SECONDS,
        )
        if result.returncode != 0:
            print(f"ERROR: uv sync failed (exit {result.returncode})")
            if result.stderr:
                print(result.stderr)
            return 1

        print("Venv repaired successfully.")

        # Verify the repair worked
        venv_python = venv_path / "bin" / "python"
        verify = subprocess.run(  # nosec B603 - venv python with hardcoded import check
            [str(venv_python), "-c", "import claude_code_hooks_daemon; print('OK')"],
            capture_output=True,
            text=True,
            timeout=_VERIFY_IMPORT_TIMEOUT_SECONDS,
        )
        if verify.returncode == 0:
            print("Verification: import claude_code_hooks_daemon OK")
        else:
            print("WARNING: Venv repaired but import check failed:")
            print(verify.stderr)
            return 1

        return 0

    except FileNotFoundError:
        print(
            "ERROR: 'uv' not found. Install with: curl -LsSf https://astral.sh/uv/install.sh | sh"
        )
        return 1
    except subprocess.TimeoutExpired as exc:
        # The same handler covers both bounded subprocesses (uv sync and the
        # import verification). Name the timed-out command rather than always
        # blaming uv sync.
        timed_out = exc.cmd if isinstance(exc.cmd, str) else " ".join(map(str, exc.cmd))
        print(f"ERROR: command timed out after {exc.timeout} seconds: {timed_out}")
        return 1


# Plan 00099: venv directories that the fingerprint-keyed scheme recognises.
# Any untracked/ subdirectory named "venv" or matching "venv-<fingerprint>/"
# is considered a candidate for listing and pruning.
_VENV_DIR_PREFIX = "venv"
_VENV_STAMP_FILENAME = ".daemon-version"
_LEGACY_VENV_DIR_NAME = "venv"


def _read_venv_stamp(venv_dir: Path) -> str:
    stamp = venv_dir / _VENV_STAMP_FILENAME
    if stamp.is_file():
        try:
            return stamp.read_text().strip()
        except OSError:
            return ""
    return ""


def _directory_size_bytes(path: Path) -> int:
    total = 0
    for entry in path.rglob("*"):
        try:
            if entry.is_file() and not entry.is_symlink():
                total += entry.stat().st_size
        except OSError as exc:
            print(
                f"warning: could not stat {entry} while sizing {path}: {exc}",
                file=sys.stderr,
            )
    return total


def _human_bytes(size: int) -> str:
    units = ["B", "KB", "MB", "GB"]
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def _daemon_untracked_dir(project_root: Path) -> Path:
    """Resolve the daemon's untracked directory for the current install mode.

    Self-install (dogfooding) keeps venvs at ``{project}/untracked/``; normal
    installs keep them at ``{project}/.claude/hooks-daemon/untracked/``.
    Detection mirrors ``ProjectContext``: presence of
    ``src/claude_code_hooks_daemon/`` at the project root signals self-install.
    """
    if (project_root / "src" / "claude_code_hooks_daemon").exists():
        return project_root / "untracked"
    return project_root / ".claude" / "hooks-daemon" / "untracked"


def _read_project_handler_health(
    project_path: Path,
) -> "ProjectHandlerHealthState":
    """Read the daemon's persisted project-handler load-failure state (Plan 00143).

    Resolves the state file deterministically from the project root (no
    ProjectContext singleton dependency), so ``status`` / ``health`` / ``check``
    can surface a degraded-protection signal whenever the running daemon skipped
    a project handler at startup.
    """
    from claude_code_hooks_daemon.daemon.project_handler_health import (
        read_load_failures_at,
    )

    return read_load_failures_at(_daemon_untracked_dir(project_path))


def _load_project_handlers(config: "Config", project_path: Path) -> list[Any]:
    """Discover this project's own handler instances for a generator.

    Shared by ``generate-docs`` and ``generate-playbook``. It is factored out
    because those two had drifted: ``generate-docs`` loaded project handlers and
    ``generate-playbook`` did not, so every project-handler acceptance test was
    silently absent from the release gate while the generator's branch for them
    sat there fully tested and never reached. Two copies of five lines is how
    that happened, so there is now one copy.

    Returns an empty list when project handlers are disabled or the configured
    directory does not exist — neither is an error, and a generator with nothing
    to add must still render the rest of the document.
    """
    if not config.project_handlers.enabled:
        return []

    from claude_code_hooks_daemon.handlers.project_loader import ProjectHandlerLoader

    handlers_path = Path(config.project_handlers.path)
    if not handlers_path.is_absolute():
        handlers_path = project_path / handlers_path
    if not handlers_path.exists():
        return []

    discovered = ProjectHandlerLoader.discover_handlers(handlers_path)
    return [handler for _event_type, handler in discovered]


def _format_project_handler_health_lines(
    state: "ProjectHandlerHealthState",
) -> list[str]:
    """Format the project-handler health section shared by status/health/check.

    Returns a loud degraded block when handlers failed to load, or a single
    OK line when clean. Single source of truth so all three commands agree.
    """
    if not state.is_degraded:
        return ["  OK — all project handlers loaded"]

    lines = [
        f"  DEGRADED — {state.failed_count} project handler(s) FAILED to load "
        "and are NOT protecting this session:",
    ]
    for failure in state.failures:
        lines.append(f"    ⚠️  {failure.event_dir}/{failure.filename} ({failure.reason})")
    lines.append(
        "  Fix the handler(s), then restart the daemon — the signal clears only "
        "after a restart reloads them. Diagnose with: "
        f"{daemon_cli_command('validate-project-handlers')}"
    )
    return lines


def _resolver_active_venv_realpath(project_root: Path) -> Path | None:
    """Return the realpath of the venv the bootstrap resolver would actually use.

    ``resolve_existing_venv_python`` is the SAME resolver the daemon and the
    bash hook forwarders call to pick a venv at runtime (Plan 00184). It can
    disagree with ``python_venv_fingerprint``-based accounting when the
    fingerprint scheme has migrated and a stale-named symlink is left
    pointing at the venv still actually in use. Resolving to the realpath
    (following any symlink) lets venv-accounting protect whichever directory
    is truly live, regardless of which name currently points at it.

    Returns ``None`` when the resolver has nothing usable (e.g. brand-new
    project with no venv provisioned yet) — accounting callers should treat
    that as "nothing is currently active".
    """
    # ``resolve_existing_venv_python`` never raises: it returns a best-effort
    # path, and its override/legacy branches are returned WITHOUT an existence
    # check. So a non-existent result IS the "no venv provisioned yet" signal --
    # there is no exception to catch and no error being hidden.
    python_path = resolve_existing_venv_python(project_root)
    if not python_path.exists():
        return None
    return python_path.resolve().parent.parent


def _enumerate_venvs(project_root: Path, include_size: bool = True) -> list[dict[str, Any]]:
    """Return metadata dicts for every venv directory under the daemon's untracked/.

    Detects both fingerprint-keyed ``venv-<fp>/`` and legacy ``venv/`` paths.
    Each entry: fingerprint, path, real_path, is_symlink, stamped_version,
    size_bytes, is_current, is_legacy.

    ``include_size=False`` skips the (potentially expensive, ~187 MB) recursive
    directory walk and reports ``size_bytes=0`` — used on the hot daemon-start
    path where only cheap name/stamp fields are needed to SELECT reclaimable
    venvs before sizing just those (Plan 00181 Task 4.2).

    Plan 00184: a venv directory name may be a SYMLINK to another venv
    directory under the same ``untracked/`` (e.g. left behind by a
    fingerprint-scheme migration). Entries whose realpath coincides are
    DEDUPED to a single entry (preferring the real, non-symlink directory) so
    the same bytes are never counted twice. ``is_current`` is the UNION of the
    fingerprint-match predicate and "this is the venv the bootstrap resolver
    (``resolve_existing_venv_python``) actually selects" — the latter is the
    one the running daemon and hook forwarders truly use, and must never be
    silently unprotected merely because its directory name's fingerprint
    doesn't match the current interpreter's fingerprint.
    """
    untracked = _daemon_untracked_dir(project_root)
    if not untracked.is_dir():
        return []

    current_fp = python_venv_fingerprint(project_root)
    resolver_active_realpath = _resolver_active_venv_realpath(project_root)
    raw_entries: list[dict[str, Any]] = []

    for child in sorted(untracked.iterdir()):
        if not child.is_dir():
            continue
        name = child.name
        if name == _LEGACY_VENV_DIR_NAME:
            fingerprint = ""
            is_legacy = True
        elif name.startswith(_VENV_DIR_PREFIX + "-"):
            fingerprint = name[len(_VENV_DIR_PREFIX) + 1 :]
            is_legacy = False
        else:
            continue

        python_bin = child / "bin" / "python"
        if not python_bin.exists():
            python_alt = child / "bin" / "python3"
            if not python_alt.exists():
                continue

        real_path = child.resolve()
        is_symlink = child.is_symlink()
        is_current = ((not is_legacy) and (fingerprint == current_fp)) or (
            resolver_active_realpath is not None and real_path == resolver_active_realpath
        )

        raw_entries.append(
            {
                "fingerprint": fingerprint,
                "path": str(child),
                "real_path": str(real_path),
                "is_symlink": is_symlink,
                "stamped_version": _read_venv_stamp(child),
                "size_bytes": _directory_size_bytes(child) if include_size else 0,
                "is_current": is_current,
                "is_legacy": is_legacy,
            }
        )

    # Dedupe entries that resolve to the same real directory (symlink + its
    # target both scanned as separate names). Prefer the entry whose own name
    # is NOT a symlink (the real directory); ties broken by iteration order
    # (already sorted by name), so the choice is deterministic.
    deduped: dict[str, dict[str, Any]] = {}
    for entry in raw_entries:
        real_path_key = entry["real_path"]
        existing = deduped.get(real_path_key)
        if existing is None:
            deduped[real_path_key] = entry
            continue
        if existing["is_symlink"] and not entry["is_symlink"]:
            deduped[real_path_key] = entry
        # else: keep the existing (already non-symlink, or first-seen tie)

    return list(deduped.values())


def _reclaimable_venv_entries(
    entries: list[dict[str, Any]], current_stamp: str
) -> list[dict[str, Any]]:
    """Select venvs that are safe to FLAG as reclaimable (never the current one).

    A venv is reclaimable if it is the legacy ``venv/`` (pre-v3.7.0 layout,
    always superseded) or a non-current fingerprint venv whose stamped daemon
    version differs from the current env's stamp. Mirrors the ``prune-venvs
    --legacy`` / ``--stale`` predicates so the advisory and the destructive
    command agree on what "stale" means. The current-fingerprint venv is never
    included. This only FLAGS — deletion stays the operator's explicit,
    guarded ``prune-venvs`` action (Plan 00181 Decision 1).
    """
    reclaimable: list[dict[str, Any]] = []
    for entry in entries:
        if entry["is_current"]:
            continue
        if entry["is_symlink"]:
            # A symlink venv name is never itself deletable content — its
            # target is either the deduped real entry (already excluded when
            # current) or a foreign path outside this accounting (Plan 00184).
            continue
        if entry["is_legacy"]:
            reclaimable.append(entry)
            continue
        if current_stamp and entry["stamped_version"] and entry["stamped_version"] != current_stamp:
            reclaimable.append(entry)
    return reclaimable


def _stale_venv_advisory(project_root: Path) -> str | None:
    """Build a daemon-start advisory about reclaimable stale/legacy venvs.

    SURFACE, don't delete (Plan 00181 Decision 1): auto-deleting venvs is unsafe
    in the multi-container shared-``untracked/`` model — no filesystem signal
    proves a peer is not using a given-fingerprint venv — so the daemon only
    reports the reclaimable space and points at the guarded ``prune-venvs``
    command. Sizing is lazy: the cheap ``include_size=False`` enumeration
    SELECTS candidates first, then only the reclaimable venvs are walked for
    their size, so the common "nothing to reclaim" case does zero disk walks on
    the hot start path.

    Returns the advisory string, or ``None`` when there is nothing to reclaim.
    """
    entries = _enumerate_venvs(project_root, include_size=False)
    if not entries:
        return None

    current_stamp = ""
    for entry in entries:
        if entry["is_current"]:
            current_stamp = entry["stamped_version"]
            break

    reclaimable = _reclaimable_venv_entries(entries, current_stamp)
    if not reclaimable:
        return None

    total_bytes = sum(_directory_size_bytes(Path(entry["path"])) for entry in reclaimable)
    count = len(reclaimable)
    plural = "s" if count != 1 else ""
    return (
        f"💿 {count} stale/legacy venv{plural} ({_human_bytes(total_bytes)}) can be "
        f"reclaimed. Run `prune-venvs --stale --force` (legacy: `--legacy`) to remove "
        f"them — the daemon never deletes venvs automatically."
    )


# Known accumulating writers under the daemon untracked dir (Plan 00181). Each
# entry is (display_name, path-relative-to-untracked, is_dir). These are the
# paths the retention work in this plan bounds; the disk-usage report sums them
# so the operator can see accumulation and what a prune would reclaim.
_DISK_USAGE_WRITERS: tuple[tuple[str, str, bool], ...] = (
    ("transcripts", "transcripts", True),
    ("thread-registry", "thread-registry", True),
    ("context-sidecar", "context-sidecar", True),
    ("payload-capture", "payload-capture", True),
    ("logs/hooks", "logs/hooks", True),
    ("supervise/decision.log", "supervise/decision.log", False),
    ("hook-errors.log", "hook-errors.log", False),
)
_HOOK_ERROR_BACKUP_GLOB = "hook-errors.log.*"


def _collect_disk_usage(project_root: Path) -> list[dict[str, Any]]:
    """Report per-writer accumulation under the daemon untracked dir.

    Pure reporting (Plan 00181 Task 5.1) — never deletes anything. Each row is
    ``{name, path, size_bytes, reclaimable_bytes}``. Missing paths report size 0
    rather than raising, so the report is robust on a fresh project. Sizes for
    the auto-reaped writers are informational (they are bounded automatically);
    ``reclaimable_bytes`` is populated for the operator-actionable items —
    rotated ``hook-errors.log.*`` backups and stale/legacy venvs.
    """
    untracked = _daemon_untracked_dir(project_root)
    rows: list[dict[str, Any]] = []

    for name, rel, is_dir in _DISK_USAGE_WRITERS:
        target = untracked / rel
        if is_dir:
            size = _directory_size_bytes(target) if target.is_dir() else 0
        else:
            size = target.stat().st_size if target.is_file() else 0
        rows.append({"name": name, "path": str(target), "size_bytes": size, "reclaimable_bytes": 0})

    # Rotated hook-errors.log backups are fully reclaimable (the live log is the
    # only one that matters); they are already count/age-bounded on rotation.
    backups = sorted(untracked.glob(_HOOK_ERROR_BACKUP_GLOB)) if untracked.is_dir() else []
    backup_size = 0
    for backup in backups:
        if backup.is_file():
            backup_size += backup.stat().st_size
    rows.append(
        {
            "name": "hook-errors.log.* backups",
            "path": str(untracked),
            "size_bytes": backup_size,
            "reclaimable_bytes": backup_size,
        }
    )

    # Venvs: total footprint plus what `prune-venvs` would reclaim (stale/legacy,
    # never the current fingerprint). This is the biggest single number.
    entries = _enumerate_venvs(project_root)
    current_stamp = ""
    for entry in entries:
        if entry["is_current"]:
            current_stamp = entry["stamped_version"]
            break
    reclaimable = _reclaimable_venv_entries(entries, current_stamp)
    rows.append(
        {
            "name": "venvs",
            "path": str(untracked),
            "size_bytes": sum(entry["size_bytes"] for entry in entries),
            "reclaimable_bytes": sum(entry["size_bytes"] for entry in reclaimable),
        }
    )

    return rows


def cmd_disk_usage(args: argparse.Namespace) -> int:
    """Report daemon untracked/ disk accumulation and reclaimable space.

    Read-only (Plan 00181 Task 5.1): never deletes. ``--json`` emits the raw
    rows; otherwise a human table with per-writer sizes, a reclaimable column,
    and TOTAL / TOTAL-reclaimable footers, pointing at the guarded prune paths.
    """
    project_root = Path(get_project_path(getattr(args, "project_root", None)))
    rows = _collect_disk_usage(project_root)

    if getattr(args, "json", False):
        print(json.dumps(rows, indent=2))
        return 0

    total = sum(row["size_bytes"] for row in rows)
    total_reclaimable = sum(row["reclaimable_bytes"] for row in rows)

    print(f"Daemon untracked/ disk usage — {_daemon_untracked_dir(project_root)}")
    print()
    print(f"{'Writer':<28} {'Size':>12} {'Reclaimable':>14}")
    print("-" * 56)
    for row in rows:
        reclaimable = _human_bytes(row["reclaimable_bytes"]) if row["reclaimable_bytes"] else "-"
        print(f"{row['name']:<28} {_human_bytes(row['size_bytes']):>12} {reclaimable:>14}")
    print("-" * 56)
    print(f"{'TOTAL':<28} {_human_bytes(total):>12} {_human_bytes(total_reclaimable):>14}")
    print()
    print(
        "Auto-reaped writers (transcripts, thread-registry, context-sidecar, "
        "payload-capture, logs, decision.log) are bounded on daemon start."
    )
    print(
        "Reclaim venvs with `prune-venvs --stale --force` (legacy: `--legacy`) — "
        "the daemon never deletes venvs automatically."
    )
    return 0


def cmd_check_permissions(args: argparse.Namespace) -> int:
    """Report (and optionally fix) group/other-writable daemon artefacts.

    Plan 00239. The daemon formerly daemonised with ``umask(0)``, so everything
    it created landed world-writable. Fixing the umask governs future creates and
    retro-fixes nothing, so an already-deployed daemon keeps its exposed files
    until this is run — which is why the fix needs a batch guard as well as a
    write-time one.

    Exits 1 while findings remain, so it is usable as a CI / upgrade gate.
    ``--fix`` strips group and other bits (owner bits untouched, so directories
    stay traversable).
    """
    project_root = Path(get_project_path(getattr(args, "project_root", None)))
    untracked_dir = _daemon_untracked_dir(project_root)
    # The socket is deliberately 0660 via an explicit post-bind chmod.
    findings = audit_untracked_permissions(untracked_dir, exempt=[get_socket_path(project_root)])

    if not findings:
        print(f"No group/other-writable daemon artefacts under {untracked_dir}")
        return 0

    print(f"Group/other-writable daemon artefacts under {untracked_dir}:")
    print()
    for finding in findings:
        print(f"  {finding.describe()}")
    print()

    if not getattr(args, "fix", False):
        print(f"{len(findings)} finding(s). Re-run with --fix to strip group/other bits.")
        print(
            "These predate the umask fix: a umask governs creates, so existing "
            "files keep the mode they were created with."
        )
        return 1

    changed = tighten_permissions(findings)
    print(f"Tightened {len(changed)} of {len(findings)} artefact(s) to owner-only.")
    remaining = audit_untracked_permissions(untracked_dir, exempt=[get_socket_path(project_root)])
    if remaining:
        print(f"WARNING: {len(remaining)} artefact(s) could not be tightened.")
        return 1
    return 0


def cmd_list_venvs(args: argparse.Namespace) -> int:
    """List all Plan 00099 fingerprint-keyed venvs (plus any legacy venv).

    Args:
        args: Command-line arguments; ``--json`` emits machine-readable output.

    Returns:
        0 on success.
    """
    project_root = Path(get_project_path(getattr(args, "project_root", None)))
    entries = _enumerate_venvs(project_root)
    as_json = getattr(args, "json", False)

    if as_json:
        print(json.dumps(entries, indent=2))
        return 0

    if not entries:
        print(f"No venvs found under {_daemon_untracked_dir(project_root)}/.")
        return 0

    current_fp = python_venv_fingerprint(project_root)
    print(f"Current Python-env fingerprint: {current_fp}")
    print()
    print(f"{'Fingerprint':<20} {'Stamp':<10} {'Size':>10}  {'Marker':<8} Path")
    print("-" * 80)
    for entry in entries:
        marker = "← current" if entry["is_current"] else ("legacy" if entry["is_legacy"] else "")
        fp_display = entry["fingerprint"] or "(legacy)"
        print(
            f"{fp_display:<20} {entry['stamped_version'] or '-':<10} "
            f"{_human_bytes(entry['size_bytes']):>10}  {marker:<8} {entry['path']}"
        )
    return 0


def cmd_prune_venvs(args: argparse.Namespace) -> int:
    """Delete stale / legacy Plan 00099 venvs.

    Selection flags (at least one required):
      --legacy                 remove untracked/venv/ (pre-v3.7.0 layout)
      --all-except-current     remove every venv-<fp>/ whose fp != current
      --stale                  remove venvs whose stamped daemon version
                               differs from the current env's stamp

    Safety flags:
      --dry-run   print the removal plan without touching the filesystem
      --force     required for actual deletion (plus at least one selection flag)

    The current Python-env's fingerprint-keyed venv is NEVER deleted.

    Plan 00100 Task 3.9: ``scripts/upgrade_version.sh`` invokes
    ``eager_cleanup_stale_venvs`` automatically after a verified daemon
    restart, so ``hooks-daemon upgrade`` leaves exactly one ``venv-*/``
    survivor with no manual intervention. ``prune-venvs --all-except-current``
    remains available for manual eager cleanup outside the upgrade flow
    (e.g. recovery after an interrupted upgrade).
    """
    project_root = Path(get_project_path(getattr(args, "project_root", None)))
    entries = _enumerate_venvs(project_root)

    select_legacy = getattr(args, "legacy", False)
    select_all_except_current = getattr(args, "all_except_current", False)
    select_stale = getattr(args, "stale", False)
    dry_run = getattr(args, "dry_run", False)
    force = getattr(args, "force", False)

    if not (select_legacy or select_all_except_current or select_stale):
        print(
            "ERROR: pass at least one of --legacy, --all-except-current, --stale",
            file=sys.stderr,
        )
        return 1

    if not force and not dry_run:
        print(
            "ERROR: destructive operation — pass --dry-run to preview or --force to proceed",
            file=sys.stderr,
        )
        return 1

    current_fp = python_venv_fingerprint(project_root)
    current_stamp = ""
    for entry in entries:
        if entry["is_current"]:
            current_stamp = entry["stamped_version"]
            break

    resolver_active_realpath = _resolver_active_venv_realpath(project_root)

    to_remove: list[dict[str, Any]] = []
    for entry in entries:
        if entry["is_current"]:
            continue  # never touch current fingerprint
        if entry["is_symlink"]:
            print(f"Skipping {entry['path']}: symlink", file=sys.stderr)
            continue
        if (
            resolver_active_realpath is not None
            and Path(entry["real_path"]) == resolver_active_realpath
        ):
            print(f"Skipping {entry['path']}: resolver-active venv", file=sys.stderr)
            continue
        chosen = False
        if select_legacy and entry["is_legacy"]:
            chosen = True
        if select_all_except_current and not entry["is_legacy"]:
            chosen = True
        if (
            select_stale
            and not entry["is_legacy"]
            and current_stamp
            and entry["stamped_version"]
            and entry["stamped_version"] != current_stamp
        ):
            chosen = True
        if chosen:
            to_remove.append(entry)

    if not to_remove:
        print("Nothing to prune. Current venv:", current_fp)
        return 0

    print(f"{'(dry-run) ' if dry_run else ''}Pruning {len(to_remove)} venv(s):")
    for entry in to_remove:
        label = entry["fingerprint"] or "(legacy)"
        print(f"  - {label:<20} {_human_bytes(entry['size_bytes']):>10}  {entry['path']}")

    if dry_run:
        print("(dry-run) No changes made.")
        return 0

    failures = 0
    for entry in to_remove:
        try:
            shutil.rmtree(entry["path"])
        except OSError as exc:
            print(f"ERROR removing {entry['path']}: {exc}", file=sys.stderr)
            failures += 1
    if failures:
        return 1
    print(f"Removed {len(to_remove)} venv(s). Current venv preserved: {current_fp}")
    return 0


def cmd_write_venv_metadata(args: argparse.Namespace) -> int:
    """Write ``.daemon-metadata.json`` inside a freshly-provisioned venv.

    Plan 00100 Task 3.3: bash ``ensure_venv`` shells out to this after
    ``uv sync`` so the schema lives in one place (the Pydantic model in
    ``paths.py``) and bash never reimplements it. The metadata gives the
    daemon's startup resolver an authoritative ``python_path`` and a
    ``lock_hash`` to compare against the current project state.
    """
    venv_path = Path(args.venv_path)
    if not venv_path.is_dir():
        print(f"ERROR: venv path does not exist: {venv_path}", file=sys.stderr)
        return 1
    python_binary = venv_path / "bin" / "python"
    if not python_binary.is_file():
        print(f"ERROR: no bin/python inside venv: {venv_path}", file=sys.stderr)
        return 1

    project_root = Path(args.project_root) if args.project_root else Path.cwd()

    try:
        lock_hash = compute_project_lock_hash(project_root)
    except FileNotFoundError as exc:
        print(f"ERROR: cannot compute lock hash: {exc}", file=sys.stderr)
        return 1

    written_at = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        meta = DaemonVenvMetadata(
            python_path=str(python_binary),
            fingerprint=args.fingerprint,
            lock_hash=lock_hash,
            daemon_version=args.daemon_version,
            written_at=written_at,
        )
    except PydanticValidationError as exc:
        print(f"ERROR: metadata failed schema validation: {exc}", file=sys.stderr)
        return 1

    try:
        write_daemon_metadata(venv_path, meta)
    except OSError as exc:
        print(f"ERROR: failed to write metadata: {exc}", file=sys.stderr)
        return 1

    return 0


def cmd_init_config(args: argparse.Namespace) -> int:
    """Generate configuration template.

    Args:
        args: Command-line arguments with mode (minimal/full)

    Returns:
        0 if config generated successfully, 1 otherwise
    """
    try:
        project_path = get_project_path(getattr(args, "project_root", None))
    except SystemExit:
        # If validation fails but --force is set, we'll overwrite the bad config anyway
        # Otherwise, get_project_path already printed error message
        if not args.force:
            return 1
        # With --force, continue with project_root from args
        project_path = args.project_root
        if project_path is None:
            # Try to find .claude directory
            current = Path.cwd()
            while current != current.parent:
                if (current / ".claude").exists():
                    project_path = current
                    break
                current = current.parent
            if project_path is None:
                return 1

    config_path = project_path / ".claude" / "hooks-daemon.yaml"

    # Determine mode
    mode: Literal["minimal", "full"] = "minimal" if args.minimal else "full"

    # --stdout: print the template for review and write nothing. Reviewing the
    # available handlers is the common case on an EXISTING install, so this
    # deliberately runs BEFORE the exists/--force check — printing cannot
    # destroy anything, and requiring --force to read something would push the
    # reader toward a destructive flag for a read-only task.
    if getattr(args, "stdout", False):
        print(generate_config(mode=mode))
        return 0

    # Check if config already exists
    if config_path.exists() and not args.force:
        print(f"ERROR: Configuration file already exists: {config_path}", file=sys.stderr)
        print("Use --force to overwrite, or --stdout to review without writing", file=sys.stderr)
        return 1

    # Generate config
    config_yaml = generate_config(mode=mode)

    # Create .claude directory if needed
    config_path.parent.mkdir(parents=True, exist_ok=True)

    # Write config
    try:
        config_path.write_text(config_yaml)
        print(f"Generated {mode} configuration: {config_path}")
        print("\nNext steps:")
        print("1. Edit the configuration to enable desired handlers")
        print(f"2. Start the daemon: {daemon_cli_command('start')}")
        return 0
    except Exception as e:
        print(f"ERROR: Failed to write configuration: {e}", file=sys.stderr)
        return 1


def cmd_generate_playbook(args: argparse.Namespace) -> int:
    """Generate acceptance test playbook from handler definitions.

    Args:
        args: Command-line arguments with format, filter options, and include_disabled flag

    Returns:
        0 if playbook generated successfully, 1 otherwise
    """
    try:
        # Get project path
        project_path = get_project_path(getattr(args, "project_root", None))
    except SystemExit:
        # get_project_path already printed error message
        return 1

    config_path = project_path / ".claude" / "hooks-daemon.yaml"

    if not config_path.exists():
        print(f"No configuration file found at: {config_path}", file=sys.stderr)
        print("Run 'init-config' to create one", file=sys.stderr)
        return 1

    try:
        # Load configuration
        config = Config.load(config_path)

        # Create handler registry and discover handlers
        from claude_code_hooks_daemon.handlers.registry import HandlerRegistry

        registry = HandlerRegistry()
        registry.discover()

        # Load plugin handlers
        from claude_code_hooks_daemon.plugins.loader import PluginLoader

        plugins = PluginLoader.load_from_plugins_config(config.plugins, project_path)

        # Create playbook generator
        from claude_code_hooks_daemon.daemon.cli_acceptance_tests import get_cli_acceptance_tests
        from claude_code_hooks_daemon.daemon.playbook_generator import PlaybookGenerator

        # Convert HandlersConfig to dictionary
        handlers_dict = config.handlers.model_dump()

        generator = PlaybookGenerator(
            config=handlers_dict,
            registry=registry,
            plugins=plugins,
            project_handlers=_load_project_handlers(config, project_path),
            cli_acceptance_tests=get_cli_acceptance_tests(),
            pseudo_events=config.pseudo_events or None,
        )

        # Get command-line arguments
        include_disabled = getattr(args, "include_disabled", False)
        output_format = getattr(args, "format", "markdown")
        filter_type = getattr(args, "filter_type", None)
        filter_handler = getattr(args, "filter_handler", None)

        # Generate playbook in requested format
        if output_format == "json":
            tests = generator.generate_json(
                include_disabled=include_disabled,
                filter_type=filter_type,
                filter_handler=filter_handler,
            )
            print(json.dumps(tests, indent=2))
        else:
            # Markdown format (default)
            markdown = generator.generate_markdown(include_disabled=include_disabled)
            print(markdown)

        return 0

    except Exception as e:
        # Log the full traceback so the failure is diagnosable — the bare
        # exception string alone (e.g. a NoneType-vs-int TypeError from a
        # config that omits a handler priority) names nothing (Plan 00282).
        logger.exception("Failed to generate playbook")
        print(f"ERROR: Failed to generate playbook: {e}", file=sys.stderr)
        return 1


def cmd_generate_docs(args: argparse.Namespace) -> int:
    """Generate .claude/HOOKS-DAEMON.md from live config and handler metadata.

    Args:
        args: Command-line arguments with include_disabled and output options

    Returns:
        0 if docs generated successfully, 1 otherwise
    """
    try:
        # Get project path
        project_path = get_project_path(getattr(args, "project_root", None))
    except SystemExit:
        return 1

    config_path = project_path / ".claude" / "hooks-daemon.yaml"

    if not config_path.exists():
        print(f"No configuration file found at: {config_path}", file=sys.stderr)
        print("Run 'init-config' to create one", file=sys.stderr)
        return 1

    try:
        # Load configuration
        config = Config.load(config_path)

        # Create handler registry and discover handlers
        from claude_code_hooks_daemon.handlers.registry import HandlerRegistry

        registry = HandlerRegistry()
        registry.discover()

        # Load plugin handlers
        from claude_code_hooks_daemon.plugins.loader import PluginLoader

        plugins = PluginLoader.load_from_plugins_config(config.plugins, project_path)

        # Load project handlers (shared with generate-playbook — see the helper)
        project_handlers_list = _load_project_handlers(config, project_path)

        # Create docs generator
        from claude_code_hooks_daemon.daemon.docs_generator import DocsGenerator

        handlers_dict = config.handlers.model_dump()

        generator = DocsGenerator(
            config=handlers_dict,
            registry=registry,
            plugins=plugins,
            project_handlers=project_handlers_list,
            pseudo_events=config.pseudo_events or None,
        )

        include_disabled = getattr(args, "include_disabled", False)
        markdown = generator.generate_markdown(include_disabled=include_disabled)

        # Determine output path
        output_path = getattr(args, "output", None)
        if output_path:
            output_file = Path(output_path)
        else:
            output_file = project_path / ".claude" / "HOOKS-DAEMON.md"

        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(markdown)
        print(f"Generated: {output_file}")

        return 0

    except Exception as e:
        # Log the full traceback so the failure is diagnosable — the bare
        # exception string alone names neither the handler nor the site
        # (Plan 00282).
        logger.exception("Failed to generate docs")
        print(f"ERROR: Failed to generate docs: {e}", file=sys.stderr)
        return 1


def _build_handler_config_mapping(config: Config) -> dict[str, dict[str, Any]]:
    """Build the per-event handler_config mapping passed to ``register_all``.

    Derived from every field on the ``HandlersConfig`` model rather than a
    hand-maintained list inlined here, so any event type the model declares —
    ``status_line`` included, whose omission from the old inline list was the
    original bug — is covered automatically. A missing event type here makes
    ``register_all`` fall back to ``enabled=True`` for every handler in that
    group, which is exactly what made ``handlers.status_line.<name>.enabled:
    false`` inert.

    Caveat (not a total guarantee): the coverage is only as complete as
    ``HandlersConfig``'s own fields, which today declare a subset of all wired
    events (the ones with built-in handler directories). An event that gains
    built-in handlers without a matching ``HandlersConfig`` field would still
    be dropped here — ``test_cli_handler_config_mapping`` guards that case by
    asserting every on-disk handler directory appears in this mapping. See
    Plan 00172 for closing the model-vs-wired-events gap wholesale.

    Each event's values are ``HandlerConfig`` instances (coerced by the model);
    they are dumped to plain dicts because the registry reads them with
    ``dict.get(...)``. Tag-filter keys (``enable_tags`` / ``disable_tags``) are
    preserved as-is (lists), not dumped.

    Args:
        config: Loaded daemon configuration.

    Returns:
        Mapping of event-type config key -> {handler_key -> settings dict}.
    """
    from claude_code_hooks_daemon.config.models import HandlerConfig, HandlersConfig

    mapping: dict[str, dict[str, Any]] = {}
    for event_key in HandlersConfig.model_fields:
        event_config = getattr(config.handlers, event_key, {})
        if not isinstance(event_config, dict):
            continue
        mapping[event_key] = {
            handler_key: (value.model_dump() if isinstance(value, HandlerConfig) else value)
            for handler_key, value in event_config.items()
        }
    return mapping


def _build_initialised_controller(config: Config, project_path: Path) -> "DaemonController":
    """Build and fully initialise a DaemonController from a loaded config.

    Single source of truth for the per-event handler_config mapping and the
    ``initialise()`` call shared by daemon startup (``cmd_start``) and one-shot doc
    regeneration (``cmd_regenerate_docs``). Initialising the controller registers
    every active handler AND runs the ClaudeMdInjector, which regenerates the
    project CLAUDE.md ``<hooksdaemon>`` block as a side effect.

    Args:
        config: Loaded daemon configuration.
        project_path: Project root (workspace) the controller serves.

    Returns:
        The initialised DaemonController.
    """
    from claude_code_hooks_daemon.daemon.controller import DaemonController

    controller = DaemonController()
    handler_config = _build_handler_config_mapping(config)
    controller.initialise(
        handler_config,
        workspace_root=project_path,
        plugins_config=config.plugins,
        project_handlers_config=config.project_handlers,
        project_languages=config.daemon.languages,
        project_exclude_paths=config.daemon.exclude_paths,
        pseudo_events_config=config.pseudo_events or None,
        plan_workflow=config.plan_workflow,
        documentation=config.documentation,
        verdict_log=config.daemon.verdict_log,
    )
    return controller


def cmd_regenerate_docs(args: argparse.Namespace) -> int:
    """Force-regenerate both generated-doc artifacts in one shot.

    1. ``.claude/HOOKS-DAEMON.md`` — via the same DocsGenerator path as ``generate-docs``.
    2. The ``<hooksdaemon>`` guidance block in the project ``CLAUDE.md`` — via the same
       ClaudeMdInjector the daemon runs at startup (initialising a controller does this).

    Unlike ``restart``, this regenerates both artifacts without bouncing the running
    daemon — useful for resolving a git merge conflict that left stale or
    conflict-marked generated content.

    Args:
        args: Command-line arguments (include_disabled, output, project_root).

    Returns:
        0 if both artifacts regenerated successfully, 1 otherwise.
    """
    # Step 1: HOOKS-DAEMON.md. cmd_generate_docs handles project/config resolution and
    # prints its own status; a missing config returns 1 here and aborts before step 2.
    docs_result = cmd_generate_docs(args)
    if docs_result != 0:
        return docs_result

    # Step 2: the CLAUDE.md <hooksdaemon> block. Building + initialising a controller
    # runs the injector against the live handler set (identical to daemon startup).
    try:
        project_path = get_project_path(getattr(args, "project_root", None))
    except SystemExit:
        return 1

    config_path = project_path / ".claude" / "hooks-daemon.yaml"
    try:
        config = Config.load(config_path)
        _build_initialised_controller(config, project_path)
        print(f"Regenerated <hooksdaemon> block in: {project_path / 'CLAUDE.md'}")
        return 0
    except Exception as e:
        print(f"ERROR: Failed to regenerate CLAUDE.md guidance: {e}", file=sys.stderr)
        return 1


def cmd_config_diff(args: argparse.Namespace) -> int:
    """Run config diff operation.

    Args:
        args: Parsed CLI arguments with user_config and default_config paths

    Returns:
        0 on success, 1 on error
    """
    from claude_code_hooks_daemon.install.config_cli import run_config_diff

    try:
        result = run_config_diff(
            user_config_path=Path(args.user_config),
            default_config_path=Path(args.default_config),
        )
        print(json.dumps(result, indent=2))
        return 0
    except (FileNotFoundError, ValueError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


def cmd_config_merge(args: argparse.Namespace) -> int:
    """Run config merge operation.

    Args:
        args: Parsed CLI arguments with config paths

    Returns:
        0 on success, 1 on error
    """
    from claude_code_hooks_daemon.install.config_cli import run_config_merge

    try:
        result = run_config_merge(
            user_config_path=Path(args.user_config),
            old_default_config_path=Path(args.old_default_config),
            new_default_config_path=Path(args.new_default_config),
        )
        print(json.dumps(result, indent=2))
        return 0
    except (FileNotFoundError, ValueError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


def cmd_config_validate(args: argparse.Namespace) -> int:
    """Run config validation.

    Args:
        args: Parsed CLI arguments with config_path

    Returns:
        0 if valid, 1 if invalid or error
    """
    from claude_code_hooks_daemon.install.config_cli import run_config_validate

    try:
        result = run_config_validate(config_path=Path(args.config_path))
        print(json.dumps(result, indent=2))
        return 0 if result["valid"] else 1
    except (FileNotFoundError, ValueError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


def cmd_check_config_migrations(args: argparse.Namespace) -> int:
    """Run config migration advisory between two daemon versions.

    Compares manifests between --from and --to versions against the user's
    config file, reporting renamed keys still in use and new options available.

    Args:
        args: Parsed CLI arguments with from_version, to_version, config,
              format, and optional manifests_dir

    Returns:
        0 if no warnings or suggestions, 1 if warnings/suggestions present,
        2 on error
    """
    from claude_code_hooks_daemon.install.config_cli import (
        list_known_versions,
        run_check_config_migrations,
    )

    from_version: str = args.from_version
    to_version: str = args.to_version
    output_format: str = args.format

    # Resolve config path
    if args.config:
        config_path = Path(args.config)
    else:
        project_path = get_project_path(getattr(args, "project_root", None))
        config_path = project_path / ".claude" / "hooks-daemon.yaml"

    # Resolve optional manifests dir override
    manifests_dir: Path | None = (
        Path(args.manifests_dir) if getattr(args, "manifests_dir", None) else None
    )

    try:
        result = run_check_config_migrations(
            from_version=from_version,
            to_version=to_version,
            user_config_path=config_path,
            output_format=output_format,
            manifests_dir=manifests_dir,
        )
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    except ValueError as e:
        err_msg = str(e)
        print(f"ERROR: {err_msg}", file=sys.stderr)
        if "from_version" in err_msg or "to_version" in err_msg:
            known = list_known_versions(manifests_dir=manifests_dir)
            if known:
                print(f"Known versions: {', '.join(known)}", file=sys.stderr)
        return 2

    if output_format == "json":
        print(json.dumps(result, indent=2))
    else:
        print(result.get("text", ""))

    has_issues = result["has_warnings"] or result["has_suggestions"]
    return 1 if has_issues else 0


def cmd_check_worktree_seed(args: argparse.Namespace) -> int:
    """Report worktree seed config drift against the project's repository.

    Answers "is my seed config current NOW?", which no version-gated advisory
    can: the daemon's shipped default for seed entries is necessarily empty, so
    suggestions have to come from scanning the project itself.

    Reports only — nothing is written, because the config belongs to the project
    and a PyYAML round-trip would strip its comments.

    Args:
        args: Parsed CLI arguments with config, format, and optional
              project_root

    Returns:
        0 if the config is current, 1 if drift was found, 2 on error
    """
    from claude_code_hooks_daemon.install.config_cli import run_check_worktree_seed

    output_format: str = args.format
    project_path = resolve_tree_root(args)
    if project_path is None:
        return 2

    config_path = (
        Path(args.config) if args.config else project_path / ".claude" / "hooks-daemon.yaml"
    )

    try:
        result = run_check_worktree_seed(
            root=project_path,
            user_config_path=config_path,
            output_format=output_format,
        )
    except (FileNotFoundError, ValueError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    if output_format == "json":
        print(json.dumps(result, indent=2))
    else:
        print(result.get("text", ""))

    return 1 if result["has_drift"] else 0


def cmd_check_truth_changes(args: argparse.Namespace) -> int:
    """Show truth-changes (was → now) to reconcile across a version range.

    Loads truth-changes manifests in (from, to] and prints the aggregated
    was → now reconciliation list. Unlike check-config-migrations, this takes
    no user config — truth-changes are guidance, not compared against anything.

    Args:
        args: Parsed CLI arguments with from_version, to_version, format,
              and optional truth_changes_dir.

    Returns:
        0 if no truth-changes in range, 1 if changes present, 2 on error.
    """
    from claude_code_hooks_daemon.install.truth_changes import (
        list_known_truth_change_versions,
        run_check_truth_changes,
    )

    truth_changes_dir: Path | None = (
        Path(args.truth_changes_dir) if getattr(args, "truth_changes_dir", None) else None
    )

    try:
        result = run_check_truth_changes(
            from_version=args.from_version,
            to_version=args.to_version,
            output_format=args.format,
            truth_changes_dir=truth_changes_dir,
        )
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        known = list_known_truth_change_versions(truth_changes_dir=truth_changes_dir)
        if known:
            print(f"Known versions: {', '.join(known)}", file=sys.stderr)
        return 2

    if args.format == "json":
        print(json.dumps(result, indent=2))
    else:
        print(result.get("text", ""))

    return 1 if result["has_changes"] else 0


def cmd_harvest_background(args: argparse.Namespace) -> int:
    """Surface runaway background processes (Plan 00142, Layer B) — never kills.

    Samples ``ps``, applies resource budgets (CPU ceiling for ALL processes so
    reparented orphans are caught; wall-TTL for tracked commands), and
    prints each breach with a ready-to-run ``kill -- -<pgid>`` command for the
    AGENT to act on. The daemon performs no kill (owner steer, Decision 1).

    Returns:
        0 if no runaways, 1 if one or more breaches are surfaced, 2 on error.
    """
    from claude_code_hooks_daemon.core.project_context import ProjectContext
    from claude_code_hooks_daemon.daemon.background_harvester import (
        build_report,
        parse_ps_output,
        read_tracked_commands,
        run_ps,
    )

    _STATE_FILENAME = "background-processes.jsonl"
    if getattr(args, "state_file", None):
        state_file = Path(args.state_file)
    else:
        # Resolve the daemon's untracked dir without requiring a running daemon:
        # initialize ProjectContext from the project config when present (mirrors
        # cmd_start), else fall back to the self-install untracked location.
        project_path = get_project_path(getattr(args, "project_root", None))
        config_file = project_path / ".claude" / "hooks-daemon.yaml"
        if not ProjectContext._initialized and config_file.exists():
            ProjectContext.initialize(config_file)
        if ProjectContext._initialized:
            state_file = ProjectContext.daemon_untracked_dir() / _STATE_FILENAME
        else:
            state_file = project_path / "untracked" / _STATE_FILENAME

    try:
        ps_text = run_ps()
    except (OSError, subprocess.SubprocessError) as e:
        print(f"ERROR: could not run ps: {e}", file=sys.stderr)
        return 2

    records = parse_ps_output(ps_text)
    tracked = read_tracked_commands(state_file)
    # Never flag the harvester's own process group.
    own_pgid = os.getpgrp()

    report = build_report(
        records,
        max_wall_seconds=args.max_wall_seconds,
        max_cpu_percent=args.max_cpu_percent,
        min_cpu_runtime_seconds=args.min_cpu_runtime_seconds,
        tracked_commands=tracked,
        exclude_pgids=(own_pgid,),
    )

    if args.format == "json":
        print(json.dumps(report, indent=2))
    else:
        print(report["text"])

    return 1 if report["has_breaches"] else 0


def cmd_inject_goal(args: argparse.Namespace) -> int:
    """Write a ``<session>.goal-intent`` signal on demand (Plan 00269 Task 2.3).

    Manual fallback / primary debugging tool for supervisor goal injection.
    Writes the SAME signal the ``goal_injection`` PostToolUse handler writes,
    with ``source: cli``. The signal file is session-keyed, so the target
    session id is resolved from ``CLAUDE_CODE_SESSION_ID`` in the environment
    (set when run from a Claude Code Bash tool — the same variable the
    supervisor's own-session scan keys on); the command refuses with a clear
    message when it is unset or the ACTIVE plan folder does not exist
    (``Completed/`` plans are deliberately not matched — a goal for an
    archived plan is always a mistake).

    Returns:
        0 on signal written, 1 on refusal/failure.
    """
    import yaml

    from claude_code_hooks_daemon.core.project_context import ProjectContext
    from claude_code_hooks_daemon.handlers.post_tool_use.goal_injection import (
        _PLAN_NUMBER_RE,
        _SOURCE_CLI,
        extract_plan_title,
        render_goal_line,
        write_goal_signal,
    )

    plan_number = str(args.plan_number).strip()
    if not _PLAN_NUMBER_RE.match(plan_number):
        print(
            f"ERROR: '{plan_number}' is not a 5-digit plan number (e.g. 00269)",
            file=sys.stderr,
        )
        return 1

    session_id = os.environ.get("CLAUDE_CODE_SESSION_ID", "").strip()
    if not session_id:
        print(
            "ERROR: CLAUDE_CODE_SESSION_ID is not set. The goal signal is "
            "session-keyed, so inject-goal must run INSIDE the Claude Code "
            "session it should target (a Bash tool call sets the variable). "
            "Cross-session retargeting is not supported.",
            file=sys.stderr,
        )
        return 1

    if getattr(args, "project_root", None):
        project_path = Path(args.project_root).resolve()
    else:
        project_path = get_project_path(None)

    plan_root = project_path / "CLAUDE" / "Plan"
    plan_dir = next(
        (
            candidate
            for candidate in sorted(plan_root.glob(f"{plan_number}-*"))
            if candidate.is_dir() and (candidate / "PLAN.md").is_file()
        ),
        None,
    )
    if plan_dir is None:
        print(
            f"ERROR: no active plan folder {plan_number}-* with a PLAN.md under "
            f"{plan_root} (archived plans in Completed/ are deliberately not "
            "matched)",
            file=sys.stderr,
        )
        return 1

    try:
        plan_text = (plan_dir / "PLAN.md").read_text(encoding="utf-8")
    except OSError as e:
        print(f"ERROR: could not read {plan_dir / 'PLAN.md'}: {e}", file=sys.stderr)
        return 1

    # Load the handler's configured options (mode/lines) so the CLI renders
    # EXACTLY what the status-flip trigger would render.
    mode = "additive"
    raw_lines: object = None
    config_file = project_path / ".claude" / "hooks-daemon.yaml"
    if config_file.is_file():
        try:
            config_data = yaml.safe_load(config_file.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError) as e:
            print(f"WARNING: could not read {config_file}: {e}", file=sys.stderr)
            config_data = {}
        options = (
            config_data.get("handlers", {})
            .get("post_tool_use", {})
            .get("goal_injection", {})
            .get("options", {})
            if isinstance(config_data, dict)
            else {}
        )
        if isinstance(options, dict):
            mode = str(options.get("mode", mode))
            raw_lines = options.get("lines")

    # Initialise the project context UNCONDITIONALLY (no private-state peeking):
    # a repeat initialise raises RuntimeError, which simply means an earlier
    # step in this process already did it. A ValueError (missing/invalid config,
    # not a git repo) is remembered so a subsequent write failure can name the
    # REAL cause instead of pointing at the daemon log.
    context_init_error: str | None = None
    try:
        ProjectContext.initialize(config_file)
    except RuntimeError:
        logger.debug("inject-goal: project context already initialised; reusing it")
    except ValueError as e:
        context_init_error = str(e)
        print(f"WARNING: could not initialise project context: {e}", file=sys.stderr)

    joined = render_goal_line(
        plan_number,
        extract_plan_title(plan_text),
        str(plan_dir.relative_to(project_path)),
        mode=mode,
        raw_lines=raw_lines,
    )
    if joined is None:
        print("ERROR: goal message could not be rendered (see daemon log)", file=sys.stderr)
        return 1
    written = write_goal_signal(session_id, plan_number, joined, _SOURCE_CLI)
    if written is None:
        detail = (
            f" (project context unavailable: {context_init_error})"
            if context_init_error is not None
            else ""
        )
        print(f"ERROR: goal signal could not be written{detail}", file=sys.stderr)
        return 1
    print(f"Goal-intent signal written: {written}")
    print(f"Rendered goal line: {joined}")
    return 0


def _resolve_registered_handler_names(
    args: argparse.Namespace, project_path: Path
) -> list[str] | None:
    """Best-effort: the full set of currently-registered handler names.

    Only available when the daemon is actually running (queried the same way
    ``cmd_handlers`` does, over the socket) — reconstructing it offline would
    mean duplicating the whole config-load + controller-init path just for a
    report command. Returns ``None`` (not an error) when the daemon is not
    running, so ``aggregate_verdicts`` knows to report "unavailable" rather
    than a misleading empty "never fired" list.
    """
    pid_path = _resolve_pid_path(args, project_path)
    pid = read_pid_file(str(pid_path))
    if pid is None:
        return None

    socket_path = _resolve_socket_path(args, project_path)
    request = {"event": "_system", "hook_input": {"action": "handlers"}}
    response = send_daemon_request(socket_path, request)
    if response is None or "error" in response:
        return None

    handlers = response.get("result", {}).get("handlers", {})
    return _behavioural_handler_names(handlers)


def _behavioural_handler_names(handlers: dict[str, Any]) -> list[str]:
    """Registered handler names, excluding Status-event renderers.

    "Never fired" is a question about handlers that DECIDE. Status handlers
    render a line of text and can only ever return ``allow``, so their verdicts
    are not recorded at all (Plan 00234) — which would otherwise land every one
    of them in this report's never-fired roster and replace one misleading
    signal with another.

    The exclusion is unconditional, and stays correct even when
    ``verdict_log.record_status_events`` is on: never-fired is computed as
    registered-minus-fired, so dropping renderers from the registered side
    simply keeps them out of a roster they were never meaningful in.

    Args:
        handlers: The daemon's handler listing, keyed by event name.

    Returns:
        Handler names from every non-Status event, in listing order.
    """
    from claude_code_hooks_daemon.daemon.controller import PSEUDO_EVENT_HANDLERS_KEY

    names: list[str] = []
    for event_name, handler_list in handlers.items():
        if event_name == EventType.STATUS_LINE.value:
            continue
        # Pseudo-event handlers are excluded for the SAME reason as Status
        # renderers: their verdicts are never recorded, so counting them on
        # the registered side of `registered - fired` guarantees they appear
        # as never-fired forever. `_record_verdicts` runs BEFORE the pseudo
        # dispatch, and the pseudo results merge as HookResult, which carries
        # no per-handler verdict — so no pseudo verdict can reach the log at
        # all. Without this they were reported as dead handlers while firing
        # normally, which is the enumeration-surfaces-disagree class Plan
        # 00237 closed, reappearing in the report rather than the registry.
        if event_name == PSEUDO_EVENT_HANDLERS_KEY:
            continue
        for handler in handler_list:
            name = handler.get("name")
            if name:
                names.append(name)
    return names


def cmd_verdicts(args: argparse.Namespace) -> int:
    """Report on the handler verdict log (Plan 00209 Task 2.5).

    Answers the field report's concrete questions from parsed
    ``verdicts.jsonl`` records: per-handler fire counts, verdict mix,
    override rate, and (when the daemon is running) which registered
    handlers never fired at all.

    ``verdicts.jsonl`` is a bounded ROLLING SAMPLE, not a durable lifetime
    counter (Plan 00206 lesson) — every figure printed describes the
    RETAINED WINDOW only; ``format_report`` states this explicitly so the
    output can never be mistaken for lifetime totals.

    Returns:
        0 always — this is a report, not a pass/fail gate.
    """
    from claude_code_hooks_daemon.core.project_context import ProjectContext
    from claude_code_hooks_daemon.daemon.verdict_log import VERDICT_LOG_FILENAME
    from claude_code_hooks_daemon.daemon.verdict_report import (
        aggregate_verdicts,
        format_report,
        read_verdict_records,
    )

    if getattr(args, "log_file", None):
        log_path = Path(args.log_file)
        project_path = get_project_path(getattr(args, "project_root", None))
    else:
        project_path = get_project_path(getattr(args, "project_root", None))
        config_file = project_path / ".claude" / "hooks-daemon.yaml"
        if not ProjectContext._initialized and config_file.exists():
            ProjectContext.initialize(config_file)
        if ProjectContext._initialized:
            log_path = (
                ProjectContext.daemon_untracked_dir() / "logs" / "hooks" / VERDICT_LOG_FILENAME
            )
        else:
            log_path = project_path / "untracked" / "logs" / "hooks" / VERDICT_LOG_FILENAME

    records = read_verdict_records(log_path)
    all_handlers = _resolve_registered_handler_names(args, project_path)
    aggregate = aggregate_verdicts(records, all_handlers=all_handlers)

    if args.json:
        print(json.dumps(aggregate, indent=2))
    else:
        print(format_report(aggregate))

    return 0


# How many unique paths to print per unproven branch before summarising the
# rest. The point is to make the risk legible, not to dump a whole tree.
_UNPROVEN_PATH_PREVIEW = 10

# The word a human must type to consent to abandoning unmerged work. A single
# keystroke is too easy to fat-finger for a decision this size.
_ABANDON_CONFIRMATION_WORD = "abandon"


def _stdin_is_a_terminal() -> bool:
    """True when a human could actually answer a prompt on this stdin.

    An agent's Bash tool runs non-interactively, so this is False there — which
    is the entire mechanism by which abandonment stays human-gated.
    """
    stdin = sys.stdin
    if stdin is None:
        return False
    try:
        return stdin.isatty()
    except ValueError:
        # A closed stdin cannot be asked anything. That is an ANSWER (there is
        # no terminal), not a swallowed failure — the caller refuses on False.
        return False


def _confirm_abandonment_on_tty(
    classifications: "Sequence[BranchClassification]", reason: str
) -> bool:
    """Ask the human at the terminal to consent to abandoning unmerged work.

    Only ever reached when stdin is a real TTY. A declared ``--reason`` asserts
    *intent*; this asks for *consent*, and consent cannot be self-granted by
    the same party that wants the deletion.
    """
    from claude_code_hooks_daemon.daemon.branch_safety import TIER_UNPROVEN

    print("\nHUMAN CONFIRMATION REQUIRED", file=sys.stderr)
    print(
        "These branches hold file content that exists nowhere else in the "
        "repository. Deleting them abandons that work:",
        file=sys.stderr,
    )
    for c in classifications:
        if c.tier != TIER_UNPROVEN:
            continue
        print(
            f"  {c.name} — {len(c.content_unique_paths)} file(s) whose content "
            f"is found only on this branch",
            file=sys.stderr,
        )
    if reason:
        print(f"Declared reason: {reason}", file=sys.stderr)

    # The prompt goes to STDERR, not via input()'s own prompt argument, which
    # writes to stdout — that would inject prose into `--format json` output and
    # break a caller piping this to a JSON parser. Piping stdout does not stop
    # stdin being a terminal, so that combination is reachable, not theoretical.
    print(f"Type '{_ABANDON_CONFIRMATION_WORD}' to proceed: ", file=sys.stderr, end="")
    sys.stderr.flush()
    try:
        answer = input()
    except EOFError:
        # Ctrl-D is a person declining to answer. Treat it as a refusal rather
        # than letting a traceback stand in for the decision.
        print("\nNo answer given — treating as declined.", file=sys.stderr)
        return False
    return answer.strip().lower() == _ABANDON_CONFIRMATION_WORD


def cmd_delete_branch(args: argparse.Namespace) -> int:
    """Delete local branches only when their safety can be proven (Plan 00206).

    The sanctioned alternative to the force branch delete that
    ``destructive_git`` blocks. It performs strictly MORE verification than that
    flag: blocking preconditions first, then a tiered proof, then an
    all-or-nothing deletion behind a recovery bundle.

    Returns:
        0 if the requested branches were deleted (or dry-run classified), 1 if
        any branch was refused, 2 on a usage error.
    """
    from claude_code_hooks_daemon.daemon.branch_safety import (
        TIER_UNPROVEN,
        delete_branches,
    )

    repo = get_project_path(getattr(args, "project_root", None))
    bundle_path = None if args.no_bundle else Path(args.bundle)

    # Pass a confirmer ONLY when a human can actually answer it. Passing one
    # that always declines would report "a human declined" when in truth none
    # was ever asked — so a missing terminal is signalled by its absence, and
    # the engine says so precisely.
    confirm = _confirm_abandonment_on_tty if _stdin_is_a_terminal() else None

    try:
        report = delete_branches(
            repo,
            args.branches,
            protected_ref=args.protected_ref,
            allow_unproven=args.allow_unproven,
            reason=args.reason,
            bundle_path=bundle_path,
            dry_run=args.dry_run,
            confirm=confirm,
        )
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    except subprocess.CalledProcessError as e:
        # A git failure the engine could not classify — most importantly an
        # expired budget, which `run_git` reports as returncode 127 and `_git`
        # re-raises as this. Reported as a refusal because that is what it is:
        # nothing was deleted, and this command's entire design is that it
        # refuses when it cannot prove the work is recoverable. Letting the
        # traceback out instead would tell a human nothing and, worse, look like
        # the tool broke rather than declined (Plan 00248 F1).
        print(
            f"ERROR: git failed ({' '.join(str(part) for part in e.cmd)}) "
            f"with exit {e.returncode}; nothing was deleted. "
            f"{e.stderr.strip() if e.stderr else ''}".strip(),
            file=sys.stderr,
        )
        return 2

    if args.format == "json":
        print(
            json.dumps(
                {
                    "refused": report.refused,
                    "deleted": list(report.deleted),
                    "bundle": str(report.bundle) if report.bundle else None,
                    "blockers": list(report.blockers),
                    "classifications": [
                        {
                            "name": c.name,
                            "tier": c.tier,
                            "refusal": c.refusal,
                            "unique_commits": c.unique_commits,
                            "unique_paths": list(c.unique_paths),
                            "content_unique_paths": list(c.content_unique_paths),
                            "detail": c.detail,
                        }
                        for c in report.classifications
                    ],
                },
                indent=2,
            )
        )
        return 1 if report.refused else 0

    for c in report.classifications:
        verdict = c.refusal or c.tier
        print(f"  {c.name}: {verdict} — {c.detail}")
        if c.tier == TIER_UNPROVEN and c.content_unique_paths:
            # Show the CONTENT-unique files: these are the only ones whose
            # bytes disappear. A merely path-unique file is already safe.
            shown = c.content_unique_paths[:_UNPROVEN_PATH_PREVIEW]
            for path in shown:
                print(f"      content found only here: {path}")
            remaining = len(c.content_unique_paths) - len(shown)
            if remaining > 0:
                print(f"      ... and {remaining} more file(s) with unique content")

    if report.refused:
        # `refused` does NOT imply nothing happened. Plan 00249 made a partial
        # batch a real outcome — git can decline one branch after others are
        # already gone — and deliberately KEEPS the bundle in that case because it
        # is then the recovery route. This branch printed a hard-coded "nothing was
        # deleted" and returned before the bundle disclosure below, so it could
        # assert three untruths at once: that a deleted branch survived, that no
        # bundle existed, and that `--allow-unproven` was the remedy when nothing
        # was unproven (Plan 00253).
        if report.deleted:
            print(
                f"\nPARTIALLY REFUSED — {len(report.deleted)} branch(es) were "
                f"deleted before the refusal: {', '.join(report.deleted)}",
                file=sys.stderr,
            )
        else:
            print("\nREFUSED — nothing was deleted.", file=sys.stderr)
        print("Blockers:", file=sys.stderr)
        for blocker in report.blockers:
            print(f"  - {blocker}", file=sys.stderr)
        if report.bundle:
            # The ONLY recovery route for whatever was deleted above. Printed to
            # stderr so it travels with the refusal a human is reading.
            print(f"\nRecovery bundle: {report.bundle}", file=sys.stderr)
            print(
                f"  restore with: git fetch {report.bundle} <branch>:<branch>",
                file=sys.stderr,
            )
        if any(c.tier == TIER_UNPROVEN for c in report.classifications):
            # Only advise the escape hatch when it actually applies. Offering it
            # for a git refusal sends the reader to flags that cannot help.
            print(
                "\nA branch whose content cannot be proven recoverable is not "
                "deleted by default. Read the unique paths above, then re-run with "
                "--allow-unproven and --reason. Those flags declare intent; "
                "abandoning unmerged work also needs a human to consent at an "
                "interactive terminal, so an agent cannot complete this alone.",
                file=sys.stderr,
            )
        return 1

    if args.dry_run:
        print("\nDry run — nothing was deleted.")
        return 0

    if report.bundle:
        print(f"\nRecovery bundle: {report.bundle}")
        print(f"  restore with: git fetch {report.bundle} <branch>:<branch>")
    print(f"Deleted {len(report.deleted)} branch(es).")
    return 0


def cmd_release_notes(args: argparse.Namespace) -> int:
    """Show daemon release notes by version, range, latest, or list.

    Reads the per-version ``RELEASES/vX.Y.Z.md`` files that ship with every
    install. With no selection flag it shows the installed version's notes.

    Args:
        args: Parsed CLI arguments with optional version, from_version,
              to_version, list_versions, latest, format, and releases_dir.

    Returns:
        0 if notes were found, 1 if the requested notes are absent, 2 on a
        bad version range.
    """
    from claude_code_hooks_daemon.install.release_notes import (
        list_known_release_versions,
        run_release_notes,
    )
    from claude_code_hooks_daemon.version import __version__

    releases_dir: Path | None = (
        Path(args.releases_dir) if getattr(args, "releases_dir", None) else None
    )

    try:
        result = run_release_notes(
            version=getattr(args, "version", None),
            from_version=getattr(args, "from_version", None),
            to_version=getattr(args, "to_version", None),
            list_versions=getattr(args, "list_versions", False),
            latest=getattr(args, "latest", False),
            current_version=__version__,
            output_format=args.format,
            releases_dir=releases_dir,
        )
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        known = list_known_release_versions(releases_dir=releases_dir)
        if known:
            print(f"Known versions: {', '.join(known)}", file=sys.stderr)
        return 2

    if args.format == "json":
        print(json.dumps(result, indent=2))
    else:
        print(result.get("text", ""))

    return 0 if result["found"] else 1


def cmd_init_project_handlers(args: argparse.Namespace) -> int:
    """Scaffold project-handlers directory structure.

    Creates the convention-based directory structure for project-level handlers
    with example handler, tests, and conftest.py fixtures.

    Args:
        args: Command-line arguments with optional force flag

    Returns:
        0 if scaffolding created successfully, 1 otherwise
    """
    try:
        project_path = get_project_path(getattr(args, "project_root", None))
    except SystemExit:
        return 1

    handlers_dir = project_path / ".claude" / "project-handlers"

    # Check if directory already exists
    if handlers_dir.exists() and not getattr(args, "force", False):
        print(
            f"ERROR: Project handlers directory already exists: {handlers_dir}",
            file=sys.stderr,
        )
        print("Use --force to overwrite", file=sys.stderr)
        return 1

    # Create directory structure
    handlers_dir.mkdir(parents=True, exist_ok=True)
    (handlers_dir / "__init__.py").write_text('"""Project-level handlers for hooks daemon."""\n')

    # Create conftest.py with standard fixtures
    conftest_content = '''"""Shared test fixtures for project handlers."""

import sys
from pathlib import Path
from typing import Any

import pytest

# Add each event-type subdirectory to sys.path so co-located tests
# can import handler modules with --import-mode=importlib
_handlers_root = Path(__file__).resolve().parent
for _subdir in _handlers_root.iterdir():
    if _subdir.is_dir() and not _subdir.name.startswith("_"):
        sys.path.insert(0, str(_subdir))


@pytest.fixture
def bash_hook_input():
    """Factory fixture for creating Bash tool hook inputs."""

    def _make(command: str) -> dict[str, Any]:
        return {
            "tool_name": "Bash",
            "tool_input": {"command": command},
        }

    return _make


@pytest.fixture
def write_hook_input():
    """Factory fixture for creating Write tool hook inputs."""

    def _make(file_path: str, content: str = "") -> dict[str, Any]:
        return {
            "tool_name": "Write",
            "tool_input": {"file_path": file_path, "content": content},
        }

    return _make


@pytest.fixture
def edit_hook_input():
    """Factory fixture for creating Edit tool hook inputs."""

    def _make(
        file_path: str, old_string: str = "", new_string: str = ""
    ) -> dict[str, Any]:
        return {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": file_path,
                "old_string": old_string,
                "new_string": new_string,
            },
        }

    return _make
'''
    (handlers_dir / "conftest.py").write_text(conftest_content)

    # Create pre_tool_use subdirectory with example handler
    pre_tool_use_dir = handlers_dir / "pre_tool_use"
    pre_tool_use_dir.mkdir(exist_ok=True)
    (pre_tool_use_dir / "__init__.py").write_text("")

    example_handler_content = '''"""Example project handler - customise or replace this."""

from typing import Any

from claude_code_hooks_daemon.core import AcceptanceTest, GatingResult, TestType
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.core.hook_result import Decision


class ExampleHandler(PreToolUseHandlerBase):
    """Example advisory handler.

    This handler demonstrates the project handler pattern.
    Replace this with your own handler logic.

    Subclass the base named after YOUR event — every event has one in
    `claude_code_hooks_daemon.core.handler_bases`. This file lives in
    `pre_tool_use/`, so it uses `PreToolUseHandlerBase`, whose `handle()`
    returns a `GatingResult` (allow / deny / ask). `PostToolUseHandlerBase`,
    `StopHandlerBase` and `SubagentStopHandlerBase` return `BlockingResult`
    (allow / deny); every other event returns `AdvisoryResult` (allow only).

    That choice is not cosmetic: an event which cannot express a refusal
    DROPS one silently, so a deny returned from, say, a SessionStart handler
    produces a perfectly valid response with the refusal removed — the handler
    believes it blocked and nothing blocked. Using the event's base makes that
    a type error instead. Subclassing `Handler` directly still works if you
    prefer it.
    """

    def __init__(self) -> None:
        super().__init__(
            handler_id="example-project-handler",
            priority=50,
            terminal=False,
            tags=["project", "example"],
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Match condition - customise this."""
        tool_input = hook_input.get("tool_input", {})
        command = tool_input.get("command", "") if isinstance(tool_input, dict) else ""
        return "example-trigger" in command

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        """Handler logic - customise this."""
        return GatingResult(
            decision=Decision.ALLOW,
            context=["EXAMPLE: This is an example project handler context message."],
        )

    def get_claude_md(self) -> str | None:
        """Guidance injected into CLAUDE.md for this handler - customise this.

        Return a markdown section describing what this handler does, so agents
        know how to avoid triggering it. Return None if the handler needs no
        agent-facing guidance (rare - prefer explaining the behaviour).
        """
        return """## example-project-handler - example advisory

Demonstrates the project handler pattern. Replace this guidance with a
description of what YOUR handler blocks or advises, and what to do instead.
"""

    def get_acceptance_tests(self) -> list[AcceptanceTest]:
        """Define acceptance tests for this handler."""
        return [
            AcceptanceTest(
                title="Example handler triggers on keyword",
                command=\'echo "example-trigger test"\',
                description="Verify example handler provides advisory context",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"EXAMPLE"],
                safety_notes="Uses echo - safe to execute",
                test_type=TestType.ADVISORY,
            ),
        ]
'''
    (pre_tool_use_dir / "example_handler.py").write_text(example_handler_content)

    example_test_content = '''"""Tests for example project handler."""

from typing import Any

from claude_code_hooks_daemon.core.hook_result import Decision
from example_handler import ExampleHandler


class TestExampleHandler:
    """Tests for ExampleHandler."""

    def setup_method(self) -> None:
        self.handler = ExampleHandler()

    def test_init(self) -> None:
        assert self.handler.name == "example-project-handler"
        assert self.handler.priority == 50
        assert self.handler.terminal is False

    def test_matches_trigger(self, bash_hook_input: Any) -> None:
        hook_input = bash_hook_input("example-trigger test")
        assert self.handler.matches(hook_input) is True

    def test_no_match_without_trigger(self, bash_hook_input: Any) -> None:
        hook_input = bash_hook_input("git status")
        assert self.handler.matches(hook_input) is False

    def test_handle_returns_advisory(self, bash_hook_input: Any) -> None:
        hook_input = bash_hook_input("example-trigger test")
        result = self.handler.handle(hook_input)
        assert result.decision == Decision.ALLOW
        assert any("EXAMPLE" in ctx for ctx in result.context)

    def test_acceptance_tests_defined(self) -> None:
        tests = self.handler.get_acceptance_tests()
        assert len(tests) >= 1
'''
    (pre_tool_use_dir / "test_example_handler.py").write_text(example_test_content)

    # Update config if project_handlers section is missing
    config_path = project_path / ".claude" / "hooks-daemon.yaml"
    if config_path.exists():
        config_content = config_path.read_text()
        if "project_handlers" not in config_content:
            config_content += (
                "\nproject_handlers:\n  enabled: true\n  path: .claude/project-handlers\n"
            )
            config_path.write_text(config_content)

    print(f"Created project handlers directory: {handlers_dir}")
    print()
    print("Structure:")
    print(f"  {handlers_dir}/")
    print("    __init__.py")
    print("    conftest.py")
    print("    pre_tool_use/")
    print("      __init__.py")
    print("      example_handler.py")
    print("      test_example_handler.py")
    print()
    print("Next steps:")
    print("  1. Edit pre_tool_use/example_handler.py with your handler logic")
    print(
        "  2. Use the hooks-daemon skill to test (Skill tool: skill=hooks-daemon, args=dev-handlers)"
    )
    print(
        "  3. Use the hooks-daemon skill to validate (Skill tool: skill=hooks-daemon, args=dev-handlers)"
    )
    print(
        "  4. Use the hooks-daemon skill to restart (Skill tool: skill=hooks-daemon, args=restart)"
    )

    return 0


def cmd_validate_project_handlers(args: argparse.Namespace) -> int:
    """Validate project handler files.

    Discovers project handlers, attempts to import and instantiate each,
    verifies Handler subclass, checks acceptance tests, and reports conflicts.

    Args:
        args: Command-line arguments

    Returns:
        0 if validation passed, 1 otherwise
    """
    try:
        project_path = get_project_path(getattr(args, "project_root", None))
    except SystemExit:
        return 1

    # Load config to get project_handlers path
    config_path = project_path / ".claude" / "hooks-daemon.yaml"
    try:
        config = Config.load(config_path) if config_path.exists() else Config()
    except Exception as exc:
        # FAIL FAST (Plan 00200 Task 5.5): a bare `except: config = Config()`
        # previously fell back to defaults on ANY config error -- including a
        # malformed hooks-daemon.yaml -- with no indication, so this command
        # could silently validate/test the WRONG project_handlers.path. Still
        # falls back (this diagnostic command must not crash on bad config),
        # but the reason is now visible.
        print(f"⚠️  Could not load {config_path}, using defaults: {exc}", file=sys.stderr)
        config = Config()

    handlers_path = Path(config.project_handlers.path)
    if not handlers_path.is_absolute():
        handlers_path = project_path / handlers_path

    if not handlers_path.exists() or not handlers_path.is_dir():
        print(
            f"ERROR: Project handlers directory not found: {handlers_path}",
            file=sys.stderr,
        )
        print("Run 'init-project-handlers' to create it", file=sys.stderr)
        return 1

    # Discover handlers using ProjectHandlerLoader
    from claude_code_hooks_daemon.core.decision_capability import undeliverable_decisions
    from claude_code_hooks_daemon.handlers.project_loader import ProjectHandlerLoader
    from claude_code_hooks_daemon.handlers.registry import EVENT_TYPE_MAPPING

    print(f"Scanning {handlers_path}...")
    print()

    total_handlers = 0
    total_warnings = 0
    total_failures = 0
    handlers_by_event: dict[str, list[str]] = {}

    for dir_name, event_type in EVENT_TYPE_MAPPING.items():
        event_dir = handlers_path / dir_name
        if not event_dir.is_dir():
            continue

        for py_file in sorted(event_dir.glob("*.py")):
            if py_file.name.startswith("_") or py_file.name.startswith("test_"):
                continue

            try:
                handler = ProjectHandlerLoader.load_handler_from_file(py_file)
            except RuntimeError as e:
                print(f"  ERROR: Failed to load {dir_name}/{py_file.name}")
                print(f"    - {e}")
                total_failures += 1
                continue

            total_handlers += 1
            if dir_name not in handlers_by_event:
                handlers_by_event[dir_name] = []
            handlers_by_event[dir_name].append(handler.name)

            print(f"  {dir_name}/{py_file.name} -> {handler.__class__.__name__}")
            print(f"    - Name: {handler.name}")
            print(f"    - Priority: {handler.priority}")
            print(f"    - Terminal: {handler.terminal}")
            print(f"    - Tags: {handler.tags}")

            # Check acceptance tests
            try:
                tests = handler.get_acceptance_tests()
                if not tests:
                    print("    - WARNING: No acceptance tests defined")
                    total_warnings += 1
                else:
                    print(f"    - Acceptance tests: {len(tests)}")
            except Exception as e:
                print(f"    - WARNING: get_acceptance_tests() failed: {e}")
                total_warnings += 1

            # A decision the event cannot deliver is DROPPED on the wire: the
            # handler believes it blocked and nothing blocked. The runtime guard
            # in `to_json` logs it, but only once the handler has shipped and a
            # live event has fired. This is the surface a developer runs WHILE
            # writing the handler, and project handlers are the one population
            # no test in the daemon's own repository can sweep.
            for problem in undeliverable_decisions(type(handler), event_type.value):
                print(f"    - WARNING: {problem}")
                total_warnings += 1

            print("    - Status: OK")
            print()

    if total_handlers == 0:
        print("No project handlers found")
        print(f"Add handler .py files to event-type subdirectories in {handlers_path}")
        return 1 if total_failures > 0 else 0

    # Summary
    print(f"Validation: {total_handlers} handler(s) loaded successfully")
    if total_warnings > 0:
        print(f"Warnings: {total_warnings}")
    if total_failures > 0:
        print(f"Failures: {total_failures} handler(s) failed to load")

    for event_name, handler_names in handlers_by_event.items():
        print(f"  {event_name}: {len(handler_names)} handler(s)")

    return 1 if total_failures > 0 else 0


def cmd_test_project_handlers(args: argparse.Namespace) -> int:
    """Run project handler tests using pytest.

    Runs pytest on the project-handlers directory using --import-mode=importlib
    to allow co-located test files to import handler modules.

    Args:
        args: Command-line arguments with optional verbose flag

    Returns:
        pytest exit code (0 for success, non-zero for failure)
    """
    try:
        project_path = get_project_path(getattr(args, "project_root", None))
    except SystemExit:
        return 1

    # Load config to get project_handlers path
    config_path = project_path / ".claude" / "hooks-daemon.yaml"
    try:
        config = Config.load(config_path) if config_path.exists() else Config()
    except Exception as exc:
        # FAIL FAST (Plan 00200 Task 5.5): a bare `except: config = Config()`
        # previously fell back to defaults on ANY config error -- including a
        # malformed hooks-daemon.yaml -- with no indication, so this command
        # could silently validate/test the WRONG project_handlers.path. Still
        # falls back (this diagnostic command must not crash on bad config),
        # but the reason is now visible.
        print(f"⚠️  Could not load {config_path}, using defaults: {exc}", file=sys.stderr)
        config = Config()

    handlers_path = Path(config.project_handlers.path)
    if not handlers_path.is_absolute():
        handlers_path = project_path / handlers_path

    if not handlers_path.exists() or not handlers_path.is_dir():
        print(
            f"ERROR: Project handlers directory not found: {handlers_path}",
            file=sys.stderr,
        )
        print("Run 'init-project-handlers' to create it", file=sys.stderr)
        return 1

    # FAIL FAST: pytest is a dev-only extra, so no client install has it.
    # Without this check the user gets a bare "No module named pytest" naming an
    # opaque fingerprint-keyed venv path, with no hint that the fix is to
    # install it into THAT venv.
    if importlib.util.find_spec(_PYTEST_MODULE) is None:
        print(
            f"ERROR: {_PYTEST_MODULE} is not installed in the daemon virtualenv.",
            file=sys.stderr,
        )
        print(
            f"       {_PYTEST_MODULE} ships as a dev-only extra, so a normal "
            f"install does not include it.",
            file=sys.stderr,
        )
        print("", file=sys.stderr)
        print("Install it into the daemon virtualenv, then re-run:", file=sys.stderr)
        print(f"  {sys.executable} -m pip install {_PYTEST_MODULE}", file=sys.stderr)
        return 1

    # Build pytest command using current Python interpreter
    cmd = [
        sys.executable,
        "-m",
        _PYTEST_MODULE,
        str(handlers_path),
        "--import-mode=importlib",
    ]

    if getattr(args, "verbose", False):
        cmd.append("-v")

    print(f"Running project handler tests in {handlers_path}...")
    print()

    try:
        result = subprocess.run(  # nosec B603 - pytest with project handler path only
            cmd,
            cwd=str(project_path),
            capture_output=True,
            text=True,
            timeout=Timeout.QA_TEST_TIMEOUT,
        )

        # Print output
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print(result.stderr, file=sys.stderr)

        return result.returncode

    except subprocess.TimeoutExpired:
        print(
            f"ERROR: Test execution timed out after {Timeout.QA_TEST_TIMEOUT} seconds",
            file=sys.stderr,
        )
        return 1


_MARKDOWN_EXTENSIONS: tuple[str, ...] = (".md", ".markdown")


def _format_single_markdown_file(path: Path, check: bool) -> tuple[bool, bool]:
    """Format a single markdown file via mdformat + mdformat-gfm.

    Args:
        path: Markdown file to format.
        check: If True, do not write changes. Only detect whether the file
            would change.

    Returns:
        Tuple of (changed, error) booleans. ``changed`` is True when the
        file would be (or was) rewritten. ``error`` is True when mdformat
        raised an exception.
    """
    try:
        before = path.read_text(encoding="utf-8")
        formatted = format_markdown_text(before)
    except Exception as exc:
        # FAIL SAFE: Surface the failure but do not crash the whole run
        # when processing a directory of many files.
        print(f"ERROR: {path}: {exc}", file=sys.stderr)
        return False, True

    if formatted == before:
        return False, False

    if not check:
        path.write_text(formatted, encoding="utf-8")
    return True, False


def cmd_format_markdown(args: argparse.Namespace) -> int:
    """Format markdown files via mdformat + mdformat-gfm.

    Accepts either a single ``.md``/``.markdown`` file or a directory to
    recurse into. ``--check`` runs in check mode and returns non-zero if
    any file would be rewritten (without actually touching the file).

    Args:
        args: Parsed CLI arguments with ``path`` (Path) and ``check`` (bool).

    Returns:
        0 when no changes needed (or all changes applied successfully),
        1 when the path is invalid or any file would change in check mode
        or any file failed to format.
    """
    path: Path = args.path
    check: bool = args.check

    if not path.exists():
        print(f"ERROR: Path does not exist: {path}", file=sys.stderr)
        return 1

    if path.is_file():
        if not path.name.lower().endswith(_MARKDOWN_EXTENSIONS):
            print(f"ERROR: {path} is not a markdown file", file=sys.stderr)
            return 1
        changed, errored = _format_single_markdown_file(path, check)
        if errored:
            return 1
        if check and changed:
            print(f"Would reformat: {path}")
            return 1
        if changed:
            print(f"Reformatted: {path}")
        return 0

    # Directory mode: recurse and process every markdown file.
    any_changed = False
    any_errored = False
    for candidate in sorted(path.rglob("*")):
        if not candidate.is_file():
            continue
        if not candidate.name.lower().endswith(_MARKDOWN_EXTENSIONS):
            continue
        changed, errored = _format_single_markdown_file(candidate, check)
        if errored:
            any_errored = True
            continue
        if changed:
            any_changed = True
            if check:
                print(f"Would reformat: {candidate}")
            else:
                print(f"Reformatted: {candidate}")

    if any_errored:
        return 1
    if check and any_changed:
        return 1
    return 0


def cmd_secret_meta(args: argparse.Namespace) -> int:
    """Report presence and safe metadata for a protected file — NEVER content.

    Plan 00272: the one sanctioned way to inspect a protected file. Emits
    JSON with existence, bucketed size, mtime, permissions (plus a hygiene
    hint when group/world-readable) and a keyed HMAC digest. Exact size and
    plain sha256 appear only when the ``secret_file_guard`` handler's
    ``allow_plain_hash`` config option is true — there is no CLI override,
    so an agent cannot self-grant the plainer disclosure.

    Returns:
        0 always (a missing file is a valid answer: ``exists: false``).
    """
    from claude_code_hooks_daemon.constants import HandlerID
    from claude_code_hooks_daemon.daemon.validation import load_config_safe
    from claude_code_hooks_daemon.utils.secret_meta import KEY_FILE_NAME, collect_secret_meta

    # An explicit --project-root is trusted as-is (same precedent as plan-qa):
    # the helper needs only a config file and an untracked dir, not a full
    # ProjectContext initialisation.
    override = getattr(args, "project_root", None)
    project_root = Path(override) if override else Path(get_project_path(None))
    config = load_config_safe(project_root) or {}
    handler_options = (
        config.get("handlers", {})
        .get("pre_tool_use", {})
        .get(HandlerID.SECRET_FILE_GUARD.config_key, {})
        .get("options", {})
    ) or {}
    allow_plain_hash = bool(handler_options.get("allow_plain_hash", False))

    key_path = _daemon_untracked_dir(project_root) / KEY_FILE_NAME
    meta = collect_secret_meta(
        Path(args.path), key_path=key_path, allow_plain_hash=allow_plain_hash
    )
    print(json.dumps(meta, indent=2))
    return 0


def cmd_reconcile_settings(args: argparse.Namespace) -> int:
    """Reconcile a settings.json's hook registrations against the SSoT.

    Adds every MISSING wired hook registration (derived from
    ``wired_event_metas()``) to ``path`` while preserving everything else. A
    missing file is created with the full wired set. This is the single
    SSoT-derived generator/merger shared by the install/upgrade shell scripts
    (replacing the drift-prone hardcoded fallback) and available to users on
    demand. ``--check`` reports drift without writing (exit 1 if incomplete).

    Args:
        args: Parsed CLI arguments with ``path`` (Path) and ``check`` (bool).

    Returns:
        0 when complete / successfully written; 1 in ``--check`` when
        registrations are missing, or on a read/parse/write error.
    """
    path: Path = args.path
    check: bool = args.check

    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            print(f"ERROR: cannot read settings.json at {path}: {exc}", file=sys.stderr)
            return 1
        if not isinstance(loaded, dict):
            print(f"ERROR: settings.json at {path} is not a JSON object", file=sys.stderr)
            return 1
        settings: dict[str, Any] = loaded
    else:
        settings = {}

    new_settings, result = reconcile_settings_hooks(settings)

    if check:
        if result.changed:
            print(
                f"Would add {len(result.events_added)} missing hook "
                f"registration(s): {', '.join(result.events_added)}"
            )
            return 1
        print("settings.json hook registrations are complete")
        return 0

    if not result.changed:
        print("settings.json hook registrations already complete — no change")
        return 0

    if path.exists():
        # Existing file: deliberately delegate to the fail-safe writer rather
        # than persisting the ``new_settings`` computed above. This re-reads and
        # re-reconciles (an intentional, negligible O(events) second pass) so the
        # one-shot backup + atomic-write + malformed-file guards live in exactly
        # ONE audited place (settings_repair) instead of being duplicated here.
        repair_result = repair_settings_registrations(path)
        if not repair_result.repaired:
            print(f"ERROR: failed to write settings.json at {path}", file=sys.stderr)
            return 1
        added = repair_result.events_added
    else:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(new_settings, indent=2) + "\n", encoding="utf-8")
        except OSError as exc:
            print(f"ERROR: cannot write settings.json at {path}: {exc}", file=sys.stderr)
            return 1
        added = result.events_added

    print(f"Added {len(added)} hook registration(s): {', '.join(added)}")
    return 0


def cmd_deploy_plan_workflow(args: argparse.Namespace) -> int:
    """(Re)deploy plan-workflow assets on demand (Plan 00185).

    Wraps the single deploy decision site ``deploy_plan_workflow_if_enabled`` so
    a user who flips ``plan_workflow.enabled: true`` after install, or partially
    hand-scaffolds the plan tree, can seed the daemon-owned assets
    (``mkplan.bash``, ``_TEMPLATE_.md``, ``_JOURNAL_TEMPLATE_.md``,
    ``PlanJournalling.md``) without a full reinstall/upgrade. Idempotent — fills
    gaps only, never overwrites client-owned files.

    Args:
        args: Parsed CLI arguments with ``project_root`` (Path).

    Returns:
        0 on success (including a config-disabled no-op); 1 on failure.
    """
    from claude_code_hooks_daemon.install.plan_workflow import (
        deploy_plan_workflow_if_enabled,
    )

    project_root: Path = args.project_root
    config_path = project_root / ".claude" / "hooks-daemon.yaml"

    result = deploy_plan_workflow_if_enabled(project_root, config_path)
    for message in result.messages:
        print(message)
    if not result.success:
        print("ERROR: plan workflow deployment failed", file=sys.stderr)
        return 1
    return 0


def cmd_agents(args: argparse.Namespace) -> int:
    """Manage daemon-shipped agent assets (Plan 00279).

    Actions:

    - ``list``: every shipped agent with version and gating config key.
    - ``status``: per-agent deployment classification
      (absent | current | outdated | customised) plus whether its gate is on.
    - ``install [name]``: run the config-gated lifecycle sync (all agents), or
      deploy one named agent — refused with guidance if its gate is disabled.
    - ``remove <name>``: remove one deployed agent; refuses a customised file.

    Args:
        args: Parsed CLI arguments with ``project_root``, ``action`` and
            optional ``name``.

    Returns:
        0 on success; 1 on refusal/failure.
    """
    from claude_code_hooks_daemon.config.models import Config
    from claude_code_hooks_daemon.install import agent_assets

    project_root: Path = args.project_root
    config_path = project_root / ".claude" / "hooks-daemon.yaml"
    config = Config.load_or_default(config_path)
    action: str = args.action
    name: str | None = args.name

    if name is not None:
        try:
            named_spec = agent_assets.spec_by_name(name)
        except KeyError:
            known = ", ".join(spec.name for spec in agent_assets.SHIPPED_AGENTS)
            print(f"ERROR: unknown agent {name!r}. Shipped agents: {known}", file=sys.stderr)
            return 1
    else:
        named_spec = None

    if action == "list":
        for spec in agent_assets.SHIPPED_AGENTS:
            enabled = "enabled" if spec.is_enabled(config) else "disabled"
            print(f"{spec.name}  v{spec.version}  gated on {spec.gating_config_key} ({enabled})")
        return 0

    if action == "status":
        for spec in agent_assets.SHIPPED_AGENTS:
            state = agent_assets.classify_agent(spec, project_root)
            enabled = "enabled" if spec.is_enabled(config) else "disabled"
            print(f"{spec.name}  v{spec.version}  {state.value}  ({enabled})")
        return 0

    if action == "install":
        if named_spec is not None:
            if not named_spec.is_enabled(config):
                print(
                    f"ERROR: {named_spec.name} is gated on "
                    f"{named_spec.gating_config_key}, which is disabled. Enable "
                    f"it in .claude/hooks-daemon.yaml and retry.",
                    file=sys.stderr,
                )
                return 1
            result = agent_assets.deploy_agent(named_spec, project_root)
            # Warning-family messages are already emitted once via logging
            # (routed to stderr by the CLI); printing them again duplicates.
            if result.action is agent_assets.AgentAction.CUSTOMISED_WARNING:
                return 1
            print(result.message)
            return 0
        report = agent_assets.sync_agents(project_root, config)
        warning_family = (
            agent_assets.AgentAction.CUSTOMISED_WARNING,
            agent_assets.AgentAction.REMOVAL_ADVISED,
        )
        for result in report.results:
            if result.action not in warning_family:
                print(result.message)
        return 0

    # action == "remove" (argparse restricts choices)
    if named_spec is None:
        print("ERROR: 'agents remove' requires an agent name", file=sys.stderr)
        return 1
    result = agent_assets.remove_agent(named_spec, project_root)
    if result.action is agent_assets.AgentAction.REFUSED_CUSTOMISED:
        return 1
    print(result.message)
    return 0


def cmd_plan_qa(args: argparse.Namespace) -> int:
    """Run plan QA checks (Plan 00144): sweep, staged gate, or single-file lint.

    Actions (mutually exclusive; default ``--sweep``):

    - ``--sweep``: evaluate the whole plan tree (Stage 3 checks) — CI-able,
      exit 1 on any finding.
    - ``--check-staged``: evaluate the staged tree (Stage 2 commit-gate
      checks) without committing.
    - ``--lint PATH``: run the Stage 1 edit-time checks against one file's
      current on-disk content.

    Args:
        args: Parsed CLI arguments with ``sweep``, ``check_staged``, ``lint``,
            ``json_output`` and optional ``project_root``.

    Returns:
        0 when clean (or plan workflow / plan QA disabled in config),
        1 when findings are reported, 2 on operational errors (missing
        plan directory or lint target).
    """
    from datetime import date

    from claude_code_hooks_daemon.config.models import Config
    from claude_code_hooks_daemon.plan_qa.context import (
        edit_context,
        staged_context,
        sweep_context,
    )
    from claude_code_hooks_daemon.plan_qa.paths import PlanFileKind, classify
    from claude_code_hooks_daemon.plan_qa.report import CLEAN_SCOPE_TREE, format_cli_report
    from claude_code_hooks_daemon.plan_qa.runner import run_stage
    from claude_code_hooks_daemon.plan_qa.types import Stage

    # An explicit --project-root is trusted as-is (plan QA needs a plan tree,
    # not a validated daemon installation); otherwise auto-detect as usual.
    resolved_root = resolve_tree_root(args)
    if resolved_root is None:
        return 2
    project_root = resolved_root
    config = Config.load_or_default(project_root / ".claude" / "hooks-daemon.yaml")
    plan_cfg = config.plan_workflow
    if not plan_cfg.enabled:
        print("Plan QA: plan workflow is disabled in config — nothing to check.")
        return 0
    if not plan_cfg.qa.enabled:
        print("Plan QA: disabled in config (plan_workflow.qa.enabled: false).")
        return 0

    policy = plan_cfg.qa
    plan_dir_rel = plan_cfg.directory

    try:
        if getattr(args, "lint", None) is not None:
            # Resolve BEFORE classifying (Plan 00230). ``classify()`` decides
            # scope with ``is_relative_to(plan_dir)`` against an absolute plan
            # dir, so an unresolved relative path — the form the shipped skill
            # documents — classified as OUTSIDE, every check no-matched, and
            # the run printed a clean bill of health for a file it never read.
            lint_path = Path(args.lint).resolve()
            if not lint_path.is_file():
                print(f"ERROR: Lint target does not exist: {lint_path}", file=sys.stderr)
                return 2
            context = edit_context(
                project_root,
                plan_dir_rel,
                policy,
                file_path=lint_path,
                file_content=lint_path.read_text(),
                file_exists_before=True,
            )
            # FAIL FAST on a target no check can apply to. Exiting 0 here would
            # certify a file that was never examined, and the exit code is what
            # CI reads.
            classified = classify(lint_path, context)
            if classified.kind is PlanFileKind.OUTSIDE:
                print(
                    f"ERROR: Lint target is not a plan document: {lint_path}\n"
                    f"       Expected a markdown file under {context.plan_dir}.",
                    file=sys.stderr,
                )
                return 2
            clean_scope = f"{classified.rel_path} is clean"
            findings = run_stage(Stage.EDIT, context)
        elif getattr(args, "check_staged", False):
            clean_scope = CLEAN_SCOPE_TREE
            context = staged_context(project_root, plan_dir_rel, policy)
            findings = run_stage(Stage.COMMIT, context)
        else:
            clean_scope = CLEAN_SCOPE_TREE
            context = sweep_context(project_root, plan_dir_rel, policy, today=date.today())
            findings = run_stage(Stage.SWEEP, context)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if getattr(args, "json_output", False):
        payload = [
            {
                "check_id": finding.check_id,
                "level": finding.level.value,
                "message": finding.message,
                "remediation": finding.remediation,
                "path": finding.path,
            }
            for finding in findings
        ]
        print(json.dumps(payload, indent=2))
    else:
        print(format_cli_report(findings, clean_scope))

    return 1 if findings else 0


def cmd_docs_qa(args: argparse.Namespace) -> int:
    """Run docs QA checks (Plan 00284): sweep or single-file lint.

    Actions (mutually exclusive; default ``--sweep``):

    - ``--sweep``: rebuild the doc corpus and evaluate it (SWEEP-stage
      checks) — CI-able, exit 1 on any finding.
    - ``--lint PATH``: run the EDIT-stage checks against one file's current
      on-disk content.
    - ``--check-staged``: run the STAGED-stage checks against the staged
      tree (Plan 00284 Task 3.1e) — a bare invocation inspects the index;
      no pathspec-scoping support in this CLI (the commit-gate HANDLER
      derives pathspecs from the actual ``git commit`` command line, which
      the CLI has no equivalent of).

    Runs regardless of ``documentation.enabled`` — an explicit CLI
    invocation is consent; ``enabled`` only gates the handlers.

    Args:
        args: Parsed CLI arguments with ``sweep``, ``check_staged``,
            ``lint``, ``json_output`` and optional ``project_root``.

    Returns:
        0 when clean, 1 when findings are reported, 2 on operational
        errors (missing or out-of-scope lint target).
    """
    from claude_code_hooks_daemon.config.models import Config
    from claude_code_hooks_daemon.docs_qa.context import (
        edit_context,
        staged_context,
        sweep_context,
    )
    from claude_code_hooks_daemon.docs_qa.corpus import (
        build_and_save_corpus,
        is_lintable_path,
        load_or_cold_corpus,
        refresh_own_record,
    )
    from claude_code_hooks_daemon.docs_qa.policy import policy_from_config
    from claude_code_hooks_daemon.docs_qa.report import CLEAN_SCOPE_CORPUS, format_cli_report
    from claude_code_hooks_daemon.docs_qa.runner import run_stage
    from claude_code_hooks_daemon.docs_qa.types import CheckStage

    resolved_root = resolve_tree_root(args)
    if resolved_root is None:
        return 2
    project_root = resolved_root
    config = Config.load_or_default(project_root / ".claude" / "hooks-daemon.yaml")
    policy = policy_from_config(config.documentation)

    if getattr(args, "check_staged", False):
        clean_scope = CLEAN_SCOPE_CORPUS
        context = staged_context(project_root=project_root, policy=policy)
        findings = run_stage(CheckStage.STAGED, context)
    elif getattr(args, "lint", None) is not None:
        # Resolve BEFORE scope-checking (mirrors the plan-qa Plan 00230
        # lesson): a relative path must classify identically to its
        # absolute form, and an unresolved relative path against an
        # absolute-path scope check would silently read as "outside".
        lint_path = Path(args.lint).resolve()
        if not lint_path.is_file():
            print(f"ERROR: Lint target does not exist: {lint_path}", file=sys.stderr)
            return 2
        lint_rel_path = str(lint_path.relative_to(project_root))
        # Same scope union the EDIT-stage handler uses (Plan 00284 Task 3.4):
        # the doc corpus's own scope, OR the generated-docs manifest (which
        # may legitimately name a path outside that scope — the default
        # entry, .claude/HOOKS-DAEMON.md, is exactly this case), OR any
        # module-scoped CLAUDE.md.
        if not is_lintable_path(lint_rel_path, lint_path, project_root, policy):
            print(
                f"ERROR: Lint target is not a documentation file: {lint_path}\n"
                f"       Expected a markdown file under one of the configured "
                f"documentation trees, .claude/rules, .claude/skills, "
                f".claude/agents, the project root, a sub-folder CLAUDE.md, "
                f"or the generated-docs manifest.",
                file=sys.stderr,
            )
            return 2
        # A cheap CACHE read only (never a build) — the cold-index rule.
        # Powers quote-source-stale's reverse lookup; every other EDIT check
        # ignores it. Cold (no cache yet) degrades that one check to silence.
        untracked_dir = _daemon_untracked_dir(project_root)
        index_path = untracked_dir / "docs-qa" / "index.json"
        corpus = load_or_cold_corpus(project_root, index_path)
        lint_content = lint_path.read_text()
        # Task 3.5: the cache read above performs NO staleness check, so
        # without this the lint target's own record can lag the file on
        # disk -- refresh it in place before any cross-document check runs.
        corpus = refresh_own_record(corpus, project_root, lint_path, lint_content)
        context = edit_context(
            project_root=project_root,
            policy=policy,
            file_path=lint_path,
            file_content=lint_content,
            file_exists_before=True,
            # F1 (Plan 00287): an on-disk lint has, by definition, no pending
            # change -- without this, every worse-only check compares the
            # would-be content against EMPTY/zero and reports every existing
            # violation as newly introduced (BLOCK), disagreeing with the
            # EDIT-stage handler, which always has the real "before" content.
            file_content_before=lint_content,
            corpus=corpus,
        )
        clean_scope = f"{lint_path.relative_to(project_root)} is clean"
        findings = run_stage(CheckStage.EDIT, context)
    else:
        untracked_dir = _daemon_untracked_dir(project_root)
        index_path = untracked_dir / "docs-qa" / "index.json"
        corpus = build_and_save_corpus(project_root, policy, index_path)
        context = sweep_context(project_root=project_root, policy=policy, corpus=corpus)
        clean_scope = CLEAN_SCOPE_CORPUS
        findings = run_stage(CheckStage.SWEEP, context)

    if getattr(args, "json_output", False):
        payload = [
            {
                "check_id": finding.check_id,
                "severity": finding.severity.value,
                "message": finding.message,
                "remediation": finding.remediation,
                "path": finding.path,
            }
            for finding in findings
        ]
        print(json.dumps(payload, indent=2))
    else:
        print(format_cli_report(findings, clean_scope))

    return 1 if findings else 0


def cmd_find_comment_blocks(args: argparse.Namespace) -> int:
    """List long comment blocks under the given paths (Plan 00284 Task 3.1g).

    Deterministic finder feeding the ``hooks-daemon-docs-qa`` agent's
    worklist (Decision 7: verbose comments that function as documentation).
    Lists candidates only — never judges content, never blocks anything.

    Args:
        args: Parsed CLI arguments with ``paths`` (files/dirs), ``min_lines``
            and ``json_output``.

    Returns:
        0 when no blocks are found, 1 when findings are reported.
    """
    from claude_code_hooks_daemon.docs_qa.comment_finder import find_long_comment_blocks

    resolved_paths = [Path(p).resolve() for p in args.paths]
    findings = find_long_comment_blocks(resolved_paths, min_lines=args.min_lines)

    if getattr(args, "json_output", False):
        payload = [
            {
                "path": str(finding.path),
                "start_line": finding.start_line,
                "end_line": finding.end_line,
                "line_count": finding.line_count,
                "preview": finding.preview,
            }
            for finding in findings
        ]
        print(json.dumps(payload, indent=2))
    else:
        print(f"{len(findings)} finding(s)")
        for finding in findings:
            print(
                f"  {finding.path}:{finding.start_line}-{finding.end_line} "
                f"({finding.line_count} lines) {finding.preview}"
            )

    return 1 if findings else 0


def cmd_skill_scan(args: argparse.Namespace) -> int:
    """Run the skill-opportunity scan pipeline (Plan 00274).

    Mines Claude Code session transcripts for repeated workloads and
    recurring points of confusion, and writes a report to
    ``untracked/reports/`` embedding the judging rubric. The judging is done
    by an in-session subagent dispatched at the report (Decision 9) — this
    command never invokes a model.

    Works with the ``skill_opportunity_detector`` handler disabled — a
    manual run is consent by definition; ``enabled`` gates only the
    SessionStart advisory.

    Returns:
        0 on any completed run (including model-stage skips — fail-open),
        2 when the project root cannot be resolved.
    """
    from datetime import date

    from claude_code_hooks_daemon.config.models import Config
    from claude_code_hooks_daemon.constants.handlers import HandlerID
    from claude_code_hooks_daemon.skill_scan.constants import (
        REPORTS_DIR_NAME,
        STATE_FILE_NAME,
    )
    from claude_code_hooks_daemon.skill_scan.extraction import derive_transcript_dir
    from claude_code_hooks_daemon.skill_scan.models import SkillScanOptions
    from claude_code_hooks_daemon.skill_scan.pipeline import run_scan
    from claude_code_hooks_daemon.skill_scan.state import (
        is_advisory_due,
        load_state,
        record_attempt,
        record_success,
    )
    from claude_code_hooks_daemon.utils.secret_redaction import (
        get_cached_secret_terms,
        resolve_secret_word_list_path,
    )

    resolved_root = resolve_tree_root(args)
    if resolved_root is None:
        return 2
    project_root = resolved_root

    config = Config.load_or_default(project_root / ".claude" / "hooks-daemon.yaml")
    handler_cfg = config.handlers.session_start.get(HandlerID.SKILL_OPPORTUNITY_DETECTOR.config_key)
    # The config model parses handler entries into HandlerConfig objects, but a
    # raw dict is tolerated too (defensive: this path also runs against
    # hand-built configs in tests).
    if isinstance(handler_cfg, dict):
        raw_options = handler_cfg.get("options", {})
    else:
        raw_options = getattr(handler_cfg, "options", {})
    options = SkillScanOptions.from_dict(raw_options if isinstance(raw_options, dict) else {})

    state_path = _daemon_untracked_dir(project_root) / STATE_FILE_NAME
    force = bool(getattr(args, "force", False))
    dry_run = bool(getattr(args, "dry_run", False))
    if not force and not dry_run:
        if not is_advisory_due(load_state(state_path), options.check_interval_days):
            print(
                "Skill scan not due yet (last scan within "
                f"{options.check_interval_days} days). Use --force to run anyway."
            )
            return 0

    sensitive_cfg = config.handlers.pre_tool_use.get(HandlerID.SENSITIVE_CONTENT.config_key)
    if isinstance(sensitive_cfg, dict):
        sensitive_options = sensitive_cfg.get("options", {})
    else:
        sensitive_options = getattr(sensitive_cfg, "options", {})
    configured_word_list = (
        sensitive_options.get("secret_word_list_path")
        if isinstance(sensitive_options, dict)
        else None
    )
    secret_terms = get_cached_secret_terms(
        resolve_secret_word_list_path(configured_word_list, project_root)
    )

    result = run_scan(
        project_root=project_root,
        options=options,
        report_dir=project_root / "untracked" / REPORTS_DIR_NAME,
        secret_terms=secret_terms,
        today=date.today(),
        dry_run=dry_run,
        window_days=getattr(args, "window_days", None),
    )

    stats = result.stats
    print(
        f"files={stats.files} lines={stats.lines} user_records={stats.user_records} "
        f"genuine={stats.genuine} unparseable={stats.unparseable}"
    )
    if dry_run:
        print("--- DRY RUN: digest that would be sent to the model ---")
        print(result.digest)
        return 0

    if stats.genuine == 0:
        # An empty window is NOT recorded as a completed scan: a missing or
        # mistyped transcript directory would otherwise silence the advisory
        # for the whole interval. Record an attempt (quietens nagging for a
        # day) and name the directory that was read so the operator can check.
        transcript_dir = (
            Path(options.transcript_dir)
            if options.transcript_dir is not None
            else derive_transcript_dir(project_root)
        )
        print(
            f"WARNING: no genuine prompts found in transcript directory "
            f"{transcript_dir} — check the path if this is unexpected. "
            "Not recording a completed scan; the advisory will retry."
        )
        record_attempt(state_path)
    elif result.report_path is not None:
        record_success(state_path, report_path=str(result.report_path))
    if result.report_path is not None:
        print(f"Report written: {result.report_path}")
        print(
            "Next: dispatch a subagent at this report — it judges the prompt "
            "under '## Judging' and its answer is appended under '## Findings'. "
            "Human review before any skill is created."
        )
    return 0


_BUG_REPORT_LOG_LINES = 100
_BUG_REPORT_DIR_NAME = "bug-reports"
_BUG_REPORT_ENV_VARS = (
    "HOSTNAME",
    "CLAUDE_HOOKS_SOCKET_PATH",
    "CLAUDE_HOOKS_PID_PATH",
    "CLAUDE_HOOKS_LOG_PATH",
    "HOOKS_DAEMON_ROOT_DIR",
    "HOOKS_DAEMON_MODE",
    "VIRTUAL_ENV",
)


def cmd_bug_report(args: argparse.Namespace) -> int:
    """Generate comprehensive bug report with system diagnostics.

    Collects daemon version, system info, daemon status, configuration,
    loaded handlers, recent logs, environment variables, and a health
    summary into a structured markdown report.

    The report is generated even when the daemon is not running — missing
    sections are noted with appropriate messages.

    Args:
        args: Command-line arguments with description, output

    Returns:
        0 if report generated successfully, 1 on error
    """
    project_path = get_project_path(getattr(args, "project_root", None))
    pid_path = _resolve_pid_path(args, project_path)
    socket_path = _resolve_socket_path(args, project_path)
    description: str = getattr(args, "description", "No description provided")

    # Gather all sections
    sections: list[str] = []
    health_checks: list[tuple[str, bool]] = []

    # --- Header ---
    now = datetime.datetime.now(tz=datetime.UTC)
    sections.append(f"# Bug Report: {description}\n")
    sections.append(f"**Generated:** {now.strftime('%Y-%m-%d %H:%M:%S UTC')}\n")

    # --- Daemon Version ---
    sections.append("## Daemon Version\n")
    try:
        from claude_code_hooks_daemon.version import __version__

        sections.append(f"- **Version:** {__version__}")
        health_checks.append(("Version detected", True))
    except ImportError:
        sections.append("- **Version:** UNKNOWN (import failed)")
        health_checks.append(("Version detected", False))

    # Git commit hash
    git_hash = _bug_report_git_hash(project_path)
    sections.append(f"- **Git Commit:** {git_hash}")

    # Install mode
    config_path = project_path / ".claude" / "hooks-daemon.yaml"
    is_self_install = _bug_report_self_install_mode(config_path)
    sections.append(f"- **Install Mode:** {'self-install' if is_self_install else 'normal'}\n")

    # --- System Info ---
    sections.append("## System Info\n")
    sections.append(f"- **OS:** {platform.system()} {platform.release()}")
    sections.append(f"- **Architecture:** {platform.machine()}")
    sections.append(f"- **Python:** {platform.python_version()}")
    sections.append(f"- **Hostname:** {resolve_hostname()}\n")
    health_checks.append(("System info collected", True))

    # --- Daemon Status ---
    sections.append("## Daemon Status\n")
    pid = read_pid_file(str(pid_path))
    daemon_running = pid is not None

    if daemon_running:
        sections.append("- **Status:** RUNNING")
        sections.append(f"- **PID:** {pid}")
        sections.append(
            f"- **Socket:** {socket_path} ({'exists' if socket_path.exists() else 'MISSING'})"
        )
        sections.append(f"- **PID File:** {pid_path}")
        health_checks.append(("Daemon running", True))
    else:
        sections.append("- **Status:** NOT RUNNING")
        sections.append(f"- **Socket:** {socket_path}")
        sections.append(f"- **PID File:** {pid_path}")
        health_checks.append(("Daemon running", False))

    # Query daemon for health info if running
    if daemon_running:
        health_resp = send_daemon_request(
            socket_path, {"event": "_system", "hook_input": {"action": "health"}}
        )
        if health_resp and "result" in health_resp:
            result = health_resp["result"]
            stats = result.get("stats", {})
            sections.append(f"- **Uptime:** {stats.get('uptime_seconds', 0):.1f}s")
            sections.append(f"- **Requests Processed:** {stats.get('requests_processed', 0)}")
            sections.append(f"- **Errors:** {stats.get('errors', 0)}")
            health_checks.append(("Health query succeeded", True))
        else:
            sections.append("- **Health Query:** Failed (no response)")
            health_checks.append(("Health query succeeded", False))
    sections.append("")

    # --- Configuration ---
    sections.append("## Configuration\n")
    if config_path.exists():
        config_content = config_path.read_text()
        sections.append(f"**Path:** `{config_path}`\n")
        sections.append("```yaml")
        sections.append(config_content.rstrip())
        sections.append("```\n")
        health_checks.append(("Config file exists", True))
    else:
        sections.append(f"**Path:** `{config_path}` — FILE NOT FOUND\n")
        health_checks.append(("Config file exists", False))

    # --- Loaded Handlers ---
    sections.append("## Loaded Handlers\n")
    if daemon_running:
        handlers_resp = send_daemon_request(
            socket_path, {"event": "_system", "hook_input": {"action": "handlers"}}
        )
        if handlers_resp and "result" in handlers_resp:
            handlers = handlers_resp["result"].get("handlers", {})
            total = sum(
                len(h_list) if isinstance(h_list, list) else h_list for h_list in handlers.values()
            )
            sections.append(f"**Total:** {total}\n")
            for event_type, handler_list in handlers.items():
                if not handler_list:
                    continue
                sections.append(f"**{event_type}:**")
                if isinstance(handler_list, list):
                    for h in handler_list:
                        terminal = "T" if h.get("terminal", True) else "-"
                        sections.append(
                            f"- [{terminal}] {h.get('priority', 50):3d} {h.get('name', 'unknown')}"
                        )
                else:
                    sections.append(f"- Count: {handler_list}")
                sections.append("")
            health_checks.append(("Handlers loaded", True))
        else:
            sections.append("Daemon running but handler query failed.\n")
            health_checks.append(("Handlers loaded", False))
    else:
        sections.append("Daemon not running — cannot query handlers.\n")
        health_checks.append(("Handlers loaded", False))

    # --- Recent Logs ---
    sections.append("## Recent Logs\n")
    if daemon_running:
        logs_resp = send_daemon_request(
            socket_path,
            {
                "event": "_system",
                "hook_input": {"action": "get_logs", "count": _BUG_REPORT_LOG_LINES},
            },
        )
        if logs_resp and "result" in logs_resp:
            logs = logs_resp["result"].get("logs", [])
            if logs:
                sections.append(f"Last {len(logs)} log entries:\n")
                sections.append("```")
                for log_line in logs:
                    sections.append(log_line)
                sections.append("```\n")
            else:
                sections.append("No logs in buffer.\n")
            health_checks.append(("Logs accessible", True))
        else:
            sections.append("Daemon running but log query failed.\n")
            health_checks.append(("Logs accessible", False))
    else:
        sections.append("Daemon not running — cannot query logs.\n")
        health_checks.append(("Logs accessible", False))

    # --- Environment ---
    sections.append("## Environment\n")
    for var_name in _BUG_REPORT_ENV_VARS:
        value = os.environ.get(var_name)
        display = value if value is not None else "(not set)"
        sections.append(f"- `{var_name}`: {display}")
    sections.append("")

    # --- Bug Description ---
    sections.append("## Bug Description\n")
    sections.append(description)
    sections.append("")

    # --- Health Summary ---
    sections.append("## Health Summary\n")
    for check_name, passed in health_checks:
        icon = "PASS" if passed else "FAIL"
        sections.append(f"- [{icon}] {check_name}")
    passed_count = sum(1 for _, p in health_checks if p)
    total_count = len(health_checks)
    sections.append(f"\n**Result:** {passed_count}/{total_count} checks passed\n")

    # --- Assemble report ---
    report = "\n".join(sections)

    # --- Write output ---
    output_target: str | None = getattr(args, "output", None)

    if output_target == "-":
        print(report)
        return 0

    if output_target is None:
        # Default path: {untracked}/bug-reports/bug-report-{timestamp}.md
        untracked_dir = _bug_report_untracked_dir(project_path, is_self_install)
        reports_dir = untracked_dir / _BUG_REPORT_DIR_NAME
        reports_dir.mkdir(parents=True, exist_ok=True)
        timestamp = now.strftime("%Y%m%d-%H%M%S")
        output_path = reports_dir / f"bug-report-{timestamp}.md"
    else:
        output_path = Path(output_target)
        output_path.parent.mkdir(parents=True, exist_ok=True)

    output_path.write_text(report)
    print(f"Bug report saved to: {output_path}")
    return 0


def _bug_report_git_hash(project_path: Path) -> str:
    """Get git commit hash for the daemon source.

    Args:
        project_path: Project root directory

    Returns:
        Short git hash or 'unknown' if not available
    """
    result = run_git(project_path, "rev-parse", "--short", "HEAD", timeout=Timeout.GIT_CONTEXT)
    if result.returncode == 0:
        return result.stdout.strip()
    return "unknown"


def _bug_report_self_install_mode(config_path: Path) -> bool:
    """Check if the daemon is in self-install mode.

    Args:
        config_path: Path to hooks-daemon.yaml

    Returns:
        True if self_install_mode is enabled
    """
    if not config_path.exists():
        return False
    try:
        config_dict = ConfigLoader.load(config_path)
        return bool(config_dict.get("daemon", {}).get("self_install_mode", False))
    except Exception:
        # Config parsing failure is non-critical for bug reports — default to normal mode
        return False


def _bug_report_untracked_dir(project_path: Path, is_self_install: bool) -> Path:
    """Get the untracked directory for bug report output.

    Args:
        project_path: Project root directory
        is_self_install: Whether running in self-install mode

    Returns:
        Path to the untracked directory
    """
    if is_self_install:
        return project_path / "untracked"
    return project_path / ".claude" / "hooks-daemon" / "untracked"


def main() -> int:
    """Main CLI entry point.

    Returns:
        Exit code (0 for success, 1 for error)
    """
    parser = argparse.ArgumentParser(
        description="Claude Code Hooks Daemon - Lifecycle Management\n"
        "Run from project root or any subdirectory.",
        prog="claude-hooks-daemon",
    )

    # Global arguments
    parser.add_argument(
        "--project-root",
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

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # start command
    parser_start = subparsers.add_parser("start", help="Start daemon")
    parser_start.set_defaults(func=cmd_start)

    # stop command
    parser_stop = subparsers.add_parser("stop", help="Stop daemon")
    parser_stop.set_defaults(func=cmd_stop)

    # status command
    parser_status = subparsers.add_parser("status", help="Check daemon status")
    parser_status.set_defaults(func=cmd_status)

    # restart command
    parser_restart = subparsers.add_parser("restart", help="Restart daemon")
    parser_restart.set_defaults(func=cmd_restart)

    # logs command
    parser_logs = subparsers.add_parser("logs", help="Query in-memory logs")
    parser_logs.add_argument(
        "-n",
        "--count",
        type=int,
        default=None,
        help="Number of recent log entries to show (default: all)",
    )
    parser_logs.add_argument(
        "-l",
        "--level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Filter logs by minimum level",
    )
    parser_logs.add_argument(
        "-f",
        "--follow",
        action="store_true",
        help="Follow logs (tail -f style)",
    )
    parser_logs.set_defaults(func=cmd_logs)

    # health command
    parser_health = subparsers.add_parser("health", help="Check daemon health")
    parser_health.set_defaults(func=cmd_health)

    # check command — verbose env/config audit (the report SessionStart hides)
    parser_check = subparsers.add_parser(
        "check",
        help="Verbose environment & configuration audit (Claude Code settings, "
        "container runtime, git fileMode, hook registration)",
    )
    parser_check.set_defaults(func=cmd_check)

    # get-mode command
    parser_get_mode = subparsers.add_parser("get-mode", help="Get current daemon mode")
    parser_get_mode.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )
    parser_get_mode.set_defaults(func=cmd_get_mode)

    # set-mode command
    parser_set_mode = subparsers.add_parser("set-mode", help="Set daemon mode")
    parser_set_mode.add_argument(
        "mode",
        choices=["default", "unattended"],
        help="Mode to set: default (normal), unattended (block Stop events)",
    )
    parser_set_mode.add_argument(
        "-m",
        "--message",
        help="Custom message for the mode (e.g., task instructions for unattended mode)",
    )
    parser_set_mode.set_defaults(func=cmd_set_mode)

    # handlers command
    parser_handlers = subparsers.add_parser("handlers", help="List registered handlers")
    parser_handlers.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )
    parser_handlers.add_argument(
        "--count",
        action="store_true",
        help="Print only the total number of registered handlers (machine-readable)",
    )
    parser_handlers.set_defaults(func=cmd_handlers)

    # config command
    parser_config = subparsers.add_parser("config", help="Show loaded configuration")
    parser_config.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )
    parser_config.set_defaults(func=cmd_config)

    # repair command
    parser_repair = subparsers.add_parser("repair", help="Repair broken venv (runs uv sync)")
    parser_repair.set_defaults(func=cmd_repair)

    # list-venvs command (Plan 00099)
    parser_list_venvs = subparsers.add_parser(
        "list-venvs",
        help="List fingerprint-keyed venvs under untracked/ (Plan 00099)",
    )
    parser_list_venvs.add_argument(
        "--json", action="store_true", help="Emit JSON instead of a human-readable table"
    )
    parser_list_venvs.set_defaults(func=cmd_list_venvs)

    # disk-usage command (Plan 00181 Task 5.1) — read-only accumulation report
    parser_disk_usage = subparsers.add_parser(
        "disk-usage",
        help="Report daemon untracked/ disk accumulation and reclaimable space (Plan 00181)",
    )
    parser_disk_usage.add_argument(
        "--json", action="store_true", help="Emit JSON instead of a human-readable table"
    )
    parser_disk_usage.set_defaults(func=cmd_disk_usage)

    # check-permissions command (Plan 00239) — the BATCH half of the umask fix.
    # A umask governs creates only, so every already-deployed daemon keeps its
    # world-writable artefacts until this is run against it.
    parser_check_permissions = subparsers.add_parser(
        "check-permissions",
        help="Report (or --fix) group/other-writable daemon artefacts (Plan 00239)",
    )
    parser_check_permissions.add_argument(
        "--fix",
        action="store_true",
        help="Strip group/other bits from every reported artefact",
    )
    parser_check_permissions.set_defaults(func=cmd_check_permissions)

    # prune-venvs command (Plan 00099)
    parser_prune_venvs = subparsers.add_parser(
        "prune-venvs",
        help="Delete stale / legacy venvs (Plan 00099)",
    )
    parser_prune_venvs.add_argument(
        "--legacy",
        action="store_true",
        help="Remove the pre-v3.7.0 untracked/venv/ directory",
    )
    parser_prune_venvs.add_argument(
        "--all-except-current",
        action="store_true",
        help="Remove every fingerprint-keyed venv whose fingerprint != current env",
    )
    parser_prune_venvs.add_argument(
        "--stale",
        action="store_true",
        help="Remove venvs whose stamped daemon version differs from the current env's",
    )
    parser_prune_venvs.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the removal plan without deleting anything",
    )
    parser_prune_venvs.add_argument(
        "--force",
        action="store_true",
        help="Required for actual deletion (combined with a selection flag)",
    )
    parser_prune_venvs.set_defaults(func=cmd_prune_venvs)

    # write-venv-metadata command (Plan 00100 Task 3.3)
    parser_write_venv_metadata = subparsers.add_parser(
        "write-venv-metadata",
        help="Write .daemon-metadata.json inside a provisioned venv (Plan 00100)",
    )
    parser_write_venv_metadata.add_argument(
        "--venv-path",
        required=True,
        help="Absolute path to the venv directory that just finished provisioning",
    )
    parser_write_venv_metadata.add_argument(
        "--fingerprint",
        required=True,
        help="Fingerprint embedded in the venv directory name " "(e.g. 'workspace-py311-2fa8b3c1')",
    )
    parser_write_venv_metadata.add_argument(
        "--daemon-version",
        required=True,
        help="Daemon version stamp (vMAJOR.MINOR.PATCH) to record in the metadata",
    )
    parser_write_venv_metadata.add_argument(
        "--project-root",
        default=None,
        help="Project root for lock-hash computation (defaults to current working directory)",
    )
    parser_write_venv_metadata.set_defaults(func=cmd_write_venv_metadata)

    # init-config command
    parser_init_config = subparsers.add_parser(
        "init-config", help="Generate configuration template"
    )
    parser_init_config.add_argument(
        "--minimal", action="store_true", help="Generate minimal configuration (no examples)"
    )
    parser_init_config.add_argument(
        "--force", action="store_true", help="Overwrite existing configuration file"
    )
    parser_init_config.add_argument(
        "--stdout",
        action="store_true",
        help="Print the template to stdout for review instead of writing it (needs no --force)",
    )
    parser_init_config.set_defaults(func=cmd_init_config)

    # generate-playbook command
    parser_gen_playbook = subparsers.add_parser(
        "generate-playbook", help="Generate acceptance test playbook from handler definitions"
    )
    parser_gen_playbook.add_argument(
        "--include-disabled",
        action="store_true",
        help="Include tests from disabled handlers",
    )
    parser_gen_playbook.add_argument(
        "--format",
        choices=["markdown", "json"],
        default="markdown",
        help="Output format: markdown (default) or json",
    )
    parser_gen_playbook.add_argument(
        "--filter-type",
        choices=["blocking", "advisory", "context"],
        help="Filter tests by type (json format only)",
    )
    parser_gen_playbook.add_argument(
        "--filter-handler",
        help="Filter tests by handler name substring (json format only)",
    )
    parser_gen_playbook.set_defaults(func=cmd_generate_playbook)

    # generate-docs command
    parser_gen_docs = subparsers.add_parser(
        "generate-docs",
        help="Generate .claude/HOOKS-DAEMON.md from live config and handler metadata",
    )
    parser_gen_docs.add_argument(
        "--include-disabled",
        action="store_true",
        help="Include disabled handlers in output",
    )
    parser_gen_docs.add_argument(
        "--output",
        type=str,
        help="Output file path (default: .claude/HOOKS-DAEMON.md)",
    )
    parser_gen_docs.add_argument(
        "--project-root",
        type=Path,
        default=None,
        help="Project root directory (default: auto-detect)",
    )
    parser_gen_docs.set_defaults(func=cmd_generate_docs)

    # regenerate-docs command — force-regenerate BOTH HOOKS-DAEMON.md and the
    # CLAUDE.md <hooksdaemon> block in one shot (no daemon restart needed).
    parser_regen_docs = subparsers.add_parser(
        "regenerate-docs",
        help="Force-regenerate .claude/HOOKS-DAEMON.md and the CLAUDE.md <hooksdaemon> block",
    )
    parser_regen_docs.add_argument(
        "--include-disabled",
        action="store_true",
        help="Include disabled handlers in HOOKS-DAEMON.md output",
    )
    parser_regen_docs.add_argument(
        "--output",
        type=str,
        help="HOOKS-DAEMON.md output file path (default: .claude/HOOKS-DAEMON.md)",
    )
    parser_regen_docs.add_argument(
        "--project-root",
        type=Path,
        default=None,
        help="Project root directory (default: auto-detect)",
    )
    parser_regen_docs.set_defaults(func=cmd_regenerate_docs)

    # config-diff command
    parser_config_diff = subparsers.add_parser(
        "config-diff", help="Compare user config against default config"
    )
    parser_config_diff.add_argument(
        "user_config", type=str, help="Path to user's current config YAML"
    )
    parser_config_diff.add_argument(
        "default_config", type=str, help="Path to default/example config YAML"
    )
    parser_config_diff.set_defaults(func=cmd_config_diff)

    # config-merge command
    parser_config_merge = subparsers.add_parser(
        "config-merge", help="Merge user customizations onto new default config"
    )
    parser_config_merge.add_argument(
        "user_config", type=str, help="Path to user's current config YAML"
    )
    parser_config_merge.add_argument(
        "old_default_config", type=str, help="Path to default config from current version"
    )
    parser_config_merge.add_argument(
        "new_default_config", type=str, help="Path to default config from new version"
    )
    parser_config_merge.set_defaults(func=cmd_config_merge)

    # config-validate command
    parser_config_validate = subparsers.add_parser(
        "config-validate", help="Validate config against Pydantic schema"
    )
    parser_config_validate.add_argument(
        "config_path", type=str, help="Path to config YAML to validate"
    )
    parser_config_validate.set_defaults(func=cmd_config_validate)

    # check-config-migrations command
    parser_check_migrations = subparsers.add_parser(
        "check-config-migrations",
        help="Show config options added/renamed since your previous version",
    )
    parser_check_migrations.add_argument(
        "--from",
        dest="from_version",
        required=True,
        metavar="VERSION",
        help="Version you are upgrading from (e.g. 2.10.0)",
    )
    parser_check_migrations.add_argument(
        "--to",
        dest="to_version",
        required=True,
        metavar="VERSION",
        help="Version you are upgrading to (e.g. 2.15.2)",
    )
    parser_check_migrations.add_argument(
        "--config",
        metavar="PATH",
        default=None,
        help="Path to hooks-daemon.yaml (default: auto-detect from project root)",
    )
    parser_check_migrations.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format: text (default) or json",
    )
    parser_check_migrations.add_argument(
        "--manifests-dir",
        dest="manifests_dir",
        metavar="PATH",
        default=None,
        help="Override manifest directory (for testing)",
    )
    parser_check_migrations.set_defaults(func=cmd_check_config_migrations)

    # check-worktree-seed command
    parser_check_worktree_seed = subparsers.add_parser(
        "check-worktree-seed",
        help="Report worktree seed config drift against this repository (reports only)",
    )
    parser_check_worktree_seed.add_argument(
        "--config",
        metavar="PATH",
        default=None,
        help="Path to hooks-daemon.yaml (default: auto-detect from project root)",
    )
    parser_check_worktree_seed.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format: text (default) or json",
    )
    parser_check_worktree_seed.add_argument(
        "--project-root",
        type=Path,
        metavar="PATH",
        default=None,
        help="Repository root to scan (default: auto-detect)",
    )
    parser_check_worktree_seed.set_defaults(func=cmd_check_worktree_seed)

    # check-truth-changes command
    parser_check_truth = subparsers.add_parser(
        "check-truth-changes",
        help="Show doc truth-changes (was -> now) to reconcile since your previous version",
    )
    parser_check_truth.add_argument(
        "--from",
        dest="from_version",
        required=True,
        metavar="VERSION",
        help="Version you are upgrading from (e.g. 3.15.0)",
    )
    parser_check_truth.add_argument(
        "--to",
        dest="to_version",
        required=True,
        metavar="VERSION",
        help="Version you are upgrading to (e.g. 3.18.0)",
    )
    parser_check_truth.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format: text (default) or json",
    )
    parser_check_truth.add_argument(
        "--truth-changes-dir",
        dest="truth_changes_dir",
        metavar="PATH",
        default=None,
        help="Override truth-changes directory (for testing)",
    )
    parser_check_truth.set_defaults(func=cmd_check_truth_changes)

    # plan-qa command (Plan 00144) — sweep / staged gate / single-file lint
    parser_plan_qa = subparsers.add_parser(
        "plan-qa",
        help="Run plan QA checks: --sweep (default, exit 1 on drift), --check-staged, --lint FILE",
    )
    parser_plan_qa.add_argument(
        "--sweep",
        action="store_true",
        help="Evaluate the whole plan tree for drift (default action)",
    )
    parser_plan_qa.add_argument(
        "--check-staged",
        dest="check_staged",
        action="store_true",
        help="Evaluate the staged tree with the commit-gate checks",
    )
    parser_plan_qa.add_argument(
        "--lint",
        type=Path,
        metavar="FILE",
        default=None,
        help="Run edit-time checks against one plan file's on-disk content",
    )
    parser_plan_qa.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="Emit findings as JSON",
    )
    parser_plan_qa.add_argument(
        "--project-root",
        dest="project_root",
        metavar="PATH",
        default=None,
        help="Project root override (default: auto-detected)",
    )
    parser_plan_qa.set_defaults(func=cmd_plan_qa)

    # docs-qa command (Plan 00284) — sweep / single-file lint (staged: not
    # implemented in this slice)
    parser_docs_qa = subparsers.add_parser(
        "docs-qa",
        help="Run docs QA checks: --sweep (default, exit 1 on drift), --lint FILE",
    )
    parser_docs_qa.add_argument(
        "--sweep",
        action="store_true",
        help="Rebuild the doc corpus and evaluate it for drift (default action)",
    )
    parser_docs_qa.add_argument(
        "--check-staged",
        dest="check_staged",
        action="store_true",
        help="Not implemented in this slice (Plan 00284 Task 3.1a); exits 2",
    )
    parser_docs_qa.add_argument(
        "--lint",
        type=Path,
        metavar="FILE",
        default=None,
        help="Run edit-time checks against one doc file's on-disk content",
    )
    parser_docs_qa.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="Emit findings as JSON",
    )
    parser_docs_qa.add_argument(
        "--project-root",
        dest="project_root",
        metavar="PATH",
        default=None,
        help="Project root override (default: auto-detected)",
    )
    parser_docs_qa.set_defaults(func=cmd_docs_qa)

    # find-comment-blocks command (Plan 00284 Task 3.1g) — deterministic
    # finder feeding the hooks-daemon-docs-qa agent's worklist (Decision 7)
    parser_find_comment_blocks = subparsers.add_parser(
        "find-comment-blocks",
        help="List long comment blocks under PATHS (feeds the docs-qa agent's worklist)",
    )
    parser_find_comment_blocks.add_argument(
        "paths",
        nargs="+",
        help="Files and/or directories to scan (directories are expanded recursively)",
    )
    parser_find_comment_blocks.add_argument(
        "--min-lines",
        dest="min_lines",
        type=int,
        default=DEFAULT_MIN_BLOCK_LINES,
        help=f"Minimum block length in lines to report (default: {DEFAULT_MIN_BLOCK_LINES})",
    )
    parser_find_comment_blocks.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="Emit findings as JSON",
    )
    parser_find_comment_blocks.set_defaults(func=cmd_find_comment_blocks)

    # skill-scan command (Plan 00274) — mine transcripts for skill candidates
    parser_skill_scan = subparsers.add_parser(
        "skill-scan",
        help="Mine session transcripts for skill-creation opportunities (report-only)",
    )
    parser_skill_scan.add_argument(
        "--force",
        action="store_true",
        help="Run even when the TTL says a scan is not yet due",
    )
    parser_skill_scan.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="Stages 1-2 only: print the redacted digest, no model call, no report",
    )
    parser_skill_scan.add_argument(
        "--window-days",
        dest="window_days",
        type=int,
        default=None,
        help="Override the transcript mtime window (default: from config)",
    )
    parser_skill_scan.add_argument(
        "--project-root",
        dest="project_root",
        metavar="PATH",
        default=None,
        help="Project root override (default: auto-detected)",
    )
    parser_skill_scan.set_defaults(func=cmd_skill_scan)

    # harvest-background command (Plan 00142, Layer B) — detect & surface, never kill
    parser_harvest = subparsers.add_parser(
        "harvest-background",
        help="Surface runaway background processes (high CPU / orphaned / over-TTL); never kills",
    )
    parser_harvest.add_argument(
        "--max-wall-seconds",
        dest="max_wall_seconds",
        type=int,
        default=600,
        help="Wall-time TTL for tracked process groups (default: 600)",
    )
    parser_harvest.add_argument(
        "--max-cpu-percent",
        dest="max_cpu_percent",
        type=float,
        default=400.0,
        help="Sustained %%CPU ceiling, applied to all processes (default: 400 == 4 cores)",
    )
    parser_harvest.add_argument(
        "--min-cpu-runtime-seconds",
        dest="min_cpu_runtime_seconds",
        type=int,
        default=60,
        help="Minimum elapsed time before a CPU breach counts (default: 60)",
    )
    parser_harvest.add_argument(
        "--state-file",
        dest="state_file",
        metavar="PATH",
        default=None,
        help="Override the tracked-process state file (default: daemon untracked dir)",
    )
    parser_harvest.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format: text (default) or json",
    )
    parser_harvest.set_defaults(func=cmd_harvest_background)

    # inject-goal command (Plan 00269) — manual goal-intent signal fallback
    parser_inject_goal = subparsers.add_parser(
        "inject-goal",
        help="Write a <session>.goal-intent signal for the ccy supervisor (manual fallback)",
    )
    parser_inject_goal.add_argument(
        "plan_number",
        metavar="NNNNN",
        help="5-digit plan number of an ACTIVE plan (e.g. 00269)",
    )
    parser_inject_goal.add_argument(
        "--project-root",
        dest="project_root",
        type=Path,
        default=None,
        help="Project root override (default: auto-detected)",
    )
    parser_inject_goal.set_defaults(func=cmd_inject_goal)

    # verdicts command (Plan 00209): report on the handler decision log
    parser_verdicts = subparsers.add_parser(
        "verdicts",
        help="Report on the handler verdict log: fire counts, verdict mix, "
        "override rate, never-fired handlers",
    )
    parser_verdicts.add_argument(
        "--log-file",
        dest="log_file",
        metavar="PATH",
        default=None,
        help="Override the verdicts.jsonl path (default: daemon untracked dir)",
    )
    parser_verdicts.add_argument(
        "--json",
        action="store_true",
        help="Output machine-readable JSON instead of a text report",
    )
    parser_verdicts.set_defaults(func=cmd_verdicts)

    # delete-branch command (Plan 00206)
    parser_delete_branch = subparsers.add_parser(
        "delete-branch",
        help="Delete local branches only when their safety can be proven "
        "(try 'git branch -d' first — this is the fallback for when it refuses)",
    )
    parser_delete_branch.add_argument(
        "branches",
        nargs="+",
        metavar="BRANCH",
        help="Local branch name(s) to delete",
    )
    parser_delete_branch.add_argument(
        "--protected-ref",
        dest="protected_ref",
        default="main",
        help="Ref every proof is measured against (default: main)",
    )
    parser_delete_branch.add_argument(
        "--dry-run",
        action="store_true",
        help="Classify and report without deleting anything",
    )
    parser_delete_branch.add_argument(
        "--allow-unproven",
        dest="allow_unproven",
        action="store_true",
        help="Permit branches whose safety cannot be proven. Requires --reason, "
        "and additionally a human confirmation at an interactive terminal",
    )
    parser_delete_branch.add_argument(
        "--reason",
        default=None,
        help="Why the unique content on an unproven branch may be destroyed",
    )
    parser_delete_branch.add_argument(
        "--bundle",
        default="untracked/deleted-branches.bundle",
        metavar="PATH",
        help="Recovery bundle written before deletion "
        "(default: untracked/deleted-branches.bundle)",
    )
    parser_delete_branch.add_argument(
        "--no-bundle",
        dest="no_bundle",
        action="store_true",
        help="Skip the recovery bundle — use when the content must NOT survive",
    )
    parser_delete_branch.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format: text (default) or json",
    )
    parser_delete_branch.set_defaults(func=cmd_delete_branch)

    # release-notes command
    parser_release_notes = subparsers.add_parser(
        "release-notes",
        help="Show daemon release notes (defaults to the installed version)",
    )
    parser_release_notes.add_argument(
        "--version",
        dest="version",
        metavar="VERSION",
        default=None,
        help="Show notes for a specific version (e.g. 3.27.0)",
    )
    parser_release_notes.add_argument(
        "--from",
        dest="from_version",
        metavar="VERSION",
        default=None,
        help="Range start, excluded (version you are upgrading from)",
    )
    parser_release_notes.add_argument(
        "--to",
        dest="to_version",
        metavar="VERSION",
        default=None,
        help="Range end, included (version you are upgrading to)",
    )
    parser_release_notes.add_argument(
        "--latest",
        dest="latest",
        action="store_true",
        help="Show the newest available version's notes",
    )
    parser_release_notes.add_argument(
        "--list",
        dest="list_versions",
        action="store_true",
        help="List all versions that have release notes",
    )
    parser_release_notes.add_argument(
        "--format",
        choices=["markdown", "json"],
        default="markdown",
        help="Output format: markdown (default) or json",
    )
    parser_release_notes.add_argument(
        "--releases-dir",
        dest="releases_dir",
        metavar="PATH",
        default=None,
        help="Override RELEASES directory (for testing)",
    )
    parser_release_notes.set_defaults(func=cmd_release_notes)

    # init-project-handlers command
    parser_init_ph = subparsers.add_parser(
        "init-project-handlers",
        help="Scaffold project-handlers directory with example handler and tests",
    )
    parser_init_ph.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing project-handlers directory",
    )
    parser_init_ph.set_defaults(func=cmd_init_project_handlers)

    # validate-project-handlers command
    parser_validate_ph = subparsers.add_parser(
        "validate-project-handlers",
        help="Validate project handler files (import, instantiate, check acceptance tests)",
    )
    parser_validate_ph.set_defaults(func=cmd_validate_project_handlers)

    # test-project-handlers command
    parser_test_ph = subparsers.add_parser(
        "test-project-handlers",
        help="Run project handler tests with pytest",
    )
    parser_test_ph.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Verbose test output",
    )
    parser_test_ph.set_defaults(func=cmd_test_project_handlers)

    # format-markdown command
    parser_format_md = subparsers.add_parser(
        "format-markdown",
        help="Format markdown files via mdformat + mdformat-gfm (auto-align tables)",
    )
    parser_format_md.add_argument(
        "path",
        type=Path,
        help="Markdown file or directory to format (directories are processed recursively)",
    )
    parser_format_md.add_argument(
        "--check",
        action="store_true",
        help="Dry-run mode: exit 1 if any file would be rewritten, do not modify files",
    )
    parser_format_md.set_defaults(func=cmd_format_markdown)

    # secret-meta (Plan 00272) — protected-file metadata, never content
    parser_secret_meta = subparsers.add_parser(
        "secret-meta",
        help="Report existence/size-bucket/mtime/mode/keyed-digest for a protected file (never content)",
    )
    parser_secret_meta.add_argument(
        "path",
        type=Path,
        help="Path of the protected file to inspect",
    )
    parser_secret_meta.add_argument(
        "--project-root",
        type=Path,
        help="Project root for config + key resolution (trusted as-is; auto-detected by default)",
    )
    parser_secret_meta.set_defaults(func=cmd_secret_meta)

    # reconcile-settings (Plan 00185) — SSoT-derived settings.json hook merge
    parser_reconcile = subparsers.add_parser(
        "reconcile-settings",
        help="Add missing wired hook registrations to a settings.json (SSoT merge)",
    )
    parser_reconcile.add_argument(
        "path",
        type=Path,
        help="Path to settings.json (created with the full wired set if missing)",
    )
    parser_reconcile.add_argument(
        "--check",
        action="store_true",
        help="Dry-run: exit 1 if any wired registration is missing, do not modify the file",
    )
    parser_reconcile.set_defaults(func=cmd_reconcile_settings)

    # deploy-plan-workflow (Plan 00185) — on-demand plan/journal asset (re)deploy
    parser_deploy_plan = subparsers.add_parser(
        "deploy-plan-workflow",
        help="(Re)deploy plan-workflow assets (mkplan.bash, journal templates) if enabled",
    )
    parser_deploy_plan.add_argument(
        "--project-root",
        type=Path,
        default=Path.cwd(),
        help="Project root (default: current directory)",
    )
    parser_deploy_plan.set_defaults(func=cmd_deploy_plan_workflow)

    # agents (Plan 00279) — daemon-shipped agent-asset lifecycle
    parser_agents = subparsers.add_parser(
        "agents",
        help="Manage daemon-shipped agents in .claude/agents/ (list/status/install/remove)",
    )
    parser_agents.add_argument(
        "action",
        choices=["list", "status", "install", "remove"],
        help="list shipped agents; status shows deployment classification; "
        "install runs the config-gated deploy; remove deletes a pristine deployed agent",
    )
    parser_agents.add_argument(
        "name",
        nargs="?",
        default=None,
        help="Agent name (required for remove; optional for install)",
    )
    parser_agents.add_argument(
        "--project-root",
        type=Path,
        default=Path.cwd(),
        help="Project root (default: current directory)",
    )
    parser_agents.set_defaults(func=cmd_agents)

    # bug-report command
    parser_bug_report = subparsers.add_parser(
        "bug-report",
        help="Generate comprehensive bug report with system diagnostics",
    )
    parser_bug_report.add_argument(
        "description",
        type=str,
        help="Brief description of the bug",
    )
    parser_bug_report.add_argument(
        "-o",
        "--output",
        type=str,
        default=None,
        help="Output file path (default: auto-generated in untracked/bug-reports/). Use '-' for stdout.",
    )
    parser_bug_report.set_defaults(func=cmd_bug_report)

    # Parse arguments
    args = parser.parse_args()

    # Execute command
    if not hasattr(args, "func"):
        parser.print_help()
        return 1

    return cast("int", args.func(args))


if __name__ == "__main__":
    sys.exit(main())
