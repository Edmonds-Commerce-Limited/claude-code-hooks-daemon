"""HookRegistrationCheckerHandler - validate hook registrations on session start.

Checks that all expected hook event types are registered in .claude/settings.json
and detects duplicate registrations across settings.json and settings.local.json.

Runs only on new sessions (not resumes). Advisory only — never blocks.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.constants.protocol import HookInputField
from claude_code_hooks_daemon.core import Decision, Handler, HookResult
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.utils.hook_registration import (
    detect_duplicate_hooks,
    validate_hook_commands,
    validate_settings_hooks,
)

logger = logging.getLogger(__name__)

# Minimum transcript size (bytes) to consider a session as resumed
_RESUME_TRANSCRIPT_MIN_BYTES = 100

# Settings file names
_SETTINGS_FILE = "settings.json"
_SETTINGS_LOCAL_FILE = "settings.local.json"
_CLAUDE_DIR = ".claude"


class HookRegistrationCheckerHandler(Handler):
    """Validate hook registrations in Claude Code settings on session start.

    Checks:
    - All expected hook event types are registered in settings.json
    - No duplicate registrations across settings.json and settings.local.json
    - Hook commands point to the correct scripts

    Advisory only — reports issues as context, never blocks.
    """

    def __init__(self) -> None:
        """Initialise the hook registration checker handler."""
        super().__init__(
            handler_id=HandlerID.HOOK_REGISTRATION_CHECKER,
            priority=Priority.HOOK_REGISTRATION_CHECKER,
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
            hook_input: Hook input dictionary

        Returns:
            True if this appears to be a resumed session
        """
        transcript_path = hook_input.get(HookInputField.TRANSCRIPT_PATH)
        if not transcript_path:
            return False

        try:
            path = Path(transcript_path)
            if not path.exists():
                return False
            return path.stat().st_size > _RESUME_TRANSCRIPT_MIN_BYTES
        except (OSError, ValueError):
            return False

    def _get_project_root(self) -> Path | None:
        """Get the project root directory.

        Returns:
            Project root path or None if unavailable
        """
        try:
            return ProjectContext.project_root()
        except RuntimeError as exc:
            logger.debug("Cannot determine project root: %s", exc)
            return None

    def _read_json_file(self, path: Path) -> dict[str, Any]:
        """Read and parse a JSON file.

        Args:
            path: Path to JSON file

        Returns:
            Parsed dict or empty dict on any error
        """
        try:
            if not path.exists():
                return {}
            with path.open() as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
            return {}
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            logger.debug("Failed to read %s: %s", path, exc)
            return {}

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Only match on new sessions (not resumes).

        Args:
            hook_input: Hook input dictionary

        Returns:
            True for new sessions, False for resumed sessions
        """
        return not self._is_resume_session(hook_input)

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Validate hook registrations and report issues.

        Args:
            hook_input: Hook input dictionary

        Returns:
            HookResult with ALLOW decision and advisory context
        """
        project_root = self._get_project_root()
        if project_root is None:
            return HookResult(decision=Decision.ALLOW, context=[])

        claude_dir = project_root / _CLAUDE_DIR

        # Read settings files
        settings = self._read_json_file(claude_dir / _SETTINGS_FILE)
        local_settings = self._read_json_file(claude_dir / _SETTINGS_LOCAL_FILE)

        # Skip if no settings.json at all (not a hooks daemon project)
        if not settings:
            return HookResult(decision=Decision.ALLOW, context=[])

        # Run all validations
        all_issues: list[str] = []
        all_issues.extend(validate_settings_hooks(settings))
        all_issues.extend(detect_duplicate_hooks(settings, local_settings))
        all_issues.extend(validate_hook_commands(settings))

        # Build context
        lines: list[str] = []
        if not all_issues:
            lines.append("HOOK REGISTRATION: All checks passed")
        else:
            lines.append(f"HOOK REGISTRATION: {len(all_issues)} issue(s) found")
            lines.append("")
            for issue in all_issues:
                lines.append(f"  WARNING: {issue}")
            lines.append("")
            lines.append("Fix: Edit .claude/settings.json and/or .claude/settings.local.json")

        return HookResult(decision=Decision.ALLOW, context=lines)

    def get_claude_md(self) -> str | None:
        """No CLAUDE.md guidance needed for a startup check."""
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
                title="hook registration checker - validates hook settings",
                command='echo "test"',
                description="Validates hook registrations in settings.json on session start",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"HOOK REGISTRATION"],
                safety_notes="Advisory handler - warns but does not block",
                test_type=TestType.CONTEXT,
                requires_event="SessionStart event (new session only)",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
