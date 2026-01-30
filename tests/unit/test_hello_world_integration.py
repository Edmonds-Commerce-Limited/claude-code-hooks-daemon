"""Integration tests for hello_world handler config loading."""

import contextlib
import json
import subprocess
from io import StringIO
from pathlib import Path

from claude_code_hooks_daemon.hooks import post_tool_use, pre_tool_use, session_start


def setup_test_git_repo(tmp_path: Path) -> None:
    """Set up a minimal git repository for testing.

    ProjectContext requires a git repository with remote origin.
    This helper creates the minimal structure needed for tests.

    Args:
        tmp_path: Temporary directory to initialize as git repo
    """
    # Initialize git repo
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

    # Add a remote origin (required by ProjectContext)
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/test/repo.git"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    # Create initial commit (some git operations need at least one commit)
    (tmp_path / "README.md").write_text("# Test Repo\n")
    subprocess.run(["git", "add", "README.md"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )


class TestHelloWorldIntegrationPreToolUse:
    """Test hello_world handler registration in PreToolUse hook."""

    def test_hello_world_handler_not_registered_when_disabled(self, tmp_path, monkeypatch):
        """When enable_hello_world_handlers is false, handler should not be registered."""
        setup_test_git_repo(tmp_path)
        # Create config with flag disabled
        config_file = tmp_path / ".claude" / "hooks-daemon.yaml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text("""
version: "1.0"
daemon:
  enable_hello_world_handlers: false
handlers:
  pre_tool_use: {}
""")

        # Mock stdin with a simple tool call
        hook_input = json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls"}})
        monkeypatch.setattr("sys.stdin", StringIO(hook_input))

        # Mock stdout to capture output
        captured_output = StringIO()
        monkeypatch.setattr("sys.stdout", captured_output)

        # Change to temp directory so config is found
        monkeypatch.chdir(tmp_path)

        # Run the hook
        with contextlib.suppress(SystemExit):
            pre_tool_use.main()

        # Check output - should NOT contain hello_world message
        output = captured_output.getvalue()
        assert "✅ PreToolUse hook system active" not in output

    def test_hello_world_handler_registered_when_enabled(self, tmp_path, monkeypatch):
        """When enable_hello_world_handlers is true, handler should be registered."""
        setup_test_git_repo(tmp_path)
        # Create config with flag enabled
        config_file = tmp_path / ".claude" / "hooks-daemon.yaml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text("""
version: "1.0"
daemon:
  enable_hello_world_handlers: true
handlers:
  pre_tool_use: {}
""")

        # Mock stdin with a simple tool call
        hook_input = json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls"}})
        monkeypatch.setattr("sys.stdin", StringIO(hook_input))

        # Mock stdout to capture output
        captured_output = StringIO()
        monkeypatch.setattr("sys.stdout", captured_output)

        # Change to temp directory so config is found
        monkeypatch.chdir(tmp_path)

        # Run the hook
        with contextlib.suppress(SystemExit):
            pre_tool_use.main()

        # Check output - SHOULD contain hello_world message
        output = captured_output.getvalue()
        # Output is JSON with Unicode-encoded emoji
        assert (
            "✅ PreToolUse hook system active" in output
            or "\\u2705 PreToolUse hook system active" in output
        )

    def test_hello_world_handler_not_registered_when_omitted(self, tmp_path, monkeypatch):
        """When enable_hello_world_handlers is omitted, handler should not be registered (default false)."""
        setup_test_git_repo(tmp_path)
        # Create config WITHOUT the flag (should default to false)
        config_file = tmp_path / ".claude" / "hooks-daemon.yaml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text("""
version: "1.0"
daemon:
  log_level: INFO
handlers:
  pre_tool_use: {}
""")

        # Mock stdin with a simple tool call
        hook_input = json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls"}})
        monkeypatch.setattr("sys.stdin", StringIO(hook_input))

        # Mock stdout to capture output
        captured_output = StringIO()
        monkeypatch.setattr("sys.stdout", captured_output)

        # Change to temp directory so config is found
        monkeypatch.chdir(tmp_path)

        # Run the hook
        with contextlib.suppress(SystemExit):
            pre_tool_use.main()

        # Check output - should NOT contain hello_world message (default is false)
        output = captured_output.getvalue()
        assert "✅ PreToolUse hook system active" not in output


class TestHelloWorldIntegrationPostToolUse:
    """Test hello_world handler registration in PostToolUse hook."""

    def test_hello_world_handler_registered_when_enabled(self, tmp_path, monkeypatch):
        """When enable_hello_world_handlers is true, handler should be registered."""
        setup_test_git_repo(tmp_path)
        # Create config with flag enabled
        config_file = tmp_path / ".claude" / "hooks-daemon.yaml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text("""
version: "1.0"
daemon:
  enable_hello_world_handlers: true
handlers:
  post_tool_use: {}
""")

        # Mock stdin with tool output
        hook_input = json.dumps({"tool_name": "Bash", "tool_output": "file.txt"})
        monkeypatch.setattr("sys.stdin", StringIO(hook_input))

        # Mock stdout to capture output
        captured_output = StringIO()
        monkeypatch.setattr("sys.stdout", captured_output)

        # Change to temp directory so config is found
        monkeypatch.chdir(tmp_path)

        # Run the hook
        with contextlib.suppress(SystemExit):
            post_tool_use.main()

        # Check output - SHOULD contain hello_world message
        output = captured_output.getvalue()
        # Output is JSON with Unicode-encoded emoji
        assert (
            "✅ PostToolUse hook system active" in output
            or "\\u2705 PostToolUse hook system active" in output
        )


class TestHelloWorldIntegrationSessionStart:
    """Test hello_world handler registration in SessionStart hook."""

    def test_hello_world_handler_registered_when_enabled(self, tmp_path, monkeypatch):
        """When enable_hello_world_handlers is true, handler should be registered."""
        setup_test_git_repo(tmp_path)
        # Create config with flag enabled
        config_file = tmp_path / ".claude" / "hooks-daemon.yaml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text("""
version: "1.0"
daemon:
  enable_hello_world_handlers: true
handlers:
  session_start: {}
""")

        # Mock stdin with session start
        hook_input = json.dumps({"source": "new"})
        monkeypatch.setattr("sys.stdin", StringIO(hook_input))

        # Mock stdout to capture output
        captured_output = StringIO()
        monkeypatch.setattr("sys.stdout", captured_output)

        # Change to temp directory so config is found
        monkeypatch.chdir(tmp_path)

        # Run the hook
        with contextlib.suppress(SystemExit):
            session_start.main()

        # Check output - SHOULD contain hello_world message
        output = captured_output.getvalue()
        # Output is JSON with Unicode-encoded emoji
        assert (
            "✅ SessionStart hook system active" in output
            or "\\u2705 SessionStart hook system active" in output
        )
