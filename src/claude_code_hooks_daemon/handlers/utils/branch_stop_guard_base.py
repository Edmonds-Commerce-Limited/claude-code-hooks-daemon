"""Shared Stop/SubagentStop flow of the branch stop guards (Plan 00558 Task 4.4).

Lives beside the other handler helpers rather than in ``handlers/stop/`` because
handler discovery treats every module there as one concrete handler, and this
base is abstract. :class:`BranchStopGuardBase` judges the branches the stopping
identity touched with :func:`core.branch_stop_gate.decide_stop`; the concrete
``branch_stop_guard`` and ``branch_subagent_stop_guard`` name the event, scope
and agent handling.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.config.models import BranchesConfig
from claude_code_hooks_daemon.constants import HandlerTag, HookInputField
from claude_code_hooks_daemon.core import BlockingResult, Decision, ProjectContext
from claude_code_hooks_daemon.core.branch_stop_gate import StopDecision, decide_stop
from claude_code_hooks_daemon.core.handler_bases import StopHandlerBase
from claude_code_hooks_daemon.core.handler_scope import HandlerScope
from claude_code_hooks_daemon.core.rule import Rule
from claude_code_hooks_daemon.daemon.synthetic_traffic import is_synthetic_event
from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue
from claude_code_hooks_daemon.utils.usage_pause_gate import hook_is_usage_paused

logger = logging.getLogger(__name__)


def stop_guard_rule(rule_id: str, who: str) -> Rule:
    """The rule a stop guard files its deny under; ``who`` names the stopping identity."""
    return Rule(
        rule_id=rule_id,
        blocked="a stop that leaves a dirty worktree, unpushed commits or a merged branch behind",
        why="Work left on a branch nobody returns to is lost work; the guard makes the stopping "
        f"{who} finish, park or hand over each branch it touched",
        fix="Run the commands the message lists for each branch, then stop again",
        verbose=(
            "WHY BLOCKED:\n"
            f"  This {who} touched the branches below and is stopping with work on them\n"
            "  uncommitted, unpushed, or merged but not deleted.\n\n"
            "DO INSTEAD:\n"
            "  Run the listed commands per branch. After three blocked stops the guard\n"
            "  gives way and records the branches as abandoned."
        ),
    )


class BranchStopGuardBase(StopHandlerBase):
    """Shared Stop/SubagentStop flow; subclasses name the event, scope and agent handling."""

    def __init__(self, *, handler_id: Any, priority: int, scope: HandlerScope, rule: Rule) -> None:
        self._rule = rule
        super().__init__(
            handler_id=handler_id,
            priority=priority,
            terminal=False,
            scope=scope,
            shares_options_with=None,
            tags=[
                HandlerTag.WORKFLOW,
                HandlerTag.GIT,
                HandlerTag.BLOCKING,
                HandlerTag.NON_TERMINAL,
            ],
        )
        # Injected by the registry from the ``branches:`` block.
        self._branches: BranchesConfig = BranchesConfig()
        self._project_root_override: Path | None = None
        self._untracked_override: Path | None = None

    def _project_root(self) -> Path:
        return self._project_root_override or ProjectContext.project_root()

    def _untracked_dir(self) -> Path:
        return self._untracked_override or ProjectContext.daemon_untracked_dir()

    def get_rules(self) -> list[Rule]:
        """The rule behind the blocked stop."""
        return [self._rule]

    def get_claude_md(self) -> str | None:
        """Guidance for the stop guard; the SubagentStop twin shares it."""
        return None

    def _agent_id(self, hook_input: dict[str, Any]) -> str | None:
        raise NotImplementedError

    def _handoff(self, hook_input: dict[str, Any]) -> bool:
        return False

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """A real stop that names its session."""
        return not is_synthetic_event(hook_input) and bool(
            hook_input.get(HookInputField.SESSION_ID)
        )

    def handle(self, hook_input: dict[str, Any]) -> BlockingResult:
        """Deny a stop that leaves branch work behind; any failure to judge allows the stop."""
        allow = BlockingResult(decision=Decision.ALLOW)
        if hook_is_usage_paused(hook_input):
            return allow
        try:
            decision: StopDecision = decide_stop(
                self._project_root(),
                self._branches,
                self._untracked_dir(),
                session_id=str(hook_input.get(HookInputField.SESSION_ID) or ""),
                agent_id=self._agent_id(hook_input),
                handoff=self._handoff(hook_input),
                now=time.time(),
            )
        except Exception as exc:
            log_and_continue(
                logger,
                exc,
                reason="a branch stop-guard failure allows the stop; a hygiene check never "
                "holds a session on its own malfunction",
            )
            return allow
        if decision.reason is not None:
            return BlockingResult.deny(decision.reason, context=list(decision.context)).under_rule(
                self._rule
            )
        return BlockingResult(decision=Decision.ALLOW, context=list(decision.context))
