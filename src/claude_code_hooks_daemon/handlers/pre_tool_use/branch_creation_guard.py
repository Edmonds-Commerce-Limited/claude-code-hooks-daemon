"""Deny creating a branch while the open work branches are at the cap (Plan 00558 Task 4.2).

Two routes create a branch from a tool call: a git command (``switch -c``,
``checkout -b``, ``branch <n>``, ``worktree add``) and an Agent dispatch with
``isolation: "worktree"``. Both are judged by the one
:func:`~claude_code_hooks_daemon.core.branch_creation.creation_verdict`, which
reads the repository the git run acts on (``cd`` and ``-C`` followed). The
WorktreeCreate event, the third route, calls the same verdict from its own
handler.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.config.models import BranchesConfig
from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, HookInputField, Priority
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.constants.tools import SUBAGENT_DISPATCH_TOOL_NAMES
from claude_code_hooks_daemon.core import GatingResult
from claude_code_hooks_daemon.core.branch_creation import (
    LABELS_RELATIVE_PATH,
    CreationVerdict,
    creation_verdict,
    read_labels,
)
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.core.hook_result import Decision
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.core.rule import Rule, RuleFormatter
from claude_code_hooks_daemon.core.utils import get_bash_command
from claude_code_hooks_daemon.utils.git_branch_creation import created_branches
from claude_code_hooks_daemon.utils.git_invocation_directory import (
    invocation_directory,
    placement_problem,
)

logger = logging.getLogger(__name__)

_ISOLATION_KEY = "isolation"
_ISOLATION_WORKTREE = "worktree"
_NAME_KEY = "name"
_SEVERITY = {"allow": 0, "warn": 1, "deny": 2}


class BranchCreationGuardHandler(PreToolUseHandlerBase):
    """Hold the open work branches at ``branches.wip.cap``; warn on likely duplicates."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.BRANCH_CREATION_GUARD,
            priority=Priority.BRANCH_CREATION_GUARD,
            tags=[HandlerTag.WORKFLOW, HandlerTag.GIT, HandlerTag.BLOCKING, HandlerTag.TERMINAL],
        )
        self._branches: BranchesConfig = BranchesConfig()
        self._project_root_override: Path | None = None
        self._rule = Rule(
            rule_id=RuleID.BRANCH_WIP_CAP,
            blocked="creating a branch while the open work branches are at `branches.wip.cap`",
            why="Work that is started and never finished piles up as branches nobody "
            "returns to; the cap makes an agent finish before it starts",
            fix="Merge, park or delete one of the listed branches, or continue in one of them",
            verbose=(
                "WHY:\n"
                "  Every open branch is work someone must finish, park or delete.\n"
                "  The list below puts the cheapest to close first: merged and\n"
                "  patch-equivalent branches carry their delete command."
            ),
        )
        self._formatter = RuleFormatter()

    def get_rules(self) -> list[Rule]:
        """Return the single Rule backing this handler's deny path."""
        return [self._rule]

    def _project_root(self) -> Path:
        if self._project_root_override is not None:
            return self._project_root_override
        try:
            return ProjectContext.project_root()
        except RuntimeError:
            logger.debug("ProjectContext not initialised; no labels snapshot for the guard")
            return Path.cwd()

    @staticmethod
    def _is_isolated_dispatch(hook_input: dict[str, Any]) -> bool:
        if hook_input.get(HookInputField.TOOL_NAME) not in SUBAGENT_DISPATCH_TOOL_NAMES:
            return False
        tool_input = hook_input.get(HookInputField.TOOL_INPUT)
        return isinstance(tool_input, dict) and (
            tool_input.get(_ISOLATION_KEY) == _ISOLATION_WORKTREE
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """A git command that creates a branch, or an isolated Agent dispatch."""
        if self._is_isolated_dispatch(hook_input):
            return True
        command = get_bash_command(hook_input)
        return bool(command) and bool(created_branches(command))

    def _verdicts(self, hook_input: dict[str, Any]) -> list[CreationVerdict]:
        cwd = Path(str(hook_input.get(HookInputField.CWD) or self._project_root()))
        labels = read_labels(self._project_root() / LABELS_RELATIVE_PATH)
        if self._is_isolated_dispatch(hook_input):
            tool_input = hook_input.get(HookInputField.TOOL_INPUT) or {}
            name = tool_input.get(_NAME_KEY)
            return [
                creation_verdict(
                    cwd,
                    self._branches,
                    name if isinstance(name, str) and name else None,
                    labels=labels,
                    name_is_branch=False,
                )
            ]
        verdicts: list[CreationVerdict] = []
        for creation in created_branches(get_bash_command(hook_input) or ""):
            run = creation.invocation
            directory = cwd if placement_problem(run, cwd) else invocation_directory(run, cwd)
            verdicts.append(
                creation_verdict(directory, self._branches, creation.name, labels=labels)
            )
        return verdicts

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        """Deny at the cap in block mode; otherwise allow with any warning lines."""
        verdicts = self._verdicts(hook_input)
        lines = [line for verdict in verdicts for line in verdict.lines]
        worst = max((verdict.decision for verdict in verdicts), key=_SEVERITY.__getitem__)
        if worst == "deny":
            reason = "\n".join([self._formatter.headline(self._rule), "", *lines])
            return GatingResult(decision=Decision.DENY, reason=reason)
        return GatingResult(decision=Decision.ALLOW, context=list(dict.fromkeys(lines)))

    def get_claude_md(self) -> str | None:
        return (
            "## branch_creation_guard — open work branches are capped\n\n"
            "Creating a branch (`git switch -c`, `checkout -b`, `branch <name>`, "
            '`worktree add`, or an Agent dispatch with `isolation: "worktree"`) is '
            "denied while the open work branches are at `branches.wip.cap` "
            "(`wip.mode: warn` only warns). The deny lists every open branch, the "
            "merged ones first with their delete command: merge, park or delete one, "
            "or continue in an existing branch. A name already in `refs/heads` is a "
            "reset, never a creation. A name close to an existing branch's draws a "
            "duplicate warning naming it; that never blocks."
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for the branch creation guard."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="resetting an existing branch is not a creation",
                command="bash -n -c 'git branch -f main main'",
                dispatch_as_bash=True,
                description="A name already in refs/heads is never counted against the cap",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="bash -n -c only parses the command, never executes it",
                test_type=TestType.ADVISORY,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
