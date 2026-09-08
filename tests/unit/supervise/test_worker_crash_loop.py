"""Plan 00361 — a dying policy worker is visible, dated, and not respawned blindly.

The host used to run ``if not worker.alive(): worker.restart()`` on every
tick and fall back to its own in-process decision with no record anywhere.
A worker spawned from a half-edited on-disk file therefore crash-looped once
per tick, invisibly. These tests pin: the worker's own crash record (dated,
fingerprinted), the host-side crash guard (log once, back off on the same
source, respawn at once on a changed source), the decider wiring, and the
fallback-transition log lines.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from tests.unit.supervise._load import load_supervisor_module

if TYPE_CHECKING:
    from pathlib import Path

_mod = load_supervisor_module()

_FP_A = "aaaaaaaaaaaa"
_FP_B = "bbbbbbbbbbbb"


def _facts(now: float = 1000.0) -> object:
    return _mod.TickFacts(
        now_wall=now,
        idle=True,
        input_line_empty=True,
        human_compact_submitted=False,
        work_idle=True,
    )


def _noop_outcome() -> object:
    return _mod.TickOutcome(
        decision_value="NOOP",
        reason="r",
        payload=None,
        submit=True,
        consume_signal_path=None,
        deferred_log=None,
    )


# ── Task 2.1: the worker's own fatal crash is dated and fingerprinted ────────


class TestWorkerCrashRecord:
    def test_an_escaped_exception_is_recorded_with_time_and_source(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        errlog = tmp_path / "worker.err.log"
        monkeypatch.setattr(_mod, "worker_error_log_path", lambda: errlog)
        monkeypatch.setattr(_mod, "_redirect_worker_stderr_to_log", lambda: None)

        def _boom(*_a: object, **_k: object) -> int:
            raise RuntimeError("half-edited source")

        monkeypatch.setattr(_mod, "run_worker", _boom)
        monkeypatch.setattr(_mod, "_self_source_fingerprint", lambda: _FP_A)

        assert _mod.main([_mod._WORKER_FLAG]) == 1

        text = errlog.read_text(encoding="utf-8")
        assert text.startswith("[20")  # append_worker_error's timestamp prefix
        assert f"worker crashed (source {_FP_A})" in text
        assert "RuntimeError: half-edited source" in text

    def test_a_clean_worker_exit_is_not_a_crash(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_mod, "_redirect_worker_stderr_to_log", lambda: None)
        monkeypatch.setattr(_mod, "run_worker", lambda *_a, **_k: 0)
        assert _mod.main([_mod._WORKER_FLAG]) == 0

    def test_self_fingerprint_is_unknown_when_the_file_is_unreadable(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(_mod, "_SELF_PATH", tmp_path / "missing.py")
        assert _mod._self_source_fingerprint() == "unknown"


# ── Task 2.2: the crash guard ───────────────────────────────────────────────


class TestWorkerCrashGuard:
    def test_first_death_on_a_source_respawns_and_logs(self) -> None:
        guard = _mod.WorkerCrashGuard()
        respawn, line = guard.on_death(
            dead_fingerprint=_FP_A, on_disk_fingerprint=_FP_A, exit_code=1, now=100.0
        )
        assert respawn is True
        assert line is not None
        assert "worker died" in line
        assert "exit 1" in line
        assert _FP_A in line
        assert "respawned" in line

    def test_second_death_on_the_same_source_holds_and_logs_the_loop_once(self) -> None:
        guard = _mod.WorkerCrashGuard(backoff_seconds=10.0)
        guard.on_death(dead_fingerprint=_FP_A, on_disk_fingerprint=_FP_A, exit_code=1, now=100.0)
        respawn, line = guard.on_death(
            dead_fingerprint=_FP_A, on_disk_fingerprint=_FP_A, exit_code=1, now=102.0
        )
        assert respawn is False
        assert line is not None
        assert "crash-looping" in line
        assert _FP_A in line
        assert "in-process" in line
        # Third death inside the backoff window: silent hold.
        respawn, line = guard.on_death(
            dead_fingerprint=_FP_A, on_disk_fingerprint=_FP_A, exit_code=1, now=104.0
        )
        assert respawn is False
        assert line is None

    def test_backoff_elapsing_retries_the_same_source_silently(self) -> None:
        guard = _mod.WorkerCrashGuard(backoff_seconds=10.0)
        guard.on_death(dead_fingerprint=_FP_A, on_disk_fingerprint=_FP_A, exit_code=1, now=100.0)
        guard.on_death(dead_fingerprint=_FP_A, on_disk_fingerprint=_FP_A, exit_code=1, now=102.0)
        respawn, line = guard.on_death(
            dead_fingerprint=_FP_A, on_disk_fingerprint=_FP_A, exit_code=1, now=112.5
        )
        assert respawn is True
        assert line is None

    def test_a_changed_source_respawns_at_once_even_mid_loop(self) -> None:
        guard = _mod.WorkerCrashGuard(backoff_seconds=10.0)
        guard.on_death(dead_fingerprint=_FP_A, on_disk_fingerprint=_FP_A, exit_code=1, now=100.0)
        guard.on_death(dead_fingerprint=_FP_A, on_disk_fingerprint=_FP_A, exit_code=1, now=102.0)
        respawn, line = guard.on_death(
            dead_fingerprint=_FP_A, on_disk_fingerprint=_FP_B, exit_code=1, now=103.0
        )
        assert respawn is True
        assert line is not None
        assert "source changed" in line
        assert _FP_B in line

    def test_a_death_on_a_new_source_starts_a_fresh_count(self) -> None:
        guard = _mod.WorkerCrashGuard(backoff_seconds=10.0)
        guard.on_death(dead_fingerprint=_FP_A, on_disk_fingerprint=_FP_A, exit_code=1, now=100.0)
        guard.on_death(dead_fingerprint=_FP_A, on_disk_fingerprint=_FP_B, exit_code=1, now=101.0)
        # The B worker dies once: that is B's FIRST death, not A's third.
        respawn, line = guard.on_death(
            dead_fingerprint=_FP_B, on_disk_fingerprint=_FP_B, exit_code=2, now=103.0
        )
        assert respawn is True
        assert line is not None
        assert "worker died" in line
        assert "exit 2" in line

    def test_an_answer_after_a_loop_logs_recovery_once(self) -> None:
        guard = _mod.WorkerCrashGuard(backoff_seconds=10.0)
        assert guard.on_answer(fingerprint=_FP_A) is None  # never looped
        guard.on_death(dead_fingerprint=_FP_A, on_disk_fingerprint=_FP_A, exit_code=1, now=100.0)
        guard.on_death(dead_fingerprint=_FP_A, on_disk_fingerprint=_FP_A, exit_code=1, now=102.0)
        line = guard.on_answer(fingerprint=_FP_B)
        assert line is not None
        assert "recovered" in line
        assert _FP_B in line
        assert guard.on_answer(fingerprint=_FP_B) is None

    def test_unknown_fingerprint_and_exit_code_are_rendered_not_crashed(self) -> None:
        guard = _mod.WorkerCrashGuard()
        respawn, line = guard.on_death(
            dead_fingerprint=None, on_disk_fingerprint=None, exit_code=None, now=1.0
        )
        assert respawn is True
        assert line is not None
        assert "unknown" in line


# ── Task 2.3: the decider routes a dead worker through the guard ────────────


def _dead_worker(*, spawned_from: str, on_disk: str, exit_code: int) -> MagicMock:
    worker = MagicMock()
    worker.alive.return_value = False
    worker.source_fingerprint = spawned_from
    worker.on_disk_fingerprint.return_value = on_disk
    worker.exit_code.return_value = exit_code
    worker.restart.return_value = True
    worker.reload_if_stale.return_value = False
    worker.decide.return_value = _noop_outcome()
    return worker


class TestDeciderUsesTheGuard:
    def test_a_dead_worker_is_logged_and_restarted(self, tmp_path: Path) -> None:
        log = _mod.DecisionLog(tmp_path / "decision.log")
        worker = _dead_worker(spawned_from=_FP_A, on_disk=_FP_A, exit_code=1)
        decider = _mod._make_worker_decider(worker, log=log)
        assert decider(_facts(100.0)) is not None
        worker.restart.assert_called_once()
        text = log.path.read_text(encoding="utf-8")
        assert "worker died (exit 1, source aaaaaaaaaaaa)" in text

    def test_a_crash_loop_stops_restarting_and_falls_back(self, tmp_path: Path) -> None:
        log = _mod.DecisionLog(tmp_path / "decision.log")
        worker = _dead_worker(spawned_from=_FP_A, on_disk=_FP_A, exit_code=1)
        decider = _mod._make_worker_decider(worker, log=log)
        decider(_facts(100.0))
        # Still dead after the respawn: the same source, so hold.
        assert decider(_facts(102.0)) is None
        assert decider(_facts(104.0)) is None
        worker.restart.assert_called_once()
        text = log.path.read_text(encoding="utf-8")
        assert text.count("crash-looping") == 1

    def test_a_changed_source_is_retried_at_once(self, tmp_path: Path) -> None:
        log = _mod.DecisionLog(tmp_path / "decision.log")
        worker = _dead_worker(spawned_from=_FP_A, on_disk=_FP_A, exit_code=1)
        decider = _mod._make_worker_decider(worker, log=log)
        decider(_facts(100.0))
        decider(_facts(102.0))
        worker.on_disk_fingerprint.return_value = _FP_B
        assert decider(_facts(103.0)) is not None
        assert worker.restart.call_count == 2

    def test_recovery_after_a_loop_is_logged(self, tmp_path: Path) -> None:
        log = _mod.DecisionLog(tmp_path / "decision.log")
        worker = _dead_worker(spawned_from=_FP_A, on_disk=_FP_A, exit_code=1)
        decider = _mod._make_worker_decider(worker, log=log)
        decider(_facts(100.0))
        decider(_facts(102.0))
        worker.alive.return_value = True
        worker.source_fingerprint = _FP_B
        assert decider(_facts(104.0)) is not None
        assert "worker recovered (source bbbbbbbbbbbb)" in log.path.read_text(encoding="utf-8")

    def test_no_log_is_fine(self) -> None:
        worker = _dead_worker(spawned_from=_FP_A, on_disk=_FP_A, exit_code=1)
        decider = _mod._make_worker_decider(worker)
        assert decider(_facts(100.0)) is not None


class TestPolicyWorkerExposesWhatTheGuardNeeds:
    def test_fingerprints_and_exit_code_before_start(self, tmp_path: Path) -> None:
        src = tmp_path / "sup.py"
        src.write_text("print('x')\n", encoding="utf-8")
        worker = _mod.PolicyWorker(src, dry_run=True)
        assert worker.source_fingerprint == _mod.compute_source_hash(src)
        assert worker.on_disk_fingerprint() == worker.source_fingerprint
        assert worker.exit_code() is None
        src.write_text("print('y')\n", encoding="utf-8")
        assert worker.on_disk_fingerprint() != worker.source_fingerprint


# ── Task 2.4: fallback transitions ──────────────────────────────────────────


class TestFallbackTransitions:
    def test_only_transitions_are_logged(self) -> None:
        transitions = _mod.FallbackTransitions()
        assert transitions.note(worker_answered=True) is None
        line = transitions.note(worker_answered=False)
        assert line is not None
        assert "in-process" in line
        assert transitions.note(worker_answered=False) is None
        line = transitions.note(worker_answered=True)
        assert line is not None
        assert "answering again" in line
        assert transitions.note(worker_answered=True) is None

    def test_a_first_tick_fallback_is_logged(self) -> None:
        transitions = _mod.FallbackTransitions()
        assert transitions.note(worker_answered=False) is not None
