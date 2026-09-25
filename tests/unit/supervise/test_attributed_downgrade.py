"""Plan 00328 Phase 2 — the restore arms on an ATTRIBUTED downgrade, not a guess.

The supervisor used to open a downgrade episode from a model high-water drop
alone: fable on screen, then opus, therefore the machine did it. A human
picking Opus from the `/model` picker produces exactly that observation, which
is how the supervisor came to type `/model fable` at a human who had just
chosen otherwise (`CLAUDE/Plan/00328-.../REPRODUCTION.md`).

Claude Code writes the automatic downgrade into the transcript, and the
daemon's `model_downgrade_recorder` publishes it as a per-session signal in the
sidecar directory. With that in hand the question inverts: the episode opens
only for a downgrade the platform ITSELF recorded, so a human change needs no
recognition at all.

Plan 00466 N47 made the record's identity and its time part of that question.
The recorder republishes the SAME record for the rest of the session, so a
record must (a) never reopen an episode it already ran, which needs an
identity (`record_id`), and (b) only ever explain a drop observed close to
when the downgrade actually happened, which needs its event time.
"""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

import pytest

from tests.unit.supervise._load import load_supervisor_module

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from tests.unit.supervise._load import SupervisorStateMachine, SupervisorTickOutcome

_mod = load_supervisor_module()

_NOW = 50_000.0
_SESSION = "attributed-sess-1"
_OTHER_SESSION = "attributed-sess-2"
_RECORD_ID = "uuid-record-1"
_WINDOW = 300.0


@pytest.fixture
def _non_utc_local_time(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Run with a local zone far from UTC, restoring the process zone after."""
    monkeypatch.setenv("TZ", "America/New_York")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


def _iso(epoch: float) -> str:
    """The transcript's own timestamp format for ``epoch``."""
    stamp = datetime.fromtimestamp(epoch, tz=UTC).isoformat(timespec="milliseconds")
    return stamp.replace("+00:00", "Z")


def _facts(now: float = _NOW) -> object:
    return _mod.TickFacts(
        now_wall=now,
        idle=True,
        input_line_empty=True,
        human_compact_submitted=False,
        work_idle=True,
    )


def _write_sidecar(
    sidecar_dir: Path,
    *,
    model_id: str,
    effort: str | None,
    ts: float,
    session_id: str = _SESSION,
) -> None:
    sidecar_dir.mkdir(parents=True, exist_ok=True)
    (sidecar_dir / f"{session_id}.json").write_text(
        json.dumps(
            {
                "red": False,
                "critical": False,
                "compact_urgent": False,
                "tier": "ok",
                "pct": 20.0,
                "session_id": session_id,
                "ts": ts,
                "seq": 1,
                "writer_pid": 42,
                "compacting": False,
                "model_id": model_id,
                "effort": effort,
            }
        ),
        encoding="utf-8",
    )


def _write_downgrade_signal(
    sidecar_dir: Path,
    *,
    original_family: str | None = "fable",
    fallback_family: str | None = "opus",
    session_id: str = _SESSION,
    ts: float = _NOW,
    record_ts: str | None = None,
    record_id: str | None = _RECORD_ID,
) -> Path:
    """Write what the daemon's model_downgrade_recorder publishes.

    ``record_ts`` defaults to ``ts`` in the transcript's own format: the
    record's event time, which is what bounds which drop it can explain.
    ``record_id=None`` writes a signal from a daemon that predates the field.
    """
    sidecar_dir.mkdir(parents=True, exist_ok=True)
    path = sidecar_dir / f"{session_id}{_mod._MODEL_DOWNGRADE_SIGNAL_SUFFIX}"
    payload: dict[str, object] = {
        "ts": ts,
        "session_id": session_id,
        "original_model": "claude-fable-5",
        "fallback_model": "claude-opus-4-8",
        "original_family": original_family,
        "fallback_family": fallback_family,
        "category": "cyber",
        "scope": "session",
        "record_ts": _iso(ts) if record_ts is None else record_ts,
    }
    if record_id is not None:
        payload["record_id"] = record_id
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _machine(restore_delay: float | None = None) -> SupervisorStateMachine:
    policy = (
        _mod.CompactPolicy()
        if restore_delay is None
        else _mod.CompactPolicy(model_restore_delay_seconds=restore_delay)
    )
    return cast("SupervisorStateMachine", _mod.CompactStateMachine(policy))


def _decide(
    sidecar_dir: Path, machine: SupervisorStateMachine, *, now: float = _NOW
) -> SupervisorTickOutcome:
    policy = _mod.CompactPolicy()
    return cast(
        "SupervisorTickOutcome",
        _mod.decide_once(
            machine,
            sidecar_dir=sidecar_dir,
            facts=_facts(now),
            dry_run=False,
            freshness_seconds=policy.freshness_seconds,
        ),
    )


def _drive_fable_to_opus(
    sidecar_dir: Path, machine: SupervisorStateMachine, *, now: float = _NOW
) -> None:
    _write_sidecar(sidecar_dir, model_id="claude-fable-5", effort="low", ts=now - 10.0)
    _decide(sidecar_dir, machine, now=now - 9.0)
    _write_sidecar(sidecar_dir, model_id="claude-opus-5", effort="high", ts=now - 8.0)
    _decide(sidecar_dir, machine, now=now - 7.0)


def _show(sidecar_dir: Path, *, model_id: str, now: float, session_id: str = _SESSION) -> None:
    """A fresh status render of ``model_id`` just before ``now``."""
    _write_sidecar(
        sidecar_dir, model_id=model_id, effort="high", ts=now - 1.0, session_id=session_id
    )


def _typed_between(
    sidecar_dir: Path,
    machine: SupervisorStateMachine,
    *,
    start: float,
    end: float,
    model_id: str,
    step: float = 30.0,
    session_id: str = _SESSION,
) -> list[str]:
    """Tick every ``step`` seconds with ``model_id`` on screen; return what was typed."""
    typed: list[str] = []
    now = start
    while now <= end:
        _show(sidecar_dir, model_id=model_id, now=now, session_id=session_id)
        outcome = _decide(sidecar_dir, machine, now=now)
        if outcome.payload is not None:
            typed.append(outcome.payload)
        now += step
    return typed


def _model_commands(typed: list[str]) -> list[str]:
    return [line for line in typed if line.startswith("/model")]


def _manual_pick_of_opus(sidecar_dir: Path, machine: SupervisorStateMachine, *, now: float) -> None:
    """The human picks Opus from Fable: a fable render, then an opus render."""
    _show(sidecar_dir, model_id="claude-fable-5", now=now)
    _decide(sidecar_dir, machine, now=now)
    _show(sidecar_dir, model_id="claude-opus-5", now=now + 2.0)
    _decide(sidecar_dir, machine, now=now + 2.0)


def _auto_downgrade_then_recovery(
    sidecar_dir: Path, machine: SupervisorStateMachine, *, now: float = _NOW
) -> list[str]:
    """A recorded downgrade at ``now``, its restore, and the recovery 60s on."""
    _write_downgrade_signal(sidecar_dir, ts=now)
    _drive_fable_to_opus(sidecar_dir, machine, now=now)
    typed = _typed_between(
        sidecar_dir, machine, start=now, end=now + 30.0, model_id="claude-opus-5"
    )
    _show(sidecar_dir, model_id="claude-fable-5", now=now + 60.0)
    _decide(sidecar_dir, machine, now=now + 60.0)
    assert machine.export_state()["downgrade_episode"] is None
    return typed


def _latch_then_record(
    sidecar_dir: Path,
    machine: SupervisorStateMachine,
    *,
    record_ts: str | None = None,
    record_id: str | None = _RECORD_ID,
    arrives: float = _NOW,
) -> SupervisorTickOutcome:
    """The reading renders before the record is published (review 3 item C).

    The drop is observed at ``_NOW - 2``; the record is published at
    ``arrives`` and the tick at that moment is returned.
    """
    _write_sidecar(sidecar_dir, model_id="claude-fable-5", effort="low", ts=_NOW - 5.0)
    _decide(sidecar_dir, machine, now=_NOW - 4.0)
    _write_sidecar(sidecar_dir, model_id="claude-opus-5", effort="high", ts=_NOW - 3.0)
    first = _decide(sidecar_dir, machine, now=_NOW - 2.0)
    assert first.noop_reason_log is not None
    assert "unattributed" in first.noop_reason_log
    assert machine.export_state()["downgrade_episode"] is None
    _write_downgrade_signal(
        sidecar_dir,
        ts=_NOW - 3.0,
        record_ts=record_ts,
        record_id=record_id,
    )
    _show(sidecar_dir, model_id="claude-opus-5", now=arrives)
    return _decide(sidecar_dir, machine, now=arrives)


class TestTheSignalLoader:
    def test_an_in_scope_signal_yields_its_record(self, tmp_path: Path) -> None:
        sidecar_dir = tmp_path / "cs"
        _write_downgrade_signal(sidecar_dir)

        found = _mod.load_model_downgrade_signal(sidecar_dir, own_sessions=frozenset({_SESSION}))

        assert found == _mod.DowngradeRecord(
            session_id=_SESSION,
            from_family="fable",
            to_family="opus",
            record_key=_RECORD_ID,
            event_ts=_NOW,
        )

    def test_a_signal_from_before_record_ids_is_keyed_by_its_time(self, tmp_path: Path) -> None:
        """An older daemon published no `record_id`; its `record_ts` is the key."""
        sidecar_dir = tmp_path / "cs"
        _write_downgrade_signal(sidecar_dir, record_id=None)

        found = _mod.load_model_downgrade_signal(sidecar_dir, own_sessions=None)

        assert found is not None
        assert found.record_key == _iso(_NOW)

    def test_an_unparseable_record_time_yields_no_event_time(self, tmp_path: Path) -> None:
        sidecar_dir = tmp_path / "cs"
        _write_downgrade_signal(sidecar_dir, record_ts="not a time")

        found = _mod.load_model_downgrade_signal(sidecar_dir, own_sessions=None)

        assert found is not None
        assert found.event_ts is None

    @pytest.mark.usefixtures("_non_utc_local_time")
    def test_a_record_time_without_a_zone_is_read_as_utc(self, tmp_path: Path) -> None:
        """Claude Code writes UTC; reading a zone-less time as LOCAL time would
        shift every record by the host's offset. Run under a non-UTC zone, or
        a UTC container could not tell the two readings apart."""
        sidecar_dir = tmp_path / "cs"
        _write_downgrade_signal(sidecar_dir, record_ts=_iso(_NOW).rstrip("Z"))

        found = _mod.load_model_downgrade_signal(sidecar_dir, own_sessions=None)

        assert found is not None
        assert found.event_ts == _NOW

    def test_a_foreign_session_signal_is_ignored(self, tmp_path: Path) -> None:
        """The defect a user-level settings file could never avoid.

        Another session's downgrade says nothing about this one.
        """
        sidecar_dir = tmp_path / "cs"
        _write_downgrade_signal(sidecar_dir, session_id="somebody-elses-session")

        found = _mod.load_model_downgrade_signal(sidecar_dir, own_sessions=frozenset({_SESSION}))

        assert found is None

    def test_a_signal_with_an_unresolved_family_is_not_actionable(self, tmp_path: Path) -> None:
        """A null family means the recorder could not name the model.

        Acting on it would aim the restore at nothing.
        """
        sidecar_dir = tmp_path / "cs"
        _write_downgrade_signal(sidecar_dir, original_family=None)

        assert (
            _mod.load_model_downgrade_signal(sidecar_dir, own_sessions=frozenset({_SESSION}))
            is None
        )

    def test_a_missing_directory_yields_none(self, tmp_path: Path) -> None:
        assert _mod.load_model_downgrade_signal(tmp_path / "nope", own_sessions=None) is None

    def test_a_malformed_signal_yields_none_rather_than_raising(self, tmp_path: Path) -> None:
        sidecar_dir = tmp_path / "cs"
        sidecar_dir.mkdir(parents=True)
        (sidecar_dir / f"{_SESSION}{_mod._MODEL_DOWNGRADE_SIGNAL_SUFFIX}").write_text(
            "{not json", encoding="utf-8"
        )

        assert _mod.load_model_downgrade_signal(sidecar_dir, own_sessions=None) is None


class TestArming:
    def test_an_attributed_downgrade_opens_the_episode(self, tmp_path: Path) -> None:
        sidecar_dir = tmp_path / "cs"
        machine = _machine()
        _write_downgrade_signal(sidecar_dir)

        _drive_fable_to_opus(sidecar_dir, machine)

        assert machine.export_state()["downgrade_episode"] is not None

    def test_an_unattributed_drop_opens_no_episode(self, tmp_path: Path) -> None:
        """The reproduction, in one assertion.

        Same observation the old high-water rule armed on — fable, then opus —
        but nothing recorded a machine downgrade, so it was the human.
        """
        sidecar_dir = tmp_path / "cs"
        machine = _machine()

        _drive_fable_to_opus(sidecar_dir, machine)

        assert machine.export_state()["downgrade_episode"] is None

    def test_an_unattributed_drop_never_injects_a_model_restore(self, tmp_path: Path) -> None:
        sidecar_dir = tmp_path / "cs"
        machine = _machine()
        _drive_fable_to_opus(sidecar_dir, machine)

        _write_sidecar(sidecar_dir, model_id="claude-opus-5", effort="xhigh", ts=_NOW - 6.0)
        later = _decide(sidecar_dir, machine, now=_NOW + 10_000.0)

        assert later.decision_value != "would-model"

    def test_a_signal_for_a_different_pair_does_not_arm_this_drop(self, tmp_path: Path) -> None:
        """A recorded sonnet downgrade says nothing about a fable -> opus move."""
        sidecar_dir = tmp_path / "cs"
        machine = _machine()
        _write_downgrade_signal(sidecar_dir, original_family="opus", fallback_family="sonnet")

        _drive_fable_to_opus(sidecar_dir, machine)

        assert machine.export_state()["downgrade_episode"] is None

    def test_the_declined_arming_is_reported_for_the_decision_log(self, tmp_path: Path) -> None:
        """A disabled recorder must be diagnosable, not silent.

        Without this note, "the supervisor stopped restoring" looks identical
        to "no downgrade ever happened".
        """
        sidecar_dir = tmp_path / "cs"
        machine = _machine()

        _write_sidecar(sidecar_dir, model_id="claude-fable-5", effort="low", ts=_NOW - 10.0)
        _decide(sidecar_dir, machine, now=_NOW - 9.0)
        _write_sidecar(sidecar_dir, model_id="claude-opus-5", effort="high", ts=_NOW - 8.0)
        outcome = _decide(sidecar_dir, machine, now=_NOW - 7.0)

        assert outcome.noop_reason_log is not None
        assert "unattributed" in outcome.noop_reason_log
        assert "fable -> opus" in outcome.noop_reason_log

    def test_the_declined_note_is_reported_once_per_drop(self, tmp_path: Path) -> None:
        """A downgraded session renders a status line roughly every second."""
        sidecar_dir = tmp_path / "cs"
        machine = _machine()

        _write_sidecar(sidecar_dir, model_id="claude-fable-5", effort="low", ts=_NOW - 10.0)
        _decide(sidecar_dir, machine, now=_NOW - 9.0)
        notes: list[str] = []
        for step in range(4):
            _write_sidecar(
                sidecar_dir, model_id="claude-opus-5", effort="high", ts=_NOW - 8.0 + step
            )
            outcome = _decide(sidecar_dir, machine, now=_NOW - 7.0 + step)
            if outcome.noop_reason_log and "unattributed" in outcome.noop_reason_log:
                notes.append(outcome.noop_reason_log)

        assert len(notes) == 1


class TestSpentRecordDoesNotReopen:
    """Plan 00466 N47 review 2 MAJOR 4.

    ``model_downgrade_recorder`` republishes the SAME record for the rest of
    the session, even after the episode it described has been fully recovered
    from. A human who later manually switched back to the fallback family
    produced the exact observation (fable, then opus, in this session) that
    the record attributes -- reopening an episode and firing ``/model fable``
    at a human who had just chosen otherwise.
    """

    def test_a_closed_episodes_record_does_not_reopen_on_a_later_manual_drop(
        self, tmp_path: Path
    ) -> None:
        sidecar_dir = tmp_path / "cs"
        machine = _machine()
        _write_downgrade_signal(sidecar_dir, ts=_NOW, session_id=_SESSION)

        # Open, then close, the episode from the one recorded downgrade.
        _drive_fable_to_opus(sidecar_dir, machine, now=_NOW)
        assert machine.export_state()["downgrade_episode"] is not None
        _write_sidecar(sidecar_dir, model_id="claude-fable-5", effort="low", ts=_NOW + 1.0)
        _decide(sidecar_dir, machine, now=_NOW + 2.0)
        assert machine.export_state()["downgrade_episode"] is None

        # The recorder's signal file is still on disk naming the SAME record
        # (Claude Code does not clear it), and the human now manually drops
        # back to opus -- the identical (fable, then opus) observation.
        _write_sidecar(sidecar_dir, model_id="claude-opus-5", effort="high", ts=_NOW + 10.0)
        _decide(sidecar_dir, machine, now=_NOW + 11.0)

        assert machine.export_state()["downgrade_episode"] is None

    def test_a_genuinely_new_downgrade_with_a_new_record_still_reopens(
        self, tmp_path: Path
    ) -> None:
        sidecar_dir = tmp_path / "cs"
        machine = _machine()
        _write_downgrade_signal(sidecar_dir, ts=_NOW, record_id="uuid-first")

        _drive_fable_to_opus(sidecar_dir, machine, now=_NOW)
        assert machine.export_state()["downgrade_episode"] is not None
        _write_sidecar(sidecar_dir, model_id="claude-fable-5", effort="low", ts=_NOW + 1.0)
        _decide(sidecar_dir, machine, now=_NOW + 2.0)
        assert machine.export_state()["downgrade_episode"] is None

        # A REAL second downgrade: a new transcript record.
        _write_downgrade_signal(sidecar_dir, ts=_NOW + 9.0, record_id="uuid-second")
        _write_sidecar(sidecar_dir, model_id="claude-opus-5", effort="high", ts=_NOW + 10.0)
        _decide(sidecar_dir, machine, now=_NOW + 11.0)

        assert machine.export_state()["downgrade_episode"] is not None

    def test_a_manual_pick_soon_after_a_recovery_is_not_fought(self, tmp_path: Path) -> None:
        """Inside the attribution window only the spent identity protects the human."""
        sidecar_dir = tmp_path / "cs"
        machine = _machine()
        restored = _auto_downgrade_then_recovery(sidecar_dir, machine)
        assert "/model fable" in restored

        _manual_pick_of_opus(sidecar_dir, machine, now=_NOW + 120.0)
        typed = _typed_between(
            sidecar_dir, machine, start=_NOW + 125.0, end=_NOW + 400.0, model_id="claude-opus-5"
        )

        assert _model_commands(typed) == []


class TestRecordIdentity:
    """Plan 00466 N47 review 4 item 4: a record is spent by its identity."""

    def test_an_episode_spends_the_records_id(self, tmp_path: Path) -> None:
        sidecar_dir = tmp_path / "cs"
        machine = _machine()

        _auto_downgrade_then_recovery(sidecar_dir, machine)

        assert machine.export_state()["spent_downgrade_record_id"] == _RECORD_ID

    def test_a_second_untimestamped_downgrade_with_a_new_id_opens_a_fresh_episode(
        self, tmp_path: Path
    ) -> None:
        """Two records with no time are still two records: their ids differ."""
        sidecar_dir = tmp_path / "cs"
        machine = _machine()
        _write_downgrade_signal(sidecar_dir, record_ts="", record_id="offset:100")
        _drive_fable_to_opus(sidecar_dir, machine, now=_NOW)
        _show(sidecar_dir, model_id="claude-fable-5", now=_NOW + 2.0)
        _decide(sidecar_dir, machine, now=_NOW + 2.0)
        assert machine.export_state()["downgrade_episode"] is None

        _write_downgrade_signal(sidecar_dir, record_ts="", record_id="offset:900")
        _show(sidecar_dir, model_id="claude-opus-5", now=_NOW + 11.0)
        _decide(sidecar_dir, machine, now=_NOW + 11.0)

        assert machine.export_state()["downgrade_episode"] is not None

    def test_a_manual_pick_after_an_untimestamped_downgrade_is_not_fought(
        self, tmp_path: Path
    ) -> None:
        """Review 4 finding 4: the record had no time, so it could never be spent.

        With an identity it is spent like any other, so the human's later pick
        of Opus, inside or outside the window, is theirs.
        """
        sidecar_dir = tmp_path / "cs"
        machine = _machine()
        _write_downgrade_signal(sidecar_dir, record_ts="", record_id="offset:100")
        _drive_fable_to_opus(sidecar_dir, machine, now=_NOW)
        _typed_between(sidecar_dir, machine, start=_NOW, end=_NOW + 30.0, model_id="claude-opus-5")
        _show(sidecar_dir, model_id="claude-fable-5", now=_NOW + 60.0)
        _decide(sidecar_dir, machine, now=_NOW + 60.0)

        _manual_pick_of_opus(sidecar_dir, machine, now=_NOW + 90.0)
        typed = _typed_between(
            sidecar_dir, machine, start=_NOW + 95.0, end=_NOW + 400.0, model_id="claude-opus-5"
        )

        assert _model_commands(typed) == []

    def test_a_record_with_no_identity_at_all_is_never_spent(self, tmp_path: Path) -> None:
        """An older daemon's untimestamped record has an empty key.

        Spending "" would refuse every later identity-less downgrade in the
        session; what bounds it instead is the attribution window.
        """
        sidecar_dir = tmp_path / "cs"
        machine = _machine()
        _write_downgrade_signal(sidecar_dir, record_ts="", record_id=None)

        _drive_fable_to_opus(sidecar_dir, machine, now=_NOW)
        _show(sidecar_dir, model_id="claude-fable-5", now=_NOW + 2.0)
        _decide(sidecar_dir, machine, now=_NOW + 2.0)

        assert machine.export_state()["downgrade_episode"] is None
        assert machine.export_state()["spent_downgrade_record_id"] is None


class TestAttributionWindow:
    """Plan 00466 N47 review 4 items 3 and 4: a record explains only a nearby drop.

    A record's event time (its transcript timestamp, or when it was first seen
    if it has none) must fall within the window of the drop it attributes.
    """

    def test_a_record_arriving_long_after_a_manual_pick_opens_nothing(self, tmp_path: Path) -> None:
        """Review 4 finding 3: the latch had no time bound."""
        sidecar_dir = tmp_path / "cs"
        machine = _machine()
        _latch_then_record(
            sidecar_dir, machine, record_ts=_iso(_NOW + 1800.0), arrives=_NOW + 1800.0
        )

        typed = _typed_between(
            sidecar_dir, machine, start=_NOW + 1801.0, end=_NOW + 3000.0, model_id="claude-opus-5"
        )

        assert _model_commands(typed) == []
        assert machine.export_state()["downgrade_episode"] is None

    def test_an_untimestamped_record_arriving_long_after_a_manual_pick_opens_nothing(
        self, tmp_path: Path
    ) -> None:
        """With no event time, the moment the record was first seen stands in."""
        sidecar_dir = tmp_path / "cs"
        machine = _machine()
        _latch_then_record(
            sidecar_dir, machine, record_ts="", record_id="offset:4", arrives=_NOW + 1800.0
        )

        typed = _typed_between(
            sidecar_dir, machine, start=_NOW + 1801.0, end=_NOW + 3000.0, model_id="claude-opus-5"
        )

        assert _model_commands(typed) == []

    def test_a_record_of_the_drop_itself_published_late_is_still_attributed(
        self, tmp_path: Path
    ) -> None:
        """The recorder only runs on PostToolUse, so publishing can lag.

        The bound is on WHEN THE DOWNGRADE HAPPENED, not when it was published.
        """
        sidecar_dir = tmp_path / "cs"
        machine = _machine()
        outcome = _latch_then_record(
            sidecar_dir, machine, record_ts=_iso(_NOW - 3.0), arrives=_NOW + 600.0
        )

        assert outcome.payload == "/model fable"

    def test_a_stale_record_does_not_attribute_a_fresh_manual_drop(self, tmp_path: Path) -> None:
        """A downgrade the supervisor never saw open an episode is never spent.

        Its record says nothing about a human's pick of Opus two hours later.
        """
        sidecar_dir = tmp_path / "cs"
        machine = _machine()
        _write_downgrade_signal(sidecar_dir, ts=_NOW - 7200.0)

        _drive_fable_to_opus(sidecar_dir, machine, now=_NOW)
        typed = _typed_between(
            sidecar_dir, machine, start=_NOW, end=_NOW + 300.0, model_id="claude-opus-5"
        )

        assert _model_commands(typed) == []
        assert machine.export_state()["downgrade_episode"] is None

    def test_a_drop_just_inside_the_window_is_attributed(self, tmp_path: Path) -> None:
        sidecar_dir = tmp_path / "cs"
        machine = _machine()
        _write_downgrade_signal(sidecar_dir, ts=_NOW - 7.0 - _WINDOW + 1.0)

        _drive_fable_to_opus(sidecar_dir, machine, now=_NOW)

        assert machine.export_state()["downgrade_episode"] is not None

    def test_a_drop_just_outside_the_window_is_not_attributed(self, tmp_path: Path) -> None:
        sidecar_dir = tmp_path / "cs"
        machine = _machine()
        _write_downgrade_signal(sidecar_dir, ts=_NOW - 7.0 - _WINDOW - 1.0)

        _drive_fable_to_opus(sidecar_dir, machine, now=_NOW)

        assert machine.export_state()["downgrade_episode"] is None

    def test_the_window_holds_for_a_record_written_after_the_drop_too(self, tmp_path: Path) -> None:
        """A standalone record lands up to 90s after the switch; far later is not it."""
        sidecar_dir = tmp_path / "cs"
        machine = _machine()
        _write_downgrade_signal(sidecar_dir, ts=_NOW - 7.0 + _WINDOW + 1.0)

        _drive_fable_to_opus(sidecar_dir, machine, now=_NOW)

        assert machine.export_state()["downgrade_episode"] is None

    def test_a_manual_pick_two_hours_after_an_untimestamped_downgrade_is_not_fought(
        self, tmp_path: Path
    ) -> None:
        """Review 4 scenario S1, for a record with no time AND no identity.

        Such a record is never spent, so the window is what stops it from
        attributing the human's own pick much later.
        """
        sidecar_dir = tmp_path / "cs"
        machine = _machine()
        _write_downgrade_signal(sidecar_dir, record_ts="", record_id=None)
        _drive_fable_to_opus(sidecar_dir, machine, now=_NOW)
        restored = _typed_between(
            sidecar_dir, machine, start=_NOW, end=_NOW + 30.0, model_id="claude-opus-5"
        )
        assert "/model fable" in restored
        _show(sidecar_dir, model_id="claude-fable-5", now=_NOW + 800.0)
        _decide(sidecar_dir, machine, now=_NOW + 800.0)

        _manual_pick_of_opus(sidecar_dir, machine, now=_NOW + 8000.0)
        typed = _typed_between(
            sidecar_dir, machine, start=_NOW + 8005.0, end=_NOW + 9500.0, model_id="claude-opus-5"
        )

        assert _model_commands(typed) == []

    def test_a_record_of_unknown_time_attributes_nothing(self, tmp_path: Path) -> None:
        """An older worker's exported state names a record but not WHEN it
        happened, and no signal file has been read since. Not knowing the time
        is not the same as the record being fresh."""
        sidecar_dir = tmp_path / "cs"
        reloaded = _machine()
        reloaded.import_state({"attributed_downgrade": f"{_SESSION}:fable:opus:{_RECORD_ID}"})

        _drive_fable_to_opus(sidecar_dir, reloaded, now=_NOW)
        typed = _typed_between(
            sidecar_dir, reloaded, start=_NOW, end=_NOW + 200.0, model_id="claude-opus-5"
        )

        assert _model_commands(typed) == []
        assert reloaded.export_state()["downgrade_episode"] is None

    def test_the_first_sighting_of_an_untimestamped_record_is_kept(self, tmp_path: Path) -> None:
        """Republishing the same record every tick must not keep it "fresh"."""
        sidecar_dir = tmp_path / "cs"
        machine = _machine()
        _write_downgrade_signal(sidecar_dir, record_ts="", record_id="offset:7")
        _show(sidecar_dir, model_id="claude-fable-5", now=_NOW)
        _decide(sidecar_dir, machine, now=_NOW)
        _typed_between(
            sidecar_dir, machine, start=_NOW + 30.0, end=_NOW + 3000.0, model_id="claude-fable-5"
        )

        _show(sidecar_dir, model_id="claude-opus-5", now=_NOW + 3030.0)
        _decide(sidecar_dir, machine, now=_NOW + 3030.0)

        assert machine.export_state()["downgrade_episode"] is None


class TestRetroAttribution:
    """Review 3 item C and review 4 findings 5 and 8: the reading-before-record latch."""

    def test_a_reading_that_renders_before_its_record_is_attributed_once_the_record_arrives(
        self, tmp_path: Path
    ) -> None:
        """Item C: the reading can render one tick before the recorder
        publishes its signal. The old code judged the drop unattributed on
        that first tick and never looked again."""
        sidecar_dir = tmp_path / "cs"
        machine = _machine()

        outcome = _latch_then_record(sidecar_dir, machine)

        assert machine.export_state()["downgrade_episode"] is not None
        assert outcome.payload == "/model fable"

    def test_the_latch_is_consumed_once_it_attributes_the_drop(self, tmp_path: Path) -> None:
        sidecar_dir = tmp_path / "cs"
        machine = _machine(restore_delay=900.0)

        _latch_then_record(sidecar_dir, machine)

        assert machine.export_state()["pending_unattributed_drop"] is None

    def test_a_retro_episode_spends_its_record_on_recovery(self, tmp_path: Path) -> None:
        """Without the stamp, the retro episode closes spending nothing, and the
        human's next pick of Opus is fought using the same record."""
        sidecar_dir = tmp_path / "cs"
        machine = _machine()
        _latch_then_record(sidecar_dir, machine)
        _show(sidecar_dir, model_id="claude-fable-5", now=_NOW + 30.0)
        _decide(sidecar_dir, machine, now=_NOW + 30.0)
        assert machine.export_state()["spent_downgrade_record_id"] == _RECORD_ID

        _manual_pick_of_opus(sidecar_dir, machine, now=_NOW + 60.0)
        typed = _typed_between(
            sidecar_dir, machine, start=_NOW + 65.0, end=_NOW + 400.0, model_id="claude-opus-5"
        )

        assert _model_commands(typed) == []

    def test_a_spent_record_is_never_retro_attributed_to_a_manual_pick(
        self, tmp_path: Path
    ) -> None:
        """The MAJOR 4 fight through the retro path.

        After an auto episode recovers, the human picks Opus. The drop is
        unattributed (its record is spent), so the latch is set -- and the same
        record, republished on every tick, must not attribute it retroactively.
        """
        sidecar_dir = tmp_path / "cs"
        machine = _machine()
        _auto_downgrade_then_recovery(sidecar_dir, machine)

        _manual_pick_of_opus(sidecar_dir, machine, now=_NOW + 120.0)
        assert machine.export_state()["pending_unattributed_drop"] is not None
        typed = _typed_between(
            sidecar_dir, machine, start=_NOW + 125.0, end=_NOW + 400.0, model_id="claude-opus-5"
        )

        assert _model_commands(typed) == []

    def test_the_latch_is_dropped_if_the_session_leaves_the_fallback_first(
        self, tmp_path: Path
    ) -> None:
        """The bridging window ends when the human moves off the fallback."""
        sidecar_dir = tmp_path / "cs"
        machine = _machine()
        _write_sidecar(sidecar_dir, model_id="claude-fable-5", effort="low", ts=_NOW - 5.0)
        _decide(sidecar_dir, machine, now=_NOW - 4.0)
        _write_sidecar(sidecar_dir, model_id="claude-opus-5", effort="high", ts=_NOW - 3.0)
        _decide(sidecar_dir, machine, now=_NOW - 2.0)
        _write_sidecar(sidecar_dir, model_id="claude-sonnet-5", effort="high", ts=_NOW - 1.0)
        _decide(sidecar_dir, machine, now=_NOW)
        assert machine.export_state()["pending_unattributed_drop"] is None

        _write_downgrade_signal(sidecar_dir, ts=_NOW - 3.0)
        typed = _typed_between(
            sidecar_dir, machine, start=_NOW + 2.0, end=_NOW + 200.0, model_id="claude-sonnet-5"
        )

        assert _model_commands(typed) == []
        assert machine.export_state()["downgrade_episode"] is None

    def test_leaving_the_fallback_on_the_tick_the_record_arrives_opens_nothing(
        self, tmp_path: Path
    ) -> None:
        """Both happen between two ticks: the record lands AND the human picks
        Sonnet. The record is read first, so the attribution has to wait for
        this tick's reading, or it opens an episode Sonnet never closes."""
        sidecar_dir = tmp_path / "cs"
        machine = _machine()
        _write_sidecar(sidecar_dir, model_id="claude-fable-5", effort="low", ts=_NOW - 5.0)
        _decide(sidecar_dir, machine, now=_NOW - 4.0)
        _write_sidecar(sidecar_dir, model_id="claude-opus-5", effort="high", ts=_NOW - 3.0)
        _decide(sidecar_dir, machine, now=_NOW - 2.0)

        _write_downgrade_signal(sidecar_dir, ts=_NOW - 3.0)
        typed = _typed_between(
            sidecar_dir, machine, start=_NOW, end=_NOW + 200.0, model_id="claude-sonnet-5"
        )

        assert _model_commands(typed) == []
        assert machine.export_state()["downgrade_episode"] is None

    def test_the_latch_is_dropped_when_the_foreground_session_changes(self, tmp_path: Path) -> None:
        """A restore types into the FOREGROUND session. If that is now another
        session, a late record for the first must not arm a `/model` there."""
        sidecar_dir = tmp_path / "cs"
        machine = _machine()
        _write_sidecar(sidecar_dir, model_id="claude-fable-5", effort="low", ts=_NOW - 5.0)
        _decide(sidecar_dir, machine, now=_NOW - 4.0)
        _write_sidecar(sidecar_dir, model_id="claude-opus-5", effort="high", ts=_NOW - 3.0)
        _decide(sidecar_dir, machine, now=_NOW - 2.0)
        (sidecar_dir / f"{_SESSION}.json").unlink()
        _show(sidecar_dir, model_id="claude-opus-5", now=_NOW, session_id=_OTHER_SESSION)
        _decide(sidecar_dir, machine, now=_NOW)
        assert machine.export_state()["pending_unattributed_drop"] is None

        _write_downgrade_signal(sidecar_dir, ts=_NOW - 3.0)
        typed = _typed_between(
            sidecar_dir,
            machine,
            start=_NOW + 2.0,
            end=_NOW + 200.0,
            model_id="claude-opus-5",
            session_id=_OTHER_SESSION,
        )

        assert _model_commands(typed) == []

    def test_a_record_for_another_session_is_not_retro_attributed(self, tmp_path: Path) -> None:
        sidecar_dir = tmp_path / "cs"
        machine = _machine()
        _write_sidecar(sidecar_dir, model_id="claude-fable-5", effort="low", ts=_NOW - 5.0)
        _decide(sidecar_dir, machine, now=_NOW - 4.0)
        _write_sidecar(sidecar_dir, model_id="claude-opus-5", effort="high", ts=_NOW - 3.0)
        _decide(sidecar_dir, machine, now=_NOW - 2.0)

        _write_downgrade_signal(sidecar_dir, ts=_NOW - 3.0, session_id=_OTHER_SESSION)
        typed = _typed_between(
            sidecar_dir, machine, start=_NOW, end=_NOW + 200.0, model_id="claude-opus-5"
        )

        assert _model_commands(typed) == []

    def test_the_latch_survives_a_worker_hot_reload(self, tmp_path: Path) -> None:
        """The worker exports its state every tick; a reload between the drop
        and the record must not lose the latch or when it was set."""
        sidecar_dir = tmp_path / "cs"
        machine = _machine()
        _write_sidecar(sidecar_dir, model_id="claude-fable-5", effort="low", ts=_NOW - 5.0)
        _decide(sidecar_dir, machine, now=_NOW - 4.0)
        _write_sidecar(sidecar_dir, model_id="claude-opus-5", effort="high", ts=_NOW - 3.0)
        _decide(sidecar_dir, machine, now=_NOW - 2.0)

        reloaded = _machine()
        reloaded.import_state(json.loads(json.dumps(machine.export_state())))
        _write_downgrade_signal(sidecar_dir, ts=_NOW - 3.0)
        _show(sidecar_dir, model_id="claude-opus-5", now=_NOW)
        outcome = _decide(sidecar_dir, reloaded, now=_NOW)

        assert outcome.payload == "/model fable"

    def test_a_retro_attribution_is_written_to_the_decision_log(self, tmp_path: Path) -> None:
        """Review 4 finding 8: the log's last word on the drop was "unattributed
        -- no restore", and then a `/model fable` restore followed."""
        sidecar_dir = tmp_path / "cs"
        machine = _machine(restore_delay=900.0)

        outcome = _latch_then_record(sidecar_dir, machine)

        assert outcome.noop_reason_log is not None
        assert "retroactively" in outcome.noop_reason_log
        assert "fable -> opus" in outcome.noop_reason_log

    def test_a_same_tick_retro_restore_names_the_retro_attribution(self, tmp_path: Path) -> None:
        """With no restore delay the restore is this tick's decision, and its
        own log line is the one that has to say why it is now attributed."""
        sidecar_dir = tmp_path / "cs"
        machine = _machine()

        outcome = _latch_then_record(sidecar_dir, machine)

        assert outcome.payload == "/model fable"
        assert "retroactively" in outcome.reason


class TestHotReloadBackfill:
    """Review 3: an episode exported without its record key gets it back on
    import, from ``attributed_downgrade`` -- but only when that record names
    THIS episode's session and fallback family."""

    @staticmethod
    def _legacy_episode_state(attributed: str) -> dict[str, object]:
        return {
            "last_model_session": _SESSION,
            "last_model_family": "opus",
            "downgrade_episode": f"{_SESSION}:opus",
            "downgrade_from_family": "fable",
            "downgrade_started_ts": _NOW - 100.0,
            "attributed_downgrade": attributed,
            "downgrade_episode_record_ts": None,
        }

    def test_an_episode_open_across_a_hot_reload_still_spends_its_record_on_close(
        self, tmp_path: Path
    ) -> None:
        sidecar_dir = tmp_path / "cs"
        original = _machine()
        _write_downgrade_signal(sidecar_dir, ts=_NOW)
        _drive_fable_to_opus(sidecar_dir, original, now=_NOW)
        legacy_state = original.export_state()
        legacy_state["downgrade_episode_record_id"] = None
        reloaded = _machine()

        reloaded.import_state(legacy_state)

        assert reloaded.export_state()["downgrade_episode_record_id"] == _RECORD_ID
        _show(sidecar_dir, model_id="claude-fable-5", now=_NOW + 2.0)
        _decide(sidecar_dir, reloaded, now=_NOW + 2.0)
        assert reloaded.export_state()["spent_downgrade_record_id"] == _RECORD_ID
        _show(sidecar_dir, model_id="claude-opus-5", now=_NOW + 11.0)
        _decide(sidecar_dir, reloaded, now=_NOW + 11.0)
        assert reloaded.export_state()["downgrade_episode"] is None

    def test_a_legacy_record_ts_state_is_read_as_the_record_key(self) -> None:
        """A worker from before record ids exported `*_record_ts` keys.

        The published record here is a NEWER one, so a backfill from it would
        give a different key: the episode's own exported key must win.
        """
        legacy = self._legacy_episode_state(f"{_SESSION}:fable:opus:uuid-newer-record")
        legacy["downgrade_episode_record_ts"] = _iso(_NOW)
        legacy["spent_downgrade_record_ts"] = "2026-08-27T09:00:00.000Z"
        reloaded = _machine()

        reloaded.import_state(legacy)

        state = reloaded.export_state()
        assert state["downgrade_episode_record_id"] == _iso(_NOW)
        assert state["spent_downgrade_record_id"] == "2026-08-27T09:00:00.000Z"

    def test_the_backfill_ignores_a_record_for_another_session(self, tmp_path: Path) -> None:
        """Backfilling another session's record would spend it on this close,
        and that session's real downgrade would then go unrestored."""
        sidecar_dir = tmp_path / "cs"
        reloaded = _machine()
        reloaded.import_state(
            self._legacy_episode_state(f"{_OTHER_SESSION}:fable:opus:{_RECORD_ID}")
        )
        assert reloaded.export_state()["downgrade_episode_record_id"] is None
        _show(sidecar_dir, model_id="claude-fable-5", now=_NOW)
        _decide(sidecar_dir, reloaded, now=_NOW)

        _write_downgrade_signal(sidecar_dir, ts=_NOW + 20.0, session_id=_OTHER_SESSION)
        _show(sidecar_dir, model_id="claude-fable-5", now=_NOW + 10.0, session_id=_OTHER_SESSION)
        _decide(sidecar_dir, reloaded, now=_NOW + 10.0)
        typed = _typed_between(
            sidecar_dir,
            reloaded,
            start=_NOW + 30.0,
            end=_NOW + 60.0,
            model_id="claude-opus-5",
            session_id=_OTHER_SESSION,
        )

        assert "/model fable" in typed

    def test_the_backfill_ignores_a_record_for_another_fallback_family(
        self, tmp_path: Path
    ) -> None:
        sidecar_dir = tmp_path / "cs"
        reloaded = _machine()
        reloaded.import_state(self._legacy_episode_state(f"{_SESSION}:fable:sonnet:{_RECORD_ID}"))
        assert reloaded.export_state()["downgrade_episode_record_id"] is None
        _show(sidecar_dir, model_id="claude-fable-5", now=_NOW)
        _decide(sidecar_dir, reloaded, now=_NOW)

        _write_downgrade_signal(sidecar_dir, ts=_NOW + 20.0, fallback_family="sonnet")
        typed = _typed_between(
            sidecar_dir, reloaded, start=_NOW + 30.0, end=_NOW + 60.0, model_id="claude-sonnet-5"
        )

        assert "/model fable" in typed

    def test_the_spent_record_id_round_trips_through_export_import(self, tmp_path: Path) -> None:
        """The export/import hop must carry this key every tick, or MAJOR 4
        comes back the moment a worker restarts mid-session."""
        sidecar_dir = tmp_path / "cs"
        machine = _machine()
        _auto_downgrade_then_recovery(sidecar_dir, machine)

        clone = _machine()
        clone.import_state(json.loads(json.dumps(machine.export_state())))

        assert clone.export_state()["spent_downgrade_record_id"] == _RECORD_ID
        _manual_pick_of_opus(sidecar_dir, clone, now=_NOW + 120.0)
        typed = _typed_between(
            sidecar_dir, clone, start=_NOW + 125.0, end=_NOW + 400.0, model_id="claude-opus-5"
        )
        assert _model_commands(typed) == []

    def test_the_attribution_time_round_trips_through_export_import(self, tmp_path: Path) -> None:
        """An untimestamped record's first sighting must survive a reload, or
        the reloaded worker would treat an old record as freshly seen."""
        sidecar_dir = tmp_path / "cs"
        machine = _machine()
        _write_downgrade_signal(sidecar_dir, record_ts="", record_id="offset:7")
        _show(sidecar_dir, model_id="claude-fable-5", now=_NOW)
        _decide(sidecar_dir, machine, now=_NOW)

        clone = _machine()
        clone.import_state(json.loads(json.dumps(machine.export_state())))
        _show(sidecar_dir, model_id="claude-fable-5", now=_NOW + 3000.0)
        _decide(sidecar_dir, clone, now=_NOW + 3000.0)
        _show(sidecar_dir, model_id="claude-opus-5", now=_NOW + 3030.0)
        _decide(sidecar_dir, clone, now=_NOW + 3030.0)

        assert clone.export_state()["downgrade_episode"] is None


class TestReaping:
    def test_a_stale_downgrade_signal_is_reaped(self, tmp_path: Path) -> None:
        """Otherwise a dead session's signal accumulates in the shared dir."""
        sidecar_dir = tmp_path / "cs"
        path = _write_downgrade_signal(sidecar_dir)
        ancient = _NOW - 10_000_000.0
        os.utime(path, (ancient, ancient))

        reaped = _mod.reap_stale_sidecars(sidecar_dir, now=_NOW, ttl_seconds=60.0)

        assert path in reaped
