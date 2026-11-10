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
from claude_code_hooks_daemon.core.branch_practice import (
    nested_worktree_advisory,
    recovery_copy_advisory,
)
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.core.hook_result import Decision
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.core.rule import Rule, RuleFormatter
from claude_code_hooks_daemon.core.utils import get_bash_command
from claude_code_hooks_daemon.utils.cli_command import daemon_cli_command_for_docs
from claude_code_hooks_daemon.utils.git_branch_creation import (
    ROUTE_WORKTREE,
    created_branches,
    worktree_add_path,
)
from claude_code_hooks_daemon.utils.git_commit_parsing import GitInvocation
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
            fix="Finish (merge) one of the listed branches, park it with a reason, or delete it "
            "once the guard proves nothing is lost; only then start new work",
            verbose=(
                "WHY:\n"
                "  Every open branch is work someone must finish, park or delete.\n"
                "  The list below puts the cheapest to close first: merged and\n"
                "  patch-equivalent branches carry their delete command."
            ),
        )
        self._dormant_rule = Rule(
            rule_id=RuleID.BRANCH_DORMANT,
            blocked="creating a branch while an unparked, unmerged branch is at the "
            "`branches.dormancy` block stage",
            why="A branch nobody has touched for weeks is work that is being forgotten; "
            "new work waits until each one is finished, parked or deleted",
            fix="Merge it, `hooks-daemon branch-park <name> --reason ...`, or `delete-branch` it",
            verbose=(
                "WHY:\n"
                "  Dormancy ages a branch from its tip's commit date. Parked and merged\n"
                "  branches never trip it; `dormancy.mode: warn` stops at the noisy stage."
            ),
        )
        self._parked_rule = Rule(
            rule_id=RuleID.BRANCH_PARKED_POOL,
            blocked="creating a branch while the parked pool is at `branches.parked.cap` "
            "or holds a branch parked past `branches.parked.max_age_days`",
            why="Parking is a pause, not a place to leave work for ever; an un-cleared "
            "park is dormant work with a reason attached",
            fix="Merge it, `branch-park <name> --clear`, delete it, or re-park it with a "
            "NEW reason (a same-reason re-park is refused)",
            verbose=(
                "WHY:\n"
                "  A park commit ages the branch from the day it was written. The list\n"
                "  below shows each parked branch with the commands that clear it."
            ),
        )
        self._merged_rule = Rule(
            rule_id=RuleID.BRANCH_MERGED_POOL,
            blocked="creating a branch while the merged pool is at `branches.merged.cap` "
            "or holds an unkept merged branch",
            why="A merged branch is finished work: it is deleted, or kept on purpose with a "
            "reason, so merged branches never pile up unexplained",
            fix="Run the `branch-sweep --clean` line below, or keep a branch with "
            "`branch-keep <name> --reason ...`",
            verbose=(
                "WHY:\n"
                "  An unkept merged branch is stale from day 0; a keep lapses after\n"
                "  `branches.merged.max_age_days`. A branch a worktree holds is not stale."
            ),
        )
        self._rules_by_id: dict[str, Rule] = {
            RuleID.BRANCH_DORMANT: self._dormant_rule,
            RuleID.BRANCH_PARKED_POOL: self._parked_rule,
            RuleID.BRANCH_MERGED_POOL: self._merged_rule,
        }
        self._formatter = RuleFormatter()

    def get_rules(self) -> list[Rule]:
        """Return the Rules backing this handler's deny paths."""
        return [self._rule, self._dormant_rule, self._parked_rule, self._merged_rule]

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
        return command is not None and bool(created_branches(command))

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
            directory = self._creation_directory(creation.invocation, cwd)
            verdicts.append(
                creation_verdict(directory, self._branches, creation.name, labels=labels)
            )
        return verdicts

    @staticmethod
    def _creation_directory(run: GitInvocation, cwd: Path) -> Path:
        """The directory a git run acts in, or ``cwd`` when it cannot be placed."""
        return cwd if placement_problem(run, cwd) else invocation_directory(run, cwd)

    def _practice_advisories(self, hook_input: dict[str, Any]) -> list[str]:
        """Branch-practice advice for a git command: recovery-copy names, nested worktrees."""
        if self._is_isolated_dispatch(hook_input):
            return []
        cwd = Path(str(hook_input.get(HookInputField.CWD) or self._project_root()))
        lines: list[str] = []
        for creation in created_branches(get_bash_command(hook_input) or ""):
            advice = recovery_copy_advisory(creation.name)
            if advice is not None:
                lines.append(advice)
            if creation.route == ROUTE_WORKTREE:
                target = worktree_add_path(creation.invocation.arguments)
                directory = self._creation_directory(creation.invocation, cwd)
                nested = nested_worktree_advisory(directory, target) if target else None
                if nested is not None:
                    lines.append(nested)
        return lines

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        """Deny at the cap in block mode; otherwise allow with any warning lines."""
        verdicts = self._verdicts(hook_input)
        lines = [line for verdict in verdicts for line in verdict.lines]
        advice = self._practice_advisories(hook_input)
        worst = max((verdict.decision for verdict in verdicts), key=_SEVERITY.__getitem__)
        if worst == "deny":
            denying = next(verdict for verdict in verdicts if verdict.decision == "deny")
            rule = self._rules_by_id.get(denying.rule_id or "", self._rule)
            preflight = daemon_cli_command_for_docs("branch-preflight")
            reason = "\n".join(
                [
                    self._formatter.headline(rule),
                    "",
                    *lines,
                    f"Re-check every blocker and its fix at any time: `{preflight}`",
                ]
            )
            return GatingResult(decision=Decision.DENY, reason=reason)
        return GatingResult(decision=Decision.ALLOW, context=list(dict.fromkeys([*lines, *advice])))

    def get_claude_md(self) -> str | None:
        return (
            "## branch_creation_guard — three branch pools, each capped\n\n"
            "Creating a branch (`git switch -c`, `checkout -b`, `branch <name>`, "
            '`worktree add`, or an Agent dispatch with `isolation: "worktree"`) is '
            "denied while a pool is full: OPEN work at `branches.wip.cap`, PARKED "
            "branches at `branches.parked.cap` (or one parked past "
            "`branches.parked.max_age_days`), MERGED branches at `branches.merged.cap` "
            "(or one unkept or kept past `branches.merged.max_age_days`). Each pool "
            "has `mode: block|warn|off`. Merge, park or delete an open branch; clear "
            "a park with `branch-park <name> --clear` or re-park with a NEW reason; "
            "clear merged branches with `branch-sweep --clean` or keep one with "
            "`branch-keep <name> --reason ...`. `branch-preflight [name]` (read-only) lists "
            "every pool that blocks a creation right now with its exact fix; the deny "
            "prints the same report. Bot-owned branches (`branches.bot_owned`) "
            "are in no pool. A name already in `refs/heads` is a "
            "reset, never a creation. A name close to an existing branch's draws a "
            "duplicate warning naming it; that never blocks. Advisory only: a branch named "
            "like a recovery copy (`rescue/*`, `recovery/*`, `backup/*`, `*-rescue`, "
            "`*-backup`) is told to archive under `refs/archive/<name>` or a bundle "
            "instead, since pools count only branches; a worktree created inside "
            "another worktree is told the main checkout is where it is created, never "
            "nested."
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
