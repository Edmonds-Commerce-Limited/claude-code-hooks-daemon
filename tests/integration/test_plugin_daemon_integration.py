"""Integration tests for plugin loading through the daemon.

These tests verify that plugins are loaded and processed when running
through the daemon (not just standalone entry points).

CRITICAL: This is THE CORE BUG - users run the daemon, so if plugins
only load in standalone entry points, they never work in practice.

These tests are in RED phase (TDD) - they should FAIL because
DaemonController doesn't load plugins yet. Task 3.2 will make them pass.
"""

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.constants import Timeout


@pytest.fixture
def plugin_fixture_dir() -> Path:
    """Return path to test plugin fixtures."""
    return Path(__file__).parent.parent / "fixtures" / "plugins"


@pytest.fixture
def daemon_env_with_plugin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    plugin_fixture_dir: Path,
) -> dict[str, Any]:
    """Set up environment for daemon testing with plugins configured.

    Creates a minimal project with:
    - Git repository
    - .claude/hooks-daemon.yaml config WITH plugin configuration
    - Daemon socket and PID locations
    - Environment variables for test isolation

    Returns:
        dict with project_root, config_path, socket_path, pid_path, log_path, plugin_dir
    """
    # Set unique paths for test daemon to avoid collision with production daemon
    # Use /tmp directly for socket files to avoid Unix socket path length limits (108 chars)
    test_id = tmp_path.name[-20:]  # Last 20 chars of test name for uniqueness
    socket_path = Path(f"/tmp/test-plugin-daemon-{test_id}.sock")
    pid_path = Path(f"/tmp/test-plugin-daemon-{test_id}.pid")
    log_path = Path(f"/tmp/test-plugin-daemon-{test_id}.log")

    # Override daemon paths via environment variables
    monkeypatch.setenv("CLAUDE_HOOKS_SOCKET_PATH", str(socket_path))
    monkeypatch.setenv("CLAUDE_HOOKS_PID_PATH", str(pid_path))
    monkeypatch.setenv("CLAUDE_HOOKS_LOG_PATH", str(log_path))

    # Create git repo
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/test/repo.git"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    # Create initial commit
    (tmp_path / "README.md").write_text("# Test Project\n")
    subprocess.run(["git", "add", "README.md"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    # Create config WITH plugin configuration
    # This uses the PluginsConfig format from models.py (source of truth)
    config_dir = tmp_path / ".claude"
    config_dir.mkdir()
    config_path = config_dir / "hooks-daemon.yaml"
    config_path.write_text(f"""
version: '1.0'
daemon:
  idle_timeout_seconds: 600
  log_level: DEBUG
  self_install_mode: true
handlers:
  pre_tool_use: {{}}
  post_tool_use: {{}}
  session_start: {{}}
plugins:
  paths:
    - "{plugin_fixture_dir}"
  plugins:
    - path: "custom_handler"
      event_type: "pre_tool_use"
      enabled: true
""")

    return {
        "project_root": tmp_path,
        "config_path": config_path,
        "socket_path": socket_path,
        "pid_path": pid_path,
        "log_path": log_path,
        "plugin_dir": plugin_fixture_dir,
    }


@pytest.fixture
def daemon_with_plugin(daemon_env_with_plugin: dict[str, Any]):
    """Start daemon process with plugins and ensure cleanup.

    Yields:
        Daemon process and environment info

    Ensures daemon is stopped after test completes.
    """
    project_root = daemon_env_with_plugin["project_root"]

    # Prepare environment with test-specific paths
    # Include the monkeypatched paths from daemon_env_with_plugin
    test_env = os.environ.copy()
    test_env["CLAUDE_HOOKS_SOCKET_PATH"] = str(daemon_env_with_plugin["socket_path"])
    test_env["CLAUDE_HOOKS_PID_PATH"] = str(daemon_env_with_plugin["pid_path"])
    test_env["CLAUDE_HOOKS_LOG_PATH"] = str(daemon_env_with_plugin["log_path"])

    # Start daemon (redirect output to /dev/null)
    start_cmd = [
        sys.executable,
        "-m",
        "claude_code_hooks_daemon.daemon.cli",
        "start",
    ]
    with open("/dev/null", "w") as devnull:
        result = subprocess.run(
            start_cmd,
            cwd=project_root,
            env=test_env,
            stdout=devnull,
            stderr=devnull,
            timeout=Timeout.SOCKET_CONNECT,
        )

    if result.returncode != 0:
        pytest.fail(f"Failed to start daemon with plugins (exit code {result.returncode})")

    # Wait for daemon to be ready
    time.sleep(1.5)

    # Get status to verify running
    status_cmd = [sys.executable, "-m", "claude_code_hooks_daemon.daemon.cli", "status"]
    status_result = subprocess.run(
        status_cmd,
        cwd=project_root,
        env=test_env,
        capture_output=True,
        text=True,
        timeout=Timeout.SOCKET_CONNECT,
    )

    if "RUNNING" not in status_result.stdout:
        pytest.fail(
            f"Daemon not running after start:\n{status_result.stdout}\n{status_result.stderr}"
        )

    yield daemon_env_with_plugin

    # Cleanup: Stop daemon
    stop_cmd = [sys.executable, "-m", "claude_code_hooks_daemon.daemon.cli", "stop"]
    subprocess.run(
        stop_cmd,
        cwd=project_root,
        env=test_env,
        capture_output=True,
        timeout=Timeout.SOCKET_CONNECT,
    )

    # Wait for cleanup
    time.sleep(0.5)


def send_hook_event(
    socket_path: str | Path, hook_input: dict[str, Any], timeout: float = 5.0
) -> dict[str, Any]:
    """Send a hook event to the daemon via Unix socket.

    Args:
        socket_path: Path to daemon Unix socket (string or Path object)
        hook_input: Hook input dictionary
        timeout: Socket timeout in seconds

    Returns:
        Response dictionary from daemon

    Raises:
        AssertionError: If communication fails
    """
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(timeout)

    try:
        sock.connect(str(socket_path))

        # Send hook input
        request = json.dumps(hook_input) + "\n"
        sock.sendall(request.encode("utf-8"))

        # Receive response
        response_data = b""
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            response_data += chunk
            if b"\n" in chunk:  # Response ends with newline
                break

        response: dict[str, Any] = json.loads(response_data.decode("utf-8"))
        return response

    finally:
        sock.close()


class TestPluginDaemonIntegration:
    """Tests for plugin loading and processing through the daemon.

    These tests verify the CORE BUG fix: plugins must load through the
    daemon, not just standalone entry points.
    """

    def test_daemon_starts_with_plugins_configured(
        self, daemon_with_plugin: dict[str, Any]
    ) -> None:
        """Daemon starts successfully with plugins configured.

        This verifies:
        1. Daemon can start with plugin configuration
        2. Daemon initializes without errors
        3. Plugin handler is registered (checked via health endpoint or handler list)
        """
        project_root = daemon_with_plugin["project_root"]
        test_env = os.environ.copy()

        # Get daemon status/health
        status_cmd = [sys.executable, "-m", "claude_code_hooks_daemon.daemon.cli", "status"]
        status_result = subprocess.run(
            status_cmd,
            cwd=project_root,
            env=test_env,
            capture_output=True,
            text=True,
            timeout=Timeout.SOCKET_CONNECT,
        )

        assert "RUNNING" in status_result.stdout, "Daemon should be running"

        # Verify plugin handler is registered by checking handler count
        # The custom_handler plugin should be registered for pre_tool_use
        # We can verify this by sending an event and checking the response
        socket_path = daemon_with_plugin["socket_path"]

        # Send a PreToolUse event that the plugin should match
        hook_input = {
            "event": "PreToolUse",
            "hook_input": {
                "tool_name": "Bash",
                "tool_input": {"command": "echo test"},
            },
            "request_id": "test-plugin-registration",
        }

        response = send_hook_event(socket_path, hook_input)

        # The custom_handler returns "allow" with context "Test custom handler"
        # If plugins are NOT loaded, we won't see this context
        assert isinstance(response, dict), "Response should be a dictionary"

        # Check if plugin handler processed the event
        # The custom_handler adds "Test custom handler" to context
        hook_output = response.get("hookSpecificOutput", {})

        # This assertion will FAIL until Task 3.2 is implemented
        # because DaemonController doesn't load plugins yet
        assert "additionalContext" in hook_output or hook_output.get(
            "permissionDecision"
        ), f"Plugin handler should have processed the event. Response: {response}"

        additional_context = hook_output.get("additionalContext", "")
        assert (
            "Test custom handler" in additional_context
        ), f"Plugin handler context not found. Response: {response}"

    def test_plugin_handler_receives_events_through_daemon(
        self, daemon_with_plugin: dict[str, Any]
    ) -> None:
        """Plugin handler receives and processes events through daemon socket.

        This is the critical test - verifies the end-to-end flow:
        1. Event sent to daemon socket
        2. Daemon routes to plugin handler
        3. Plugin handler processes and returns result
        4. Response contains plugin handler output
        """
        socket_path = daemon_with_plugin["socket_path"]

        # Send PreToolUse event that custom_handler will match
        # custom_handler.matches() returns True for all inputs
        hook_input = {
            "event": "PreToolUse",
            "hook_input": {
                "tool_name": "Bash",
                "tool_input": {"command": "git status"},
            },
            "request_id": "test-plugin-event-flow",
        }

        response = send_hook_event(socket_path, hook_input)

        # Verify response structure
        assert isinstance(response, dict), "Response should be a dictionary"

        # The custom_handler returns:
        # - decision: ALLOW
        # - context: "Test custom handler"
        hook_output = response.get("hookSpecificOutput", {})

        # This will FAIL until daemon loads plugins
        # Check for the plugin's contribution to the response
        additional_context = hook_output.get("additionalContext", "")

        assert (
            "Test custom handler" in additional_context
        ), f"Expected plugin handler context 'Test custom handler' in response. Got: {response}"

    def test_daemon_restart_preserves_plugin_registration(
        self, daemon_env_with_plugin: dict[str, Any]
    ) -> None:
        """Plugin registration persists across daemon restart.

        Verifies:
        1. Start daemon with plugin
        2. Verify plugin works
        3. Stop daemon
        4. Restart daemon
        5. Verify plugin still works
        """
        project_root = daemon_env_with_plugin["project_root"]
        socket_path = daemon_env_with_plugin["socket_path"]
        test_env = os.environ.copy()

        # Start daemon
        start_cmd = [sys.executable, "-m", "claude_code_hooks_daemon.daemon.cli", "start"]
        with open("/dev/null", "w") as devnull:
            result = subprocess.run(
                start_cmd,
                cwd=project_root,
                env=test_env,
                stdout=devnull,
                stderr=devnull,
                timeout=Timeout.SOCKET_CONNECT,
            )

        assert result.returncode == 0, "Failed to start daemon"
        time.sleep(1.5)

        # Verify plugin works (first run)
        hook_input = {
            "event": "PreToolUse",
            "hook_input": {
                "tool_name": "Bash",
                "tool_input": {"command": "ls"},
            },
            "request_id": "test-before-restart",
        }

        response_before = send_hook_event(socket_path, hook_input)
        hook_output_before = response_before.get("hookSpecificOutput", {})
        context_before = hook_output_before.get("additionalContext", "")

        # Stop daemon
        stop_cmd = [sys.executable, "-m", "claude_code_hooks_daemon.daemon.cli", "stop"]
        subprocess.run(
            stop_cmd,
            cwd=project_root,
            env=test_env,
            capture_output=True,
            timeout=Timeout.SOCKET_CONNECT,
        )
        time.sleep(1)

        # Verify stopped
        status_cmd = [sys.executable, "-m", "claude_code_hooks_daemon.daemon.cli", "status"]
        status_result = subprocess.run(
            status_cmd,
            cwd=project_root,
            env=test_env,
            capture_output=True,
            text=True,
            timeout=Timeout.SOCKET_CONNECT,
        )
        assert "NOT RUNNING" in status_result.stdout, "Daemon should be stopped"

        # Restart daemon
        with open("/dev/null", "w") as devnull:
            result = subprocess.run(
                start_cmd,
                cwd=project_root,
                env=test_env,
                stdout=devnull,
                stderr=devnull,
                timeout=Timeout.SOCKET_CONNECT,
            )

        assert result.returncode == 0, "Failed to restart daemon"
        time.sleep(1.5)

        # Verify running again
        status_result = subprocess.run(
            status_cmd,
            cwd=project_root,
            env=test_env,
            capture_output=True,
            text=True,
            timeout=Timeout.SOCKET_CONNECT,
        )
        assert "RUNNING" in status_result.stdout, "Daemon should be running after restart"

        # Verify plugin still works (after restart)
        hook_input["request_id"] = "test-after-restart"
        response_after = send_hook_event(socket_path, hook_input)
        hook_output_after = response_after.get("hookSpecificOutput", {})
        context_after = hook_output_after.get("additionalContext", "")

        # This will FAIL until daemon loads plugins
        assert (
            "Test custom handler" in context_before
        ), f"Plugin should work before restart. Response: {response_before}"

        assert (
            "Test custom handler" in context_after
        ), f"Plugin should work after restart. Response: {response_after}"

        # Cleanup
        subprocess.run(
            stop_cmd,
            cwd=project_root,
            env=test_env,
            capture_output=True,
            timeout=Timeout.SOCKET_CONNECT,
        )

    def test_plugin_blocks_through_daemon_socket(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, plugin_fixture_dir: Path
    ) -> None:
        """E2E smoke test: Plugin can block requests through daemon socket.

        This is THE critical test - verifies the complete production flow:
        1. Client sends request → Unix socket
        2. Daemon receives → routes to plugin handler
        3. Plugin handler blocks → returns DENY decision
        4. Response flows back through socket → client receives block

        This proves plugins work as deployed, not just in unit tests.
        """
        # Setup daemon with blocking handler
        test_id = tmp_path.name[-20:]
        socket_path = Path(f"/tmp/test-plugin-e2e-{test_id}.sock")
        pid_path = Path(f"/tmp/test-plugin-e2e-{test_id}.pid")
        log_path = Path(f"/tmp/test-plugin-e2e-{test_id}.log")

        monkeypatch.setenv("CLAUDE_HOOKS_SOCKET_PATH", str(socket_path))
        monkeypatch.setenv("CLAUDE_HOOKS_PID_PATH", str(pid_path))
        monkeypatch.setenv("CLAUDE_HOOKS_LOG_PATH", str(log_path))

        # Create minimal project with git repository
        subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )
        # Add remote origin (required by daemon validation)
        subprocess.run(
            ["git", "remote", "add", "origin", "https://github.com/test/test.git"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )

        # Create config with blocking handler
        config_dir = tmp_path / ".claude"
        config_dir.mkdir()
        config_path = config_dir / "hooks-daemon.yaml"

        # Use absolute path to blocking_handler.py
        blocking_handler_path = plugin_fixture_dir / "blocking_handler.py"

        config_path.write_text(f"""
version: '1.0'
daemon:
  idle_timeout_seconds: 600
  log_level: INFO
  self_install_mode: true
handlers:
  pre_tool_use: {{}}
plugins:
  paths: []
  plugins:
    - path: "{blocking_handler_path}"
      event_type: pre_tool_use
      handlers: ["BlockingHandler"]
      enabled: true
""")

        # Start daemon
        test_env = os.environ.copy()
        start_cmd = [sys.executable, "-m", "claude_code_hooks_daemon.daemon.cli", "start"]
        with open("/dev/null", "w") as devnull:
            result = subprocess.run(
                start_cmd,
                cwd=tmp_path,
                env=test_env,
                stdout=devnull,
                stderr=devnull,
                timeout=Timeout.SOCKET_CONNECT,
            )

        if result.returncode != 0:
            # Check log file for details
            log_content = ""
            if log_path.exists():
                log_content = log_path.read_text()
            pytest.fail(
                f"Failed to start daemon with plugin (exit code {result.returncode})\n"
                f"Log file: {log_path}\n{log_content}"
            )

        # Wait for daemon to be ready
        time.sleep(1.5)

        # Verify daemon is RUNNING
        status_cmd = [sys.executable, "-m", "claude_code_hooks_daemon.daemon.cli", "status"]
        status_result = subprocess.run(
            status_cmd,
            cwd=tmp_path,
            env=test_env,
            capture_output=True,
            text=True,
            timeout=Timeout.SOCKET_CONNECT,
        )

        if "RUNNING" not in status_result.stdout:
            # Check log file for details
            log_content = ""
            if log_path.exists():
                log_content = log_path.read_text()
            pytest.fail(
                f"Daemon not running after start:\n"
                f"Status stdout: {status_result.stdout}\n"
                f"Status stderr: {status_result.stderr}\n"
                f"Log file: {log_path}\n{log_content}"
            )

        try:
            # Test 1: Send request with BLOCK_THIS pattern - should be DENIED
            hook_input_block = {
                "event": "PreToolUse",
                "hook_input": {
                    "tool_name": "Bash",
                    "tool_input": {"command": "echo BLOCK_THIS"},
                },
                "request_id": "test-e2e-block",
            }

            response_block = send_hook_event(socket_path, hook_input_block)
            assert isinstance(response_block, dict), "Response should be dict"

            # Verify DENY decision came through socket
            hook_output_block = response_block.get("hookSpecificOutput", {})
            permission = hook_output_block.get("permissionDecision")
            reason = hook_output_block.get("permissionDecisionReason", "")

            assert permission == "deny", (
                f"Plugin should have blocked request. "
                f"Got permission={permission}, reason={reason}, response={response_block}"
            )
            assert (
                "Blocked by E2E smoke test" in reason
            ), f"Expected blocking plugin message. Got: {reason}"

            # Test 2: Send request WITHOUT pattern - should be ALLOWED
            hook_input_allow = {
                "event": "PreToolUse",
                "hook_input": {
                    "tool_name": "Bash",
                    "tool_input": {"command": "echo safe_command"},
                },
                "request_id": "test-e2e-allow",
            }

            response_allow = send_hook_event(socket_path, hook_input_allow)
            assert isinstance(response_allow, dict), "Response should be dict"

            hook_output_allow = response_allow.get("hookSpecificOutput", {})
            permission_allow = hook_output_allow.get("permissionDecision", "allow")

            # Should be allowed (plugin doesn't match)
            assert (
                permission_allow != "deny"
            ), f"Non-matching request should be allowed. Response: {response_allow}"

        finally:
            # Cleanup
            stop_cmd = [sys.executable, "-m", "claude_code_hooks_daemon.daemon.cli", "stop"]
            subprocess.run(
                stop_cmd,
                cwd=tmp_path,
                env=test_env,
                capture_output=True,
                timeout=Timeout.SOCKET_CONNECT,
            )
            # Clean up test files
            for path in [socket_path, pid_path, log_path]:
                if path.exists():
                    path.unlink()


class TestPluginDaemonErrorHandling:
    """Tests for error handling when loading plugins through daemon."""

    def test_daemon_starts_with_missing_plugin_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Daemon starts successfully even if plugin path doesn't exist.

        Plugins should fail-open - missing plugins shouldn't prevent daemon startup.
        """
        # Set unique paths for test daemon isolation
        test_id = tmp_path.name[-20:]
        socket_path = Path(f"/tmp/test-missing-plugin-{test_id}.sock")
        pid_path = Path(f"/tmp/test-missing-plugin-{test_id}.pid")
        log_path = Path(f"/tmp/test-missing-plugin-{test_id}.log")

        monkeypatch.setenv("CLAUDE_HOOKS_SOCKET_PATH", str(socket_path))
        monkeypatch.setenv("CLAUDE_HOOKS_PID_PATH", str(pid_path))
        monkeypatch.setenv("CLAUDE_HOOKS_LOG_PATH", str(log_path))
        test_env = os.environ.copy()

        # Create git repo
        subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test User"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "remote", "add", "origin", "https://github.com/test/repo.git"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )

        # Create initial commit
        (tmp_path / "README.md").write_text("# Test Project\n")
        subprocess.run(["git", "add", "README.md"], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "Initial commit"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )

        # Create config with non-existent plugin path
        config_dir = tmp_path / ".claude"
        config_dir.mkdir()
        config_path = config_dir / "hooks-daemon.yaml"
        config_path.write_text("""
version: '1.0'
daemon:
  idle_timeout_seconds: 600
  log_level: DEBUG
  self_install_mode: true
handlers:
  pre_tool_use: {}
plugins:
  paths:
    - "/nonexistent/plugin/path"
  plugins:
    - path: "nonexistent_handler"
      event_type: "pre_tool_use"
      enabled: true
""")

        # Start daemon - should succeed even with missing plugin
        start_cmd = [sys.executable, "-m", "claude_code_hooks_daemon.daemon.cli", "start"]
        with open("/dev/null", "w") as devnull:
            result = subprocess.run(
                start_cmd,
                cwd=tmp_path,
                env=test_env,
                stdout=devnull,
                stderr=devnull,
                timeout=Timeout.SOCKET_CONNECT,
            )

        # Daemon should start successfully (fail-open for plugins)
        assert result.returncode == 0, "Daemon should start even with missing plugins"

        time.sleep(1)

        # Verify running
        status_cmd = [sys.executable, "-m", "claude_code_hooks_daemon.daemon.cli", "status"]
        status_result = subprocess.run(
            status_cmd,
            cwd=tmp_path,
            env=test_env,
            capture_output=True,
            text=True,
            timeout=Timeout.SOCKET_CONNECT,
        )

        assert "RUNNING" in status_result.stdout, "Daemon should be running"

        # Cleanup
        stop_cmd = [sys.executable, "-m", "claude_code_hooks_daemon.daemon.cli", "stop"]
        subprocess.run(
            stop_cmd,
            cwd=tmp_path,
            env=test_env,
            capture_output=True,
            timeout=Timeout.SOCKET_CONNECT,
        )

    # NOTE: Removed test_daemon_logs_plugin_loading_status
    # The daemon uses in-memory logging (MemoryLogHandler) by design.
    # It does NOT write logs to disk files - get_log_path() exists but is unused.
    # See server.py docstring: "No file logging - query logs via CLI or socket API"
    # If file logging is implemented in the future, add a test here.
