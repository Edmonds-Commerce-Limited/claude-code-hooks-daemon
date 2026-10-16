"""ReviewRoundAdvisorHandler - count review rounds per plan or branch (Plan 00471 L9).

Review agents were 23.2 % of measured subagent spend, and one plan dispatched 12
of them. Whether successive rounds are converging is a judgement no daemon can
make, but the COUNT is deterministic: on an ``Agent``/``Task`` dispatch whose
description or prompt says "review" and names a plan (``Plan 00463``) or a work
branch (``worktree-...``), the round for that key is counted, and from round
``advise_at`` (4) the coordinator is told to compare this round's findings with
the last and consider taking it to the owner.

Advisory only. The counter advances only when the dispatch actually went ahead
(``commit_side_effects``), so a dispatch another handler denied is not a round.
Shipped off for clients; on in this repository.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.constants import (
    SUBAGENT_DISPATCH_TOOL_NAMES,
    HandlerID,
    HandlerTag,
    HookInputField,
    Priority,
)
from claude_code_hooks_daemon.core import Decision, GatingResult, ProjectContext
from claude_code_hooks_daemon.core.chain import is_restrictive
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.handlers.pre_tool_use.subagent_context_budget import int_or_none
from claude_code_hooks_daemon.utils.spend_ledger import (
    append_event,
    read_state,
    state_path,
    write_state,
)

DEFAULT_ADVISE_AT: Final[int] = 4

_REVIEW: Final[re.Pattern[str]] = re.compile(r"(?i)\breview")
_PLAN: Final[re.Pattern[str]] = re.compile(r"(?i)\bplan\s*0*([1-9][0-9]{2,4})\b")
_BRANCH: Final[re.Pattern[str]] = re.compile(r"\b(worktree-[A-Za-z0-9._-]+)")
_STATE_KIND: Final[str] = "review-rounds"
_STATE_ROUNDS: Final[str] = "rounds"


def review_key(description: str, prompt: str) -> str | None:
    """``plan-<n>`` or ``branch-<name>`` for a review dispatch, else None."""
    text = f"{description}\n{prompt}"
    if not _REVIEW.search(text):
        return None
    plan = _PLAN.search(text)
    if plan is not None:
        return f"plan-{plan.group(1)}"
    branch = _BRANCH.search(text)
    return f"branch-{branch.group(1)}" if branch is not None else None


class ReviewRoundAdvisorHandler(PreToolUseHandlerBase):
    """Advise from the ``advise_at``-th review dispatch on one plan or branch."""

    default_enabled = False

    _advise_at: int | None = DEFAULT_ADVISE_AT

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.REVIEW_ROUND_ADVISOR,
            priority=Priority.REVIEW_ROUND_ADVISOR,
            terminal=False,
            tags=[HandlerTag.WORKFLOW, HandlerTag.ADVISORY, HandlerTag.NON_TERMINAL],
        )
        self._untracked_override: Path | None = None

    def get_default_enabled(self) -> bool:
        """Off for clients: a heuristic count is this repository's dogfood first."""
        return False

    def _untracked_dir(self) -> Path:
        return self._untracked_override or ProjectContext.daemon_untracked_dir()

    @staticmethod
    def _key(hook_input: dict[str, Any]) -> str | None:
        if hook_input.get(HookInputField.TOOL_NAME) not in SUBAGENT_DISPATCH_TOOL_NAMES:
            return None
        tool_input = hook_input.get(HookInputField.TOOL_INPUT)
        if not isinstance(tool_input, dict):
            return None
        description = tool_input.get("description")
        prompt = tool_input.get("prompt")
        return review_key(
            description if isinstance(description, str) else "",
            prompt if isinstance(prompt, str) else "",
        )

    def _state_file(self, hook_input: dict[str, Any], key: str) -> Path:
        session = str(hook_input.get(HookInputField.SESSION_ID) or "")
        return state_path(self._untracked_dir(), session, _STATE_KIND, key)

    def _rounds_so_far(self, hook_input: dict[str, Any], key: str) -> int:
        rounds = read_state(self._state_file(hook_input, key)).get(_STATE_ROUNDS)
        return rounds if isinstance(rounds, int) and not isinstance(rounds, bool) else 0

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """A review dispatch that names a plan or a work branch."""
        return self._key(hook_input) is not None

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        """Advise from round ``advise_at``; the count itself moves in commit_side_effects."""
        key = self._key(hook_input)
        if key is None:
            return GatingResult(decision=Decision.ALLOW)
        this_round = self._rounds_so_far(hook_input, key) + 1
        advise_at = int_or_none(self._advise_at) or DEFAULT_ADVISE_AT
        if this_round < advise_at:
            return GatingResult(decision=Decision.ALLOW)
        append_event(
            self._untracked_dir(),
            str(hook_input.get(HookInputField.SESSION_ID) or ""),
            {"kind": "review-round-advisory", "key": key, "round": this_round},
        )
        return GatingResult(
            decision=Decision.ALLOW,
            context=[
                f"REVIEW ROUNDS: this is review round {this_round} on {key} (advise at "
                f"{advise_at}). Compare this round's findings count with the last one: if they "
                "are not shrinking, another round is unlikely to converge, and the open "
                "findings may be an owner decision rather than more review."
            ],
        )

    def commit_side_effects(self, hook_input: dict[str, Any], chain_decision: Decision) -> None:
        """Count the round only when the dispatch went ahead."""
        if is_restrictive(chain_decision):
            return
        key = self._key(hook_input)
        if key is None:
            return
        state_file = self._state_file(hook_input, key)
        write_state(state_file, {_STATE_ROUNDS: self._rounds_so_far(hook_input, key) + 1})

    def get_claude_md(self) -> str | None:
        """Advisory delivered with the dispatch; no standing rule to hold."""
        return None

    def get_acceptance_tests(self) -> list[Any]:
        """One probe: a review dispatch is allowed (the count is unit-tested)."""
        from claude_code_hooks_daemon.constants.tools import ToolName
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            RecommendedModel,
            TestType,
            ToolPayload,
        )

        probe = ToolPayload(
            tool_name=ToolName.AGENT,
            tool_input={"description": "Review plan 00471", "prompt": "review it"},
        )
        return [
            AcceptanceTest(
                title="review round advisor - a review dispatch is allowed",
                command=probe.as_instruction(),
                description=(
                    "The dispatch is allowed; from round 4 on one plan it carries advice. "
                    "The count is asserted by "
                    "tests/unit/handlers/pre_tool_use/test_review_round_advisor.py."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Advisory only; writes one small counter file.",
                test_type=TestType.CONTEXT,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=True,
                tool_payload=probe,
            )
        ]
