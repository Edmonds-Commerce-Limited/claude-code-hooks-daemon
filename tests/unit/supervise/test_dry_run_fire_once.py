"""Plan 00183 — dry-run fires once per session, once only.

The state machine is pure and identical in dry-run and armed modes; the only
divergence is environment feedback. In armed mode a ``WOULD_COMPACT`` injects a
real ``/compact`` that actually compacts, so the episode resolves. In dry-run
the marker is a no-op on the environment, so context stays red and the machine
would re-decide to act every episode -- flooding the session with fake prompts.

The fix: a process-lifetime latch on ``CompactStateMachine`` (carried in the
exported machine state so it round-trips through the policy worker). The FIRST
dry-run tick that would inject a marker fires it; every subsequent dry-run tick
suppresses the payload. Armed mode is untouched.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from tests.unit.supervise._load import load_supervisor_module

if TYPE_CHECKING:
    from pathlib import Path

_mod = load_supervisor_module()


def _urgent_sidecar_payload(now: float) -> dict[str, object]:
    return {
        "red": True,
        "critical": True,
        "compact_urgent": True,
        "tier": "critical",
        "pct": 96.0,
        "session_id": "fg",
        "ts": now,
        "seq": 1,
        "writer_pid": 1,
        "compacting": False,
    }


def _write_urgent_sidecar(sidecar_dir: Path, *, now: float) -> None:
    sidecar_dir.mkdir(parents=True, exist_ok=True)
    (sidecar_dir / "fg.json").write_text(json.dumps(_urgent_sidecar_payload(now)), encoding="utf-8")


def _idle_facts(now: float, machine_state: dict[str, object] | None = None) -> object:
    return _mod.TickFacts(
        now_wall=now,
        idle=True,
        input_line_empty=True,
        human_compact_submitted=False,
        work_idle=True,
        machine_state=machine_state,
    )


class TestDryRunLatchState:
    def test_latch_defaults_off(self) -> None:
        machine = _mod.CompactStateMachine(_mod.CompactPolicy())
        assert machine.dry_run_fired is False

    def test_mark_sets_latch(self) -> None:
        machine = _mod.CompactStateMachine(_mod.CompactPolicy())
        machine.mark_dry_run_fired()
        assert machine.dry_run_fired is True

    def test_latch_survives_export_import_roundtrip(self) -> None:
        src = _mod.CompactStateMachine(_mod.CompactPolicy())
        src.mark_dry_run_fired()
        state = src.export_state()
        assert state["dry_run_fired"] is True

        dst = _mod.CompactStateMachine(_mod.CompactPolicy())
        dst.import_state(state)
        assert dst.dry_run_fired is True
        assert dst.export_state() == state


class TestDryRunFiresOnce:
    def test_first_dry_run_tick_fires_and_latches(self, tmp_path: Path) -> None:
        sidecar_dir = tmp_path / "context-sidecar"
        _write_urgent_sidecar(sidecar_dir, now=1000.0)
        policy = _mod.CompactPolicy()

        outcome = _mod.decide_once(
            _mod.CompactStateMachine(policy),
            sidecar_dir=sidecar_dir,
            facts=_idle_facts(1000.0),
            dry_run=True,
            freshness_seconds=policy.freshness_seconds,
        )

        assert outcome.decision_value == _mod.Decision.WOULD_COMPACT.value
        assert outcome.payload is not None
        # The latch is recorded in the returned state so it round-trips to the host.
        assert outcome.machine_state["dry_run_fired"] is True

    def test_second_dry_run_tick_is_suppressed(self, tmp_path: Path) -> None:
        sidecar_dir = tmp_path / "context-sidecar"
        _write_urgent_sidecar(sidecar_dir, now=1000.0)
        policy = _mod.CompactPolicy()

        first = _mod.decide_once(
            _mod.CompactStateMachine(policy),
            sidecar_dir=sidecar_dir,
            facts=_idle_facts(1000.0),
            dry_run=True,
            freshness_seconds=policy.freshness_seconds,
        )
        assert first.payload is not None

        # A fresh machine seeded with the carried state (the worker/host pattern):
        # 61s later the machine WOULD escape-flush, but the once-only latch
        # suppresses the payload so nothing is injected.
        second = _mod.decide_once(
            _mod.CompactStateMachine(policy),
            sidecar_dir=sidecar_dir,
            facts=_idle_facts(1061.0, machine_state=first.machine_state),
            dry_run=True,
            freshness_seconds=policy.freshness_seconds,
        )
        assert second.decision_value == _mod.Decision.WOULD_ESCAPE.value
        assert second.payload is None
        assert second.noop_reason_log is not None
        assert "dry-run" in second.noop_reason_log


class TestArmedModeUnaffected:
    def test_armed_mode_injects_each_episode_and_never_latches(self, tmp_path: Path) -> None:
        sidecar_dir = tmp_path / "context-sidecar"
        _write_urgent_sidecar(sidecar_dir, now=1000.0)
        policy = _mod.CompactPolicy()

        first = _mod.decide_once(
            _mod.CompactStateMachine(policy),
            sidecar_dir=sidecar_dir,
            facts=_idle_facts(1000.0),
            dry_run=False,
            freshness_seconds=policy.freshness_seconds,
        )
        assert first.decision_value == _mod.Decision.WOULD_COMPACT.value
        assert first.payload is not None
        # Armed mode NEVER touches the dry-run latch.
        assert first.machine_state["dry_run_fired"] is False

        second = _mod.decide_once(
            _mod.CompactStateMachine(policy),
            sidecar_dir=sidecar_dir,
            facts=_idle_facts(1061.0, machine_state=first.machine_state),
            dry_run=False,
            freshness_seconds=policy.freshness_seconds,
        )
        assert second.decision_value == _mod.Decision.WOULD_ESCAPE.value
        # Armed ESC still injects (the real interrupt key), not suppressed.
        assert second.payload is not None
