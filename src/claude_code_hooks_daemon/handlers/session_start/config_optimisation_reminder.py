"""Config-optimisation reminder handler for SessionStart events (Plan 00308).

Surfaces a skipped post-upgrade configuration review. ``/optimise`` (the
formalised config-optimisation step, see ``.claude/skills/optimise``) is
supposed to run after every upgrade, but nothing enforced that until now: an
agent could upgrade, skip the review, and the gap would simply be lost. This
handler ONLY compares the installed daemon version against the version
recorded the last time ``/optimise`` ran (state written by that skill via
``bin/hooks-daemon record-config-optimisation-run``) and reminds the agent to
run it again when they differ, or when no run was ever recorded. Advisory
only — it never blocks, and does the analysis itself.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.config_optimisation.state import STATE_FILE_NAME, load_state
from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, HookInputField, Priority
from claude_code_hooks_daemon.core import AdvisoryResult, ProjectContext
from claude_code_hooks_daemon.core.handler_bases import SessionStartHandlerBase
from claude_code_hooks_daemon.core.hook_result import Decision
from claude_code_hooks_daemon.utils.session_helpers import is_resume_session
from claude_code_hooks_daemon.version import __version__

logger = logging.getLogger(__name__)

_SESSION_START_EVENT = "SessionStart"


class ConfigOptimisationReminderHandler(SessionStartHandlerBase):
    """Remind the agent when the config-optimisation review is stale.

    Does file-stat work only; advisory, non-terminal, and can never fail
    session start under any failure mode.
    """

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.CONFIG_OPTIMISATION_REMINDER,
            priority=Priority.CONFIG_OPTIMISATION_REMINDER,
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

    def _state_dir(self) -> Path:
        """The daemon untracked dir holding the last-run state (never /tmp, B108)."""
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
        """Advise re-running the review when the recorded run is stale."""
        try:
            state = load_state(self._state_dir() / STATE_FILE_NAME)
            current = __version__
            if state.last_run_version == current:
                return AdvisoryResult(decision=Decision.ALLOW, reason=None, context=[])

            if state.last_run_version is None:
                context = [
                    "🛠️ No config-optimisation review (`/optimise`) has ever been "
                    "recorded for this project.",
                ]
            else:
                context = [
                    "🛠️ The hooks daemon was upgraded since the last "
                    "config-optimisation review "
                    f"(reviewed at v{state.last_run_version}, now v{current}).",
                ]
            context.extend(
                [
                    "Run `/optimise` in this session — it inventories "
                    "disabled-but-relevant handlers and gives a prioritised "
                    "enable/skip recommendation list, and never applies changes "
                    "without explicit confirmation.",
                    "This is the mandatory post-upgrade review, deferred: it is "
                    "not an optional to-do. If the user asked for other work "
                    "first, do that, then run the review before you stop.",
                    "Only if `/optimise` is genuinely unavailable in this "
                    "project, silence this reminder with `bin/hooks-daemon "
                    "record-config-optimisation-run` — that records a review "
                    "that did not happen.",
                ]
            )
            return AdvisoryResult(decision=Decision.ALLOW, reason=None, context=context)
        except Exception as exc:
            # Advisory handler: any failure must degrade to silence, never
            # block a session start.
            logger.error("config_optimisation_reminder failed: %s", exc, exc_info=True)
            return AdvisoryResult(decision=Decision.ALLOW, reason=None, context=[])

    def get_claude_md(self) -> str | None:
        """No resident guidance: the fire-time advisory carries the whole remedy."""
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
                title="config-optimisation reminder on session start",
                command='echo "session start reminder"',
                description=(
                    "With the handler enabled and no config-optimisation run "
                    "recorded (or recorded against a stale version), a new "
                    "session's context includes a reminder to run /optimise"
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"optimise"],
                safety_notes="Advisory only; never blocks session start",
                test_type=TestType.CONTEXT,
                requires_event="SessionStart event (new session, not resume)",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
