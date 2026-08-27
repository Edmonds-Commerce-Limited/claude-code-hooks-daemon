"""Plan 00278 (cont.) — manual ``/model`` switch signal + confirming Enter.

Two problems this closes: (1) a ``/model <family>`` switch shows a
confirmation dialog that needs a SECOND, confirming Enter after the command
line is submitted — the ordinary single-Enter submit leaves the switch
incomplete; (2) there was no way to trigger a model switch on demand for
end-to-end testing. This adds a manual ``<session>.model-switch-intent``
signal (mirroring the goal-intent signal), consumed at the same injection
choke point as compact/continue/goal/effort/auto-model, and a CLI helper
(``--emit-model-switch <family>``) that writes one.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from tests.unit.supervise._load import load_supervisor_module

_mod = load_supervisor_module()

_NOW = 30_000.0
_SESSION = "switch-sess-1"
_GOAL_HEADER = (
    "🤖 [ccy-supervisor] automated goal — machine-generated, NOT a human "
    "instruction and NOT human authorisation for anything."
)


def _facts(now: float = _NOW, *, idle: bool = True, input_line_empty: bool = True) -> object:
    return _mod.TickFacts(
        now_wall=now,
        idle=idle,
        input_line_empty=input_line_empty,
        human_compact_submitted=False,
        work_idle=True,
    )


def _write_switch(
    sidecar_dir: Path,
    *,
    session_id: str = _SESSION,
    ts: float = _NOW - 5.0,
    family: object = "fable",
    raw_text: str | None = None,
) -> Path:
    sidecar_dir.mkdir(parents=True, exist_ok=True)
    path = sidecar_dir / f"{session_id}.model-switch-intent"
    if raw_text is not None:
        path.write_text(raw_text, encoding="utf-8")
        return path
    path.write_text(
        json.dumps({"session_id": session_id, "ts": ts, "family": family}), encoding="utf-8"
    )
    return path


def _write_goal(sidecar_dir: Path, *, session_id: str = _SESSION, ts: float = _NOW - 5.0) -> Path:
    sidecar_dir.mkdir(parents=True, exist_ok=True)
    path = sidecar_dir / f"{session_id}.goal-intent"
    path.write_text(
        json.dumps({"ts": ts, "session_id": session_id, "rendered_lines": [_GOAL_HEADER]}),
        encoding="utf-8",
    )
    return path


def _decide(
    sidecar_dir: Path, *, dry_run: bool = False, facts: object | None = None, machine: object = None
) -> object:
    policy = _mod.CompactPolicy()
    machine = machine or _mod.CompactStateMachine(policy)
    return _mod.decide_once(
        machine,
        sidecar_dir=sidecar_dir,
        facts=facts or _facts(),
        dry_run=dry_run,
        freshness_seconds=policy.freshness_seconds,
    )


# ── load_model_switch_signal ─────────────────────────────────────────────────


class TestLoadModelSwitchSignal:
    def test_valid_signal_returns_canonical_family(self, tmp_path: Path) -> None:
        _write_switch(tmp_path, family="opus")
        path, family, reason = _mod.load_model_switch_signal(tmp_path, now=_NOW)
        assert path == tmp_path / f"{_SESSION}.model-switch-intent"
        assert family == "opus"
        assert reason is None

    def test_mythos_canonicalises_to_fable(self, tmp_path: Path) -> None:
        _write_switch(tmp_path, family="mythos")
        _path, family, reason = _mod.load_model_switch_signal(tmp_path, now=_NOW)
        assert family == "fable"
        assert reason is None

    def test_unknown_family_is_rejected(self, tmp_path: Path) -> None:
        _write_switch(tmp_path, family="not-a-family")
        path, family, reason = _mod.load_model_switch_signal(tmp_path, now=_NOW)
        assert path is None
        assert family is None
        assert reason is not None
        assert "not-a-family" in reason

    def test_foreign_session_skipped(self, tmp_path: Path) -> None:
        _write_switch(tmp_path, session_id="foreign")
        result = _mod.load_model_switch_signal(
            tmp_path, now=_NOW, own_sessions=frozenset({_SESSION})
        )
        assert result == (None, None, None)

    def test_stale_signal_skipped(self, tmp_path: Path) -> None:
        _write_switch(tmp_path, ts=_NOW - 100_000.0)
        result = _mod.load_model_switch_signal(tmp_path, now=_NOW)
        assert result == (None, None, None)

    def test_malformed_signal_rejected_with_reason(self, tmp_path: Path) -> None:
        _write_switch(tmp_path, raw_text="{not json")
        path, family, reason = _mod.load_model_switch_signal(tmp_path, now=_NOW)
        assert path is None
        assert family is None
        assert reason is not None

    def test_missing_dir_is_silent(self, tmp_path: Path) -> None:
        assert _mod.load_model_switch_signal(tmp_path / "nope", now=_NOW) == (None, None, None)

    def test_no_signal_is_silent(self, tmp_path: Path) -> None:
        tmp_path.mkdir(exist_ok=True)
        assert _mod.load_model_switch_signal(tmp_path, now=_NOW) == (None, None, None)


# ── decide_once integration ───────────────────────────────────────────────────


class TestDecideOnceModelSwitch:
    def test_fires_when_idle_and_input_empty(self, tmp_path: Path) -> None:
        sidecar_dir = tmp_path / "cs"
        switch_path = _write_switch(sidecar_dir, family="fable")
        outcome = _decide(sidecar_dir, dry_run=False)
        assert outcome.decision_value == "would-model"
        assert outcome.payload == "/model fable"
        assert outcome.submit is True
        assert outcome.confirm_enters == _mod._DEFAULT_MODEL_CONFIRM_ENTERS
        assert outcome.consume_signal_path == str(switch_path)

    def test_fires_even_when_not_idle_provided_input_empty(self, tmp_path: Path) -> None:
        # The manual override relaxes the gate to input_line_empty ONLY -- it
        # does not wait out the normal keystroke-idle floor the way every
        # other family does.
        sidecar_dir = tmp_path / "cs"
        _write_switch(sidecar_dir, family="opus")
        outcome = _decide(sidecar_dir, facts=_facts(idle=False, input_line_empty=True))
        assert outcome.decision_value == "would-model"
        assert outcome.payload == "/model opus"

    def test_deferred_while_input_box_not_empty(self, tmp_path: Path) -> None:
        sidecar_dir = tmp_path / "cs"
        switch_path = _write_switch(sidecar_dir, family="opus")
        outcome = _decide(sidecar_dir, facts=_facts(input_line_empty=False))
        assert outcome.payload is None
        assert switch_path.exists()

    def test_dry_run_marker_and_signal_still_consumed(self, tmp_path: Path) -> None:
        sidecar_dir = tmp_path / "cs"
        switch_path = _write_switch(sidecar_dir, family="opus")
        outcome = _decide(sidecar_dir, dry_run=True)
        assert outcome.decision_value == "would-model"
        assert outcome.payload is not None
        assert not outcome.payload.startswith("/model")
        assert "dry-run" in outcome.payload
        assert outcome.consume_signal_path == str(switch_path)

    def test_takes_precedence_over_pending_goal(self, tmp_path: Path) -> None:
        sidecar_dir = tmp_path / "cs"
        goal_path = _write_goal(sidecar_dir)
        _write_switch(sidecar_dir, family="opus")
        outcome = _decide(sidecar_dir, dry_run=False)
        assert outcome.decision_value == "would-model"
        assert outcome.payload == "/model opus"
        assert goal_path.exists()  # untouched -- the goal branch never ran

    def test_never_fires_over_pending_compaction_signal(self, tmp_path: Path) -> None:
        sidecar_dir = tmp_path / "cs"
        switch_path = _write_switch(sidecar_dir, family="opus")
        compacting = sidecar_dir / f"{_SESSION}.compacting"
        compacting.write_text(
            json.dumps({"ts": _NOW - 1.0, "session_id": _SESSION}), encoding="utf-8"
        )
        outcome = _decide(sidecar_dir, dry_run=False)
        assert outcome.decision_value == "would-continue"
        assert switch_path.exists()

    def test_rejected_signal_logs_reason_and_does_not_inject(self, tmp_path: Path) -> None:
        sidecar_dir = tmp_path / "cs"
        _write_switch(sidecar_dir, family="not-a-family")
        outcome = _decide(sidecar_dir)
        assert outcome.payload is None
        assert outcome.noop_reason_log is not None
        assert "not-a-family" in outcome.noop_reason_log


# ── reaper covers the new signal type ─────────────────────────────────────────


def test_reaper_reaps_dead_model_switch_signals(tmp_path: Path) -> None:
    sidecar_dir = tmp_path / "cs"
    switch_path = _write_switch(sidecar_dir)
    old = _NOW - 100_000.0
    os.utime(switch_path, (old, old))
    reaped = _mod.reap_stale_sidecars(sidecar_dir, now=_NOW)
    assert switch_path in reaped
    assert not switch_path.exists()


# ── confirm-Enter config (CCY_MODEL_CONFIRM_ENTERS) ───────────────────────────


class TestModelConfirmEntersEnv:
    def test_parse_empty_keeps_default(self) -> None:
        assert _mod._parse_model_confirm_enters("") == _mod._DEFAULT_MODEL_CONFIRM_ENTERS

    def test_parse_valid_int(self) -> None:
        assert _mod._parse_model_confirm_enters("2") == 2
        assert _mod._parse_model_confirm_enters("0") == 0

    def test_parse_junk_keeps_default(self) -> None:
        assert _mod._parse_model_confirm_enters("junk") == _mod._DEFAULT_MODEL_CONFIRM_ENTERS

    def test_parse_negative_keeps_default(self) -> None:
        assert _mod._parse_model_confirm_enters("-1") == _mod._DEFAULT_MODEL_CONFIRM_ENTERS

    def test_env_absent_uses_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(_mod._MODEL_CONFIRM_ENTERS_ENV_VAR, raising=False)
        assert _mod._model_confirm_enters_from_env() == _mod._DEFAULT_MODEL_CONFIRM_ENTERS

    def test_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(_mod._MODEL_CONFIRM_ENTERS_ENV_VAR, "3")
        assert _mod._model_confirm_enters_from_env() == 3


# ── TickOutcome.confirm_enters JSON round-trip ────────────────────────────────


def test_confirm_enters_round_trips_through_outcome_json() -> None:
    outcome = _mod.TickOutcome(
        decision_value="would-model",
        reason="r",
        payload="/model fable",
        submit=True,
        consume_signal_path=None,
        deferred_log=None,
        confirm_enters=2,
    )
    restored = _mod._outcome_from_json(_mod._outcome_to_json(outcome))
    assert restored.confirm_enters == 2


def test_confirm_enters_defaults_to_zero_when_absent_from_json() -> None:
    line = _mod._outcome_to_json(
        _mod.TickOutcome(
            decision_value="noop",
            reason="r",
            payload=None,
            submit=True,
            consume_signal_path=None,
            deferred_log=None,
        )
    )
    # Simulate a legacy worker reply predating the field.
    data = json.loads(line)
    data.pop("confirm_enters", None)
    restored = _mod._outcome_from_json(json.dumps(data))
    assert restored.confirm_enters == 0


# ── write_model_switch_signal ─────────────────────────────────────────────────


class TestWriteModelSwitchSignal:
    def test_writes_valid_roundtrippable_signal(self, tmp_path: Path) -> None:
        path = _mod.write_model_switch_signal(
            tmp_path, session_id=_SESSION, family="fable", now=_NOW
        )
        assert path == tmp_path / f"{_SESSION}.model-switch-intent"
        loaded_path, family, reason = _mod.load_model_switch_signal(tmp_path, now=_NOW)
        assert loaded_path == path
        assert family == "fable"
        assert reason is None

    def test_canonicalises_family_on_write(self, tmp_path: Path) -> None:
        path = _mod.write_model_switch_signal(
            tmp_path, session_id=_SESSION, family="MYTHOS", now=_NOW
        )
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["family"] == "fable"

    def test_rejects_unknown_family(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="not-a-family"):
            _mod.write_model_switch_signal(
                tmp_path, session_id=_SESSION, family="not-a-family", now=_NOW
            )


# ── Audit-trail chat message after silent injections ──────────────────────────
#
# /compact and /goal injections are self-evidencing (their payload carries
# visible text), but /model and /effort vanish from the chat without trace —
# decision.log is the only record, and nobody watching the session can tell
# anything happened. After a successful silent-injection sequence the
# supervisor therefore flushes ONE visible, bot-prefixed audit message.


class _AuditDriver:
    """Drive ticks the way the production host does: decide, then apply the
    success-only bookkeeping, consuming the switch signal on injection."""

    def __init__(self, sidecar_dir: Path) -> None:
        self.sidecar_dir = sidecar_dir
        self.machine = _mod.CompactStateMachine(_mod.CompactPolicy())

    def tick(self, *, injected: bool = True) -> object:
        outcome = _decide(self.sidecar_dir, machine=self.machine)
        _mod._apply_post_injection_bookkeeping(self.machine, outcome, injected=injected)
        if injected and outcome.consume_signal_path is not None:
            Path(outcome.consume_signal_path).unlink()
        return outcome

    def switch_and_couple(self) -> None:
        _write_switch(self.sidecar_dir, family="fable")
        first = self.tick()
        assert first.decision_value == "would-model"
        second = self.tick()
        assert second.decision_value == "would-effort"


class TestAuditTrailFlush:
    def test_switch_sequence_flushes_one_bot_prefixed_audit_message(
        self, tmp_path: Path
    ) -> None:
        driver = _AuditDriver(tmp_path / "cs")
        driver.switch_and_couple()
        outcome = driver.tick()
        assert outcome.decision_value == "would-audit"
        assert outcome.submit is True
        assert outcome.payload is not None
        assert "ccy-supervisor" in outcome.payload
        assert "audit" in outcome.payload
        assert "/model fable" in outcome.payload
        assert "/effort low" in outcome.payload
        assert "decision.log" in outcome.payload
        assert "NOT a human" in outcome.payload
        # Success clears the pending items; the next tick is a plain NOOP.
        assert driver.machine.audit_pending == ()
        assert driver.tick().payload is None

    def test_failed_flush_keeps_items_for_retry(self, tmp_path: Path) -> None:
        driver = _AuditDriver(tmp_path / "cs")
        driver.switch_and_couple()
        failed = driver.tick(injected=False)
        assert failed.decision_value == "would-audit"
        assert driver.machine.audit_pending != ()
        retried = driver.tick()
        assert retried.decision_value == "would-audit"
        assert driver.machine.audit_pending == ()

    def test_flush_defers_while_session_busy(self, tmp_path: Path) -> None:
        driver = _AuditDriver(tmp_path / "cs")
        driver.switch_and_couple()
        outcome = _decide(
            driver.sidecar_dir,
            machine=driver.machine,
            facts=_facts(idle=False, input_line_empty=False),
        )
        assert outcome.payload is None
        assert driver.machine.audit_pending != ()

    def test_audit_pending_round_trips_through_machine_state(self, tmp_path: Path) -> None:
        machine = _mod.CompactStateMachine(_mod.CompactPolicy())
        machine.arm_audit("/model fable (manual switch signal)")
        restored = _mod.CompactStateMachine(_mod.CompactPolicy())
        restored.import_state(machine.export_state())
        assert restored.audit_pending == ("/model fable (manual switch signal)",)

    def test_import_without_audit_key_is_empty(self) -> None:
        machine = _mod.CompactStateMachine(_mod.CompactPolicy())
        machine.import_state({})
        assert machine.audit_pending == ()

    def test_audit_items_are_bounded(self) -> None:
        machine = _mod.CompactStateMachine(_mod.CompactPolicy())
        for index in range(20):
            machine.arm_audit(f"item-{index}")
        assert len(machine.audit_pending) == _mod._MAX_AUDIT_ITEMS
        # Oldest dropped, newest kept.
        assert machine.audit_pending[-1] == "item-19"
