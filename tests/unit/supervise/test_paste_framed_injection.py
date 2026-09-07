"""A submitted payload is framed as a paste, so the Enter after it is a keypress.

Measured against a real Claude Code TUI (v2.1.263) driven over a PTY, with the
REAL 131-byte armed compact payload:

===========================================================  ==============
bytes written                                                result
===========================================================  ==============
``payload`` + ``\\r`` in ONE write                             sits UNSUBMITTED
``payload``, 0.2s pause, ``\\r``                               submits
``ESC[200~`` + ``payload`` + ``ESC[201~`` + ``\\r``, ONE write  submits
===========================================================  ==============

A short bare ``/compact\\r`` submits even as a single write, which is what makes
the mechanism specific: Claude Code treats a burst that large as PASTED TEXT,
and a carriage return inside pasted text is a literal newline, not a submit.
That is the reported failure exactly — a compaction message and a newline
sitting in the input box.

``_SUBMIT_DELAY_SECONDS`` was the previous defence, and it cannot be sufficient:
the pause is on the WRITE side while the paste heuristic is applied at the
READER, so a TUI event loop blocked longer than the pause sees one burst again.
Framing the payload with the explicit bracketed-paste markers states where the
paste ENDS, so the following ``\\r`` is unambiguously a keypress no matter how
the two writes are batched. The pause is kept as a second line of defence.

The pasted text still behaves as typed input: the probe showed the slash-command
menu opening on a pasted ``/compact`` and the submitted command running (it
answered "Not enough messages to compact"), so slash-command recognition — the
risk that made this worth measuring rather than reasoning about — is intact.
"""

from __future__ import annotations

from tests.unit.supervise._load import load_supervisor_module

_mod = load_supervisor_module()


def _written(payload: str, **kwargs: object) -> list[bytes]:
    written: list[bytes] = []
    _mod._perform_injection(written.append, payload, sleep=lambda _s: None, **kwargs)
    return written


class TestASubmittedPayloadIsPasteFramed:
    """The framing is what makes the submit boundary explicit rather than timed."""

    def test_the_payload_is_wrapped_in_bracketed_paste_markers(self) -> None:
        assert _written("hello world") == [b"\x1b[200~hello world\x1b[201~", b"\r"]

    def test_the_frame_and_payload_are_a_single_write(self) -> None:
        """A split write could be read as a paste that never ends.

        The start marker, the text and the end marker describe ONE paste; the
        reader must never see the opening marker without the closing one.
        """
        written = _written("hello world")

        assert written[0].startswith(b"\x1b[200~")
        assert written[0].endswith(b"\x1b[201~")

    def test_the_enter_is_still_a_separate_write_after_the_pause(self) -> None:
        """Framing is the fix; the pause stays as a second line of defence."""
        written: list[bytes] = []
        sleeps: list[float] = []
        _mod._perform_injection(written.append, "hello world", sleep=sleeps.append)

        assert written[-1] == b"\r"
        assert sleeps == [_mod._SUBMIT_DELAY_SECONDS]

    def test_the_enter_is_outside_the_paste(self) -> None:
        """A CR inside the markers is the literal newline this bug is made of."""
        assert b"\r" not in _written("hello world")[0]

    def test_the_payload_text_is_unchanged_inside_the_frame(self) -> None:
        """`/compact` must stay the first token or it is not a slash command."""
        written = _written("/compact do the thing")

        assert written[0] == b"\x1b[200~/compact do the thing\x1b[201~"

    def test_confirmation_enters_stay_bare_keypresses(self) -> None:
        """A /model confirmation dialog needs an Enter, not a pasted line."""
        assert _written("/model fable", confirm_enters=2) == [
            b"\x1b[200~/model fable\x1b[201~",
            b"\r",
            b"\r",
            b"\r",
        ]


class TestEveryInjectedPayloadStaysUnderThePlaceholderThreshold:
    """A paste too large stops being text and becomes a REFERENCE to text.

    Measured on the same PTY rig, framed, single-line, control-byte free:

    ========  ==========================
    payload   input box shows
    ========  ==========================
    134 B     the text, inline
    303 B     the text, inline
    503 B     the text, inline
    803 B     ``[Pasted text #1]``
    1503 B    ``[Pasted text #2]``
    ========  ==========================

    Above the threshold Claude Code collapses the paste to a placeholder, so a
    submitted `/compact` would carry a reference rather than the instruction --
    the injection silently becomes meaningless. Every payload the supervisor
    builds is capped well under it TODAY; this pins that, because the failure
    mode is invisible (the line submits, it just says nothing) and the caps are
    the only thing keeping us on the safe side.
    """

    #: Half-way between the largest size measured to insert inline (503) and
    #: the smallest measured to collapse (803). Not a discovered constant --
    #: the exact threshold was not bisected, so this is the conservative bound
    #: the measurements support.
    SAFE_PAYLOAD_CEILING = 600

    def test_the_goal_payload_cap_is_under_the_threshold(self) -> None:
        assert _mod._GOAL_MAX_JOINED_CHARS <= self.SAFE_PAYLOAD_CEILING

    def test_the_standing_auth_payload_cap_is_under_the_threshold(self) -> None:
        assert _mod._STANDING_AUTH_MAX_JOINED_CHARS <= self.SAFE_PAYLOAD_CEILING

    def test_the_armed_compact_payload_is_under_the_threshold(self) -> None:
        """The compact payload is built from constants, not capped at all."""
        payload = _mod._resolve_payload(_mod.Decision.WOULD_COMPACT, dry_run=False)

        assert payload is not None
        assert len(payload.encode()) <= self.SAFE_PAYLOAD_CEILING


class TestARawKeypressIsNeverFramed:
    """Framing a keypress would turn a control key into literal pasted text."""

    def test_the_escape_interrupt_is_written_raw(self) -> None:
        """A framed ESC would be pasted as text instead of interrupting."""
        assert _written("\x1b", submit=False) == [b"\x1b"]

    def test_the_resubmit_enter_is_written_raw(self) -> None:
        """A framed CR is the exact thing this whole change exists to avoid."""
        assert _written(_mod._RESUBMIT_PAYLOAD, submit=False) == [b"\r"]
