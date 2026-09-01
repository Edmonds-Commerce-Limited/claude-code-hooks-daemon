"""Advise worktree isolation when several agents already share one checkout.

Plan 00200 Task 6.5. Four agents were dispatched into a single ``/workspace``
checkout and the shared ``.git/index`` produced three incidents where staged
work was absorbed or lost by a peer's bare ``git commit``.

The proximate cause looked like the bare commit. The real defect was
**dispatching concurrent writers into a shared tree at all** — this daemon
already ships a ``worktree_create`` handler that makes isolation a one-flag
decision, and only one of the four agents genuinely needed the shared tree
(daemon-restart verification and client-mode testing are anchored to the
project root). A constraint binding one agent was applied to four.

Design constraints this pins:

- **Silent for a single agent.** At one or zero live threads there is nothing
  to collide with, so the overwhelmingly common case must see nothing.
- **Silent when isolation is already requested.** Advising someone who already
  did the right thing trains them to ignore the advisory.
- **Never blocks.** Sometimes the shared tree is genuinely required, and the
  handler cannot know which case it is looking at.
- **Never raises.** The thread count is read from disk; a missing or corrupt
  registry must yield "no advice", never a failed dispatch.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use.agent_isolation_advisor import (
    AgentIsolationAdvisorHandler,
)


def _task_input(**tool_input: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"prompt": "refactor the config loader"}
    payload.update(tool_input)
    return {"tool_name": "Task", "tool_input": payload}


@pytest.fixture
def handler() -> AgentIsolationAdvisorHandler:
    return AgentIsolationAdvisorHandler()


def _with_live_threads(count: int) -> Any:
    """Patch the registry read to report ``count`` live threads."""
    entries = [{"session_id": f"s{i}", "last_seen": 0.0} for i in range(count)]
    return patch.object(
        AgentIsolationAdvisorHandler,
        "_count_live_threads",
        return_value=len(entries),
    )


class TestIdentity:
    def test_is_advisory_not_terminal(self, handler: AgentIsolationAdvisorHandler) -> None:
        assert handler.terminal is False

    def test_exposes_claude_md_guidance(self, handler: AgentIsolationAdvisorHandler) -> None:
        """A DENY-capable handler needs guidance; an advisory one earns its context."""
        guidance = handler.get_claude_md()

        assert guidance is not None
        assert "worktree" in guidance.lower()


class TestMatching:
    def test_matches_task_spawn_when_peers_are_live(
        self, handler: AgentIsolationAdvisorHandler
    ) -> None:
        with _with_live_threads(3):
            assert handler.matches(_task_input()) is True

    def test_silent_for_a_lone_agent(self, handler: AgentIsolationAdvisorHandler) -> None:
        """THE most important negative: single-agent sessions must be untouched."""
        with _with_live_threads(1):
            assert handler.matches(_task_input()) is False

    def test_silent_when_no_threads_are_registered(
        self, handler: AgentIsolationAdvisorHandler
    ) -> None:
        with _with_live_threads(0):
            assert handler.matches(_task_input()) is False

    @pytest.mark.parametrize("isolation", ["worktree", "WORKTREE"])
    def test_silent_when_isolation_already_requested(
        self, handler: AgentIsolationAdvisorHandler, isolation: str
    ) -> None:
        """Do not nag someone who already did the right thing."""
        with _with_live_threads(4):
            assert handler.matches(_task_input(isolation=isolation)) is False

    def test_ignores_other_tools(self, handler: AgentIsolationAdvisorHandler) -> None:
        with _with_live_threads(4):
            assert handler.matches({"tool_name": "Bash", "tool_input": {"command": "ls"}}) is False

    def test_matches_agent_tool_name_dispatch(self, handler: AgentIsolationAdvisorHandler) -> None:
        # Claude Code >= 2.1.x dispatches subagents as tool_name "Agent"
        # (verified live in the v3.59.0 acceptance run).
        with _with_live_threads(4):
            hook_input = {"tool_name": "Agent", "tool_input": {"prompt": "work"}}
            assert handler.matches(hook_input) is True

    def test_ignores_a_task_call_without_a_prompt(
        self, handler: AgentIsolationAdvisorHandler
    ) -> None:
        with _with_live_threads(4):
            assert handler.matches({"tool_name": "Task", "tool_input": {}}) is False


class TestAdvice:
    def test_allows_and_names_the_flag(self, handler: AgentIsolationAdvisorHandler) -> None:
        with _with_live_threads(3):
            result = handler.handle(_task_input())

        assert result.decision == Decision.ALLOW
        joined = "\n".join(result.context or [])
        assert "isolation" in joined
        assert "worktree" in joined

    def test_reports_the_observed_count(self, handler: AgentIsolationAdvisorHandler) -> None:
        with _with_live_threads(4):
            result = handler.handle(_task_input())

        assert "4" in "\n".join(result.context or [])

    def test_names_the_exception_rather_than_advising_blindly(
        self, handler: AgentIsolationAdvisorHandler
    ) -> None:
        """Some agents genuinely need the shared tree; the advice must say so.

        Otherwise it pushes daemon-restart and client-mode verification into a
        worktree, where they do not work.
        """
        with _with_live_threads(3):
            joined = "\n".join(handler.handle(_task_input()).context or [])

        assert "daemon" in joined.lower()


class TestReadingTheRegistryNeverBreaksDispatch:
    """The count comes off disk, so every failure mode must degrade to silence."""

    def test_missing_registry_directory_yields_zero(
        self, handler: AgentIsolationAdvisorHandler, tmp_path: Path
    ) -> None:
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.agent_isolation_advisor."
            "ProjectContext.daemon_untracked_dir",
            return_value=tmp_path / "does-not-exist",
        ):
            assert handler._count_live_threads() == 0

    def test_unreadable_registry_does_not_raise(
        self, handler: AgentIsolationAdvisorHandler
    ) -> None:
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.agent_isolation_advisor."
            "ProjectContext.daemon_untracked_dir",
            side_effect=OSError("boom"),
        ):
            assert handler._count_live_threads() == 0

    def test_matches_is_false_when_the_count_cannot_be_read(
        self, handler: AgentIsolationAdvisorHandler
    ) -> None:
        """A registry failure must not turn into an advisory on every spawn."""
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.agent_isolation_advisor."
            "ProjectContext.daemon_untracked_dir",
            side_effect=OSError("boom"),
        ):
            assert handler.matches(_task_input()) is False
