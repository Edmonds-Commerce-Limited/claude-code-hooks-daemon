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
import signal
import socket
import threading
from collections.abc import Callable, Iterator

import pytest

from tests.unit.supervise._load import load_supervisor_module

_mod = load_supervisor_module()
InputActivity = _mod.InputActivity
strip_suspend = _mod.strip_suspend
install_input_signal_guards = _mod.install_input_signal_guards
_CTRL_Z_NOTICE_TEXT = _mod._CTRL_Z_NOTICE_TEXT
_CTRL_BACKSLASH_NOTICE_TEXT = _mod._CTRL_BACKSLASH_NOTICE_TEXT

_SUSPEND = b"\x1a"
# Bound on the socketpair recv + thread join so a hung _forward_io never wedges
# the test run (named to satisfy the magic-timeout QA rule).
_IO_TIMEOUT_SECONDS = 2.0

# Signals the guard touches; saved/restored around each guard test so installing
# real handlers cannot leak into the rest of the pytest process.
_GUARDED_SIGNALS = (
    signal.SIGTSTP,
    signal.SIGQUIT,
    signal.SIGTTIN,
    signal.SIGTTOU,
    signal.SIGINT,
)


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

    def _drive(
        self,
        stdin_payload: bytes,
        *,
        on_suspend: Callable[[], object] | None = None,
    ) -> bytes:
        """Run ``_forward_io`` over pipes and return the bytes it forwarded.

        stdin is a pipe we write ``stdin_payload`` into; the child (master) side
        is a socketpair so ``_forward_io`` can BOTH write forwarded stdin to it
        and read child output from it (a real PTY master is bidirectional). We
        read the forwarded bytes off the far end, then close it so the master
        read returns EOF and ``_forward_io`` returns.
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
                    on_suspend=on_suspend,
                )
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

    def test_lone_ctrl_z_never_reaches_child(self) -> None:
        assert self._drive(b"\x1a") == b""

    def test_ctrl_z_stripped_from_surrounding_input(self) -> None:
        assert self._drive(b"a\x1ab") == b"ab"

    def test_plain_input_passes_through_unchanged(self) -> None:
        assert self._drive(b"hello") == b"hello"

    def test_on_suspend_fires_when_a_suspend_byte_is_dropped(self) -> None:
        calls = {"count": 0}

        def _cb() -> None:
            calls["count"] += 1

        assert self._drive(b"a\x1ab", on_suspend=_cb) == b"ab"
        assert calls["count"] == 1

    def test_on_suspend_not_fired_for_plain_input(self) -> None:
        calls = {"count": 0}

        def _cb() -> None:
            calls["count"] += 1

        assert self._drive(b"hello", on_suspend=_cb) == b"hello"
        assert calls["count"] == 0


class TestInputSignalGuards:
    """Belt-and-braces: swallow stop/quit SIGNALS if they reach the supervisor.

    The byte strip only covers Ctrl+Z while the outer terminal is in raw mode.
    If a stop/quit signal is actually delivered (a race before ``setraw``, a
    non-tty stdin, ``kill -TSTP``/``-QUIT``, or shell job control), the guard
    must swallow it so the session never freezes or core-dumps — while leaving
    the legitimate SIGINT (Ctrl+C) untouched.
    """

    @pytest.fixture(autouse=True)
    def _restore_signals(self) -> Iterator[None]:
        saved = {sig: signal.getsignal(sig) for sig in _GUARDED_SIGNALS}
        try:
            yield
        finally:
            for sig, handler in saved.items():
                signal.signal(sig, handler)

    def test_installs_swallowing_handlers_for_stop_and_quit(self) -> None:
        install_input_signal_guards(lambda _text: None)
        # A real callable handler (not default / ignore) for the stop + quit sigs.
        assert callable(signal.getsignal(signal.SIGTSTP))
        assert signal.getsignal(signal.SIGTSTP) not in (signal.SIG_DFL, signal.SIG_IGN)
        assert callable(signal.getsignal(signal.SIGQUIT))
        assert signal.getsignal(signal.SIGQUIT) not in (signal.SIG_DFL, signal.SIG_IGN)

    def test_ignores_background_tty_stop_signals(self) -> None:
        install_input_signal_guards(lambda _text: None)
        assert signal.getsignal(signal.SIGTTIN) == signal.SIG_IGN
        assert signal.getsignal(signal.SIGTTOU) == signal.SIG_IGN

    def test_leaves_sigint_untouched(self) -> None:
        before = signal.getsignal(signal.SIGINT)
        install_input_signal_guards(lambda _text: None)
        # Ctrl+C is a legitimate interrupt in Claude's TUI — never swallowed.
        assert signal.getsignal(signal.SIGINT) == before

    def test_stop_handler_posts_notice_and_does_not_stop(self) -> None:
        posted: list[str] = []
        install_input_signal_guards(posted.append)
        handler = signal.getsignal(signal.SIGTSTP)
        assert callable(handler)
        # Invoking the handler must NOT raise/stop; it posts the Ctrl+Z notice.
        assert handler(signal.SIGTSTP, None) is None
        assert posted == [_CTRL_Z_NOTICE_TEXT]

    def test_quit_handler_posts_notice_and_does_not_exit(self) -> None:
        posted: list[str] = []
        install_input_signal_guards(posted.append)
        handler = signal.getsignal(signal.SIGQUIT)
        assert callable(handler)
        assert handler(signal.SIGQUIT, None) is None
        assert posted == [_CTRL_BACKSLASH_NOTICE_TEXT]
