"""owner_wait_stop_guard and auto_continue_stop on ONE `[awaiting-human]` stop (Plan 00636 F1).

The guard (priority 3) denies first, and the chain shows only the first
restrictive reason, so auto_continue_stop's stand-in-cron deny used to be hidden;
the re-stop is a confirmed re-entry that both handlers let through, so the
stand-in cron was never asked for. The guard's refusal now carries the stand-in
requirement whenever auto_continue_stop would have asked for it. Driven through
the real ``HandlerChain`` with both real handlers.
"""

from __future__ import annotations

import json
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from tests.support.autonomy import pin_session_modes

from claude_code_hooks_daemon.config.models import Config, PersistentCronsConfig
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.chain import HandlerChain
from claude_code_hooks_daemon.handlers.stop.auto_continue_stop import AutoContinueStopHandler
from claude_code_hooks_daemon.handlers.stop.owner_wait_stop_guard import (
    OwnerWaitStopGuardHandler,
)
from claude_code_hooks_daemon.utils.owner_wait_bus import BusUnreadable
from claude_code_hooks_daemon.utils.owner_wait_check import (
    BusPost,
    BusSnapshot,
    OwnerThread,
    ThreadKind,
)
from claude_code_hooks_daemon.utils.session_modes import declared_blocked_entry
from claude_code_hooks_daemon.utils.stand_in_cron import stand_in_prompt
from claude_code_hooks_daemon.utils.teamchat_seat import (
    ProbeReason,
    RoleKind,
    SeatContext,
    SeatState,
    SessionSignals,
    TeamSeat,
)

NOW = 1_000_000.0
AWAITING = "STOPPING BECAUSE: [awaiting-human] the owner has to choose between A and B (Q61)."
STAND_IN_HEADLINE = "AWAITING-HUMAN STAND-IN MISSING"
ENABLED = Config(persistent_crons=PersistentCronsConfig(enabled=True))
STAND_IN_CRON = {"id": "s1", "schedule": "15 12 6 10 *", "prompt": stand_in_prompt()}


class _Bus:
    def __init__(self, result: BusSnapshot | BusUnreadable) -> None:
        self.result = result

    def read(self, team: str, signals: SessionSignals) -> BusSnapshot | BusUnreadable:
        return self.result

    def bump_command(self, team: str, thread_ids: Sequence[str]) -> str:
        return f"teamchat bump --team {team} " + " ".join(thread_ids)

    def notify_commands(self, team: str) -> tuple[str, str]:
        return (f"pingbus thread --team {team} Q<n> --ask", "x")

    def flags_readable(self) -> bool:
        return True


class _Guard(OwnerWaitStopGuardHandler):
    def __init__(self, bus: _Bus, config: Config) -> None:
        super().__init__()
        self._bus = bus
        self._clock = lambda: NOW
        self._config_loader = lambda: config

    def _resolve_seats(self, signals: SessionSignals) -> SeatContext:
        seat = TeamSeat(team="alpha", role_kind=RoleKind.DECLARED, role="coordinator")
        return SeatContext(SeatState.RESOLVED, ProbeReason.RESOLVED, (seat,))


class _FaultingGuard(_Guard):
    def _check(self, hook_input: dict[str, Any]) -> Any:
        raise RuntimeError("stale check exploded")


def _stale() -> BusSnapshot:
    return BusSnapshot(
        threads=(OwnerThread("Q61", "$Q61root", ThreadKind.SEAT_QUESTION, started_at=0.0),)
    )


def _bumped() -> BusSnapshot:
    post = BusPost("$p", NOW - 60, True, True, "$Q61root", body="which of A or B to ship?")
    return BusSnapshot(threads=_stale().threads, posts=(post,))


def _assistant(text: str) -> dict[str, Any]:
    return {
        "type": "assistant",
        "message": {"role": "assistant", "content": [{"type": "text", "text": text}]},
    }


def _feedback(reason: str) -> dict[str, Any]:
    return {
        "type": "user",
        "message": {"role": "user", "content": f"Stop hook feedback:\n{reason}"},
    }


@pytest.fixture(autouse=True)
def _registry(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pin_session_modes(monkeypatch, tmp_path / "modes")


def _chain(bus: _Bus, config: Config = ENABLED) -> HandlerChain:
    auto = AutoContinueStopHandler()
    auto._config_loader = lambda: config
    chain = HandlerChain()
    chain.add(_Guard(bus, config))
    chain.add(auto)
    return chain


def _run(
    chain: HandlerChain,
    tmp_path: Path,
    entries: list[dict[str, Any]],
    *,
    active: bool = False,
    session_crons: list[dict[str, Any]] | None = None,
) -> Any:
    path = tmp_path / "transcript.jsonl"
    path.write_text("".join(json.dumps(e) + "\n" for e in entries), encoding="utf-8")
    hook_input: dict[str, Any] = {
        "hook_event_name": "Stop",
        "session_id": "lead",
        "transcript_path": str(path),
        "stop_hook_active": active,
        "teamchat_runtime": "/run/user/1000/teamchat/s1",
        "teamchat_kit": "/opt/teamchat",
        "session_crons": [] if session_crons is None else session_crons,
    }
    with patch(
        "claude_code_hooks_daemon.handlers.stop.auto_continue_stop."
        "ProjectContext.daemon_untracked_dir",
        return_value=tmp_path,
    ):
        return chain.execute(hook_input).result


class TestStandInSurvivesTheOwnerWaitDeny:
    def test_a_repeat_awaiting_stop_asks_for_a_longer_stand_in_delay(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Plan 00639: the guard's own deny backs the stand-in off when no human came between."""
        previous = declared_blocked_entry("lead", entered_at=time.time() - 3 * 3600)
        pin_session_modes(monkeypatch, tmp_path / "modes", previous)
        result = _run(_chain(_Bus(_stale())), tmp_path, [_assistant(AWAITING)])
        assert result.decision is Decision.DENY
        assert STAND_IN_HEADLINE in result.reason
        assert "about 6 hours out" in result.reason

    def test_one_awaiting_stop_carries_both_requirements(self, tmp_path: Path) -> None:
        result = _run(_chain(_Bus(_stale())), tmp_path, [_assistant(AWAITING)])
        assert result.decision is Decision.DENY
        assert "teamchat bump --team alpha Q61" in result.reason
        assert STAND_IN_HEADLINE in result.reason
        assert "[tick:stand-in]" in result.reason

    def test_full_sequence_asks_for_the_stand_in_before_the_stop_is_let_through(
        self, tmp_path: Path
    ) -> None:
        chain = _chain(_Bus(_stale()))
        first = _run(chain, tmp_path, [_assistant(AWAITING)])
        assert STAND_IN_HEADLINE in first.reason
        second = _run(
            chain,
            tmp_path,
            [_assistant(AWAITING), _feedback(first.reason), _assistant(AWAITING)],
            active=True,
            session_crons=[STAND_IN_CRON],
        )
        assert second.decision is Decision.ALLOW

    def test_no_stand_in_text_when_one_is_already_scheduled(self, tmp_path: Path) -> None:
        result = _run(
            _chain(_Bus(_stale())),
            tmp_path,
            [_assistant(AWAITING)],
            session_crons=[STAND_IN_CRON],
        )
        assert result.decision is Decision.DENY
        assert STAND_IN_HEADLINE not in result.reason

    def test_no_stand_in_text_while_persistent_crons_is_off(self, tmp_path: Path) -> None:
        result = _run(_chain(_Bus(_stale()), Config()), tmp_path, [_assistant(AWAITING)])
        assert result.decision is Decision.DENY
        assert STAND_IN_HEADLINE not in result.reason

    def test_the_fault_path_refusal_carries_the_stand_in_too(self, tmp_path: Path) -> None:
        # N1: a fault while checking used to deny with static text only, hiding the stand-in.
        chain = HandlerChain()
        chain.add(_FaultingGuard(_Bus(_stale()), ENABLED))
        auto = AutoContinueStopHandler()
        auto._config_loader = lambda: ENABLED
        chain.add(auto)
        result = _run(chain, tmp_path, [_assistant(AWAITING)])
        assert result.decision is Decision.DENY
        assert "failed before it could confirm" in result.reason
        assert STAND_IN_HEADLINE in result.reason

    def test_a_stand_in_fault_on_the_fault_path_still_denies(self, tmp_path: Path) -> None:
        guard = _FaultingGuard(_Bus(_stale()), ENABLED)

        def _broken() -> Config:
            raise RuntimeError("config gone")

        guard._config_loader = _broken
        chain = HandlerChain()
        chain.add(guard)
        result = _run(chain, tmp_path, [_assistant(AWAITING)])
        assert result.decision is Decision.DENY
        assert "failed before it could confirm" in result.reason

    def test_a_bumped_wait_still_meets_the_stand_in_deny(self, tmp_path: Path) -> None:
        result = _run(_chain(_Bus(_bumped())), tmp_path, [_assistant(AWAITING)])
        assert result.decision is Decision.DENY
        assert STAND_IN_HEADLINE in result.reason


RHETORICAL = (
    "STOPPING BECAUSE: waiting on the owner to choose A or B (Q61). "
    "Want me to build slice 2 next?"
)


class TestOtherStopRefusalsSurviveTheOwnerWaitDeny:
    """N1: the guard's deny must not make the re-stop skip auto_continue_stop's own refusals."""

    def test_the_re_stop_after_the_guard_deny_meets_auto_continue_afresh(
        self, tmp_path: Path
    ) -> None:
        chain = _chain(_Bus(_stale()))
        first = _run(chain, tmp_path, [_assistant(RHETORICAL)])
        assert first.decision is Decision.DENY
        assert "R-STOP-OWNER-WAIT-UNBUMPED" in first.reason
        second = _run(
            chain,
            tmp_path,
            [_assistant(RHETORICAL), _feedback(first.reason), _assistant(RHETORICAL)],
            active=True,
        )
        assert second.decision is Decision.DENY
        assert second.rule == "R-STOP-TAUTOLOGICAL-QUESTION"

    def test_no_third_refusal_in_the_chain(self, tmp_path: Path) -> None:
        chain = _chain(_Bus(_stale()))
        first = _run(chain, tmp_path, [_assistant(RHETORICAL)])
        second = _run(
            chain,
            tmp_path,
            [_assistant(RHETORICAL), _feedback(first.reason), _assistant(RHETORICAL)],
            active=True,
        )
        third = _run(
            chain,
            tmp_path,
            [
                _assistant(RHETORICAL),
                _feedback(first.reason),
                _assistant(RHETORICAL),
                _feedback(second.reason),
                _assistant(RHETORICAL),
            ],
            active=True,
        )
        assert third.decision is Decision.ALLOW

    def test_a_clean_re_stop_after_the_guard_deny_is_allowed(self, tmp_path: Path) -> None:
        text = "STOPPING BECAUSE: waiting on the owner to choose A or B (Q61)."
        chain = _chain(_Bus(_stale()))
        first = _run(chain, tmp_path, [_assistant(text)])
        assert first.decision is Decision.DENY
        second = _run(
            chain,
            tmp_path,
            [_assistant(text), _feedback(first.reason), _assistant(text)],
            active=True,
        )
        assert second.decision is Decision.ALLOW
