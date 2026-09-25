"""OptimalConfigCheckerHandler - Checks Claude Code config for optimal settings.

Runs on SessionStart. As of the lean-SessionStart rework (Plan 00128) handle()
no longer emits the full per-setting audit — that report now lives in the
`cli check` command (which reuses ``_run_checks()``). On a session start the
handler only silently enforces critical settings and announces an actual
settings write via a single ``CONFIG SYNC: ...`` line.

The full audit (``_run_checks()``) covers:
1. Agent Teams env var (CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1)
2. Effort Source (warns when anything pins one effort level on every model,
   overriding settings.json's per-model levels; never recommends a level)
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

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import AdvisoryResult, Decision
from claude_code_hooks_daemon.core.handler_bases import SessionStartHandlerBase
from claude_code_hooks_daemon.utils.session_helpers import is_resume_session

logger = logging.getLogger(__name__)

DOCS_URL = "https://code.claude.com/docs/en/settings"

# ── Effort source check (Plan 00466 N47) ─────────────────────────────────────
_EFFORT_ENV_VAR = "CLAUDE_CODE_EFFORT_LEVEL"
# Claude Code reads these as "no explicit level", so they pin nothing.
_EFFORT_ENV_NON_PINNING_VALUES = frozenset({"", "auto", "unset"})
# The settings files that outrank the user file and are read from the project.
_PROJECT_SETTINGS_FILES = ("settings.json", "settings.local.json")
_EFFORT_CHECK_NAME = "Effort Source"
_EFFORT_CHECK_WHY = (
    "Effort is set per model in settings.json under modelSettings, so each model "
    "(and each automatic fallback) runs at its own configured level. The "
    "CLAUDE_CODE_EFFORT_LEVEL environment variable, or a top-level effortLevel "
    "in the project or local settings file, pins ONE level on every model instead "
    "and silently overrides those per-model entries."
)
_EFFORT_CHECK_FIX = (
    "Remove the pin and keep levels per model in modelSettings: "
    "unset CLAUDE_CODE_EFFORT_LEVEL, and delete the top-level effortLevel key "
    "from the project/local settings file"
)
_EFFORT_CHECK_WHERE = (
    "environment (~/.bashrc, ~/.zshrc, settings.json env section), "
    ".claude/settings.json, .claude/settings.local.json"
)


class OptimalConfigCheckerHandler(SessionStartHandlerBase):
    """Check Claude Code environment for optimal configuration on session start.

    Advisory handler that runs on new sessions only (not resumes). On session
    start it silently enforces critical settings and announces an actual
    settings write via a single ``CONFIG SYNC: ...`` line; the full per-setting
    audit (with fix instructions and doc links) is exposed via ``cli check``.
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

    def _get_settings_path(self) -> Path:
        """Get path to Claude global settings file.

        Returns:
            Path to ~/.claude/settings.json
        """
        return Path.home() / ".claude" / "settings.json"

    def _read_global_settings(self) -> dict[str, Any]:
        """Read ~/.claude/settings.json.

        Returns:
            Parsed settings dict, or empty dict on failure
        """
        try:
            settings_path = self._get_settings_path()
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

    def _write_global_settings(self, settings: dict[str, Any]) -> bool:
        """Write settings back to ~/.claude/settings.json.

        Args:
            settings: Complete settings dict to write

        Returns:
            True if write succeeded, False on failure
        """
        try:
            settings_path = self._get_settings_path()
            settings_path.parent.mkdir(parents=True, exist_ok=True)
            with settings_path.open("w") as f:
                json.dump(settings, f, indent=2)
                f.write("\n")
            return True
        except (OSError, ValueError) as e:
            logger.debug("Failed to write global settings: %s", e)
            return False

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

    def _check_effort_source(self, project_root: Path) -> dict[str, Any]:
        """Warn when something pins ONE effort level on every model.

        Plan 00466 N47: effort is settings.json's call, set per model under
        ``modelSettings`` -- the daemon holds no opinion on the level itself
        and never recommends one. What it can see is anything that silently
        overrides those per-model levels for every model at once: the
        ``CLAUDE_CODE_EFFORT_LEVEL`` environment variable, and a top-level
        ``effortLevel`` in the project's or the local settings file (both
        outrank the user file, and a top-level key there applies to every
        model). A top-level ``effortLevel`` in the USER file is not a pin: a
        per-model entry in the same file outranks it.

        A project settings file that cannot be read is reported too: not
        knowing whether it pins effort is not the same as knowing it does not.
        """
        pins: list[str] = []
        env_value = os.environ.get(_EFFORT_ENV_VAR, "")
        if env_value.strip().lower() not in _EFFORT_ENV_NON_PINNING_VALUES:
            pins.append(f"{_EFFORT_ENV_VAR}={env_value!r}")
        for name in _PROJECT_SETTINGS_FILES:
            relative = f".claude/{name}"
            path = project_root / ".claude" / name
            if not path.exists():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as e:
                logger.debug("Cannot read %s for the effort check: %s", path, e)
                pins.append(
                    f"{relative} is unreadable, so a top-level effortLevel cannot be ruled out"
                )
                continue
            if not isinstance(data, dict):
                pins.append(f"{relative} is not a JSON object, so it cannot be checked")
            elif "effortLevel" in data:
                pins.append(f"{relative} sets a top-level effortLevel={data['effortLevel']!r}")

        if not pins:
            return {
                "name": _EFFORT_CHECK_NAME,
                "passed": True,
                "current": "per-model levels come from settings.json modelSettings",
                "why": _EFFORT_CHECK_WHY,
                "fix": _EFFORT_CHECK_FIX,
                "where": _EFFORT_CHECK_WHERE,
                "docs": DOCS_URL,
            }
        return {
            "name": _EFFORT_CHECK_NAME,
            "passed": False,
            "warn": True,
            "current": "; ".join(pins),
            "why": _EFFORT_CHECK_WHY,
            "fix": _EFFORT_CHECK_FIX,
            "where": _EFFORT_CHECK_WHERE,
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

    def _untracked_memory_forbidden(self) -> bool:
        """True if markdown_organization.allow_untracked_claude_memory is false.

        Reads the daemon config (single source of truth for the policy) so this
        SessionStart advisory does not contradict the PreToolUse block. Fail-safe:
        any read/parse problem means 'policy not active', so default auto-memory
        advice still applies. Plan 00131.
        """
        try:
            from claude_code_hooks_daemon.config.models import Config
            from claude_code_hooks_daemon.core import ProjectContext
            from claude_code_hooks_daemon.handlers.pre_tool_use.markdown_organization import (
                ALLOW_UNTRACKED_CLAUDE_MEMORY_OPTION,
                DEFAULT_ALLOW_UNTRACKED_CLAUDE_MEMORY,
            )

            config = Config.load_or_default(ProjectContext.config_path())
            md_org = config.handlers.pre_tool_use.get("markdown_organization", {})
            if isinstance(md_org, dict):
                options = md_org.get("options", {})
            else:
                options = getattr(md_org, "options", {})
            # Fallback to the shipped default (SSoT) so an unset option is read
            # exactly as the handler treats it — no drift between block + advisory.
            return (
                options.get(
                    ALLOW_UNTRACKED_CLAUDE_MEMORY_OPTION, DEFAULT_ALLOW_UNTRACKED_CLAUDE_MEMORY
                )
                is False
            )
        except (RuntimeError, OSError, ValueError, AttributeError) as e:
            logger.debug("Could not determine untracked-memory policy: %s", e)
            return False

    def _check_auto_memory(self) -> dict[str, Any]:
        """Check auto-memory state, reconciled with the tracked-docs policy.

        When allow_untracked_claude_memory: false is active, the daemon BLOCKS
        memory writes — so this check must never nag to re-enable memory (it
        always passes and frames disabling as an optional best-effort step).
        """
        value = os.environ.get("CLAUDE_CODE_DISABLE_AUTO_MEMORY", "")
        disabled = value == "1"

        if self._untracked_memory_forbidden():
            state = (
                "DISABLED (CLAUDE_CODE_DISABLE_AUTO_MEMORY=1)" if disabled else "Enabled (default)"
            )
            return {
                "name": "Auto Memory",
                "passed": True,
                "current": (
                    f"{state} — untracked Claude memory is BLOCKED by the daemon "
                    "(allow_untracked_claude_memory: false)"
                ),
                "why": (
                    "This project forbids untracked Claude memory "
                    "(allow_untracked_claude_memory: false): the daemon blocks memory "
                    "writes and durable knowledge lives in tracked project docs. The "
                    "auto-memory env var no longer matters — the block is the enforcement."
                ),
                "fix": "Optional: disable auto-memory too — export CLAUDE_CODE_DISABLE_AUTO_MEMORY=1",
                "where": "~/.bashrc, ~/.zshrc, or settings.json env section",
                "docs": DOCS_URL,
            }

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

    def _run_checks(self, project_root: Path) -> list[dict[str, Any]]:
        """Run all configuration checks.

        Args:
            project_root: The checked project, whose own settings files can
                override the user's (read by the effort source check)

        Returns:
            List of check result dicts with name, passed, current, why, fix,
            where, docs -- plus ``warn: True`` on a failing check that is a
            warning about an override rather than a missing setting
        """
        return [
            self._check_agent_teams(),
            self._check_effort_source(project_root),
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
        return not is_resume_session(hook_input)

    def _enforce_settings_sync(self) -> list[str]:
        """Ensure critical settings exist in ~/.claude/settings.json.

        When alwaysThinkingEnabled is missing from settings, writes the
        optimal default so the statusline and config stay in sync.

        Effort is deliberately NOT written here (Plan 00466 N47): the ccy
        supervisor redesign removed the supervisor as a second, silent opinion
        fighting the owner's own settings.json — auto-writing `effortLevel`
        here would reintroduce exactly that problem through a different
        handler. The daemon holds no effort opinion at all; `cli check` only
        warns about a pin that overrides settings.json (`_check_effort_source`).

        Reads the file directly (not via _read_global_settings) to distinguish
        between "file missing/empty" (safe to create) and "read error" (abort
        to avoid clobbering existing settings).

        Returns:
            List of setting names that were written
        """
        try:
            settings_path = self._get_settings_path()
            if settings_path.exists():
                raw = settings_path.read_text()
                settings = json.loads(raw)
                if not isinstance(settings, dict):
                    logger.debug("Settings file is not a dict, skipping sync")
                    return []
            else:
                settings = {}
        except (OSError, json.JSONDecodeError, ValueError) as e:
            # Read failed — do NOT write to avoid clobbering existing settings
            logger.debug("Cannot read settings for sync, aborting: %s", e)
            return []

        written: list[str] = []

        if "alwaysThinkingEnabled" not in settings:
            settings["alwaysThinkingEnabled"] = True
            written.append("alwaysThinkingEnabled=true")

        if written:
            self._write_global_settings(settings)

        return written

    def handle(self, hook_input: dict[str, Any]) -> AdvisoryResult:
        """Run config checks and return advisory context.

        Also enforces that alwaysThinkingEnabled is explicitly set in
        ~/.claude/settings.json so the statusline stays in sync with actual
        configuration. Effort is never auto-written (Plan 00466 N47).

        Args:
            hook_input: SessionStart hook input

        Returns:
            AdvisoryResult with ALLOW decision and config check results
        """
        # Lean SessionStart (Plan 00128): do NOT emit the full config audit here.
        # It is verbose and rarely actionable on every session; the full
        # per-setting report now lives in the `cli check` command (which reuses
        # `_run_checks()` below). We still enforce critical settings silently and
        # announce ONLY an actual settings write — a real, one-time change the
        # user should know about.
        enforced = self._enforce_settings_sync()

        lines: list[str] = []
        if enforced:
            lines.append(f"CONFIG SYNC: Auto-set {', '.join(enforced)} in ~/.claude/settings.json")

        return AdvisoryResult(decision=Decision.ALLOW, context=lines)

    def get_claude_md(self) -> str | None:
        return None

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for this handler."""
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="optimal config checker - announces settings sync",
                command='echo "test"',
                description=(
                    "Tests that the handler silently enforces extended thinking on a "
                    "new session and announces an actual settings.json write via a "
                    "'CONFIG SYNC' line. Effort is never auto-written."
                ),
                expected_decision=Decision.ALLOW,
                # handle() only emits 'CONFIG SYNC: ...' and only on first run /
                # unset settings (when it actually writes settings.json).
                expected_message_patterns=[r"CONFIG SYNC"],
                safety_notes="Advisory handler - reports but does not block",
                test_type=TestType.CONTEXT,
                requires_event="SessionStart event (new session only)",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
