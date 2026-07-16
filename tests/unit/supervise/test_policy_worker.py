"""Plan 00164 Phase 4 — restartable policy-worker split.

The supervisor's decision logic (``decide_once`` + the state machine) runs in a
``--worker`` subprocess so it can be hot-reloaded from a freshly-deployed
``claude-supervise.py`` WITHOUT restarting the PTY host that owns ``claude``.
Host and worker exchange line-delimited JSON (``TickFacts`` → ``TickOutcome``);
anything that goes wrong falls back to an identical in-process decision.
"""

from __future__ import annotations

import io
import json
import os
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from tests.unit.supervise._load import SCRIPT_PATH, load_supervisor_module

if TYPE_CHECKING:
    from pathlib import Path

_mod = load_supervisor_module()


def _idle_facts(now: float = 1000.0) -> object:
    return _mod.TickFacts(
        now_wall=now,
        idle=True,
        input_line_empty=True,
        human_compact_submitted=False,
        work_idle=True,
    )


# ── Serialization round-trips ────────────────────────────────────────────────


def test_facts_json_roundtrip() -> None:
    facts = _mod.TickFacts(
        now_wall=1.5,
        idle=True,
        input_line_empty=False,
        human_compact_submitted=True,
        work_idle=False,
    )
    assert _mod._facts_from_json(_mod._facts_to_json(facts)) == facts


def test_outcome_json_roundtrip_noop() -> None:
    outcome = _mod.TickOutcome(
        decision_value="NOOP",
        reason="reason",
        payload=None,
        submit=True,
        consume_signal_path=None,
        deferred_log=None,
    )
    assert _mod._outcome_from_json(_mod._outcome_to_json(outcome)) == outcome


def test_outcome_json_roundtrip_full() -> None:
    outcome = _mod.TickOutcome(
        decision_value="WOULD_COMPACT",
        reason="red",
        payload="/compact ...",
        submit=True,
        consume_signal_path="/x/sig",
        deferred_log="deferred (busy)",
    )
    assert _mod._outcome_from_json(_mod._outcome_to_json(outcome)) == outcome


def test_outcome_json_roundtrip_carries_noop_reason_log() -> None:
    # Plan 00168 Phase 1: the worker's NOOP-reason diagnostic must survive the
    # worker->host wire so the host's DecisionLog can record it.
    outcome = _mod.TickOutcome(
        decision_value="NOOP",
        reason="cooldown active",
        payload=None,
        submit=True,
        consume_signal_path=None,
        deferred_log=None,
        noop_reason_log="noop: cooldown active [critical]",
    )
    restored = _mod._outcome_from_json(_mod._outcome_to_json(outcome))
    assert restored == outcome
    assert restored.noop_reason_log == "noop: cooldown active [critical]"


def test_outcome_from_json_defaults_missing_noop_reason_log_to_none() -> None:
    # Backward-compat: an older worker's JSON without the new key must decode.
    line = json.dumps(
        {
            "decision_value": "NOOP",
            "reason": "r",
            "payload": None,
            "submit": True,
            "consume_signal_path": None,
            "deferred_log": None,
            "machine_state": None,
        }
    )
    assert _mod._outcome_from_json(line).noop_reason_log is None


# ── run_worker() in-process (no subprocess) ──────────────────────────────────


def test_run_worker_emits_one_outcome_per_tick(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "context-sidecar"  # empty → NOOP
    in_stream = io.StringIO(_mod._facts_to_json(_idle_facts()) + "\n")
    out_stream = io.StringIO()

    rc = _mod.run_worker(
        in_stream,
        out_stream,
        dry_run=True,
        sidecar_dir=sidecar_dir,
        policy=_mod.CompactPolicy(),
    )

    assert rc == 0
    outcome = _mod._outcome_from_json(out_stream.getvalue().strip())
    assert outcome.payload is None  # nothing to inject with no sidecar


def test_run_worker_matches_in_process_decide(tmp_path: Path) -> None:
    """The worker must produce the SAME decision as an in-process decide_once —
    a restart cannot change behaviour."""
    sidecar_dir = tmp_path / "context-sidecar"
    sidecar_dir.mkdir()
    facts = _idle_facts()
    policy = _mod.CompactPolicy()

    expected = _mod.decide_once(
        _mod.CompactStateMachine(policy),
        sidecar_dir=sidecar_dir,
        facts=facts,
        dry_run=True,
        freshness_seconds=policy.freshness_seconds,
    )

    out_stream = io.StringIO()
    _mod.run_worker(
        io.StringIO(_mod._facts_to_json(facts) + "\n"),
        out_stream,
        dry_run=True,
        sidecar_dir=sidecar_dir,
        policy=policy,
    )
    got = _mod._outcome_from_json(out_stream.getvalue().strip())
    assert got == expected


def test_run_worker_skips_blank_and_bad_lines(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "context-sidecar"
    lines = "\n" + "not json\n" + _mod._facts_to_json(_idle_facts()) + "\n"
    out_stream = io.StringIO()
    rc = _mod.run_worker(
        io.StringIO(lines),
        out_stream,
        dry_run=True,
        sidecar_dir=sidecar_dir,
        policy=_mod.CompactPolicy(),
    )
    assert rc == 0
    # Exactly one valid tick → exactly one outcome line.
    assert len([ln for ln in out_stream.getvalue().splitlines() if ln.strip()]) == 1


# ── PolicyWorker host client (real subprocess — exercises main() --worker) ────


def test_policy_worker_decide_none_when_not_started() -> None:
    worker = _mod.PolicyWorker(SCRIPT_PATH, dry_run=True)
    assert worker.decide(_idle_facts()) is None


def test_policy_worker_subprocess_roundtrip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # No sidecars under this project root → the worker decides NOOP.
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    worker = _mod.PolicyWorker(SCRIPT_PATH, dry_run=True)
    assert worker.start() is True
    try:
        outcome = worker.decide(_idle_facts())
        assert outcome is not None
        assert outcome.payload is None
    finally:
        worker.close()


def test_policy_worker_restart_still_decides(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    worker = _mod.PolicyWorker(SCRIPT_PATH, dry_run=True)
    assert worker.start() is True
    try:
        assert worker.restart() is True
        assert worker.decide(_idle_facts()) is not None
    finally:
        worker.close()


def test_policy_worker_decide_none_after_close(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    worker = _mod.PolicyWorker(SCRIPT_PATH, dry_run=True)
    assert worker.start() is True
    worker.close()
    assert worker.decide(_idle_facts()) is None


# ── main() orchestration helpers ─────────────────────────────────────────────


def test_make_policy_worker_respects_opt_out(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLAUDE_SUPERVISE_NO_WORKER", "1")
    assert _mod._make_policy_worker(dry_run=True) is None


def test_worker_decider_delegates_and_reloads() -> None:
    """The per-tick decider hot-reloads on the first tick and returns the
    worker's decision."""
    worker = MagicMock()
    worker.alive.return_value = True
    sentinel = _mod.TickOutcome(
        decision_value="NOOP",
        reason="r",
        payload=None,
        submit=True,
        consume_signal_path=None,
        deferred_log=None,
    )
    worker.decide.return_value = sentinel

    decider = _mod._make_worker_decider(worker)
    facts = _idle_facts(now=1000.0)
    assert decider(facts) is sentinel
    worker.reload_if_stale.assert_called()
    worker.decide.assert_called_once_with(facts)


def test_worker_decider_restarts_dead_worker() -> None:
    worker = MagicMock()
    worker.alive.return_value = False
    worker.decide.return_value = None
    decider = _mod._make_worker_decider(worker)
    decider(_idle_facts(now=1000.0))
    worker.restart.assert_called_once()


# ── Live PTY integration (Task 4.6) ──────────────────────────────────────────


class TestWorkerIntegration:
    """supervise() driven by a REAL worker subprocess over a real PTY."""

    def test_live_worker_passthrough(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capfd: pytest.CaptureFixture[str],
    ) -> None:
        # Empty project root → the worker decides NOOP; nothing is injected and
        # the child's output must pass through untouched.
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
        worker = _mod.PolicyWorker(SCRIPT_PATH, dry_run=True)
        assert worker.start() is True
        decider = _mod._make_worker_decider(worker)
        stdin_fd = os.open(os.devnull, os.O_RDONLY)
        try:
            code = _mod.supervise(
                ["bash", "-lc", "printf 'WORKER_OK\\n'; sleep 0.25; exit 0"],
                dry_run=True,
                stdin_fd=stdin_fd,
                poll_seconds=0.05,  # fire the decider many times during the run
                sidecar_dir=tmp_path / "context-sidecar",
                decider=decider,
            )
        finally:
            os.close(stdin_fd)
            worker.close()
        assert code == 0
        assert "WORKER_OK" in capfd.readouterr().out

    def test_repeated_worker_restart_midrun_is_transparent(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capfd: pytest.CaptureFixture[str],
    ) -> None:
        """Thrashing the worker (restart every tick) must not disturb the child."""
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
        worker = _mod.PolicyWorker(SCRIPT_PATH, dry_run=True)
        assert worker.start() is True

        def churny_decider(facts: object) -> object:
            worker.restart()  # swap the policy subprocess on every tick
            return worker.decide(facts)

        stdin_fd = os.open(os.devnull, os.O_RDONLY)
        try:
            code = _mod.supervise(
                ["bash", "-lc", "printf 'STILL_HERE\\n'; sleep 0.3; exit 0"],
                dry_run=True,
                stdin_fd=stdin_fd,
                poll_seconds=0.05,
                sidecar_dir=tmp_path / "context-sidecar",
                decider=churny_decider,
            )
        finally:
            os.close(stdin_fd)
            worker.close()
        assert code == 0
        assert "STILL_HERE" in capfd.readouterr().out


# ── Single-authoritative machine state (Plan 00164 duplicate-compact fix) ─────
#
# The host holds the ONE authoritative CompactStateMachine. It carries that
# state INTO each tick (TickFacts.machine_state) and ADOPTS the post-tick state
# the worker returns (TickOutcome.machine_state). Without this, the host's
# in-process fallback machine keeps stale MONITOR state while the worker handles
# ticks, so a worker stall right after a /compact lets the host inject a DUPLICATE
# /compact — the very bug class this release fixes.


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


def test_machine_state_export_import_roundtrip() -> None:
    policy = _mod.CompactPolicy()
    reading = _mod.SidecarReading(
        red=True,
        critical=True,
        compact_urgent=True,
        tier="critical",
        pct=95.0,
        session_id="s",
        ts=1000.0,
        seq=1,
        writer_pid=1,
        compacting=False,
        stale=False,
    )
    src = _mod.CompactStateMachine(policy)
    src.evaluate(reading, idle=True, now=1000.0)  # -> AWAIT_COMPACTING
    state = src.export_state()

    dst = _mod.CompactStateMachine(policy)
    dst.import_state(state)
    assert dst.state is _mod.SupervisorState.AWAIT_COMPACTING
    assert dst.export_state() == state


def test_facts_json_roundtrip_carries_machine_state() -> None:
    state = _mod.CompactStateMachine(_mod.CompactPolicy()).export_state()
    facts = _mod.TickFacts(
        now_wall=1.5,
        idle=True,
        input_line_empty=True,
        human_compact_submitted=False,
        work_idle=True,
        machine_state=state,
    )
    assert _mod._facts_from_json(_mod._facts_to_json(facts)) == facts


def test_decide_once_returns_post_tick_machine_state(tmp_path: Path) -> None:
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
    assert outcome.machine_state is not None
    assert outcome.machine_state["state"] == _mod.SupervisorState.AWAIT_COMPACTING.value


def test_host_adopting_worker_state_prevents_duplicate_compact(tmp_path: Path) -> None:
    """Regression (Plan 00164): a worker stall right after a /compact must not let
    the host fallback machine inject a SECOND /compact. Because the host carries
    its authoritative state into the tick, a fallback tick seeded with the
    post-compact state sees AWAIT_COMPACTING, not a fresh MONITOR — so it never
    re-compacts."""
    sidecar_dir = tmp_path / "context-sidecar"
    _write_urgent_sidecar(sidecar_dir, now=1000.0)
    policy = _mod.CompactPolicy()

    # Tick 1: the worker decides -> WOULD_COMPACT and returns its new state.
    worker_machine = _mod.CompactStateMachine(policy)
    first = _mod.decide_once(
        worker_machine,
        sidecar_dir=sidecar_dir,
        facts=_idle_facts(1000.0),
        dry_run=True,
        freshness_seconds=policy.freshness_seconds,
    )
    assert first.decision_value == _mod.Decision.WOULD_COMPACT.value

    # Tick 2: the worker STALLS; the host falls back to a SEPARATE fresh machine
    # but seeds it with the authoritative state carried in facts.machine_state.
    fallback_machine = _mod.CompactStateMachine(policy)
    facts2 = _mod.TickFacts(
        now_wall=1001.0,
        idle=True,
        input_line_empty=True,
        human_compact_submitted=False,
        work_idle=True,
        machine_state=first.machine_state,
    )
    second = _mod.decide_once(
        fallback_machine,
        sidecar_dir=sidecar_dir,
        facts=facts2,
        dry_run=True,
        freshness_seconds=policy.freshness_seconds,
    )
    assert second.decision_value != _mod.Decision.WOULD_COMPACT.value


def test_fresh_fallback_without_shared_state_would_double_compact(tmp_path: Path) -> None:
    """Guardrail proving the above test is meaningful: a fresh machine given the
    SAME facts WITHOUT the carried state does compact — i.e. the divergence is
    real and the shared state is what prevents it."""
    sidecar_dir = tmp_path / "context-sidecar"
    _write_urgent_sidecar(sidecar_dir, now=1000.0)
    policy = _mod.CompactPolicy()
    outcome = _mod.decide_once(
        _mod.CompactStateMachine(policy),
        sidecar_dir=sidecar_dir,
        facts=_idle_facts(1001.0),  # no machine_state carried
        dry_run=True,
        freshness_seconds=policy.freshness_seconds,
    )
    assert outcome.decision_value == _mod.Decision.WOULD_COMPACT.value
