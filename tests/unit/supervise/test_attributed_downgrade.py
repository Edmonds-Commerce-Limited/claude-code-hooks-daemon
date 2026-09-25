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
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING, cast

from tests.unit.supervise._load import load_supervisor_module

if TYPE_CHECKING:
    from pathlib import Path

    from tests.unit.supervise._load import SupervisorStateMachine, SupervisorTickOutcome

_mod = load_supervisor_module()

_NOW = 50_000.0
_SESSION = "attributed-sess-1"


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
    record_ts: str = "2026-08-27T09:34:10.341Z",
) -> Path:
    """Write what the daemon's model_downgrade_recorder publishes."""
    sidecar_dir.mkdir(parents=True, exist_ok=True)
    path = sidecar_dir / f"{session_id}{_mod._MODEL_DOWNGRADE_SIGNAL_SUFFIX}"
    path.write_text(
        json.dumps(
            {
                "ts": ts,
                "session_id": session_id,
                "original_model": "claude-fable-5",
                "fallback_model": "claude-opus-4-8",
                "original_family": original_family,
                "fallback_family": fallback_family,
                "category": "cyber",
                "scope": "session",
                "record_ts": record_ts,
            }
        ),
        encoding="utf-8",
    )
    return path


def _machine() -> SupervisorStateMachine:
    return cast("SupervisorStateMachine", _mod.CompactStateMachine(_mod.CompactPolicy()))


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


class TestTheSignalLoader:
    def test_an_in_scope_signal_yields_its_families(self, tmp_path: Path) -> None:
        sidecar_dir = tmp_path / "cs"
        _write_downgrade_signal(sidecar_dir)

        found = _mod.load_model_downgrade_signal(sidecar_dir, own_sessions=frozenset({_SESSION}))

        assert found == (_SESSION, "fable", "opus", "2026-08-27T09:34:10.341Z")

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

    ``model_downgrade_recorder`` republishes the SAME record (same
    ``record_ts``) for the rest of the session, even after the episode it
    described has been fully recovered from. Before this fix, a human who
    later manually switched back to the fallback family produced the exact
    observation (fable, then opus, in this session) the old
    ``session:from:to`` attribution key matched again -- reopening an episode
    and firing ``/model fable`` at a human who had just chosen otherwise.
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

        # The recorder's signal file is still on disk with the SAME record_ts
        # (Claude Code does not clear it), and the human now manually drops
        # back to opus -- the identical (fable, then opus) observation.
        _write_sidecar(sidecar_dir, model_id="claude-opus-5", effort="high", ts=_NOW + 10.0)
        _decide(sidecar_dir, machine, now=_NOW + 11.0)

        assert machine.export_state()["downgrade_episode"] is None

    def test_a_genuinely_new_downgrade_with_a_fresh_record_ts_still_reopens(
        self, tmp_path: Path
    ) -> None:
        sidecar_dir = tmp_path / "cs"
        machine = _machine()
        _write_downgrade_signal(
            sidecar_dir, ts=_NOW, session_id=_SESSION, record_ts="2026-08-27T09:00:00.000Z"
        )

        _drive_fable_to_opus(sidecar_dir, machine, now=_NOW)
        assert machine.export_state()["downgrade_episode"] is not None
        _write_sidecar(sidecar_dir, model_id="claude-fable-5", effort="low", ts=_NOW + 1.0)
        _decide(sidecar_dir, machine, now=_NOW + 2.0)
        assert machine.export_state()["downgrade_episode"] is None

        # A REAL second downgrade: a new transcript record, a new record_ts.
        _write_downgrade_signal(
            sidecar_dir, ts=_NOW + 5.0, session_id=_SESSION, record_ts="2026-08-27T10:00:00.000Z"
        )
        _write_sidecar(sidecar_dir, model_id="claude-opus-5", effort="high", ts=_NOW + 10.0)
        _decide(sidecar_dir, machine, now=_NOW + 11.0)

        assert machine.export_state()["downgrade_episode"] is not None


class TestReview3Edges:
    """Plan 00466 N47 review 3, item 4 (the four MAJOR-4 gaps)."""

    def test_a_reading_that_renders_before_its_record_is_attributed_once_the_record_arrives(
        self, tmp_path: Path
    ) -> None:
        """Item C: the reading can render one tick before the recorder
        publishes its signal (both write on the same PostToolUse-adjacent
        window, in either order). The old code judged the drop unattributed
        on that first tick and never looked again, since nothing about the
        family changes on the later tick the record actually arrives."""
        sidecar_dir = tmp_path / "cs"
        machine = _machine()
        _write_sidecar(sidecar_dir, model_id="claude-fable-5", effort="low", ts=_NOW - 5.0)
        _decide(sidecar_dir, machine, now=_NOW - 4.0)

        # The reading shows opus BEFORE any downgrade signal exists on disk.
        _write_sidecar(sidecar_dir, model_id="claude-opus-5", effort="high", ts=_NOW - 3.0)
        first = _decide(sidecar_dir, machine, now=_NOW - 2.0)
        assert first.noop_reason_log is not None
        assert "unattributed" in first.noop_reason_log
        assert machine.export_state()["downgrade_episode"] is None

        # The record arrives now, one tick later, with the session STILL on
        # opus (same sidecar reading, no new render needed).
        _write_downgrade_signal(sidecar_dir, ts=_NOW - 1.0, session_id=_SESSION)
        _decide(sidecar_dir, machine, now=_NOW)

        assert machine.export_state()["downgrade_episode"] is not None

    def test_the_latch_is_dropped_if_the_session_leaves_the_fallback_before_the_record_arrives(
        self, tmp_path: Path
    ) -> None:
        """The bridging window has a natural end: if the human moves off the
        fallback family before the record ever shows up, a later record must
        not retroactively resurrect a stale episode."""
        sidecar_dir = tmp_path / "cs"
        machine = _machine()
        _write_sidecar(sidecar_dir, model_id="claude-fable-5", effort="low", ts=_NOW - 5.0)
        _decide(sidecar_dir, machine, now=_NOW - 4.0)
        _write_sidecar(sidecar_dir, model_id="claude-opus-5", effort="high", ts=_NOW - 3.0)
        _decide(sidecar_dir, machine, now=_NOW - 2.0)
        assert machine.export_state()["downgrade_episode"] is None

        # The human moves to sonnet -- never mind, no record ever showed up.
        _write_sidecar(sidecar_dir, model_id="claude-sonnet-5", effort="high", ts=_NOW - 1.0)
        _decide(sidecar_dir, machine, now=_NOW)

        # A stale/unrelated record for the ORIGINAL fable->opus drop now
        # appears -- it must not open anything; the window already closed.
        _write_downgrade_signal(sidecar_dir, ts=_NOW + 1.0, session_id=_SESSION)
        _decide(sidecar_dir, machine, now=_NOW + 2.0)

        assert machine.export_state()["downgrade_episode"] is None

    def test_an_empty_record_ts_does_not_block_a_later_empty_record_ts_downgrade(
        self, tmp_path: Path
    ) -> None:
        """Item E: `record_ts` falls back to `""` when the transcript record
        has no timestamp. Spending `""` as though it were a real record_ts
        would refuse EVERY later untimestamped downgrade in the session."""
        sidecar_dir = tmp_path / "cs"
        machine = _machine()
        _write_downgrade_signal(sidecar_dir, ts=_NOW, session_id=_SESSION, record_ts="")

        _drive_fable_to_opus(sidecar_dir, machine, now=_NOW)
        assert machine.export_state()["downgrade_episode"] is not None
        _write_sidecar(sidecar_dir, model_id="claude-fable-5", effort="low", ts=_NOW + 1.0)
        _decide(sidecar_dir, machine, now=_NOW + 2.0)
        assert machine.export_state()["downgrade_episode"] is None
        assert machine.export_state()["spent_downgrade_record_ts"] is None

        # A SECOND, genuinely new downgrade whose record also carries no
        # timestamp -- it must still open a fresh episode.
        _write_downgrade_signal(sidecar_dir, ts=_NOW + 5.0, session_id=_SESSION, record_ts="")
        _write_sidecar(sidecar_dir, model_id="claude-opus-5", effort="high", ts=_NOW + 10.0)
        _decide(sidecar_dir, machine, now=_NOW + 11.0)

        assert machine.export_state()["downgrade_episode"] is not None

    def test_an_episode_open_across_a_hot_reload_still_spends_its_record_on_close(
        self, tmp_path: Path
    ) -> None:
        """Item: an episode opened by an OLDER worker (or a legacy payload
        with `downgrade_episode_record_ts` stripped) has no record_ts to
        spend when a fresh worker later closes it. Backfilled from
        `attributed_downgrade`, which the daemon's signal keeps supplying,
        as long as it still names this exact open episode."""
        sidecar_dir = tmp_path / "cs"
        original = _machine()
        _write_downgrade_signal(sidecar_dir, ts=_NOW, session_id=_SESSION)
        _drive_fable_to_opus(sidecar_dir, original, now=_NOW)
        assert original.export_state()["downgrade_episode"] is not None

        # Simulate a hot reload that lost `downgrade_episode_record_ts` --
        # legacy state, or a pre-fix export.
        legacy_state = original.export_state()
        legacy_state["downgrade_episode_record_ts"] = None
        reloaded = _machine()
        reloaded.import_state(legacy_state)
        assert reloaded.export_state()["downgrade_episode_record_ts"] is not None  # backfilled

        # Close it (family recovers), and confirm the record was genuinely
        # spent -- not silently dropped.
        _write_sidecar(sidecar_dir, model_id="claude-fable-5", effort="low", ts=_NOW + 1.0)
        _decide(sidecar_dir, reloaded, now=_NOW + 2.0)
        assert reloaded.export_state()["downgrade_episode"] is None
        assert reloaded.export_state()["spent_downgrade_record_ts"] is not None

        # The MAJOR 4 regression does not recur: the same still-published
        # record does not reopen the episode on a later manual drop back.
        _write_sidecar(sidecar_dir, model_id="claude-opus-5", effort="high", ts=_NOW + 10.0)
        _decide(sidecar_dir, reloaded, now=_NOW + 11.0)
        assert reloaded.export_state()["downgrade_episode"] is None

    def test_spent_downgrade_record_ts_round_trips_through_export_import(
        self, tmp_path: Path
    ) -> None:
        """The export/import hop must carry this key every tick, or MAJOR 4
        comes back the moment a worker restarts mid-session."""
        sidecar_dir = tmp_path / "cs"
        machine = _machine()
        _write_downgrade_signal(sidecar_dir, ts=_NOW, session_id=_SESSION)
        _drive_fable_to_opus(sidecar_dir, machine, now=_NOW)
        _write_sidecar(sidecar_dir, model_id="claude-fable-5", effort="low", ts=_NOW + 1.0)
        _decide(sidecar_dir, machine, now=_NOW + 2.0)
        spent = machine.export_state()["spent_downgrade_record_ts"]
        assert spent is not None

        clone = _machine()
        clone.import_state(machine.export_state())
        assert clone.export_state()["spent_downgrade_record_ts"] == spent

        # And the clone genuinely honours it: no reopen on a later manual drop.
        _write_sidecar(sidecar_dir, model_id="claude-opus-5", effort="high", ts=_NOW + 10.0)
        _decide(sidecar_dir, clone, now=_NOW + 11.0)
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
