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
"""

import argparse
import asyncio
import json
import os
import signal
import socket
import sys
import time
from pathlib import Path
from typing import Any, Literal, cast

from claude_code_hooks_daemon.config.loader import ConfigLoader
from claude_code_hooks_daemon.config.models import Config
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
            config_dict = ConfigLoader.load(config_file)
            config = Config.model_validate(config_dict)
            self_install = config.daemon.self_install_mode
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


def cmd_start(args: argparse.Namespace) -> int:
    """Start daemon in background.

    Args:
        args: Command-line arguments

    Returns:
        0 if daemon started successfully, 1 otherwise
    """
    project_path = get_project_path(getattr(args, "project_root", None))
    socket_path = get_socket_path(project_path)
    pid_path = get_pid_path(project_path)

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
    controller.initialise(handler_config, workspace_root=project_path)

    # Get the daemon config with proper paths
    daemon_config = config.daemon

    # Ensure paths are set (use getters if not set)
    if daemon_config.socket_path is None:
        daemon_config.socket_path = str(daemon_config.get_socket_path(project_path))
    if daemon_config.pid_file_path is None:
        daemon_config.pid_file_path = str(daemon_config.get_pid_file_path(project_path))

    daemon = HooksDaemon(daemon_config, controller)

    try:
        asyncio.run(daemon.start())
    except Exception as e:
        print(f"ERROR: Daemon crashed: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        sys.exit(1)

    sys.exit(0)


def cmd_stop(args: argparse.Namespace) -> int:
    """Stop running daemon.

    Args:
        args: Command-line arguments

    Returns:
        0 if daemon stopped successfully, 1 otherwise
    """
    project_path = get_project_path(getattr(args, "project_root", None))
    pid_path = get_pid_path(project_path)
    socket_path = get_socket_path(project_path)

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
        timeout = 5
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
    pid_path = get_pid_path(project_path)
    socket_path = get_socket_path(project_path)

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
    socket_path = get_socket_path(project_path)
    pid_path = get_pid_path(project_path)

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
    socket_path = get_socket_path(project_path)
    pid_path = get_pid_path(project_path)

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


def cmd_handlers(args: argparse.Namespace) -> int:
    """List registered handlers.

    Args:
        args: Command-line arguments

    Returns:
        0 if successful, 1 otherwise
    """
    project_path = get_project_path(getattr(args, "project_root", None))
    socket_path = get_socket_path(project_path)
    pid_path = get_pid_path(project_path)

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
    project_path = get_project_path(getattr(args, "project_root", None))
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


def cmd_restart(args: argparse.Namespace) -> int:
    """Restart daemon (stop + start).

    Args:
        args: Command-line arguments

    Returns:
        0 if daemon restarted successfully, 1 otherwise
    """
    # Stop daemon
    cmd_stop(args)

    # Start daemon
    time.sleep(0.5)  # Brief delay between stop and start
    return cmd_start(args)


def cmd_init_config(args: argparse.Namespace) -> int:
    """Generate configuration template.

    Args:
        args: Command-line arguments with mode (minimal/full)

    Returns:
        0 if config generated successfully, 1 otherwise
    """
    project_path = get_project_path(getattr(args, "project_root", None))
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

    # Parse arguments
    args = parser.parse_args()

    # Execute command
    if not hasattr(args, "func"):
        parser.print_help()
        return 1

    return cast("int", args.func(args))


if __name__ == "__main__":
    sys.exit(main())
