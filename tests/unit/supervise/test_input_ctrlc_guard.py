"""Tests for the Ctrl+C double-press guard in claude-supervise.py (Plan 00312).

In current Claude Code a single Ctrl+C kills background agents, so one
accidental ``^C`` — muscle memory from any other terminal — can destroy hours
of delegated work. The supervisor owns the PTY between the terminal and the
``claude`` child, and the outer terminal is in raw mode, so Ctrl+C arrives as
a lone ``0x03`` byte on stdin rather than a signal. The guard swallows that
first lone press, arms a confirm window, and forwards a second press that
lands inside the window — spamming Ctrl+C always wins.

Paste-burst safety: only a chunk that is EXACTLY one ``0x03`` byte is treated
as a press. A ``0x03`` embedded in a larger chunk (a paste, or two presses
coalesced into one read) is not a lone keystroke and passes through
unchanged, so the guard can never corrupt pasted content and rapid spamming
is never delayed by chunk coalescing.

Three layers are tested:

1. ``CtrlCGate`` — the pure press-gating state machine (the actual logic).
2. Env resolution — enabled flag and window seconds.
3. ``_forward_io`` end-to-end — a lone ``0x03`` on stdin never reaches the
   child (master) fd, a second press within the window does.
"""

from __future__ import annotations

import os
import socket
import threading
import time
from collections.abc import Callable
from typing import Any

from tests.unit.supervise._load import load_supervisor_module

_mod = load_supervisor_module()
InputActivity = _mod.InputActivity
CtrlCGate = _mod.CtrlCGate

_INTERRUPT = b"\x03"
# Bound on the socketpair recv + thread join so a hung _forward_io never wedges
# the test run (named to satisfy the magic-timeout QA rule).
_IO_TIMEOUT_SECONDS = 2.0
# A window comfortably longer than any test's execution between two presses.
_WIDE_WINDOW_SECONDS = 60.0
# Gap between sequential stdin writes so each press arrives as its own read.
_WRITE_SPACING_SECONDS = 0.1


class _FakeClock:
    """Deterministic monotonic clock the tests advance by hand."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class TestCtrlCGatePressLogic:
    """The pure ``CtrlCGate.filter(data) -> (forwarded, event)`` machine."""

    def _gate(self, **kwargs: Any) -> tuple[Any, _FakeClock]:
        clock = _FakeClock()
        gate = CtrlCGate(clock=clock, **kwargs)
        return gate, clock

    def test_first_lone_press_is_swallowed(self) -> None:
        gate, _clock = self._gate()
        forwarded, event = gate.filter(_INTERRUPT)
        assert forwarded == b""
        assert event == _mod._CTRL_C_EVENT_SWALLOWED

    def test_second_press_within_window_is_forwarded(self) -> None:
        gate, clock = self._gate()
        gate.filter(_INTERRUPT)
        clock.now += 0.5
        forwarded, event = gate.filter(_INTERRUPT)
        assert forwarded == _INTERRUPT
        assert event == _mod._CTRL_C_EVENT_FORWARDED

    def test_press_after_window_expiry_is_swallowed_again(self) -> None:
        gate, clock = self._gate(window_seconds=2.0)
        gate.filter(_INTERRUPT)
        clock.now += 2.5
        forwarded, event = gate.filter(_INTERRUPT)
        assert forwarded == b""
        assert event == _mod._CTRL_C_EVENT_SWALLOWED

    def test_forwarded_press_disarms_the_gate(self) -> None:
        # After a forwarded double-press, the NEXT press starts a fresh cycle
        # (swallowed again) rather than riding the old arm.
        gate, clock = self._gate()
        gate.filter(_INTERRUPT)
        clock.now += 0.1
        gate.filter(_INTERRUPT)
        clock.now += 0.1
        forwarded, event = gate.filter(_INTERRUPT)
        assert forwarded == b""
        assert event == _mod._CTRL_C_EVENT_SWALLOWED

    def test_plain_input_passes_through_with_no_event(self) -> None:
        gate, _clock = self._gate()
        forwarded, event = gate.filter(b"hello")
        assert forwarded == b"hello"
        assert event is None

    def test_paste_chunk_containing_interrupt_passes_through(self) -> None:
        # A 0x03 embedded in a larger chunk is a paste burst, not a keystroke.
        gate, _clock = self._gate()
        payload = b"before\x03after"
        forwarded, event = gate.filter(payload)
        assert forwarded == payload
        assert event is None

    def test_coalesced_double_press_chunk_passes_through(self) -> None:
        # Two presses arriving in ONE read chunk means the user is spamming
        # faster than the loop reads — that is the escape hatch; forward it.
        gate, _clock = self._gate()
        forwarded, event = gate.filter(_INTERRUPT * 2)
        assert forwarded == _INTERRUPT * 2
        assert event is None

    def test_plain_input_does_not_disturb_an_armed_window(self) -> None:
        # Typing between the two presses must not disarm the gate.
        gate, clock = self._gate()
        gate.filter(_INTERRUPT)
        gate.filter(b"x")
        clock.now += 0.5
        forwarded, event = gate.filter(_INTERRUPT)
        assert forwarded == _INTERRUPT
        assert event == _mod._CTRL_C_EVENT_FORWARDED

    def test_disabled_gate_forwards_lone_press_untouched(self) -> None:
        gate, _clock = self._gate(enabled=False)
        forwarded, event = gate.filter(_INTERRUPT)
        assert forwarded == _INTERRUPT
        assert event is None

    def test_boundary_press_exactly_at_window_edge_is_forwarded(self) -> None:
        gate, clock = self._gate(window_seconds=2.0)
        gate.filter(_INTERRUPT)
        clock.now += 2.0
        forwarded, event = gate.filter(_INTERRUPT)
        assert forwarded == _INTERRUPT
        assert event == _mod._CTRL_C_EVENT_FORWARDED


class TestCtrlCGateEnvResolution:
    """Env-var resolution for the enabled flag and the confirm window."""

    def test_guard_enabled_by_default(self) -> None:
        assert _mod._resolve_ctrl_c_guard_enabled(env={}) is True

    def test_guard_disabled_by_zero(self) -> None:
        assert _mod._resolve_ctrl_c_guard_enabled(env={"CCY_CTRL_C_GUARD": "0"}) is False

    def test_guard_disabled_by_false_word(self) -> None:
        assert _mod._resolve_ctrl_c_guard_enabled(env={"CCY_CTRL_C_GUARD": "false"}) is False

    def test_guard_enabled_by_explicit_one(self) -> None:
        assert _mod._resolve_ctrl_c_guard_enabled(env={"CCY_CTRL_C_GUARD": "1"}) is True

    def test_window_defaults_when_unset(self) -> None:
        assert _mod._resolve_ctrl_c_window_seconds(env={}) == _mod._CTRL_C_CONFIRM_WINDOW_SECONDS

    def test_window_reads_env_override(self) -> None:
        assert _mod._resolve_ctrl_c_window_seconds(env={"CCY_CTRL_C_WINDOW_SECONDS": "5"}) == 5.0

    def test_window_rejects_garbage_and_falls_back(self) -> None:
        assert (
            _mod._resolve_ctrl_c_window_seconds(env={"CCY_CTRL_C_WINDOW_SECONDS": "soon"})
            == _mod._CTRL_C_CONFIRM_WINDOW_SECONDS
        )

    def test_window_rejects_nonpositive_and_falls_back(self) -> None:
        assert (
            _mod._resolve_ctrl_c_window_seconds(env={"CCY_CTRL_C_WINDOW_SECONDS": "-1"})
            == _mod._CTRL_C_CONFIRM_WINDOW_SECONDS
        )


class TestForwardIoCtrlCGuard:
    """``_forward_io`` end-to-end with a ``CtrlCGate`` installed."""

    def _drive(
        self,
        payloads: list[bytes],
        *,
        gate: Any,
        expected: bytes,
        on_event: Callable[[str], object] | None = None,
    ) -> bytes:
        """Run ``_forward_io`` over pipes and return the bytes it forwarded.

        Mirrors the Ctrl+Z guard test rig: stdin is a pipe, the child side is
        a socketpair read until ``expected`` has arrived or the recv times out.
        """
        stdin_r, stdin_w = os.pipe()
        master_side, child_side = socket.socketpair()
        child_side.settimeout(_IO_TIMEOUT_SECONDS)
        forwarded = bytearray()

        def run() -> None:
            try:
                _mod._forward_io(
                    stdin_r,
                    master_side.fileno(),
                    InputActivity(),
                    ctrl_c_gate=gate,
                    on_ctrl_c_event=on_event,
                )
            except OSError:
                # Expected once the fds are torn down at the end.
                pass

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        try:
            for index, payload in enumerate(payloads):
                if index:
                    # Space the writes so the select loop reads each press as
                    # its own chunk — coalesced presses are (correctly) treated
                    # as spam passthrough by the gate, which is not what these
                    # sequenced-press tests exercise.
                    time.sleep(_WRITE_SPACING_SECONDS)
                os.write(stdin_w, payload)
            while len(forwarded) < len(expected):
                try:
                    chunk = child_side.recv(64)
                except TimeoutError:
                    break
                if not chunk:
                    break
                forwarded += chunk
        finally:
            child_side.close()  # EOF on master -> _forward_io returns
            thread.join(timeout=_IO_TIMEOUT_SECONDS)
            os.close(stdin_r)
            os.close(stdin_w)
            master_side.close()
        return bytes(forwarded)

    def test_lone_ctrl_c_never_reaches_child(self) -> None:
        gate = CtrlCGate(window_seconds=_WIDE_WINDOW_SECONDS)
        assert self._drive([_INTERRUPT], gate=gate, expected=b"") == b""

    def test_double_press_reaches_child(self) -> None:
        gate = CtrlCGate(window_seconds=_WIDE_WINDOW_SECONDS)
        result = self._drive([_INTERRUPT, _INTERRUPT], gate=gate, expected=_INTERRUPT)
        assert result == _INTERRUPT

    def test_events_are_reported_for_swallow_then_forward(self) -> None:
        events: list[str] = []
        gate = CtrlCGate(window_seconds=_WIDE_WINDOW_SECONDS)
        self._drive(
            [_INTERRUPT, _INTERRUPT], gate=gate, expected=_INTERRUPT, on_event=events.append
        )
        assert events == [_mod._CTRL_C_EVENT_SWALLOWED, _mod._CTRL_C_EVENT_FORWARDED]

    def test_plain_input_unaffected_by_gate(self) -> None:
        gate = CtrlCGate(window_seconds=_WIDE_WINDOW_SECONDS)
        assert self._drive([b"hello"], gate=gate, expected=b"hello") == b"hello"

    def test_no_gate_forwards_ctrl_c_as_before(self) -> None:
        assert self._drive([_INTERRUPT], gate=None, expected=_INTERRUPT) == _INTERRUPT
