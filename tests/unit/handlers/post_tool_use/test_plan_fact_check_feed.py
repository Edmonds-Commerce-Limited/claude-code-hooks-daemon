"""Tests for PlanFactCheckFeedHandler (Plan 00480 Tasks 4.1 to 4.3).

The debouncer is injected with a fake clock and an inline runner, so no test
sleeps.
"""

import logging
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.constants import HandlerID, Priority
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.debouncer import Debouncer
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.handlers.post_tool_use import plan_fact_check_feed
from claude_code_hooks_daemon.handlers.post_tool_use.plan_fact_check_feed import (
    PlanFactCheckFeedHandler,
)
from claude_code_hooks_daemon.utils.plan_fact_check import PlanFactCheckState

# matches() also looks for owed checks in the daemon untracked dir.
pytestmark = pytest.mark.usefixtures("state_dir")


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _inline(job: Callable[[], None]) -> None:
    job()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def debouncer(clock: FakeClock, monkeypatch: pytest.MonkeyPatch) -> Iterator[Debouncer]:
    instance = Debouncer(clock=clock, runner=_inline, start_scheduler=False)
    monkeypatch.setattr(plan_fact_check_feed, "get_debouncer", lambda: instance)
    yield instance
    instance.shutdown()


@pytest.fixture
def state_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    target = tmp_path / "untracked"
    target.mkdir()
    monkeypatch.setattr(ProjectContext, "daemon_untracked_dir", classmethod(lambda cls: target))
    monkeypatch.setattr(ProjectContext, "project_root", classmethod(lambda cls: tmp_path))
    return target


def _baseline(state_dir: Path, *folders: str) -> None:
    """Record empty checked content, so the next fire is past first sight."""
    state = PlanFactCheckState(state_dir / "plan-fact-check")
    for folder in folders:
        state.record_checked(folder, {})


@pytest.fixture
def handler() -> PlanFactCheckFeedHandler:
    return PlanFactCheckFeedHandler()


def _plan_file(tmp_path: Path, folder: str, name: str = "PLAN.md", text: str = "x\n") -> Path:
    path = tmp_path / "CLAUDE" / "Plan" / folder / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _write(path: Path) -> dict[str, Any]:
    return {"tool_name": "Write", "tool_input": {"file_path": str(path), "content": "x"}}


class TestRegistration:
    def test_identity_priority_and_non_terminal(self, handler: PlanFactCheckFeedHandler) -> None:
        assert handler.handler_id == HandlerID.PLAN_FACT_CHECK_FEED
        assert handler.priority == Priority.PLAN_FACT_CHECK_FEED
        assert handler.terminal is False

    def test_ships_default_disabled(self, handler: PlanFactCheckFeedHandler) -> None:
        assert PlanFactCheckFeedHandler.default_enabled is False
        assert handler.get_default_enabled() is False

    def test_default_quiet_period_is_five_seconds(self, handler: PlanFactCheckFeedHandler) -> None:
        assert handler._quiet_seconds == 5.0


class TestMatches:
    def test_matches_a_plan_write(self, handler: PlanFactCheckFeedHandler, tmp_path: Path) -> None:
        assert handler.matches(_write(_plan_file(tmp_path, "00001-a"))) is True

    def test_matches_a_plan_edit(self, handler: PlanFactCheckFeedHandler, tmp_path: Path) -> None:
        path = _plan_file(tmp_path, "00001-a")
        hook = {"tool_name": "Edit", "tool_input": {"file_path": str(path)}}
        assert handler.matches(hook) is True

    def test_matches_a_bash_write_to_a_plan(
        self, handler: PlanFactCheckFeedHandler, tmp_path: Path
    ) -> None:
        path = _plan_file(tmp_path, "00001-a")
        hook = {"tool_name": "Bash", "tool_input": {"command": f"echo hi > {path}"}}
        assert handler.matches(hook) is True

    def test_ignores_non_plan_paths(
        self, handler: PlanFactCheckFeedHandler, tmp_path: Path
    ) -> None:
        other = tmp_path / "src" / "a.py"
        other.parent.mkdir()
        other.write_text("x")
        assert handler.matches(_write(other)) is False

    def test_ignores_non_write_tools(self, handler: PlanFactCheckFeedHandler) -> None:
        assert handler.matches({"tool_name": "Read", "tool_input": {"file_path": "/x"}}) is False


class TestWorktreePaths:
    """N359 item 1: a worktree's plan edit never feeds the main session's debouncer."""

    def _worktree_plan(self, tmp_path: Path) -> Path:
        path = tmp_path / ".claude" / "worktrees" / "agent-1" / "CLAUDE" / "Plan" / "00001-a"
        path.mkdir(parents=True)
        plan = path / "PLAN.md"
        plan.write_text("x\n", encoding="utf-8")
        return plan

    def test_a_plan_edit_in_a_nested_worktree_is_ignored(
        self, handler: PlanFactCheckFeedHandler, debouncer: Debouncer, tmp_path: Path
    ) -> None:
        hook = _write(self._worktree_plan(tmp_path))
        assert handler.matches(hook) is False
        handler.handle(hook)
        assert debouncer.pending() == {}

    def test_untracked_worktrees_are_ignored_too(
        self, handler: PlanFactCheckFeedHandler, tmp_path: Path
    ) -> None:
        folder = tmp_path / "untracked" / "worktrees" / "w" / "CLAUDE" / "Plan" / "00001-a"
        folder.mkdir(parents=True)
        plan = folder / "PLAN.md"
        plan.write_text("x\n", encoding="utf-8")
        assert handler.matches(_write(plan)) is False

    def test_a_session_rooted_in_the_worktree_still_feeds(
        self,
        handler: PlanFactCheckFeedHandler,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        plan = self._worktree_plan(tmp_path)
        worktree_root = tmp_path / ".claude" / "worktrees" / "agent-1"
        monkeypatch.setattr(ProjectContext, "project_root", classmethod(lambda cls: worktree_root))
        assert handler.matches(_write(plan)) is True

    def test_a_path_outside_the_project_is_ignored(
        self,
        handler: PlanFactCheckFeedHandler,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        monkeypatch.setattr(ProjectContext, "project_root", classmethod(lambda cls: elsewhere))
        assert handler.matches(_write(_plan_file(tmp_path, "00001-a"))) is False


class TestFirstSight:
    def test_a_first_edit_records_a_baseline_and_delivers_nothing(
        self,
        handler: PlanFactCheckFeedHandler,
        debouncer: Debouncer,
        clock: FakeClock,
        state_dir: Path,
        tmp_path: Path,
    ) -> None:
        handler.handle(_write(_plan_file(tmp_path, "00001-a", text="whole folder\n")))
        clock.advance(6.0)
        debouncer.run_due()
        state = PlanFactCheckState(state_dir / "plan-fact-check")
        assert state.pending_folders() == []
        assert state.read_checked("00001-a") is not None
        unrelated = {"tool_name": "Read", "tool_input": {"file_path": "/x"}}
        assert not handler.handle(unrelated).context


class TestDebouncedFeed:
    def test_burst_of_edits_to_one_plan_fires_exactly_once(
        self,
        handler: PlanFactCheckFeedHandler,
        debouncer: Debouncer,
        clock: FakeClock,
        state_dir: Path,
        tmp_path: Path,
    ) -> None:
        _baseline(state_dir, "00001-a")
        path = _plan_file(tmp_path, "00001-a", text="one\n")
        for _ in range(5):
            result = handler.handle(_write(path))
            assert result.decision == Decision.ALLOW
            clock.advance(1.0)
        assert debouncer.run_due() == 0  # 1 s after the last edit: still quiet-waiting
        clock.advance(4.5)
        assert debouncer.run_due() == 1
        pending = PlanFactCheckState(state_dir / "plan-fact-check").read_pending("00001-a")
        assert pending is not None
        assert pending.trigger_count == 5
        assert "+one" in pending.diff
        assert debouncer.run_due() == 0

    def test_two_plans_fire_independently(
        self,
        handler: PlanFactCheckFeedHandler,
        debouncer: Debouncer,
        clock: FakeClock,
        state_dir: Path,
        tmp_path: Path,
    ) -> None:
        _baseline(state_dir, "00001-a", "00002-b")
        first = _plan_file(tmp_path, "00001-a")
        second = _plan_file(tmp_path, "00002-b")
        handler.handle(_write(first))
        clock.advance(3.0)
        handler.handle(_write(second))
        clock.advance(2.5)
        assert debouncer.run_due() == 1  # only plan one is quiet
        state = PlanFactCheckState(state_dir / "plan-fact-check")
        assert state.read_pending("00001-a") is not None
        assert state.read_pending("00002-b") is None
        clock.advance(3.0)
        assert debouncer.run_due() == 1
        assert state.read_pending("00002-b") is not None

    def test_quiet_period_is_configurable(
        self,
        handler: PlanFactCheckFeedHandler,
        debouncer: Debouncer,
        clock: FakeClock,
        state_dir: Path,
        tmp_path: Path,
    ) -> None:
        _baseline(state_dir, "00001-a")
        handler._quiet_seconds = 30.0
        handler.handle(_write(_plan_file(tmp_path, "00001-a")))
        clock.advance(29.0)
        assert debouncer.run_due() == 0
        clock.advance(1.5)
        assert debouncer.run_due() == 1

    def test_non_plan_write_feeds_nothing(
        self, handler: PlanFactCheckFeedHandler, debouncer: Debouncer, tmp_path: Path
    ) -> None:
        other = tmp_path / "src" / "a.py"
        other.parent.mkdir()
        other.write_text("x")
        handler.handle(_write(other))
        assert debouncer.pending() == {}

    def test_shutdown_cancels_pending(
        self,
        handler: PlanFactCheckFeedHandler,
        debouncer: Debouncer,
        clock: FakeClock,
        state_dir: Path,
        tmp_path: Path,
    ) -> None:
        handler.handle(_write(_plan_file(tmp_path, "00001-a")))
        assert len(debouncer.pending()) == 1
        debouncer.shutdown()
        clock.advance(60.0)
        assert debouncer.run_due() == 0
        assert PlanFactCheckState(state_dir / "plan-fact-check").read_pending("00001-a") is None

    def test_fire_logs_at_info_and_dispatches_nothing(
        self,
        handler: PlanFactCheckFeedHandler,
        debouncer: Debouncer,
        clock: FakeClock,
        state_dir: Path,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        _baseline(state_dir, "00001-a")
        handler.handle(_write(_plan_file(tmp_path, "00001-a")))
        clock.advance(6.0)
        with caplog.at_level(logging.INFO, logger="claude_code_hooks_daemon.utils.plan_fact_check"):
            debouncer.run_due()
        assert any(
            "00001-a" in r.getMessage() and r.levelno == logging.INFO for r in caplog.records
        )
        # No delivery: the only artefact is the pending record in the state dir.
        files = sorted(p.name for p in (state_dir / "plan-fact-check").iterdir())
        assert files == ["00001-a.checked.json", "00001-a.pending.json"]


class TestDelivery:
    """A pending fact-check is delivered to the session on the next hook event."""

    def _fire(
        self,
        handler: PlanFactCheckFeedHandler,
        debouncer: Debouncer,
        clock: FakeClock,
        tmp_path: Path,
        text: str = "x\n",
    ) -> None:
        _baseline(tmp_path / "untracked", "00001-a")
        handler.handle(_write(_plan_file(tmp_path, "00001-a", text=text)))
        clock.advance(6.0)
        debouncer.run_due()

    def test_next_unrelated_event_delivers_the_instruction(
        self,
        handler: PlanFactCheckFeedHandler,
        debouncer: Debouncer,
        clock: FakeClock,
        state_dir: Path,
        tmp_path: Path,
    ) -> None:
        self._fire(handler, debouncer, clock, tmp_path, "a false claim\n")
        unrelated = {"tool_name": "Read", "tool_input": {"file_path": "/x"}}
        assert handler.matches(unrelated) is True
        result = handler.handle(unrelated)
        assert result.decision == Decision.ALLOW
        text = "\n".join(result.context)
        assert "plan-fact-checker" in text
        assert "00001-a" in text
        assert "REFUTED" in text
        diff_file = state_dir / "plan-fact-check" / "00001-a.diff"
        assert str(diff_file) in text
        assert "+a false claim" in diff_file.read_text(encoding="utf-8")

    def test_each_pending_record_is_delivered_once(
        self,
        handler: PlanFactCheckFeedHandler,
        debouncer: Debouncer,
        clock: FakeClock,
        state_dir: Path,
        tmp_path: Path,
    ) -> None:
        self._fire(handler, debouncer, clock, tmp_path)
        unrelated = {"tool_name": "Read", "tool_input": {"file_path": "/x"}}
        assert handler.handle(unrelated).context
        assert not handler.handle(unrelated).context

    def test_delivery_alone_does_not_advance_the_checked_content(
        self,
        handler: PlanFactCheckFeedHandler,
        debouncer: Debouncer,
        clock: FakeClock,
        state_dir: Path,
        tmp_path: Path,
    ) -> None:
        """N359 item 4: only a seen dispatch of the agent marks the content checked."""
        self._fire(handler, debouncer, clock, tmp_path)
        state = PlanFactCheckState(state_dir / "plan-fact-check")
        handler.handle({"tool_name": "Read", "tool_input": {"file_path": "/x"}})
        checked = state.read_checked("00001-a")
        assert checked is not None
        assert checked.files == {}
        assert state.offered_folders() == ["00001-a"]

    @pytest.mark.parametrize("tool_name", ["Task", "Agent"])
    def test_dispatching_the_fact_checker_with_the_diff_confirms_the_check(
        self,
        handler: PlanFactCheckFeedHandler,
        debouncer: Debouncer,
        clock: FakeClock,
        state_dir: Path,
        tmp_path: Path,
        tool_name: str,
    ) -> None:
        self._fire(handler, debouncer, clock, tmp_path)
        state = PlanFactCheckState(state_dir / "plan-fact-check")
        handler.handle({"tool_name": "Read", "tool_input": {"file_path": "/x"}})
        dispatch = {
            "tool_name": tool_name,
            "tool_input": {
                "subagent_type": "plan-fact-checker",
                "prompt": f"check {state.diff_path('00001-a')}",
            },
        }
        assert handler.matches(dispatch) is True
        assert not handler.handle(dispatch).context
        checked = state.read_checked("00001-a")
        assert checked is not None
        assert checked.files == {"PLAN.md": "x\n"}
        assert state.offered_folders() == []
        assert handler.matches({"tool_name": "Read", "tool_input": {}}) is False

    def test_dispatching_another_agent_confirms_nothing(
        self,
        handler: PlanFactCheckFeedHandler,
        debouncer: Debouncer,
        clock: FakeClock,
        state_dir: Path,
        tmp_path: Path,
    ) -> None:
        self._fire(handler, debouncer, clock, tmp_path)
        state = PlanFactCheckState(state_dir / "plan-fact-check")
        handler.handle({"tool_name": "Read", "tool_input": {"file_path": "/x"}})
        other = {
            "tool_name": "Task",
            "tool_input": {"subagent_type": "other", "prompt": str(state.diff_path("00001-a"))},
        }
        handler.handle(other)
        assert state.offered_folders() == ["00001-a"]

    def test_a_subagent_dispatch_confirms_nothing(
        self,
        handler: PlanFactCheckFeedHandler,
        debouncer: Debouncer,
        clock: FakeClock,
        state_dir: Path,
        tmp_path: Path,
    ) -> None:
        self._fire(handler, debouncer, clock, tmp_path)
        state = PlanFactCheckState(state_dir / "plan-fact-check")
        handler.handle({"tool_name": "Read", "tool_input": {"file_path": "/x"}})
        dispatch = {
            "tool_name": "Task",
            "agent_id": "a1b2c3d4e5f6a7b8c",
            "tool_input": {
                "subagent_type": "plan-fact-checker",
                "prompt": str(state.diff_path("00001-a")),
            },
        }
        handler.handle(dispatch)
        assert state.offered_folders() == ["00001-a"]

    def test_an_archived_plan_is_delivered_under_its_existing_path(
        self,
        handler: PlanFactCheckFeedHandler,
        debouncer: Debouncer,
        clock: FakeClock,
        tmp_path: Path,
    ) -> None:
        """N359 item 2."""
        self._fire(handler, debouncer, clock, tmp_path)
        live = tmp_path / "CLAUDE" / "Plan" / "00001-a"
        archived = live.parent / "Completed" / "00001-a"
        archived.parent.mkdir()
        live.rename(archived)
        text = "\n".join(
            handler.handle({"tool_name": "Read", "tool_input": {"file_path": "/x"}}).context
        )
        assert str(archived / "PLAN.md") in text
        assert str(live / "PLAN.md") not in text

    def test_a_plan_edit_event_also_delivers_an_earlier_pending_check(
        self,
        handler: PlanFactCheckFeedHandler,
        debouncer: Debouncer,
        clock: FakeClock,
        state_dir: Path,
        tmp_path: Path,
    ) -> None:
        self._fire(handler, debouncer, clock, tmp_path)
        result = handler.handle(_write(_plan_file(tmp_path, "00001-a", text="more\n")))
        assert result.decision == Decision.ALLOW
        assert result.context
        assert len(debouncer.pending()) == 1  # the new edit still feeds the debouncer

    def test_a_subagent_event_neither_matches_nor_takes_the_owed_check(
        self,
        handler: PlanFactCheckFeedHandler,
        debouncer: Debouncer,
        clock: FakeClock,
        state_dir: Path,
        tmp_path: Path,
    ) -> None:
        """N374: the check is owed to the session that owns the plan, not to a worker."""
        self._fire(handler, debouncer, clock, tmp_path)
        subagent = {
            "tool_name": "Read",
            "tool_input": {"file_path": "/x"},
            "agent_id": "a1b2c3d4e5f6a7b8c",
        }
        assert handler.matches(subagent) is False
        assert not handler.handle(subagent).context
        state = PlanFactCheckState(state_dir / "plan-fact-check")
        assert state.pending_folders() == ["00001-a"]
        assert state.read_checked("00001-a") is not None
        main_thread = {"tool_name": "Read", "tool_input": {"file_path": "/x"}}
        assert handler.handle(main_thread).context

    def test_a_subagent_plan_edit_still_feeds_the_debouncer_but_delivers_nothing(
        self,
        handler: PlanFactCheckFeedHandler,
        debouncer: Debouncer,
        clock: FakeClock,
        state_dir: Path,
        tmp_path: Path,
    ) -> None:
        self._fire(handler, debouncer, clock, tmp_path)
        _baseline(state_dir, "00002-b")
        edit = _write(_plan_file(tmp_path, "00002-b"))
        edit["agent_id"] = "a1b2c3d4e5f6a7b8c"
        assert handler.matches(edit) is True
        assert not handler.handle(edit).context
        assert len(debouncer.pending()) == 1
        assert PlanFactCheckState(state_dir / "plan-fact-check").pending_folders() == ["00001-a"]

    def test_corrupt_pending_record_never_blocks(
        self, handler: PlanFactCheckFeedHandler, state_dir: Path
    ) -> None:
        folder = state_dir / "plan-fact-check"
        folder.mkdir()
        (folder / "00001-a.pending.json").write_text("{nope", encoding="utf-8")
        result = handler.handle({"tool_name": "Read", "tool_input": {"file_path": "/x"}})
        assert result.decision == Decision.ALLOW
        assert not result.context

    def test_no_state_dir_means_nothing_to_deliver(
        self, handler: PlanFactCheckFeedHandler, state_dir: Path
    ) -> None:
        assert handler.matches({"tool_name": "Read", "tool_input": {"file_path": "/x"}}) is False


class TestGuidance:
    def test_silent_handler_has_no_resident_guidance(
        self, handler: PlanFactCheckFeedHandler
    ) -> None:
        assert handler.get_claude_md() is None

    def test_acceptance_tests_declared(self, handler: PlanFactCheckFeedHandler) -> None:
        assert handler.get_acceptance_tests()
