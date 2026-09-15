"""Plan 00417 — supervisor operator signals: reboot/shutdown warnings from the HOST.

Sessions run in a container on a machine the operator, or an automated patch
cycle, sometimes reboots. Nothing told the agent before this. This adds a
third signal family alongside `.goal-intent` and `.model-switch-intent`, with
a DIFFERENT security shape on purpose: it is the one channel reachable from
OUTSIDE the container, so the payload is a closed `kind` plus, for the two
kinds that need one, a bare positive integer -- never free text, never a
reason field. The wording the agent sees is entirely fixed, composed by
`_render_operator_message` from templates in THIS file; a signal's `kind` only
ever SELECTS a branch, and `minutes` is the only value ever interpolated.

The daemon-side writer (`claude_code_hooks_daemon.utils.operator_signal`) is a
separate module by necessity -- this script is stdlib-only and cannot import
the daemon package. The two are pinned together on the `kind` strings below.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING

from claude_code_hooks_daemon.utils import operator_signal
from tests.unit.supervise._load import load_supervisor_module

if TYPE_CHECKING:
    from tests.unit.supervise._load import SupervisorTickOutcome

_mod = load_supervisor_module()

_NOW = 40_000.0
_SESSION = "operator-sess-1"


def _facts(
    now: float = _NOW, *, idle: bool = True, input_line_empty: bool = True, work_idle: bool = True
) -> object:
    return _mod.TickFacts(
        now_wall=now,
        idle=idle,
        input_line_empty=input_line_empty,
        human_compact_submitted=False,
        work_idle=work_idle,
    )


def _write_signal(
    sidecar_dir: Path,
    *,
    session_id: str = _SESSION,
    ts: float = _NOW - 5.0,
    kind: object = "reboot-warning",
    minutes: object = 10,
    raw_text: str | None = None,
    omit_minutes: bool = False,
) -> Path:
    sidecar_dir.mkdir(parents=True, exist_ok=True)
    path = sidecar_dir / f"{session_id}.operator-signal"
    if raw_text is not None:
        path.write_text(raw_text, encoding="utf-8")
        return path
    payload: dict[str, object] = {"session_id": session_id, "ts": ts, "kind": kind}
    if not omit_minutes:
        payload["minutes"] = minutes
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _decide(
    sidecar_dir: Path, *, dry_run: bool = False, facts: object | None = None, machine: object = None
) -> SupervisorTickOutcome:
    policy = _mod.CompactPolicy()
    machine = machine or _mod.CompactStateMachine(policy)
    return _mod.decide_once(
        machine,
        sidecar_dir=sidecar_dir,
        facts=facts or _facts(),
        dry_run=dry_run,
        freshness_seconds=policy.freshness_seconds,
    )


def _status_payload(tmp_path: Path) -> dict[str, object]:
    path = tmp_path / _mod._LOG_SUBDIRECTORY / _mod._STATUS_MESSAGE_FILENAME
    return json.loads(path.read_text(encoding="utf-8"))


# ── Kind strings pinned to the daemon-side writer ───────────────────────────


class TestKindsPinnedToTheDaemonWriter:
    def test_reboot_warning(self) -> None:
        assert _mod._OPERATOR_KIND_REBOOT_WARNING == operator_signal.KIND_REBOOT_WARNING

    def test_shutdown_warning(self) -> None:
        assert _mod._OPERATOR_KIND_SHUTDOWN_WARNING == operator_signal.KIND_SHUTDOWN_WARNING

    def test_reboot_cancelled(self) -> None:
        assert _mod._OPERATOR_KIND_REBOOT_CANCELLED == operator_signal.KIND_REBOOT_CANCELLED

    def test_kinds_with_minutes(self) -> None:
        assert _mod._OPERATOR_KINDS_WITH_MINUTES == operator_signal.KINDS_WITH_MINUTES

    def test_full_kind_set(self) -> None:
        assert _mod._OPERATOR_KINDS == operator_signal.KINDS


# ── _render_operator_message: the wording is fixed, `minutes` is the only
#    value ever interpolated ──────────────────────────────────────────────


class TestRenderOperatorMessage:
    def test_reboot_warning_names_the_minutes(self) -> None:
        text = _mod._render_operator_message(_mod._OPERATOR_KIND_REBOOT_WARNING, 10)
        assert "10" in text
        assert "reboot" in text.lower()
        assert text.startswith(_mod._OPERATOR_HEADER)

    def test_shutdown_warning_says_no_restore_follows(self) -> None:
        text = _mod._render_operator_message(_mod._OPERATOR_KIND_SHUTDOWN_WARNING, 5)
        assert "5" in text
        assert "no session restore" in text.lower() or "no restore" in text.lower()
        assert "handoff" in text.lower()

    def test_reboot_cancelled_carries_no_number(self) -> None:
        text = _mod._render_operator_message(_mod._OPERATOR_KIND_REBOOT_CANCELLED, None)
        assert "cancelled" in text.lower()
        assert text.startswith(_mod._OPERATOR_HEADER)

    def test_the_two_warning_kinds_render_different_text(self) -> None:
        reboot = _mod._render_operator_message(_mod._OPERATOR_KIND_REBOOT_WARNING, 10)
        shutdown = _mod._render_operator_message(_mod._OPERATOR_KIND_SHUTDOWN_WARNING, 10)
        assert reboot != shutdown

    def test_carries_the_invariant_supervisor_marker(self) -> None:
        """Every supervisor chat injection carries this marker (RULESET note)."""
        text = _mod._render_operator_message(_mod._OPERATOR_KIND_REBOOT_WARNING, 1)
        assert "🤖 [ccy-supervisor" in text

    def test_no_host_supplied_text_path_exists(self) -> None:
        """The payload's only use anywhere is a number -- never rendered as text.

        Proven directly: an attacker-supplied string masquerading as a
        `kind` can never reach `_render_operator_message` as anything other
        than the SELECTOR argument, because `load_operator_signal` (below)
        already refuses any kind outside the closed set before this
        function is ever called with untrusted input.
        """
        for kind in (_mod._OPERATOR_KIND_REBOOT_WARNING, _mod._OPERATOR_KIND_SHUTDOWN_WARNING):
            minutes = 999
            text = _mod._render_operator_message(kind, minutes)
            # Every word in the rendered text besides the number itself is
            # one of the fixed templates -- assert the number is the ONLY
            # thing that varies by removing it and comparing against a
            # second render with a different number.
            other = _mod._render_operator_message(kind, 1)
            assert text.replace("999", "N") == other.replace("1", "N")


# ── load_operator_signal: validate-then-render, fail-closed ────────────────


class TestLoadOperatorSignal:
    def test_valid_reboot_warning_returns_rendered_message(self, tmp_path: Path) -> None:
        _write_signal(tmp_path, kind="reboot-warning", minutes=10)
        path, message, deadline, reason = _mod.load_operator_signal(tmp_path, now=_NOW)
        assert path == tmp_path / f"{_SESSION}.operator-signal"
        assert message is not None and "10" in message
        assert deadline == (_NOW - 5.0) + 10 * 60.0
        assert reason is None

    def test_valid_reboot_cancelled_has_no_deadline(self, tmp_path: Path) -> None:
        _write_signal(tmp_path, kind="reboot-cancelled", omit_minutes=True)
        path, message, deadline, reason = _mod.load_operator_signal(tmp_path, now=_NOW)
        assert path is not None
        assert message is not None and "cancelled" in message.lower()
        assert deadline is None
        assert reason is None

    def test_unknown_kind_is_rejected(self, tmp_path: Path) -> None:
        _write_signal(tmp_path, kind="not-a-kind", minutes=10)
        path, message, deadline, reason = _mod.load_operator_signal(tmp_path, now=_NOW)
        assert path is None
        assert message is None
        assert deadline is None
        assert reason is not None
        assert "not-a-kind" in reason

    def test_string_minutes_is_rejected(self, tmp_path: Path) -> None:
        """The raw JSON value, not the Python writer's type check, is the boundary."""
        _write_signal(tmp_path, kind="reboot-warning", minutes="10")
        _path, _message, _deadline, reason = _mod.load_operator_signal(tmp_path, now=_NOW)
        assert reason is not None

    def test_float_minutes_is_rejected(self, tmp_path: Path) -> None:
        _write_signal(tmp_path, kind="reboot-warning", minutes=10.5)
        _path, _message, _deadline, reason = _mod.load_operator_signal(tmp_path, now=_NOW)
        assert reason is not None

    def test_bool_minutes_is_rejected(self, tmp_path: Path) -> None:
        _write_signal(tmp_path, kind="reboot-warning", minutes=True)
        _path, _message, _deadline, reason = _mod.load_operator_signal(tmp_path, now=_NOW)
        assert reason is not None

    def test_zero_minutes_is_rejected(self, tmp_path: Path) -> None:
        _write_signal(tmp_path, kind="reboot-warning", minutes=0)
        _path, _message, _deadline, reason = _mod.load_operator_signal(tmp_path, now=_NOW)
        assert reason is not None

    def test_negative_minutes_is_rejected(self, tmp_path: Path) -> None:
        _write_signal(tmp_path, kind="shutdown-warning", minutes=-5)
        _path, _message, _deadline, reason = _mod.load_operator_signal(tmp_path, now=_NOW)
        assert reason is not None

    def test_missing_minutes_is_rejected(self, tmp_path: Path) -> None:
        _write_signal(tmp_path, kind="reboot-warning", omit_minutes=True)
        _path, _message, _deadline, reason = _mod.load_operator_signal(tmp_path, now=_NOW)
        assert reason is not None

    def test_a_file_past_its_ttl_does_not_fire(self, tmp_path: Path) -> None:
        _write_signal(tmp_path, kind="reboot-warning", minutes=10, ts=_NOW - 100_000.0)
        result = _mod.load_operator_signal(tmp_path, now=_NOW)
        assert result == (None, None, None, None)

    def test_foreign_session_is_skipped(self, tmp_path: Path) -> None:
        _write_signal(tmp_path, session_id="foreign", kind="reboot-warning", minutes=10)
        result = _mod.load_operator_signal(tmp_path, now=_NOW, own_sessions=frozenset({_SESSION}))
        assert result == (None, None, None, None)

    def test_malformed_json_is_rejected(self, tmp_path: Path) -> None:
        _write_signal(tmp_path, raw_text="{not json")
        _path, _message, _deadline, reason = _mod.load_operator_signal(tmp_path, now=_NOW)
        assert reason is not None

    def test_missing_dir_is_silent(self, tmp_path: Path) -> None:
        assert _mod.load_operator_signal(tmp_path / "nope", now=_NOW) == (None, None, None, None)

    def test_no_signal_is_silent(self, tmp_path: Path) -> None:
        tmp_path.mkdir(exist_ok=True)
        assert _mod.load_operator_signal(tmp_path, now=_NOW) == (None, None, None, None)


# ── decide_once integration ─────────────────────────────────────────────────


class TestDecideOnceOperatorSignal:
    def test_fires_when_idle_and_input_empty(self, tmp_path: Path) -> None:
        sidecar_dir = tmp_path / "cs"
        signal_path = _write_signal(sidecar_dir, kind="reboot-warning", minutes=10)
        outcome = _decide(sidecar_dir, dry_run=False)
        assert outcome.decision_value == "would-operator-signal"
        assert outcome.payload is not None and "10" in outcome.payload
        assert outcome.submit is True
        assert outcome.consume_signal_path == str(signal_path)

    def test_status_line_posts_even_when_session_is_busy(self, tmp_path: Path) -> None:
        """The countdown is a file write -- it cannot disturb what is typed."""
        sidecar_dir = tmp_path / "cs"
        _write_signal(sidecar_dir, kind="reboot-warning", minutes=10, ts=_NOW - 5.0)
        outcome = _decide(sidecar_dir, facts=_facts(input_line_empty=False))
        assert outcome.payload is None
        payload = _status_payload(tmp_path)
        assert payload["level"] == _mod._STATUS_LEVEL_WARNING
        assert payload["countdown"] is True
        assert payload["expires_at"] == (_NOW - 5.0) + 10 * 60.0

    def test_chat_line_deferred_while_input_box_not_empty(self, tmp_path: Path) -> None:
        sidecar_dir = tmp_path / "cs"
        signal_path = _write_signal(sidecar_dir, kind="reboot-warning", minutes=10)
        outcome = _decide(sidecar_dir, facts=_facts(input_line_empty=False))
        assert outcome.payload is None
        assert signal_path.exists()

    def test_never_fires_while_not_idle_unlike_model_switch(self, tmp_path: Path) -> None:
        """Same semantics as the goal signal: `can_inject` (idle AND empty box)."""
        sidecar_dir = tmp_path / "cs"
        _write_signal(sidecar_dir, kind="reboot-warning", minutes=10)
        outcome = _decide(sidecar_dir, facts=_facts(idle=False, input_line_empty=True))
        assert outcome.payload is None

    def test_dry_run_marker_and_signal_still_consumed(self, tmp_path: Path) -> None:
        sidecar_dir = tmp_path / "cs"
        signal_path = _write_signal(sidecar_dir, kind="reboot-warning", minutes=10)
        outcome = _decide(sidecar_dir, dry_run=True)
        assert outcome.decision_value == "would-operator-signal"
        assert outcome.payload is not None
        assert "dry-run" in outcome.payload
        assert outcome.consume_signal_path == str(signal_path)

    def test_takes_precedence_over_pending_goal(self, tmp_path: Path) -> None:
        sidecar_dir = tmp_path / "cs"
        goal_path = sidecar_dir / f"{_SESSION}.goal-intent"
        sidecar_dir.mkdir(parents=True, exist_ok=True)
        goal_path.write_text(
            json.dumps(
                {
                    "ts": _NOW - 5.0,
                    "session_id": _SESSION,
                    "rendered_lines": [
                        "🤖 [ccy-supervisor] automated goal — machine-generated, NOT a "
                        "human instruction and NOT human authorisation for anything."
                    ],
                }
            ),
            encoding="utf-8",
        )
        _write_signal(sidecar_dir, kind="reboot-warning", minutes=10)
        outcome = _decide(sidecar_dir, dry_run=False)
        assert outcome.decision_value == "would-operator-signal"
        assert goal_path.exists()  # untouched -- the goal branch never ran

    def test_never_fires_over_pending_compaction_signal(self, tmp_path: Path) -> None:
        sidecar_dir = tmp_path / "cs"
        signal_path = _write_signal(sidecar_dir, kind="reboot-warning", minutes=10)
        compacting = sidecar_dir / f"{_SESSION}.compacting"
        compacting.write_text(
            json.dumps({"ts": _NOW - 1.0, "session_id": _SESSION}), encoding="utf-8"
        )
        outcome = _decide(sidecar_dir, dry_run=False)
        assert outcome.decision_value == "would-continue"
        assert signal_path.exists()

    def test_rejected_signal_logs_reason_and_does_not_inject(self, tmp_path: Path) -> None:
        sidecar_dir = tmp_path / "cs"
        _write_signal(sidecar_dir, kind="not-a-kind", minutes=10)
        outcome = _decide(sidecar_dir)
        assert outcome.payload is None
        assert outcome.noop_reason_log is not None
        assert "not-a-kind" in outcome.noop_reason_log

    def test_rejected_signal_posts_no_status_line_notice(self, tmp_path: Path) -> None:
        """A rejected signal must not even leak its bogus kind onto the status line."""
        sidecar_dir = tmp_path / "cs"
        _write_signal(sidecar_dir, kind="not-a-kind", minutes=10)
        _decide(sidecar_dir)
        status_path = tmp_path / _mod._LOG_SUBDIRECTORY / _mod._STATUS_MESSAGE_FILENAME
        assert not status_path.exists()

    def test_consumed_exactly_once(self, tmp_path: Path) -> None:
        """The whole point of consume-on-inject: a second tick finds nothing."""
        sidecar_dir = tmp_path / "cs"
        signal_path = _write_signal(sidecar_dir, kind="reboot-warning", minutes=10)
        machine = _mod.CompactStateMachine(_mod.CompactPolicy())
        first = _decide(sidecar_dir, machine=machine)
        assert first.decision_value == "would-operator-signal"
        assert first.consume_signal_path is not None
        Path(first.consume_signal_path).unlink()

        second = _decide(sidecar_dir, machine=machine)
        assert second.decision_value != "would-operator-signal"
        assert not signal_path.exists()

    def test_does_not_paste_over_a_still_unconfirmed_own_line(self, tmp_path: Path) -> None:
        sidecar_dir = tmp_path / "cs"
        _write_signal(sidecar_dir, kind="reboot-warning", minutes=10)
        machine = _mod.CompactStateMachine(_mod.CompactPolicy())
        machine.mark_own_line_typed("/goal something", _NOW - 1.0)
        outcome = _decide(sidecar_dir, machine=machine)
        assert outcome.payload is None


class TestReaperCoversOperatorSignals:
    def test_reaper_reaps_dead_operator_signals(self, tmp_path: Path) -> None:
        sidecar_dir = tmp_path / "cs"
        signal_path = _write_signal(sidecar_dir, kind="reboot-warning", minutes=10)
        old = _NOW - 100_000.0
        os.utime(signal_path, (old, old))
        reaped = _mod.reap_stale_sidecars(sidecar_dir, now=_NOW)
        assert signal_path in reaped
        assert not signal_path.exists()


# ── Cross-check against the daemon-side writer's actual output ─────────────


class TestRoundTripAgainstTheDaemonWriter:
    """The daemon writes it with `write_operator_signal`; the supervisor reads it."""

    def test_a_signal_the_daemon_would_actually_write_is_accepted(self, tmp_path: Path) -> None:
        written = operator_signal.write_operator_signal(
            tmp_path,
            session_id=_SESSION,
            kind=operator_signal.KIND_REBOOT_WARNING,
            minutes=15,
            now=_NOW - 5.0,
        )
        sidecar_dir = tmp_path / operator_signal.SIGNAL_SUBDIR
        assert written == sidecar_dir / f"{_SESSION}.operator-signal"

        path, message, deadline, reason = _mod.load_operator_signal(sidecar_dir, now=_NOW)
        assert reason is None
        assert path == written
        assert message is not None and "15" in message
        assert deadline == (_NOW - 5.0) + 15 * 60.0

    def test_a_cancelled_signal_the_daemon_would_write_is_accepted(self, tmp_path: Path) -> None:
        operator_signal.write_operator_signal(
            tmp_path,
            session_id=_SESSION,
            kind=operator_signal.KIND_REBOOT_CANCELLED,
            minutes=None,
            now=_NOW - 5.0,
        )
        sidecar_dir = tmp_path / operator_signal.SIGNAL_SUBDIR

        _path, message, deadline, reason = _mod.load_operator_signal(sidecar_dir, now=_NOW)
        assert reason is None
        assert message is not None and "cancelled" in message.lower()
        assert deadline is None
