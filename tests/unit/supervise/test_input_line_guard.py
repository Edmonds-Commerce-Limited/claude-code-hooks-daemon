"""Tests for the empty-input-box injection guard in claude-supervise.py.

Production incident: the supervisor pasted its injection into a NON-EMPTY
input box that the human had partially typed into, then submitted the
corrupted mix of bot text and human text. The supervisor must ONLY inject
into an EMPTY input box.

The guard works by tracking the human input-line state from the operator
stdin bytes the supervisor already forwards (`InputActivity.record`), and
gating every injection path (armed /compact, continue, dry-run marker) in
`_poll_once` on that tracked line being empty. The supervisor's OWN injected
keystrokes are written straight to the PTY master and never pass through
`InputActivity.record`, so they can never mark the box non-empty.
"""

from __future__ import annotations

import json
import os
import time
from typing import TYPE_CHECKING

from tests.unit.supervise._load import load_supervisor_module

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

_mod = load_supervisor_module()
Decision = _mod.Decision
CompactPolicy = _mod.CompactPolicy
CompactStateMachine = _mod.CompactStateMachine
HumanInputLine = _mod.HumanInputLine
InputActivity = _mod.InputActivity
DecisionLog = _mod.DecisionLog

_DEFERRED = "injection deferred: input box not empty"
_ENTER = b"\r"
_CTRL_U = b"\x15"
_CTRL_C = b"\x03"
_DEL = b"\x7f"
_BACKSPACE = b"\x08"
_CTRL_W = b"\x17"
_CTRL_K = b"\x0b"


class TestHumanInputLine:
    """Byte-stream model of the human's input box contents."""

    def test_starts_empty(self) -> None:
        assert HumanInputLine().is_empty is True

    def test_printable_input_marks_non_empty(self) -> None:
        line = HumanInputLine()
        line.feed(b"fix the bug in")
        assert line.is_empty is False

    def test_whitespace_only_input_stays_empty(self) -> None:
        line = HumanInputLine()
        line.feed(b"  \t ")
        assert line.is_empty is True

    def test_enter_carriage_return_resets(self) -> None:
        line = HumanInputLine()
        line.feed(b"hello" + _ENTER)
        assert line.is_empty is True

    def test_enter_newline_resets(self) -> None:
        line = HumanInputLine()
        line.feed(b"hello\n")
        assert line.is_empty is True

    def test_ctrl_u_line_kill_resets(self) -> None:
        line = HumanInputLine()
        line.feed(b"hello" + _CTRL_U)
        assert line.is_empty is True

    def test_ctrl_c_resets(self) -> None:
        line = HumanInputLine()
        line.feed(b"hello" + _CTRL_C)
        assert line.is_empty is True

    def test_del_backspace_shrinks_to_empty(self) -> None:
        line = HumanInputLine()
        line.feed(b"ab" + _DEL + _DEL)
        assert line.is_empty is True

    def test_ctrl_h_backspace_shrinks_to_empty(self) -> None:
        line = HumanInputLine()
        line.feed(b"a" + _BACKSPACE)
        assert line.is_empty is True

    def test_partial_backspace_stays_non_empty(self) -> None:
        line = HumanInputLine()
        line.feed(b"ab" + _DEL)
        assert line.is_empty is False

    def test_backspace_on_empty_line_is_noop(self) -> None:
        line = HumanInputLine()
        line.feed(_DEL + _BACKSPACE)
        assert line.is_empty is True


class TestHumanInputLineStability:
    """Plan 00398 Phase 2: content-stability tracking, not mere non-emptiness.

    The owner's ruling ("if the text is the same after X seconds ... regard it
    as captured by accident") requires telling a human mid-sentence apart from
    one who has walked away. A naive "non-empty for threshold_seconds" timer
    gets the continuous-typing case wrong -- these tests pin that it does not.
    """

    _THRESHOLD = 120.0

    def test_empty_box_is_never_abandoned(self) -> None:
        line = HumanInputLine()
        assert line.is_abandoned(now=10_000.0, threshold_seconds=self._THRESHOLD) is False

    def test_unchanged_content_past_threshold_is_abandoned(self) -> None:
        line = HumanInputLine()
        line.feed(b"forgot to hit enter", now=1000.0)
        assert (
            line.is_abandoned(now=1000.0 + self._THRESHOLD, threshold_seconds=self._THRESHOLD)
            is True
        )

    def test_unchanged_content_just_under_threshold_is_not_abandoned(self) -> None:
        line = HumanInputLine()
        line.feed(b"still composing", now=1000.0)
        assert (
            line.is_abandoned(now=1000.0 + self._THRESHOLD - 1.0, threshold_seconds=self._THRESHOLD)
            is False
        )

    def test_continuous_typing_never_reads_abandoned(self) -> None:
        # The case a naive "non-empty for threshold_seconds" timer gets wrong:
        # the box has been non-empty for well over the threshold, but every
        # keystroke refreshes the "last changed" clock, so it must never trip.
        line = HumanInputLine()
        now = 1000.0
        line.feed(b"f", now=now)
        for _ in range(200):
            now += 1.0
            line.feed(b"x", now=now)
        assert now - 1000.0 > self._THRESHOLD  # sanity: the box IS old by now
        assert line.is_abandoned(now=now, threshold_seconds=self._THRESHOLD) is False

    def test_submitting_then_typing_again_restarts_the_clock(self) -> None:
        line = HumanInputLine()
        line.feed(b"old message" + _ENTER, now=1000.0)
        later = 1000.0 + self._THRESHOLD + 10.0
        line.feed(b"new", now=later)
        assert line.is_abandoned(now=later, threshold_seconds=self._THRESHOLD) is False

    def test_feed_without_explicit_now_does_not_raise(self) -> None:
        # The real (host/worker) callers do not always pass `now` -- defaults
        # to the real clock so every existing call site keeps working.
        line = HumanInputLine()
        line.feed(b"typed without an explicit clock")
        assert line.is_empty is False


class TestHumanInputLineForceClear:
    """Plan 00398 Phase 3: the flush path must be able to reset the model.

    The supervisor's own injected Enter (used to flush an abandoned box) is
    written straight to the PTY master and never passes through `feed`, so the
    model needs an explicit way to be told "this content is gone now" -- same
    reason every other supervisor injection never marks the box non-empty.
    """

    def test_clear_empties_the_box(self) -> None:
        line = HumanInputLine()
        line.feed(b"leftover text", now=1000.0)
        line.clear()
        assert line.is_empty is True

    def test_clear_resets_the_stability_clock(self) -> None:
        line = HumanInputLine()
        line.feed(b"leftover text", now=1000.0)
        line.clear()
        line.feed(b"x", now=1000.5)
        assert line.is_abandoned(now=1000.5 + 1.0, threshold_seconds=1.0) is True
        # But immediately after clear+refeed, it is fresh, not stale from before.
        assert line.is_abandoned(now=1000.6, threshold_seconds=1.0) is False


class TestHumanInputLineClearByteGaps:
    """Plan 00398 Phase 4: latent clear-byte gaps recorded (unproven) in the
    plan, confirmed here as real defects and fixed on their own merits.

    Ctrl-W and Ctrl-K empty the REAL box (fully or partially) but were in
    neither `_LINE_CLEAR_BYTES` nor `_LINE_BACKSPACE_BYTES`, so they fell to
    the `else` branch and were APPENDED as literal bytes -- the tracked model
    grows non-whitespace content the real box does not have, and can never
    read empty again without an Enter/Ctrl-U/Ctrl-C. An unterminated
    bracketed-paste start has the same shape: every byte after it, INCLUDING
    Enter, is swallowed as paste payload forever.
    """

    def test_ctrl_w_deletes_the_trailing_word_down_to_empty(self) -> None:
        # A single word, fully word-deleted, must read empty again -- today it
        # does not (the byte is appended, not interpreted).
        line = HumanInputLine()
        line.feed(b"oops" + _CTRL_W)
        assert line.is_empty is True

    def test_ctrl_w_deletes_only_the_trailing_word(self) -> None:
        # Real shells word-delete just the last word, not the whole line --
        # modelling it as a full clear would be WRONG in the other direction.
        line = HumanInputLine()
        line.feed(b"two words" + _CTRL_W)
        assert line.is_empty is False

    def test_repeated_ctrl_w_clears_a_multi_word_line(self) -> None:
        line = HumanInputLine()
        line.feed(b"two words" + _CTRL_W + _CTRL_W)
        assert line.is_empty is True

    def test_ctrl_w_on_an_empty_line_is_a_harmless_noop(self) -> None:
        line = HumanInputLine()
        line.feed(_CTRL_W)
        assert line.is_empty is True

    def test_ctrl_k_on_an_empty_line_does_not_wedge_it_non_empty(self) -> None:
        # The core permanent-non-empty bug: today the raw 0x0B byte is
        # appended as "content" even though nothing was typed.
        line = HumanInputLine()
        line.feed(_CTRL_K)
        assert line.is_empty is True

    def test_ctrl_k_does_not_delete_existing_content(self) -> None:
        # No cursor-position tracking exists in this model, so Ctrl-K is
        # modelled as a no-op under the same "cursor at end" assumption
        # backspace already makes -- it must never SILENTLY drop content that
        # is still genuinely in the (real) box.
        line = HumanInputLine()
        line.feed(b"still typing")
        line.feed(_CTRL_K)
        assert line.is_empty is False

    def test_unterminated_bracketed_paste_does_not_swallow_a_later_enter(self) -> None:
        # A missing/dropped paste-end marker must not make every later
        # keystroke -- including the human's own Enter -- unable to ever
        # clear the box again.
        line = HumanInputLine()
        line.feed(b"\x1b[200~" + b"x" * 70_000)  # no ESC[201~ -- latch never ends
        line.feed(_ENTER)
        assert line.is_empty is True


class TestHumanCompactDetection:
    """Detect a human-submitted `/compact` from the forwarded stdin (Plan 00151).

    The supervisor watches the human's submitted line so it can avoid stacking a
    second `/compact` on top of one the human already typed (Claude Code aborts
    the duplicate). Detection is edge-triggered and consumed exactly once.
    """

    def test_plain_compact_submit_is_detected(self) -> None:
        line = HumanInputLine()
        line.feed(b"/compact" + _ENTER)
        assert line.take_compact_submitted() is True

    def test_compact_with_instructions_is_detected(self) -> None:
        line = HumanInputLine()
        line.feed(b"/compact keep the auth work" + _ENTER)
        assert line.take_compact_submitted() is True

    def test_leading_whitespace_still_detected(self) -> None:
        line = HumanInputLine()
        line.feed(b"   /compact" + _ENTER)
        assert line.take_compact_submitted() is True

    def test_newline_submit_is_detected(self) -> None:
        line = HumanInputLine()
        line.feed(b"/compact\n")
        assert line.take_compact_submitted() is True

    def test_take_is_consumed_once(self) -> None:
        line = HumanInputLine()
        line.feed(b"/compact" + _ENTER)
        assert line.take_compact_submitted() is True
        assert line.take_compact_submitted() is False

    def test_non_compact_command_not_detected(self) -> None:
        line = HumanInputLine()
        line.feed(b"/clear" + _ENTER)
        assert line.take_compact_submitted() is False

    def test_plain_text_not_detected(self) -> None:
        line = HumanInputLine()
        line.feed(b"please compact this" + _ENTER)
        assert line.take_compact_submitted() is False

    def test_ctrl_u_kill_is_not_a_submit(self) -> None:
        # Killing the line is NOT submitting it — no compaction was requested.
        line = HumanInputLine()
        line.feed(b"/compact" + _CTRL_U)
        assert line.take_compact_submitted() is False

    def test_ctrl_c_discard_is_not_a_submit(self) -> None:
        line = HumanInputLine()
        line.feed(b"/compact" + _CTRL_C)
        assert line.take_compact_submitted() is False

    def test_unsubmitted_compact_not_detected(self) -> None:
        # Typed but not yet submitted -> not a queued compaction.
        line = HumanInputLine()
        line.feed(b"/compact")
        assert line.take_compact_submitted() is False

    def test_input_activity_exposes_take(self) -> None:
        activity = InputActivity()
        activity.record(b"/compact" + _ENTER)
        assert activity.take_compact_submitted() is True
        assert activity.take_compact_submitted() is False

    def test_typing_after_submit_marks_non_empty_again(self) -> None:
        line = HumanInputLine()
        line.feed(b"first message" + _ENTER + b"second")
        assert line.is_empty is False

    def test_clear_applies_mid_chunk(self) -> None:
        # A submit embedded in the middle of one read() chunk must reset the
        # buffer before the following bytes accumulate.
        line = HumanInputLine()
        line.feed(b"old" + _ENTER + _ENTER)
        assert line.is_empty is True

    def test_feed_accumulates_across_chunks(self) -> None:
        line = HumanInputLine()
        line.feed(b"he")
        line.feed(b"llo")
        assert line.is_empty is False
        line.feed(_ENTER)
        assert line.is_empty is True

    def test_escape_sequences_count_as_content_conservatively(self) -> None:
        # Arrow-up recalls history into the box -- the model cannot know what
        # was recalled, so it must conservatively treat the box as non-empty.
        line = HumanInputLine()
        line.feed(b"\x1b[A")
        assert line.is_empty is False

    def test_unrecognised_control_bytes_count_as_content(self) -> None:
        # A genuinely unrecognised control byte (not one of the specific
        # editing keys this class models) must count as content -- modelling
        # it as a no-op/clear would falsely report empty.
        line = HumanInputLine()
        line.feed(b"two words\x01")  # Ctrl-A: not modelled, so conservative
        assert line.is_empty is False

    def test_utf8_multibyte_input_counts_as_content(self) -> None:
        line = HumanInputLine()
        line.feed("héllo".encode())
        assert line.is_empty is False


class TestHumanInputLineAnsiControlSequences:
    """Terminal control sequences must not poison the empty-box model.

    Regression (v3.34.1): focus events, cursor/device reports and other
    terminal-GENERATED escape sequences were counted as typed content, so a
    single window-focus switch wedged the box 'non-empty' for the whole session
    and the supervisor deferred every injection forever (28 deferrals, 0
    injections in the field). Only genuine box content -- printable keystrokes,
    bracketed-paste payload, up/down history recall -- may mark the box.
    """

    def test_focus_in_event_is_not_content(self) -> None:
        line = HumanInputLine()
        line.feed(b"\x1b[I")
        assert line.is_empty is True

    def test_focus_out_event_is_not_content(self) -> None:
        line = HumanInputLine()
        line.feed(b"\x1b[O")
        assert line.is_empty is True

    def test_repeated_focus_events_never_wedge_the_box(self) -> None:
        line = HumanInputLine()
        for _ in range(30):
            line.feed(b"\x1b[I\x1b[O")
        assert line.is_empty is True

    def test_cursor_position_report_is_not_content(self) -> None:
        line = HumanInputLine()
        line.feed(b"\x1b[6;3R")
        assert line.is_empty is True

    def test_device_attributes_report_is_not_content(self) -> None:
        line = HumanInputLine()
        line.feed(b"\x1b[?1;2c")
        assert line.is_empty is True

    def test_sgr_mouse_event_is_not_content(self) -> None:
        line = HumanInputLine()
        line.feed(b"\x1b[<0;10;10M")
        assert line.is_empty is True

    def test_ss3_function_key_is_not_content(self) -> None:
        line = HumanInputLine()
        line.feed(b"\x1bOP")  # F1 via SS3
        assert line.is_empty is True

    def test_control_sequence_split_across_chunks_is_not_content(self) -> None:
        line = HumanInputLine()
        line.feed(b"\x1b[")
        line.feed(b"I")
        assert line.is_empty is True

    def test_typed_content_after_focus_event_still_counts(self) -> None:
        line = HumanInputLine()
        line.feed(b"\x1b[I")
        line.feed(b"hi")
        assert line.is_empty is False

    def test_focus_event_after_submit_leaves_box_empty(self) -> None:
        # The exact field repro: submit a message, then window-focus churn.
        line = HumanInputLine()
        line.feed(b"done" + _ENTER)
        line.feed(b"\x1b[I\x1b[O\x1b[I")
        assert line.is_empty is True

    def test_bracketed_paste_payload_counts_as_content(self) -> None:
        line = HumanInputLine()
        line.feed(b"\x1b[200~hello world\x1b[201~")
        assert line.is_empty is False

    def test_bracketed_paste_whitespace_only_stays_empty(self) -> None:
        line = HumanInputLine()
        line.feed(b"\x1b[200~   \t \x1b[201~")
        assert line.is_empty is True

    def test_bracketed_paste_end_then_submit_and_focus_stays_empty(self) -> None:
        line = HumanInputLine()
        line.feed(b"\x1b[200~pasted\x1b[201~" + _ENTER)
        line.feed(b"\x1b[I")
        assert line.is_empty is True

    def test_bracketed_paste_split_across_chunks(self) -> None:
        line = HumanInputLine()
        line.feed(b"\x1b[200~payl")
        line.feed(b"oad\x1b[20")
        line.feed(b"1~")
        assert line.is_empty is False

    def test_up_arrow_history_recall_still_counts_as_content(self) -> None:
        # Preserved conservative behaviour: up-arrow may recall a command into
        # an empty box, so it must read non-empty (never inject over recalled text).
        line = HumanInputLine()
        line.feed(b"\x1b[A")
        assert line.is_empty is False

    def test_left_right_arrows_are_not_content(self) -> None:
        # Cursor movement within an (empty) box adds nothing.
        line = HumanInputLine()
        line.feed(b"\x1b[C\x1b[D")
        assert line.is_empty is True


class TestInputActivityFeedsLine:
    """InputActivity.record must feed the line model (human stdin only)."""

    def test_record_feeds_line_tracker(self) -> None:
        activity = InputActivity()
        assert activity.line.is_empty is True
        activity.record(b"typing something")
        assert activity.line.is_empty is False

    def test_record_submit_clears_line(self) -> None:
        activity = InputActivity()
        activity.record(b"typing something" + _ENTER)
        assert activity.line.is_empty is True


def _write_sidecar(directory: Path, *, red: bool, ts: float = 1000.0) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "s.json").write_text(
        json.dumps(
            {
                "red": red,
                # These box-guard tests want an injection PENDING whenever red so
                # the empty/non-empty input box is the sole gate under test. Mark
                # a red sidecar compact_urgent (Plan 00152 elevated band) so it
                # fires promptly regardless of child-output work-idle timing.
                "compact_urgent": red,
                "tier": "red" if red else "green",
                "pct": 90.0,
                "session_id": "s",
                "ts": ts,
                "seq": 1,
                "writer_pid": 1,
            }
        ),
        encoding="utf-8",
    )


def _write_signal(directory: Path, *, ts: float = 1000.0) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "s.compacting").write_text(json.dumps({"ts": ts}), encoding="utf-8")


class TestPollOnceInputBoxGuard:
    """_poll_once must skip EVERY injection path while the box is non-empty."""

    def test_dry_run_compact_deferred_when_box_non_empty(self, tmp_path: Path) -> None:
        _write_sidecar(tmp_path / "sc", red=True)
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
            input_line_empty=False,
        )
        assert ev.decision is Decision.NOOP
        assert written == []

    def test_armed_compact_deferred_when_box_non_empty(self, tmp_path: Path) -> None:
        _write_sidecar(tmp_path / "sc", red=True)
        written: list[bytes] = []
        ev = _mod._poll_once(
            CompactStateMachine(CompactPolicy()),
            sidecar_dir=tmp_path / "sc",
            now_wall=1000.0,
            idle=True,
            dry_run=False,
            master_writer=written.append,
            log=None,
            freshness_seconds=30.0,
            input_line_empty=False,
        )
        assert ev.decision is Decision.NOOP
        assert written == []

    def test_continue_deferred_and_signal_kept_when_box_non_empty(self, tmp_path: Path) -> None:
        sc = tmp_path / "sc"
        _write_signal(sc, ts=1000.0)
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
            input_line_empty=False,
        )
        assert ev.decision is Decision.NOOP
        assert written == []
        # The signal must stay in place so the resume retries on a later tick.
        assert (sc / "s.compacting").exists()

    def test_deferral_is_logged(self, tmp_path: Path) -> None:
        _write_sidecar(tmp_path / "sc", red=True)
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
            input_line_empty=False,
        )
        contents = (tmp_path / "decision.log").read_text(encoding="utf-8")
        assert _DEFERRED in contents
        assert "; injected " not in contents

    def test_no_deferral_log_when_nothing_pending(self, tmp_path: Path) -> None:
        # Green sidecar + non-empty box: no injection was pending, so nothing
        # was deferred, and nothing else is logged either (Plan 00466 N47
        # review 2: the settings-status note is gone along with the settings
        # resolver it reported on).
        _write_sidecar(tmp_path / "sc", red=False)
        log_path = tmp_path / "decision.log"
        _mod._poll_once(
            CompactStateMachine(CompactPolicy()),
            sidecar_dir=tmp_path / "sc",
            now_wall=1000.0,
            idle=True,
            dry_run=True,
            master_writer=lambda _b: None,
            log=DecisionLog(log_path),
            freshness_seconds=30.0,
            input_line_empty=False,
        )
        contents = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
        assert _DEFERRED not in contents
        assert "noop:" not in contents

    def test_compact_fires_on_later_tick_after_box_cleared(self, tmp_path: Path) -> None:
        # The deferred tick must leave NO side effects (no cooldown, no state
        # transition, no injection count) so the SAME machine injects as soon
        # as the box is empty again.
        _write_sidecar(tmp_path / "sc", red=True)
        machine = CompactStateMachine(CompactPolicy())
        written: list[bytes] = []
        first = _mod._poll_once(
            machine,
            sidecar_dir=tmp_path / "sc",
            now_wall=1000.0,
            idle=True,
            dry_run=True,
            master_writer=written.append,
            log=None,
            freshness_seconds=30.0,
            input_line_empty=False,
        )
        assert first.decision is Decision.NOOP
        assert written == []
        second = _mod._poll_once(
            machine,
            sidecar_dir=tmp_path / "sc",
            now_wall=1002.0,
            idle=True,
            dry_run=True,
            master_writer=written.append,
            log=None,
            freshness_seconds=30.0,
            input_line_empty=True,
        )
        assert second.decision is Decision.WOULD_COMPACT
        expected = _mod._resolve_payload(Decision.WOULD_COMPACT, dry_run=True, now_wall=1002.0)
        framed = _mod._PASTE_START + expected + _mod._PASTE_END
        assert b"".join(written) == (framed + "\r").encode("utf-8")

    def test_continue_fires_on_later_tick_after_box_cleared(self, tmp_path: Path) -> None:
        sc = tmp_path / "sc"
        _write_signal(sc, ts=1000.0)
        machine = CompactStateMachine(CompactPolicy())
        written: list[bytes] = []
        first = _mod._poll_once(
            machine,
            sidecar_dir=sc,
            now_wall=1000.0,
            idle=True,
            dry_run=True,
            master_writer=written.append,
            log=None,
            freshness_seconds=30.0,
            compaction_signal_ttl_seconds=120.0,
            input_line_empty=False,
        )
        assert first.decision is Decision.NOOP
        assert written == []
        second = _mod._poll_once(
            machine,
            sidecar_dir=sc,
            now_wall=1002.0,
            idle=True,
            dry_run=True,
            master_writer=written.append,
            log=None,
            freshness_seconds=30.0,
            compaction_signal_ttl_seconds=120.0,
            input_line_empty=True,
        )
        assert second.decision is Decision.WOULD_CONTINUE
        expected = _mod._resolve_payload(Decision.WOULD_CONTINUE, dry_run=True, now_wall=1002.0)
        framed = _mod._PASTE_START + expected + _mod._PASTE_END
        assert b"".join(written) == (framed + "\r").encode("utf-8")
        assert not (sc / "s.compacting").exists()

    def test_empty_box_default_still_injects(self, tmp_path: Path) -> None:
        # Existing behaviour is unchanged when the box is empty.
        _write_sidecar(tmp_path / "sc", red=True)
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
            input_line_empty=True,
        )
        assert ev.decision is Decision.WOULD_COMPACT
        assert written != []

    def test_backspaced_to_empty_box_allows_injection(self, tmp_path: Path) -> None:
        _write_sidecar(tmp_path / "sc", red=True)
        line = HumanInputLine()
        line.feed(b"oops" + _DEL + _DEL + _DEL + _DEL)
        ev = _mod._poll_once(
            CompactStateMachine(CompactPolicy()),
            sidecar_dir=tmp_path / "sc",
            now_wall=1000.0,
            idle=True,
            dry_run=True,
            master_writer=lambda _b: None,
            log=None,
            freshness_seconds=30.0,
            input_line_empty=line.is_empty,
        )
        assert ev.decision is Decision.WOULD_COMPACT


class TestInjectedBytesDoNotCountAsHumanInput:
    """Supervisor-injected keystrokes must never mark the box non-empty."""

    def test_injection_via_master_does_not_touch_line_model(self) -> None:
        # _forward_io feeds InputActivity from STDIN only; on_poll injections
        # write to the master fd directly and bypass the model.
        stdin_read_fd, stdin_write_fd = os.pipe()
        master_read_fd, master_write_fd = os.pipe()
        activity = InputActivity()
        state = {"polled": False}

        def _on_poll() -> None:
            if not state["polled"]:
                state["polled"] = True
                _mod._perform_injection(
                    lambda data: os.write(master_write_fd, data) and None,
                    "injected text",
                    sleep=lambda _s: None,
                )
            else:
                os.close(master_write_fd)  # EOF ends _forward_io

        os.close(stdin_write_fd)  # immediate stdin EOF -> poll timeouts fire
        try:
            _mod._forward_io(
                stdin_read_fd,
                master_read_fd,
                activity,
                poll_seconds=0.01,
                on_poll=_on_poll,
            )
        finally:
            os.close(stdin_read_fd)
            os.close(master_read_fd)

        assert state["polled"] is True
        assert activity.line.is_empty is True

    def test_human_stdin_bytes_do_mark_line_non_empty(self) -> None:
        # A real PTY pair is needed here: _forward_io WRITES the forwarded
        # stdin bytes to the master fd, which a plain pipe read-end rejects.
        stdin_read_fd, stdin_write_fd = os.pipe()
        master_fd, slave_fd = os.openpty()
        activity = InputActivity()
        state = {"slave_open": True}
        os.write(stdin_write_fd, b"human typing")
        os.close(stdin_write_fd)

        def _on_poll() -> None:
            if state["slave_open"]:
                state["slave_open"] = False
                os.close(slave_fd)  # master read now errors/EOFs -> loop ends

        try:
            _mod._forward_io(
                stdin_read_fd,
                master_fd,
                activity,
                poll_seconds=0.01,
                on_poll=_on_poll,
            )
        finally:
            os.close(stdin_read_fd)
            os.close(master_fd)
            if state["slave_open"]:
                os.close(slave_fd)

        assert activity.line.is_empty is False


class TestSuperviseWiresInputBoxGuard:
    """End-to-end: supervise() must gate real injections on the tracked line."""

    def _run(self, tmp_path: Path, stdin_payload: bytes, monkeypatch: pytest.MonkeyPatch) -> str:
        sidecar_dir = tmp_path / "sc"
        # Plan 00166: the real supervise() loop scopes to its own container's
        # session ids; pin the resolver to the test sidecar's session ("s") so
        # this input-box-guard test is deterministic and env-independent.
        monkeypatch.setattr(_mod, "cached_own_session_ids", lambda *a, **k: frozenset({"s"}))
        _write_sidecar(sidecar_dir, red=True, ts=time.time())
        log = DecisionLog(tmp_path / "decision.log")
        read_fd, write_fd = os.pipe()
        os.write(write_fd, stdin_payload)
        os.close(write_fd)
        try:
            code = _mod.supervise(
                ["bash", "-lc", "sleep 0.3; exit 0"],
                dry_run=True,
                log=log,
                activity=InputActivity(),
                stdin_fd=read_fd,
                sidecar_dir=sidecar_dir,
                poll_seconds=0.02,
                idle_floor_seconds=0.0,
            )
        finally:
            os.close(read_fd)
        assert code == 0
        return (tmp_path / "decision.log").read_text(encoding="utf-8")

    def test_partially_typed_message_defers_injection(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        contents = self._run(tmp_path, b"half typed human message", monkeypatch)
        assert _DEFERRED in contents
        assert "; injected " not in contents

    def test_submitted_message_leaves_box_empty_and_injection_fires(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        contents = self._run(tmp_path, b"finished human message\r", monkeypatch)
        assert "; injected " in contents
