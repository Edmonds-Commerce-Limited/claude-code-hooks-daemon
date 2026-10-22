"""Tests for the pure session-modes model (Plan 00501 Task 1.1).

The model has no I/O: an enum of modes, frozen entries, the policy a set of
entries composes into (suppressions union, a halting mode beats a driving one),
the status-line precedence, and the tick-drop truth table.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from claude_code_hooks_daemon.utils import session_modes
from claude_code_hooks_daemon.utils.cron_tick import DaemonTick, TickKind
from claude_code_hooks_daemon.utils.session_modes import (
    FOCUS_TTL_SECONDS,
    BlockReason,
    Lifetime,
    ModeLabel,
    ModeSource,
    SessionMode,
    SessionModeEntry,
    SessionPolicy,
    TickAction,
    is_genuine_human_prompt,
)

_SID = "session-a"
_T0 = 1_000_000.0


def _focus(task: str = "fix the parser", *, session_id: str = _SID) -> SessionModeEntry:
    return SessionModeEntry(
        mode=SessionMode.FOCUS,
        session_id=session_id,
        entered_at=_T0,
        expires_at=_T0 + FOCUS_TTL_SECONDS,
        source=ModeSource.HUMAN,
        detail=task,
    )


def _blocked(reason: BlockReason = BlockReason.DECLARED) -> SessionModeEntry:
    return SessionModeEntry(
        mode=SessionMode.BLOCKED,
        session_id=_SID,
        entered_at=_T0,
        expires_at=_T0 + 3600.0,
        source=ModeSource.AGENT if reason is BlockReason.DECLARED else ModeSource.DETECTOR,
        reason=reason,
    )


def _usage_paused() -> SessionModeEntry:
    return SessionModeEntry(
        mode=SessionMode.USAGE_PAUSED,
        session_id=_SID,
        entered_at=_T0,
        expires_at=_T0 + 3600.0,
        source=ModeSource.DAEMON,
    )


def _unattended() -> SessionModeEntry:
    return SessionModeEntry(
        mode=SessionMode.UNATTENDED,
        session_id=_SID,
        entered_at=_T0,
        expires_at=_T0 + 3600.0,
        source=ModeSource.DAEMON,
    )


class TestEntry:
    def test_entries_are_frozen(self) -> None:
        entry = _focus()
        field_name = "detail"
        with pytest.raises(FrozenInstanceError):
            setattr(entry, field_name, "other")

    def test_focus_has_session_lifetime_and_a_twelve_hour_ttl(self) -> None:
        assert _focus().lifetime is Lifetime.SESSION
        assert FOCUS_TTL_SECONDS == 12 * 3600

    def test_blocked_requires_a_reason(self) -> None:
        with pytest.raises(ValueError, match="reason"):
            SessionModeEntry(
                mode=SessionMode.BLOCKED,
                session_id=_SID,
                entered_at=_T0,
                expires_at=_T0 + 1,
                source=ModeSource.AGENT,
            )

    def test_a_reason_on_any_other_mode_is_refused(self) -> None:
        with pytest.raises(ValueError, match="reason"):
            SessionModeEntry(
                mode=SessionMode.FOCUS,
                session_id=_SID,
                entered_at=_T0,
                expires_at=_T0 + 1,
                source=ModeSource.HUMAN,
                detail="x",
                reason=BlockReason.DECLARED,
            )

    def test_focus_requires_its_task(self) -> None:
        with pytest.raises(ValueError, match="task"):
            _focus("   ")

    def test_an_empty_session_id_is_refused(self) -> None:
        with pytest.raises(ValueError, match="session"):
            _focus(session_id=" ")

    def test_expiry_must_follow_entry(self) -> None:
        with pytest.raises(ValueError, match="expires_at"):
            SessionModeEntry(
                mode=SessionMode.FOCUS,
                session_id=_SID,
                entered_at=_T0,
                expires_at=_T0,
                source=ModeSource.HUMAN,
                detail="x",
            )

    def test_is_live_until_its_expiry(self) -> None:
        entry = _focus()
        assert entry.is_live(_T0) is True
        assert entry.is_live(entry.expires_at - 1) is True
        assert entry.is_live(entry.expires_at) is False

    def test_only_focus_is_renewable(self) -> None:
        assert _focus().renewal_ttl == FOCUS_TTL_SECONDS
        assert _blocked().renewal_ttl is None

    def test_renewed_moves_the_expiry_from_now(self) -> None:
        renewed = _focus().renewed(_T0 + 100.0)
        assert renewed.expires_at == _T0 + 100.0 + FOCUS_TTL_SECONDS
        assert renewed.entered_at == _T0

    def test_renewing_a_mode_with_no_ttl_is_an_error(self) -> None:
        with pytest.raises(ValueError, match="renew"):
            _blocked().renewed(_T0 + 1)

    def test_registry_owned_modes(self) -> None:
        assert SessionMode.FOCUS.registry_owned is True
        assert SessionMode.BLOCKED.registry_owned is True
        assert SessionMode.USAGE_PAUSED.registry_owned is False
        assert SessionMode.UNATTENDED.registry_owned is False


class TestLabels:
    @pytest.mark.parametrize(
        ("entry", "label"),
        [
            (_focus(), ModeLabel.FOCUS),
            (_blocked(BlockReason.DECLARED), ModeLabel.AWAITING_HUMAN),
            (_blocked(BlockReason.GOAL_LOOP), ModeLabel.GOAL_BLOCKED),
            (_usage_paused(), ModeLabel.USAGE_PAUSED),
            (_unattended(), ModeLabel.UNATTENDED),
        ],
    )
    def test_each_entry_has_its_label(self, entry: SessionModeEntry, label: ModeLabel) -> None:
        assert entry.label is label

    def test_precedence_order(self) -> None:
        assert list(ModeLabel.by_precedence()) == [
            ModeLabel.USAGE_PAUSED,
            ModeLabel.GOAL_BLOCKED,
            ModeLabel.AWAITING_HUMAN,
            ModeLabel.FOCUS,
            ModeLabel.UNATTENDED,
        ]


class TestPolicy:
    def test_no_modes_drives_work_and_shows_nothing(self) -> None:
        policy = SessionPolicy.from_entries(())
        assert policy.drives_work is True
        assert policy.unattended_block_applies is True
        assert policy.badge() == ""
        assert policy.labels == ()
        assert policy.focus_task is None

    @pytest.mark.parametrize("entry", [_focus(), _blocked(), _usage_paused()])
    def test_each_work_halting_mode_stops_driving_work(self, entry: SessionModeEntry) -> None:
        assert SessionPolicy.from_entries((entry,)).drives_work is False

    def test_unattended_alone_still_drives_work(self) -> None:
        assert SessionPolicy.from_entries((_unattended(),)).drives_work is True

    def test_focus_keeps_the_unattended_stop_block(self) -> None:
        assert SessionPolicy.from_entries((_focus(),)).unattended_block_applies is True

    @pytest.mark.parametrize("entry", [_blocked(), _usage_paused()])
    def test_a_halting_mode_beats_the_unattended_stop_block(self, entry: SessionModeEntry) -> None:
        policy = SessionPolicy.from_entries((entry, _unattended()))
        assert policy.unattended_block_applies is False

    def test_badge_is_the_top_label_plus_a_count(self) -> None:
        policy = SessionPolicy.from_entries((_focus(), _unattended(), _blocked()))
        assert policy.labels == (
            ModeLabel.AWAITING_HUMAN,
            ModeLabel.FOCUS,
            ModeLabel.UNATTENDED,
        )
        assert policy.badge() == "awaiting-human +2"

    def test_badge_of_one_mode_has_no_count(self) -> None:
        assert SessionPolicy.from_entries((_focus(),)).badge() == "focus"

    def test_focus_task_is_exposed(self) -> None:
        assert SessionPolicy.from_entries((_focus("ship 1.3"),)).focus_task == "ship 1.3"
        assert SessionPolicy.from_entries((_blocked(),)).focus_task is None

    def test_entries_of_two_sessions_are_refused(self) -> None:
        with pytest.raises(ValueError, match="session"):
            SessionPolicy.from_entries((_focus(), _focus(session_id="session-b")))

    def test_two_entries_with_one_label_are_refused(self) -> None:
        with pytest.raises(ValueError, match="once"):
            SessionPolicy.from_entries((_focus(), _focus("other")))

    def test_explain_clause_names_each_mode(self) -> None:
        clause = SessionPolicy.from_entries((_focus("ship 1.3"), _blocked())).explain_clause()
        assert "awaiting-human since" in clause
        assert "focus mode on 'ship 1.3'" in clause

    def test_explain_clause_of_goal_blocked_and_usage_paused(self) -> None:
        clause = SessionPolicy.from_entries(
            (_blocked(BlockReason.GOAL_LOOP), _usage_paused())
        ).explain_clause()
        assert clause.index("usage-paused") < clause.index("goal-blocked")

    def test_explain_clause_is_empty_without_a_halting_mode(self) -> None:
        assert SessionPolicy.from_entries((_unattended(),)).explain_clause() == ""

    def test_exit_clause_names_how_focus_ends(self) -> None:
        clause = SessionPolicy.from_entries((_focus(),)).exit_clause()
        assert "`hooks-daemon focus off`" in clause

    def test_exit_clause_names_how_a_blocked_mode_ends(self) -> None:
        for reason in BlockReason:
            clause = SessionPolicy.from_entries((_blocked(reason),)).exit_clause()
            assert "the next message the human types" in clause

    def test_exit_clause_names_how_usage_pause_ends(self) -> None:
        clause = SessionPolicy.from_entries((_usage_paused(),)).exit_clause()
        assert "usage window resets" in clause

    def test_exit_clause_states_a_shared_exit_once(self) -> None:
        both = SessionPolicy.from_entries(
            (_blocked(BlockReason.GOAL_LOOP), _blocked(BlockReason.DECLARED))
        ).exit_clause()
        assert both.count("the next message the human types") == 1

    def test_exit_clause_covers_every_halting_mode_in_precedence_order(self) -> None:
        clause = SessionPolicy.from_entries((_focus(), _usage_paused())).exit_clause()
        assert clause.index("usage window") < clause.index("focus off")

    def test_exit_clause_is_empty_without_a_halting_mode(self) -> None:
        assert SessionPolicy.from_entries((_unattended(),)).exit_clause() == ""
        assert SessionPolicy.from_entries(()).exit_clause() == ""


_FAILSAFE = DaemonTick(TickKind.FAILSAFE)
_WATCHDOG = DaemonTick(TickKind.WATCHDOG)
_RESUME = DaemonTick(TickKind.USAGE_RESUME)
_STAND_IN = DaemonTick(TickKind.STAND_IN)
_JOB = DaemonTick(TickKind.DECLARED, "issue-sdlc")

_D = TickAction.DELIVER
_X = TickAction.DROP
_T = TickAction.THIN
_F = TickAction.DELIVER_NAMING_FOCUS


class TestTickTruthTable:
    """Rows: the mode set. Columns: the tick, and the two facts the suppressor knows."""

    @pytest.mark.parametrize(
        ("entries", "tick", "runs_while_blocked", "owed", "expected"),
        [
            # No mode: the mode never intervenes; cadence rules stay the suppressor's.
            ((), _FAILSAFE, False, False, _D),
            ((), _FAILSAFE, False, True, _D),
            ((), _JOB, False, None, _D),
            ((), _WATCHDOG, False, None, _D),
            ((), _STAND_IN, False, None, _D),
            ((), _RESUME, False, None, _D),
            # Focus: declared jobs dropped (even runs_while_awaiting_human), the
            # failsafe delivered naming the task, the rest delivered.
            ((_focus(),), _JOB, False, None, _X),
            ((_focus(),), _JOB, True, None, _X),
            ((_focus(),), _FAILSAFE, False, True, _F),
            ((_focus(),), _FAILSAFE, False, False, _F),
            ((_focus(),), _WATCHDOG, False, None, _D),
            ((_focus(),), _STAND_IN, False, None, _D),
            ((_focus(),), _RESUME, False, None, _D),
            # BLOCKED (either reason): today's marker rows.
            ((_blocked(),), _JOB, False, None, _X),
            ((_blocked(),), _JOB, True, None, _D),
            ((_blocked(),), _FAILSAFE, False, True, _T),
            ((_blocked(),), _FAILSAFE, False, False, _X),
            ((_blocked(),), _FAILSAFE, False, None, _X),
            ((_blocked(BlockReason.GOAL_LOOP),), _FAILSAFE, False, None, _X),
            ((_blocked(BlockReason.GOAL_LOOP),), _JOB, False, None, _X),
            ((_blocked(),), _WATCHDOG, False, None, _D),
            ((_blocked(),), _STAND_IN, False, None, _D),
            ((_blocked(),), _RESUME, False, None, _D),
            # Usage-paused: only the resume tick passes.
            ((_usage_paused(),), _RESUME, False, None, _D),
            ((_usage_paused(),), _FAILSAFE, False, True, _X),
            ((_usage_paused(),), _WATCHDOG, False, None, _X),
            ((_usage_paused(),), _STAND_IN, False, None, _X),
            ((_usage_paused(),), _JOB, True, None, _X),
            # Unattended changes no tick.
            ((_unattended(),), _JOB, False, None, _D),
            ((_unattended(),), _FAILSAFE, False, False, _D),
            # Composition: the most suppressive action wins.
            ((_focus(), _blocked()), _FAILSAFE, False, True, _T),
            ((_focus(), _blocked()), _FAILSAFE, False, False, _X),
            ((_focus(), _blocked()), _JOB, True, None, _X),
            ((_focus(), _usage_paused()), _FAILSAFE, False, True, _X),
            ((_focus(), _unattended()), _FAILSAFE, False, True, _F),
        ],
    )
    def test_tick_action(
        self,
        entries: tuple[SessionModeEntry, ...],
        tick: DaemonTick,
        runs_while_blocked: bool,
        owed: bool | None,
        expected: TickAction,
    ) -> None:
        policy = SessionPolicy.from_entries(entries)
        assert policy.tick_action(tick, runs_while_blocked=runs_while_blocked, work_owed=owed) is (
            expected
        )

    def test_actions_are_ordered_by_suppression(self) -> None:
        assert _D.rank < _F.rank < _T.rank < _X.rank


class TestGenuineHumanPrompt:
    @pytest.mark.parametrize(
        "prompt",
        ["please keep going", "hooks-daemon focus fix the parser"],
    )
    def test_a_typed_prompt_is_genuine(self, prompt: str) -> None:
        assert is_genuine_human_prompt(prompt) is True

    @pytest.mark.parametrize(
        "prompt",
        [
            "",
            "   ",
            "[tick:failsafe]\nFAILSAFE RECOVERY CHECK",
            "[tick:job:issue-sdlc]\nwork the queue",
            "🤖 [ccy-supervisor] continue",
            "<task-notification>done</task-notification>",
            None,
            42,
        ],
    )
    def test_machine_traffic_is_not(self, prompt: object) -> None:
        assert is_genuine_human_prompt(prompt) is False


class TestDeclaredBlocked:
    """The one 24 h expiry and factory every BLOCKED writer shares (Task 2.2)."""

    def test_ttl_is_a_day(self) -> None:
        assert session_modes.DECLARED_BLOCKED_TTL_SECONDS == 24 * 3600

    def test_blocked_labels_are_the_blocked_family(self) -> None:
        assert session_modes.BLOCKED_LABELS == frozenset(
            {ModeLabel.AWAITING_HUMAN, ModeLabel.GOAL_BLOCKED}
        )

    def test_factory_builds_a_declared_agent_session_entry(self) -> None:
        entry = session_modes.declared_blocked_entry(_SID, entered_at=_T0)
        assert entry.mode is SessionMode.BLOCKED
        assert entry.reason is BlockReason.DECLARED
        assert entry.source is ModeSource.AGENT
        assert entry.lifetime is Lifetime.SESSION
        assert entry.label is ModeLabel.AWAITING_HUMAN
        assert entry.entered_at == _T0
        assert entry.expires_at == _T0 + session_modes.DECLARED_BLOCKED_TTL_SECONDS

    def test_policy_is_blocked_for_either_blocked_label(self) -> None:
        declared = session_modes.declared_blocked_entry(_SID, entered_at=_T0)
        goal = SessionModeEntry(
            mode=SessionMode.BLOCKED,
            session_id=_SID,
            entered_at=_T0,
            expires_at=_T0 + 60,
            source=ModeSource.DETECTOR,
            reason=BlockReason.GOAL_LOOP,
        )
        assert SessionPolicy.from_entries([declared]).is_blocked is True
        assert SessionPolicy.from_entries([goal]).is_blocked is True

    def test_policy_is_not_blocked_under_focus_or_nothing(self) -> None:
        assert SessionPolicy.from_entries([]).is_blocked is False
        assert SessionPolicy.from_entries([_focus()]).is_blocked is False


class TestDisplayedPolicy:
    """Plan 00501 Task 4.1: the badge composes registry, usage-paused and unattended."""

    def test_registry_entries_alone(self) -> None:
        policy = session_modes.displayed_policy(
            _SID, [_focus()], usage_pause=None, unattended=False, now=_T0
        )
        assert policy.labels == (ModeLabel.FOCUS,)

    def test_usage_pause_and_unattended_are_shown_in_precedence_order(self) -> None:
        policy = session_modes.displayed_policy(
            _SID,
            [_focus()],
            usage_pause=session_modes.UsagePauseView(paused_at=_T0, until=_T0 + 9, reason="5h"),
            unattended=True,
            now=_T0 + 1,
        )
        assert policy.labels == (ModeLabel.USAGE_PAUSED, ModeLabel.FOCUS, ModeLabel.UNATTENDED)
        assert policy.badge() == "usage-paused +2"
        assert policy.entries[0].detail == "5h"
        assert policy.entries[0].mode is SessionMode.USAGE_PAUSED

    def test_unattended_alone_shows_but_does_not_halt_work(self) -> None:
        policy = session_modes.displayed_policy(_SID, [], usage_pause=None, unattended=True, now=1.0)
        assert policy.badge() == "unattended"
        assert policy.drives_work is True
