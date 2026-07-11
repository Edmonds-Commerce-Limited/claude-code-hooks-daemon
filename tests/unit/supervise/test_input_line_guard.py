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
        # Ctrl-W (word kill) removes only PART of the line; modelling it as a
        # clear would falsely report empty. It must count as content instead.
        line = HumanInputLine()
        line.feed(b"two words\x17")
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
        # was deferred -- the log must not accumulate noise on every tick.
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
        # Nothing at all was logged: the file was never even created.
        assert not log_path.exists()

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
        assert b"".join(written) == (_mod._DRY_RUN_COMPACT_MARKER + "\r").encode("utf-8")

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
        assert b"".join(written) == (_mod._CONTINUE_PAYLOAD + "\r").encode("utf-8")
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

    def _run(self, tmp_path: Path, stdin_payload: bytes) -> str:
        sidecar_dir = tmp_path / "sc"
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

    def test_partially_typed_message_defers_injection(self, tmp_path: Path) -> None:
        contents = self._run(tmp_path, b"half typed human message")
        assert _DEFERRED in contents
        assert "; injected " not in contents

    def test_submitted_message_leaves_box_empty_and_injection_fires(self, tmp_path: Path) -> None:
        contents = self._run(tmp_path, b"finished human message\r")
        assert "; injected " in contents
