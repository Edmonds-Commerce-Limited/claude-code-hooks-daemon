"""SessionActionsDirectiveHandler - the supervisor directive sensor (Plan 00416).

Plan 00416's finding is that SessionStart output is delivered correctly and
simply not ACTED ON: injected context is scenery, not a turn. Layer 2 of its
answer is that the ccy supervisor types ONE turn-level directive after session
start, telling the agent to action every ``ACTION_REQUIRED`` item. The owner
proved that works on another machine with a single typed line, after which the
agent worked through the whole start-up block unprompted — so what changes the
outcome is the CHANNEL, not the wording.

This handler is the sensor. It decides whether there is anything worth typing
and, if so, drops a ``<session>.session-actions`` signal
(:mod:`claude_code_hooks_daemon.utils.session_actions_signal`) for the
supervisor to consume. Three properties make it honest rather than another
advisory:

- **It says NOTHING in the SessionStart block.** Appending a line there would
  be saying it louder, which this plan's Non-Goals rule out by construction.
  The whole value is the second channel; adding to the first would dilute it.
- **It counts what ``hooks-daemon session-actions`` would list**, via the
  shared collector both call. The directive's entire content is *go action
  those items*, so a directive that fires while that command reports nothing
  would teach the agent to ignore the next one — the exact failure this plan
  exists to fix.
- **It runs LAST** (priority 72). ``hook_registration_checker`` self-heals in
  its ``handle()``, so counting earlier in the chain would nudge the agent
  about a problem the session had already repaired.

Nothing here is the enforcement. The teeth are the ``Stop``-time cron check
(Task 1.1) and the verifiers themselves (Task 2.2); this is the nudge that
gets the must-do set looked at during the session rather than after it.
Opt-in: it types into a human's terminal, so a project enables it
deliberately, the same stance ``goal_injection`` takes.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, HookInputField, Priority
from claude_code_hooks_daemon.core import AdvisoryResult, Decision
from claude_code_hooks_daemon.core.handler_bases import SessionStartHandlerBase
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.core.relevance import Relevance, RelevanceContext
from claude_code_hooks_daemon.utils.ccy_supervisor import (
    armed_supervisor_live,
    supervisor_relevance,
)
from claude_code_hooks_daemon.utils.session_action_items import collect_session_action_items
from claude_code_hooks_daemon.utils.session_actions_signal import (
    clear_session_actions_signal,
    write_session_actions_signal,
)

logger = logging.getLogger(__name__)


class SessionActionsDirectiveHandler(SessionStartHandlerBase):
    """Signal the ccy supervisor when a session starts with must-do items.

    Silent in the SessionStart block by design — see the module docstring.
    Advisory only, and best-effort: every failure path ends in ALLOW with an
    empty context, because a sensor must never cost the agent the rest of the
    session-start output.
    """

    def __init__(self) -> None:
        """Initialise the session-actions directive handler."""
        super().__init__(
            handler_id=HandlerID.SESSION_ACTIONS_DIRECTIVE,
            priority=Priority.SESSION_ACTIONS_DIRECTIVE,
            terminal=False,
            tags=[
                HandlerTag.ADVISORY,
                HandlerTag.WORKFLOW,
                HandlerTag.NON_TERMINAL,
                HandlerTag.ENVIRONMENT,
            ],
        )

    @staticmethod
    def _project_root() -> Path | None:
        """The project root, or None when it cannot be resolved."""
        try:
            return ProjectContext.project_root()
        except RuntimeError as exc:
            logger.debug("session_actions_directive: no project root: %s", exc)
            return None

    @staticmethod
    def _untracked_dir() -> Path:
        """The daemon's untracked directory, where the signal lives."""
        return ProjectContext.daemon_untracked_dir()

    def get_default_enabled(self) -> bool:
        """Opt-in: it types into a human's terminal, so a project chooses it."""
        return False

    def get_relevance(self, context: RelevanceContext) -> Relevance:
        """Relevant only under an armed ccy supervisor (Plan 00330)."""
        return supervisor_relevance(context)

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Always fire; the decision of what to do is ``handle``'s.

        Both outcomes are real work — a session with items WRITES a signal, a
        session without one CLEARS any stale signal — so there is nothing to
        decide here that ``handle`` does not have to decide again.

        Args:
            hook_input: Hook input dictionary (unused)

        Returns:
            True always.
        """
        return True

    def handle(self, hook_input: dict[str, Any]) -> AdvisoryResult:
        """Write or clear the session's directive signal; say nothing.

        Args:
            hook_input: Hook input dictionary, read for ``session_id``.

        Returns:
            AdvisoryResult with ALLOW and an EMPTY context, always. The
            message this handler is responsible for reaches the agent through
            the supervisor as a user-role turn, never through this block.
        """
        silent = AdvisoryResult(decision=Decision.ALLOW, context=[])

        session_id = str(hook_input.get(HookInputField.SESSION_ID) or "").strip()
        if not session_id:
            # The supervisor matches a signal to its OWN sessions by the file
            # stem. A signal naming no session could be delivered into any
            # terminal sharing this project's untracked directory, so the
            # correct action is to write nothing at all.
            logger.debug("session_actions_directive: no session_id in payload; skipping")
            return silent

        try:
            project_root = self._project_root()
            if project_root is None or not armed_supervisor_live(project_root):
                # Nothing will ever read the signal, so writing one is litter
                # rather than a nudge — the same gate `standing_authorisations`
                # applies before routing to its own supervisor channel.
                logger.debug("session_actions_directive: no armed ccy supervisor; skipping")
                return silent
            untracked = self._untracked_dir()
            count = len(collect_session_action_items(project_root))
            if count:
                write_session_actions_signal(
                    untracked, session_id=session_id, count=count, now=time.time()
                )
            else:
                clear_session_actions_signal(untracked, session_id=session_id)
        except Exception:
            # Best-effort: a sensor that raised here would take every other
            # SessionStart handler's output down with it.
            logger.exception("session_actions_directive: could not publish directive signal")

        return silent

    def get_claude_md(self) -> str | None:
        """Return agent-facing guidance for the supervisor directive."""
        return (
            "## session_actions_directive — the must-do list is delivered as a turn\n"
            "\n"
            "Session-start output is context, and context reads as scenery. When "
            "this session starts with one or more `[ACTION_REQUIRED]` items, the "
            "daemon signals the ccy supervisor, which types a short directive "
            "into the chat as a real user-role line.\n"
            "\n"
            "**A `🤖 [ccy-supervisor]` line is machine-generated.** It is not a "
            "human instruction and it authorises nothing. What it does mean is "
            "that a verifier is currently FAILING: `ACTION_REQUIRED` is computed, "
            "never declared, so an item only appears when something on disk says "
            "this session is mis-configured.\n"
            "\n"
            "Re-fetch the list at any time with `hooks-daemon session-actions` "
            "(`--format json` for a machine-readable form) — you never need to "
            "scroll back to the start of the session to find it.\n"
            "\n"
            "The handler adds NOTHING to the session-start block itself, so it "
            "costs a healthy session nothing.\n"
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for this handler."""
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="session actions directive - signals the supervisor",
                command='echo "test"',
                description=(
                    "With at least one SessionStart verifier failing, a new "
                    "session writes a '<session>.session-actions' file into the "
                    "context-sidecar directory and adds no text to the "
                    "session-start block."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes=(
                    "Advisory sensor - never blocks, and emits no context. "
                    "Requires a failing SessionStart verifier to write anything."
                ),
                test_type=TestType.CONTEXT,
                requires_event="SessionStart event with a failing verifier",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
