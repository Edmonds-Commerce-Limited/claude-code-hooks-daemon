"""BranchRejectVerdictRecorderHandler - turn a reviewer's stop into a branch-reject verdict.

Plan 00620 Task 2.2. A thin shell over ``core.branch_reject.record_review_stop``: it
resolves the stopping reviewer's own transcript and ``meta.json``, takes the reply
strictly from the payload's ``last_assistant_message`` (the core compares it with the
transcript's last assistant text, so it must never be read from the transcript here),
and lets the core decide whether a verdict is recorded, withdrawn or ignored.

Only a literal ``stop_hook_active: false`` counts as a first stop; any other value, or
none, is treated as a re-entry, which withdraws the nonce's verdict and records nothing.

It never blocks a stop. Every failure records no verdict, which is the closed state:
no verdict chains, so no removal is unlocked. A disabled recorder fails closed for the
same reason.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.config.models import BranchesConfig
from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, HookInputField, Priority
from claude_code_hooks_daemon.core import BlockingResult, Decision, ProjectContext
from claude_code_hooks_daemon.core.branch_reject import (
    REVIEWER_AGENT_TYPE,
    RejectStore,
    ReviewStop,
    main_checkout,
    read_review_transcript,
    record_review_stop,
)
from claude_code_hooks_daemon.core.handler_bases import SubagentStopHandlerBase
from claude_code_hooks_daemon.daemon.synthetic_traffic import is_synthetic_event
from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue
from claude_code_hooks_daemon.utils.spend_ledger import read_agent_meta
from claude_code_hooks_daemon.utils.transcript_tail import resolve_agent_transcript

logger = logging.getLogger(__name__)

_REPLY_FIELD: Final[str] = "last_assistant_message"
_STOP_HOOK_ACTIVE_FIELD: Final[str] = "stop_hook_active"


def _text(mapping: dict[str, Any], key: str) -> str:
    value = mapping.get(key)
    return value if isinstance(value, str) else ""


class BranchRejectVerdictRecorderHandler(SubagentStopHandlerBase):
    """Record a branch-reject reviewer's verdict from its final, clean stop."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.BRANCH_REJECT_VERDICT_RECORDER,
            priority=Priority.BRANCH_REJECT_VERDICT_RECORDER,
            terminal=False,
            tags=[HandlerTag.WORKFLOW, HandlerTag.NON_TERMINAL],
        )
        # The registry injects the project's own ``branches`` config here.
        self._branches: BranchesConfig = BranchesConfig()

    @staticmethod
    def _project_root() -> Path:
        return ProjectContext.project_root()

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """A real stop of the reviewer agent type, re-entries included.

        Store-free and filesystem-free, so a damaged store never touches another
        agent's stop. A re-entry must match: it is what withdraws a verdict.
        """
        if is_synthetic_event(hook_input):
            return False
        return _text(hook_input, HookInputField.AGENT_TYPE) == REVIEWER_AGENT_TYPE

    def handle(self, hook_input: dict[str, Any]) -> BlockingResult:
        """Hand the stop to the recorder core; always allow."""
        session_id = _text(hook_input, HookInputField.SESSION_ID)
        agent_id = _text(hook_input, HookInputField.AGENT_ID)
        transcript = resolve_agent_transcript(
            _text(hook_input, HookInputField.AGENT_TRANSCRIPT_PATH), session_id, agent_id
        )
        if transcript is None:
            logger.info("branch-reject reviewer stop: transcript not found, nothing recorded")
            return BlockingResult(decision=Decision.ALLOW)
        try:
            meta = read_agent_meta(transcript)
            stop = ReviewStop(
                session_id=session_id,
                agent_id=agent_id,
                agent_type=_text(hook_input, HookInputField.AGENT_TYPE),
                meta_agent_type=meta.agent_type,
                meta_tool_use_id=meta.tool_use_id,
                stop_hook_active=hook_input.get(_STOP_HOOK_ACTIVE_FIELD) is not False,
                reply=_text(hook_input, _REPLY_FIELD),
            )
            facts = read_review_transcript(transcript)
            store = RejectStore(
                main_checkout(self._project_root()) / self._branches.reject.state_dir
            )
            outcome = record_review_stop(store, stop, facts, now=time.time())
            logger.info("branch-reject reviewer stop: %s", outcome)
        # A recorder must never block a stop: strict mode turns a crash into a deny,
        # and every later stop would crash the same way. Any failure records nothing.
        except (OSError, RuntimeError, ValueError, LookupError, AttributeError, TypeError) as exc:
            log_and_continue(
                logger,
                exc,
                reason="a stop the recorder could not judge records no verdict, which is the closed state; the stop itself is untouched",
                level=logging.WARNING,
            )
        return BlockingResult(decision=Decision.ALLOW)

    def get_claude_md(self) -> str | None:
        """Silent sensor: nothing an agent acts on."""
        return None

    def get_acceptance_tests(self) -> list[Any]:
        """One case: a reviewer's stop is recorded silently."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="branch-reject verdict recorder - records a reviewer stop silently",
                command="Let a dispatched branch-reject reviewer finish with its verdict block",
                description=(
                    "The stop is allowed with no message. The recording is asserted by "
                    "tests/unit/handlers/subagent_stop/test_branch_reject_verdict_recorder.py."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Writes one verdict and one stop marker under the branch-reject state dir.",
                test_type=TestType.CONTEXT,
                recommended_model=RecommendedModel.HAIKU,
                requires_event="SubagentStop event for the branch-reject reviewer",
            )
        ]
