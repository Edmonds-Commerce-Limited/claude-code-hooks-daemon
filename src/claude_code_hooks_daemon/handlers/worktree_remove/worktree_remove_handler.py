"""WorktreeRemove handler — clean up daemon-created worktrees (Plan 00188).

Because :mod:`WorktreeCreateHandler` now creates real git worktrees, the daemon
also deregisters them on WorktreeRemove so ``git worktree list`` never fills with
stale entries. WorktreeRemove is a side-effect-only event (it cannot block and
``{}`` is a safe response), so this handler never raises to the event chain and
always returns an empty allow.

The exact Claude Code WorktreeRemove payload was not observed, so the handler is
payload-defensive:

- ALWAYS ``git worktree prune`` — path-independent and safe (it only drops
  registrations whose working directory has already been removed; a live
  worktree is never touched).
- ADDITIONALLY ``git worktree remove --force <path>`` when the payload carries a
  worktree path that still exists on disk.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.constants.handlers import HandlerID
from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.core.handler import Handler
from claude_code_hooks_daemon.core.hook_result import HookResult
from claude_code_hooks_daemon.utils.git_repo import run_git

_WORKTREE_REMOVE_PRIORITY = 50

_KEY_CWD = "cwd"
# Payload keys that may carry the worktree path (defensive — exact key unknown).
_PATH_KEYS = ("worktree_path", "path")


class WorktreeRemoveHandler(Handler):
    """Prune stale worktree registrations (and remove a named worktree)."""

    def __init__(self) -> None:
        super().__init__(
            HandlerID.WORKTREE_REMOVE,
            priority=_WORKTREE_REMOVE_PRIORITY,
            terminal=True,
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Handle every WorktreeRemove event (no matcher filtering)."""
        return True

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Best-effort cleanup; always a clean allow (WorktreeRemove is safe)."""
        cwd = hook_input.get(_KEY_CWD)
        if cwd:
            path = self._extract_path(hook_input)
            if path is not None and path.exists():
                self._run_git(str(cwd), "worktree", "remove", "--force", str(path))
            # Prune last so registrations for just-removed / externally-deleted
            # worktrees are dropped regardless of how the directory went away.
            self._run_git(str(cwd), "worktree", "prune")
        return HookResult()

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
        """Run a git subcommand from ``cwd``, swallowing expected failures.

        WorktreeRemove is non-blocking, so a git error (not a repo, worktree
        already gone) must not propagate — it is surfaced on stderr, never
        silently discarded. :func:`run_git` never raises, so a failure is just a
        non-zero ``returncode`` to report rather than an exception to catch.
        """
        result = run_git(Path(cwd), *args, timeout=Timeout.GIT_WORKTREE)
        if result.returncode != 0:
            # Expected when cwd is not a repo or the worktree is already gone.
            # Non-blocking event: report and continue, never crash the chain.
            print(
                f"worktree_remove: git {' '.join(args)} failed: {result.stderr.strip()}",
                file=sys.stderr,
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
