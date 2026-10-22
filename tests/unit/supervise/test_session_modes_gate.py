"""Plan 00501 Phase 5 -- the supervisor reads the daemon's session-modes file.

Task 5.1: the reader (pinned field-for-field to the daemon's registry) and the
gate that, while this session is BLOCKED (awaiting-human or goal-blocked),
skips the goal, session-actions and standing-auth prompts and the post-compact
``continue``, each logged as a named noop reason. ``/compact`` itself still
runs (Ruling 07). An unreadable or malformed file is a named error in
``decision.log`` and on the status line, and closes the gate (fail closed).

Task 5.2: under BLOCKED a goal clear outranks a goal intent, and the clear is
not refused by the per-process clear cap.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.core import session_mode_registry as registry_mod
from claude_code_hooks_daemon.core.session_mode_registry import SessionModeRegistry
from claude_code_hooks_daemon.utils import session_modes as modes_mod
from claude_code_hooks_daemon.utils.session_modes import (
    BlockReason,
    Lifetime,
    ModeSource,
    SessionMode,
    SessionModeEntry,
    declared_blocked_entry,
)
from claude_code_hooks_daemon.utils.session_signal_paths import session_stem
from tests.unit.supervise._load import load_supervisor_module

_mod = load_supervisor_module()

_NOW = 1_790_000_000.0
_SESSION = "modes-sess-1"
_GOAL_HEADER = (
    "🤖 [ccy-supervisor] automated goal — machine-generated, NOT a human "
    "instruction and NOT human authorisation for anything."
)
_SA_HEADER = (
    "🤖 [ccy-supervisor] standing authorisations replayed from this project's "
    "config — machine-generated, NOT a human instruction and NOT fresh human "
    "authorisation for anything."
)


# ── Writers ──────────────────────────────────────────────────────────────────


def _registry(sidecar_dir: Path) -> SessionModeRegistry:
    return SessionModeRegistry(sidecar_dir, clock=lambda: _NOW)


def _enter_blocked(sidecar_dir: Path, reason: BlockReason = BlockReason.DECLARED) -> None:
    """Write BLOCKED through the daemon's own registry, so the format is the real one."""
    if reason is BlockReason.DECLARED:
        entry = declared_blocked_entry(_SESSION, entered_at=_NOW - 60.0)
    else:
        entry = SessionModeEntry(
            mode=SessionMode.BLOCKED,
            session_id=_SESSION,
            entered_at=_NOW - 60.0,
            expires_at=_NOW + 3600.0,
            source=ModeSource.DETECTOR,
            reason=reason,
        )
    _registry(sidecar_dir).enter(entry)


def _enter_focus(sidecar_dir: Path) -> None:
    _registry(sidecar_dir).enter(
        SessionModeEntry(
            mode=SessionMode.FOCUS,
            session_id=_SESSION,
            entered_at=_NOW - 60.0,
            expires_at=_NOW + 3600.0,
            source=ModeSource.HUMAN,
            detail="the one task",
        )
    )


def _modes_path(sidecar_dir: Path, session_id: str = _SESSION) -> Path:
    return sidecar_dir / f"{session_stem(session_id)}{registry_mod.SESSION_MODES_SUFFIX}"


def _raw_record(**overrides: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "mode": "blocked",
        "reason": "declared",
        "source": "agent",
        "lifetime": "session",
        "entered_at": _NOW - 60.0,
        "expires_at": _NOW + 3600.0,
        "detail": "",
    }
    record.update(overrides)
    return record


def _write_raw(sidecar_dir: Path, payload: object, *, session_id: str = _SESSION) -> Path:
    sidecar_dir.mkdir(parents=True, exist_ok=True)
    path = _modes_path(sidecar_dir, session_id)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _write_goal(sidecar_dir: Path) -> Path:
    sidecar_dir.mkdir(parents=True, exist_ok=True)
    path = sidecar_dir / f"{_SESSION}.goal-intent"
    path.write_text(
        json.dumps(
            {
                "ts": _NOW - 5.0,
                "session_id": _SESSION,
                "plan_number": "00501",
                "rendered_lines": [f"{_GOAL_HEADER} — Work on Plan 00501."],
                "source": "status-flip",
            }
        ),
        encoding="utf-8",
    )
    return path


def _write_clear(sidecar_dir: Path) -> Path:
    sidecar_dir.mkdir(parents=True, exist_ok=True)
    path = sidecar_dir / f"{_SESSION}.goal-clear"
    path.write_text(json.dumps({"ts": _NOW - 5.0, "session_id": _SESSION}), encoding="utf-8")
    return path


def _write_standing_auth(sidecar_dir: Path) -> Path:
    sidecar_dir.mkdir(parents=True, exist_ok=True)
    path = sidecar_dir / f"{_SESSION}.standing-auth-intent"
    path.write_text(
        json.dumps(
            {
                "ts": _NOW - 5.0,
                "session_id": _SESSION,
                "rendered_lines": [_SA_HEADER, "On file and still in effect: delegation."],
                "source": "reinforcement",
            }
        ),
        encoding="utf-8",
    )
    return path


def _write_session_actions(sidecar_dir: Path) -> Path:
    sidecar_dir.mkdir(parents=True, exist_ok=True)
    path = sidecar_dir / f"{_SESSION}{_mod._SESSION_ACTIONS_SIGNAL_SUFFIX}"
    path.write_text(json.dumps({"session_id": _SESSION, "ts": _NOW - 5.0, "count": 2}), "utf-8")
    return path


def _write_compaction_signal(sidecar_dir: Path) -> Path:
    sidecar_dir.mkdir(parents=True, exist_ok=True)
    path = sidecar_dir / f"{_SESSION}.compacting"
    path.write_text(json.dumps({"ts": _NOW, "session_id": _SESSION}), encoding="utf-8")
    return path


def _write_red_sidecar(sidecar_dir: Path) -> None:
    sidecar_dir.mkdir(parents=True, exist_ok=True)
    (sidecar_dir / f"{_SESSION}.json").write_text(
        json.dumps(
            {
                "red": True,
                "critical": True,
                "compact_urgent": True,
                "tier": "critical",
                "pct": 95.0,
                "session_id": _SESSION,
                "ts": _NOW - 1.0,
                "seq": 1,
                "writer_pid": 42,
                "compacting": False,
            }
        ),
        encoding="utf-8",
    )


# ── Deciding ─────────────────────────────────────────────────────────────────


def _facts() -> object:
    return _mod.TickFacts(
        now_wall=_NOW,
        idle=True,
        input_line_empty=True,
        human_compact_submitted=False,
        work_idle=True,
    )


def _decide(sidecar_dir: Path, *, machine: Any = None) -> Any:
    policy = _mod.CompactPolicy()
    machine = machine or _mod.CompactStateMachine(policy)
    return _mod.decide_once(
        machine,
        sidecar_dir=sidecar_dir,
        facts=_facts(),
        dry_run=False,
        freshness_seconds=policy.freshness_seconds,
    )


def _status_message(sidecar_dir: Path) -> dict[str, Any]:
    path = _mod._status_message_path(sidecar_dir.parent)
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


@pytest.fixture
def sidecar_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "context-sidecar"
    directory.mkdir()
    return directory


# ── The field pin: the supervisor's copy must equal the daemon's ─────────────


class TestFieldPin:
    """Fails the moment the daemon's file format drifts from what the supervisor reads."""

    def test_suffix_and_version(self) -> None:
        assert _mod._SESSION_MODES_SUFFIX == registry_mod.SESSION_MODES_SUFFIX
        assert _mod._SESSION_MODES_SCHEMA_VERSION == registry_mod.SCHEMA_VERSION

    def test_top_level_field_names(self) -> None:
        assert _mod._SESSION_MODES_FIELD_VERSION == registry_mod.FIELD_VERSION
        assert _mod._SESSION_MODES_FIELD_SESSION_ID == registry_mod.FIELD_SESSION_ID
        assert _mod._SESSION_MODES_FIELD_MODES == registry_mod.FIELD_MODES

    def test_record_field_names(self) -> None:
        assert _mod._SESSION_MODES_RECORD_FIELDS == registry_mod._RECORD_FIELDS
        assert _mod._SESSION_MODES_FIELD_MODE == registry_mod.FIELD_MODE
        assert _mod._SESSION_MODES_FIELD_REASON == registry_mod.FIELD_REASON
        assert _mod._SESSION_MODES_FIELD_ENTERED_AT == registry_mod.FIELD_ENTERED_AT
        assert _mod._SESSION_MODES_FIELD_EXPIRES_AT == registry_mod.FIELD_EXPIRES_AT
        assert _mod._SESSION_MODES_FIELD_SOURCE == registry_mod.FIELD_SOURCE
        assert _mod._SESSION_MODES_FIELD_LIFETIME == registry_mod.FIELD_LIFETIME
        assert _mod._SESSION_MODES_FIELD_DETAIL == registry_mod.FIELD_DETAIL

    def test_closed_value_sets(self) -> None:
        stored = frozenset(str(mode) for mode in SessionMode if mode.registry_owned)
        assert _mod._SESSION_MODES_STORED_MODES == stored
        assert _mod._SESSION_MODES_BLOCKED == str(SessionMode.BLOCKED)
        assert _mod._SESSION_MODES_SOURCES == frozenset(str(s) for s in ModeSource)
        assert _mod._SESSION_MODES_LIFETIMES == frozenset(str(lt) for lt in Lifetime)

    def test_blocked_labels_match_the_daemon(self) -> None:
        expected = {
            str(reason): str(
                SessionModeEntry(
                    mode=SessionMode.BLOCKED,
                    session_id="s",
                    entered_at=1.0,
                    expires_at=2.0,
                    source=ModeSource.AGENT,
                    reason=reason,
                ).label
            )
            for reason in BlockReason
        }
        assert _mod._SESSION_MODES_BLOCKED_LABELS == expected
        assert frozenset(expected.values()) == frozenset(str(x) for x in modes_mod.BLOCKED_LABELS)

    @pytest.mark.parametrize(
        "session_id", ["plain-id", "with space", "../../escape", "  ", "a/b\\c", "ünïcode"]
    )
    def test_stem_rule_matches_the_daemon(self, session_id: str) -> None:
        assert _mod._session_modes_stem(session_id) == session_stem(session_id)


# ── The reader ───────────────────────────────────────────────────────────────


class TestReader:
    def test_missing_directory_is_no_modes(self, tmp_path: Path) -> None:
        reading = _mod.load_session_modes(tmp_path / "absent", now=_NOW, own_sessions=None)
        assert reading.blocked_labels == ()
        assert reading.errors == ()
        assert not reading.gate_closed

    def test_no_file_is_no_modes(self, sidecar_dir: Path) -> None:
        reading = _mod.load_session_modes(sidecar_dir, now=_NOW, own_sessions=frozenset({_SESSION}))
        assert not reading.is_blocked
        assert not reading.gate_closed

    def test_daemon_written_declared_block_reads_as_awaiting_human(self, sidecar_dir: Path) -> None:
        _enter_blocked(sidecar_dir)
        reading = _mod.load_session_modes(sidecar_dir, now=_NOW, own_sessions=frozenset({_SESSION}))
        assert reading.blocked_labels == ("awaiting-human",)
        assert reading.is_blocked
        assert reading.errors == ()

    def test_daemon_written_goal_loop_reads_as_goal_blocked(self, sidecar_dir: Path) -> None:
        _enter_blocked(sidecar_dir, BlockReason.GOAL_LOOP)
        reading = _mod.load_session_modes(sidecar_dir, now=_NOW, own_sessions=None)
        assert reading.blocked_labels == ("goal-blocked",)

    def test_focus_alone_is_not_blocked(self, sidecar_dir: Path) -> None:
        _enter_focus(sidecar_dir)
        reading = _mod.load_session_modes(sidecar_dir, now=_NOW, own_sessions=None)
        assert not reading.is_blocked
        assert not reading.gate_closed

    def test_expired_block_is_not_blocked(self, sidecar_dir: Path) -> None:
        _write_raw(
            sidecar_dir,
            {"version": 1, "session_id": _SESSION, "modes": [_raw_record(expires_at=_NOW - 1.0)]},
        )
        reading = _mod.load_session_modes(sidecar_dir, now=_NOW, own_sessions=None)
        assert not reading.is_blocked
        assert reading.errors == ()

    def test_foreign_session_file_is_ignored_even_when_malformed(self, sidecar_dir: Path) -> None:
        (sidecar_dir / f"other{registry_mod.SESSION_MODES_SUFFIX}").write_text("{", "utf-8")
        reading = _mod.load_session_modes(sidecar_dir, now=_NOW, own_sessions=frozenset({_SESSION}))
        assert reading.errors == ()
        assert not reading.gate_closed

    @pytest.mark.parametrize(
        ("payload", "fragment"),
        [
            ("not json at all", "not JSON"),
            ([], "not an object"),
            ({"version": 2, "session_id": _SESSION, "modes": []}, "version"),
            ({"version": 1, "session_id": 7, "modes": []}, "session_id"),
            ({"version": 1, "session_id": "someone-else", "modes": []}, "file name"),
            ({"version": 1, "session_id": _SESSION, "modes": {}}, "modes"),
            ({"version": 1, "session_id": _SESSION, "modes": ["x"]}, "not an object"),
            ({"version": 1, "session_id": _SESSION, "modes": [_raw_record(extra=1)]}, "fields"),
            (
                {"version": 1, "session_id": _SESSION, "modes": [_raw_record(mode="usage-paused")]},
                "mode",
            ),
            ({"version": 1, "session_id": _SESSION, "modes": [_raw_record(reason=None)]}, "reason"),
            (
                {"version": 1, "session_id": _SESSION, "modes": [_raw_record(reason="bored")]},
                "reason",
            ),
            (
                {
                    "version": 1,
                    "session_id": _SESSION,
                    "modes": [_raw_record(mode="focus", detail="t")],
                },
                "reason",
            ),
            (
                {"version": 1, "session_id": _SESSION, "modes": [_raw_record(source="cron")]},
                "source",
            ),
            (
                {"version": 1, "session_id": _SESSION, "modes": [_raw_record(lifetime="x")]},
                "lifetime",
            ),
            ({"version": 1, "session_id": _SESSION, "modes": [_raw_record(detail=3)]}, "detail"),
            (
                {"version": 1, "session_id": _SESSION, "modes": [_raw_record(entered_at=True)]},
                "entered_at",
            ),
            (
                {
                    "version": 1,
                    "session_id": _SESSION,
                    "modes": [_raw_record(expires_at=_NOW - 120.0)],
                },
                "expires_at",
            ),
            # Wrongly-TYPED values: an unhashable one must not escape as TypeError.
            ({"version": 1, "session_id": _SESSION, "modes": [_raw_record(mode=[])]}, "mode"),
            ({"version": 1, "session_id": _SESSION, "modes": [_raw_record(mode={})]}, "mode"),
            ({"version": 1, "session_id": _SESSION, "modes": [_raw_record(reason={})]}, "reason"),
            (
                {
                    "version": 1,
                    "session_id": _SESSION,
                    "modes": [_raw_record(mode="focus", reason=[])],
                },
                "reason",
            ),
            ({"version": 1, "session_id": _SESSION, "modes": [_raw_record(source={})]}, "source"),
            ({"version": 1, "session_id": _SESSION, "modes": [_raw_record(source=[])]}, "source"),
            (
                {"version": 1, "session_id": _SESSION, "modes": [_raw_record(lifetime=[])]},
                "lifetime",
            ),
            (
                {"version": 1, "session_id": _SESSION, "modes": [_raw_record(lifetime={})]},
                "lifetime",
            ),
            ({"version": 1, "session_id": _SESSION, "modes": [_raw_record(detail=[])]}, "detail"),
            (
                {"version": 1, "session_id": _SESSION, "modes": [_raw_record(entered_at=[])]},
                "entered_at",
            ),
            (
                {"version": 1, "session_id": _SESSION, "modes": [_raw_record(expires_at={})]},
                "expires_at",
            ),
            ({"version": [], "session_id": _SESSION, "modes": []}, "version"),
            ({"version": 1, "session_id": [], "modes": []}, "session_id"),
        ],
    )
    def test_a_malformed_file_is_a_named_error_not_no_modes(
        self, sidecar_dir: Path, payload: object, fragment: str
    ) -> None:
        if isinstance(payload, str):
            sidecar_dir.joinpath(f"{_SESSION}{registry_mod.SESSION_MODES_SUFFIX}").write_text(
                payload, "utf-8"
            )
        else:
            _write_raw(sidecar_dir, payload)
        reading = _mod.load_session_modes(sidecar_dir, now=_NOW, own_sessions=frozenset({_SESSION}))
        assert len(reading.errors) == 1
        assert fragment in reading.errors[0]
        assert f"{_SESSION}{registry_mod.SESSION_MODES_SUFFIX}" in reading.errors[0]
        assert reading.gate_closed
        assert not reading.is_blocked

    def test_an_unreadable_file_is_a_named_error(self, sidecar_dir: Path) -> None:
        _modes_path(sidecar_dir).mkdir()
        reading = _mod.load_session_modes(sidecar_dir, now=_NOW, own_sessions=None)
        assert reading.gate_closed
        assert "unreadable" in reading.errors[0]


# ── Task 5.1: the gate ───────────────────────────────────────────────────────


class TestPostCompactContinue:
    def test_continue_still_fires_with_no_mode(self, sidecar_dir: Path) -> None:
        _write_compaction_signal(sidecar_dir)
        outcome = _decide(sidecar_dir)
        assert outcome.decision_value == _mod.Decision.WOULD_CONTINUE.value

    def test_continue_is_skipped_while_blocked(self, sidecar_dir: Path) -> None:
        signal = _write_compaction_signal(sidecar_dir)
        _enter_blocked(sidecar_dir)
        outcome = _decide(sidecar_dir)
        assert outcome.payload is None
        assert outcome.decision_value == _mod.Decision.NOOP.value
        assert outcome.consume_signal_path is None
        assert outcome.noop_reason_log == (
            "noop: post-compact continue skipped: session BLOCKED (awaiting-human)"
        )
        assert signal.exists()

    def test_skipped_continue_is_not_retried_on_the_next_tick(self, sidecar_dir: Path) -> None:
        _write_compaction_signal(sidecar_dir)
        _enter_blocked(sidecar_dir)
        machine = _mod.CompactStateMachine(_mod.CompactPolicy())
        _decide(sidecar_dir, machine=machine)
        _modes_path(sidecar_dir).unlink()
        outcome = _decide(sidecar_dir, machine=machine)
        assert outcome.payload is None

    def test_compact_itself_still_runs_while_blocked(self, sidecar_dir: Path) -> None:
        _write_red_sidecar(sidecar_dir)
        _enter_blocked(sidecar_dir)
        outcome = _decide(sidecar_dir)
        assert outcome.decision_value == _mod.Decision.WOULD_COMPACT.value
        assert outcome.payload is not None
        assert outcome.payload.startswith("/compact")


class TestPromptsSkippedWhileBlocked:
    def test_goal_is_skipped_and_left_for_its_ttl(self, sidecar_dir: Path) -> None:
        goal = _write_goal(sidecar_dir)
        _enter_blocked(sidecar_dir, BlockReason.GOAL_LOOP)
        outcome = _decide(sidecar_dir)
        assert outcome.payload is None
        assert outcome.noop_reason_log == (
            "noop: goal injection skipped: session BLOCKED (goal-blocked)"
        )
        assert goal.exists()

    def test_goal_still_fires_under_focus_alone(self, sidecar_dir: Path) -> None:
        _write_goal(sidecar_dir)
        _enter_focus(sidecar_dir)
        outcome = _decide(sidecar_dir)
        assert outcome.decision_value == _mod.Decision.WOULD_GOAL.value

    def test_standing_auth_is_skipped(self, sidecar_dir: Path) -> None:
        _write_standing_auth(sidecar_dir)
        assert _decide(sidecar_dir).decision_value == _mod.Decision.WOULD_STANDING_AUTH.value
        _enter_blocked(sidecar_dir)
        outcome = _decide(sidecar_dir)
        assert outcome.payload is None
        assert outcome.noop_reason_log == (
            "noop: standing-auth reminder skipped: session BLOCKED (awaiting-human)"
        )

    def test_session_actions_directive_is_skipped(self, sidecar_dir: Path) -> None:
        _write_session_actions(sidecar_dir)
        assert _decide(sidecar_dir).decision_value == _mod.Decision.WOULD_SESSION_ACTIONS.value
        _enter_blocked(sidecar_dir)
        outcome = _decide(sidecar_dir)
        assert outcome.payload is None
        assert outcome.noop_reason_log == (
            "noop: session-actions directive skipped: session BLOCKED (awaiting-human)"
        )


class TestUnreadableModesFile:
    """Fail closed: a file we cannot read might be the BLOCKED we must honour."""

    def _corrupt(self, sidecar_dir: Path) -> None:
        _modes_path(sidecar_dir).write_text("{", encoding="utf-8")

    def test_goal_is_withheld_and_the_error_logged(self, sidecar_dir: Path) -> None:
        _write_goal(sidecar_dir)
        self._corrupt(sidecar_dir)
        outcome = _decide(sidecar_dir)
        assert outcome.payload is None
        assert outcome.noop_reason_log is not None
        assert outcome.noop_reason_log.startswith("noop: session-modes file unreadable")
        assert f"{_SESSION}{registry_mod.SESSION_MODES_SUFFIX}" in outcome.noop_reason_log

    def test_continue_is_withheld(self, sidecar_dir: Path) -> None:
        _write_compaction_signal(sidecar_dir)
        self._corrupt(sidecar_dir)
        outcome = _decide(sidecar_dir)
        assert outcome.payload is None

    def test_the_status_line_carries_a_warning(self, sidecar_dir: Path) -> None:
        self._corrupt(sidecar_dir)
        _decide(sidecar_dir)
        message = _status_message(sidecar_dir)
        assert message["level"] == _mod._STATUS_LEVEL_WARNING
        assert "session-modes" in message["text"]

    def test_the_clear_cap_still_applies(self, sidecar_dir: Path) -> None:
        _write_clear(sidecar_dir)
        self._corrupt(sidecar_dir)
        machine = _mod.CompactStateMachine(_mod.CompactPolicy())
        machine.import_state({"goal_clear_injections": _mod._MAX_GOAL_CLEAR_INJECTIONS})
        outcome = _decide(sidecar_dir, machine=machine)
        assert outcome.payload is None

    def test_compact_itself_still_runs(self, sidecar_dir: Path) -> None:
        _write_red_sidecar(sidecar_dir)
        self._corrupt(sidecar_dir)
        assert _decide(sidecar_dir).decision_value == _mod.Decision.WOULD_COMPACT.value

    @pytest.mark.parametrize("field", ["mode", "source", "lifetime"])
    def test_a_wrongly_typed_field_fails_closed_inside_decide_once(
        self, sidecar_dir: Path, field: str
    ) -> None:
        """An unhashable value is the named error, never an exception out of the tick."""
        _write_goal(sidecar_dir)
        _write_raw(
            sidecar_dir,
            {"version": 1, "session_id": _SESSION, "modes": [_raw_record(**{field: []})]},
        )
        outcome = _decide(sidecar_dir)
        assert outcome.payload is None
        assert outcome.noop_reason_log is not None
        assert outcome.noop_reason_log.startswith("noop: session-modes file unreadable")
        assert field in outcome.noop_reason_log
        assert _status_message(sidecar_dir)["level"] == _mod._STATUS_LEVEL_WARNING


# ── Task 5.2: the goal clear under BLOCKED ───────────────────────────────────


class TestGoalClearUnderBlocked:
    def test_goal_outranks_clear_when_not_blocked(self, sidecar_dir: Path) -> None:
        _write_goal(sidecar_dir)
        _write_clear(sidecar_dir)
        assert _decide(sidecar_dir).decision_value == _mod.Decision.WOULD_GOAL.value

    def test_clear_outranks_goal_when_blocked(self, sidecar_dir: Path) -> None:
        goal = _write_goal(sidecar_dir)
        clear = _write_clear(sidecar_dir)
        _enter_blocked(sidecar_dir, BlockReason.GOAL_LOOP)
        outcome = _decide(sidecar_dir)
        assert outcome.decision_value == _mod.Decision.WOULD_GOAL_CLEAR.value
        assert outcome.payload == _mod._GOAL_CLEAR_COMMAND
        assert outcome.consume_signal_path == str(clear)
        assert goal.exists()

    def test_the_cap_refuses_an_ordinary_clear(self, sidecar_dir: Path) -> None:
        _write_clear(sidecar_dir)
        machine = _mod.CompactStateMachine(_mod.CompactPolicy())
        machine.import_state({"goal_clear_injections": _mod._MAX_GOAL_CLEAR_INJECTIONS})
        outcome = _decide(sidecar_dir, machine=machine)
        assert outcome.payload is None
        assert outcome.noop_reason_log == "noop: goal clear cap reached"

    @pytest.mark.parametrize("reason", list(BlockReason))
    def test_the_cap_does_not_refuse_a_blocked_clear(
        self, sidecar_dir: Path, reason: BlockReason
    ) -> None:
        _write_clear(sidecar_dir)
        _enter_blocked(sidecar_dir, reason)
        machine = _mod.CompactStateMachine(_mod.CompactPolicy())
        machine.import_state({"goal_clear_injections": _mod._MAX_GOAL_CLEAR_INJECTIONS + 3})
        outcome = _decide(sidecar_dir, machine=machine)
        assert outcome.decision_value == _mod.Decision.WOULD_GOAL_CLEAR.value
        assert outcome.payload == _mod._GOAL_CLEAR_COMMAND

    def test_blocked_clears_have_a_bounded_ceiling(self, sidecar_dir: Path) -> None:
        """A trigger whose delete keeps failing is not retyped every tick for its TTL."""
        assert _mod._MAX_BLOCKED_GOAL_CLEAR_INJECTIONS > _mod._MAX_GOAL_CLEAR_INJECTIONS
        _write_clear(sidecar_dir)
        _enter_blocked(sidecar_dir)
        machine = _mod.CompactStateMachine(_mod.CompactPolicy())
        machine.import_state({"goal_clear_injections": _mod._MAX_BLOCKED_GOAL_CLEAR_INJECTIONS})
        outcome = _decide(sidecar_dir, machine=machine)
        assert outcome.payload is None
        assert outcome.noop_reason_log == "noop: goal clear ceiling reached while BLOCKED"

    def test_an_undeletable_clear_stops_at_the_ceiling(
        self, sidecar_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """End to end: every consume fails (and is logged), the retyping still stops."""
        _write_clear(sidecar_dir)
        _enter_blocked(sidecar_dir)
        machine = _mod.CompactStateMachine(_mod.CompactPolicy())
        warnings: list[str] = []

        class _Log:
            def write(self, line: str) -> None:
                warnings.append(line)

            def write_noop(self, line: str) -> None:
                warnings.append(line)

        def _refuse(self: Path, missing_ok: bool = False) -> None:
            raise PermissionError("read-only sidecar")

        monkeypatch.setattr(Path, "unlink", _refuse)
        typed = 0
        for _ in range(_mod._MAX_BLOCKED_GOAL_CLEAR_INJECTIONS + 10):
            outcome = _decide(sidecar_dir, machine=machine)
            if outcome.payload is None:
                assert outcome.noop_reason_log == "noop: goal clear ceiling reached while BLOCKED"
                break
            typed += 1
            _mod._consume_signal(Path(outcome.consume_signal_path), _Log())
            _mod._apply_post_injection_bookkeeping(machine, outcome, injected=True, now_wall=_NOW)
            # The typed line was submitted; only the undeletable trigger remains.
            machine.clear_own_line()
        assert typed == _mod._MAX_BLOCKED_GOAL_CLEAR_INJECTIONS
        assert sum("could not consume" in line for line in warnings) == typed
