"""Tests for CI/daemon-unavailable graceful degradation in init.sh.

This module tests three distinct failure modes when the daemon cannot start:

1. NON-CI ENVIRONMENT, NOT INSTALLED (no CI env vars, venv absent):
   Passthrough mode must NOT activate. emit_hook_error is called with "Not
   installed" guidance pointing to CLAUDE/LLM-INSTALL.md. Fail-open for
   most events; block for Stop events.

2. NON-CI ENVIRONMENT, INSTALLED BUT NOT RUNNING (venv present, daemon crashed):
   emit_hook_error is called with "Not currently running" restart guidance.
   Fail-open for most events; block for Stop events. Each call returns an
   error independently — no state file suppression.

3. CI ENVIRONMENT (CI=true, GITHUB_ACTIONS=true, JENKINS_URL set, etc.):
   Passthrough mode activates — daemon is simply not installed in this pipeline.
   First call returns one-time advisory context. Second call (flag exists) returns
   empty {}. No blocking. Supports multiple CI platform detection.

4. CI ENFORCED (ci_enabled: true in config):
   Hard fail regardless of environment. PreToolUse is denied with STOP message.
   Stop events are blocked. No state file created.

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


def _build_clean_env(
    project_path: str,
    ci_env: dict[str, str] | None = None,
) -> dict[str, str]:
    """Build a clean environment with no daemon available.

    Uses a fake project path so the daemon cannot start (no venv, no socket).
    By default, NO CI environment variables are included — this simulates a
    developer machine or dev container where passthrough must NOT activate.

    Args:
        project_path: Path to the fake project root.
        ci_env: Optional dict of CI environment variables to add (e.g.
                {"CI": "true"} or {"GITHUB_ACTIONS": "true"}). If None,
                no CI variables are set — non-CI environment.
    """
    env: dict[str, str] = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", "/root"),
        "HOSTNAME": os.environ.get("HOSTNAME", "test-host"),
        # Override HOOKS_DAEMON_ROOT_DIR to point at the fake project
        "HOOKS_DAEMON_ROOT_DIR": f"{project_path}/.claude/hooks-daemon",
    }
    if ci_env:
        env.update(ci_env)
    return env


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


def _create_installed_stub(project_path: Path) -> None:
    """Create a fake venv python binary so _is_daemon_installed() returns true.

    The test script template hardcodes PYTHON_CMD to {project}/nonexistent/python.
    Creating that file makes the daemon appear 'installed' (dir + venv both present),
    so ensure_daemon() falls through to the 'installed but not running' error path.
    """
    stub = project_path / "nonexistent" / "python"
    stub.parent.mkdir(parents=True, exist_ok=True)
    stub.write_text("#!/bin/bash\nexit 1\n")
    stub.chmod(0o755)


def _run_hook_via_forwarder(
    hook_name: str,
    hook_input: dict[str, Any],
    project_path: Path,
    timeout: int = 10,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a hook forwarder script directly with controlled environment.

    Creates a minimal forwarder that sources init.sh from the real repo
    but uses the fake project path for daemon lookup.

    Args:
        hook_name: Hook script name (e.g. "pre-tool-use").
        hook_input: JSON-serialisable dict to pass as hook input.
        project_path: Path to the fake project root.
        timeout: Subprocess timeout in seconds.
        extra_env: Optional additional environment variables to merge into
                   the clean environment (e.g. {"CI": "true"} for CI tests).
    """
    hook_path = _HOOKS_DIR / hook_name
    assert hook_path.exists(), f"Hook script not found: {hook_path}"

    init_sh = _HOOKS_DIR.parent / "init.sh"
    env = _build_clean_env(str(project_path), ci_env=extra_env)

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


class TestNonCIDaemonFailure:
    """Non-CI environment: daemon failure must NOT enter passthrough mode.

    When running outside a CI environment (no CI env vars), passthrough mode
    must never activate. Instead, emit_hook_error provides install or restart
    guidance depending on whether the daemon is installed. This prevents silent
    protection-bypass in developer environments and dev containers.
    """

    def test_non_ci_not_installed_returns_install_guidance(self, tmp_path: Path) -> None:
        """Non-CI, daemon not installed: hookSpecificOutput points to LLM-INSTALL.md."""
        project = _create_project_structure(tmp_path, ci_enabled=None)
        # No extra_env — no CI variables present; no venv stub — daemon not installed
        result = _run_hook_via_forwarder("pre-tool-use", _PRE_TOOL_INPUT, project)

        assert result.returncode == 0
        stdout = result.stdout.strip()
        parsed = json.loads(stdout)
        assert "hookSpecificOutput" in parsed, f"Expected hookSpecificOutput, got: {parsed}"
        context = parsed["hookSpecificOutput"]["additionalContext"]
        # Must say "Not installed" and point to the install guide
        assert "Not installed" in context, f"Expected 'Not installed' in context, got: {context!r}"
        assert (
            "/hooks-daemon install" in context
        ), f"Expected install skill reference in context, got: {context!r}"
        # Must NOT look like passthrough advisory
        assert (
            "not installed in CI" not in context
        ), "Non-CI not-installed should not show CI advisory language"

    def test_non_ci_installed_but_not_running_shows_restart_guidance(self, tmp_path: Path) -> None:
        """Non-CI, daemon installed but not starting: hookSpecificOutput says 'Not currently running'."""
        project = _create_project_structure(tmp_path, ci_enabled=None)
        _create_installed_stub(project)  # venv python exists → daemon appears installed
        result = _run_hook_via_forwarder("pre-tool-use", _PRE_TOOL_INPUT, project)

        assert result.returncode == 0
        stdout = result.stdout.strip()
        parsed = json.loads(stdout)
        assert "hookSpecificOutput" in parsed, f"Expected hookSpecificOutput, got: {parsed}"
        context = parsed["hookSpecificOutput"]["additionalContext"]
        assert (
            "Not currently running" in context
        ), f"Expected 'Not currently running' in context, got: {context!r}"
        assert "restart" in context, f"Expected restart instruction in context, got: {context!r}"
        assert (
            "LLM-INSTALL.md" not in context
        ), "Installed-but-not-running should not show install guide"

    def test_non_ci_stop_event_blocked(self, tmp_path: Path) -> None:
        """Non-CI daemon failure returns decision: block for Stop events."""
        project = _create_project_structure(tmp_path, ci_enabled=None)
        result = _run_hook_via_forwarder("stop", _STOP_INPUT, project)

        assert result.returncode == 0
        stdout = result.stdout.strip()
        parsed = json.loads(stdout)
        assert (
            parsed.get("decision") == "block"
        ), f"Expected block for Stop in non-CI, got: {parsed}"

    def test_non_ci_no_passthrough_flag_created(self, tmp_path: Path) -> None:
        """Non-CI daemon failure must NOT create the passthrough state file."""
        project = _create_project_structure(tmp_path, ci_enabled=None)
        _run_hook_via_forwarder("pre-tool-use", _PRE_TOOL_INPUT, project)

        state_file = project / ".claude" / "hooks-daemon" / "untracked" / ".hooks-passthrough"
        assert (
            not state_file.exists()
        ), "Passthrough state file must NOT be created in non-CI environments"

    def test_non_ci_second_call_also_returns_error(self, tmp_path: Path) -> None:
        """Each non-CI call returns an error independently (no flag suppression)."""
        project = _create_project_structure(tmp_path, ci_enabled=None)

        result1 = _run_hook_via_forwarder("pre-tool-use", _PRE_TOOL_INPUT, project)
        result2 = _run_hook_via_forwarder("pre-tool-use", _PRE_TOOL_INPUT, project)

        parsed1 = json.loads(result1.stdout.strip())
        parsed2 = json.loads(result2.stdout.strip())
        # Both calls must return error context, not silent {}
        assert "hookSpecificOutput" in parsed1, f"First call should error, got: {parsed1}"
        assert "hookSpecificOutput" in parsed2, f"Second call should also error, got: {parsed2}"
        assert result2.stdout.strip() != "{}", "Second call must not silently passthrough"

    def test_ci_enabled_false_non_ci_still_errors(self, tmp_path: Path) -> None:
        """ci_enabled: false + no CI env vars → error response (not passthrough)."""
        project = _create_project_structure(tmp_path, ci_enabled=False)
        # No CI env vars — non-CI environment; no venv stub — daemon not installed
        result = _run_hook_via_forwarder("pre-tool-use", _PRE_TOOL_INPUT, project)

        assert result.returncode == 0
        stdout = result.stdout.strip()
        parsed = json.loads(stdout)
        # Should show error context, not passthrough advisory or deny
        assert "hookSpecificOutput" in parsed, f"Expected hookSpecificOutput, got: {parsed}"
        context = parsed["hookSpecificOutput"]["additionalContext"]
        # ci_enabled: false still can't start daemon → shows "Not installed" guidance
        assert "Not installed" in context, f"Expected daemon error message, got: {context!r}"


class TestCIEnvironmentPassthrough:
    """CI environment: daemon failure enters passthrough mode (daemon not installed).

    When a CI environment is detected (CI=true, GITHUB_ACTIONS=true, JENKINS_URL,
    TF_BUILD, GITLAB_CI), passthrough mode activates. The daemon is simply not
    installed in the pipeline — safety handlers are not expected to run.

    First call: one-time advisory context returned.
    Subsequent calls: silent {} (state file suppresses noise).
    """

    def test_ci_first_call_returns_advisory(self, tmp_path: Path) -> None:
        """CI=true → first failure returns advisory hookSpecificOutput."""
        project = _create_project_structure(tmp_path, ci_enabled=None)
        result = _run_hook_via_forwarder(
            "pre-tool-use", _PRE_TOOL_INPUT, project, extra_env={"CI": "true"}
        )

        assert result.returncode == 0
        stdout = result.stdout.strip()
        parsed = json.loads(stdout)
        assert (
            "hookSpecificOutput" in parsed
        ), f"CI first failure should return advisory hookSpecificOutput, got: {parsed}"
        context = parsed["hookSpecificOutput"]["additionalContext"]
        assert "INACTIVE" in context, f"Advisory should mention INACTIVE, got: {context!r}"

    def test_ci_first_call_logs_to_stderr(self, tmp_path: Path) -> None:
        """CI=true → first failure logs passthrough warning to stderr."""
        project = _create_project_structure(tmp_path, ci_enabled=None)
        result = _run_hook_via_forwarder(
            "pre-tool-use", _PRE_TOOL_INPUT, project, extra_env={"CI": "true"}
        )

        assert (
            "passthrough mode" in result.stderr
        ), f"Expected 'passthrough mode' in stderr, got: {result.stderr!r}"
        assert (
            "handlers inactive" in result.stderr.lower()
        ), f"Expected 'handlers inactive' in stderr, got: {result.stderr!r}"

    def test_ci_state_file_created(self, tmp_path: Path) -> None:
        """CI=true → first failure creates passthrough state file."""
        project = _create_project_structure(tmp_path, ci_enabled=None)
        _run_hook_via_forwarder("pre-tool-use", _PRE_TOOL_INPUT, project, extra_env={"CI": "true"})

        state_file = project / ".claude" / "hooks-daemon" / "untracked" / ".hooks-passthrough"
        assert state_file.exists(), "Passthrough state file should be created in CI environment"

    def test_ci_second_call_silent_passthrough(self, tmp_path: Path) -> None:
        """CI=true → second call (flag exists) returns empty {} silently."""
        project = _create_project_structure(tmp_path, ci_enabled=None)

        # First call: creates state file and returns advisory
        _run_hook_via_forwarder("pre-tool-use", _PRE_TOOL_INPUT, project, extra_env={"CI": "true"})

        # Second call: should be silent passthrough
        result = _run_hook_via_forwarder(
            "pre-tool-use", _PRE_TOOL_INPUT, project, extra_env={"CI": "true"}
        )

        assert result.returncode == 0
        stdout = result.stdout.strip()
        assert stdout == "{}", f"CI second call should return '{{}}', got: {stdout!r}"
        assert (
            "passthrough mode" not in result.stderr
        ), "Second CI call should not repeat the noisy warning"

    def test_ci_github_actions_also_passthrough(self, tmp_path: Path) -> None:
        """GITHUB_ACTIONS=true (without CI var) → passthrough mode."""
        project = _create_project_structure(tmp_path, ci_enabled=None)
        result = _run_hook_via_forwarder(
            "pre-tool-use",
            _PRE_TOOL_INPUT,
            project,
            extra_env={"GITHUB_ACTIONS": "true"},
        )

        assert result.returncode == 0
        stdout = result.stdout.strip()
        parsed = json.loads(stdout)
        # Should be advisory (passthrough first call) not error
        assert (
            "hookSpecificOutput" in parsed
        ), f"GITHUB_ACTIONS should trigger passthrough advisory, got: {parsed}"
        context = parsed["hookSpecificOutput"]["additionalContext"]
        assert (
            "INACTIVE" in context
        ), f"GITHUB_ACTIONS passthrough should mention INACTIVE, got: {context!r}"

    def test_ci_jenkins_also_passthrough(self, tmp_path: Path) -> None:
        """JENKINS_URL set → passthrough mode (Jenkins does not set CI var)."""
        project = _create_project_structure(tmp_path, ci_enabled=None)
        result = _run_hook_via_forwarder(
            "pre-tool-use",
            _PRE_TOOL_INPUT,
            project,
            extra_env={"JENKINS_URL": "http://jenkins.example.com/"},
        )

        assert result.returncode == 0
        stdout = result.stdout.strip()
        parsed = json.loads(stdout)
        assert (
            "hookSpecificOutput" in parsed
        ), f"JENKINS_URL should trigger passthrough advisory, got: {parsed}"
        context = parsed["hookSpecificOutput"]["additionalContext"]
        assert (
            "INACTIVE" in context
        ), f"Jenkins passthrough should mention INACTIVE, got: {context!r}"


class TestCIEnforcedFailClosed:
    """ci_enabled: true behaviour: hard block with loud STOP message.

    When ci_enabled: true is set in config, the daemon is REQUIRED regardless
    of environment. All operations are blocked until the daemon is installed.
    """

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
    """Passthrough state is cleaned up when the daemon recovers.

    Bug fix: previously the cleanup at start_daemon() success was unreachable
    because the passthrough check returned early before start_daemon() was called.
    The fix: clean up the flag in the is_daemon_running() branch too.
    """

    def test_state_file_not_present_in_non_ci_environment(self, tmp_path: Path) -> None:
        """Non-CI daemon failure must not create state file (nothing to recover from).

        Verifies that after a non-CI failure, no passthrough state file is written.
        Recovery only applies to CI environments where the file IS written.
        """
        project = _create_project_structure(tmp_path, ci_enabled=None)
        state_file = project / ".claude" / "hooks-daemon" / "untracked" / ".hooks-passthrough"

        # Non-CI failure — no state file should be written
        _run_hook_via_forwarder("pre-tool-use", _PRE_TOOL_INPUT, project)
        assert (
            not state_file.exists()
        ), "Non-CI daemon failure must not create passthrough state file"

    def test_ci_state_file_persists_when_daemon_still_down(self, tmp_path: Path) -> None:
        """CI state file remains when daemon still cannot start after second call."""
        project = _create_project_structure(tmp_path, ci_enabled=None)
        state_file = project / ".claude" / "hooks-daemon" / "untracked" / ".hooks-passthrough"

        # First CI call: creates state file
        _run_hook_via_forwarder("pre-tool-use", _PRE_TOOL_INPUT, project, extra_env={"CI": "true"})
        assert state_file.exists(), "State file should exist after first CI failure"

        # Second CI call: daemon still down, state file should remain
        _run_hook_via_forwarder("pre-tool-use", _PRE_TOOL_INPUT, project, extra_env={"CI": "true"})
        assert state_file.exists(), "State file should persist when daemon still not running"
