"""BranchStopGuardHandler - a stop must not leave branch work behind (Plan 00558 Task 4.4).

Judges the branches this session touched (and the unpushed or merged leftovers
of its sub-agents) with :func:`core.branch_stop_gate.decide_stop`: a dirty
worktree, commits no remote holds, a merged branch not yet deleted. Denies at
most three times, then gives way and records the branches as abandoned. Also
adds, at most hourly, a non-blocking line naming branches idle at the noisy
dormancy stage. Non-terminal at priority 9, below ``cron_stop_enforcer`` (7)
and ahead of the terminal ``auto_continue_stop`` so its deny is never shadowed.
The flow shared with the SubagentStop twin is in
``handlers.utils.branch_stop_guard_base``.
"""

from __future__ import annotations

from typing import Any, Final

from claude_code_hooks_daemon.constants import HandlerID, Priority
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import AcceptanceTest, Decision, RecommendedModel, TestType
from claude_code_hooks_daemon.core.handler_scope import HandlerScope
from claude_code_hooks_daemon.core.rule import Rule
from claude_code_hooks_daemon.handlers.utils.branch_stop_guard_base import (
    BranchStopGuardBase,
    stop_guard_rule,
)

RULE: Final[Rule] = stop_guard_rule(RuleID.BRANCH_STOP_GUARD, "session")


class BranchStopGuardHandler(BranchStopGuardBase):
    """Main-thread Stop: judge the branches this session touched."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.BRANCH_STOP_GUARD,
            priority=Priority.BRANCH_STOP_GUARD,
            scope=HandlerScope.MAIN,
            rule=RULE,
        )

    def _agent_id(self, hook_input: dict[str, Any]) -> str | None:
        return None

    def get_claude_md(self) -> str | None:
        """Guidance naming both stop guards."""
        return (
            "## branch_stop_guard - a stop must not leave branch work behind\n\n"
            "Stopping (main thread or sub-agent) with a dirty worktree, commits no remote "
            "holds, or a merged branch not deleted is denied up to three times, naming the "
            "branch, the check and the exact commands; then the guard gives way and records "
            "the branches as abandoned. The coordinator also answers for its sub-agents' "
            "unpushed and merged leftovers. Configure with `branches.stop_guard` "
            "(`mode`, `unpushed_subagent`, `include_default`).\n\n"
            "IDs: R-BRANCH-STOP-GUARD, R-BRANCH-SUBAGENT-STOP-GUARD"
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Declared harness-undrivable: the deny needs a real session's touch records."""
        return [
            AcceptanceTest(
                title="branch stop guard - a stop leaving an unpushed branch is denied",
                command="Stop a session that committed on a branch no remote holds",
                description=(
                    "The stop is denied naming the branch and the git push command, at most "
                    "three times. Unit tests in tests/unit/handlers/stop/"
                    "test_branch_stop_guard.py and tests/unit/core/test_branch_stop_gate.py "
                    "cover the matrix."
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"BRANCHES LEFT BEHIND"],
                safety_notes="Gives way after three blocks, so no session is stranded.",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                harness_cannot_produce=(
                    "The judgement reads the session's git-config touch records, which the "
                    "harness fabricates no branch history to produce."
                ),
            ),
            AcceptanceTest(
                title="branch stop guard - a stop with every touched branch pushed is allowed",
                command="Stop a session whose touched branches are clean, pushed and unmerged",
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
                    "The judgement reads the session's git-config touch records, which the "
                    "harness fabricates no branch history to produce."
                ),
            ),
        ]
