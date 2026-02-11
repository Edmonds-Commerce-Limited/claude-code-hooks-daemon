"""Asyncio-based Unix socket server for Claude Code Hooks daemon.

This module provides the core daemon server that eliminates process spawn overhead
by maintaining a long-lived Python process with handlers loaded in memory.

Logging:
- All logs stored in memory via MemoryLogHandler (circular buffer, 1000 records)
- ERROR level and above also output to stderr for critical visibility
- No file logging - query logs via CLI or socket API
"""

import asyncio
import contextlib
import json
import logging
import os
import signal
import sys
import time
from functools import partial
from typing import Any, Protocol, runtime_checkable

from claude_code_hooks_daemon.core.hook_result import HookResult
from claude_code_hooks_daemon.core.input_schemas import get_input_schema
from claude_code_hooks_daemon.daemon.config import DaemonConfig
from claude_code_hooks_daemon.daemon.memory_log_handler import MemoryLogHandler

# Global memory log handler - accessible for log queries
_memory_log_handler: MemoryLogHandler | None = None

logger = logging.getLogger(__name__)


@runtime_checkable
class Controller(Protocol):
    """Protocol for controllers that can handle hook events."""

    def process_request(self, request_data: dict[str, Any]) -> dict[str, Any]:
        """Process a request and return response dict."""
        ...

    def get_health(self) -> dict[str, Any]:
        """Get health status."""
        ...

    def get_handlers(self) -> dict[str, list[dict[str, Any]]]:
        """Get registered handlers."""
        ...


@runtime_checkable
class LegacyController(Protocol):
    """Protocol for legacy FrontController."""

    def dispatch(self, hook_input: dict[str, Any]) -> HookResult:
        """Dispatch to handlers."""
        ...


def get_memory_logs(count: int | None = None, level: str | None = None) -> list[str]:
    """Get logs from memory buffer.

    Args:
        count: Number of recent logs to return (None = all)
        level: Minimum log level to filter by (None = all)

    Returns:
        List of formatted log strings
    """
    if _memory_log_handler is None:
        return ["No logs available - daemon not initialised"]

    logs = _memory_log_handler.get_logs(count)

    # Filter by level if specified
    if level:
        level_names = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        allowed_levels = level_names[level_names.index(level.upper()) :]
        logs = [log for log in logs if any(f"[{lvl}]" in log for lvl in allowed_levels)]

    return logs


def get_log_count() -> int:
    """Get number of log records in memory buffer.

    Returns:
        Number of log records
    """
    if _memory_log_handler is None:
        return 0
    return _memory_log_handler.get_record_count()


class HooksDaemon:
    """Asyncio Unix socket server for hook request handling.

    Features:
    - Asyncio-based Unix socket server for IPC
    - Idle timeout monitoring with automatic shutdown
    - Graceful shutdown handling (SIGTERM, SIGINT)
    - PID file management with stale PID detection
    - Request timing metrics
    - Concurrent request handling
    - In-memory logging with stderr output for errors
    """

    __slots__ = (
        "_active_requests",
        "_idle_check_interval",
        "_input_validators",
        "_is_new_controller",
        "_shutdown_requested",
        "_shutdown_task",
        "config",
        "controller",
        "last_activity",
        "server",
        "shutdown_event",
    )

    def __init__(
        self,
        config: DaemonConfig,
        controller: Controller | LegacyController,
        idle_check_interval: int = 60,
    ) -> None:
        """Initialise hooks daemon.

        Args:
            config: Daemon configuration
            controller: Controller for request dispatch (new or legacy)
            idle_check_interval: Seconds between idle timeout checks (default 60)
        """
        self.config = config
        self.controller = controller
        self.server: asyncio.Server | None = None
        self.last_activity: float = time.time()
        self.shutdown_event = asyncio.Event()
        self._active_requests = 0
        self._shutdown_requested = False
        self._shutdown_task: asyncio.Task[None] | None = None
        self._idle_check_interval = idle_check_interval
        self._is_new_controller = isinstance(controller, Controller)
        self._input_validators: dict[str, Any] = {}  # Cached validators per event type

        # Configure logging with memory handler and stderr for errors
        self._setup_logging(config.log_level)

    def _setup_logging(self, log_level: str) -> None:
        """Configure logging with memory handler and stderr error output.

        Checks HOOKS_DAEMON_LOG_LEVEL environment variable first, falls back to config.

        Args:
            log_level: Log level string from config (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        """
        global _memory_log_handler

        # Check for environment variable override
        env_log_level = os.environ.get("HOOKS_DAEMON_LOG_LEVEL", "").strip().upper()
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

        # Use env var if valid, otherwise use config
        if env_log_level and env_log_level in valid_levels:
            effective_log_level = env_log_level
            logger.debug(
                "Using log level %s from HOOKS_DAEMON_LOG_LEVEL env var (config: %s)",
                effective_log_level,
                log_level,
            )
        else:
            effective_log_level = log_level
            if env_log_level:
                logger.warning(
                    "Invalid HOOKS_DAEMON_LOG_LEVEL value '%s', using config value '%s'",
                    env_log_level,
                    log_level,
                )

        # Create memory handler
        _memory_log_handler = MemoryLogHandler(max_records=1000)
        _memory_log_handler.setLevel(logging.DEBUG)  # Capture all levels in memory

        # Create formatter
        formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        _memory_log_handler.setFormatter(formatter)

        # Create stderr handler for ERROR and above only
        stderr_handler = logging.StreamHandler(sys.stderr)
        stderr_handler.setLevel(logging.ERROR)
        stderr_handler.setFormatter(formatter)

        # Configure root logger
        root_logger = logging.getLogger()
        root_logger.setLevel(getattr(logging, effective_log_level))

        # Remove any existing handlers
        root_logger.handlers.clear()

        # Add our handlers
        root_logger.addHandler(_memory_log_handler)
        root_logger.addHandler(stderr_handler)

    def _should_validate_input(self) -> bool:
        """Check if input validation is enabled.

        Environment variable HOOKS_DAEMON_INPUT_VALIDATION overrides config.

        Returns:
            True if validation should be performed
        """
        # Check environment variable first
        env_enabled = os.environ.get("HOOKS_DAEMON_INPUT_VALIDATION", "").strip().lower()
        if env_enabled in ("true", "1", "yes"):
            return True
        if env_enabled in ("false", "0", "no"):
            return False

        # Fall back to config
        return self.config.input_validation.enabled

    def _is_strict_validation(self) -> bool:
        """Check if strict validation mode is enabled.

        Environment variable HOOKS_DAEMON_VALIDATION_STRICT overrides config.

        Returns:
            True if strict mode (fail-closed) should be used
        """
        # Check environment variable first
        env_strict = os.environ.get("HOOKS_DAEMON_VALIDATION_STRICT", "").strip().lower()
        if env_strict in ("true", "1", "yes"):
            return True
        if env_strict in ("false", "0", "no"):
            return False

        # Fall back to daemon-level strict_mode
        return self.config.strict_mode

    def _get_input_validator(self, event_type: str) -> Any:
        """Get or create cached validator for event type.

        Args:
            event_type: Event name (PreToolUse, PostToolUse, etc.)

        Returns:
            Draft7Validator instance or None if schema not found
        """
        if event_type not in self._input_validators:
            schema = get_input_schema(event_type)
            if schema:
                try:
                    from jsonschema import Draft7Validator

                    self._input_validators[event_type] = Draft7Validator(schema)
                except ImportError:
                    logger.warning("jsonschema not installed - input validation disabled")
                    return None
        return self._input_validators.get(event_type)

    def _validate_hook_input(self, event_type: str, hook_input: dict[str, Any]) -> list[str]:
        """Validate hook_input against event-specific schema.

        Args:
            event_type: Event name (PreToolUse, PostToolUse, etc.)
            hook_input: Hook input dictionary

        Returns:
            List of validation error messages (empty if valid)
        """
        validator = self._get_input_validator(event_type)
        if validator is None:
            return []  # Unknown event type or jsonschema not available

        errors = []
        for error in validator.iter_errors(hook_input):
            path = ".".join(str(p) for p in error.path) if error.path else "root"
            errors.append(f"{path}: {error.message}")

        return errors

    def _validation_error_response(
        self, event_type: str, validation_errors: list[str], request_id: str | None
    ) -> dict[str, Any]:
        """Create error response for validation failure.

        Args:
            event_type: Event type that failed validation
            validation_errors: List of validation error messages
            request_id: Optional request ID

        Returns:
            Error response dictionary
        """
        response: dict[str, Any] = {
            "error": "input_validation_failed",
            "details": validation_errors,
            "event_type": event_type,
        }
        if request_id:
            response["request_id"] = request_id
        return response

    async def start(self) -> None:
        """Start the daemon server.

        - Writes PID file
        - Creates Unix socket server
        - Starts idle timeout monitor
        - Handles graceful shutdown signals
        """
        socket_path = self.config.socket_path_obj
        logger.info("Starting hooks daemon on %s", socket_path)

        # Write PID file
        if self.config.pid_file_path_obj:
            self._write_pid_file()

        # Remove stale socket if exists
        if socket_path and socket_path.exists():
            logger.warning("Removing stale socket: %s", socket_path)
            socket_path.unlink()

        # Start Unix socket server
        try:
            self.server = await asyncio.start_unix_server(self._handle_client, path=str(socket_path))
        except OSError as e:
            # AF_UNIX socket path too long or other socket creation failure
            logger.error(
                "Failed to create Unix socket at %s (length=%d): %s",
                socket_path,
                len(str(socket_path)),
                e,
            )
            raise

        # Set socket permissions (owner read/write, group read, world none)
        if socket_path:
            socket_path.chmod(0o660)

        logger.info("Daemon listening on %s", socket_path)

        # Setup signal handlers for graceful shutdown
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, partial(self._signal_handler, sig))

        # Start idle timeout monitor
        idle_monitor_task = asyncio.create_task(self._monitor_idle_timeout())

        # Wait for shutdown event
        await self.shutdown_event.wait()

        # Cancel idle monitor
        idle_monitor_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await idle_monitor_task

        logger.info("Daemon shutdown complete")

    def _signal_handler(self, sig: signal.Signals) -> None:
        """Handle shutdown signals.

        Args:
            sig: Signal received (SIGTERM or SIGINT)
        """
        logger.info("Received signal %s, initiating graceful shutdown", sig.name)
        # Store task reference to prevent GC, task runs independently
        self._shutdown_task = asyncio.create_task(self.shutdown())

    async def _monitor_idle_timeout(self) -> None:
        """Monitor idle timeout and shutdown if exceeded.

        Checks periodically (based on idle_check_interval) if idle timeout has been exceeded.
        Shuts down gracefully when no recent activity.
        """
        try:
            while not self._shutdown_requested:
                await asyncio.sleep(self._idle_check_interval)

                idle_time = time.time() - self.last_activity
                if idle_time >= self.config.idle_timeout_seconds:
                    logger.info(
                        "Idle timeout exceeded (%.1fs >= %ds), shutting down",
                        idle_time,
                        self.config.idle_timeout_seconds,
                    )
                    await self.shutdown()
                    break
        except asyncio.CancelledError:
            logger.debug("Idle timeout monitor cancelled")
            raise

    async def shutdown(self) -> None:
        """Gracefully shutdown the daemon.

        - Sets shutdown flag
        - Waits for active requests to complete
        - Closes server
        - Removes socket and PID files
        - Sets shutdown event
        """
        if self._shutdown_requested:
            return

        self._shutdown_requested = True
        logger.info("Shutting down daemon...")

        # Wait for active requests to complete (with timeout)
        if self._active_requests > 0:
            logger.info("Waiting for %d active requests...", self._active_requests)
            for _ in range(50):  # Wait up to 5 seconds
                if self._active_requests == 0:
                    break
                await asyncio.sleep(0.1)

        # Close server
        if self.server:
            self.server.close()
            await self.server.wait_closed()

        # Cleanup socket file
        socket_path = self.config.socket_path_obj
        if socket_path and socket_path.exists():
            socket_path.unlink()
            logger.debug("Removed socket: %s", socket_path)

        # Cleanup PID file
        pid_file_path = self.config.pid_file_path_obj
        if pid_file_path and pid_file_path.exists():
            pid_file_path.unlink()
            logger.debug("Removed PID file: %s", pid_file_path)

        # Signal shutdown complete
        self.shutdown_event.set()

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Handle incoming client connection.

        Args:
            reader: Stream reader for incoming data
            writer: Stream writer for outgoing data
        """
        self._active_requests += 1
        self.last_activity = time.time()

        try:
            # Read request (newline-delimited JSON)
            request_data = await reader.readline()

            if not request_data:
                logger.warning("Received empty request")
                return

            # Parse and process request
            start_time = time.time()
            response = await self._process_request(request_data.decode())
            elapsed_ms = (time.time() - start_time) * 1000

            # Note: timing_ms removed - Claude Code schema doesn't accept it as top-level field
            # Timing is logged below for internal metrics only

            # Send response
            response_json = json.dumps(response) + "\n"

            # DEBUG: Log ALL responses with deny/block decisions
            if (
                "deny" in response_json
                or "block" in response_json
                or "permissionDecision" in response_json
            ):
                logger.debug("BLOCKING RESPONSE: %s", response_json[:1000])

            writer.write(response_json.encode())
            await writer.drain()

            logger.debug("Request processed in %.2fms", elapsed_ms)

        except Exception as e:
            logger.exception("Error handling client: %s", e)
            error_response = {"error": str(e)}
            writer.write((json.dumps(error_response) + "\n").encode())
            await writer.drain()

        finally:
            self._active_requests -= 1
            writer.close()
            await writer.wait_closed()

    async def _process_request(self, request_data: str) -> dict[str, Any]:
        """Process incoming hook request.

        Args:
            request_data: JSON-encoded request string

        Returns:
            Response dictionary with result or error
        """
        try:
            request = json.loads(request_data)
        except json.JSONDecodeError as e:
            logger.error("Malformed JSON request: %s", e)
            return {"error": f"Malformed JSON: {e}"}

        # Extract request fields
        request_id = request.get("request_id")
        event = request.get("event")
        hook_input = request.get("hook_input")

        # Validate required fields
        if not event:
            error_msg = "Missing required field: event"
            logger.error(error_msg)
            response: dict[str, Any] = {"error": error_msg}
            if request_id:
                response["request_id"] = request_id
            return response

        if not hook_input:
            error_msg = "Missing required field: hook_input"
            logger.error(error_msg)
            response = {"error": error_msg}
            if request_id:
                response["request_id"] = request_id
            return response

        # Handle system events (logs, status, health, handlers)
        if event == "_system":
            return self._handle_system_request(hook_input, request_id)

        # INPUT VALIDATION - Validate hook_input structure before dispatch
        if self._should_validate_input():
            validation_errors = self._validate_hook_input(event, hook_input)
            if validation_errors:
                # Log validation errors
                if self._is_strict_validation():
                    logger.error(
                        "Input validation failed for %s (strict mode): %s",
                        event,
                        validation_errors,
                    )
                    # Strict mode: return error, don't dispatch
                    return self._validation_error_response(event, validation_errors, request_id)
                else:
                    # Fail-open: log warning and continue
                    if self.config.input_validation.log_validation_errors:
                        logger.warning(
                            "Input validation failed for %s (continuing): %s",
                            event,
                            validation_errors,
                        )

        # Process with appropriate controller
        loop = asyncio.get_running_loop()

        if self._is_new_controller and isinstance(self.controller, Controller):
            # New DaemonController - use process_request directly
            result: dict[str, Any] = await loop.run_in_executor(
                None, self.controller.process_request, request
            )
            if request_id:
                result["request_id"] = request_id
            return result
        elif isinstance(self.controller, LegacyController):
            # Legacy FrontController - dispatch and convert result
            hook_result = await loop.run_in_executor(None, self.controller.dispatch, hook_input)

            # Build response (don't wrap in "result" - to_json already returns correct format)
            response_dict: dict[str, Any] = hook_result.to_json(event)
            if request_id:
                response_dict["request_id"] = request_id
            return response_dict
        else:
            return {"error": "Unknown controller type"}

    def _handle_system_request(
        self, hook_input: dict[str, Any], request_id: str | None
    ) -> dict[str, Any]:
        """Handle internal system requests (logs, health, handlers, etc.).

        Args:
            hook_input: Request data with 'action' field
            request_id: Optional request ID

        Returns:
            Response dictionary
        """
        action = hook_input.get("action")
        response: dict[str, Any]

        if action == "get_logs":
            count = hook_input.get("count")
            level = hook_input.get("level")
            logs = get_memory_logs(count, level)
            result = {"logs": logs, "count": get_log_count()}
            response = {"result": result}

        elif action == "health":
            if self._is_new_controller and isinstance(self.controller, Controller):
                health_result = self.controller.get_health()
            else:
                health_result = {
                    "status": "healthy",
                    "initialised": True,
                    "stats": {"uptime_seconds": 0, "requests_processed": 0},
                    "handlers": {},
                }
            response = {"result": health_result}

        elif action == "handlers":
            if self._is_new_controller and isinstance(self.controller, Controller):
                handlers = self.controller.get_handlers()
            else:
                handlers = {}
            response = {"result": {"handlers": handlers}}

        elif action == "log_marker":
            # Log a boundary marker message
            message = hook_input.get("message", "MARKER")
            logger.info(f"=== {message} ===")
            response = {"result": {"status": "logged", "message": message}}

        else:
            error_msg = f"Unknown system action: {action}"
            logger.warning(error_msg)
            response = {"error": error_msg}

        if request_id:
            response["request_id"] = request_id
        return response

    def _write_pid_file(self) -> None:
        """Write current process PID to PID file.

        Handles stale PID files (process no longer exists).
        """
        pid_file_path = self.config.pid_file_path_obj
        if not pid_file_path:
            return

        pid = os.getpid()

        # Check for stale PID file
        if pid_file_path.exists():
            try:
                old_pid = int(pid_file_path.read_text().strip())
                # Check if process exists
                try:
                    os.kill(old_pid, 0)  # Signal 0 checks existence
                    logger.warning(
                        "Daemon already running with PID %d, overwriting with PID %d",
                        old_pid,
                        pid,
                    )
                except ProcessLookupError:
                    logger.info("Stale PID file detected (PID %d not running)", old_pid)
            except (ValueError, OSError) as e:
                logger.warning("Error reading stale PID file: %s", e)

        # Write current PID
        pid_file_path.parent.mkdir(parents=True, exist_ok=True)
        pid_file_path.write_text(str(pid))
        logger.debug("Wrote PID %d to %s", pid, pid_file_path)
