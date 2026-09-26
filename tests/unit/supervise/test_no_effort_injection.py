"""Plan 00466 N47: the supervisor never TYPES an `/effort` command, on any path.

Claude Code saves every interactively typed `/effort <level>` into the owner's
own `settings.json` (`modelSettings`), so any level the supervisor typed would
overwrite the single source of truth the owner configures effort in. N47
removed both injections that used to do it -- the Fable "DROP ANCHOR"
(`/effort low` whenever Fable ran above low) and the downgrade compensation
(`/effort xhigh` on the fallback model) -- and this file is what stops either
coming back.

Every test drives the real decision path (`decide_once` on a persistent
machine, or `run_worker` over the JSON tick stream) through a scenario that
USED to produce an `/effort` payload, and asserts on the PAYLOADS: nothing
typed may start with `/effort`. Each scenario also asserts it actually
exercised its path (the restore fired, the compaction ran), so a scenario
that silently stops reaching its branch fails instead of passing vacuously.
"""

from __future__ import annotations

import base64
import io
import json
from typing import TYPE_CHECKING, cast

import pytest

from tests.unit.supervise._load import load_supervisor_module
from tests.unit.supervise.conftest import write_attributed_downgrade

if TYPE_CHECKING:
    from pathlib import Path

    from tests.unit.supervise._load import SupervisorStateMachine, SupervisorTickOutcome

_mod = load_supervisor_module()

_SESSION = "no-effort-sess"
_OTHER_SESSION = "no-effort-other"
_NOW = 30_000.0
_TICK = 30.0
_EFFORT_PREFIX = "/effort"


def _facts(now: float, *, raw: bytes = b"", idle: bool = True) -> object:
    return _mod.TickFacts(
        now_wall=now,
        idle=idle,
        input_line_empty=True,
        human_compact_submitted=False,
        work_idle=True,
        human_raw_input=base64.b64encode(raw).decode("ascii"),
    )


def _write_sidecar(
    sidecar_dir: Path,
    *,
    model_id: str,
    effort: str | None,
    ts: float,
    session_id: str = _SESSION,
    pct: float = 20.0,
    urgent: bool = False,
) -> None:
    sidecar_dir.mkdir(parents=True, exist_ok=True)
    (sidecar_dir / f"{session_id}.json").write_text(
        json.dumps(
            {
                "red": urgent,
                "critical": False,
                "compact_urgent": urgent,
                "tier": "urgent" if urgent else "ok",
                "pct": pct,
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


def _machine(restore_delay: float | None = None) -> SupervisorStateMachine:
    policy = (
        _mod.CompactPolicy()
        if restore_delay is None
        else _mod.CompactPolicy(model_restore_delay_seconds=restore_delay)
    )
    return cast("SupervisorStateMachine", _mod.CompactStateMachine(policy))


def _decide(
    sidecar_dir: Path, machine: SupervisorStateMachine, now: float
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
            own_sessions=frozenset({_SESSION, _OTHER_SESSION}),
        ),
    )


def _typed(outcomes: list[SupervisorTickOutcome]) -> list[str]:
    return [outcome.payload for outcome in outcomes if outcome.payload is not None]


def _assert_no_effort_typed(typed: list[str]) -> None:
    effort_lines = [line for line in typed if line.lstrip().startswith(_EFFORT_PREFIX)]
    assert effort_lines == [], f"the supervisor typed an effort command: {effort_lines}"


@pytest.mark.parametrize("effort", ["medium", "high", "xhigh", "max"])
def test_fable_running_above_low_is_never_anchored_back_down(tmp_path: Path, effort: str) -> None:
    """The removed DROP ANCHOR typed `/effort low` whenever Fable ran above low.

    Fable's level is the owner's `modelSettings` entry (or a level they chose
    themselves this session); the supervisor has no opinion on it at all. An
    idle, empty-box session is exactly where the anchor used to fire.
    """
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    outcomes = []
    for step in range(6):
        now = _NOW + step * _TICK
        _write_sidecar(sidecar_dir, model_id="claude-fable-5-1", effort=effort, ts=now - 1.0)
        outcomes.append(_decide(sidecar_dir, machine, now))

    _assert_no_effort_typed(_typed(outcomes))
    assert _typed(outcomes) == []


def test_a_whole_attributed_downgrade_episode_types_only_model_commands(tmp_path: Path) -> None:
    """Downgrade, restore, recovery: the old compensation typed `/effort xhigh`.

    The fallback model's level is the owner's `modelSettings` entry for it.
    The episode's only injections are the `/model fable` restore and its
    confirming Enters.
    """
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    outcomes = []
    _write_sidecar(sidecar_dir, model_id="claude-fable-5-1", effort="low", ts=_NOW - 1.0)
    outcomes.append(_decide(sidecar_dir, machine, _NOW))
    write_attributed_downgrade(sidecar_dir, session_id=_SESSION)
    for step in range(1, 5):
        now = _NOW + step * _TICK
        _write_sidecar(sidecar_dir, model_id="claude-opus-4-8", effort="high", ts=now - 1.0)
        outcomes.append(_decide(sidecar_dir, machine, now))
    # The restore lands; the session is back on Fable at whatever level
    # Claude Code resolved for it.
    for step in range(5, 9):
        now = _NOW + step * _TICK
        _write_sidecar(sidecar_dir, model_id="claude-fable-5-1", effort="xhigh", ts=now - 1.0)
        outcomes.append(_decide(sidecar_dir, machine, now))

    typed = _typed(outcomes)
    _assert_no_effort_typed(typed)
    assert "/model fable" in typed
    assert machine.export_state()["downgrade_episode"] is None


def test_a_manual_model_pick_draws_no_injection_of_any_kind(tmp_path: Path) -> None:
    """The human picks Opus from Fable: no record, so no episode and no typing.

    Before N47 a manual `/model` also drew a "coupled" `/effort` correction.
    """
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    outcomes = []
    _write_sidecar(sidecar_dir, model_id="claude-fable-5-1", effort="low", ts=_NOW - 1.0)
    outcomes.append(_decide(sidecar_dir, machine, _NOW))
    for step in range(1, 8):
        now = _NOW + step * _TICK
        _write_sidecar(sidecar_dir, model_id="claude-opus-5-5", effort="medium", ts=now - 1.0)
        outcomes.append(_decide(sidecar_dir, machine, now))

    assert _typed(outcomes) == []


def test_the_operator_model_switch_signal_types_only_the_model_command(tmp_path: Path) -> None:
    """The `/model` test trigger: `/model opus` and its Enters, never a level."""
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    outcomes = []
    _write_sidecar(sidecar_dir, model_id="claude-fable-5-1", effort="low", ts=_NOW - 1.0)
    outcomes.append(_decide(sidecar_dir, machine, _NOW))
    _mod.write_model_switch_signal(sidecar_dir, session_id=_SESSION, family="opus", now=_NOW)
    for step in range(1, 6):
        now = _NOW + step * _TICK
        model_id = "claude-fable-5-1" if step == 1 else "claude-opus-5"
        _write_sidecar(sidecar_dir, model_id=model_id, effort="xhigh", ts=now - 1.0)
        outcomes.append(_decide(sidecar_dir, machine, now))

    typed = _typed(outcomes)
    _assert_no_effort_typed(typed)
    assert "/model opus" in typed


def test_a_compaction_and_its_resume_type_no_effort(tmp_path: Path) -> None:
    """Compaction resets nothing about effort, so nothing re-asserts one after."""
    sidecar_dir = tmp_path / "cs"
    machine = _machine()
    outcomes = []
    _write_sidecar(
        sidecar_dir, model_id="claude-fable-5-1", effort="high", ts=_NOW - 1.0, urgent=True
    )
    outcomes.append(_decide(sidecar_dir, machine, _NOW))
    compacting = sidecar_dir / f"{_SESSION}.compacting"
    compacting.write_text(
        json.dumps({"ts": _NOW + _TICK, "session_id": _SESSION, "origin": "supervisor"}),
        encoding="utf-8",
    )
    outcomes.append(_decide(sidecar_dir, machine, _NOW + _TICK))
    compacting.unlink()
    for step in range(2, 8):
        now = _NOW + step * _TICK
        _write_sidecar(sidecar_dir, model_id="claude-fable-5-1", effort="high", ts=now - 1.0)
        outcomes.append(_decide(sidecar_dir, machine, now))

    typed = _typed(outcomes)
    _assert_no_effort_typed(typed)
    assert any(line.startswith("/compact ") for line in typed)
    assert any(line.endswith("] continue") for line in typed)


def test_a_human_typed_effort_through_the_raw_input_tap_is_never_echoed_or_corrected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The human types `/effort max` themselves; the worker must not answer it.

    Driven end to end through `run_worker`'s JSON tick stream, the path the
    live worker takes, with the typed bytes arriving on the raw-input tap.
    """
    monkeypatch.setattr(_mod, "cached_own_session_ids", lambda: frozenset({_SESSION}))
    sidecar_dir = tmp_path / "cs"
    _write_sidecar(sidecar_dir, model_id="claude-fable-5-1", effort="max", ts=_NOW + 200.0)
    ticks = [_mod._facts_to_json(_facts(_NOW, raw=b"/effort max\r", idle=False))]
    ticks += [_mod._facts_to_json(_facts(_NOW + step * 10.0)) for step in range(1, 8)]
    out_stream = io.StringIO()

    _mod.run_worker(
        io.StringIO("\n".join(ticks) + "\n"),
        out_stream,
        dry_run=False,
        sidecar_dir=sidecar_dir,
        policy=_mod.CompactPolicy(),
    )

    outcomes = [
        _mod._outcome_from_json(line) for line in out_stream.getvalue().splitlines() if line
    ]
    assert len(outcomes) == len(ticks)
    typed = [outcome.payload for outcome in outcomes if outcome.payload is not None]
    assert typed == []
