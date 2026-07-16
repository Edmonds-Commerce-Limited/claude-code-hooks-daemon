"""Plan 00168 Phase 2 — deterministic reproduction of the compaction-gap hypotheses.

The live report ("an agent reached COMPACT NOW but never got a /compact") could
not be reproduced from the healthy diagnosing session. These tests instead pin
each RANKED hypothesis as a deterministic unit case AND assert that Plan 00168
Phase 1 now makes each one OBSERVABLE in ``decision.log`` (the failure mode is no
longer silent), so a future occurrence is diagnosable from the log alone.

- H1: a backgrounded Agent-View thread stops rendering its statusLine, so its
  sidecar goes STALE -> the supervisor (which acts only on a fresh foreground
  sidecar) NOOPs "sidecar stale" even at critical. Real coverage gap; silent
  before Phase 1.
- H2: the empty-input-box guard blocks even a critical compaction while the
  human has text in the box (BY DESIGN -- never corrupt their input) -- now
  logged as a deferral. The streaming variant is shown NOT to block critical.
- H3: an empty own-session set (Plan 00166 fail-safe) filters out every sidecar
  -> the supervisor sees "no sidecar reading" and acts on nothing. Silent
  before Phase 1.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from tests.unit.supervise._load import load_supervisor_module

if TYPE_CHECKING:
    from pathlib import Path

_mod = load_supervisor_module()
Decision = _mod.Decision
CompactPolicy = _mod.CompactPolicy
CompactStateMachine = _mod.CompactStateMachine
DecisionLog = _mod.DecisionLog


def _write_sidecar(
    directory: Path,
    *,
    session_id: str = "s",
    red: bool = True,
    critical: bool = True,
    ts: float = 1000.0,
) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    payload = {
        "red": red,
        "critical": critical,
        "compact_urgent": critical,
        "tier": "critical" if critical else ("red" if red else "green"),
        "pct": 95.0 if red else 5.0,
        "session_id": session_id,
        "ts": ts,
        "seq": 1,
        "writer_pid": 1,
    }
    (directory / f"{session_id}.json").write_text(json.dumps(payload), encoding="utf-8")


def _poll(
    sc: Path,
    log: object,
    *,
    now_wall: float,
    idle: bool = True,
    input_line_empty: bool = True,
    work_idle: bool = True,
    own_sessions: object = None,
    machine: object = None,
) -> Any:
    return _mod._poll_once(
        machine if machine is not None else CompactStateMachine(CompactPolicy()),
        sidecar_dir=sc,
        now_wall=now_wall,
        idle=idle,
        dry_run=True,
        master_writer=lambda _b: None,
        log=log,
        freshness_seconds=30.0,
        input_line_empty=input_line_empty,
        work_idle=work_idle,
        own_sessions=own_sessions,
    )


class TestH1BackgroundThreadStaleSidecar:
    """A stale (non-rendering, backgrounded) critical sidecar -> NOOP, now logged."""

    def test_stale_critical_sidecar_noops_and_is_logged(self, tmp_path: Path) -> None:
        sc = tmp_path / "sc"
        # ts 60s old: past the 30s freshness window but well within the 1800s
        # reap TTL, so it lingers stale rather than being deleted.
        _write_sidecar(sc, ts=1000.0)
        log_path = tmp_path / "decision.log"
        ev = _poll(sc, DecisionLog(log_path), now_wall=1060.0)
        assert ev.decision is Decision.NOOP
        assert ev.reason == "sidecar stale"
        contents = log_path.read_text(encoding="utf-8")
        assert "noop: sidecar stale" in contents


class TestH2InputBoxGuardBlocksEvenCritical:
    """A non-empty input box defers even a critical compaction (by design), logged."""

    def test_critical_with_nonempty_input_box_defers_and_is_logged(self, tmp_path: Path) -> None:
        sc = tmp_path / "sc"
        _write_sidecar(sc, ts=1000.0)
        log_path = tmp_path / "decision.log"
        ev = _poll(sc, DecisionLog(log_path), now_wall=1000.0, input_line_empty=False)
        assert ev.decision is Decision.NOOP
        assert ev.reason == _mod._REASON_BUSY_COMPOSING
        contents = log_path.read_text(encoding="utf-8")
        assert _mod._DEFERRED_LOG_PREFIX in contents

    def test_critical_while_streaming_still_compacts(self, tmp_path: Path) -> None:
        # CONTRAST: critical bypasses the work_idle patience gate, so a streaming
        # (work_idle=False) but keystroke-idle, empty-box session STILL compacts.
        # This documents that the H2 "streaming blocks critical" theory is false.
        sc = tmp_path / "sc"
        _write_sidecar(sc, ts=1000.0)
        ev = _poll(sc, None, now_wall=1000.0, work_idle=False)
        assert ev.decision is Decision.WOULD_COMPACT


class TestH3EmptyOwnSessionsFiltersEverything:
    """Plan 00166 fail-safe: an empty own-session set acts on nothing, now logged."""

    def test_empty_own_sessions_noops_no_reading_and_is_logged(self, tmp_path: Path) -> None:
        sc = tmp_path / "sc"
        _write_sidecar(sc, ts=1000.0)
        log_path = tmp_path / "decision.log"
        ev = _poll(sc, DecisionLog(log_path), now_wall=1000.0, own_sessions=frozenset())
        assert ev.decision is Decision.NOOP
        assert ev.reason == "no sidecar reading"
        contents = log_path.read_text(encoding="utf-8")
        assert "noop: no sidecar reading" in contents

    def test_own_sessions_including_the_session_compacts(self, tmp_path: Path) -> None:
        # CONTRAST: when the session IS in scope, the same critical sidecar
        # compacts -- proving the empty-set case is specifically the filter.
        sc = tmp_path / "sc"
        _write_sidecar(sc, session_id="mine", ts=1000.0)
        ev = _poll(sc, None, now_wall=1000.0, own_sessions=frozenset({"mine"}))
        assert ev.decision is Decision.WOULD_COMPACT


class TestSupervisorVersionMatchesDaemon:
    """Task 3.2: the supervisor's __version__ must track the daemon's version.py.

    The release version-bump updated version.py but not the hardcoded string in
    claude-supervise.py (observed 3.41.0 while the repo shipped 3.42.0). Locking
    them together here makes any future drift a failing test rather than a
    silently-stale banner / supervisor-status.json version.
    """

    def test_supervisor_version_equals_daemon_version(self) -> None:
        from claude_code_hooks_daemon.version import __version__ as daemon_version

        assert _mod.__version__ == daemon_version
