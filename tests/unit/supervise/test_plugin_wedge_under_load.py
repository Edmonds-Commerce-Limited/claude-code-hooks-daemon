"""Defence for the class "a wall-clock budget judged without regard to host load".

A worker that the kernel has not scheduled for 0.75 s looks exactly like a
worker stuck inside a plugin hook if the only evidence is how old the in-hook
marker is. These tests pin the defence: a wedge needs the SAME marker at two
consecutive checks with no CPU progress by the worker in between, a plugin
disabled for a failure that load can mimic comes back, the notice names the
cause, the log and what is off, and every disable leaves a log record with the
marker's age and the host load.
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING, Any

import pytest

from tests.unit.supervise._load import load_supervisor_module
from tests.unit.supervise._plugin_helpers import NOW, spec, write_plugin

if TYPE_CHECKING:
    from pathlib import Path

_mod = load_supervisor_module()
_OWN_UIDS = frozenset({os.getuid(), 0})


class _Cpu:
    """A controllable stand-in for the worker's CPU time."""

    def __init__(self, value: float | None = 1.0) -> None:
        self.value = value

    def __call__(self) -> float | None:
        return self.value


class _Recorder:
    def __init__(self) -> None:
        self.restarts = 0

    def restart(self) -> bool:
        self.restarts += 1
        return True


def _marker(tmp_path: Path) -> Path:
    return tmp_path / "untracked" / "supervise" / "marker.json"


def _write_marker(tmp_path: Path, **fields: Any) -> None:
    payload = {"plugin": "p", "hook": "on_idle", "started_at": NOW - 10.0}
    payload.update(fields)
    _marker(tmp_path).parent.mkdir(parents=True, exist_ok=True)
    _marker(tmp_path).write_text(json.dumps(payload))


def _host(tmp_path: Path, cpu: _Cpu | None = None, names: tuple[str, ...] = ("p",)) -> Any:
    specs = [spec(n, write_plugin(tmp_path / "plugins", n)) for n in names]
    host = _mod.PluginHost(
        specs,
        write_status=lambda entries: None,
        allowed_uids=_OWN_UIDS,
        status_dir=tmp_path / "untracked",
        marker_path=_marker(tmp_path),
    )
    host.set_worker_cpu_source(cpu if cpu is not None else _Cpu())
    return host


class TestWedgeNeedsTwoStrikesWithoutProgress:
    def test_one_stale_observation_is_not_a_wedge(self, tmp_path: Path) -> None:
        """A descheduled worker shows a stale marker exactly once."""
        host = _host(tmp_path)
        _write_marker(tmp_path)
        assert host.detect_wedge(NOW) is None

    def test_the_same_marker_twice_with_no_cpu_progress_is_a_wedge(self, tmp_path: Path) -> None:
        host = _host(tmp_path)
        _write_marker(tmp_path)
        assert host.detect_wedge(NOW) is None
        failure = host.detect_wedge(NOW + 3.0)
        assert (failure.plugin, failure.kind, failure.hook) == ("p", "wedge", "on_idle")

    def test_cpu_progress_between_checks_means_the_worker_is_alive(self, tmp_path: Path) -> None:
        cpu = _Cpu(1.0)
        host = _host(tmp_path, cpu)
        _write_marker(tmp_path)
        assert host.detect_wedge(NOW) is None
        cpu.value = 1.4
        assert host.detect_wedge(NOW + 3.0) is None

    def test_progress_restarts_the_count(self, tmp_path: Path) -> None:
        cpu = _Cpu(1.0)
        host = _host(tmp_path)
        host.set_worker_cpu_source(cpu)
        _write_marker(tmp_path)
        host.detect_wedge(NOW)
        cpu.value = 2.0
        assert host.detect_wedge(NOW + 3.0) is None
        assert host.detect_wedge(NOW + 6.0) is not None

    def test_a_different_marker_is_a_new_hook_not_a_second_strike(self, tmp_path: Path) -> None:
        host = _host(tmp_path)
        _write_marker(tmp_path, started_at=NOW - 10.0)
        assert host.detect_wedge(NOW) is None
        _write_marker(tmp_path, started_at=NOW + 2.0)
        assert host.detect_wedge(NOW + 13.0) is None

    def test_a_marker_that_cleared_between_checks_resets_the_count(self, tmp_path: Path) -> None:
        """The worker was only descheduled: it finished the hook before the next tick."""
        host = _host(tmp_path)
        _write_marker(tmp_path)
        assert host.detect_wedge(NOW) is None
        _marker(tmp_path).unlink()
        assert host.detect_wedge(NOW + 3.0) is None
        _write_marker(tmp_path)
        assert host.detect_wedge(NOW + 4.0) is None

    def test_an_unreadable_cpu_still_needs_two_strikes(self, tmp_path: Path) -> None:
        host = _host(tmp_path, _Cpu(None))
        _write_marker(tmp_path)
        assert host.detect_wedge(NOW) is None
        assert host.detect_wedge(NOW + 3.0) is not None

    def test_the_strike_count_is_configurable(self, tmp_path: Path) -> None:
        host = _mod.PluginHost(
            [spec("p", write_plugin(tmp_path / "plugins", "p"))],
            allowed_uids=_OWN_UIDS,
            status_dir=tmp_path / "untracked",
            marker_path=_marker(tmp_path),
            wedge_strikes=3,
        )
        _write_marker(tmp_path)
        assert host.detect_wedge(NOW) is None
        assert host.detect_wedge(NOW + 3.0) is None
        assert host.detect_wedge(NOW + 6.0) is not None

    def test_a_loaded_host_never_disables_a_plugin_that_keeps_finishing(
        self, tmp_path: Path
    ) -> None:
        """The field case: every tick the worker is late, every hook still ends."""
        host = _host(tmp_path)
        for tick in range(20):
            _write_marker(tmp_path, started_at=NOW + tick * 3.0 - 0.9)
            assert host.detect_wedge(NOW + tick * 3.0) is None
            _marker(tmp_path).unlink()


class TestDisableIsLogged:
    def test_a_wedge_disable_records_marker_age_and_load(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        log = tmp_path / "worker.err.log"
        monkeypatch.setattr(_mod, "worker_error_log_path", lambda: log)
        monkeypatch.setattr(os, "getloadavg", lambda: (55.5, 60.0, 70.0))
        host = _host(tmp_path)
        assert host.record_failure("p", "wedge", "on_idle", marker_age=10.0) is True
        text = log.read_text()
        assert "plugin p disabled: wedge in on_idle" in text
        assert "marker age 10.00s" in text
        assert "loadavg 55.50 60.00 70.00" in text

    def test_a_disable_without_a_marker_says_so(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        log = tmp_path / "worker.err.log"
        monkeypatch.setattr(_mod, "worker_error_log_path", lambda: log)
        host = _host(tmp_path)
        host.record_failure("p", "exception", "on_idle")
        assert "marker age n/a" in log.read_text()

    def test_an_unavailable_load_average_does_not_stop_the_record(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        log = tmp_path / "worker.err.log"
        monkeypatch.setattr(_mod, "worker_error_log_path", lambda: log)

        def broken() -> tuple[float, float, float]:
            raise OSError("no loadavg")

        monkeypatch.setattr(os, "getloadavg", broken)
        host = _host(tmp_path)
        host.record_failure("p", "overrun", "on_idle")
        assert "loadavg n/a" in log.read_text()

    def test_silence_with_a_wedge_logs_the_marker_age(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        log = tmp_path / "worker.err.log"
        monkeypatch.setattr(_mod, "worker_error_log_path", lambda: log)
        host, recorder = _host(tmp_path), _Recorder()
        _write_marker(tmp_path)
        for now in (NOW, NOW + 3.0):
            _mod.handle_worker_silence(
                plugin_host=host,
                machine=_mod.CompactStateMachine(_mod.CompactPolicy()),
                restart_worker=recorder.restart,
                log=None,
                status_dir=tmp_path / "untracked",
                now_wall=now,
            )
        assert recorder.restarts == 1
        assert "marker age 13.00s" in log.read_text()


class TestDisabledPluginComesBack:
    def test_clean_ticks_re_enable_a_wedged_plugin(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CCY_PLUGIN_REENABLE_CLEAN_TICKS", "3")
        host = _host(tmp_path)
        host.record_failure("p", "wedge", "on_idle")
        assert host.note_clean_tick() == []
        assert host.note_clean_tick() == []
        assert host.note_clean_tick() == ["p"]
        assert host.status_entries()[0]["state"] == "loaded"
        assert "--disable-plugin" not in host.worker_argv()

    def test_the_default_is_a_bounded_positive_count(self) -> None:
        assert _mod._plugin_reenable_clean_ticks() == _mod._PLUGIN_REENABLE_CLEAN_TICKS_DEFAULT
        assert _mod._PLUGIN_REENABLE_CLEAN_TICKS_DEFAULT > 0

    @pytest.mark.parametrize("raw", ["junk", "0", "-4", ""])
    def test_a_bad_override_keeps_the_default(
        self, raw: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CCY_PLUGIN_REENABLE_CLEAN_TICKS", raw)
        assert _mod._plugin_reenable_clean_ticks() == _mod._PLUGIN_REENABLE_CLEAN_TICKS_DEFAULT

    def test_the_restart_that_follows_a_wedge_still_leaves_it_off(self, tmp_path: Path) -> None:
        host = _host(tmp_path)
        host.record_failure("p", "wedge", "on_idle")
        assert host.worker_argv().count("--disable-plugin") == 1

    def test_the_next_worker_restart_brings_it_back(self, tmp_path: Path) -> None:
        host = _host(tmp_path)
        host.record_failure("p", "wedge", "on_idle")
        host.worker_argv()  # the restart the failure itself caused
        argv = host.worker_argv()  # the next restart, e.g. a hot reload
        assert "--disable-plugin" not in argv
        assert host.status_entries()[0]["state"] == "loaded"

    def test_an_exception_needs_no_restart_so_the_next_one_re_enables(self, tmp_path: Path) -> None:
        host = _host(tmp_path)
        host.record_failure("p", "exception", "on_idle")
        assert "--disable-plugin" not in host.worker_argv()

    @pytest.mark.parametrize("kind", ["load", "exit-stuck", "host-fault"])
    def test_kinds_that_load_cannot_explain_stay_off(self, tmp_path: Path, kind: str) -> None:
        host = _host(tmp_path)
        host.record_failure("p", kind, "on_idle")
        host.worker_argv()
        host.worker_argv()
        for _ in range(_mod._PLUGIN_REENABLE_CLEAN_TICKS_DEFAULT + 1):
            assert host.note_clean_tick() == []
        assert host.status_entries()[0]["state"] in ("disabled", "failed")

    def test_a_plugin_the_operator_switched_off_stays_off(self, tmp_path: Path) -> None:
        host = _mod.PluginHost(
            [spec("p", write_plugin(tmp_path / "plugins", "p"))],
            allowed_uids=_OWN_UIDS,
            status_dir=tmp_path / "untracked",
            marker_path=_marker(tmp_path),
            disabled=["p"],
        )
        host.worker_argv()
        host.worker_argv()
        for _ in range(_mod._PLUGIN_REENABLE_CLEAN_TICKS_DEFAULT + 1):
            host.note_clean_tick()
        assert host.status_entries()[0]["state"] == "disabled"

    def test_handle_plugin_outcome_re_enables_restarts_and_logs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CCY_PLUGIN_REENABLE_CLEAN_TICKS", "2")
        host, recorder = _host(tmp_path), _Recorder()
        host.record_failure("p", "overrun", "on_idle")
        log = _mod.DecisionLog(tmp_path / "decision.log")
        clean = _mod.TickOutcome(
            decision_value="noop",
            reason="r",
            payload=None,
            submit=True,
            consume_signal_path=None,
            deferred_log=None,
        )
        for _ in range(2):
            _mod.handle_plugin_outcome(
                clean,
                machine=_mod.CompactStateMachine(_mod.CompactPolicy()),
                restart=_mod.RestartCoordinator(state_path=tmp_path / "restart.json"),
                write_master=lambda data: None,
                log=log,
                dry_run=False,
                session_ids=frozenset(),
                plugin_host=host,
                restart_worker=recorder.restart,
            )
        assert recorder.restarts == 1
        assert "plugin p: re-enabled after 2 clean ticks" in (tmp_path / "decision.log").read_text()


class TestNoticeNamesCauseLogAndWhatIsOff:
    def test_a_wedge_notice_is_not_a_no_action_needed_and_names_the_log(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(_mod, "worker_error_log_path", lambda: tmp_path / "w.err.log")
        text = _mod.render_plugin_notice("ccy-lifecycle", "wedge", "on_idle")
        assert "No action is needed" not in text
        assert str(tmp_path / "w.err.log") in text
        assert "host load" in text
        assert "relaunch on a team join" in text
        assert "max-age restart" in text
        assert "deadline notice" in text

    def test_an_unknown_plugin_gets_the_generic_statement(self) -> None:
        text = _mod.render_plugin_notice("other", "exception", "on_idle")
        assert "everything that plugin provides" in text
        assert "relaunch on a team join" not in text

    @pytest.mark.parametrize("kind", sorted(_mod._PLUGIN_KINDS))
    def test_no_kind_says_no_action_is_needed(self, kind: str) -> None:
        assert "No action is needed" not in _mod.render_plugin_notice("p", kind, "on_idle")

    def test_a_recoverable_notice_states_when_it_comes_back(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CCY_PLUGIN_REENABLE_CLEAN_TICKS", "77")
        text = _mod.render_plugin_notice("p", "wedge", "on_idle")
        assert "next policy-worker restart" in text
        assert "77 clean ticks" in text


class TestWorkerCpuReading:
    def test_reads_this_process(self) -> None:
        value = _mod._process_cpu_seconds(os.getpid())
        assert value is not None
        assert value >= 0.0

    def test_a_missing_process_is_none(self) -> None:
        assert _mod._process_cpu_seconds(2**22 + 12345) is None

    def test_a_worker_that_is_not_started_is_none(self, tmp_path: Path) -> None:
        worker = _mod.PolicyWorker(tmp_path / "x.py", dry_run=True)
        assert worker.cpu_seconds() is None


class TestHarnessKeepsTheRealWorkerLogUntouched:
    def test_a_raising_hook_is_logged_under_work_dir_only(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        live = tmp_path / "live" / "claude-supervise-worker.err.log"
        monkeypatch.setattr(_mod, "worker_error_log_path", lambda: live)
        body = """
    def on_start(self):
        pass
    def on_idle(self, tick):
        raise ValueError("visible to the author")
"""
        path = write_plugin(tmp_path / "p", "raiser", body)
        work = tmp_path / "harness"
        harness = _mod.PluginTestHarness("raiser", path, work_dir=work, allowed_uids=_OWN_UIDS)
        harness.start()
        with pytest.raises(_mod.PluginHarnessError):
            harness.idle()
        assert not live.exists()
        assert not live.parent.exists()
        logged = (work / "claude-supervise-worker.err.log").read_text()
        assert "visible to the author" in logged

    def test_the_redirect_ends_with_the_harness_call(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        live = tmp_path / "live.log"
        monkeypatch.setattr(_mod, "worker_error_log_path", lambda: live)
        path = write_plugin(tmp_path / "p", "ok")
        harness = _mod.PluginTestHarness(
            "ok", path, work_dir=tmp_path / "harness", allowed_uids=_OWN_UIDS
        )
        harness.start()
        harness.idle()
        _mod.append_worker_error("afterwards")
        assert "afterwards" in live.read_text()
