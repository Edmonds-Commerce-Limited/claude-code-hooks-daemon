"""Plan 00487 Task 1.3 -- the worker-half hooks.

``create_worker_half(api)`` returns an object with ``on_start()`` and
``on_idle(tick)``. ``on_idle`` is asked ONLY at the end of the `decide_once`
cascade, after every built-in family, when the gates its siblings use hold plus
``can_inject`` and no own line pending; plugins are asked in flag order; every
call runs on a budgeted thread; and the in-process fallback behaves the same.
"""

from __future__ import annotations

import io
import json
import stat
import time
from typing import TYPE_CHECKING, Any

import pytest

from tests.unit.supervise._load import load_supervisor_module
from tests.unit.supervise._plugin_helpers import (
    GOOD_BODY,
    NOW,
    OWN_SESSION,
    idle_facts,
    make_runtime,
)

if TYPE_CHECKING:
    from pathlib import Path

_mod = load_supervisor_module()

# Records that the hook ran by appending the plugin's name to a shared file.
_RECORDING_BODY = """
    def on_start(self):
        pass
    def on_idle(self, tick):
        with open(self.api.state_dir.parent / "order.log", "a") as handle:
            handle.write("@NAME@\\n")
        return None
"""


def _recording(name: str) -> str:
    return _RECORDING_BODY.replace("@NAME@", name)


def _order(tmp_path: Path) -> list[str]:
    path = tmp_path / "state" / "order.log"
    return path.read_text().split() if path.exists() else []


def _sidecar_dir(tmp_path: Path) -> Path:
    path = tmp_path / "untracked" / "context-sidecar"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _decide(
    tmp_path: Path,
    runtime: Any,
    *,
    machine: Any = None,
    facts: Any = None,
    dry_run: bool = False,
) -> Any:
    policy = _mod.CompactPolicy()
    machine = machine or _mod.CompactStateMachine(policy)
    return _mod.decide_once(
        machine,
        sidecar_dir=_sidecar_dir(tmp_path),
        facts=facts or idle_facts(),
        dry_run=dry_run,
        freshness_seconds=policy.freshness_seconds,
        own_sessions=frozenset({OWN_SESSION}),
        plugins=runtime,
    )


# -- the api handed to the factory -------------------------------------------


class TestPluginApi:
    def test_session_id_is_the_one_own_session(self, tmp_path: Path) -> None:
        runtime = make_runtime(tmp_path, {"p": GOOD_BODY})
        assert runtime.half("p").api.session_id() == OWN_SESSION

    @pytest.mark.parametrize("sessions", [frozenset(), frozenset({"a", "b"})])
    def test_session_id_is_none_unless_there_is_exactly_one(
        self, tmp_path: Path, sessions: frozenset[str]
    ) -> None:
        runtime = make_runtime(tmp_path, {"p": GOOD_BODY}, sessions=sessions)
        assert runtime.half("p").api.session_id() is None

    def test_state_dir_is_private_and_per_plugin(self, tmp_path: Path) -> None:
        runtime = make_runtime(tmp_path, {"one": GOOD_BODY, "two": GOOD_BODY})
        one, two = runtime.half("one").api.state_dir, runtime.half("two").api.state_dir
        assert one != two
        assert stat.S_IMODE(one.stat().st_mode) == 0o700

    def test_status_posts_a_prefixed_message_at_the_given_level(self, tmp_path: Path) -> None:
        runtime = make_runtime(tmp_path, {"p": GOOD_BODY})
        runtime.half("p").api.status("restart in 10 minutes", "warning", 20)
        payload = json.loads(
            (tmp_path / "untracked" / "supervise" / "status-message.json").read_text()
        )
        assert payload["text"] == "[p] restart in 10 minutes"
        assert payload["level"] == "warning"

    def test_status_text_is_one_clean_bounded_line(self, tmp_path: Path) -> None:
        runtime = make_runtime(tmp_path, {"p": GOOD_BODY})
        runtime.half("p").api.status("a\nb\x1b[31mred" + "x" * 500, "bogus-level", 9999)
        payload = json.loads(
            (tmp_path / "untracked" / "supervise" / "status-message.json").read_text()
        )
        assert "\n" not in payload["text"]
        assert "\x1b" not in payload["text"]
        assert len(payload["text"]) < 260
        assert payload["level"] == "info"
        assert payload["expires_at"] - time.time() <= _mod._PLUGIN_STATUS_TTL_MAX_SECONDS + 1

    def test_audit_lines_are_collected_prefixed_and_sanitised(self, tmp_path: Path) -> None:
        runtime = make_runtime(tmp_path, {"p": GOOD_BODY})
        runtime.half("p").api.audit("first\nforged line")
        assert runtime.take_audit_lines() == ("plugin p: first forged line",)
        assert runtime.take_audit_lines() == ()

    def test_audit_backlog_is_bounded(self, tmp_path: Path) -> None:
        runtime = make_runtime(tmp_path, {"p": GOOD_BODY})
        for index in range(_mod._PLUGIN_AUDIT_MAX_PENDING + 5):
            runtime.half("p").api.audit(f"m{index}")
        assert len(runtime.take_audit_lines()) == _mod._PLUGIN_AUDIT_MAX_PENDING

    def test_the_api_offers_the_result_type(self, tmp_path: Path) -> None:
        runtime = make_runtime(tmp_path, {"p": GOOD_BODY})
        assert runtime.half("p").api.ExitForRestart("why") == _mod.ExitForRestart("why")


# -- on_start and on_idle -----------------------------------------------------


class TestHooks:
    def test_on_start_runs_once_per_start(self, tmp_path: Path) -> None:
        runtime = make_runtime(tmp_path, {"p": GOOD_BODY})
        assert runtime.half("p").starts == 1

    def test_on_idle_gets_the_tick_with_the_one_session(self, tmp_path: Path) -> None:
        body = """
    def on_start(self):
        pass
    def on_idle(self, tick):
        self.tick = tick
        return None
"""
        runtime = make_runtime(tmp_path, {"p": body})
        runtime.run_idle(NOW)
        assert runtime.half("p").tick == _mod.IdleTick(now=NOW, session_id=OWN_SESSION)

    def test_plugins_are_asked_in_flag_order(self, tmp_path: Path) -> None:
        runtime = make_runtime(tmp_path, {"zeta": _recording("zeta"), "alpha": _recording("alpha")})
        runtime.run_idle(NOW)
        assert _order(tmp_path) == ["zeta", "alpha"]

    def test_an_exit_request_is_validated_and_ends_the_round(self, tmp_path: Path) -> None:
        asks = """
    def on_start(self):
        pass
    def on_idle(self, tick):
        return self.api.ExitForRestart("max age\\nreached")
"""
        runtime = make_runtime(tmp_path, {"asks": asks, "later": _recording("later")})
        request = runtime.run_idle(NOW)
        assert request == _mod.PluginExitRequest(plugin="asks", reason="max age reached")
        assert _order(tmp_path) == []

    def test_none_means_nothing_to_do(self, tmp_path: Path) -> None:
        runtime = make_runtime(tmp_path, {"p": GOOD_BODY})
        assert runtime.run_idle(NOW) is None
        assert runtime.half("p").idles == 1

    def test_a_disabled_plugin_is_not_asked(self, tmp_path: Path) -> None:
        runtime = make_runtime(tmp_path, {"p": _recording("p")})
        runtime.disable("p")
        runtime.run_idle(NOW)
        assert _order(tmp_path) == []
        assert runtime.loaded == []


# -- budgets -----------------------------------------------------------------


class TestBudgets:
    def test_budgets_sit_well_inside_the_host_read_timeout(self) -> None:
        assert _mod._PLUGIN_HOOK_BUDGET_SECONDS <= _mod._PLUGIN_TICK_BUDGET_SECONDS
        assert _mod._PLUGIN_TICK_BUDGET_SECONDS <= _mod._WORKER_READ_TIMEOUT_SECONDS / 2

    def test_a_slow_hook_cannot_hold_the_tick_past_its_budget(self, tmp_path: Path) -> None:
        slow = """
    def on_start(self):
        pass
    def on_idle(self, tick):
        import time
        time.sleep(3)
"""
        runtime = make_runtime(tmp_path, {"slow": slow}, hook_budget=0.1)
        started = time.monotonic()
        runtime.run_idle(NOW)
        assert time.monotonic() - started < 1.0

    def test_the_tick_budget_stops_asking_further_plugins(self, tmp_path: Path) -> None:
        slow = """
    def on_start(self):
        pass
    def on_idle(self, tick):
        import time
        time.sleep(3)
"""
        runtime = make_runtime(
            tmp_path,
            {"first": slow, "second": slow, "third": _recording("third")},
            hook_budget=0.15,
            tick_budget=0.2,
        )
        started = time.monotonic()
        runtime.run_idle(NOW)
        assert time.monotonic() - started < 1.0
        # Running out of tick budget is not a failure: `third` was simply not
        # asked this tick, and is still enabled for the next one.
        assert _order(tmp_path) == []
        assert [name for name, _ in runtime.loaded if name == "third"] == ["third"]


# -- the cascade gate ---------------------------------------------------------


def _write_operator_signal(tmp_path: Path) -> None:
    (_sidecar_dir(tmp_path) / f"{OWN_SESSION}.operator-signal").write_text(
        json.dumps(
            {"session_id": OWN_SESSION, "ts": NOW - 5, "kind": "reboot-warning", "minutes": 5}
        )
    )


def _write_red_sidecar(tmp_path: Path) -> None:
    (_sidecar_dir(tmp_path) / f"{OWN_SESSION}.json").write_text(
        json.dumps(
            {
                "red": True,
                "critical": False,
                "compact_urgent": True,
                "tier": "urgent",
                "pct": 80.0,
                "session_id": OWN_SESSION,
                "ts": NOW,
                "seq": 1,
                "writer_pid": 1,
                "compacting": False,
            }
        )
    )


class TestCascadeGate:
    def test_asked_on_a_quiet_idle_tick(self, tmp_path: Path) -> None:
        runtime = make_runtime(tmp_path, {"p": GOOD_BODY})
        outcome = _decide(tmp_path, runtime)
        assert runtime.half("p").idles == 1
        assert outcome.payload is None
        assert outcome.exit_for_restart is None

    def test_asked_in_dry_run_too(self, tmp_path: Path) -> None:
        runtime = make_runtime(tmp_path, {"p": GOOD_BODY})
        _decide(tmp_path, runtime, dry_run=True)
        assert runtime.half("p").idles == 1

    @pytest.mark.parametrize(
        "facts",
        [
            idle_facts(idle=False),
            idle_facts(input_line_empty=False),
            idle_facts(idle=False, input_line_empty=False),
        ],
    )
    def test_not_asked_unless_the_session_can_be_typed_into(
        self, tmp_path: Path, facts: Any
    ) -> None:
        runtime = make_runtime(tmp_path, {"p": GOOD_BODY})
        _decide(tmp_path, runtime, facts=facts)
        assert runtime.half("p").idles == 0

    def test_not_asked_while_an_own_line_is_pending(self, tmp_path: Path) -> None:
        runtime = make_runtime(tmp_path, {"p": GOOD_BODY})
        machine = _mod.CompactStateMachine(_mod.CompactPolicy())
        machine.mark_own_line_typed("/goal something", NOW)
        _decide(tmp_path, runtime, machine=machine)
        assert runtime.half("p").idles == 0

    def test_not_asked_on_a_tick_a_builtin_family_claimed(self, tmp_path: Path) -> None:
        runtime = make_runtime(tmp_path, {"p": GOOD_BODY})
        _write_operator_signal(tmp_path)
        outcome = _decide(tmp_path, runtime)
        assert outcome.decision_value == _mod.Decision.WOULD_OPERATOR_SIGNAL.value
        assert runtime.half("p").idles == 0

    def test_not_asked_on_a_compact_tick(self, tmp_path: Path) -> None:
        runtime = make_runtime(tmp_path, {"p": GOOD_BODY})
        _write_red_sidecar(tmp_path)
        outcome = _decide(tmp_path, runtime)
        assert outcome.decision_value == _mod.Decision.WOULD_COMPACT.value
        assert runtime.half("p").idles == 0

    def test_not_asked_while_a_compaction_signal_is_pending(self, tmp_path: Path) -> None:
        runtime = make_runtime(tmp_path, {"p": GOOD_BODY})
        (_sidecar_dir(tmp_path) / f"{OWN_SESSION}.compacting").write_text(
            json.dumps({"session_id": OWN_SESSION, "ts": NOW - 1})
        )
        _decide(tmp_path, runtime)
        assert runtime.half("p").idles == 0

    def test_not_asked_while_the_machine_is_awaiting_compaction(self, tmp_path: Path) -> None:
        runtime = make_runtime(tmp_path, {"p": GOOD_BODY})
        machine = _mod.CompactStateMachine(_mod.CompactPolicy())
        machine.import_state({"state": _mod.SupervisorState.AWAIT_COMPACTING.value})
        _decide(tmp_path, runtime, machine=machine)
        assert runtime.half("p").idles == 0

    def test_not_asked_after_a_session_actions_directive_claimed_the_tick(
        self, tmp_path: Path
    ) -> None:
        runtime = make_runtime(tmp_path, {"p": GOOD_BODY})
        (_sidecar_dir(tmp_path) / f"{OWN_SESSION}.session-actions").write_text(
            json.dumps({"session_id": OWN_SESSION, "ts": NOW - 5, "count": 2})
        )
        outcome = _decide(tmp_path, runtime)
        assert outcome.decision_value == _mod.Decision.WOULD_SESSION_ACTIONS.value
        assert runtime.half("p").idles == 0

    def test_an_exit_request_reaches_the_outcome_without_a_payload(self, tmp_path: Path) -> None:
        asks = """
    def on_start(self):
        pass
    def on_idle(self, tick):
        return self.api.ExitForRestart("max age")
"""
        runtime = make_runtime(tmp_path, {"asks": asks})
        outcome = _decide(tmp_path, runtime)
        assert outcome.exit_for_restart == ("asks", "max age")
        assert outcome.payload is None
        assert outcome.decision_value == _mod.Decision.NOOP.value

    def test_no_runtime_changes_nothing(self, tmp_path: Path) -> None:
        outcome = _decide(tmp_path, None)
        assert outcome.exit_for_restart is None
        assert outcome.plugin_failures == ()


class TestOutcomeCarriesPluginData:
    def test_versions_and_audit_lines_ride_the_outcome(self, tmp_path: Path) -> None:
        body = """
    def on_start(self):
        pass
    def on_idle(self, tick):
        self.api.audit("armed")
"""
        runtime = make_runtime(tmp_path, {"p": body})
        outcome = _decide(tmp_path, runtime)
        assert outcome.plugin_versions == (("p", "1.2.3"),)
        assert outcome.plugin_log_lines == ("plugin p: armed",)


# -- the wire format ----------------------------------------------------------


class TestOutcomeCodec:
    def test_new_fields_round_trip(self) -> None:
        outcome = _mod.TickOutcome(
            decision_value="noop",
            reason="r",
            payload=None,
            submit=True,
            consume_signal_path=None,
            deferred_log=None,
            plugin_failures=(
                ("a", "exception", "on_idle", ""),
                ("b", "load", "load", "api-mismatch"),
            ),
            plugin_versions=(("a", "1.0"),),
            plugin_log_lines=("plugin a: hi",),
            exit_for_restart=("a", "max age"),
        )
        assert _mod._outcome_from_json(_mod._outcome_to_json(outcome)) == outcome

    def test_legacy_json_decodes_with_empty_defaults(self) -> None:
        line = json.dumps(
            {
                "decision_value": "noop",
                "reason": "r",
                "payload": None,
                "submit": True,
                "consume_signal_path": None,
                "deferred_log": None,
            }
        )
        outcome = _mod._outcome_from_json(line)
        assert outcome.plugin_failures == ()
        assert outcome.plugin_versions == ()
        assert outcome.plugin_log_lines == ()
        assert outcome.exit_for_restart is None

    def test_malformed_plugin_fields_are_dropped_not_trusted(self) -> None:
        line = json.dumps(
            {
                "decision_value": "noop",
                "reason": "r",
                "payload": None,
                "submit": True,
                "consume_signal_path": None,
                "deferred_log": None,
                "plugin_failures": [["a", "exception"], "junk", ["b", 1, 2, 3]],
                "plugin_versions": [["a"]],
                "plugin_log_lines": [1, "ok"],
                "exit_for_restart": ["only-one"],
            }
        )
        outcome = _mod._outcome_from_json(line)
        assert outcome.plugin_failures == ()
        assert outcome.plugin_versions == ()
        assert outcome.plugin_log_lines == ("ok",)
        assert outcome.exit_for_restart is None


# -- run_worker and the in-process fallback -----------------------------------


class TestWorkerAndFallback:
    def test_run_worker_starts_plugins_once_and_asks_them_each_tick(self, tmp_path: Path) -> None:
        runtime = make_runtime(tmp_path, {"p": GOOD_BODY})
        sidecar_dir = _sidecar_dir(tmp_path)
        lines = "".join(_mod._facts_to_json(idle_facts()) + "\n" for _ in range(3))
        out = io.StringIO()
        # make_runtime already started the plugin; run_worker starts it again,
        # which is the "once per worker start" the hot-reload contract describes.
        _mod.run_worker(
            io.StringIO(lines),
            out,
            dry_run=False,
            sidecar_dir=sidecar_dir,
            policy=_mod.CompactPolicy(),
            plugins=runtime,
        )
        assert runtime.half("p").starts == 2
        assert runtime.half("p").idles == 3
        assert len(out.getvalue().splitlines()) == 3

    def test_the_in_process_poll_asks_plugins_the_same_way(self, tmp_path: Path) -> None:
        runtime = make_runtime(tmp_path, {"p": GOOD_BODY})
        machine = _mod.CompactStateMachine(_mod.CompactPolicy())
        written: list[bytes] = []
        _mod._poll_once(
            machine,
            sidecar_dir=_sidecar_dir(tmp_path),
            now_wall=NOW,
            idle=True,
            dry_run=False,
            master_writer=written.append,
            log=None,
            freshness_seconds=30.0,
            own_sessions=frozenset({OWN_SESSION}),
            plugins=runtime,
        )
        assert runtime.half("p").idles == 1
        assert written == []

    def test_the_in_process_poll_honours_the_same_gate(self, tmp_path: Path) -> None:
        runtime = make_runtime(tmp_path, {"p": GOOD_BODY})
        machine = _mod.CompactStateMachine(_mod.CompactPolicy())
        _mod._poll_once(
            machine,
            sidecar_dir=_sidecar_dir(tmp_path),
            now_wall=NOW,
            idle=True,
            dry_run=False,
            master_writer=lambda data: None,
            log=None,
            freshness_seconds=30.0,
            input_line_empty=False,
            own_sessions=frozenset({OWN_SESSION}),
            plugins=runtime,
        )
        assert runtime.half("p").idles == 0

    def test_the_in_process_poll_hands_the_outcome_to_its_callback(self, tmp_path: Path) -> None:
        asks = """
    def on_start(self):
        pass
    def on_idle(self, tick):
        return self.api.ExitForRestart("max age")
"""
        runtime = make_runtime(tmp_path, {"asks": asks})
        machine = _mod.CompactStateMachine(_mod.CompactPolicy())
        seen: list[Any] = []
        _mod._poll_once(
            machine,
            sidecar_dir=_sidecar_dir(tmp_path),
            now_wall=NOW,
            idle=True,
            dry_run=False,
            master_writer=lambda data: None,
            log=None,
            freshness_seconds=30.0,
            own_sessions=frozenset({OWN_SESSION}),
            plugins=runtime,
            on_outcome=seen.append,
        )
        assert [o.exit_for_restart for o in seen] == [("asks", "max age")]
