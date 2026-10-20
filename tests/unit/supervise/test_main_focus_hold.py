"""Plan 00537 (issue #125) -- hold every send while main-thread focus is unconfirmed.

The supervisor cannot see which Claude Code thread has focus. A bare Up/Down
can move focus into the sub-agent panel, and Enter on a selected row opens
that sub-agent's transcript, so the only evidence available is the human's
own keystrokes. `MainFocusModel` reads them (in parallel with
`HumanInputLine`, never changing it), latches on navigation that could have
left the prompt, and clears only on a bare Esc. While latched NOTHING is
typed: every `_perform_injection` call site defers, the defer is logged
(rate-limited) and a status-line banner tells the human to press Esc.
"""

from __future__ import annotations

import ast
import json
from typing import TYPE_CHECKING, Any

import pytest

from tests.unit.supervise._load import SCRIPT_PATH, load_supervisor_module

if TYPE_CHECKING:
    from pathlib import Path

_mod = load_supervisor_module()
Decision = _mod.Decision
CompactPolicy = _mod.CompactPolicy
CompactStateMachine = _mod.CompactStateMachine
FocusHold = _mod.FocusHold
MainFocusModel = _mod.MainFocusModel
TickFacts = _mod.TickFacts

_UP = b"\x1b[A"
_DOWN = b"\x1b[B"
_ESC = b"\x1b"
_ENTER = b"\r"
_CTRL_C = b"\x03"
_CTRL_U = b"\x15"
_NOW = 10_000.0
_SESSION = "s"
_SETTLE = _mod._FOCUS_ESC_SETTLE_SECONDS


def _hold(*, since: float = _NOW, reason: str = "bare Up arrow") -> Any:
    return FocusHold(reason=reason, since=since, latch_bytes="\\x1b[A")


def _facts(
    *,
    now: float = _NOW,
    confirmed: bool = True,
    since: float = _NOW,
    idle: bool = True,
    input_line_empty: bool = True,
    input_line_abandoned: bool = False,
) -> Any:
    return TickFacts(
        now_wall=now,
        idle=idle,
        input_line_empty=input_line_empty,
        human_compact_submitted=False,
        work_idle=True,
        input_line_abandoned=input_line_abandoned,
        main_focus_confirmed=confirmed,
        focus_hold_reason="" if confirmed else "bare Up arrow",
        focus_held_since=0.0 if confirmed else since,
        focus_latch_bytes="" if confirmed else "\\x1b[A",
    )


def _write_red_sidecar(directory: Path, *, ts: float = _NOW) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{_SESSION}.json").write_text(
        json.dumps(
            {
                "red": True,
                "critical": True,
                "compact_urgent": True,
                "tier": "critical",
                "pct": 95.0,
                "session_id": _SESSION,
                "ts": ts,
                "seq": 1,
                "writer_pid": 1,
            }
        ),
        encoding="utf-8",
    )


def _decide(sidecar_dir: Path, machine: Any, facts: Any, *, dry_run: bool = False) -> Any:
    return _mod.decide_once(
        machine,
        sidecar_dir=sidecar_dir,
        facts=facts,
        dry_run=dry_run,
        freshness_seconds=30.0,
    )


@pytest.fixture
def sidecar_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "untracked" / "context-sidecar"
    directory.mkdir(parents=True)
    return directory


# ── Task 1.1: the focus model, from stdin byte fixtures ─────────────────────


class TestMainFocusModel:
    """Latches on navigation that could leave the prompt; clears on a bare Esc only."""

    def test_no_navigation_holds_nothing(self) -> None:
        model = MainFocusModel()
        model.feed(b"hello world", now=_NOW)
        model.feed(_ENTER, now=_NOW)
        model.feed(b"\x1b[I\x1b[O\x1b[C\x1b[D", now=_NOW)  # focus events, Left/Right
        assert model.confirmed is True
        assert model.hold is None

    def test_up_then_esc_holds_then_releases(self) -> None:
        model = MainFocusModel()
        model.feed(_UP, now=_NOW)
        assert model.confirmed is False
        assert model.hold is not None
        assert model.hold.since == _NOW
        assert "\\x1b[A" in model.hold.latch_bytes
        model.feed(_ESC, now=_NOW + 1)
        # The Esc ended its read: unresolved until the settle window passes.
        assert model.confirmed is False
        model.settle(now=_NOW + 1 + _SETTLE)
        assert model.confirmed is True
        assert model.hold is None

    def test_down_latches_too(self) -> None:
        model = MainFocusModel()
        model.feed(_DOWN, now=_NOW)
        assert model.confirmed is False

    def test_application_cursor_up_latches(self) -> None:
        # SS3 arrows (ESC O A) are the same key in application-cursor mode;
        # unsure means hold.
        model = MainFocusModel()
        model.feed(b"\x1bOA", now=_NOW)
        assert model.confirmed is False

    def test_up_with_params_does_not_latch(self) -> None:
        model = MainFocusModel()
        model.feed(b"\x1b[1;2A", now=_NOW)
        assert model.confirmed is True

    def test_up_enter_text_enter_holds_throughout(self) -> None:
        model = MainFocusModel()
        model.feed(_UP, now=_NOW)
        model.feed(_ENTER, now=_NOW + 1)
        assert model.confirmed is False
        model.feed(b"text for the sub-agent", now=_NOW + 2)
        assert model.confirmed is False
        model.feed(_ENTER, now=_NOW + 3)
        assert model.confirmed is False
        assert model.hold is not None
        # The hold is dated from the navigation, not the later Enter.
        assert model.hold.since == _NOW
        assert "Enter" in model.hold.reason

    def test_up_with_no_esc_stays_held(self) -> None:
        model = MainFocusModel()
        model.feed(_UP, now=_NOW)
        for offset in range(1, 50):
            model.feed(b"x", now=_NOW + offset)
        assert model.confirmed is False

    @pytest.mark.parametrize("key", [_CTRL_C, _CTRL_U, _ENTER])
    def test_clear_keys_do_not_release(self, key: bytes) -> None:
        model = MainFocusModel()
        model.feed(_UP, now=_NOW)
        model.feed(key, now=_NOW + 1)
        assert model.confirmed is False

    def test_esc_in_same_chunk_after_up_releases(self) -> None:
        model = MainFocusModel()
        model.feed(_UP + _ESC, now=_NOW)
        model.settle(now=_NOW + _SETTLE)
        assert model.confirmed is True

    def test_double_esc_releases(self) -> None:
        model = MainFocusModel()
        model.feed(_UP, now=_NOW)
        model.feed(_ESC + _ESC, now=_NOW + 1)
        assert model.confirmed is True

    def test_esc_followed_by_printable_releases(self) -> None:
        model = MainFocusModel()
        model.feed(_UP, now=_NOW)
        model.feed(_ESC + b"x", now=_NOW + 1)
        assert model.confirmed is True

    def test_trailing_esc_that_continues_an_arrow_keeps_the_hold(self) -> None:
        model = MainFocusModel()
        model.feed(_UP, now=_NOW)
        model.feed(_ESC, now=_NOW + 1)
        model.feed(b"[A", now=_NOW + 1)
        model.settle(now=_NOW + 10)
        assert model.confirmed is False
        assert model.hold is not None
        assert model.hold.since == _NOW

    def test_focus_and_paste_sequences_do_not_release(self) -> None:
        model = MainFocusModel()
        model.feed(_UP, now=_NOW)
        model.feed(b"\x1b[I\x1b[O", now=_NOW + 1)
        model.feed(b"\x1b[200~pasted \x1b text\x1b[201~", now=_NOW + 2)
        assert model.confirmed is False

    def test_arrows_inside_a_paste_do_not_latch(self) -> None:
        model = MainFocusModel()
        model.feed(b"\x1b[200~a\x1b[Ab\x1b[201~", now=_NOW)
        assert model.confirmed is True

    def test_human_input_line_unchanged_by_arrows(self) -> None:
        # The ruling forbids changing `_finish_csi`: an Up still counts as box
        # content in `HumanInputLine`.
        line = _mod.HumanInputLine()
        line.feed(_UP, now=_NOW)
        assert line.is_empty is False

    def test_input_activity_feeds_the_focus_model(self) -> None:
        activity = _mod.InputActivity()
        activity.record(_UP, now=_NOW)
        assert activity.focus.confirmed is False
        activity.record(_ESC, now=_NOW + 1)
        activity.focus.settle(now=_NOW + 1 + _SETTLE)
        assert activity.focus.confirmed is True


def _after_reads(chunks: list[bytes], *, settle: bool = True) -> Any:
    """Feed each chunk as one read() 50 ms apart, then let a pending Esc settle."""
    model = MainFocusModel()
    for index, chunk in enumerate(chunks):
        model.feed(chunk, now=_NOW + index * 0.05)
    if settle:
        model.settle(now=_NOW + len(chunks) + _SETTLE)
    return model


class TestFocusModelAcrossReads:
    """Review C1/I2: an Esc that ends one read must not reinterpret the next one."""

    @pytest.mark.parametrize(
        ("chunks", "confirmed"),
        [
            pytest.param([_ESC, b"P", b"lease fix", _ENTER, _UP], False, id="A-esc-Please-up"),
            pytest.param([_ESC, b"]", _UP], False, id="B-esc-bracket-up"),
            pytest.param([_UP, _ESC, b"O", b"K"], True, id="C-up-esc-OK"),
            pytest.param([_UP, _ESC, b"[", b"x"], True, id="D-up-esc-[x"),
            pytest.param([_UP, _ESC, b"P", b"lease"], True, id="E-up-esc-Please"),
            pytest.param([_UP, _ESC], True, id="F-up-esc"),
            pytest.param([_ESC, b"Please fix"], True, id="esc-then-text-one-read"),
            pytest.param([_UP, _ESC, b"OK"], True, id="up-esc-OK-one-read"),
            pytest.param([_ESC, b"_", _UP], False, id="esc-underscore-up"),
            pytest.param([_ESC, b"^X", _UP], False, id="esc-caret-up"),
        ],
    )
    def test_probe_cases(self, chunks: list[bytes], confirmed: bool) -> None:
        assert _after_reads(chunks).confirmed is confirmed

    @pytest.mark.parametrize(
        "chunks",
        [
            pytest.param([_ESC, b"[A"], id="esc|[A"),
            pytest.param([_ESC, b"[", b"A"], id="esc|[|A"),
            pytest.param([b"\x1b[", b"A"], id="esc[|A"),
            pytest.param([_ESC, b"OA"], id="esc|OA"),
            pytest.param([_ESC, b"O", b"B"], id="esc|O|B"),
            pytest.param([_ESC, b"[B"], id="esc|[B"),
        ],
    )
    def test_arrow_split_across_reads_latches(self, chunks: list[bytes]) -> None:
        assert _after_reads(chunks).confirmed is False

    def test_split_arrow_with_params_neither_latches_nor_releases(self) -> None:
        assert _after_reads([_ESC, b"[1;2A"]).confirmed is True
        assert _after_reads([_UP, _ESC, b"[1;2A"]).confirmed is False

    def test_pending_esc_keeps_the_hold_until_it_resolves(self) -> None:
        model = MainFocusModel()
        model.feed(_UP, now=_NOW)
        model.feed(_ESC, now=_NOW + 1)
        model.settle(now=_NOW + 1 + _SETTLE / 10)
        assert model.confirmed is False
        model.settle(now=_NOW + 1 + _SETTLE)
        assert model.confirmed is True

    def test_prefix_read_keeps_the_hold_while_pending(self) -> None:
        model = MainFocusModel()
        model.feed(_UP, now=_NOW)
        model.feed(_ESC, now=_NOW + 1)
        model.feed(b"[", now=_NOW + 1.01)
        assert model.confirmed is False
        model.feed(b"x", now=_NOW + 1.02)
        assert model.confirmed is True

    def test_letters_after_a_settled_esc_are_text(self) -> None:
        # Past the settle window the Esc was bare, whatever arrives next.
        model = MainFocusModel()
        model.feed(_UP, now=_NOW)
        model.feed(_ESC, now=_NOW + 1)
        model.feed(b"[A", now=_NOW + 1 + 2 * _SETTLE)
        assert model.confirmed is True

    def test_open_string_sequence_does_not_outlive_its_read(self) -> None:
        assert _after_reads([b"\x1b]11;rgb", _UP]).confirmed is False

    def test_complete_terminal_reply_in_one_read_does_not_release(self) -> None:
        assert _after_reads([_UP, b"\x1b]11;rgb:0/0/0\x1b\\"]).confirmed is False

    def test_unterminated_paste_is_bounded(self) -> None:
        model = MainFocusModel()
        model.feed(b"\x1b[200~" + b"x" * (_mod._PASTE_LATCH_MAX_BYTES + 1), now=_NOW)
        model.feed(_UP, now=_NOW + 1)
        assert model.confirmed is False

    def test_paste_end_marker_split_across_reads(self) -> None:
        model = MainFocusModel()
        model.feed(b"\x1b[200~text\x1b", now=_NOW)
        model.feed(b"[201~", now=_NOW + 0.01)
        model.feed(_UP, now=_NOW + 0.02)
        assert model.confirmed is False


# ── Task 1.2: the TickFacts field, ANDed into can_inject ────────────────────


class TestTickFactsField:
    def test_defaults_to_confirmed(self) -> None:
        facts = TickFacts(
            now_wall=_NOW,
            idle=True,
            input_line_empty=True,
            human_compact_submitted=False,
            work_idle=True,
        )
        assert facts.main_focus_confirmed is True

    def test_round_trips_through_the_worker_json(self) -> None:
        facts = _facts(confirmed=False, since=_NOW - 5)
        back = _mod._facts_from_json(_mod._facts_to_json(facts))
        assert back.main_focus_confirmed is False
        assert back.focus_hold_reason == "bare Up arrow"
        assert back.focus_held_since == _NOW - 5
        assert back.focus_latch_bytes == "\\x1b[A"

    def test_absent_key_from_a_host_without_the_model_is_confirmed(self) -> None:
        data = json.loads(_mod._facts_to_json(_facts()))
        for key in (
            "main_focus_confirmed",
            "focus_hold_reason",
            "focus_held_since",
            "focus_latch_bytes",
        ):
            del data[key]
        assert _mod._facts_from_json(json.dumps(data)).main_focus_confirmed is True


class TestCanInjectAndsFocus:
    def test_red_and_idle_compacts_when_confirmed(self, sidecar_dir: Path) -> None:
        _write_red_sidecar(sidecar_dir)
        outcome = _decide(sidecar_dir, CompactStateMachine(CompactPolicy()), _facts())
        assert outcome.decision_value == Decision.WOULD_COMPACT.value

    def test_red_and_idle_holds_when_latched(self, sidecar_dir: Path) -> None:
        _write_red_sidecar(sidecar_dir)
        machine = CompactStateMachine(CompactPolicy())
        outcome = _decide(sidecar_dir, machine, _facts(confirmed=False))
        assert outcome.payload is None
        assert outcome.deferred_log is not None
        assert outcome.deferred_log.startswith(_mod._FOCUS_HOLD_LOG_PREFIX)
        assert "bare Up arrow" in outcome.deferred_log
        # Held means deferred: the machine did not advance.
        assert machine.state is _mod.SupervisorState.MONITOR

    def test_escape_and_resubmit_hold_in_await(self, sidecar_dir: Path) -> None:
        _write_red_sidecar(sidecar_dir)
        machine = CompactStateMachine(CompactPolicy())
        first = _decide(sidecar_dir, machine, _facts())
        assert first.decision_value == Decision.WOULD_COMPACT.value
        later = _NOW + _mod._DEFAULT_ESCAPE_AFTER_SECONDS + 1
        _write_red_sidecar(sidecar_dir, ts=later)
        held = _decide(sidecar_dir, machine, _facts(now=later, confirmed=False))
        assert held.payload is None
        released = _decide(sidecar_dir, machine, _facts(now=later + 1))
        assert released.decision_value in (
            Decision.WOULD_ESCAPE.value,
            Decision.WOULD_RESUBMIT.value,
        )

    def test_dry_run_marker_held_and_not_spent(self, sidecar_dir: Path) -> None:
        _write_red_sidecar(sidecar_dir)
        machine = CompactStateMachine(CompactPolicy())
        held = _decide(sidecar_dir, machine, _facts(confirmed=False), dry_run=True)
        assert held.payload is None
        assert machine.dry_run_fired is False
        released = _decide(sidecar_dir, machine, _facts(now=_NOW + 1), dry_run=True)
        assert released.payload is not None


# ── Task 1.3: every family that bypasses can_inject ─────────────────────────


class TestBypassFamiliesHold:
    def test_model_switch_holds_and_keeps_its_signal(self, sidecar_dir: Path) -> None:
        _mod.write_model_switch_signal(sidecar_dir, session_id=_SESSION, family="opus", now=_NOW)
        machine = CompactStateMachine(CompactPolicy())
        held = _decide(sidecar_dir, machine, _facts(confirmed=False))
        assert held.payload is None
        assert held.consume_signal_path is None
        assert held.deferred_log is not None
        assert "model switch" in held.deferred_log
        released = _decide(sidecar_dir, machine, _facts(now=_NOW + 1))
        assert released.decision_value == Decision.WOULD_MODEL.value

    def test_abandoned_flush_holds_without_spending_its_one_shot(self, sidecar_dir: Path) -> None:
        _write_red_sidecar(sidecar_dir)
        machine = CompactStateMachine(CompactPolicy())
        held = _decide(
            sidecar_dir,
            machine,
            _facts(confirmed=False, input_line_empty=False, input_line_abandoned=True),
        )
        assert held.payload is None
        assert held.abandoned_box_flushed is False
        assert held.deferred_log is not None
        assert held.deferred_log.startswith(_mod._FOCUS_HOLD_LOG_PREFIX)
        released = _decide(
            sidecar_dir,
            machine,
            _facts(now=_NOW + 1, input_line_empty=False, input_line_abandoned=True),
        )
        assert released.abandoned_box_flushed is True
        assert released.payload == "\r"

    def test_usage_pause_compact_holds(self, sidecar_dir: Path) -> None:
        from claude_code_hooks_daemon.utils import usage_pause
        from claude_code_hooks_daemon.utils.usage_pause import UsagePause

        usage_pause.write_usage_pause(
            sidecar_dir.parent,
            UsagePause(
                session_id=_SESSION,
                paused_at=_NOW - 60.0,
                resume_at=_NOW + 3600.0,
                window=usage_pause.WINDOW_FIVE_HOUR,
                used_percentage=93.0,
                ceiling=90.0,
                reason="five_hour window at 93% (ceiling 90%)",
            ),
        )
        machine = CompactStateMachine(CompactPolicy())
        held = _decide(sidecar_dir, machine, _facts(confirmed=False))
        assert held.payload is None
        assert held.deferred_log is not None
        assert "usage-pause" in held.deferred_log
        assert machine.pause_compacted_for is None
        released = _decide(sidecar_dir, machine, _facts(now=_NOW + 1))
        assert released.decision_value == Decision.WOULD_COMPACT.value


class _Writer:
    def __init__(self) -> None:
        self.chunks: list[bytes] = []

    def __call__(self, data: bytes) -> None:
        self.chunks.append(data)


def _coordinator(tmp_path: Path) -> Any:
    return _mod.RestartCoordinator(
        state_path=tmp_path / "state" / "restart-request.json",
        wait_seconds=30.0,
        monotonic=lambda: 100.0,
        wall_clock=lambda: _NOW,
        sleep=lambda _: None,
    )


class TestRestartExitHolds:
    def _request(self, coordinator: Any, writer: _Writer, machine: Any, hold: Any) -> bool:
        return bool(
            coordinator.request(
                "max-age",
                "session is 3 days old",
                session_ids=frozenset({_SESSION}),
                machine=machine,
                write_master=writer,
                log=None,
                dry_run=False,
                focus_hold=hold,
            )
        )

    def test_held_exit_types_nothing_and_leaves_no_state(self, tmp_path: Path) -> None:
        coordinator = _coordinator(tmp_path)
        writer = _Writer()
        machine = CompactStateMachine(CompactPolicy())
        assert self._request(coordinator, writer, machine, _hold()) is False
        assert writer.chunks == []
        assert coordinator.pending is False
        assert machine.own_line_pending is False
        # No abandon count and no cooldown: released, the same request goes
        # through at once.
        assert coordinator.abandon(None) is None
        assert self._request(coordinator, writer, machine, None) is True
        assert b"/exit" in b"".join(writer.chunks)


class TestApplyDecisionBelt:
    def test_payload_decided_before_a_latch_is_not_typed(self) -> None:
        outcome = _mod.TickOutcome(
            decision_value=Decision.WOULD_COMPACT.value,
            reason="red",
            payload="/compact",
            submit=True,
            consume_signal_path=None,
            deferred_log=None,
        )
        writer = _Writer()
        injected = _mod._apply_decision(
            outcome, master_writer=writer, log=None, main_focus_confirmed=False
        )
        assert injected is False
        assert writer.chunks == []


def _write_pause(sidecar_dir: Path) -> None:
    from claude_code_hooks_daemon.utils import usage_pause
    from claude_code_hooks_daemon.utils.usage_pause import UsagePause

    usage_pause.write_usage_pause(
        sidecar_dir.parent,
        UsagePause(
            session_id=_SESSION,
            paused_at=_NOW - 60.0,
            resume_at=_NOW + 3600.0,
            window=usage_pause.WINDOW_FIVE_HOUR,
            used_percentage=93.0,
            ceiling=90.0,
            reason="five_hour window at 93% (ceiling 90%)",
        ),
    )


class TestWorkerOutcomeHeldAtApply:
    """Review I1: a payload the host refuses at apply time is not booked as sent.

    The worker decided with focus confirmed; the host's model latched before
    apply. Like a failed PTY write, the host keeps its own pre-tick state.
    """

    def _apply(self, outcome: Any, machine: Any, line: Any, *, confirmed: bool) -> bool:
        return bool(
            _mod._apply_worker_outcome(
                outcome,
                machine=machine,
                line=line,
                master_writer=_Writer(),
                log=None,
                main_focus_confirmed=confirmed,
                now_wall=_NOW,
            )
        )

    def _decided(self, sidecar_dir: Path, facts: Any, *, dry_run: bool = False) -> Any:
        return _decide(sidecar_dir, CompactStateMachine(CompactPolicy()), facts, dry_run=dry_run)

    def test_held_compact_leaves_the_host_in_monitor(self, sidecar_dir: Path) -> None:
        _write_red_sidecar(sidecar_dir)
        outcome = self._decided(sidecar_dir, _facts())
        assert outcome.decision_value == Decision.WOULD_COMPACT.value
        host = CompactStateMachine(CompactPolicy())
        assert self._apply(outcome, host, _mod.HumanInputLine(), confirmed=False) is False
        assert host.state is _mod.SupervisorState.MONITOR

    def test_confirmed_compact_is_adopted(self, sidecar_dir: Path) -> None:
        _write_red_sidecar(sidecar_dir)
        outcome = self._decided(sidecar_dir, _facts())
        host = CompactStateMachine(CompactPolicy())
        assert self._apply(outcome, host, _mod.HumanInputLine(), confirmed=True) is True
        assert host.state is _mod.SupervisorState.AWAIT_COMPACTING

    def test_held_usage_pause_compact_is_not_latched(self, sidecar_dir: Path) -> None:
        _write_pause(sidecar_dir)
        outcome = self._decided(sidecar_dir, _facts())
        assert outcome.decision_value == Decision.WOULD_COMPACT.value
        host = CompactStateMachine(CompactPolicy())
        self._apply(outcome, host, _mod.HumanInputLine(), confirmed=False)
        assert host.pause_compacted_for is None

    def test_held_dry_run_marker_keeps_its_fuse(self, sidecar_dir: Path) -> None:
        _write_red_sidecar(sidecar_dir)
        outcome = self._decided(sidecar_dir, _facts(), dry_run=True)
        assert outcome.payload is not None
        host = CompactStateMachine(CompactPolicy())
        self._apply(outcome, host, _mod.HumanInputLine(), confirmed=False)
        assert host.dry_run_fired is False

    def test_held_abandoned_flush_keeps_the_box_text(self, sidecar_dir: Path) -> None:
        _write_red_sidecar(sidecar_dir)
        outcome = self._decided(
            sidecar_dir, _facts(input_line_empty=False, input_line_abandoned=True)
        )
        assert outcome.abandoned_box_flushed is True
        line = _mod.HumanInputLine()
        line.feed(b"half-typed", now=_NOW)
        self._apply(outcome, CompactStateMachine(CompactPolicy()), line, confirmed=False)
        assert line.is_empty is False

    def test_confirmed_abandoned_flush_clears_the_box_model(self, sidecar_dir: Path) -> None:
        _write_red_sidecar(sidecar_dir)
        outcome = self._decided(
            sidecar_dir, _facts(input_line_empty=False, input_line_abandoned=True)
        )
        line = _mod.HumanInputLine()
        line.feed(b"half-typed", now=_NOW)
        self._apply(outcome, CompactStateMachine(CompactPolicy()), line, confirmed=True)
        assert line.is_empty is True

    def test_held_own_line_is_not_recorded(self, sidecar_dir: Path) -> None:
        _write_red_sidecar(sidecar_dir)
        outcome = self._decided(sidecar_dir, _facts())
        host = CompactStateMachine(CompactPolicy())
        self._apply(outcome, host, _mod.HumanInputLine(), confirmed=False)
        assert host.own_line_pending is False


def _perform_injection_call_sites() -> set[str]:
    """Qualified names of every function that calls `_perform_injection(`."""
    tree = ast.parse(SCRIPT_PATH.read_text(encoding="utf-8"))
    sites: set[str] = set()

    def visit(node: ast.AST, scope: tuple[str, ...]) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.ClassDef)):
                visit(child, (*scope, child.name))
                continue
            if (
                isinstance(child, ast.Call)
                and isinstance(child.func, ast.Name)
                and child.func.id == "_perform_injection"
            ):
                sites.add(".".join(scope))
            visit(child, scope)

    visit(tree, ())
    return sites


def test_every_perform_injection_call_site_is_gated() -> None:
    """A new call site fails here until it is gated and listed.

    Each listed site has a behavioural test above proving it defers while
    latched: `_apply_decision` (TestApplyDecisionBelt, and every decide_once
    family) and `RestartCoordinator.request` (TestRestartExitHolds).
    """
    assert _perform_injection_call_sites() == {"_apply_decision", "RestartCoordinator.request"}


# ── Task 1.4: rate-limited log, banner, escalation option ───────────────────


class TestFocusHoldVisibility:
    def test_log_is_rate_limited_per_family(self) -> None:
        machine = CompactStateMachine(CompactPolicy())
        hold = _hold()
        assert machine.focus_hold_log("goal", hold, now_wall=_NOW) is not None
        assert machine.focus_hold_log("goal", hold, now_wall=_NOW + 30) is None
        assert machine.focus_hold_log("model switch", hold, now_wall=_NOW + 30) is not None
        assert machine.focus_hold_log("goal", hold, now_wall=_NOW + 61) is not None

    def test_rate_limit_survives_the_worker_state_round_trip(self) -> None:
        host = CompactStateMachine(CompactPolicy())
        assert host.focus_hold_log("goal", _hold(), now_wall=_NOW) is not None
        worker = CompactStateMachine(CompactPolicy())
        worker.import_state(host.export_state())
        assert worker.focus_hold_log("goal", _hold(), now_wall=_NOW + 10) is None

    def test_escalation_logs_inside_the_minute_and_names_bytes(self) -> None:
        machine = CompactStateMachine(CompactPolicy())
        hold = _hold(since=_NOW)
        assert machine.focus_hold_log("goal", hold, now_wall=_NOW + 290) is not None
        first_bound = machine.focus_hold_log("goal", hold, now_wall=_NOW + 301)
        assert first_bound is not None
        assert "held 5 min" in first_bound
        assert "\\x1b[A" not in first_bound
        second_bound = machine.focus_hold_log("goal", hold, now_wall=_NOW + 901)
        assert second_bound is not None
        assert "held 15 min" in second_bound
        assert "\\x1b[A" in second_bound

    def test_held_tick_posts_the_warning_banner(self, sidecar_dir: Path) -> None:
        _write_red_sidecar(sidecar_dir)
        _decide(sidecar_dir, CompactStateMachine(CompactPolicy()), _facts(confirmed=False))
        message = json.loads(
            _mod._status_message_path(sidecar_dir.parent).read_text(encoding="utf-8")
        )
        assert message["level"] == _mod._STATUS_LEVEL_WARNING
        assert message["text"] == (
            "supervisor holding: focus may be on a sub-agent; press Esc to return to the main"
            " thread"
        )

    def test_banner_is_louder_past_the_first_bound(self, sidecar_dir: Path) -> None:
        _write_red_sidecar(sidecar_dir, ts=_NOW + 400)
        _decide(
            sidecar_dir,
            CompactStateMachine(CompactPolicy()),
            _facts(now=_NOW + 400, confirmed=False, since=_NOW),
        )
        message = json.loads(
            _mod._status_message_path(sidecar_dir.parent).read_text(encoding="utf-8")
        )
        assert message["text"].startswith("SUPERVISOR HOLDING 6 MIN")
        assert "press Esc" in message["text"]

    def test_escalation_never_resumes_typing(self, sidecar_dir: Path) -> None:
        late = _NOW + 100_000
        _write_red_sidecar(sidecar_dir, ts=late)
        outcome = _decide(
            sidecar_dir,
            CompactStateMachine(CompactPolicy()),
            _facts(now=late, confirmed=False, since=_NOW),
        )
        assert outcome.payload is None

    def test_unlatched_tick_posts_no_banner(self, sidecar_dir: Path) -> None:
        _write_red_sidecar(sidecar_dir)
        _decide(sidecar_dir, CompactStateMachine(CompactPolicy()), _facts())
        assert not _mod._status_message_path(sidecar_dir.parent).exists()


class TestEscalateOption:
    def test_default_bounds(self) -> None:
        assert CompactPolicy().focus_hold_escalate_seconds == (300.0, 900.0)

    def test_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CCY_FOCUS_HOLD_ESCALATE_SECONDS", "120,600")
        assert CompactPolicy().focus_hold_escalate_seconds == (120.0, 600.0)

    @pytest.mark.parametrize("raw", ["junk", "300", "900,300", "0,10", "-1,5", "300,300"])
    def test_invalid_override_keeps_default(self, raw: str) -> None:
        assert _mod._parse_focus_hold_escalate(raw) == (300.0, 900.0)

    def test_bounds_drive_the_escalation(self) -> None:
        machine = CompactStateMachine(CompactPolicy(focus_hold_escalate_seconds=(60.0, 120.0)))
        line = machine.focus_hold_log("goal", _hold(since=_NOW), now_wall=_NOW + 130)
        assert line is not None
        assert "\\x1b[A" in line
