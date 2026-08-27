"""Tests for keystroke injection + poll wiring in claude-supervise.py.

Plan 00135 Slice 2. In dry-run the supervisor injects a harmless visible
MARKER; armed it injects the real /compact. These tests exercise the payload
resolver, the injection primitive, the idle gate, the poll tick, and the
select-timeout wiring in `_forward_io` -- all without a real `claude` child.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import TYPE_CHECKING

from tests.unit.supervise._load import load_supervisor_module

if TYPE_CHECKING:
    from pathlib import Path

_mod = load_supervisor_module()
Decision = _mod.Decision
CompactPolicy = _mod.CompactPolicy
CompactStateMachine = _mod.CompactStateMachine
InputActivity = _mod.InputActivity
DecisionLog = _mod.DecisionLog

# A fixed tick wall-clock so timestamped payloads are deterministic in tests.
_FIXED_NOW = 1_700_000_000.0
_BOT_PREFIX = _mod._BOT_PREFIX


def _expected_stamp(now_wall: float) -> str:
    """The local-time stamp the supervisor embeds for a given tick wall clock."""
    return datetime.fromtimestamp(now_wall).strftime(_mod._BOT_PREFIX_TIME_FORMAT)


class TestResolvePayload:
    def test_noop_returns_none(self) -> None:
        assert _mod._resolve_payload(Decision.NOOP, dry_run=True) is None
        assert _mod._resolve_payload(Decision.NOOP, dry_run=False) is None

    def test_dry_run_compact_is_marker(self) -> None:
        payload = _mod._resolve_payload(Decision.WOULD_COMPACT, dry_run=True, now_wall=_FIXED_NOW)
        assert payload is not None
        assert _BOT_PREFIX in payload
        assert _mod._DRY_RUN_COMPACT_BODY in payload

    def test_dry_run_continue_is_real_continue(self) -> None:
        # continue is harmless -> injected for real even in dry-run.
        payload = _mod._resolve_payload(Decision.WOULD_CONTINUE, dry_run=True, now_wall=_FIXED_NOW)
        assert payload is not None
        assert "continue" in payload
        assert _BOT_PREFIX in payload

    def test_armed_compact_carries_bot_chrome(self) -> None:
        # `/compact` must stay the FIRST token (so it is recognised as the slash
        # command), but its freeform-instruction argument carries the bot chrome
        # so the compaction is visibly supervisor-initiated, never mistaken for a
        # human `/compact`.
        payload = _mod._resolve_payload(Decision.WOULD_COMPACT, dry_run=False, now_wall=_FIXED_NOW)
        assert payload is not None
        assert payload.startswith("/compact ")
        assert _BOT_PREFIX in payload
        assert "🤖" in payload

    def test_armed_compact_instruction_is_actionable_not_provenance(self) -> None:
        # The instruction the post-compact session acts on must be the actionable
        # "resume and continue" — NOT provenance framing about who initiated it.
        # The agent should just do what it is told, regardless of source.
        payload = _mod._resolve_payload(Decision.WOULD_COMPACT, dry_run=False, now_wall=_FIXED_NOW)
        assert payload is not None
        assert "resume" in payload.lower()
        assert "human-initiated" not in payload
        assert "NOT human" not in payload

    def test_armed_continue_matches_dry_run(self) -> None:
        # `continue` is identical armed vs dry-run for the same tick.
        armed = _mod._resolve_payload(Decision.WOULD_CONTINUE, dry_run=False, now_wall=_FIXED_NOW)
        dry = _mod._resolve_payload(Decision.WOULD_CONTINUE, dry_run=True, now_wall=_FIXED_NOW)
        assert armed == dry

    def test_injected_prompts_carry_bot_marker(self) -> None:
        # The user must be able to tell supervisor messages from their own typing.
        compact = _mod._resolve_payload(Decision.WOULD_COMPACT, dry_run=True, now_wall=_FIXED_NOW)
        cont = _mod._resolve_payload(Decision.WOULD_CONTINUE, dry_run=True, now_wall=_FIXED_NOW)
        assert compact is not None and cont is not None
        assert _BOT_PREFIX in compact
        assert "🤖" in compact
        assert _BOT_PREFIX in cont
        assert "🤖" in cont


class TestTimestampedPayloads:
    """Plan: supervisor-injected messages embed the tick wall-clock time.

    Every visible supervisor message must carry the local date/time it was
    injected, so a human scrolling back through the transcript can see WHEN each
    action happened without correlating against the decision log.
    """

    def test_prefix_embeds_local_wall_clock_stamp(self) -> None:
        prefix = _mod._format_bot_prefix(_FIXED_NOW)
        assert prefix.startswith(_BOT_PREFIX)
        assert prefix.endswith("]")
        assert _expected_stamp(_FIXED_NOW) in prefix

    def test_dry_compact_payload_is_timestamped(self) -> None:
        payload = _mod._resolve_payload(Decision.WOULD_COMPACT, dry_run=True, now_wall=_FIXED_NOW)
        assert payload is not None
        assert _expected_stamp(_FIXED_NOW) in payload

    def test_armed_compact_payload_is_timestamped(self) -> None:
        payload = _mod._resolve_payload(Decision.WOULD_COMPACT, dry_run=False, now_wall=_FIXED_NOW)
        assert payload is not None
        assert _expected_stamp(_FIXED_NOW) in payload

    def test_continue_payload_is_timestamped(self) -> None:
        payload = _mod._resolve_payload(Decision.WOULD_CONTINUE, dry_run=True, now_wall=_FIXED_NOW)
        assert payload is not None
        assert _expected_stamp(_FIXED_NOW) in payload

    def test_dry_escape_payload_is_timestamped(self) -> None:
        payload = _mod._resolve_payload(Decision.WOULD_ESCAPE, dry_run=True, now_wall=_FIXED_NOW)
        assert payload is not None
        assert _expected_stamp(_FIXED_NOW) in payload

    def test_stamp_tracks_the_tick_wall_clock(self) -> None:
        # A later tick embeds a later timestamp -> the two payloads differ.
        early = _mod._resolve_payload(Decision.WOULD_CONTINUE, dry_run=True, now_wall=_FIXED_NOW)
        later = _mod._resolve_payload(
            Decision.WOULD_CONTINUE, dry_run=True, now_wall=_FIXED_NOW + 3600.0
        )
        assert early != later

    def test_omitted_now_falls_back_to_current_time(self) -> None:
        # No explicit tick clock -> still a well-formed timestamped prefix.
        prefix = _mod._format_bot_prefix()
        assert prefix.startswith(_BOT_PREFIX)
        assert prefix.endswith("]")


class TestResolveEscapePayload:
    """WOULD_ESCAPE resolves to a raw ESC when armed, a marker in dry-run."""

    def test_armed_escape_is_raw_esc_byte(self) -> None:
        assert _mod._resolve_payload(Decision.WOULD_ESCAPE, dry_run=False) == _mod._ESC_PAYLOAD
        assert _mod._resolve_payload(Decision.WOULD_ESCAPE, dry_run=False) == "\x1b"

    def test_dry_run_escape_is_visible_marker(self) -> None:
        payload = _mod._resolve_payload(Decision.WOULD_ESCAPE, dry_run=True, now_wall=_FIXED_NOW)
        assert payload is not None
        assert payload != "\x1b"
        assert _BOT_PREFIX in payload


class TestPerformInjection:
    def test_submit_false_writes_payload_only(self) -> None:
        # ESC is an interrupt key, not a line: it must NOT get a trailing Enter.
        written: list[bytes] = []
        _mod._perform_injection(written.append, "\x1b", submit=False, sleep=lambda _s: None)
        assert written == [b"\x1b"]

    def test_payload_and_submit_are_separate_writes(self) -> None:
        # The submit MUST be a distinct write after a short pause: injecting
        # `text\r` as one burst leaves the trailing CR absorbed into the
        # multiline input box (text sits unsubmitted, observed live on a long
        # `/compact` line). A standalone, delayed `\r` reads as a real Enter.
        written: list[bytes] = []
        sleeps: list[float] = []
        _mod._perform_injection(written.append, "hello world", sleep=sleeps.append)
        assert written == [b"hello world", b"\r"]
        assert sleeps == [_mod._SUBMIT_DELAY_SECONDS]

    def test_full_line_still_ends_in_carriage_return(self) -> None:
        written: list[bytes] = []
        _mod._perform_injection(written.append, "hello world", sleep=lambda _s: None)
        assert b"".join(written) == b"hello world\r"

    def test_confirm_enters_sends_additional_standalone_enters(self) -> None:
        # A /model switch needs a SECOND confirming Enter after the normal
        # submit -- each is its own delayed write, mirroring the submit itself.
        written: list[bytes] = []
        sleeps: list[float] = []
        _mod._perform_injection(
            written.append, "/model fable", confirm_enters=1, sleep=sleeps.append
        )
        assert written == [b"/model fable", b"\r", b"\r"]
        assert sleeps == [_mod._SUBMIT_DELAY_SECONDS, _mod._MODEL_CONFIRM_DELAY_SECONDS]

    def test_confirm_enters_default_is_zero_and_unchanged(self) -> None:
        written: list[bytes] = []
        _mod._perform_injection(written.append, "hello", sleep=lambda _s: None)
        assert written == [b"hello", b"\r"]

    def test_confirm_enters_multiple(self) -> None:
        written: list[bytes] = []
        _mod._perform_injection(
            written.append, "/model fable", confirm_enters=2, sleep=lambda _s: None
        )
        assert written == [b"/model fable", b"\r", b"\r", b"\r"]

    def test_confirm_enters_ignored_when_submit_false(self) -> None:
        # ESC is an interrupt keypress, not a submitted line -- confirm_enters
        # must never apply to it.
        written: list[bytes] = []
        _mod._perform_injection(
            written.append, "\x1b", submit=False, confirm_enters=1, sleep=lambda _s: None
        )
        assert written == [b"\x1b"]


class TestIsIdle:
    def test_no_input_is_idle(self) -> None:
        activity = InputActivity()
        assert _mod._is_idle(activity, now_monotonic=100.0, idle_floor_seconds=2.0) is True

    def test_recent_input_is_not_idle(self) -> None:
        activity = InputActivity()
        activity.last_input_monotonic = 99.5
        assert _mod._is_idle(activity, now_monotonic=100.0, idle_floor_seconds=2.0) is False

    def test_old_input_is_idle(self) -> None:
        activity = InputActivity()
        activity.last_input_monotonic = 90.0
        assert _mod._is_idle(activity, now_monotonic=100.0, idle_floor_seconds=2.0) is True


class TestPollOnce:
    def _sidecar(
        self,
        directory: Path,
        *,
        red: bool,
        ts: float = 1000.0,
        compacting: bool | None = None,
        critical: bool | None = None,
        compact_urgent: bool | None = None,
    ) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        payload: dict[str, object] = {
            "red": red,
            "tier": "red" if red else "green",
            "pct": 85.0,
            "session_id": "s",
            "ts": ts,
            "seq": 1,
            "writer_pid": 1,
        }
        if compacting is not None:
            payload["compacting"] = compacting
        if critical is not None:
            payload["critical"] = critical
        if compact_urgent is not None:
            payload["compact_urgent"] = compact_urgent
        (directory / "s.json").write_text(json.dumps(payload), encoding="utf-8")

    def test_red_idle_injects_marker(self, tmp_path: Path) -> None:
        self._sidecar(tmp_path / "sc", red=True)
        written: list[bytes] = []
        ev = _mod._poll_once(
            CompactStateMachine(CompactPolicy()),
            sidecar_dir=tmp_path / "sc",
            now_wall=1000.0,
            idle=True,
            dry_run=True,
            master_writer=written.append,
            log=None,
            freshness_seconds=30.0,
        )
        assert ev.decision is Decision.WOULD_COMPACT
        expected = _mod._resolve_payload(Decision.WOULD_COMPACT, dry_run=True, now_wall=1000.0)
        assert b"".join(written) == (expected + "\r").encode("utf-8")

    def test_not_red_no_injection(self, tmp_path: Path) -> None:
        self._sidecar(tmp_path / "sc", red=False)
        written: list[bytes] = []
        ev = _mod._poll_once(
            CompactStateMachine(CompactPolicy()),
            sidecar_dir=tmp_path / "sc",
            now_wall=1000.0,
            idle=True,
            dry_run=True,
            master_writer=written.append,
            log=None,
            freshness_seconds=30.0,
        )
        assert ev.decision is Decision.NOOP
        assert written == []

    def _red_sidecar_named(self, directory: Path, name: str, ts: float) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        payload = {
            "red": True,
            "tier": "red",
            "pct": 85.0,
            "compact_urgent": True,
            "session_id": name,
            "ts": ts,
            "seq": 1,
            "writer_pid": 1,
        }
        (directory / f"{name}.json").write_text(json.dumps(payload), encoding="utf-8")

    def test_ambiguous_foreground_defers_injection(self, tmp_path: Path) -> None:
        """Two fresh red sidecars within the margin (a thread switch) -> no inject."""
        sc = tmp_path / "sc"
        self._red_sidecar_named(sc, "newfg", ts=1000.0)
        self._red_sidecar_named(sc, "oldfg", ts=999.0)  # 1s apart, within 10s margin
        written: list[bytes] = []
        ev = _mod._poll_once(
            CompactStateMachine(CompactPolicy()),
            sidecar_dir=sc,
            now_wall=1000.0,
            idle=True,
            dry_run=True,
            master_writer=written.append,
            log=None,
            freshness_seconds=30.0,
        )
        assert ev.decision is Decision.NOOP
        assert ev.reason == _mod._REASON_FOREGROUND_AMBIGUOUS
        assert written == []

    def test_unambiguous_foreground_injects(self, tmp_path: Path) -> None:
        """Freshest red sidecar clearly leads (backgrounded one aged out) -> inject."""
        sc = tmp_path / "sc"
        self._red_sidecar_named(sc, "fg", ts=1000.0)
        self._red_sidecar_named(sc, "old", ts=985.0)  # 15s back, beyond the 10s margin
        written: list[bytes] = []
        ev = _mod._poll_once(
            CompactStateMachine(CompactPolicy()),
            sidecar_dir=sc,
            now_wall=1000.0,
            idle=True,
            dry_run=True,
            master_writer=written.append,
            log=None,
            freshness_seconds=30.0,
        )
        assert ev.decision is Decision.WOULD_COMPACT
        assert written != []

    def test_busy_no_injection(self, tmp_path: Path) -> None:
        self._sidecar(tmp_path / "sc", red=True)
        written: list[bytes] = []
        ev = _mod._poll_once(
            CompactStateMachine(CompactPolicy()),
            sidecar_dir=tmp_path / "sc",
            now_wall=1000.0,
            idle=False,
            dry_run=True,
            master_writer=written.append,
            log=None,
            freshness_seconds=30.0,
        )
        assert ev.decision is Decision.NOOP
        assert written == []

    def test_armed_injects_real_slash_compact_with_chrome(self, tmp_path: Path) -> None:
        self._sidecar(tmp_path / "sc", red=True)
        written: list[bytes] = []
        _mod._poll_once(
            CompactStateMachine(CompactPolicy()),
            sidecar_dir=tmp_path / "sc",
            now_wall=1000.0,
            idle=True,
            dry_run=False,
            master_writer=written.append,
            log=None,
            freshness_seconds=30.0,
        )
        payload = b"".join(written).decode("utf-8")
        # Slash command first (recognised), bot chrome in the instruction arg,
        # submitted with a carriage return.
        assert payload.startswith("/compact ")
        assert "🤖" in payload
        assert payload.endswith("\r")

    def test_human_compact_suppresses_supervisor_compact(self, tmp_path: Path) -> None:
        # A detected human /compact must stop the supervisor injecting its own.
        self._sidecar(tmp_path / "sc", red=True)
        written: list[bytes] = []
        ev = _mod._poll_once(
            CompactStateMachine(CompactPolicy()),
            sidecar_dir=tmp_path / "sc",
            now_wall=1000.0,
            idle=True,
            dry_run=True,
            master_writer=written.append,
            log=None,
            freshness_seconds=30.0,
            human_compact_submitted=True,
        )
        assert ev.decision is Decision.NOOP
        assert written == []

    def test_escape_injects_raw_esc_without_submit(self, tmp_path: Path) -> None:
        # After a supervisor /compact that never starts compacting, the ESC flush
        # writes a bare ESC byte with NO trailing carriage return. Plan 00152
        # reserves the ESC flush for CRITICAL, so the sidecar is critical.
        sc = tmp_path / "sc"
        self._sidecar(sc, red=True, critical=True)
        machine = CompactStateMachine(
            CompactPolicy(escape_after_seconds=60, await_timeout_seconds=600)
        )
        # Tick 1: red + idle -> inject /compact, enter AWAIT at t=1000.
        _mod._poll_once(
            machine,
            sidecar_dir=sc,
            now_wall=1000.0,
            idle=True,
            dry_run=False,
            master_writer=lambda _b: None,
            log=None,
            freshness_seconds=30.0,
        )
        # Tick 2: 65s later, still no compaction -> ESC flush.
        written: list[bytes] = []
        ev = _mod._poll_once(
            machine,
            sidecar_dir=sc,
            now_wall=1065.0,
            idle=True,
            dry_run=False,
            master_writer=written.append,
            log=None,
            freshness_seconds=30.0,
        )
        assert ev.decision is Decision.WOULD_ESCAPE
        assert b"".join(written) == b"\x1b"

    def test_injection_is_logged(self, tmp_path: Path) -> None:
        self._sidecar(tmp_path / "sc", red=True)
        log = DecisionLog(tmp_path / "decision.log")
        _mod._poll_once(
            CompactStateMachine(CompactPolicy()),
            sidecar_dir=tmp_path / "sc",
            now_wall=1000.0,
            idle=True,
            dry_run=True,
            master_writer=lambda _b: None,
            log=log,
            freshness_seconds=30.0,
        )
        contents = (tmp_path / "decision.log").read_text(encoding="utf-8")
        assert "would-compact" in contents
        assert "injected" in contents


class TestPollOnceNoopLogging:
    """Plan 00168 Phase 1: every NOOP tick records WHY it did nothing.

    A red-but-not-compacting session previously left ZERO trace of which gate
    blocked (``_apply_decision`` only logged actual injections). These tests
    pin the new deduped NOOP-reason logging: the gate is named, the observed
    context band is annotated, and an unchanged reason never floods the log.
    """

    def _sidecar(
        self,
        directory: Path,
        *,
        red: bool,
        tier: str,
        critical: bool = False,
        compact_urgent: bool = False,
        ts: float = 1000.0,
    ) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        payload = {
            "red": red,
            "tier": tier,
            "pct": 85.0 if red else 5.0,
            "critical": critical,
            "compact_urgent": compact_urgent,
            "session_id": "s",
            "ts": ts,
            "seq": 1,
            "writer_pid": 1,
        }
        (directory / "s.json").write_text(json.dumps(payload), encoding="utf-8")

    def _poll(self, sc: Path, log: object, *, idle: bool) -> None:
        _mod._poll_once(
            CompactStateMachine(CompactPolicy()),
            sidecar_dir=sc,
            now_wall=1000.0,
            idle=idle,
            dry_run=True,
            master_writer=lambda _b: None,
            log=log,
            freshness_seconds=30.0,
        )

    def test_benign_green_noop_is_silent(self, tmp_path: Path) -> None:
        # A positively not-red, non-stale context is the common idle tick with
        # nothing to do -- it carries no diagnostic value, so the log stays empty
        # (the blind-spot gates below are what DO get recorded).
        sc = tmp_path / "sc"
        self._sidecar(sc, red=False, tier="green")
        log_path = tmp_path / "decision.log"
        self._poll(sc, DecisionLog(log_path), idle=True)
        assert not log_path.exists()

    def test_consecutive_identical_gate_noop_is_deduped(self, tmp_path: Path) -> None:
        # A red context gated on a busy TUI, held for several ticks, logs ONCE.
        sc = tmp_path / "sc"
        self._sidecar(sc, red=True, tier="red")
        log = DecisionLog(tmp_path / "decision.log")
        for _ in range(4):
            self._poll(sc, log, idle=False)
        lines = (tmp_path / "decision.log").read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1

    def test_red_busy_noop_names_gate_and_red_band(self, tmp_path: Path) -> None:
        # Red context + a busy TUI (idle=False) -> gated on "session busy"; the
        # log must record the gate AND that the context was already red.
        sc = tmp_path / "sc"
        self._sidecar(sc, red=True, tier="red")
        log = DecisionLog(tmp_path / "decision.log")
        self._poll(sc, log, idle=False)
        contents = (tmp_path / "decision.log").read_text(encoding="utf-8")
        assert "noop:" in contents
        assert _mod._REASON_BUSY_COMPOSING in contents
        assert "[red]" in contents

    def test_critical_busy_noop_annotates_critical_band(self, tmp_path: Path) -> None:
        sc = tmp_path / "sc"
        self._sidecar(sc, red=True, tier="critical", critical=True)
        log = DecisionLog(tmp_path / "decision.log")
        self._poll(sc, log, idle=False)
        contents = (tmp_path / "decision.log").read_text(encoding="utf-8")
        assert "[critical]" in contents

    def test_no_sidecar_noop_is_logged(self, tmp_path: Path) -> None:
        # H1/H3 signature: the sidecar is absent/filtered, so the supervisor sees
        # no reading. This MUST leave a trace (deduped) rather than nothing.
        sc = tmp_path / "sc"
        sc.mkdir(parents=True)
        log = DecisionLog(tmp_path / "decision.log")
        self._poll(sc, log, idle=True)
        contents = (tmp_path / "decision.log").read_text(encoding="utf-8")
        assert "noop: no sidecar reading" in contents

    def test_injection_is_not_logged_as_noop(self, tmp_path: Path) -> None:
        sc = tmp_path / "sc"
        self._sidecar(sc, red=True, tier="red")
        log = DecisionLog(tmp_path / "decision.log")
        self._poll(sc, log, idle=True)
        contents = (tmp_path / "decision.log").read_text(encoding="utf-8")
        assert "would-compact" in contents
        assert "noop:" not in contents


def _write_signal(directory: Path, name: str, *, ts: float) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{name}.compacting").write_text(json.dumps({"ts": ts}), encoding="utf-8")


class TestLoadCompactionSignal:
    def test_missing_dir_is_none(self, tmp_path: Path) -> None:
        assert _mod.load_compaction_signal(tmp_path / "no", now=1000.0, ttl_seconds=120.0) is None

    def test_no_signal_is_none(self, tmp_path: Path) -> None:
        tmp_path.mkdir(exist_ok=True)
        assert _mod.load_compaction_signal(tmp_path, now=1000.0, ttl_seconds=120.0) is None

    def test_fresh_signal_returns_path(self, tmp_path: Path) -> None:
        _write_signal(tmp_path, "s", ts=1000.0)
        result = _mod.load_compaction_signal(tmp_path, now=1050.0, ttl_seconds=120.0)
        assert result == tmp_path / "s.compacting"

    def test_stale_signal_is_none(self, tmp_path: Path) -> None:
        _write_signal(tmp_path, "s", ts=1000.0)
        assert _mod.load_compaction_signal(tmp_path, now=1200.0, ttl_seconds=120.0) is None

    def test_ignores_json_sidecars(self, tmp_path: Path) -> None:
        # A .json context sidecar must never be read as a compaction signal.
        tmp_path.mkdir(exist_ok=True)
        (tmp_path / "s.json").write_text(json.dumps({"ts": 1000.0}), encoding="utf-8")
        assert _mod.load_compaction_signal(tmp_path, now=1000.0, ttl_seconds=120.0) is None


class TestPollOnceCompaction:
    def test_signal_fires_continue_even_without_sidecar(self, tmp_path: Path) -> None:
        sc = tmp_path / "sc"
        _write_signal(sc, "s", ts=1000.0)  # signal only, no context sidecar
        written: list[bytes] = []
        ev = _mod._poll_once(
            CompactStateMachine(CompactPolicy()),
            sidecar_dir=sc,
            now_wall=1000.0,
            idle=True,
            dry_run=True,
            master_writer=written.append,
            log=None,
            freshness_seconds=30.0,
            compaction_signal_ttl_seconds=120.0,
        )
        assert ev.decision is Decision.WOULD_CONTINUE
        expected = _mod._resolve_payload(Decision.WOULD_CONTINUE, dry_run=True, now_wall=1000.0)
        assert b"".join(written) == (expected + "\r").encode("utf-8")

    def test_signal_overrides_green_sidecar(self, tmp_path: Path) -> None:
        sc = tmp_path / "sc"
        sc.mkdir(parents=True)
        (sc / "s.json").write_text(
            json.dumps(
                {"red": False, "tier": "green", "pct": 5.0, "ts": 1000.0, "session_id": "s"}
            ),
            encoding="utf-8",
        )
        _write_signal(sc, "s", ts=1000.0)
        written: list[bytes] = []
        ev = _mod._poll_once(
            CompactStateMachine(CompactPolicy()),
            sidecar_dir=sc,
            now_wall=1000.0,
            idle=True,
            dry_run=True,
            master_writer=written.append,
            log=None,
            freshness_seconds=30.0,
            compaction_signal_ttl_seconds=120.0,
        )
        assert ev.decision is Decision.WOULD_CONTINUE
        expected = _mod._resolve_payload(Decision.WOULD_CONTINUE, dry_run=True, now_wall=1000.0)
        assert b"".join(written) == (expected + "\r").encode("utf-8")

    def test_resume_consumes_signal_file(self, tmp_path: Path) -> None:
        # After a resume fires, the signal file is deleted so it cannot re-fire
        # or wedge a later compaction -- this is the fix for the live failure
        # where a lingering-but-stale signal left the session idle.
        sc = tmp_path / "sc"
        _write_signal(sc, "s", ts=1000.0)
        ev = _mod._poll_once(
            CompactStateMachine(CompactPolicy()),
            sidecar_dir=sc,
            now_wall=1000.0,
            idle=True,
            dry_run=True,
            master_writer=lambda _b: None,
            log=None,
            freshness_seconds=30.0,
            compaction_signal_ttl_seconds=120.0,
        )
        assert ev.decision is Decision.WOULD_CONTINUE
        assert not (sc / "s.compacting").exists()

    def test_busy_session_defers_resume_and_keeps_signal(self, tmp_path: Path) -> None:
        # A compaction detected while the human is composing must NOT inject
        # `continue` (it would corrupt their input); the signal is left in place
        # to retry on the next idle poll.
        sc = tmp_path / "sc"
        _write_signal(sc, "s", ts=1000.0)
        written: list[bytes] = []
        ev = _mod._poll_once(
            CompactStateMachine(CompactPolicy()),
            sidecar_dir=sc,
            now_wall=1000.0,
            idle=False,
            dry_run=True,
            master_writer=written.append,
            log=None,
            freshness_seconds=30.0,
            compaction_signal_ttl_seconds=120.0,
        )
        assert ev.decision is Decision.NOOP
        assert written == []
        assert (sc / "s.compacting").exists()


class TestForwardIoPolling:
    def test_on_poll_runs_on_select_timeout(self) -> None:
        stdin_read_fd, stdin_write_fd = os.pipe()
        master_read_fd, master_write_fd = os.pipe()
        calls = {"count": 0}

        def _on_poll() -> None:
            calls["count"] += 1
            if calls["count"] >= 2:
                # Close the master write end -> EOF makes _forward_io return.
                os.close(master_write_fd)

        try:
            _mod._forward_io(
                stdin_read_fd,
                master_read_fd,
                InputActivity(),
                poll_seconds=0.01,
                on_poll=_on_poll,
            )
        finally:
            os.close(stdin_read_fd)
            os.close(stdin_write_fd)
            os.close(master_read_fd)

        assert calls["count"] >= 2

    def test_stdin_eof_is_dropped_so_polling_still_fires(self) -> None:
        # An EOF stdin is always "readable"; it must be dropped from the watch
        # set so the poll timeout can still fire (else the loop would spin).
        stdin_read_fd, stdin_write_fd = os.pipe()
        os.close(stdin_write_fd)  # immediate EOF on stdin
        master_read_fd, master_write_fd = os.pipe()
        calls = {"count": 0}

        def _on_poll() -> None:
            calls["count"] += 1
            os.close(master_write_fd)  # end the loop after the first poll

        try:
            _mod._forward_io(
                stdin_read_fd,
                master_read_fd,
                InputActivity(),
                poll_seconds=0.01,
                on_poll=_on_poll,
            )
        finally:
            os.close(stdin_read_fd)
            os.close(master_read_fd)

        assert calls["count"] >= 1
