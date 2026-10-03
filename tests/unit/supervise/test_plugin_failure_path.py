"""Plan 00487 Task 1.6 -- the uniform plugin failure path and the plugin-notice family.

A plugin must never block the supervisor or the session. Every failure --
a load refusal, an exception, an overrun, a wedged worker, a result the
supervisor does not accept -- takes the same four steps: detect, disable for
the rest of the supervisor process (``--disable-plugin`` rides on every worker
start), recover whatever it affected, and tell the session once, with a notice
rendered from FIXED templates (a validated name plus closed-set values, never
plugin or exception text), typed only at an idle point and capped per process.
"""

from __future__ import annotations

import json
import os
import time
from typing import TYPE_CHECKING, Any

import pytest

from tests.unit.supervise._load import SCRIPT_PATH, load_supervisor_module
from tests.unit.supervise._plugin_helpers import (
    GOOD_BODY,
    NOW,
    OWN_SESSION,
    idle_facts,
    make_runtime,
    spec,
    write_plugin,
)

if TYPE_CHECKING:
    from pathlib import Path

_mod = load_supervisor_module()
_OWN_UIDS = frozenset({os.getuid(), 0})
_SECRET = "SECRET-TOKEN-123"

_RAISING_BODY = f"""
    def on_start(self):
        pass
    def on_idle(self, tick):
        raise ValueError("{_SECRET}")
"""
_BAD_RESULT_BODY = """
    def on_start(self):
        pass
    def on_idle(self, tick):
        return 42
"""
_SLOW_BODY = """
    def on_start(self):
        pass
    def on_idle(self, tick):
        import time
        time.sleep(30)
"""
_START_RAISES_BODY = f"""
    def on_start(self):
        raise RuntimeError("{_SECRET}")
    def on_idle(self, tick):
        return None
"""
_STOPS_THE_WORKER_BODY = """
    def on_start(self):
        pass
    def on_idle(self, tick):
        import os, signal
        os.kill(os.getpid(), signal.SIGSTOP)
"""


def _sidecar_dir(tmp_path: Path) -> Path:
    path = tmp_path / "untracked" / "context-sidecar"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _decide(
    tmp_path: Path,
    runtime: Any,
    machine: Any,
    *,
    facts: Any = None,
    dry_run: bool = False,
) -> Any:
    policy = _mod.CompactPolicy()
    return _mod.decide_once(
        machine,
        sidecar_dir=_sidecar_dir(tmp_path),
        facts=facts or idle_facts(),
        dry_run=dry_run,
        freshness_seconds=policy.freshness_seconds,
        own_sessions=frozenset({OWN_SESSION}),
        plugins=runtime,
    )


def _machine() -> Any:
    return _mod.CompactStateMachine(_mod.CompactPolicy())


def _tick(tmp_path: Path, runtime: Any, machine: Any, **kwargs: Any) -> Any:
    """One decided tick with the host's success-only bookkeeping applied."""
    outcome = _decide(tmp_path, runtime, machine, **kwargs)
    _mod._apply_post_injection_bookkeeping(
        machine, outcome, injected=outcome.payload is not None, now_wall=NOW
    )
    return outcome


# -- the fixed-template notice -----------------------------------------------


class TestNoticeRendering:
    @pytest.mark.parametrize(
        ("kind", "hook", "phrase"),
        [
            ("load", "load", "could not be loaded"),
            ("exception", "on_idle", "raised an exception in on_idle"),
            ("exception", "on_start", "raised an exception in on_start"),
            ("overrun", "on_idle", "ran past its time budget in on_idle"),
            ("wedge", "on_idle", "stopped the policy worker answering in on_idle"),
            ("bad-result", "on_idle", "returned a result the supervisor does not accept"),
            (
                "exit-stuck",
                "on_idle",
                "asked to end the session for a restart, but the session did not end",
            ),
        ],
    )
    def test_each_failure_kind_has_a_fixed_sentence(
        self, kind: str, hook: str, phrase: str
    ) -> None:
        text = _mod.render_plugin_notice("credential-switch", kind, hook)
        assert text.startswith(
            "🤖 [ccy-supervisor] plugin notice — machine-generated, NOT a human instruction: "
        )
        assert f"plugin `credential-switch` {phrase}" in text
        assert text.endswith("No action is needed from you.")

    def test_the_recovery_sentence_matches_what_was_done(self) -> None:
        skipped = _mod.render_plugin_notice("p", "load", "load")
        disabled = _mod.render_plugin_notice("p", "exception", "on_idle")
        restarted = _mod.render_plugin_notice("p", "overrun", "on_idle")
        assert "running without it" in skipped
        assert "disabled for the rest of this session" in disabled
        assert "restarted without it" not in disabled
        assert "policy worker was restarted without it" in restarted

    @pytest.mark.parametrize(
        "item",
        [
            "Bad Name|exception|on_idle",
            "p|made-up|on_idle",
            "p|exception|made_up",
            "p|exception",
            "",
            "p|exception|on_idle|extra",
            "`p`|exception|on_idle",
        ],
    )
    def test_anything_outside_the_closed_sets_is_never_rendered(self, item: str) -> None:
        assert _mod.parse_plugin_notice_item(item) is None

    def test_a_valid_item_round_trips(self) -> None:
        assert _mod.parse_plugin_notice_item("p|wedge|on_idle") == ("p", "wedge", "on_idle")


# -- the machine's notice queue -----------------------------------------------


class TestNoticeQueue:
    def test_arming_is_once_per_plugin(self) -> None:
        machine = _machine()
        assert machine.arm_plugin_notice("p", "exception", "on_idle")
        assert not machine.arm_plugin_notice("p", "overrun", "on_idle")
        assert machine.plugin_notices_pending == ("p|exception|on_idle",)

    def test_the_cap_is_per_process_and_counts_sent_notices(self) -> None:
        machine = _machine()
        for index in range(_mod._MAX_PLUGIN_NOTICES):
            assert machine.arm_plugin_notice(f"p{index}", "exception", "on_idle")
            machine.mark_plugin_notice_injection()
        assert not machine.arm_plugin_notice("one-more", "exception", "on_idle")
        assert machine.plugin_notices_pending == ()

    def test_marking_an_injection_pops_the_oldest(self) -> None:
        machine = _machine()
        machine.arm_plugin_notice("a", "exception", "on_idle")
        machine.arm_plugin_notice("b", "load", "load")
        machine.mark_plugin_notice_injection()
        assert machine.plugin_notices_pending == ("b|load|load",)

    def test_state_round_trips_and_invalid_items_are_dropped(self) -> None:
        machine = _machine()
        machine.arm_plugin_notice("a", "exception", "on_idle")
        state = machine.export_state()
        other = _machine()
        other.import_state(state)
        assert other.plugin_notices_pending == ("a|exception|on_idle",)
        other.import_state({"plugin_notices_pending": ["a|exception|on_idle", "junk", 7]})
        assert other.plugin_notices_pending == ("a|exception|on_idle",)
        assert not other.arm_plugin_notice("a", "load", "load")

    def test_a_peer_that_predates_the_keys_leaves_the_queue_alone(self) -> None:
        machine = _machine()
        machine.arm_plugin_notice("a", "exception", "on_idle")
        machine.import_state({"state": "monitor"})
        assert machine.plugin_notices_pending == ("a|exception|on_idle",)


# -- worker-side detection ----------------------------------------------------


def _failure_kinds(runtime: Any) -> list[tuple[str, str, str]]:
    return [(f.plugin, f.kind, f.hook) for f in runtime.failures]


class TestDetection:
    def test_a_raising_hook_is_disabled_and_not_asked_again(self, tmp_path: Path) -> None:
        runtime = make_runtime(tmp_path, {"p": _RAISING_BODY})
        runtime.run_idle(NOW)
        assert _failure_kinds(runtime) == [("p", "exception", "on_idle")]
        assert runtime.loaded == []
        runtime.run_idle(NOW)
        assert len(runtime.failures) == 1

    def test_a_raising_on_start_is_a_failure_in_on_start(self, tmp_path: Path) -> None:
        runtime = make_runtime(tmp_path, {"p": _START_RAISES_BODY})
        assert _failure_kinds(runtime) == [("p", "exception", "on_start")]

    def test_an_overrun_is_detected_and_the_plugin_is_disabled(self, tmp_path: Path) -> None:
        runtime = make_runtime(tmp_path, {"p": _SLOW_BODY}, hook_budget=0.1)
        runtime.run_idle(NOW)
        assert _failure_kinds(runtime) == [("p", "overrun", "on_idle")]

    def test_an_unacceptable_result_is_a_failure(self, tmp_path: Path) -> None:
        runtime = make_runtime(tmp_path, {"p": _BAD_RESULT_BODY})
        runtime.run_idle(NOW)
        assert _failure_kinds(runtime) == [("p", "bad-result", "on_idle")]

    def test_a_failing_plugin_does_not_stop_the_next_one(self, tmp_path: Path) -> None:
        runtime = make_runtime(tmp_path, {"bad": _RAISING_BODY, "good": GOOD_BODY})
        runtime.run_idle(NOW)
        assert runtime.half("good").idles == 1

    def test_the_in_hook_marker_is_gone_after_a_normal_call(self, tmp_path: Path) -> None:
        runtime = make_runtime(tmp_path, {"p": GOOD_BODY})
        runtime.run_idle(NOW)
        assert not (tmp_path / "untracked" / "supervise" / "plugin-in-hook.json").exists()

    def test_the_in_hook_marker_names_the_plugin_while_a_hook_runs(self, tmp_path: Path) -> None:
        marker = tmp_path / "untracked" / "supervise" / "plugin-in-hook.json"
        body = f"""
    def on_start(self):
        pass
    def on_idle(self, tick):
        import json
        self.seen = json.loads(open({str(marker)!r}).read())
"""
        runtime = make_runtime(tmp_path, {"p": body})
        runtime.run_idle(NOW)
        assert runtime.half("p").seen["plugin"] == "p"
        assert runtime.half("p").seen["hook"] == "on_idle"


# -- the notice is typed once, at an idle point -------------------------------


class TestNoticeTyping:
    def test_a_raising_plugin_gets_exactly_one_notice_at_the_next_idle_tick(
        self, tmp_path: Path
    ) -> None:
        runtime = make_runtime(tmp_path, {"p": _RAISING_BODY})
        machine = _machine()
        payloads = [_tick(tmp_path, runtime, machine).payload for _ in range(5)]
        typed = [p for p in payloads if p is not None]
        assert len(typed) == 1
        assert payloads[0] is None  # the failure tick itself types nothing
        assert typed[0] == _mod.render_plugin_notice("p", "exception", "on_idle")

    def test_the_typed_decision_is_the_plugin_notice_family(self, tmp_path: Path) -> None:
        runtime = make_runtime(tmp_path, {"p": _RAISING_BODY})
        machine = _machine()
        _tick(tmp_path, runtime, machine)
        outcome = _tick(tmp_path, runtime, machine)
        assert outcome.decision_value == _mod.Decision.WOULD_PLUGIN_NOTICE.value

    def test_the_notice_carries_no_plugin_or_exception_text(self, tmp_path: Path) -> None:
        runtime = make_runtime(tmp_path, {"p": _RAISING_BODY})
        machine = _machine()
        outcomes = [_tick(tmp_path, runtime, machine) for _ in range(3)]
        for outcome in outcomes:
            assert _SECRET not in _mod._outcome_to_json(outcome)
        status = tmp_path / "untracked" / "supervise" / "status-message.json"
        assert _SECRET not in status.read_text()

    def test_a_status_line_warning_is_posted_when_the_failure_is_observed(
        self, tmp_path: Path
    ) -> None:
        runtime = make_runtime(tmp_path, {"p": _RAISING_BODY})
        _tick(tmp_path, runtime, _machine())
        payload = json.loads(
            (tmp_path / "untracked" / "supervise" / "status-message.json").read_text()
        )
        assert payload["level"] == "warning"
        assert "p" in payload["text"]
        assert "raised an exception" in payload["text"]

    def test_dry_run_types_a_marked_demonstration_instead(self, tmp_path: Path) -> None:
        runtime = make_runtime(tmp_path, {"p": _RAISING_BODY})
        machine = _machine()
        _tick(tmp_path, runtime, machine, dry_run=True)
        outcome = _tick(tmp_path, runtime, machine, dry_run=True)
        assert outcome.payload is not None
        assert "dry-run" in outcome.payload
        assert _mod.render_plugin_notice("p", "exception", "on_idle") in outcome.payload

    @pytest.mark.parametrize(
        "facts",
        [idle_facts(input_line_empty=False), idle_facts(idle=False)],
    )
    def test_never_typed_into_a_non_empty_box_or_a_busy_session(
        self, tmp_path: Path, facts: Any
    ) -> None:
        runtime = make_runtime(tmp_path, {"p": _RAISING_BODY})
        machine = _machine()
        _tick(tmp_path, runtime, machine)
        assert _tick(tmp_path, runtime, machine, facts=facts).payload is None
        assert machine.plugin_notices_pending  # still owed

    def test_not_typed_over_a_pending_own_line(self, tmp_path: Path) -> None:
        runtime = make_runtime(tmp_path, {"p": _RAISING_BODY})
        machine = _machine()
        _tick(tmp_path, runtime, machine)
        machine.mark_own_line_typed("/goal x", NOW)
        assert _tick(tmp_path, runtime, machine).payload is None

    def test_ranked_with_the_operator_signal_ahead_of_a_model_switch(self, tmp_path: Path) -> None:
        runtime = make_runtime(tmp_path, {"p": _RAISING_BODY})
        machine = _machine()
        _tick(tmp_path, runtime, machine)
        sidecars = _sidecar_dir(tmp_path)
        (sidecars / f"{OWN_SESSION}.model-switch-intent").write_text(
            json.dumps({"session_id": OWN_SESSION, "ts": NOW - 5, "family": "opus"})
        )
        outcome = _tick(tmp_path, runtime, machine)
        assert outcome.decision_value == _mod.Decision.WOULD_PLUGIN_NOTICE.value

    def test_the_operator_signal_is_typed_first_when_both_are_pending(self, tmp_path: Path) -> None:
        runtime = make_runtime(tmp_path, {"p": _RAISING_BODY})
        machine = _machine()
        _tick(tmp_path, runtime, machine)
        (_sidecar_dir(tmp_path) / f"{OWN_SESSION}.operator-signal").write_text(
            json.dumps(
                {"session_id": OWN_SESSION, "ts": NOW - 5, "kind": "reboot-warning", "minutes": 5}
            )
        )
        first = _tick(tmp_path, runtime, machine)
        assert first.decision_value == _mod.Decision.WOULD_OPERATOR_SIGNAL.value

    def test_not_typed_while_a_compaction_is_in_flight(self, tmp_path: Path) -> None:
        runtime = make_runtime(tmp_path, {"p": _RAISING_BODY})
        machine = _machine()
        _tick(tmp_path, runtime, machine)
        (_sidecar_dir(tmp_path) / f"{OWN_SESSION}.compacting").write_text(
            json.dumps({"session_id": OWN_SESSION, "ts": NOW - 1})
        )
        outcome = _tick(tmp_path, runtime, machine)
        # The compaction's own resume wins the tick; the notice stays owed.
        assert outcome.decision_value == _mod.Decision.WOULD_CONTINUE.value
        assert "plugin notice" not in outcome.payload
        assert machine.plugin_notices_pending

    def test_a_load_failure_is_told_to_the_session_too(self, tmp_path: Path) -> None:
        plugin_dir = tmp_path / "plugins"
        path = write_plugin(plugin_dir, "p", api=9)
        runtime = _mod.PluginRuntime(
            state_root=tmp_path / "state",
            status_dir=tmp_path / "untracked",
            marker_path=tmp_path / "marker.json",
            session_ids=lambda: frozenset({OWN_SESSION}),
            allowed_uids=_OWN_UIDS,
        )
        runtime.load([("p", path)], frozenset())
        machine = _machine()
        _tick(tmp_path, runtime, machine)
        outcome = _tick(tmp_path, runtime, machine)
        assert outcome.payload == _mod.render_plugin_notice("p", "load", "load")

    def test_a_failure_the_host_lost_is_re_armed_from_the_cumulative_report(
        self, tmp_path: Path
    ) -> None:
        # The host discards a reply that arrives after its read timeout, taking
        # the armed notice with it. The worker re-reports every failure every
        # tick, so the notice is armed again by the next one.
        runtime = make_runtime(tmp_path, {"p": _RAISING_BODY})
        _tick(tmp_path, runtime, _machine())
        fresh_host_machine = _machine()
        _tick(tmp_path, runtime, fresh_host_machine)  # re-armed at the end of this tick
        outcome = _tick(tmp_path, runtime, fresh_host_machine)
        assert outcome.decision_value == _mod.Decision.WOULD_PLUGIN_NOTICE.value


# -- host-side handling ---------------------------------------------------------


class _Recorder:
    def __init__(self) -> None:
        self.restarts = 0

    def restart(self) -> bool:
        self.restarts += 1
        return True


def _host_for(tmp_path: Path, names: list[str]) -> Any:
    specs = [spec(name, write_plugin(tmp_path / "plugins", name)) for name in names]
    return _mod.PluginHost(
        specs,
        write_status=lambda entries: None,
        allowed_uids=_OWN_UIDS,
        state_root=tmp_path / "state",
        status_dir=tmp_path / "untracked",
        marker_path=tmp_path / "untracked" / "supervise" / "marker.json",
    )


def _outcome(**fields: Any) -> Any:
    return _mod.TickOutcome(
        decision_value="noop",
        reason="r",
        payload=None,
        submit=True,
        consume_signal_path=None,
        deferred_log=None,
        **fields,
    )


def _handle(tmp_path: Path, host: Any, outcome: Any, recorder: _Recorder, log: Any = None) -> None:
    _mod.handle_plugin_outcome(
        outcome,
        machine=_machine(),
        restart=_mod.RestartCoordinator(state_path=tmp_path / "restart.json"),
        write_master=lambda data: None,
        log=log,
        dry_run=False,
        session_ids=frozenset({OWN_SESSION}),
        plugin_host=host,
        restart_worker=recorder.restart,
    )


class TestHostHandling:
    def test_an_exception_disables_the_plugin_without_restarting_the_worker(
        self, tmp_path: Path
    ) -> None:
        host, recorder = _host_for(tmp_path, ["p"]), _Recorder()
        log = _mod.DecisionLog(tmp_path / "decision.log")
        _handle(
            tmp_path,
            host,
            _outcome(plugin_failures=(("p", "exception", "on_idle", ""),)),
            recorder,
            log,
        )
        assert recorder.restarts == 0
        assert host.status_entries()[0]["state"] == "disabled"
        assert "--disable-plugin" in host.worker_argv()
        assert (
            "plugin p: exception in on_idle -> disabled" in (tmp_path / "decision.log").read_text()
        )

    @pytest.mark.parametrize("kind", ["overrun", "wedge"])
    def test_an_overrun_or_wedge_restarts_the_worker_without_the_plugin(
        self, tmp_path: Path, kind: str
    ) -> None:
        host, recorder = _host_for(tmp_path, ["p"]), _Recorder()
        _handle(tmp_path, host, _outcome(plugin_failures=(("p", kind, "on_idle", ""),)), recorder)
        assert recorder.restarts == 1
        assert host.worker_argv()[-2:] == ["--disable-plugin", "p"]

    def test_the_cumulative_report_is_handled_once(self, tmp_path: Path) -> None:
        host, recorder = _host_for(tmp_path, ["p"]), _Recorder()
        log = _mod.DecisionLog(tmp_path / "decision.log")
        outcome = _outcome(plugin_failures=(("p", "overrun", "on_idle", ""),))
        for _ in range(3):
            _handle(tmp_path, host, outcome, recorder, log)
        assert recorder.restarts == 1
        assert (tmp_path / "decision.log").read_text().count("overrun in on_idle") == 1

    def test_words_outside_the_closed_sets_are_ignored(self, tmp_path: Path) -> None:
        host, recorder = _host_for(tmp_path, ["p"]), _Recorder()
        _handle(
            tmp_path, host, _outcome(plugin_failures=(("p", "made-up", "on_idle", ""),)), recorder
        )
        _handle(
            tmp_path, host, _outcome(plugin_failures=(("p", "exception", "made_up", ""),)), recorder
        )
        assert host.status_entries()[0]["state"] == "loaded"

    def test_a_failure_for_an_unknown_plugin_changes_nothing(self, tmp_path: Path) -> None:
        host, recorder = _host_for(tmp_path, ["p"]), _Recorder()
        _handle(
            tmp_path,
            host,
            _outcome(plugin_failures=(("ghost", "overrun", "on_idle", ""),)),
            recorder,
        )
        assert recorder.restarts == 0

    def test_a_confirmed_load_records_the_version(self, tmp_path: Path) -> None:
        host, recorder = _host_for(tmp_path, ["p"]), _Recorder()
        _handle(tmp_path, host, _outcome(plugin_versions=(("p", "4.5.6"),)), recorder)
        assert host.status_entries()[0]["version"] == "4.5.6"


# -- a wedged worker ------------------------------------------------------------


def _write_marker(host_marker: Path, **fields: Any) -> None:
    payload = {"plugin": "p", "hook": "on_idle", "started_at": NOW - 10.0}
    payload.update(fields)
    host_marker.parent.mkdir(parents=True, exist_ok=True)
    host_marker.write_text(json.dumps(payload))


class TestWedgeDetection:
    def _marker(self, tmp_path: Path) -> Path:
        return tmp_path / "untracked" / "supervise" / "marker.json"

    def test_an_old_marker_names_the_culprit(self, tmp_path: Path) -> None:
        host = _host_for(tmp_path, ["p"])
        _write_marker(self._marker(tmp_path))
        failure = host.detect_wedge(NOW)
        assert (failure.plugin, failure.kind, failure.hook) == ("p", "wedge", "on_idle")

    def test_a_fresh_marker_is_a_slow_hook_not_a_wedge(self, tmp_path: Path) -> None:
        host = _host_for(tmp_path, ["p"])
        _write_marker(self._marker(tmp_path), started_at=NOW - 0.1)
        assert host.detect_wedge(NOW) is None

    def test_a_load_hook_gets_the_longer_load_budget(self, tmp_path: Path) -> None:
        host = _host_for(tmp_path, ["p"])
        _write_marker(self._marker(tmp_path), hook="load", started_at=NOW - 1.2)
        assert host.detect_wedge(NOW) is None
        _write_marker(self._marker(tmp_path), hook="load", started_at=NOW - 2.0)
        assert host.detect_wedge(NOW) is not None

    @pytest.mark.parametrize(
        "fields",
        [{"plugin": "ghost"}, {"hook": "made_up"}, {"plugin": "Bad Name"}, {"started_at": "x"}],
    )
    def test_a_marker_outside_the_closed_sets_blames_nobody(
        self, tmp_path: Path, fields: dict[str, Any]
    ) -> None:
        host = _host_for(tmp_path, ["p"])
        _write_marker(self._marker(tmp_path), **fields)
        assert host.detect_wedge(NOW) is None

    def test_no_marker_and_a_garbled_marker_blame_nobody(self, tmp_path: Path) -> None:
        host = _host_for(tmp_path, ["p"])
        assert host.detect_wedge(NOW) is None
        self._marker(tmp_path).parent.mkdir(parents=True, exist_ok=True)
        self._marker(tmp_path).write_text("not json")
        assert host.detect_wedge(NOW) is None

    def test_an_already_disabled_plugin_is_not_blamed_again(self, tmp_path: Path) -> None:
        host = _host_for(tmp_path, ["p"])
        host.record_failure("p", "exception", "on_idle")
        _write_marker(self._marker(tmp_path))
        assert host.detect_wedge(NOW) is None

    def test_silence_with_a_culprit_disables_restarts_arms_and_logs(self, tmp_path: Path) -> None:
        host, recorder, machine = _host_for(tmp_path, ["p"]), _Recorder(), _machine()
        _write_marker(self._marker(tmp_path))
        log = _mod.DecisionLog(tmp_path / "decision.log")
        _mod.handle_worker_silence(
            plugin_host=host,
            machine=machine,
            restart_worker=recorder.restart,
            log=log,
            status_dir=tmp_path / "untracked",
            now_wall=NOW,
        )
        assert recorder.restarts == 1
        assert machine.plugin_notices_pending == ("p|wedge|on_idle",)
        assert host.status_entries()[0]["state"] == "disabled"
        assert host.status_entries()[0]["reason"] == "wedge in on_idle"
        assert not self._marker(tmp_path).exists()
        assert "plugin p: wedge in on_idle" in (tmp_path / "decision.log").read_text()

    def test_silence_without_a_culprit_does_nothing(self, tmp_path: Path) -> None:
        host, recorder, machine = _host_for(tmp_path, ["p"]), _Recorder(), _machine()
        _mod.handle_worker_silence(
            plugin_host=host,
            machine=machine,
            restart_worker=recorder.restart,
            log=None,
            status_dir=tmp_path / "untracked",
            now_wall=NOW,
        )
        assert recorder.restarts == 0
        assert machine.plugin_notices_pending == ()


# -- the whole path over a real worker subprocess and PTY ------------------------

_CHILD = r"""
import os, sys, time, select
log = open(sys.argv[1], "ab", buffering=0)
deadline = time.time() + float(sys.argv[2])
while time.time() < deadline:
    ready, _, _ = select.select([0], [], [], 0.05)
    if ready:
        log.write(os.read(0, 4096))
sys.exit(7)
"""


def _live_supervise(
    tmp_path: Path, body: str, *, linger: float
) -> tuple[int, Path, Any, _Recorder]:
    path = write_plugin(tmp_path / "plugins", "culprit", body)
    untracked = tmp_path / "untracked"
    host = _mod.PluginHost(
        [spec("culprit", path)],
        write_status=lambda entries: None,
        allowed_uids=_OWN_UIDS,
        state_root=tmp_path / "ccy-state" / "plugins",
        status_dir=untracked,
        marker_path=_mod._plugin_marker_path(untracked, os.getpid()),
    )
    worker = _mod.PolicyWorker(SCRIPT_PATH, dry_run=False, extra_argv=host.worker_argv)
    assert worker.start()
    restarts = _Recorder()

    def restart_worker() -> bool:
        restarts.restarts += 1
        return bool(worker.restart())

    received = tmp_path / "received.bin"
    stdin_fd = os.open(os.devnull, os.O_RDONLY)
    try:
        code = _mod.supervise(
            [_mod.sys.executable, "-c", _CHILD, str(received), str(linger)],
            dry_run=False,
            log=_mod.DecisionLog(tmp_path / "decision.log"),
            stdin_fd=stdin_fd,
            poll_seconds=0.05,
            sidecar_dir=untracked / "context-sidecar",
            decider=_mod._make_worker_decider(worker),
            plugin_host=host,
            restart_worker=restart_worker,
            restart_coordinator=_mod.RestartCoordinator(state_path=tmp_path / "restart.json"),
        )
    finally:
        os.close(stdin_fd)
        worker.close()
    return int(code), received, host, restarts


class TestLiveFailurePath:
    def test_a_raising_plugin_never_stops_the_session_and_is_told_once(
        self, live_env: Path
    ) -> None:
        code, received, host, restarts = _live_supervise(live_env, _RAISING_BODY, linger=2.0)
        assert code == 7  # the child ran to its own exit
        typed = received.read_bytes().decode()
        assert typed.count("plugin notice") == 1
        assert "plugin `culprit` raised an exception in on_idle" in typed
        assert _SECRET not in typed
        assert _SECRET not in (live_env / "decision.log").read_text()
        assert host.status_entries()[0]["state"] == "disabled"
        assert restarts.restarts == 0

    def test_an_overrunning_plugin_restarts_the_worker_without_it(self, live_env: Path) -> None:
        code, received, host, restarts = _live_supervise(live_env, _SLOW_BODY, linger=3.0)
        assert code == 7
        assert restarts.restarts == 1
        assert "--disable-plugin" in host.worker_argv()
        assert received.read_bytes().decode().count("plugin notice") == 1
        assert "plugin culprit: overrun in on_idle" in (live_env / "decision.log").read_text()

    def test_a_worker_wedged_inside_a_hook_is_restarted_and_the_culprit_named(
        self, live_env: Path
    ) -> None:
        started = time.monotonic()
        code, received, host, restarts = _live_supervise(
            live_env, _STOPS_THE_WORKER_BODY, linger=6.0
        )
        assert code == 7
        assert restarts.restarts == 1
        assert host.status_entries()[0]["reason"] == "wedge in on_idle"
        assert received.read_bytes().decode().count("plugin notice") == 1
        assert time.monotonic() - started < 15


class TestLoadRefusalsReachTheSession:
    def test_a_refused_plugin_is_skipped_and_the_notice_is_typed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            _mod, "cached_own_session_ids", lambda *a, **k: frozenset({OWN_SESSION})
        )
        path = write_plugin(tmp_path / "plugins", "loose")
        path.chmod(0o666)
        host = _mod.PluginHost(
            [spec("loose", path)],
            write_status=lambda entries: None,
            allowed_uids=_OWN_UIDS,
            state_root=tmp_path / "state",
            status_dir=tmp_path / "untracked",
            marker_path=tmp_path / "untracked" / "supervise" / "marker.json",
        )
        received = tmp_path / "received.bin"
        stdin_fd = os.open(os.devnull, os.O_RDONLY)
        try:
            code = _mod.supervise(
                [_mod.sys.executable, "-c", _CHILD, str(received), "1.0"],
                dry_run=False,
                log=_mod.DecisionLog(tmp_path / "decision.log"),
                stdin_fd=stdin_fd,
                poll_seconds=0.05,
                sidecar_dir=tmp_path / "untracked" / "context-sidecar",
                plugin_host=host,
                restart_coordinator=_mod.RestartCoordinator(state_path=tmp_path / "r.json"),
            )
        finally:
            os.close(stdin_fd)
        assert code == 7
        assert received.read_bytes().decode().count("plugin notice") == 1
        assert "plugin `loose` could not be loaded" in received.read_bytes().decode()
        assert (
            "plugin loose: load: group-or-world-writable" in (tmp_path / "decision.log").read_text()
        )


class TestStateDirOverride:
    def test_the_environment_overrides_the_state_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CCY_SUPERVISOR_STATE_DIR", str(tmp_path / "elsewhere"))
        assert _mod._ccy_state_dir() == tmp_path / "elsewhere"
        assert _mod._plugin_state_root() == tmp_path / "elsewhere" / "plugins"
