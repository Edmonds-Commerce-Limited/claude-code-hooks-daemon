"""Integration tests for hook entry points - targeting branch coverage.

These tests specifically target uncovered branches in hook entry points
to reach 95% combined coverage.
"""

import json
import subprocess
import sys
from pathlib import Path
from typing import Any


class TestEntryPointBranchCoverage:
    """Tests targeting specific branch coverage in hook entry points."""

    def _run_entry_point(
        self,
        module: str,
        hook_input: dict[str, Any],
        cwd: Path,
    ) -> subprocess.CompletedProcess[str]:
        """Helper to run a hook entry point module.

        Args:
            module: Module name (e.g., "claude_code_hooks_daemon.hooks.notification")
            hook_input: Hook input dictionary
            cwd: Working directory

        Returns:
            Subprocess result
        """
        return subprocess.run(
            [sys.executable, "-m", module],
            input=json.dumps(hook_input),
            capture_output=True,
            text=True,
            cwd=cwd,
        )

    def test_notification_without_config_file(self, tmp_path: Path) -> None:
        """Notification hook works without config file (FileNotFoundError branch)."""
        # No config file - triggers FileNotFoundError in ConfigLoader.find_config()
        hook_input = {
            "level": "info",
            "message": "Test notification",
        }

        result = self._run_entry_point(
            "claude_code_hooks_daemon.hooks.notification",
            hook_input,
            tmp_path,
        )

        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output == {}  # Silent allow

    def test_permission_request_without_config_file(self, tmp_path: Path) -> None:
        """PermissionRequest hook works without config file."""
        hook_input = {
            "permission_type": "file_read",
            "resource": "/tmp/test.txt",
        }

        result = self._run_entry_point(
            "claude_code_hooks_daemon.hooks.permission_request",
            hook_input,
            tmp_path,
        )

        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output == {}

    def test_stop_without_config_file(self, tmp_path: Path) -> None:
        """Stop hook works without config file."""
        hook_input = {
            "reason": "user_request",
        }

        result = self._run_entry_point(
            "claude_code_hooks_daemon.hooks.stop",
            hook_input,
            tmp_path,
        )

        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output == {}

    def test_user_prompt_submit_without_config_file(self, tmp_path: Path) -> None:
        """UserPromptSubmit hook works without config file."""
        hook_input = {
            "prompt": "Test prompt",
        }

        result = self._run_entry_point(
            "claude_code_hooks_daemon.hooks.user_prompt_submit",
            hook_input,
            tmp_path,
        )

        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output == {}

    def test_subagent_stop_without_config_file(self, tmp_path: Path) -> None:
        """SubagentStop hook works without config file."""
        hook_input = {
            "subagent_name": "test-agent",
            "reason": "completed",
        }

        result = self._run_entry_point(
            "claude_code_hooks_daemon.hooks.subagent_stop",
            hook_input,
            tmp_path,
        )

        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output == {}

    def test_pre_compact_without_config_file(self, tmp_path: Path) -> None:
        """PreCompact hook works without config file."""
        hook_input = {
            "reason": "token_limit",
        }

        result = self._run_entry_point(
            "claude_code_hooks_daemon.hooks.pre_compact",
            hook_input,
            tmp_path,
        )

        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output == {}

    def test_session_end_without_config_file(self, tmp_path: Path) -> None:
        """SessionEnd hook works without config file."""
        hook_input = {
            "session_id": "test-session",
        }

        result = self._run_entry_point(
            "claude_code_hooks_daemon.hooks.session_end",
            hook_input,
            tmp_path,
        )

        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output == {}

    def test_post_tool_use_without_config_file(self, tmp_path: Path) -> None:
        """PostToolUse hook works without config file."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "echo test"},
            "tool_output": {"stdout": "test\n"},
        }

        result = self._run_entry_point(
            "claude_code_hooks_daemon.hooks.post_tool_use",
            hook_input,
            tmp_path,
        )

        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output == {}

    def test_session_start_without_config_file(self, tmp_path: Path) -> None:
        """SessionStart hook works without config file."""
        hook_input = {
            "session_id": "test-session",
        }

        result = self._run_entry_point(
            "claude_code_hooks_daemon.hooks.session_start",
            hook_input,
            tmp_path,
        )

        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output == {}

    def test_pre_tool_use_with_tag_filtering_enable_tags(self, tmp_path: Path) -> None:
        """PreToolUse handler registration respects enable_tags configuration."""
        # Create config with enable_tags at event level
        config_file = tmp_path / ".claude" / "hooks-daemon.yaml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text("""
version: '1.0'
handlers:
  pre_tool_use:
    enable_tags: ["safety"]  # Event-level: only enable handlers with 'safety' tag
    destructive_git:
      enabled: true
plugins: []
""")

        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "git reset --hard"},
        }

        result = self._run_entry_point(
            "claude_code_hooks_daemon.hooks.pre_tool_use",
            hook_input,
            tmp_path,
        )

        assert result.returncode == 0
        output = json.loads(result.stdout)
        # Handler should be registered and block
        assert "hookSpecificOutput" in output

    def test_pre_tool_use_with_tag_filtering_disable_tags(self, tmp_path: Path) -> None:
        """PreToolUse handler registration respects disable_tags configuration."""
        # Create config with disable_tags at event level
        config_file = tmp_path / ".claude" / "hooks-daemon.yaml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text("""
version: '1.0'
handlers:
  pre_tool_use:
    disable_tags: ["safety"]  # Event-level: disables handlers with 'safety' tag
    destructive_git:
      enabled: true
plugins: []
""")

        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "git reset --hard"},
        }

        result = self._run_entry_point(
            "claude_code_hooks_daemon.hooks.pre_tool_use",
            hook_input,
            tmp_path,
        )

        assert result.returncode == 0
        output = json.loads(result.stdout)
        # Handler should be skipped due to disable_tags - silent allow
        assert output == {}

    def test_post_tool_use_with_tag_filtering_enable_tags(self, tmp_path: Path) -> None:
        """PostToolUse handler registration respects enable_tags."""
        config_file = tmp_path / ".claude" / "hooks-daemon.yaml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text("""
version: '1.0'
handlers:
  post_tool_use:
    enable_tags: ["workflow"]  # Event-level: only enable handlers with 'workflow' tag
    worktree_file_copy:
      enabled: true
plugins: []
""")

        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "git status"},
            "tool_output": {"stdout": "nothing to commit"},
        }

        result = self._run_entry_point(
            "claude_code_hooks_daemon.hooks.post_tool_use",
            hook_input,
            tmp_path,
        )

        assert result.returncode == 0
        # Should work (tag matches)

    def test_post_tool_use_with_tag_filtering_disable_tags(self, tmp_path: Path) -> None:
        """PostToolUse handler registration respects disable_tags."""
        config_file = tmp_path / ".claude" / "hooks-daemon.yaml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text("""
version: '1.0'
handlers:
  post_tool_use:
    disable_tags: ["workflow"]  # Event-level: disable handlers with 'workflow' tag
    worktree_file_copy:
      enabled: true
plugins: []
""")

        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "git status"},
            "tool_output": {"stdout": "nothing to commit"},
        }

        result = self._run_entry_point(
            "claude_code_hooks_daemon.hooks.post_tool_use",
            hook_input,
            tmp_path,
        )

        assert result.returncode == 0
        # Handler disabled by tag

    def test_session_end_with_tag_filtering_enable_tags(self, tmp_path: Path) -> None:
        """SessionEnd handler registration respects enable_tags."""
        config_file = tmp_path / ".claude" / "hooks-daemon.yaml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text("""
version: '1.0'
handlers:
  session_end:
    enable_tags: ["workflow"]  # Event-level: only enable handlers with 'workflow' tag
    workflow_state_cleanup:
      enabled: true
plugins: []
""")

        hook_input = {
            "session_id": "test-session",
        }

        result = self._run_entry_point(
            "claude_code_hooks_daemon.hooks.session_end",
            hook_input,
            tmp_path,
        )

        assert result.returncode == 0

    def test_session_end_with_tag_filtering_disable_tags(self, tmp_path: Path) -> None:
        """SessionEnd handler registration respects disable_tags."""
        config_file = tmp_path / ".claude" / "hooks-daemon.yaml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text("""
version: '1.0'
handlers:
  session_end:
    disable_tags: ["workflow"]  # Event-level: disable handlers with 'workflow' tag
    workflow_state_cleanup:
      enabled: true
plugins: []
""")

        hook_input = {
            "session_id": "test-session",
        }

        result = self._run_entry_point(
            "claude_code_hooks_daemon.hooks.session_end",
            hook_input,
            tmp_path,
        )

        assert result.returncode == 0

    def test_notification_with_tag_filtering_enable_tags(self, tmp_path: Path) -> None:
        """Notification hook respects enable_tags at event level."""
        config_file = tmp_path / ".claude" / "hooks-daemon.yaml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text("""
version: '1.0'
handlers:
  notification:
    enable_tags: ["logging"]  # notification_logger has 'logging' tag
    notification_logger:
      enabled: true
plugins: []
""")

        hook_input = {
            "level": "info",
            "message": "Test",
        }

        result = self._run_entry_point(
            "claude_code_hooks_daemon.hooks.notification",
            hook_input,
            tmp_path,
        )

        assert result.returncode == 0

    def test_notification_with_tag_filtering_disable_tags(self, tmp_path: Path) -> None:
        """Notification hook respects disable_tags at event level."""
        config_file = tmp_path / ".claude" / "hooks-daemon.yaml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text("""
version: '1.0'
handlers:
  notification:
    disable_tags: ["logging"]  # Will disable notification_logger
    notification_logger:
      enabled: true
plugins: []
""")

        hook_input = {
            "level": "info",
            "message": "Test",
        }

        result = self._run_entry_point(
            "claude_code_hooks_daemon.hooks.notification",
            hook_input,
            tmp_path,
        )

        assert result.returncode == 0

    def test_permission_request_with_tag_filtering(self, tmp_path: Path) -> None:
        """PermissionRequest hook respects tag filtering."""
        config_file = tmp_path / ".claude" / "hooks-daemon.yaml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text("""
version: '1.0'
handlers:
  permission_request:
    enable_tags: ["security"]
plugins: []
""")

        hook_input = {
            "permission_type": "file_read",
            "resource": "/tmp/test.txt",
        }

        result = self._run_entry_point(
            "claude_code_hooks_daemon.hooks.permission_request",
            hook_input,
            tmp_path,
        )

        assert result.returncode == 0

    def test_stop_with_tag_filtering(self, tmp_path: Path) -> None:
        """Stop hook respects tag filtering."""
        config_file = tmp_path / ".claude" / "hooks-daemon.yaml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text("""
version: '1.0'
handlers:
  stop:
    disable_tags: ["workflow"]
plugins: []
""")

        hook_input = {
            "reason": "user_request",
        }

        result = self._run_entry_point(
            "claude_code_hooks_daemon.hooks.stop",
            hook_input,
            tmp_path,
        )

        assert result.returncode == 0

    def test_user_prompt_submit_with_tag_filtering(self, tmp_path: Path) -> None:
        """UserPromptSubmit hook respects tag filtering."""
        config_file = tmp_path / ".claude" / "hooks-daemon.yaml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text("""
version: '1.0'
handlers:
  user_prompt_submit:
    enable_tags: ["workflow"]
plugins: []
""")

        hook_input = {
            "prompt": "Test",
        }

        result = self._run_entry_point(
            "claude_code_hooks_daemon.hooks.user_prompt_submit",
            hook_input,
            tmp_path,
        )

        assert result.returncode == 0

    def test_subagent_stop_with_tag_filtering(self, tmp_path: Path) -> None:
        """SubagentStop hook respects tag filtering."""
        config_file = tmp_path / ".claude" / "hooks-daemon.yaml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text("""
version: '1.0'
handlers:
  subagent_stop:
    disable_tags: ["workflow"]
plugins: []
""")

        hook_input = {
            "subagent_name": "test",
            "reason": "completed",
        }

        result = self._run_entry_point(
            "claude_code_hooks_daemon.hooks.subagent_stop",
            hook_input,
            tmp_path,
        )

        assert result.returncode == 0

    def test_pre_compact_with_tag_filtering(self, tmp_path: Path) -> None:
        """PreCompact hook respects tag filtering."""
        config_file = tmp_path / ".claude" / "hooks-daemon.yaml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text("""
version: '1.0'
handlers:
  pre_compact:
    enable_tags: ["workflow"]
plugins: []
""")

        hook_input = {
            "reason": "token_limit",
        }

        result = self._run_entry_point(
            "claude_code_hooks_daemon.hooks.pre_compact",
            hook_input,
            tmp_path,
        )

        assert result.returncode == 0

    def test_session_start_with_tag_filtering(self, tmp_path: Path) -> None:
        """SessionStart hook respects tag filtering."""
        config_file = tmp_path / ".claude" / "hooks-daemon.yaml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text("""
version: '1.0'
handlers:
  session_start:
    disable_tags: ["safety"]
plugins: []
""")

        hook_input = {
            "session_id": "test",
        }

        result = self._run_entry_point(
            "claude_code_hooks_daemon.hooks.session_start",
            hook_input,
            tmp_path,
        )

        assert result.returncode == 0
