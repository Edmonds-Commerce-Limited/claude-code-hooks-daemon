"""Tests for entering and ending a goal-loop block (Plan 00501 Tasks 6.3 and 6.4).

The detector enters GOAL_BLOCKED in act mode, signals the goal clear once and
queues one notice; the block ends on its timer, on a human prompt, on a
repository change, or on an explicit unblock. An unblock never ends a declared
awaiting-human entry: that is refused with a named error.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from claude_code_hooks_daemon.core.goal_loop_block import (
    DeclaredBlockRefusedError,
    UnblockChange,
    UnblockOutcome,
    enter_goal_loop,
    unblock_goal_loop,
)
from claude_code_hooks_daemon.core.session_mode_log import TransitionAction, TransitionLog
from claude_code_hooks_daemon.core.session_mode_registry import (
    ModeNotice,
    NoticeKind,
    SessionModeRegistry,
)
from claude_code_hooks_daemon.utils.session_modes import (
    BlockReason,
    ModeLabel,
    ModeSource,
    declared_blocked_entry,
)

SID = "session-a"
T0 = 1_000_000.0
TTL = 4 * 3600.0
EVIDENCE = "cycles=3 threshold=3 mode=act"
UNBLOCK_EVIDENCE = "cause=explicit-clear (the session-mode CLI or /mode skill)"


class FakeClock:
    """A settable clock for the registry."""

    def __init__(self, now: float = T0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class ClearRecorder:
    """Records each goal-clear signal and answers with ``result``."""

    def __init__(self, result: bool = True) -> None:
        self.result = result
        self.calls: list[str] = []

    def __call__(self, session_id: str) -> bool:
        self.calls.append(session_id)
        return self.result


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def log(tmp_path: Path) -> TransitionLog:
    return TransitionLog(tmp_path / "transitions.jsonl")


@pytest.fixture
def registry(tmp_path: Path, clock: FakeClock, log: TransitionLog) -> SessionModeRegistry:
    reg = SessionModeRegistry(tmp_path / "sidecar", clock=clock, transition_log=log)
    reg.load()
    return reg


def _enter(registry: SessionModeRegistry, clear: ClearRecorder | None = None) -> bool:
    return enter_goal_loop(
        registry,
        SID,
        ttl_seconds=TTL,
        evidence=EVIDENCE,
        clear_goal=clear or ClearRecorder(),
    )


class TestEnter:
    def test_enters_a_detector_goal_blocked_entry_for_the_ttl(
        self, registry: SessionModeRegistry
    ) -> None:
        assert _enter(registry) is True
        (entry,) = registry.active(SID)
        assert entry.label is ModeLabel.GOAL_BLOCKED
        assert entry.reason is BlockReason.GOAL_LOOP
        assert entry.source is ModeSource.DETECTOR
        assert (entry.entered_at, entry.expires_at) == (T0, T0 + TTL)

    def test_logs_the_enter_with_the_evidence(
        self, registry: SessionModeRegistry, log: TransitionLog
    ) -> None:
        _enter(registry)
        (record,) = log.recent(10, session_id=SID)
        assert (record.action, record.label) == (TransitionAction.ENTER, ModeLabel.GOAL_BLOCKED)
        assert record.evidence == EVIDENCE

    def test_signals_the_clear_once_and_queues_one_cleared_notice(
        self, registry: SessionModeRegistry
    ) -> None:
        clear = ClearRecorder()
        _enter(registry, clear)
        assert clear.calls == [SID]
        (notice,) = registry.take_notices(SID)
        assert notice.kind is NoticeKind.GOAL_LOOP_ENTERED
        assert notice.goal_cleared is True
        assert notice.entry.label is ModeLabel.GOAL_BLOCKED
        assert "the ccy supervisor types `/goal clear`" in notice.text()

    def test_a_failed_clear_is_a_warning_and_the_notice_says_so(
        self, registry: SessionModeRegistry, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING):
            assert _enter(registry, ClearRecorder(result=False)) is False
        assert any(
            r.levelno == logging.WARNING and "goal clear" in r.getMessage() for r in caplog.records
        )
        (notice,) = registry.take_notices(SID)
        assert notice.goal_cleared is False
        assert "could not signal the goal clear" in notice.text()
        assert registry.policy(SID).is_blocked is True

    def test_a_reentry_renews_the_ttl_and_signals_again(
        self, registry: SessionModeRegistry, clock: FakeClock
    ) -> None:
        clear = ClearRecorder()
        _enter(registry, clear)
        clock.now = T0 + 100
        _enter(registry, clear)
        (entry,) = registry.active(SID)
        assert entry.expires_at == T0 + 100 + TTL
        assert clear.calls == [SID, SID]


class TestTimerExit:
    def test_the_entry_expires_and_the_log_shows_why(
        self, registry: SessionModeRegistry, clock: FakeClock, log: TransitionLog
    ) -> None:
        _enter(registry)
        registry.take_notices(SID)
        clock.now = T0 + TTL + 1
        assert registry.policy(SID).entries == ()
        actions = [(r.action, r.evidence) for r in log.recent(10, session_id=SID)]
        assert actions[-1] == (TransitionAction.EXPIRE, "its expiry time passed")


class TestUnblock:
    def test_ends_a_live_goal_block_and_logs_the_cause(
        self, registry: SessionModeRegistry, log: TransitionLog
    ) -> None:
        _enter(registry)
        change = unblock_goal_loop(registry, SID, evidence=UNBLOCK_EVIDENCE)
        assert change == UnblockChange(UnblockOutcome.UNBLOCKED, declared_remains=False)
        assert registry.active(SID) == ()
        last = log.recent(10, session_id=SID)[-1]
        assert (last.action, last.label) == (TransitionAction.EXIT, ModeLabel.GOAL_BLOCKED)
        assert last.evidence == UNBLOCK_EVIDENCE
        assert "goal-blocked" in change.line()
        assert "awaiting-human" not in change.line()

    def test_refuses_a_declared_awaiting_human_entry_and_leaves_it(
        self, registry: SessionModeRegistry, caplog: pytest.LogCaptureFixture
    ) -> None:
        registry.enter(declared_blocked_entry(SID, entered_at=T0))
        with caplog.at_level(logging.WARNING), pytest.raises(DeclaredBlockRefusedError) as raised:
            unblock_goal_loop(registry, SID, evidence=UNBLOCK_EVIDENCE)
        message = str(raised.value)
        assert "awaiting-human" in message
        assert "genuine prompt from the human" in message
        assert "Plan 00501 Phase 2" in message
        assert isinstance(raised.value, ValueError)
        assert [e.label for e in registry.active(SID)] == [ModeLabel.AWAITING_HUMAN]
        assert any(r.levelno == logging.WARNING for r in caplog.records)

    def test_with_both_live_ends_only_the_goal_block_and_says_the_declared_remains(
        self, registry: SessionModeRegistry
    ) -> None:
        registry.enter(declared_blocked_entry(SID, entered_at=T0))
        _enter(registry)
        change = unblock_goal_loop(registry, SID, evidence=UNBLOCK_EVIDENCE)
        assert change == UnblockChange(UnblockOutcome.UNBLOCKED, declared_remains=True)
        assert [e.label for e in registry.active(SID)] == [ModeLabel.AWAITING_HUMAN]
        assert "awaiting-human" in change.line()
        assert "still applies" in change.line()

    def test_with_neither_live_is_not_blocked(
        self, registry: SessionModeRegistry, log: TransitionLog
    ) -> None:
        change = unblock_goal_loop(registry, SID, evidence=UNBLOCK_EVIDENCE)
        assert change.outcome is UnblockOutcome.NOT_BLOCKED
        assert change.declared_remains is False
        assert "not goal-blocked" in change.line()
        assert log.recent(10, session_id=SID) == []

    def test_each_outcome_has_a_distinct_line(self) -> None:
        lines = {
            UnblockChange(UnblockOutcome.UNBLOCKED, declared_remains=False).line(),
            UnblockChange(UnblockOutcome.UNBLOCKED, declared_remains=True).line(),
            UnblockChange(UnblockOutcome.NOT_BLOCKED, declared_remains=False).line(),
        }
        assert len(lines) == 3


def test_notice_built_here_is_the_registry_notice_type(registry: SessionModeRegistry) -> None:
    _enter(registry)
    assert all(isinstance(n, ModeNotice) for n in registry.take_notices(SID))
