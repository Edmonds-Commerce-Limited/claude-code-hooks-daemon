"""Tests for the dry-run compact decision logic in claude-supervise.py.

Plan 00135 Slice 2 (dry-run phase). Covers the sidecar reader and the
MONITOR -> AWAIT_COMPACTING state machine (Decision H). Every path here is
pure decision logic that INJECTS NOTHING — arming the actual PTY writes is a
separate, later step.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from tests.unit.supervise._load import load_supervisor_module

if TYPE_CHECKING:
    from pathlib import Path

_mod = load_supervisor_module()
SidecarReading = _mod.SidecarReading
load_freshest_sidecar = _mod.load_freshest_sidecar
CompactStateMachine = _mod.CompactStateMachine
CompactPolicy = _mod.CompactPolicy
Decision = _mod.Decision
SupervisorState = _mod.SupervisorState


class TestDefaultSidecarDir:
    # Install-mode-aware resolution (Plan 00149 Bug A): a bare project (no
    # src/claude_code_hooks_daemon) is a NORMAL client install, so the sidecar
    # dir is .claude/hooks-daemon/untracked/context-sidecar — the daemon's real
    # write location. Full matrix in test_sidecar_dir_resolution.py.
    def test_uses_claude_project_dir_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
        assert (
            _mod._default_sidecar_dir()
            == tmp_path / ".claude" / "hooks-daemon" / "untracked" / "context-sidecar"
        )

    def test_falls_back_to_cwd(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
        monkeypatch.chdir(tmp_path)
        assert (
            _mod._default_sidecar_dir()
            == tmp_path / ".claude" / "hooks-daemon" / "untracked" / "context-sidecar"
        )


def _write_sidecar(
    directory: Path,
    name: str,
    *,
    red: bool = False,
    tier: str = "green",
    pct: float = 10.0,
    session_id: str = "sess",
    ts: float = 1000.0,
    seq: int = 1,
    writer_pid: int = 4242,
    compacting: bool | None = None,
    raw: str | None = None,
) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.json"
    if raw is not None:
        path.write_text(raw, encoding="utf-8")
        return
    payload = {
        "schema_version": 1,
        "red": red,
        "tier": tier,
        "pct": pct,
        "window_size": 200000,
        "session_id": session_id,
        "ts": ts,
        "seq": seq,
        "writer_pid": writer_pid,
    }
    if compacting is not None:
        payload["compacting"] = compacting
    path.write_text(json.dumps(payload), encoding="utf-8")


# --------------------------------------------------------------------------
# load_freshest_sidecar
# --------------------------------------------------------------------------


class TestLoadFreshestSidecar:
    def test_missing_dir_returns_none(self, tmp_path: Path) -> None:
        assert load_freshest_sidecar(tmp_path / "nope", now=1000.0, freshness_seconds=30) is None

    def test_empty_dir_returns_none(self, tmp_path: Path) -> None:
        tmp_path.mkdir(exist_ok=True)
        assert load_freshest_sidecar(tmp_path, now=1000.0, freshness_seconds=30) is None

    def test_loads_fields(self, tmp_path: Path) -> None:
        _write_sidecar(tmp_path, "s", red=True, tier="red", pct=85.0, ts=1000.0, seq=7)
        reading = load_freshest_sidecar(tmp_path, now=1000.0, freshness_seconds=30)
        assert reading is not None
        assert reading.red is True
        assert reading.tier == "red"
        assert reading.pct == 85.0
        assert reading.seq == 7
        assert reading.writer_pid == 4242

    def test_picks_freshest_by_ts(self, tmp_path: Path) -> None:
        _write_sidecar(tmp_path, "old", ts=100.0, session_id="old", red=False)
        _write_sidecar(tmp_path, "new", ts=900.0, session_id="new", red=True)
        reading = load_freshest_sidecar(tmp_path, now=905.0, freshness_seconds=30)
        assert reading is not None
        assert reading.session_id == "new"
        assert reading.red is True

    def test_stale_when_old(self, tmp_path: Path) -> None:
        _write_sidecar(tmp_path, "s", ts=1000.0)
        reading = load_freshest_sidecar(tmp_path, now=1040.0, freshness_seconds=30)
        assert reading is not None
        assert reading.stale is True

    def test_fresh_when_recent(self, tmp_path: Path) -> None:
        _write_sidecar(tmp_path, "s", ts=1000.0)
        reading = load_freshest_sidecar(tmp_path, now=1010.0, freshness_seconds=30)
        assert reading is not None
        assert reading.stale is False

    def test_compacting_defaults_false(self, tmp_path: Path) -> None:
        _write_sidecar(tmp_path, "s", ts=1000.0)
        reading = load_freshest_sidecar(tmp_path, now=1000.0, freshness_seconds=30)
        assert reading is not None
        assert reading.compacting is False

    def test_compacting_true_when_present(self, tmp_path: Path) -> None:
        _write_sidecar(tmp_path, "s", ts=1000.0, compacting=True)
        reading = load_freshest_sidecar(tmp_path, now=1000.0, freshness_seconds=30)
        assert reading is not None
        assert reading.compacting is True

    def test_skips_malformed_and_loads_valid(self, tmp_path: Path) -> None:
        _write_sidecar(tmp_path, "broken", raw="{not json")
        _write_sidecar(tmp_path, "good", ts=1000.0, red=True)
        reading = load_freshest_sidecar(tmp_path, now=1000.0, freshness_seconds=30)
        assert reading is not None
        assert reading.red is True

    def test_all_malformed_returns_none(self, tmp_path: Path) -> None:
        _write_sidecar(tmp_path, "broken", raw="{not json")
        assert load_freshest_sidecar(tmp_path, now=1000.0, freshness_seconds=30) is None

    def test_missing_fields_default_sanely(self, tmp_path: Path) -> None:
        (tmp_path).mkdir(exist_ok=True)
        (tmp_path / "s.json").write_text(json.dumps({"ts": 1000.0}), encoding="utf-8")
        reading = load_freshest_sidecar(tmp_path, now=1000.0, freshness_seconds=30)
        assert reading is not None
        assert reading.red is False
        assert reading.pct == 0.0


# --------------------------------------------------------------------------
# CompactStateMachine — MONITOR
# --------------------------------------------------------------------------


def _reading(**kw: object) -> object:
    defaults: dict[str, object] = {
        "red": True,
        "tier": "red",
        "pct": 85.0,
        "session_id": "s",
        "ts": 1000.0,
        "seq": 1,
        "writer_pid": 1,
        "compacting": False,
        "stale": False,
    }
    defaults.update(kw)
    return SidecarReading(**defaults)


class TestMonitor:
    def test_red_idle_fresh_would_compact(self) -> None:
        sm = CompactStateMachine(CompactPolicy())
        result = sm.evaluate(_reading(), idle=True, now=1000.0)
        assert result.decision is Decision.WOULD_COMPACT
        assert sm.state is SupervisorState.AWAIT_COMPACTING

    def test_not_red_noop(self) -> None:
        sm = CompactStateMachine(CompactPolicy())
        result = sm.evaluate(_reading(red=False, tier="green"), idle=True, now=1000.0)
        assert result.decision is Decision.NOOP
        assert sm.state is SupervisorState.MONITOR

    def test_red_but_busy_noop(self) -> None:
        sm = CompactStateMachine(CompactPolicy())
        result = sm.evaluate(_reading(), idle=False, now=1000.0)
        assert result.decision is Decision.NOOP
        assert sm.state is SupervisorState.MONITOR

    def test_red_idle_but_stale_noop(self) -> None:
        sm = CompactStateMachine(CompactPolicy())
        result = sm.evaluate(_reading(stale=True), idle=True, now=1000.0)
        assert result.decision is Decision.NOOP

    def test_none_reading_noop(self) -> None:
        sm = CompactStateMachine(CompactPolicy())
        result = sm.evaluate(None, idle=True, now=1000.0)
        assert result.decision is Decision.NOOP

    def test_cap_reached_noop(self) -> None:
        sm = CompactStateMachine(CompactPolicy(max_injections=1, cooldown_seconds=0))
        first = sm.evaluate(_reading(), idle=True, now=1000.0)
        assert first.decision is Decision.WOULD_COMPACT
        # Drive back to MONITOR via compacting so cap (not state) is the gate.
        sm.evaluate(_reading(compacting=True), idle=True, now=1001.0)
        second = sm.evaluate(_reading(), idle=True, now=2000.0)
        assert second.decision is Decision.NOOP

    def test_cooldown_blocks_second_compact(self) -> None:
        sm = CompactStateMachine(CompactPolicy(cooldown_seconds=300))
        sm.evaluate(_reading(), idle=True, now=1000.0)
        sm.evaluate(_reading(compacting=True), idle=True, now=1001.0)  # -> MONITOR
        result = sm.evaluate(_reading(), idle=True, now=1100.0)  # only 99s later
        assert result.decision is Decision.NOOP


# --------------------------------------------------------------------------
# CompactStateMachine — AWAIT_COMPACTING
# --------------------------------------------------------------------------


class TestAwaitCompacting:
    def test_compacting_would_continue(self) -> None:
        sm = CompactStateMachine(CompactPolicy())
        sm.evaluate(_reading(), idle=True, now=1000.0)  # -> AWAIT
        result = sm.evaluate(_reading(compacting=True), idle=True, now=1005.0)
        assert result.decision is Decision.WOULD_CONTINUE
        assert sm.state is SupervisorState.MONITOR

    def test_not_yet_compacting_noop(self) -> None:
        sm = CompactStateMachine(CompactPolicy())
        sm.evaluate(_reading(), idle=True, now=1000.0)  # -> AWAIT
        result = sm.evaluate(_reading(compacting=False), idle=True, now=1005.0)
        assert result.decision is Decision.NOOP
        assert sm.state is SupervisorState.AWAIT_COMPACTING

    def test_await_timeout_gives_up(self) -> None:
        sm = CompactStateMachine(CompactPolicy(await_timeout_seconds=120))
        sm.evaluate(_reading(), idle=True, now=1000.0)  # -> AWAIT
        result = sm.evaluate(_reading(compacting=False), idle=True, now=1200.0)
        assert result.decision is Decision.NOOP
        assert sm.state is SupervisorState.MONITOR

    def test_full_cycle_monitor_compact_await_continue(self) -> None:
        sm = CompactStateMachine(CompactPolicy(cooldown_seconds=0))
        a = sm.evaluate(_reading(), idle=True, now=1000.0)
        b = sm.evaluate(_reading(compacting=True), idle=True, now=1005.0)
        c = sm.evaluate(_reading(), idle=True, now=1010.0)
        assert a.decision is Decision.WOULD_COMPACT
        assert b.decision is Decision.WOULD_CONTINUE
        assert c.decision is Decision.WOULD_COMPACT  # next red round


class TestCompactionDetection:
    """A compaction underway (manual OR supervisor-triggered) fires continue once."""

    def test_external_compaction_in_monitor_fires_continue(self) -> None:
        sm = CompactStateMachine(CompactPolicy())
        result = sm.evaluate(_reading(compacting=True), idle=True, now=1000.0)
        assert result.decision is Decision.WOULD_CONTINUE
        assert sm.state is SupervisorState.MONITOR

    def test_latch_prevents_repeat_continue_while_compacting(self) -> None:
        sm = CompactStateMachine(CompactPolicy(cooldown_seconds=0))
        first = sm.evaluate(_reading(compacting=True), idle=True, now=1000.0)
        second = sm.evaluate(_reading(compacting=True), idle=True, now=1001.0)
        assert first.decision is Decision.WOULD_CONTINUE
        assert second.decision is Decision.NOOP  # already resumed, no repeat

    def test_no_compact_fired_while_compacting(self) -> None:
        # Even red + idle must not trigger a /compact while a compaction runs.
        sm = CompactStateMachine(CompactPolicy(cooldown_seconds=0))
        sm.evaluate(_reading(compacting=True), idle=True, now=1000.0)  # -> continue
        result = sm.evaluate(_reading(red=True, compacting=True), idle=True, now=1001.0)
        assert result.decision is Decision.NOOP

    def test_latch_resets_after_compaction_ends(self) -> None:
        sm = CompactStateMachine(CompactPolicy(cooldown_seconds=0))
        sm.evaluate(_reading(compacting=True), idle=True, now=1000.0)  # continue
        sm.evaluate(_reading(compacting=False, red=False), idle=True, now=1001.0)  # reset
        again = sm.evaluate(_reading(compacting=True), idle=True, now=1002.0)
        assert again.decision is Decision.WOULD_CONTINUE

    def test_compaction_detected_even_when_stale(self) -> None:
        # Compaction stops status renders, so the reading is often stale.
        sm = CompactStateMachine(CompactPolicy())
        result = sm.evaluate(_reading(compacting=True, stale=True), idle=True, now=1000.0)
        assert result.decision is Decision.WOULD_CONTINUE

    def test_compaction_while_busy_defers_without_latching(self) -> None:
        # `continue` must never be typed into a busy TUI: a busy poll returns
        # NOOP and does NOT latch, so the resume still fires on the next idle
        # poll while the compaction signal is still live.
        sm = CompactStateMachine(CompactPolicy())
        busy = sm.evaluate(_reading(compacting=True), idle=False, now=1000.0)
        assert busy.decision is Decision.NOOP
        assert sm.state is SupervisorState.MONITOR
        settled = sm.evaluate(_reading(compacting=True), idle=True, now=1002.0)
        assert settled.decision is Decision.WOULD_CONTINUE


class TestEvaluationReason:
    def test_reason_is_populated(self) -> None:
        sm = CompactStateMachine(CompactPolicy())
        result = sm.evaluate(_reading(), idle=True, now=1000.0)
        assert isinstance(result.reason, str)
        assert result.reason
