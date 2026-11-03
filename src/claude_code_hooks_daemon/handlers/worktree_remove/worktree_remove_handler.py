"""WorktreeRemove handler: lossless removal, then the proven-merged branch (Plans 00188, 00558).

WorktreeRemove is a side-effect-only event (it cannot block and ``{}`` is a safe
response), so this handler never raises to the event chain and always returns
an empty allow. What it did, and what it left, goes to the daemon log.

1. Map the payload path to its branch through ``git worktree list --porcelain``.
   A path git does not list as a linked worktree is never removed.
2. Remove the worktree only when :func:`worktree_blockers` finds nothing a
   removal would lose: ``git worktree remove`` deletes ignored files, the
   scratch notes among them (issue #155). ``--force`` is added only when HEAD is
   also contained in another ref (DESIGN.md section 11); otherwise git's own
   refusal stands. A blocked worktree is left and its blocking paths logged.
3. A branch WorktreeCreate made (creator route ``worktree_create``; with no
   creator record at all, the ``<slug>-<8 hex>`` name) is deleted through
   :func:`delete_if_merged` when the default or an integration line holds every
   commit. Anything else is left for ``branch-sweep --clean``.
4. Always ``git worktree prune`` (only drops registrations whose directory is
   already gone).

Every git call is timed against the event's handler budget; when it runs out,
the remaining steps are skipped and logged rather than overrunning the chain.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.config.models import BranchesConfig
from claude_code_hooks_daemon.constants.events import EventType
from claude_code_hooks_daemon.constants.handlers import HandlerID
from claude_code_hooks_daemon.constants.protocol import HookInputField
from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.core import AdvisoryResult
from claude_code_hooks_daemon.core.branch_cleanup import (
    CleanupReport,
    delete_if_merged,
    render,
    worktree_blockers,
)
from claude_code_hooks_daemon.core.handler_bases import WorktreeRemoveHandlerBase
from claude_code_hooks_daemon.core.branch_records import worktree_branch_deletable
from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue
from claude_code_hooks_daemon.utils.git_repo import (
    WorktreeRecord,
    branch_ref,
    parse_worktree_porcelain,
    run_git,
)
from claude_code_hooks_daemon.utils.git_sync import resolve_default_branch
from claude_code_hooks_daemon.utils.path_predicates import path_exists

logger = logging.getLogger(__name__)

_WORKTREE_REMOVE_PRIORITY = 50

# Payload keys that may carry the worktree path (defensive: exact key unknown).
_PATH_KEYS = ("worktree_path", "path")

#: Time the branch step needs left over before it starts (creator record read,
#: probes plus delete).
_BRANCH_STEP_RESERVE = 3 * Timeout.GIT_CONTEXT


class _BudgetSpent(Exception):
    """The handler budget ran out before the next step."""


class _Clock:
    """The time left of this event's handler budget."""

    def __init__(self) -> None:
        budget = Timeout.EVENT_HANDLER_BUDGET[EventType.WORKTREE_REMOVE]
        self._deadline = time.monotonic() + budget

    def left(self) -> float:
        return self._deadline - time.monotonic()

    def timeout(self, nominal: float, step: str) -> float:
        """``nominal`` capped by the time left; raises when none is left."""
        left = self.left()
        if left <= 0:
            raise _BudgetSpent(step)
        return min(nominal, left)


def _linked_record(records: Sequence[WorktreeRecord], path: Path) -> WorktreeRecord | None:
    """The LINKED worktree record at ``path`` (never the main checkout), or None."""
    wanted = path.resolve()
    for record in records[1:]:
        if record.path.resolve() == wanted:
            return record
    return None


def _contained_elsewhere(record: WorktreeRecord, clock: _Clock) -> bool:
    """Whether the worktree's HEAD is reachable from a ref other than its own branch.

    A git failure reads as not contained, so ``--force`` is withheld.
    """
    listing = run_git(
        record.path,
        "for-each-ref",
        "--contains",
        "HEAD",
        "--format=%(refname)",
        timeout=clock.timeout(Timeout.GIT_CONTEXT, "the containment check"),
    )
    if listing.returncode != 0:
        return False
    own = branch_ref(record.branch) if record.branch is not None else None
    return any(ref and ref != own for ref in listing.stdout.splitlines())


class WorktreeRemoveHandler(WorktreeRemoveHandlerBase):
    """Remove a worktree without loss, then delete its branch when proven merged."""

    def __init__(self) -> None:
        super().__init__(
            HandlerID.WORKTREE_REMOVE,
            priority=_WORKTREE_REMOVE_PRIORITY,
            terminal=True,
        )
        # Injected by the registry from the top-level `branches:` block.
        self._branches: BranchesConfig = BranchesConfig()

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Handle every WorktreeRemove event (no matcher filtering)."""
        return True

    def handle(self, hook_input: dict[str, Any]) -> AdvisoryResult:
        """Best-effort cleanup; always a clean allow (WorktreeRemove is safe)."""
        cwd = hook_input.get(HookInputField.CWD)
        if not cwd:
            return AdvisoryResult()
        clock = _Clock()
        path = self._extract_path(hook_input)
        # The payload path arrives with no containment check, so it is as
        # unstattable as any caller-supplied path: an unreadable one skips the
        # removal and leaves the prune below to clean up.
        if path is not None and path_exists(path, unreadable_means=False):
            try:
                self._remove(Path(cwd), path, clock)
            except _BudgetSpent as spent:
                log_and_continue(
                    logger,
                    spent,
                    reason=f"WorktreeRemove cannot block and must answer within its budget; "
                    f"{path} and its branch are left for branch-sweep --clean",
                )
        # Prune last so registrations for just-removed / externally-deleted
        # worktrees are dropped regardless of how the directory went away.
        if clock.left() > 0:
            self._run_git(str(cwd), "worktree", "prune")
        else:
            logger.warning("worktree_remove: the handler budget ran out before git worktree prune")
        return AdvisoryResult()

    def _remove(self, cwd: Path, path: Path, clock: _Clock) -> None:
        """Steps 1-3 of the module docstring for the worktree at ``path``."""
        listing = run_git(
            cwd,
            "worktree",
            "list",
            "--porcelain",
            timeout=clock.timeout(Timeout.GIT_CONTEXT, "the worktree listing"),
        )
        if listing.returncode != 0:
            logger.warning("worktree_remove: git worktree list failed: %s", listing.stderr.strip())
            return
        records = parse_worktree_porcelain(listing.stdout)
        record = _linked_record(records, path)
        if record is None:
            logger.warning("worktree_remove: %s is not a linked worktree; it is left alone", path)
            return
        clock.timeout(Timeout.GIT_CONTEXT, "the loss check")
        blockers = worktree_blockers(record.path, self._branches.cleanup_after_merge.regenerable)
        if blockers:
            logger.warning(
                "worktree_remove: %s is left in place; removing it would lose: %s",
                record.path,
                ", ".join(blockers),
            )
            return
        args = ["worktree", "remove"]
        if _contained_elsewhere(record, clock):
            args.append("--force")
        removed = run_git(
            cwd, *args, str(record.path), timeout=clock.timeout(Timeout.GIT_WORKTREE, "the removal")
        )
        if removed.returncode != 0:
            logger.warning(
                "worktree_remove: git refused to remove %s: %s", record.path, removed.stderr.strip()
            )
            return
        if record.branch is not None:
            self._delete_branch(records[0].path, record.branch, clock)

    def _delete_branch(self, repo: Path, name: str, clock: _Clock) -> None:
        """Delete ``name`` when it is a WorktreeCreate branch proven merged.

        Its creator record decides (route ``worktree_create``); only a branch with
        no record falls back to the ``<slug>-<8 hex>`` name shape.
        """
        if clock.left() < _BRANCH_STEP_RESERVE:
            raise _BudgetSpent(f"the branch check of {name}")
        record_timeout = clock.timeout(Timeout.GIT_CONTEXT, f"the creator record of {name}")
        if not worktree_branch_deletable(repo, name, timeout=record_timeout):
            logger.info("worktree_remove: %s was not made by WorktreeCreate; branch kept", name)
            return
        default = resolve_default_branch(self._branches, repo)
        if default is None:
            report = CleanupReport(skipped=(f"{name}: no default branch resolves",))
        else:
            try:
                report = delete_if_merged(
                    repo,
                    name,
                    config=self._branches,
                    default=default,
                    probe_timeout=clock.timeout(Timeout.GIT_CONTEXT, f"the merge probe of {name}"),
                )
            except RuntimeError as exc:
                log_and_continue(
                    logger,
                    exc,
                    reason="an unread ref listing proves nothing, so the branch is kept "
                    "for branch-sweep --clean",
                )
                report = CleanupReport(skipped=(f"{name}: the refs could not be read: {exc}",))
        logger.warning(
            "worktree_remove: %s (made by WorktreeCreate): %s",
            name,
            "; ".join(render(report)),
        )

    @staticmethod
    def _extract_path(hook_input: dict[str, Any]) -> Path | None:
        """Return the first recognisable worktree path in the payload, if any."""
        for key in _PATH_KEYS:
            value = hook_input.get(key)
            if isinstance(value, str) and value:
                return Path(value)
        return None

    @staticmethod
    def _run_git(cwd: str, *args: str) -> None:
        """Run a cheap git subcommand from ``cwd``, reporting a failure.

        WorktreeRemove is non-blocking, so a git error (not a repo, worktree
        already gone) must not propagate; it is logged, never discarded.
        """
        result = run_git(Path(cwd), *args, timeout=Timeout.GIT_CONTEXT)
        if result.returncode != 0:
            logger.warning(
                "worktree_remove: git %s failed: %s", " ".join(args), result.stderr.strip()
            )

    def get_claude_md(self) -> str | None:
        """No agent-facing guidance — silent housekeeping."""
        return None

    def get_acceptance_tests(self) -> list[Any]:
        """VERIFIED_BY_LOAD: WorktreeRemove fires only on worktree teardown
        (untriggerable by a tool call), verified by daemon load + unit tests.
        """
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="worktree_remove prunes stale worktrees",
                command='echo "worktree remove verified by unit tests"',
                description=(
                    "WorktreeRemove runs git worktree prune (and removes a named "
                    "worktree) so registrations never accumulate; always a clean {}."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r".*"],
                safety_notes="Untriggerable by tool call; verified by daemon load + unit tests.",
                test_type=TestType.CONTEXT,
                requires_event="WorktreeRemove event",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
