"""Plan 00164 Phase 4 — restartable policy-worker split.

The supervisor's decision logic (``decide_once`` + the state machine) runs in a
``--worker`` subprocess so it can be hot-reloaded from a freshly-deployed
``claude-supervise.py`` WITHOUT restarting the PTY host that owns ``claude``.
Host and worker exchange line-delimited JSON (``TickFacts`` → ``TickOutcome``);
anything that goes wrong falls back to an identical in-process decision.
"""

from __future__ import annotations

import io
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
