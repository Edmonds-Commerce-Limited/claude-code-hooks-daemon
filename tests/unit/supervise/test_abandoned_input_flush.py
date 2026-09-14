"""Plan 00398 Phase 3 — acting on an abandoned input box.

The state-machine-level behaviour (`CompactStateMachine.evaluate`) is covered
by `TestAbandonedInputBoxFlush` in test_compact_state_machine.py. This file
covers the layers ABOVE the machine: `decide_once`'s wiring of
`TickFacts.input_line_abandoned`, `_poll_once`'s caller-side flush callback,
`run_worker`'s own recognizer reset, and an end-to-end `supervise()` run --
because the flush's own injected Enter never passes through the tracked
`HumanInputLine` (same as every other supervisor keystroke), each of these
layers has its own responsibility to reset the model it owns, and a gap at
any one of them reopens the unbounded gate this plan exists to close.
"""

from __future__ import annotations

import base64
import io
import json
import os
from typing import TYPE_CHECKING

from tests.unit.supervise._load import load_supervisor_module

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

_mod = load_supervisor_module()
Decision = _mod.Decision
CompactPolicy = _mod.CompactPolicy
CompactStateMachine = _mod.CompactStateMachine
DecisionLog = _mod.DecisionLog
HumanInputLine = _mod.HumanInputLine
InputActivity = _mod.InputActivity
TickFacts = _mod.TickFacts

_ENTER = b"\r"


def _write_sidecar(directory: Path, *, critical: bool = False, ts: float = 1000.0) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "s.json").write_text(
        json.dumps(
            {
                "red": True,
                "critical": critical,
                "compact_urgent": True,
                "tier": "critical" if critical else "red",
                "pct": 95.0 if critical else 90.0,
                "session_id": "s",
                "ts": ts,
                "seq": 1,
                "writer_pid": 1,
            }
        ),
        encoding="utf-8",
    )


class TestDecideOnceAbandonedBoxFlush:
    """`decide_once` wires `TickFacts.input_line_abandoned` into the machine."""

    def test_abandoned_and_busy_fires_resubmit_with_flag_set(self, tmp_path: Path) -> None:
        sc = tmp_path / "sc"
        _write_sidecar(sc)
        facts = TickFacts(
            now_wall=1000.0,
            idle=True,
            input_line_empty=False,
            human_compact_submitted=False,
            work_idle=True,
            input_line_abandoned=True,
        )
        outcome = _mod.decide_once(
            CompactStateMachine(CompactPolicy()),
            sidecar_dir=sc,
            facts=facts,
            dry_run=False,
            freshness_seconds=30.0,
        )
        assert outcome.decision_value == Decision.WOULD_RESUBMIT.value
        assert outcome.abandoned_box_flushed is True
        # The EXISTING resubmit machinery: a raw, unframed Enter -- not a new
        # keystroke path.
        assert outcome.payload == "\r"
        assert outcome.submit is False

    def test_abandoned_but_not_reported_by_facts_keeps_deferring(self, tmp_path: Path) -> None:
        sc = tmp_path / "sc"
        _write_sidecar(sc)
        facts = TickFacts(
            now_wall=1000.0,
            idle=True,
            input_line_empty=False,
            human_compact_submitted=False,
            work_idle=True,
            input_line_abandoned=False,
        )
        outcome = _mod.decide_once(
            CompactStateMachine(CompactPolicy()),
            sidecar_dir=sc,
            facts=facts,
            dry_run=False,
            freshness_seconds=30.0,
        )
        assert outcome.decision_value == Decision.NOOP.value
        assert outcome.abandoned_box_flushed is False
        assert outcome.deferred_log is not None


class TestPollOnceFlushCallback:
    """`_poll_once` must tell its caller to reset the tracked box on flush."""

    def test_callback_fires_exactly_when_outcome_flushed(self, tmp_path: Path) -> None:
        sc = tmp_path / "sc"
        _write_sidecar(sc)
        calls: list[None] = []
        ev = _mod._poll_once(
            CompactStateMachine(CompactPolicy()),
            sidecar_dir=sc,
            now_wall=1000.0,
            idle=False,
            dry_run=True,
            master_writer=lambda _b: None,
            log=None,
            freshness_seconds=30.0,
            input_line_empty=False,
            input_line_abandoned=True,
            on_input_line_flushed=lambda: calls.append(None),
        )
        assert ev.decision is Decision.WOULD_RESUBMIT
        assert len(calls) == 1

    def test_callback_not_called_on_ordinary_deferral(self, tmp_path: Path) -> None:
        sc = tmp_path / "sc"
        _write_sidecar(sc)
        calls: list[None] = []
        _mod._poll_once(
            CompactStateMachine(CompactPolicy()),
            sidecar_dir=sc,
            now_wall=1000.0,
            idle=False,
            dry_run=True,
            master_writer=lambda _b: None,
            log=None,
            freshness_seconds=30.0,
            input_line_empty=False,
            input_line_abandoned=False,
            on_input_line_flushed=lambda: calls.append(None),
        )
        assert calls == []

    def test_omitted_callback_does_not_raise(self, tmp_path: Path) -> None:
        sc = tmp_path / "sc"
        _write_sidecar(sc)
        ev = _mod._poll_once(
            CompactStateMachine(CompactPolicy()),
            sidecar_dir=sc,
            now_wall=1000.0,
            idle=False,
            dry_run=True,
            master_writer=lambda _b: None,
            log=None,
            freshness_seconds=30.0,
            input_line_empty=False,
            input_line_abandoned=True,
        )
        assert ev.decision is Decision.WOULD_RESUBMIT


class TestRunWorkerClearsOwnRecognizer:
    """The worker's own `HumanInputLine` must not stay stuck non-empty."""

    def test_flush_clears_worker_recognizer_so_the_next_tick_can_compact(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sc = tmp_path / "sc"
        monkeypatch.setattr(_mod, "cached_own_session_ids", lambda *a, **k: frozenset({"s"}))
        _write_sidecar(sc, critical=True)
        # Prime the worker's OWN recognizer with the same "abandoned" text a
        # real human would have left, via the raw-input tap.
        raw = base64.b64encode(b"forgotten message").decode("ascii")
        tick1 = TickFacts(
            now_wall=1000.0,
            idle=False,
            input_line_empty=False,
            human_compact_submitted=False,
            work_idle=True,
            human_raw_input=raw,
            input_line_abandoned=True,
        )
        # Box now reads empty from the HOST's side (it cleared its own model
        # too) and no new bytes arrive -- only the worker's OWN (unless reset)
        # recognizer could still wrongly hold it non-empty.
        tick2 = TickFacts(
            now_wall=1002.0,
            idle=True,
            input_line_empty=True,
            human_compact_submitted=False,
            work_idle=True,
            input_line_abandoned=False,
        )
        in_stream = io.StringIO(
            _mod._facts_to_json(tick1) + "\n" + _mod._facts_to_json(tick2) + "\n"
        )
        out_stream = io.StringIO()
        _mod.run_worker(in_stream, out_stream, dry_run=True, sidecar_dir=sc, policy=CompactPolicy())
        outcomes = [
            _mod._outcome_from_json(ln) for ln in out_stream.getvalue().splitlines() if ln.strip()
        ]
        assert len(outcomes) == 2
        assert outcomes[0].decision_value == Decision.WOULD_RESUBMIT.value
        assert outcomes[0].abandoned_box_flushed is True
        # Without the reset this would still be NOOP (worker's own is_empty
        # ANDing the box back to non-empty forever).
        assert outcomes[1].decision_value == Decision.WOULD_COMPACT.value


class TestSuperviseEndToEndAbandonedFlush:
    """`supervise()` submits an abandoned message, then compacts, once."""

    def _run(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
        sidecar_dir = tmp_path / "sc"
        monkeypatch.setattr(_mod, "cached_own_session_ids", lambda *a, **k: frozenset({"s"}))
        _write_sidecar(sidecar_dir, critical=True, ts=1_000_000_000.0)
        # Freeze the sidecar's own freshness clock far in the future relative
        # to `ts` so `time.time()` (used by `_on_poll`) still reads it fresh --
        # simplest is a huge freshness window instead of monkeypatching time.
        log = DecisionLog(tmp_path / "decision.log")

        read_fd, write_fd = os.pipe()
        os.write(write_fd, b"forgot to hit enter")
        os.close(write_fd)
        try:
            code = _mod.supervise(
                ["bash", "-lc", "sleep 0.5; exit 0"],
                # Armed, not dry-run: Plan 00183's dry-run latch fires ONCE per
                # session for ANY payload type, so a dry-run resubmit would
                # itself suppress the compact that is meant to follow it --
                # unrelated to this feature, but it means only armed mode can
                # exercise the two-step chain end-to-end.
                dry_run=False,
                log=log,
                activity=InputActivity(),
                stdin_fd=read_fd,
                sidecar_dir=sidecar_dir,
                poll_seconds=0.02,
                idle_floor_seconds=0.0,
                input_line_abandon_seconds=0.05,
                policy=CompactPolicy(freshness_seconds=1e12),
            )
        finally:
            os.close(read_fd)
        assert code == 0
        return (tmp_path / "decision.log").read_text(encoding="utf-8")

    def test_abandoned_message_is_submitted_then_compacted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        contents = self._run(tmp_path, monkeypatch)
        assert f"{Decision.WOULD_RESUBMIT.value}:" in contents
        assert f"{Decision.WOULD_COMPACT.value}:" in contents
        # Exactly one flush for the one abandoned episode.
        assert contents.count(f"{Decision.WOULD_RESUBMIT.value}:") == 1
