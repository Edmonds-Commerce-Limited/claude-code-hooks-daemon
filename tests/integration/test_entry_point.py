"""Integration tests for PreToolUse entry point.

Tests the full workflow: config loading → handler registration → hook processing.
"""

import json
import subprocess
import sys
from pathlib import Path


class TestPreToolUseEntryPoint:
    """Integration tests for pre_tool_use.py entry point."""

    def test_entry_point_with_minimal_config(self, tmp_path: Path) -> None:
        """Entry point works with minimal configuration."""
        # Create minimal config
        config_file = tmp_path / ".claude" / "hooks-daemon.yaml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text("""
version: '1.0'
handlers:
  pre_tool_use: {}
plugins: []
""")

        # Create hook input (allow operation)
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "ls -la"},
        }

        # Run entry point
        result = subprocess.run(
            [sys.executable, "-m", "claude_code_hooks_daemon.hooks.pre_tool_use"],
            input=json.dumps(hook_input),
            capture_output=True,
            text=True,
            cwd=tmp_path,
        )

        assert result.returncode == 0
        output = json.loads(result.stdout)

        # Should allow (no handlers match) - silent allow returns empty dict
        assert output == {}

    def test_entry_point_blocks_destructive_git(self, tmp_path: Path) -> None:
        """Entry point blocks destructive git commands via handler."""
        # Create config with destructive_git enabled
        config_file = tmp_path / ".claude" / "hooks-daemon.yaml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text("""
version: '1.0'
handlers:
  pre_tool_use:
    destructive_git:
      enabled: true
plugins: []
""")

        # Create hook input (destructive git)
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "git reset --hard HEAD~1"},
        }

        # Run entry point
        result = subprocess.run(
            [sys.executable, "-m", "claude_code_hooks_daemon.hooks.pre_tool_use"],
            input=json.dumps(hook_input),
            capture_output=True,
            text=True,
            cwd=tmp_path,
        )

        assert result.returncode == 0
        output = json.loads(result.stdout)

        # Should block
        assert "hookSpecificOutput" in output
        hook_output = output["hookSpecificOutput"]
        assert hook_output["permissionDecision"] == "deny"
        assert "destructive" in hook_output["permissionDecisionReason"].lower()

    def test_entry_point_with_disabled_handler(self, tmp_path: Path) -> None:
        """Disabled handlers are not invoked."""
        # Create config with handler disabled
        config_file = tmp_path / ".claude" / "hooks-daemon.yaml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text("""
version: '1.0'
handlers:
  pre_tool_use:
    destructive_git:
      enabled: false
plugins: []
""")

        # Create hook input (would normally be blocked)
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "git reset --hard"},
        }

        # Run entry point
        result = subprocess.run(
            [sys.executable, "-m", "claude_code_hooks_daemon.hooks.pre_tool_use"],
            input=json.dumps(hook_input),
            capture_output=True,
            text=True,
            cwd=tmp_path,
        )

        assert result.returncode == 0
        output = json.loads(result.stdout)

        # Should allow (handler disabled) - silent allow
        assert output == {}

    def test_entry_point_with_custom_priority(self, tmp_path: Path) -> None:
        """Custom priority configuration is applied."""
        # Create config with custom priority
        config_file = tmp_path / ".claude" / "hooks-daemon.yaml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text("""
version: '1.0'
handlers:
  pre_tool_use:
    destructive_git:
      enabled: true
      priority: 5
plugins: []
""")

        # Create hook input
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "git reset --hard"},
        }

        # Run entry point
        result = subprocess.run(
            [sys.executable, "-m", "claude_code_hooks_daemon.hooks.pre_tool_use"],
            input=json.dumps(hook_input),
            capture_output=True,
            text=True,
            cwd=tmp_path,
        )

        assert result.returncode == 0
        output = json.loads(result.stdout)

        # Should still block (priority doesn't affect behavior, just order)
        assert "hookSpecificOutput" in output
        assert output["hookSpecificOutput"]["permissionDecision"] == "deny"

    def test_entry_point_without_config_uses_defaults(self, tmp_path: Path) -> None:
        """Entry point works without config file (uses defaults)."""
        # No config file created

        # Create hook input
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "echo hello"},
        }

        # Run entry point
        result = subprocess.run(
            [sys.executable, "-m", "claude_code_hooks_daemon.hooks.pre_tool_use"],
            input=json.dumps(hook_input),
            capture_output=True,
            text=True,
            cwd=tmp_path,
        )

        assert result.returncode == 0
        output = json.loads(result.stdout)

        # Should allow (safe command) - silent allow
        assert output == {}

    def test_entry_point_with_invalid_json_input(self, tmp_path: Path) -> None:
        """Invalid JSON input doesn't crash (fail-open)."""
        # Create config
        config_file = tmp_path / ".claude" / "hooks-daemon.yaml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text("""
version: '1.0'
handlers:
  pre_tool_use: {}
""")

        # Invalid JSON input
        invalid_input = "{ this is not valid json }"

        # Run entry point
        result = subprocess.run(
            [sys.executable, "-m", "claude_code_hooks_daemon.hooks.pre_tool_use"],
            input=invalid_input,
            capture_output=True,
            text=True,
            cwd=tmp_path,
        )

        assert result.returncode == 0

        # Should output empty dict (fail-open)
        assert result.stdout.strip() == "{}"

    def test_entry_point_processes_multiple_handlers(self, tmp_path: Path) -> None:
        """Multiple enabled handlers are processed in priority order."""
        # Create config with multiple handlers
        config_file = tmp_path / ".claude" / "hooks-daemon.yaml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text("""
version: '1.0'
handlers:
  pre_tool_use:
    destructive_git:
      enabled: true
      priority: 10
    git_stash:
      enabled: true
      priority: 20
plugins: []
""")

        # Test with git stash (should be caught by git_stash handler)
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "git stash"},
        }

        # Run entry point
        result = subprocess.run(
            [sys.executable, "-m", "claude_code_hooks_daemon.hooks.pre_tool_use"],
            input=json.dumps(hook_input),
            capture_output=True,
            text=True,
            cwd=tmp_path,
        )

        assert result.returncode == 0
        output = json.loads(result.stdout)

        # Should allow with guidance/warning about stash
        assert "hookSpecificOutput" in output
        # GitStashHandler now returns ALLOW with guidance instead of DENY
        # This warns the user but doesn't block (stash can be recovered)
        assert output["hookSpecificOutput"].get("guidance") is not None
        assert "stash" in output["hookSpecificOutput"]["guidance"].lower()

    def test_entry_point_allows_safe_commands(self, tmp_path: Path) -> None:
        """Safe commands pass through all handlers."""
        # Create config with all handlers enabled
        config_file = tmp_path / ".claude" / "hooks-daemon.yaml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text("""
version: '1.0'
handlers:
  pre_tool_use:
    destructive_git:
      enabled: true
    git_stash:
      enabled: true
    sed_blocker:
      enabled: true
plugins: []
""")

        # Safe command
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "git status"},
        }

        # Run entry point
        result = subprocess.run(
            [sys.executable, "-m", "claude_code_hooks_daemon.hooks.pre_tool_use"],
            input=json.dumps(hook_input),
            capture_output=True,
            text=True,
            cwd=tmp_path,
        )

        assert result.returncode == 0
        output = json.loads(result.stdout)

        # Should allow - silent allow
        assert output == {}

    def test_entry_point_as_executable_script(self, tmp_path: Path) -> None:
        """Entry point can be run as executable script."""
        # Create minimal config
        config_file = tmp_path / ".claude" / "hooks-daemon.yaml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text("""
version: '1.0'
handlers:
  pre_tool_use: {}
""")

        # Get path to entry point script
        entry_point = (
            Path(__file__).parent.parent.parent
            / "src/claude_code_hooks_daemon/hooks/pre_tool_use.py"
        )

        # Hook input
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "echo test"},
        }

        # Run with sys.executable (executable bit not needed for modules)
        result = subprocess.run(
            [sys.executable, str(entry_point)],
            input=json.dumps(hook_input),
            capture_output=True,
            text=True,
            cwd=tmp_path,
        )

        assert result.returncode == 0
        output = json.loads(result.stdout)
        # Silent allow
        assert output == {}
