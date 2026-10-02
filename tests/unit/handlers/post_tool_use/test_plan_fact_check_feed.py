"""Tests for PlanFactCheckFeedHandler (Plan 00480 Task 4.1, Task 4.2 partial).

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
    return target


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


class TestDebouncedFeed:
    def test_burst_of_edits_to_one_plan_fires_exactly_once(
        self,
        handler: PlanFactCheckFeedHandler,
        debouncer: Debouncer,
        clock: FakeClock,
        state_dir: Path,
        tmp_path: Path,
    ) -> None:
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
        handler.handle(_write(_plan_file(tmp_path, "00001-a")))
        clock.advance(6.0)
        with caplog.at_level(logging.INFO, logger="claude_code_hooks_daemon.utils.plan_fact_check"):
            debouncer.run_due()
        assert any(
            "00001-a" in r.getMessage() and r.levelno == logging.INFO for r in caplog.records
        )
        # No delivery: the only artefact is the pending record in the state dir.
        files = sorted(p.name for p in (state_dir / "plan-fact-check").iterdir())
        assert files == ["00001-a.pending.json"]


class TestGuidance:
    def test_silent_handler_has_no_resident_guidance(
        self, handler: PlanFactCheckFeedHandler
    ) -> None:
        assert handler.get_claude_md() is None

    def test_acceptance_tests_declared(self, handler: PlanFactCheckFeedHandler) -> None:
        assert handler.get_acceptance_tests()
