"""AgentIsolationAdvisorHandler - advise worktree isolation for concurrent agents.

Plan 00200 Task 6.5. Four agents were dispatched into one ``/workspace``
checkout and the shared ``.git/index`` produced three incidents where staged
work was absorbed or lost by a peer's bare ``git commit``.

The proximate cause looked like the bare commit, and a process rule ("always
scope your commits to a pathspec") is the obvious response. But pathspec
scoping protects the *committer*, not the agent whose staged work a
bare-committing peer absorbs — so a process rule only works if every writer
follows it, which is precisely the argument for a guard instead.

The deeper fix is upstream of the commit: **do not dispatch concurrent writers
into a shared tree.** This daemon already ships a ``worktree_create`` handler
that makes isolation a one-flag decision, and only one of those four agents
genuinely needed the shared checkout — daemon-restart verification and
client-mode testing are anchored to the project root. A constraint binding one
agent had been applied to all four.

Advisory, never blocking: the handler cannot tell which case it is looking at,
and sometimes the shared tree is genuinely required.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from claude_code_hooks_daemon.constants import (
    HandlerID,
    HandlerTag,
    HookInputField,
    Priority,
    ToolName,
)
from claude_code_hooks_daemon.core import Decision, Handler, HookResult, ProjectContext
from claude_code_hooks_daemon.handlers.status_line.thread_registry import (
    _REGISTRY_SUBDIR,
    read_live_entries,
)

logger = logging.getLogger(__name__)

# The Task tool's isolation flag, and the value that already does the right
# thing. Compared case-insensitively so a differently-cased spelling still
# counts as "already isolated" rather than earning a redundant nag.
_ISOLATION_FIELD = "isolation"
_WORKTREE_ISOLATION = "worktree"

# Below this many live threads there is nothing to collide with, so the handler
# stays silent. One thread is the spawning session itself.
_MIN_THREADS_TO_ADVISE = 2


class AgentIsolationAdvisorHandler(Handler):
    """Advise ``isolation: worktree`` when peers are already active in this checkout.

    Silent in the common case. It only speaks when ALL of:

    - the Task tool is spawning an agent, and
    - more than one live thread is registered for this project, and
    - the spawn has not already asked for worktree isolation.
    """

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.AGENT_ISOLATION_ADVISOR,
            priority=Priority.AGENT_ISOLATION_ADVISOR,
            terminal=False,
            tags=[
                HandlerTag.WORKFLOW,
                HandlerTag.ADVISORY,
                HandlerTag.NON_TERMINAL,
            ],
        )

    def _count_live_threads(self) -> int:
        """Live threads registered for this project, or 0 if that cannot be read.

        The registry is on disk and written by a different handler, so every
        failure mode degrades to 0 — which makes ``matches()`` False. A guard
        that cannot read its input must go quiet, not advise on every spawn.
        """
        try:
            registry_dir = ProjectContext.daemon_untracked_dir() / _REGISTRY_SUBDIR
            return len(read_live_entries(registry_dir, time.time()))
        except (OSError, ValueError, RuntimeError) as exc:
            logger.debug("Thread registry unreadable, skipping isolation advice: %s", exc)
            return 0

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """True when a Task spawn would join an already-shared checkout."""
        if hook_input.get(HookInputField.TOOL_NAME) != ToolName.TASK:
            return False

        tool_input = hook_input.get(HookInputField.TOOL_INPUT, {})
        if not isinstance(tool_input, dict) or not tool_input.get("prompt"):
            return False

        isolation = tool_input.get(_ISOLATION_FIELD)
        if isinstance(isolation, str) and isolation.strip().lower() == _WORKTREE_ISOLATION:
            return False

        return self._count_live_threads() >= _MIN_THREADS_TO_ADVISE

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Suggest isolation, and name the case where the shared tree is correct."""
        live = self._count_live_threads()

        return HookResult(
            decision=Decision.ALLOW,
            context=[
                f"🌳 CONCURRENT AGENTS: {live} live threads share this checkout\n\n"
                f"Agents dispatched into one working tree share a single .git/index. "
                f"A peer's bare `git commit` can absorb another agent's staged work, "
                f"and that failure is silent — the losing agent sees its changes "
                f"committed by someone else, or not at all.\n\n"
                f'CONSIDER: pass `isolation: "worktree"` to the Agent tool so this '
                f"agent gets its own checkout. Merge back with `git merge` or "
                f"`git cherry-pick`.\n\n"
                f"KEEP THE SHARED TREE when the agent needs it — daemon restart "
                f"verification and client-mode testing are anchored to the project "
                f"root and do NOT work in a worktree. Isolation is the default worth "
                f"reaching for, not a blanket rule.\n\n"
                f"Advisory only — proceeding as dispatched.",
            ],
        )

    def get_claude_md(self) -> str | None:
        return (
            "## agent_isolation_advisor — isolate concurrent agents\n\n"
            "When more than one agent thread is live in this checkout, spawning "
            "another Agent without isolation is flagged (advisory, never blocked).\n\n"
            "Agents in one working tree share a single `.git/index`, so a peer's "
            "bare `git commit` can silently absorb another agent's staged work.\n\n"
            '**Prefer**: `isolation: "worktree"` on the Agent tool, then `git merge` '
            "or `git cherry-pick` to bring work back.\n\n"
            "**Keep the shared tree** for agents that need the real project root — "
            "daemon restart verification and client-mode testing do not work in a "
            "worktree."
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for the agent isolation advisor."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="Agent spawned without isolation while peers are live",
                command=(
                    "With more than one agent thread active, use the Agent tool "
                    "without an isolation setting"
                ),
                description="Advises worktree isolation when agents share a checkout",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"worktree", r"CONCURRENT AGENTS"],
                safety_notes="Advisory only — never blocks. Silent for a single agent.",
                test_type=TestType.ADVISORY,
                requires_event="PreToolUse with Task tool",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="Agent spawned WITH worktree isolation (near-miss allow)",
                command='Use the Agent tool with isolation: "worktree"',
                description="Stays silent when isolation was already requested",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes=(
                    "Negative case (Plan 00200 Task 6.4): advising someone who already "
                    "did the right thing trains them to ignore the advisory."
                ),
                test_type=TestType.ADVISORY,
                requires_event="PreToolUse with Task tool",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=False,
            ),
        ]
