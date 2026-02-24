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
- repair: Repair broken venv (runs uv sync)
- config-diff: Compare user config against default
- config-merge: Merge user customizations onto new default
- config-validate: Validate config against Pydantic schema
- init-project-handlers: Scaffold project-handlers directory structure
- validate-project-handlers: Validate project handler files
- test-project-handlers: Run project handler tests
"""

import argparse
import asyncio
import json
import os
import signal
import socket
import subprocess  # nosec B404 - subprocess used for daemon management (systemctl) only
import sys
import time
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import ValidationError as PydanticValidationError

from claude_code_hooks_daemon.config.loader import ConfigLoader
from claude_code_hooks_daemon.config.models import Config
from claude_code_hooks_daemon.constants import Timeout
from claude_code_hooks_daemon.constants.modes import DaemonMode
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.daemon.paths import (
    cleanup_pid_file,
    cleanup_socket,
    get_pid_path,
    get_socket_path,
    read_pid_file,
)
from claude_code_hooks_daemon.daemon.validation import (
    check_for_nested_installation,
    is_hooks_daemon_repo,
    is_inside_daemon_directory,
)

from .init_config import generate_config


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
                pass
        current = current.parent

    print(
        "ERROR: Could not find .claude directory with valid hooks daemon installation\n"
        "You must run this command from the project root or any subdirectory.\n"
        f"Current directory: {Path.cwd()}",
        file=sys.stderr,
    )
    sys.exit(1)


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

            friendly_msg = format_validation_error(
                e, config_dict if "config_dict" in dir() else None
            )
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

    except Exception as e:
        print(f"ERROR: Failed to communicate with daemon: {e}", file=sys.stderr)
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

    # Enforce single daemon process (if enabled)
    from claude_code_hooks_daemon.daemon.enforcement import enforce_single_daemon

    enforce_single_daemon(config=config, pid_path=pid_path)

    # Check if already running
    pid = read_pid_file(str(pid_path))
    if pid is not None:
        print(f"Daemon already running (PID: {pid})")
        return 0

    # Clean up stale socket
    cleanup_socket(str(socket_path))

    # Daemonise process (fork and detach from terminal)
    try:
        # First fork
        pid = os.fork()
        if pid > 0:
            # Parent process - wait briefly then check daemon started
            time.sleep(0.5)
            daemon_pid = read_pid_file(str(pid_path))
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
    os.umask(0)

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

    # Redirect stdout/stderr to /dev/null (server uses in-memory logging + stderr for errors)
    devnull = Path("/dev/null").open("w")  # noqa: SIM115 - need to keep fd open for dup2
    os.dup2(devnull.fileno(), sys.stdout.fileno())
    # Keep stderr for error output (MemoryLogHandler sends ERROR+ to stderr)

    # Now run the daemon server
    from claude_code_hooks_daemon.daemon.controller import DaemonController
    from claude_code_hooks_daemon.daemon.server import HooksDaemon

    # Load configuration
    config = Config.find_and_load(project_path)

    # Create daemon controller
    controller = DaemonController()
    handler_config = {
        "pre_tool_use": {k: v.model_dump() for k, v in config.handlers.pre_tool_use.items()},
        "post_tool_use": {k: v.model_dump() for k, v in config.handlers.post_tool_use.items()},
        "session_start": {k: v.model_dump() for k, v in config.handlers.session_start.items()},
        "session_end": {k: v.model_dump() for k, v in config.handlers.session_end.items()},
        "pre_compact": {k: v.model_dump() for k, v in config.handlers.pre_compact.items()},
        "user_prompt_submit": {
            k: v.model_dump() for k, v in config.handlers.user_prompt_submit.items()
        },
        "permission_request": {
            k: v.model_dump() for k, v in config.handlers.permission_request.items()
        },
        "notification": {k: v.model_dump() for k, v in config.handlers.notification.items()},
        "stop": {k: v.model_dump() for k, v in config.handlers.stop.items()},
        "subagent_stop": {k: v.model_dump() for k, v in config.handlers.subagent_stop.items()},
    }
    controller.initialise(
        handler_config,
        workspace_root=project_path,
        plugins_config=config.plugins,
        project_handlers_config=config.project_handlers,
        project_languages=config.daemon.languages,
    )

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

    try:
        asyncio.run(daemon.start())
    except Exception as e:
        print(f"ERROR: Daemon crashed: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        sys.exit(1)
    finally:
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

    # Read PID
    pid = read_pid_file(str(pid_path))
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
    pid_path = _resolve_pid_path(args, project_path)
    socket_path = _resolve_socket_path(args, project_path)

    # Read PID
    pid = read_pid_file(str(pid_path))

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


def cmd_health(args: argparse.Namespace) -> int:
    """Check daemon health status.

    Args:
        args: Command-line arguments

    Returns:
        0 if healthy, 1 otherwise
    """
    project_path = get_project_path(getattr(args, "project_root", None))
    socket_path = _resolve_socket_path(args, project_path)
    pid_path = _resolve_pid_path(args, project_path)

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

    return 0 if status == "healthy" else 1


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

        print("\n[Handlers]")
        for event_type in [
            "pre_tool_use",
            "post_tool_use",
            "session_start",
            "session_end",
            "pre_compact",
            "user_prompt_submit",
            "permission_request",
            "notification",
            "stop",
            "subagent_stop",
        ]:
            handlers = getattr(config.handlers, event_type, {})
            if handlers:
                print(f"  {event_type}:")
                for name, handler_config in handlers.items():
                    enabled = "enabled" if handler_config.enabled else "disabled"
                    priority = (
                        f"priority={handler_config.priority}"
                        if handler_config.priority
                        else "default"
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

    # Stop daemon
    cmd_stop(args)

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

    # Run uv sync to rebuild venv
    venv_path = Path(project_root) / "untracked" / "venv"
    env = os.environ.copy()
    env["UV_PROJECT_ENVIRONMENT"] = str(venv_path)

    try:
        result = subprocess.run(  # nosec B603 B607 - uv is trusted tool, no user input
            ["uv", "sync"],
            cwd=str(project_root),
            env=env,
            capture_output=True,
            text=True,
            timeout=Timeout.BASH_DEFAULT,
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
    except subprocess.TimeoutExpired:
        print(f"ERROR: uv sync timed out after {Timeout.BASH_DEFAULT / 1000:.0f} seconds")
        return 1


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

    # Check if config already exists
    if config_path.exists() and not args.force:
        print(f"ERROR: Configuration file already exists: {config_path}", file=sys.stderr)
        print("Use --force to overwrite", file=sys.stderr)
        return 1

    # Determine mode
    mode: Literal["minimal", "full"] = "minimal" if args.minimal else "full"

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
        print("2. Start the daemon: python3 -m claude_code_hooks_daemon.daemon.cli start")
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
        from claude_code_hooks_daemon.daemon.playbook_generator import PlaybookGenerator

        # Convert HandlersConfig to dictionary
        handlers_dict = config.handlers.model_dump()

        generator = PlaybookGenerator(
            config=handlers_dict,
            registry=registry,
            plugins=plugins,
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
        print(f"ERROR: Failed to generate playbook: {e}", file=sys.stderr)
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

from claude_code_hooks_daemon.core import AcceptanceTest, Handler, HookResult, TestType
from claude_code_hooks_daemon.core.hook_result import Decision


class ExampleHandler(Handler):
    """Example advisory handler.

    This handler demonstrates the project handler pattern.
    Replace this with your own handler logic.
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

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Handler logic - customise this."""
        return HookResult(
            decision=Decision.ALLOW,
            context=["EXAMPLE: This is an example project handler context message."],
        )

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
    print("  2. Run tests: python -m claude_code_hooks_daemon.daemon.cli test-project-handlers")
    print("  3. Validate: python -m claude_code_hooks_daemon.daemon.cli validate-project-handlers")
    print("  4. Restart daemon: python -m claude_code_hooks_daemon.daemon.cli restart")

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
    except Exception:
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
    from claude_code_hooks_daemon.handlers.project_loader import ProjectHandlerLoader
    from claude_code_hooks_daemon.handlers.registry import EVENT_TYPE_MAPPING

    print(f"Scanning {handlers_path}...")
    print()

    total_handlers = 0
    total_warnings = 0
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
                total_warnings += 1
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

            print("    - Status: OK")
            print()

    if total_handlers == 0:
        print("No project handlers found")
        print(f"Add handler .py files to event-type subdirectories in {handlers_path}")
        return 0

    # Summary
    print(f"Validation: {total_handlers} handler(s) loaded successfully")
    if total_warnings > 0:
        print(f"Warnings: {total_warnings}")

    for event_name, handler_names in handlers_by_event.items():
        print(f"  {event_name}: {len(handler_names)} handler(s)")

    return 0


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
    except Exception:
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

    # Build pytest command using current Python interpreter
    cmd = [
        sys.executable,
        "-m",
        "pytest",
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

    # Parse arguments
    args = parser.parse_args()

    # Execute command
    if not hasattr(args, "func"):
        parser.print_help()
        return 1

    return cast("int", args.func(args))


if __name__ == "__main__":
    sys.exit(main())
