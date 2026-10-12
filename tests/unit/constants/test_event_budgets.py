"""Per-event time budgets (Plan 00512, issue #82).

WorktreeCreate and WorktreeRemove run git, not a guard's judgement, so the 20s
guard chain deadline is the wrong budget for them. These tests pin the ordering
handler budget < chain deadline < client wait for every event with its own
budget, that every other event keeps the guard deadline, and that the shell
client and the relay forwarder mirror the same numbers.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.config.models import ChainConfig, TransportConfig
from claude_code_hooks_daemon.constants.events import EventType
from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.core.chain import HandlerChain
from claude_code_hooks_daemon.handlers.worktree_create import worktree_create_handler as wch
from claude_code_hooks_daemon.handlers.worktree_create.worktree_create_handler import (
    WorktreeCreateHandler,
)
from claude_code_hooks_daemon.handlers.worktree_remove import worktree_remove_handler as wrh
from claude_code_hooks_daemon.handlers.worktree_remove.worktree_remove_handler import (
    WorktreeRemoveHandler,
)
from claude_code_hooks_daemon.install.forwarder_generator import build_relay_guard_block

_REPO_ROOT = Path(__file__).resolve().parents[3]
_BUDGET_EVENTS = [EventType.WORKTREE_CREATE, EventType.WORKTREE_REMOVE]


def _recorded_git_timeouts(module: Any, handler: Any, hook_input: dict[str, Any]) -> list[float]:
    """Run ``handler`` with every git call failing; return each call's timeout."""
    timeouts: list[float] = []

    def fake_run_git(cwd: Path, *args: str, timeout: float = 0, **_: Any) -> Any:
        timeouts.append(timeout)
        return subprocess.CompletedProcess(["git", *args], 1, "", "boom")

    with patch.object(module, "run_git", fake_run_git):
        try:
            handler.handle(hook_input)
        except subprocess.CalledProcessError:
            pass
    return timeouts


class TestBudgetOrdering:
    @pytest.mark.parametrize("event", _BUDGET_EVENTS)
    def test_handler_budget_below_deadline_below_client_wait(self, event: EventType) -> None:
        budget = Timeout.EVENT_HANDLER_BUDGET[event]
        deadline = ChainConfig().deadline_for(event)
        wait = Timeout.EVENT_CLIENT_WAIT[event]
        assert deadline is not None
        assert budget < deadline < wait
        assert wait - deadline >= Timeout.CHAIN_DEADLINE_SOCKET_MARGIN_SECONDS

    def test_worktree_create_git_budget_fits_the_chain_deadline(self) -> None:
        deadline = ChainConfig().deadline_for(EventType.WORKTREE_CREATE)
        assert deadline is not None
        assert Timeout.GIT_WORKTREE < deadline

    def test_create_handler_worst_case_git_time_is_within_its_budget(self, tmp_path: Path) -> None:
        timeouts = _recorded_git_timeouts(
            wch,
            WorktreeCreateHandler(),
            {"cwd": str(tmp_path), "name": "x", "prompt_id": "p", "session_id": "s"},
        )
        assert timeouts, "the handler made no git call"
        assert sum(timeouts) <= Timeout.EVENT_HANDLER_BUDGET[EventType.WORKTREE_CREATE]

    def test_remove_handler_worst_case_git_time_is_within_its_budget(self, tmp_path: Path) -> None:
        worktree = tmp_path / "wt"
        worktree.mkdir()
        timeouts = _recorded_git_timeouts(
            wrh,
            WorktreeRemoveHandler(),
            {"cwd": str(tmp_path), "worktree_path": str(worktree)},
        )
        assert len(timeouts) == 2
        assert sum(timeouts) <= Timeout.EVENT_HANDLER_BUDGET[EventType.WORKTREE_REMOVE]


class TestGuardEventsKeepTheGuardDeadline:
    @pytest.mark.parametrize(
        "event", [e for e in EventType if e not in _BUDGET_EVENTS], ids=lambda e: e.value
    )
    def test_every_other_event_keeps_the_configured_deadline(self, event: EventType) -> None:
        assert ChainConfig().deadline_for(event) == Timeout.CHAIN_DEADLINE_DEFAULT == 20
        assert ChainConfig(deadline_seconds=7).deadline_for(event) == 7

    @pytest.mark.parametrize("event", _BUDGET_EVENTS)
    def test_disabled_deadline_stays_disabled(self, event: EventType) -> None:
        assert ChainConfig(deadline_seconds=None).deadline_for(event) is None

    @pytest.mark.parametrize("event", _BUDGET_EVENTS)
    def test_a_configured_deadline_cannot_undercut_the_event_budget(self, event: EventType) -> None:
        assert (
            ChainConfig(deadline_seconds=5).deadline_for(event)
            == Timeout.EVENT_CHAIN_DEADLINE[event]
        )


class TestSlowAddStillYieldsThePath:
    def test_add_slower_than_the_guard_deadline_answers_within_the_event_deadline(
        self, tmp_path: Path
    ) -> None:
        """An add that outlives a guard-sized deadline still returns its path."""
        slow_seconds = 0.6
        guard_sized = 0.2

        def slow_add(cwd: str, path: Path, branch: str) -> None:
            import time

            time.sleep(slow_seconds)
            path.mkdir(parents=True)

        handler = WorktreeCreateHandler()
        chain = HandlerChain()
        chain.add(handler)
        hook_input = {"cwd": str(tmp_path), "name": "slow", "prompt_id": "p", "session_id": "s"}

        with (
            patch.object(WorktreeCreateHandler, "_git_worktree_add", staticmethod(slow_add)),
            patch.object(WorktreeCreateHandler, "_repo_root", staticmethod(lambda cwd: cwd)),
            patch.dict(Timeout.EVENT_CHAIN_DEADLINE, {EventType.WORKTREE_CREATE: slow_seconds * 5}),
        ):
            deadline = ChainConfig(deadline_seconds=guard_sized).deadline_for(
                EventType.WORKTREE_CREATE
            )
            result = chain.execute(hook_input, deadline_seconds=deadline)

        assert result.result.worktree_path is not None
        assert Path(result.result.worktree_path).is_dir()


class TestClientMirrors:
    def test_init_sh_default_wait_matches_the_event_table(self) -> None:
        source = (_REPO_ROOT / "init.sh").read_text(encoding="utf-8")
        found = dict(re.findall(r"^\s*(Worktree\w+)\) _event_socket_wait=(\d+);;", source, re.M))
        expected = {str(e.value): str(Timeout.EVENT_CLIENT_WAIT[e]) for e in _BUDGET_EVENTS}
        assert found == expected

    @pytest.mark.parametrize(
        ("bash_key", "event"),
        [("worktree-remove", EventType.WORKTREE_REMOVE), ("pre-tool-use", EventType.PRE_TOOL_USE)],
    )
    def test_relay_guard_waits_for_the_event_budget(
        self, bash_key: str, event: EventType, tmp_path: Path
    ) -> None:
        block = build_relay_guard_block(bash_key, TransportConfig(), tmp_path / "u", tmp_path)
        wait = Timeout.EVENT_CLIENT_WAIT.get(event, TransportConfig().timeout_seconds)
        assert f'--timeout-ms "{int(wait * 1000)}"' in block
