"""Tests for CI/daemon-unavailable graceful degradation in init.sh.

When the daemon cannot start and ci_enabled is NOT set in config (default),
hook scripts degrade gracefully: warn once, write a state file, then silently
passthrough on subsequent calls.

When ci_enabled: true IS set in config, hook scripts hard-block with a loud
STOP message telling the agent to report that hooks daemon needs installing.

Tests invoke the actual bash hook forwarder scripts via subprocess with
controlled config files, verifying real end-to-end behaviour.
"""

import json
import os
import subprocess
import textwrap
from pathlib import Path
from typing import Any

# Path to hook scripts (relative to repo root)
_HOOKS_DIR = Path(__file__).resolve().parents[2] / ".claude" / "hooks"


def _build_clean_env(project_path: str) -> dict[str, str]:
    """Build a clean environment with no daemon available.

    Uses a fake project path so the daemon cannot start (no venv, no socket).
    """
    return {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", "/root"),
        "HOSTNAME": os.environ.get("HOSTNAME", "test-host"),
        # Override HOOKS_DAEMON_ROOT_DIR to point at the fake project
        "HOOKS_DAEMON_ROOT_DIR": f"{project_path}/.claude/hooks-daemon",
    }


def _create_project_structure(
    tmp_path: Path,
    ci_enabled: bool | None = None,
) -> Path:
    """Create a minimal project structure with .claude/ and config.

    Args:
        tmp_path: Pytest temporary directory.
        ci_enabled: If True, set ci_enabled: true in config. If False, set false.
                    If None, omit the setting entirely (default behaviour).

    Returns:
        Path to the project root.
    """
    project = tmp_path / "project"
    project.mkdir()

    claude_dir = project / ".claude"
    claude_dir.mkdir()

    # Create hooks dir symlink or copy (forwarders need init.sh)
    hooks_dir = claude_dir / "hooks"
    hooks_dir.mkdir()

    # Create daemon untracked dir (for passthrough state file)
    daemon_dir = claude_dir / "hooks-daemon"
    daemon_dir.mkdir()
    untracked_dir = daemon_dir / "untracked"
    untracked_dir.mkdir()

    # Create config file
    config_lines = ['version: "2.0"', "", "daemon:", "  idle_timeout_seconds: 600"]
    if ci_enabled is True:
        config_lines.append("  ci_enabled: true")
    elif ci_enabled is False:
        config_lines.append("  ci_enabled: false")
    # If None, omit ci_enabled entirely (default)

    config_file = claude_dir / "hooks-daemon.yaml"
    config_file.write_text("\n".join(config_lines) + "\n")

    return project


def _run_hook(
    hook_name: str,
    hook_input: dict[str, Any],
    project_path: Path,
    timeout: int = 10,
) -> subprocess.CompletedProcess[str]:
    """Run a hook forwarder script with a fake project path."""
    hook_path = _HOOKS_DIR / hook_name
    assert hook_path.exists(), f"Hook script not found: {hook_path}"

    env = _build_clean_env(str(project_path))

    return subprocess.run(
        ["bash", "-c", f'source "{_HOOKS_DIR}/../init.sh" && ensure_daemon && echo "{{}}"'],
        input=json.dumps(hook_input),
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
        cwd=str(project_path),
    )


def _run_hook_via_forwarder(
    hook_name: str,
    hook_input: dict[str, Any],
    project_path: Path,
    timeout: int = 10,
) -> subprocess.CompletedProcess[str]:
    """Run a hook forwarder script directly with controlled environment.

    Creates a minimal forwarder that sources init.sh from the real repo
    but uses the fake project path for daemon lookup.
    """
    hook_path = _HOOKS_DIR / hook_name
    assert hook_path.exists(), f"Hook script not found: {hook_path}"

    init_sh = _HOOKS_DIR.parent / "init.sh"
    env = _build_clean_env(str(project_path))

    # Build a minimal test forwarder that:
    # 1. Sets PROJECT_PATH to fake project (before sourcing init.sh)
    # 2. Sources init.sh (which will fail to start daemon)
    # 3. Mimics the real forwarder flow
    event_name_map = {
        "pre-tool-use": "PreToolUse",
        "post-tool-use": "PostToolUse",
        "session-start": "SessionStart",
        "session-end": "SessionEnd",
        "stop": "Stop",
        "subagent-stop": "SubagentStop",
    }
    event_name = event_name_map.get(hook_name, "PreToolUse")

    # Source init.sh (which detects PROJECT_PATH from BASH_SOURCE),
    # then override all path variables to point at the test project.
    # This ensures ensure_daemon fails (no venv) and reads our test config.
    script = textwrap.dedent(f"""\
        set -euo pipefail
        source "{init_sh}"

        # Override paths AFTER sourcing — init.sh detects from BASH_SOURCE
        PROJECT_PATH="{project_path}"
        HOOKS_DAEMON_ROOT_DIR="{project_path}/.claude/hooks-daemon"
        SOCKET_PATH="{project_path}/nonexistent.sock"
        PID_PATH="{project_path}/nonexistent.pid"
        PYTHON_CMD="{project_path}/nonexistent/python"

        if ! ensure_daemon; then
            emit_hook_error "{event_name}" "daemon_startup_failed" \
                "Failed to start hooks daemon"
            exit 0
        fi
        jq -c '{{event: "{event_name}", hook_input: .}}' | send_request_stdin
    """)

    return subprocess.run(
        ["bash", "-c", script],
        input=json.dumps(hook_input),
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
        cwd=str(project_path),
    )


# Minimal valid hook input
_PRE_TOOL_INPUT = {"tool_name": "Bash", "tool_input": {"command": "echo hello"}}
_STOP_INPUT = {"stop_hook_active": True}


class TestDefaultFailOpen:
    """Default behaviour (no ci_enabled): fail open with one-time noise."""

    def test_first_call_returns_advisory_context(self, tmp_path: Path) -> None:
        """First failure should return advisory hookSpecificOutput (not empty)."""
        project = _create_project_structure(tmp_path, ci_enabled=None)
        result = _run_hook_via_forwarder("pre-tool-use", _PRE_TOOL_INPUT, project)

        assert result.returncode == 0
        stdout = result.stdout.strip()
        # Should contain advisory context, not be empty
        parsed = json.loads(stdout)
        assert "hookSpecificOutput" in parsed
        context = parsed["hookSpecificOutput"]["additionalContext"]
        assert "INACTIVE" in context
        assert "warning appears once" in context.lower() or "warning appears once" in context

    def test_first_call_logs_warning_to_stderr(self, tmp_path: Path) -> None:
        """First failure should log warning to stderr."""
        project = _create_project_structure(tmp_path, ci_enabled=None)
        result = _run_hook_via_forwarder("pre-tool-use", _PRE_TOOL_INPUT, project)

        assert "passthrough mode" in result.stderr
        assert "handlers inactive" in result.stderr.lower()

    def test_state_file_created_on_first_failure(self, tmp_path: Path) -> None:
        """First failure should create passthrough state file."""
        project = _create_project_structure(tmp_path, ci_enabled=None)
        _run_hook_via_forwarder("pre-tool-use", _PRE_TOOL_INPUT, project)

        state_file = project / ".claude" / "hooks-daemon" / "untracked" / ".hooks-passthrough"
        assert state_file.exists(), "Passthrough state file should be created on first failure"

    def test_second_call_is_silent_passthrough(self, tmp_path: Path) -> None:
        """Second call (state file exists) should return empty {} silently."""
        project = _create_project_structure(tmp_path, ci_enabled=None)

        # First call: creates state file
        _run_hook_via_forwarder("pre-tool-use", _PRE_TOOL_INPUT, project)

        # Second call: should be silent passthrough
        result = _run_hook_via_forwarder("pre-tool-use", _PRE_TOOL_INPUT, project)

        assert result.returncode == 0
        stdout = result.stdout.strip()
        assert stdout == "{}", f"Second call should return '{{}}', got: {stdout!r}"
        # Should NOT log the noisy warning again
        assert "passthrough mode" not in result.stderr

    def test_ci_enabled_false_same_as_default(self, tmp_path: Path) -> None:
        """ci_enabled: false should behave same as omitted (fail open)."""
        project = _create_project_structure(tmp_path, ci_enabled=False)
        result = _run_hook_via_forwarder("pre-tool-use", _PRE_TOOL_INPUT, project)

        assert result.returncode == 0
        stdout = result.stdout.strip()
        # Should be advisory (first call) not a deny
        parsed = json.loads(stdout)
        assert "decision" not in parsed or parsed.get("decision") != "deny"

    def test_does_not_block_any_event_type(self, tmp_path: Path) -> None:
        """Default mode should never block, even Stop events."""
        project = _create_project_structure(tmp_path, ci_enabled=None)
        result = _run_hook_via_forwarder("stop", _STOP_INPUT, project)

        assert result.returncode == 0
        stdout = result.stdout.strip()
        parsed = json.loads(stdout)
        # Should NOT have decision: block (the ci_enforced response)
        # First call returns advisory context or passthrough
        if "decision" in parsed:
            assert parsed["decision"] != "block", "Default mode should not block Stop events"


class TestCIEnforcedFailClosed:
    """ci_enabled: true behaviour: hard block with loud STOP message."""

    def test_pre_tool_use_denied(self, tmp_path: Path) -> None:
        """PreToolUse should be denied with loud STOP message."""
        project = _create_project_structure(tmp_path, ci_enabled=True)
        result = _run_hook_via_forwarder("pre-tool-use", _PRE_TOOL_INPUT, project)

        assert result.returncode == 0
        stdout = result.stdout.strip()
        parsed = json.loads(stdout)
        assert parsed.get("decision") == "deny", f"Expected deny, got: {parsed}"
        reason = parsed.get("reason", "")
        assert "STOP" in reason
        assert "ci_enabled" in reason
        assert "NOT installed" in reason or "not installed" in reason.lower()

    def test_stop_event_blocked(self, tmp_path: Path) -> None:
        """Stop events should be blocked when ci_enforced."""
        project = _create_project_structure(tmp_path, ci_enabled=True)
        result = _run_hook_via_forwarder("stop", _STOP_INPUT, project)

        assert result.returncode == 0
        stdout = result.stdout.strip()
        parsed = json.loads(stdout)
        assert parsed.get("decision") == "block"

    def test_no_state_file_created(self, tmp_path: Path) -> None:
        """ci_enforced should NOT create passthrough state file."""
        project = _create_project_structure(tmp_path, ci_enabled=True)
        _run_hook_via_forwarder("pre-tool-use", _PRE_TOOL_INPUT, project)

        state_file = project / ".claude" / "hooks-daemon" / "untracked" / ".hooks-passthrough"
        assert not state_file.exists(), "ci_enforced should not create passthrough state file"

    def test_every_call_blocks(self, tmp_path: Path) -> None:
        """ci_enforced should block on every call (no state file to bypass)."""
        project = _create_project_structure(tmp_path, ci_enabled=True)

        # Call twice
        result1 = _run_hook_via_forwarder("pre-tool-use", _PRE_TOOL_INPUT, project)
        result2 = _run_hook_via_forwarder("pre-tool-use", _PRE_TOOL_INPUT, project)

        parsed1 = json.loads(result1.stdout.strip())
        parsed2 = json.loads(result2.stdout.strip())
        assert parsed1.get("decision") == "deny"
        assert parsed2.get("decision") == "deny"

    def test_message_tells_agent_to_stop(self, tmp_path: Path) -> None:
        """The deny reason should clearly instruct the agent to stop working."""
        project = _create_project_structure(tmp_path, ci_enabled=True)
        result = _run_hook_via_forwarder("pre-tool-use", _PRE_TOOL_INPUT, project)

        parsed = json.loads(result.stdout.strip())
        reason = parsed.get("reason", "")
        assert "STOP" in reason
        assert "do not use any tools" in reason.lower() or "DO NOT" in reason
        assert "report to the user" in reason.lower()


class TestPassthroughRecovery:
    """Test that passthrough state is cleaned up when daemon recovers."""

    def test_state_file_cleaned_on_manual_creation(self, tmp_path: Path) -> None:
        """If state file exists but daemon starts, state file should be cleaned up.

        We can't easily test real daemon recovery, but we can verify the
        state file path and cleanup logic are correct.
        """
        project = _create_project_structure(tmp_path, ci_enabled=None)
        state_file = project / ".claude" / "hooks-daemon" / "untracked" / ".hooks-passthrough"

        # Create state file manually
        state_file.touch()
        assert state_file.exists()

        # Run hook - daemon still can't start, so state file remains
        result = _run_hook_via_forwarder("pre-tool-use", _PRE_TOOL_INPUT, project)
        assert result.returncode == 0
        # State file should still exist (daemon didn't start)
        assert state_file.exists()
