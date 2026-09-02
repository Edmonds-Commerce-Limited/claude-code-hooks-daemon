"""Plan 00317 Task 2.1 — the host->worker raw-input tap.

``RawInputTap`` is a bounded, fail-open buffer the PTY host feeds with every
forwarded stdin chunk (alongside ``InputActivity.record``) so the raw bytes
can be shipped to the hot-reloadable ``--worker`` subprocess for typed-command
recognition, instead of that recognition running host-side (which never
reloads). It must never grow unbounded and must never raise.
"""

from __future__ import annotations

import os

from tests.unit.supervise._load import load_supervisor_module

_mod = load_supervisor_module()


def test_drain_returns_and_clears_appended_bytes() -> None:
    tap = _mod.RawInputTap()
    tap.append(b"/model opus")
    assert tap.drain() == b"/model opus"
    assert tap.drain() == b""  # cleared after drain


def test_multiple_appends_accumulate_in_order() -> None:
    tap = _mod.RawInputTap()
    tap.append(b"/mo")
    tap.append(b"del ")
    tap.append(b"opus\r")
    assert tap.drain() == b"/model opus\r"


def test_drain_on_empty_tap_returns_empty_bytes() -> None:
    tap = _mod.RawInputTap()
    assert tap.drain() == b""


def test_overflow_drops_oldest_bytes_never_raises() -> None:
    tap = _mod.RawInputTap(max_bytes=4)
    tap.append(b"abcdef")  # 6 bytes appended to a 4-byte-bounded buffer
    assert tap.drain() == b"cdef"  # oldest 2 bytes dropped, newest 4 kept


def test_overflow_across_multiple_appends_keeps_bound() -> None:
    tap = _mod.RawInputTap(max_bytes=5)
    for _ in range(20):
        tap.append(b"xy")  # 40 bytes total, bound is 5
    drained = tap.drain()
    assert len(drained) == 5
    assert drained == b"yxyxy"  # tail of the interleaved stream, oldest dropped


def test_forward_io_forwards_input_when_raw_tap_is_never_drained() -> None:
    """Fail-open (Plan 00317 Task 2.1): an un-drained (e.g. worker-dead) tap
    must never block or alter what `_forward_io` forwards to the child, even
    when the buffered volume vastly exceeds the tap's bound."""
    stdin_read_fd, stdin_write_fd = os.pipe()
    master_fd, slave_fd = os.openpty()
    activity = _mod.InputActivity()
    raw_tap = _mod.RawInputTap(max_bytes=8)  # tiny bound; input far exceeds it
    payload = b"human typed text that is much longer than the tap bound"
    os.write(stdin_write_fd, payload)
    os.close(stdin_write_fd)
    state = {"slave_open": True}

    def _on_poll() -> None:
        if state["slave_open"]:
            state["slave_open"] = False
            os.close(slave_fd)  # master read now EOFs -> loop ends

    try:
        _mod._forward_io(
            stdin_read_fd,
            master_fd,
            activity,
            poll_seconds=0.01,
            on_poll=_on_poll,
            raw_tap=raw_tap,
        )
    finally:
        os.close(stdin_read_fd)
        os.close(master_fd)
        if state["slave_open"]:
            os.close(slave_fd)

    # Forwarding (host->child) is complete and unaltered regardless of the tap.
    assert activity.bytes_seen == len(payload)
    # The un-drained tap held only its bound worth -- never grew unbounded.
    assert len(raw_tap.drain()) == 8
