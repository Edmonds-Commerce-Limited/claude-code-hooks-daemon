"""BranchSubagentStopGuardHandler - a sub-agent's stop must not leave its branches behind (Plan 00558 Task 4.4).

The SubagentStop twin of ``branch_stop_guard``, sharing its flow. Judges the
branches this sub-agent touched. An agent that hit the hard context budget is on
the handoff path: the merged-but-not-deleted check is waived and the deny
appends each branch with its tip sha for the handoff note. Priority 12, after
``subagent_handoff_gate`` (11), non-terminal.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HookInputField, Priority
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import AcceptanceTest, Decision, RecommendedModel, TestType
from claude_code_hooks_daemon.core.handler_scope import HandlerScope
from claude_code_hooks_daemon.handlers.pre_tool_use.subagent_context_budget import (
    STATE_HARD_ENGAGED,
    STATE_KIND,
)
from claude_code_hooks_daemon.handlers.utils.branch_stop_guard_base import (
    BranchStopGuardBase,
    stop_guard_rule,
)
from claude_code_hooks_daemon.utils.spend_ledger import read_state, state_path


class BranchSubagentStopGuardHandler(BranchStopGuardBase):
    """SubagentStop: judge the branches this sub-agent touched."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.BRANCH_SUBAGENT_STOP_GUARD,
            priority=Priority.BRANCH_SUBAGENT_STOP_GUARD,
            scope=HandlerScope.SUB,
            rule=stop_guard_rule(RuleID.BRANCH_SUBAGENT_STOP_GUARD, "sub-agent"),
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """A real subagent stop that names its agent."""
        return super().matches(hook_input) and bool(hook_input.get(HookInputField.AGENT_ID))

    def _agent_id(self, hook_input: dict[str, Any]) -> str | None:
        return str(hook_input.get(HookInputField.AGENT_ID) or "") or None

    def _handoff(self, hook_input: dict[str, Any]) -> bool:
        untracked: Path = self._untracked_dir()
        state = read_state(
            state_path(
                untracked,
                str(hook_input.get(HookInputField.SESSION_ID) or ""),
                STATE_KIND,
                str(hook_input.get(HookInputField.AGENT_ID) or ""),
            )
        )
        return state.get(STATE_HARD_ENGAGED) is True

    def get_claude_md(self) -> str | None:
        """Covered by ``branch_stop_guard``'s section."""
        return None

    def get_acceptance_tests(self) -> list[Any]:
        """Declared harness-undrivable: it needs a real sub-agent's touch records."""
        return [
            AcceptanceTest(
                title="branch subagent stop guard - a sub-agent leaving its branch unpushed is held",
                command="Stop a subagent that committed on a branch no remote holds",
                description=(
                    "The stop is denied naming the branch and the git push command, at most "
                    "three times, unless branches.stop_guard.unpushed_subagent is advise. "
                    "Unit tests in tests/unit/handlers/subagent_stop/"
                    "test_branch_subagent_stop_guard.py cover the matrix."
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"BRANCHES LEFT BEHIND"],
                safety_notes="Gives way after three blocks, so no agent is stranded.",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                harness_cannot_produce=(
                    "It needs a real sub-agent whose branch touches are recorded in git "
                    "config; the harness fabricates neither."
                ),
            ),
            AcceptanceTest(
                title="branch subagent stop guard - a sub-agent stop with its branches pushed is allowed",
                command="Stop a subagent whose touched branches are clean, pushed and unmerged",
                description=(
                    "Nothing is left behind, so the stop proceeds with no block. Only the "
                    "unpushed commit differs from the deny case."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="The near miss of the deny case.",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                harness_cannot_produce=(
                    "It needs a real sub-agent whose branch touches are recorded in git "
                    "config; the harness fabricates neither."
                ),
            ),
        ]
