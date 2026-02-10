"""OptimalConfigCheckerHandler - Checks Claude Code config for optimal settings.

Runs on SessionStart to audit environment variables and settings.json
for optimal Claude Code configuration. Reports issues with explanations,
benefits, and how-to-fix instructions with links to docs.

Checks:
1. Agent Teams env var (CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1)
2. Effort Level (should be "high")
3. Extended Thinking (alwaysThinkingEnabled)
4. Max Output Tokens (CLAUDE_CODE_MAX_OUTPUT_TOKENS=64000)
5. Auto Memory (CLAUDE_CODE_DISABLE_AUTO_MEMORY should NOT be "1")
6. Bash Working Directory (CLAUDE_BASH_MAINTAIN_PROJECT_WORKING_DIR=1)
"""

import json
import logging
import os
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, HookInputField, Priority
from claude_code_hooks_daemon.core import Decision, Handler, HookResult

logger = logging.getLogger(__name__)

DOCS_URL = "https://code.claude.com/docs/en/settings"


class OptimalConfigCheckerHandler(Handler):
    """Check Claude Code environment for optimal configuration on session start.

    Advisory handler that runs on new sessions only (not resumes).
    Reports which settings are optimal and which need attention,
    with clear fix instructions and documentation links.
    """

    def __init__(self) -> None:
        """Initialise the optimal config checker handler."""
        super().__init__(
            handler_id=HandlerID.OPTIMAL_CONFIG_CHECKER,
            priority=Priority.OPTIMAL_CONFIG_CHECKER,
            terminal=False,
            tags=[
                HandlerTag.ADVISORY,
                HandlerTag.WORKFLOW,
                HandlerTag.NON_TERMINAL,
                HandlerTag.ENVIRONMENT,
            ],
        )

    def _is_resume_session(self, hook_input: dict[str, Any]) -> bool:
        """Check if this is a resumed session (transcript has content).

        Args:
            hook_input: SessionStart hook input

        Returns:
            True if resume, False if new session
        """
        transcript_path = hook_input.get(HookInputField.TRANSCRIPT_PATH)
        if not transcript_path:
            return False

        try:
            path = Path(transcript_path)
            if not path.exists():
                return False
            return path.stat().st_size > 100
        except (OSError, ValueError):
            return False

    def _read_global_settings(self) -> dict[str, Any]:
        """Read ~/.claude/settings.json.

        Returns:
            Parsed settings dict, or empty dict on failure
        """
        try:
            settings_path = Path.home() / ".claude" / "settings.json"
            if not settings_path.exists():
                return {}
            with settings_path.open() as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
            return {}
        except (OSError, json.JSONDecodeError, ValueError) as e:
            logger.debug("Failed to read global settings: %s", e)
            return {}

    def _check_agent_teams(self) -> dict[str, Any]:
        """Check if agent teams env var is enabled."""
        value = os.environ.get("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS", "")
        passed = value == "1"
        return {
            "name": "Agent Teams",
            "passed": passed,
            "current": f"CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS={value!r}" if value else "Not set",
            "why": (
                "Enables multi-agent team collaboration. Agents can spawn teammates "
                "for parallel work, code review, and complex orchestration."
            ),
            "fix": 'Set environment variable: export CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS="1"',
            "where": "~/.bashrc, ~/.zshrc, or settings.json env section",
            "docs": DOCS_URL,
        }

    def _check_effort_level(self) -> dict[str, Any]:
        """Check if effort level is set to high."""
        env_value = os.environ.get("CLAUDE_CODE_EFFORT_LEVEL", "")
        settings = self._read_global_settings()
        settings_value = str(settings.get("effortLevel", ""))

        # Env var takes precedence
        effective = env_value or settings_value or "not set"
        passed = effective == "high"

        return {
            "name": "Effort Level",
            "passed": passed,
            "current": f"effortLevel={effective!r}",
            "why": (
                "High effort level makes Claude think more deeply, produce higher quality code, "
                "and catch more edge cases. Medium/low saves tokens but reduces quality."
            ),
            "fix": (
                'Set in ~/.claude/settings.json: {"effortLevel": "high"}\n'
                '  Or env var: export CLAUDE_CODE_EFFORT_LEVEL="high"'
            ),
            "where": "~/.claude/settings.json or environment variable",
            "docs": DOCS_URL,
        }

    def _check_extended_thinking(self) -> dict[str, Any]:
        """Check if extended thinking is enabled."""
        settings = self._read_global_settings()
        enabled = settings.get("alwaysThinkingEnabled", False)

        return {
            "name": "Extended Thinking",
            "passed": bool(enabled),
            "current": f"alwaysThinkingEnabled={enabled!r}",
            "why": (
                "Extended thinking gives Claude a scratchpad for complex reasoning before "
                "responding. Significantly improves quality on hard problems, debugging, "
                "and architectural decisions."
            ),
            "fix": 'Set in ~/.claude/settings.json: {"alwaysThinkingEnabled": true}',
            "where": "~/.claude/settings.json",
            "docs": DOCS_URL,
        }

    def _check_max_output_tokens(self) -> dict[str, Any]:
        """Check if max output tokens is set to maximum (64000)."""
        value = os.environ.get("CLAUDE_CODE_MAX_OUTPUT_TOKENS", "")
        try:
            tokens = int(value) if value else 0
        except ValueError:
            tokens = 0

        passed = tokens >= 64000

        return {
            "name": "Max Output Tokens",
            "passed": passed,
            "current": (
                f"CLAUDE_CODE_MAX_OUTPUT_TOKENS={value!r}" if value else "Not set (default: 32000)"
            ),
            "why": (
                "Default is 32,000 tokens. Setting to 64,000 doubles the maximum response "
                "length, preventing truncated outputs on large code generation, refactoring, "
                "and detailed explanations."
            ),
            "fix": 'Set environment variable: export CLAUDE_CODE_MAX_OUTPUT_TOKENS="64000"',
            "where": "~/.bashrc, ~/.zshrc, or settings.json env section",
            "docs": DOCS_URL,
        }

    def _check_auto_memory(self) -> dict[str, Any]:
        """Check if auto-memory is NOT disabled."""
        value = os.environ.get("CLAUDE_CODE_DISABLE_AUTO_MEMORY", "")
        disabled = value == "1"

        return {
            "name": "Auto Memory",
            "passed": not disabled,
            "current": (
                "DISABLED (CLAUDE_CODE_DISABLE_AUTO_MEMORY=1)" if disabled else "Enabled (default)"
            ),
            "why": (
                "Auto-memory lets Claude learn from past sessions - recording patterns, "
                "mistakes, and project-specific knowledge in MEMORY.md files. "
                "Disabling it means Claude starts fresh every session."
            ),
            "fix": "Remove or unset: unset CLAUDE_CODE_DISABLE_AUTO_MEMORY",
            "where": "Check ~/.bashrc, ~/.zshrc, and settings.json env section",
            "docs": DOCS_URL,
        }

    def _check_bash_working_dir(self) -> dict[str, Any]:
        """Check if bash maintains project working directory."""
        value = os.environ.get("CLAUDE_BASH_MAINTAIN_PROJECT_WORKING_DIR", "")
        passed = value == "1"

        return {
            "name": "Bash Working Directory",
            "passed": passed,
            "current": (
                f"CLAUDE_BASH_MAINTAIN_PROJECT_WORKING_DIR={value!r}" if value else "Not set"
            ),
            "why": (
                "Without this, cd commands in bash persist between tool calls, causing "
                "Claude to lose track of the working directory. With it enabled, each "
                "bash command resets to the project root - preventing path confusion."
            ),
            "fix": 'Set environment variable: export CLAUDE_BASH_MAINTAIN_PROJECT_WORKING_DIR="1"',
            "where": "~/.bashrc, ~/.zshrc, or settings.json env section",
            "docs": DOCS_URL,
        }

    def _run_checks(self) -> list[dict[str, Any]]:
        """Run all configuration checks.

        Returns:
            List of check result dicts with name, passed, current, why, fix, docs
        """
        return [
            self._check_agent_teams(),
            self._check_effort_level(),
            self._check_extended_thinking(),
            self._check_max_output_tokens(),
            self._check_auto_memory(),
            self._check_bash_working_dir(),
        ]

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Only match on new sessions (not resumes).

        Args:
            hook_input: SessionStart hook input

        Returns:
            True for new sessions, False for resumes
        """
        return not self._is_resume_session(hook_input)

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Run config checks and return advisory context.

        Args:
            hook_input: SessionStart hook input

        Returns:
            HookResult with ALLOW decision and config check results
        """
        checks = self._run_checks()
        failures = [c for c in checks if not c["passed"]]
        passes = [c for c in checks if c["passed"]]

        lines: list[str] = []

        if not failures:
            lines.append(
                f"CONFIG CHECK: All {len(checks)} checks passed - configuration is optimal."
            )
        else:
            lines.append(f"CONFIG CHECK: {len(failures)}/{len(checks)} settings need attention")
            lines.append("")

            for check in failures:
                lines.append(f"  MISSING: {check['name']}")
                lines.append(f"    Current: {check['current']}")
                lines.append(f"    Why: {check['why']}")
                lines.append(f"    Fix: {check['fix']}")
                lines.append(f"    Where: {check['where']}")
                lines.append(f"    Docs: {check['docs']}")
                lines.append("")

            if passes:
                pass_names = ", ".join(c["name"] for c in passes)
                lines.append(f"  OK: {pass_names}")

        return HookResult(decision=Decision.ALLOW, context=lines)

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for this handler."""
        from claude_code_hooks_daemon.core import AcceptanceTest, TestType

        return [
            AcceptanceTest(
                title="optimal config checker - reports configuration issues",
                command='echo "test"',
                description=(
                    "Tests that the handler checks Claude Code environment for optimal "
                    "configuration (agent teams, effort level, thinking, max tokens, "
                    "auto memory, bash working dir) and reports issues with fix instructions."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"CONFIG CHECK"],
                safety_notes="Advisory handler - reports but does not block",
                test_type=TestType.CONTEXT,
                requires_event="SessionStart event (new session only)",
            ),
        ]
