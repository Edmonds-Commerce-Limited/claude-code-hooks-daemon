"""Tests for the Ctrl+Z (SUSP) input guard in claude-supervise.py.

Ctrl+Z is universal muscle memory for "undo", but a terminal interprets it as
SIGTSTP. Pressing it against Claude can suspend the session and drop the user
to a shell -- painful to recover from inside a container (upstream
anthropics/claude-code#43596). The supervisor forwards operator stdin
byte-for-byte to the child PTY; the outer terminal is in raw mode so Ctrl+Z
arrives as a lone ``0x1a`` byte rather than a signal. The guard drops that byte
from the forwarded stream so it never reaches the child and can never suspend
anything -- Ctrl+Z becomes an inert, ignored keystroke.

Two layers are tested:

1. ``strip_suspend`` -- the pure byte-filter (the actual logic).
2. ``_forward_io`` end-to-end -- a ``0x1a`` written on stdin never reaches the
   child (master) fd, while surrounding bytes pass through unchanged.
"""

from __future__ import annotations

import os
import socket
import threading

from tests.unit.supervise._load import load_supervisor_module

_mod = load_supervisor_module()
InputActivity = _mod.InputActivity
strip_suspend = _mod.strip_suspend

_SUSPEND = b"\x1a"


class TestStripSuspend:
    """The pure ``strip_suspend(data) -> data`` byte filter."""

    def test_empty_stays_empty(self) -> None:
        assert strip_suspend(b"") == b""

    def test_plain_bytes_untouched(self) -> None:
        assert strip_suspend(b"hello world") == b"hello world"

    def test_lone_suspend_is_removed(self) -> None:
        assert strip_suspend(_SUSPEND) == b""

    def test_repeated_suspend_all_removed(self) -> None:
        assert strip_suspend(_SUSPEND * 5) == b""

    def test_embedded_suspend_removed_surrounding_survive(self) -> None:
        assert strip_suspend(b"a\x1ab") == b"ab"

    def test_trailing_suspend_removed(self) -> None:
        assert strip_suspend(b"abc\x1a") == b"abc"

    def test_leading_suspend_removed(self) -> None:
        assert strip_suspend(b"\x1aabc") == b"abc"

    def test_multiple_scattered_suspends_removed(self) -> None:
        assert strip_suspend(b"\x1aa\x1a\x1ab\x1ac\x1a") == b"abc"

    def test_other_control_bytes_are_preserved(self) -> None:
        # Only 0x1a is stripped; Ctrl+C, Ctrl+U, CR, ESC etc. are untouched.
        assert strip_suspend(b"\x03\x15\r\x1b") == b"\x03\x15\r\x1b"


class TestForwardIoDropsSuspend:
    """``_forward_io`` must never forward a ``0x1a`` byte to the child."""

    def _drive(self, stdin_payload: bytes) -> bytes:
        """Run ``_forward_io`` over pipes and return the bytes it forwarded.

        stdin is a pipe we write ``stdin_payload`` into; the child (master) side
        is a socketpair so ``_forward_io`` can BOTH write forwarded stdin to it
        and read child output from it (a real PTY master is bidirectional). We
        read the forwarded bytes off the far end, then close it so the master
        read returns EOF and ``_forward_io`` returns.
        """
        stdin_r, stdin_w = os.pipe()
        master_side, child_side = socket.socketpair()
        child_side.settimeout(2.0)
        forwarded = bytearray()

        def run() -> None:
            try:
                _mod._forward_io(stdin_r, master_side.fileno(), InputActivity())
            except OSError:
                # Expected once the fds are torn down at the end.
                pass

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        try:
            os.write(stdin_w, stdin_payload)
            # Accumulate whatever survived the guard until the far end is idle.
            expected = strip_suspend(stdin_payload)
            while len(forwarded) < len(expected):
                try:
                    chunk = child_side.recv(64)
                except socket.timeout:
                    break
                if not chunk:
                    break
                forwarded += chunk
        finally:
            child_side.close()  # EOF on master -> _forward_io returns
            thread.join(timeout=2.0)
            os.close(stdin_r)
            os.close(stdin_w)
            master_side.close()
        return bytes(forwarded)

    def test_lone_ctrl_z_never_reaches_child(self) -> None:
        assert self._drive(b"\x1a") == b""

    def test_ctrl_z_stripped_from_surrounding_input(self) -> None:
        assert self._drive(b"a\x1ab") == b"ab"

    def test_plain_input_passes_through_unchanged(self) -> None:
        assert self._drive(b"hello") == b"hello"
