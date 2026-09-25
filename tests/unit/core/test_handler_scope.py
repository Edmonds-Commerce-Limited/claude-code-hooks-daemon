"""A handler declares where it is active: ALL, MAIN or SUB (Plan 00423 Task 3.1).

Issue #40 asks that a nudge handler stop firing at subagents. The discriminator
was proved in Phase 2 against live payloads: ``agent_id`` reaches a hook only
inside a subagent call, so its ABSENCE means main thread. Two things about that
proof are load-bearing here and are pinned below rather than inherited.

**``agent_type`` is disqualified, in BOTH directions.** The contract warns it
appears on a main-thread stop under a session-wide ``--agent`` (over-reports);
Phase 2 measured it present but EMPTY in 4 of 5 real subagent stops
(under-reports). A handler keying on it would have misclassified four of five
subagents as main-thread — firing nudges exactly where they were meant to be
suppressed. Nothing here reads it.

**A synthetic event has no ``agent_id`` either**, so it is indistinguishable
from a main-thread one by that field alone. The acceptance playbook fabricates
events, and ``orchestrator_simulate`` already guards with
``is_synthetic_event()`` — its docstring records that without it the suite went
red "with hundreds of denied probes AND, under most-restrictive-wins, other
handlers' expected ALLOWs turned into failures". So ``MAIN`` cannot mean "no
``agent_id``"; it must mean "no ``agent_id`` AND not synthetic", and the test
for that fabricates one rather than describing it.
"""

from __future__ import annotations

from typing import Any

import pytest

from claude_code_hooks_daemon.core.handler_scope import (
    HandlerScope,
    resolve_scope,
    scope_admits,
)
from claude_code_hooks_daemon.daemon.synthetic_traffic import (
    MANUAL_PROBE,
    PROBE_AGENT_ID,
    PROBE_AS_FIELD,
    SOCKET_STDIN_TEST,
    SYNTHETIC_SOURCE_FIELD,
    TEST_PROBE,
    TRANSPORT_VERIFY,
)

_AGENT_ID = "agent_01H9XQK2M4N7P"


def _main_thread() -> dict[str, Any]:
    return {"hook_event_name": "PreToolUse", "tool_name": "Write", "session_id": "real-session"}


def _subagent() -> dict[str, Any]:
    return {**_main_thread(), "agent_id": _AGENT_ID}


def _synthetic() -> dict[str, Any]:
    """A fabricated event: no agent_id, so main-thread by that field alone."""
    return {**_main_thread(), SYNTHETIC_SOURCE_FIELD: "playbook-probe"}


class TestScopeAll:
    """The default, and it must never turn anything off."""

    @pytest.mark.parametrize(
        "event", [_main_thread(), _subagent(), _synthetic()], ids=["main", "sub", "synthetic"]
    )
    def test_admits_every_event(self, event: dict[str, Any]) -> None:
        assert scope_admits(HandlerScope.ALL, event)


class TestScopeMain:
    def test_admits_the_main_thread(self) -> None:
        assert scope_admits(HandlerScope.MAIN, _main_thread())

    def test_refuses_a_subagent(self) -> None:
        assert not scope_admits(HandlerScope.MAIN, _subagent())

    def test_refuses_a_synthetic_event(self) -> None:
        """The trap: no agent_id, and still not the main thread."""
        assert not scope_admits(HandlerScope.MAIN, _synthetic())

    def test_an_empty_agent_id_is_not_a_subagent(self) -> None:
        """Measured: agent_id is a 17-char string whenever present, never empty.

        Keying on truthiness is therefore safe, but the property that makes it
        safe is worth pinning rather than inheriting by accident.
        """
        assert scope_admits(HandlerScope.MAIN, {**_main_thread(), "agent_id": ""})


class TestScopeSub:
    def test_admits_a_subagent(self) -> None:
        assert scope_admits(HandlerScope.SUB, _subagent())

    def test_refuses_the_main_thread(self) -> None:
        assert not scope_admits(HandlerScope.SUB, _main_thread())

    def test_refuses_a_synthetic_event(self) -> None:
        """Symmetry: a fabricated event is neither, so neither scope claims it."""
        assert not scope_admits(HandlerScope.SUB, _synthetic())


def _probe(**fields: Any) -> dict[str, Any]:
    """A hand-sent probe: marked with the probe helper's own source."""
    return {**_main_thread(), SYNTHETIC_SOURCE_FIELD: MANUAL_PROBE, **fields}


class TestProbeAs:
    """Plan 00466 N12: a probe is synthetic for the LOG and still names a thread.

    Without this a marked probe could never exercise a MAIN- or SUB-scoped
    handler: measured, a marked Stop probe answered `{}` where the same
    payload unmarked was blocked by `auto_continue_stop`.
    """

    def test_a_probe_as_main_is_admitted_by_main(self) -> None:
        assert scope_admits(HandlerScope.MAIN, _probe(**{PROBE_AS_FIELD: "main"}))

    def test_a_probe_as_main_is_refused_by_sub(self) -> None:
        assert not scope_admits(HandlerScope.SUB, _probe(**{PROBE_AS_FIELD: "main"}))

    def test_a_probe_with_no_probe_as_is_still_refused_by_both(self) -> None:
        assert not scope_admits(HandlerScope.MAIN, _probe())
        assert not scope_admits(HandlerScope.SUB, _probe())

    def test_a_probe_as_sub_with_the_probe_agent_is_admitted_by_sub(self) -> None:
        event = _probe(**{PROBE_AS_FIELD: "sub", "agent_id": PROBE_AGENT_ID})
        assert scope_admits(HandlerScope.SUB, event)
        assert not scope_admits(HandlerScope.MAIN, event)

    def test_a_probe_as_sub_needs_the_documented_probe_agent_id(self) -> None:
        """Otherwise a probe could borrow a real teammate's identity."""
        assert not scope_admits(HandlerScope.SUB, _probe(**{PROBE_AS_FIELD: "sub"}))
        real = _probe(**{PROBE_AS_FIELD: "sub", "agent_id": _AGENT_ID})
        assert not scope_admits(HandlerScope.SUB, real)

    def test_a_probe_as_main_carrying_an_agent_id_contradicts_itself(self) -> None:
        event = _probe(**{PROBE_AS_FIELD: "main", "agent_id": PROBE_AGENT_ID})
        assert not scope_admits(HandlerScope.MAIN, event)

    @pytest.mark.parametrize("source", ["playbook-probe", "cron-tick"])
    def test_a_non_probe_synthetic_source_cannot_claim_a_thread(self, source: str) -> None:
        """A harness, a cron tick or a supervisor event keeps today's refusal."""
        event = {**_main_thread(), SYNTHETIC_SOURCE_FIELD: source, PROBE_AS_FIELD: "main"}
        assert not scope_admits(HandlerScope.MAIN, event)
        sub = {**event, PROBE_AS_FIELD: "sub", "agent_id": PROBE_AGENT_ID}
        assert not scope_admits(HandlerScope.SUB, sub)

    @pytest.mark.parametrize("source", [TRANSPORT_VERIFY, TEST_PROBE, SOCKET_STDIN_TEST])
    def test_a_live_daemon_probe_source_is_declared_probe_class(self, source: str) -> None:
        """Each sends a Stop probe that exists to see `auto_continue_stop` block."""
        event = {**_main_thread(), SYNTHETIC_SOURCE_FIELD: source, PROBE_AS_FIELD: "main"}
        assert scope_admits(HandlerScope.MAIN, event)

    @pytest.mark.parametrize("value", ["MAIN", "orchestrator", "", 1, None])
    def test_an_unknown_probe_as_value_is_refused(self, value: object) -> None:
        assert not scope_admits(HandlerScope.MAIN, _probe(**{PROBE_AS_FIELD: value}))

    def test_probe_as_on_real_traffic_changes_nothing(self) -> None:
        """Only a synthetic event consults it; a real event is judged as today."""
        assert not scope_admits(HandlerScope.MAIN, {**_subagent(), PROBE_AS_FIELD: "main"})
        assert scope_admits(HandlerScope.MAIN, {**_main_thread(), PROBE_AS_FIELD: "sub"})


class TestAgentTypeIsNeverConsulted:
    """The disqualified field, pinned in both of its failure directions."""

    def test_an_empty_agent_type_on_a_subagent_still_reads_as_sub(self) -> None:
        """Measured in 4 of 5 real subagent stops. agent_id decides."""
        event = {**_subagent(), "agent_type": ""}
        assert not scope_admits(HandlerScope.MAIN, event)
        assert scope_admits(HandlerScope.SUB, event)

    def test_an_agent_type_on_a_main_thread_stop_still_reads_as_main(self) -> None:
        """A session-wide `--agent` sets it on the MAIN thread, per the contract."""
        event = {**_main_thread(), "agent_type": "general-purpose"}
        assert scope_admits(HandlerScope.MAIN, event)
        assert not scope_admits(HandlerScope.SUB, event)


class TestResolveScope:
    def test_absent_key_uses_the_handler_default(self) -> None:
        assert resolve_scope({}, HandlerScope.MAIN) is HandlerScope.MAIN

    def test_a_bare_yaml_key_parses_to_none_and_uses_the_default(self) -> None:
        """PyYAML turns `scope:` with no value into None, as it does `priority:`."""
        assert resolve_scope({"scope": None}, HandlerScope.ALL) is HandlerScope.ALL

    def test_a_configured_value_overrides_the_default(self) -> None:
        assert resolve_scope({"scope": "SUB"}, HandlerScope.MAIN) is HandlerScope.SUB

    def test_the_value_is_case_insensitive(self) -> None:
        assert resolve_scope({"scope": "main"}, HandlerScope.ALL) is HandlerScope.MAIN

    def test_an_unknown_value_raises_rather_than_falling_back(self) -> None:
        """Falling back would turn a typo into a silently wider scope.

        `scope: MIAN` must not quietly become ALL — that is a guard running
        where its author meant it not to, which is the direction that cannot be
        noticed from the outside.
        """
        with pytest.raises(ValueError, match="MIAN"):
            resolve_scope({"scope": "MIAN"}, HandlerScope.MAIN)
