"""BranchCountAdvisorHandler - open work branches and how far they lag (Plan 00475 Task 4.1).

CLAUDE/Worktree.md, "Small Batches", defines the rule this reports against:
at most 3 open work branches at once, counted as the ``worktree-*`` branches
that exist, a branch whose worktree is gone counting until it is deleted. An
unmerged branch also falls behind the default branch, and its merge cost grows
with every commit it misses.

On a new session this counts the local ``worktree-*`` branches. When there are
more than ``max_open_branches`` it names them all; it also names any branch more
than ``behind_main_threshold`` commits behind the default branch. It is
advisory only and silent when within both limits, outside a git repository, or
when git fails.
"""

import logging
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.core import AdvisoryResult, Decision
from claude_code_hooks_daemon.core.handler_bases import SessionStartHandlerBase
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.utils import git_sync
from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue
from claude_code_hooks_daemon.utils.git_repo import (
    HEADS_PREFIX,
    branch_ref,
    run_git,
    strip_branch_ref,
)
from claude_code_hooks_daemon.utils.session_helpers import is_resume_session

logger = logging.getLogger(__name__)

# CLAUDE/Worktree.md, "Small Batches": the limit and the branch naming it counts.
DEFAULT_MAX_OPEN_BRANCHES = 3
WORK_BRANCH_PREFIX = "worktree-"
# A branch this far behind is costly to merge (ledger 00466's stale branches were
# 139 to 650 commits behind); half of the smallest of those is the warning line.
DEFAULT_BEHIND_MAIN_THRESHOLD = 50

# SessionStart has a time budget (ledger 00474 N276) and each behind check is one
# git call, so only this many branches are measured; the rest are reported unchecked.
MAX_BEHIND_CHECKS = 20

_ICON = "🌿"


class BranchCountAdvisorHandler(SessionStartHandlerBase):
    """Name open work branches beyond the limit, and any far behind the default branch."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.BRANCH_COUNT_ADVISOR,
            priority=Priority.BRANCH_COUNT_ADVISOR,
            terminal=False,
            tags=[
                HandlerTag.ADVISORY,
                HandlerTag.GIT,
                HandlerTag.NON_TERMINAL,
                HandlerTag.WORKFLOW,
            ],
        )
        # Set by the registry from options.max_open_branches / behind_main_threshold.
        self._max_open_branches: int = DEFAULT_MAX_OPEN_BRANCHES
        self._behind_main_threshold: int = DEFAULT_BEHIND_MAIN_THRESHOLD

    def _get_project_root(self) -> Path:
        try:
            return ProjectContext.project_root()
        except RuntimeError:
            logger.debug("ProjectContext not initialised; using cwd for branch count")
            return Path.cwd()

    def _work_branches(self, root: Path) -> list[str]:
        """Local ``worktree-*`` branch names; empty when git fails."""
        result = run_git(
            root,
            "for-each-ref",
            "--format=%(refname)",
            f"{HEADS_PREFIX}{WORK_BRANCH_PREFIX}*",
            timeout=Timeout.GIT_CONTEXT,
        )
        if result.returncode != 0:
            logger.debug("branch_count_advisor: for-each-ref failed: %s", result.stderr.strip())
            return []
        return sorted(strip_branch_ref(line) for line in result.stdout.splitlines() if line)

    def _behind(self, root: Path, base: str, branch: str) -> int:
        """Commits on ``base`` that ``branch`` lacks.

        Raises:
            ValueError: git failed or printed something that is not a count.
        """
        result = run_git(
            root,
            "rev-list",
            "--count",
            f"{branch_ref(branch)}..{branch_ref(base)}",
            timeout=Timeout.GIT_CONTEXT,
        )
        if result.returncode != 0:
            raise ValueError(f"rev-list failed for {branch}: {result.stderr.strip()}")
        return int(result.stdout.strip())

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Run on new sessions only."""
        return not is_resume_session(hook_input)

    def handle(self, hook_input: dict[str, Any]) -> AdvisoryResult:
        """Report an over-limit branch count and any branch far behind the default branch."""
        root = self._get_project_root()
        branches = self._work_branches(root)
        if not branches:
            return AdvisoryResult(decision=Decision.ALLOW, context=[])

        base = git_sync.default_branch(root)
        stale: list[tuple[str, int]] = []
        unchecked = 0
        if base is not None:
            checked = branches[:MAX_BEHIND_CHECKS]
            unchecked = len(branches) - len(checked)
            for branch in checked:
                try:
                    behind = self._behind(root, base, branch)
                except ValueError as exc:
                    log_and_continue(
                        logger,
                        exc,
                        reason="a branch whose behind-count cannot be computed is left out of the advice; the advisory lists the other branches",
                        level=logging.DEBUG,
                    )
                    continue
                if behind > self._behind_main_threshold:
                    stale.append((branch, behind))

        context: list[str] = []
        if len(branches) > self._max_open_branches:
            context.extend(self._count_lines(branches))
        if stale and base is not None:
            if context:
                context.append("")
            context.extend(self._stale_lines(stale, base))
        if unchecked:
            if context:
                context.append("")
            context.append(
                f"{_ICON}  GIT: {unchecked} more work branch(es) not checked for how far "
                f"behind they are (only the first {MAX_BEHIND_CHECKS} are)."
            )
        return AdvisoryResult(decision=Decision.ALLOW, context=context)

    def _count_lines(self, branches: list[str]) -> list[str]:
        lines = [
            f"{_ICON}  GIT: {len(branches)} open work branches exist (limit "
            f"{self._max_open_branches}, see CLAUDE/Worktree.md, Small Batches). "
            "Finish one before starting another: merge it or drop it.",
            "",
        ]
        lines.extend(f"  - {name}" for name in branches)
        return lines

    def _stale_lines(self, stale: list[tuple[str, int]], base: str) -> list[str]:
        lines = [
            f"{_ICON}  GIT: work branch(es) more than {self._behind_main_threshold} commits "
            f"behind {base}. Merge cost grows with every commit missed; merge or drop them.",
            "",
        ]
        lines.extend(f"  - {name}: {behind} commits behind {base}" for name, behind in stale)
        return lines

    def get_claude_md(self) -> str | None:
        """The branch limit is a standing policy, not a one-shot correction."""
        return (
            "## branch_count_advisor — keep open work branches few\n\n"
            "At most `options.max_open_branches` (default 3) `worktree-*` branches may be "
            "open at once. Finish (merge or drop) one before starting another. A branch "
            "whose worktree is gone still counts until it is deleted. A branch more than "
            "`options.behind_main_threshold` (default 50) commits behind the default "
            "branch should be merged or dropped. Advisory only."
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Acceptance test: the advisory is silent or names branches, never blocks."""
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="branch count advisor - names work branches beyond the limit",
                command='echo "test"',
                description=(
                    "On a new session the handler counts worktree-* branches and, above the "
                    "limit or far behind the default branch, names them. It never blocks."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"open work branches|commits behind"],
                safety_notes="Advisory only; reads branch refs, changes nothing",
                test_type=TestType.CONTEXT,
                requires_event="SessionStart event (new session only)",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
