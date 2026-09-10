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
from typing import TYPE_CHECKING

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
                "record_ts": "2026-08-27T09:34:10.341Z",
            }
        ),
        encoding="utf-8",
    )
    return path


def _machine() -> SupervisorStateMachine:
    return _mod.CompactStateMachine(_mod.CompactPolicy())


def _decide(
    sidecar_dir: Path, machine: SupervisorStateMachine, *, now: float = _NOW
) -> SupervisorTickOutcome:
    policy = _mod.CompactPolicy()
    return _mod.decide_once(
        machine,
        sidecar_dir=sidecar_dir,
        facts=_facts(now),
        dry_run=False,
        freshness_seconds=policy.freshness_seconds,
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

        assert found == (_SESSION, "fable", "opus")

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


class TestReaping:
    def test_a_stale_downgrade_signal_is_reaped(self, tmp_path: Path) -> None:
        """Otherwise a dead session's signal accumulates in the shared dir."""
        sidecar_dir = tmp_path / "cs"
        path = _write_downgrade_signal(sidecar_dir)
        ancient = _NOW - 10_000_000.0
        os.utime(path, (ancient, ancient))

        reaped = _mod.reap_stale_sidecars(sidecar_dir, now=_NOW, ttl_seconds=60.0)

        assert path in reaped
