"""Skill-opportunity detector handler for SessionStart events (Plan 00274).

Advisory delegation (PLAN.md Decision 1): this handler ONLY checks the TTL
state file and, when a scan is due, injects an advisory telling the agent to
run ``bin/hooks-daemon skill-scan``. The pipeline (and its model call) lives
entirely in the CLI, outside every hook path. Ships disabled upstream — a
project enabling it is the explicit opt-in (Decision 2).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, HookInputField, Priority
from claude_code_hooks_daemon.core import AdvisoryResult, ProjectContext
from claude_code_hooks_daemon.core.handler_bases import SessionStartHandlerBase
from claude_code_hooks_daemon.core.hook_result import Decision
from claude_code_hooks_daemon.skill_scan.constants import STATE_FILE_NAME
from claude_code_hooks_daemon.skill_scan.models import SkillScanOptions
from claude_code_hooks_daemon.skill_scan.state import is_advisory_due, load_state
from claude_code_hooks_daemon.utils.session_helpers import is_resume_session

logger = logging.getLogger(__name__)

_SESSION_START_EVENT = "SessionStart"


class SkillOpportunityDetectorHandler(SessionStartHandlerBase):
    """TTL-gated advisory pointing at the ``skill-scan`` CLI.

    Does file-stat work only; advisory, non-terminal, and can never fail
    session start under any failure mode.
    """

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.SKILL_OPPORTUNITY_DETECTOR,
            priority=Priority.SKILL_OPPORTUNITY_DETECTOR,
            terminal=False,
            tags=[
                HandlerTag.WORKFLOW,
                HandlerTag.ADVISORY,
                HandlerTag.NON_TERMINAL,
            ],
        )
        self.config: dict[str, Any] = {"enabled": True}

    def configure(self, config: dict[str, Any]) -> None:
        """Apply configuration."""
        self.config.update(config)

    def _options(self) -> SkillScanOptions:
        raw = self.config.get("options")
        return SkillScanOptions.from_dict(raw if isinstance(raw, dict) else {})

    def _state_dir(self) -> Path:
        """The daemon untracked dir holding the TTL state (never /tmp, B108)."""
        return ProjectContext.daemon_untracked_dir()

    def matches(self, hook_input: dict[str, Any] | None) -> bool:
        """Run on new (non-resume) SessionStart events when enabled."""
        if not hook_input or not isinstance(hook_input, dict):
            return False
        if not self.config.get("enabled", True):
            return False
        if hook_input.get(HookInputField.HOOK_EVENT_NAME) != _SESSION_START_EVENT:
            return False
        return not is_resume_session(hook_input)

    def handle(self, hook_input: dict[str, Any]) -> AdvisoryResult:
        """Advise a scan when the TTL says one is due; silent otherwise."""
        try:
            options = self._options()
            state = load_state(self._state_dir() / STATE_FILE_NAME)
            if not is_advisory_due(state, options.check_interval_days):
                return AdvisoryResult(decision=Decision.ALLOW, reason=None, context=[])
            context = [
                "🔍 A skill-opportunity scan is due "
                f"(cadence: every {options.check_interval_days} days).",
                "Run: `bin/hooks-daemon skill-scan` — it mines recent session",
                "transcripts for repeated workloads and recurring confusion, and",
                "files a report of skill-creation suggestions under",
                "untracked/reports/ for HUMAN review. Report-only: never create a",
                "skill from it without human sign-off. `--dry-run` previews the",
                "exact redacted digest that would be sent to the model (the",
                "privacy audit view); `--force` bypasses the cadence gate. Every",
                "failure (no `claude` CLI, no auth, offline, timeout) is",
                "fail-open: the report notes the skip and the scan retries later —",
                "do not work around a failed model stage.",
            ]
            return AdvisoryResult(decision=Decision.ALLOW, reason=None, context=context)
        except Exception as exc:
            # Advisory handler: any failure must degrade to silence, never
            # block a session start.
            logger.error("skill_opportunity_detector failed: %s", exc, exc_info=True)
            return AdvisoryResult(decision=Decision.ALLOW, reason=None, context=[])

    def get_claude_md(self) -> str | None:
        """No resident guidance: the fire-time advisory carries the whole remedy.

        Same verdict as the other SessionStart advisories (T4 in
        ``tests/integration/test_claude_md_guidance_coverage.py``): the
        advisory fires once per cadence with the CLI invocation, the
        report-only contract, the privacy audit flag and the fail-open rule
        all in the message itself.
        """
        return None

    def get_acceptance_tests(self) -> list[Any]:
        """Acceptance tests for the release playbook."""
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="skill-scan dry run",
                command="bin/hooks-daemon skill-scan --dry-run",
                description=(
                    "CLI pipeline runs stages 1-2 and prints the redacted digest "
                    "without calling the model or writing a report"
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"DRY RUN", r"genuine="],
                safety_notes="Read-only over transcripts; no model call, no report",
                test_type=TestType.CONTEXT,
                requires_event="None (CLI invocation, not a hook event)",
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="skill-scan advisory on session start",
                command='echo "session start advisory"',
                description=(
                    "With the handler enabled and no recent scan recorded, a new "
                    "session's context includes the skill-scan-due advisory"
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"skill-scan"],
                safety_notes="Advisory only; never blocks session start",
                test_type=TestType.CONTEXT,
                requires_event="SessionStart event (new session, not resume)",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
