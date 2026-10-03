"""Plan 00487 round-2 review, defect 1 -- a tripped containment switches EVERY plugin off.

The host's plugin handling is contained as a whole: the first unexpected
exception in it stops the host handling plugin results. That alone leaves the
worker running every plugin (a Notify still types into the chat, an exit
request is dropped, and a plugin that then hangs is never disabled, so every
tick stalls the PTY loop for the worker's read timeout). A trip therefore also
disables all plugins through the uniform failure path -- one notice -- and
restarts the worker with no plugin flags at all.
"""

from __future__ import annotations

import os
import time
from typing import TYPE_CHECKING, Any

from tests.unit.supervise._load import SCRIPT_PATH, load_supervisor_module
from tests.unit.supervise._plugin_helpers import spec, write_plugin

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

_mod = load_supervisor_module()
_OWN_UIDS = frozenset({os.getuid(), 0})
_SECOND_IDLE_TICKS = 2


class _Recorder:
    def __init__(self) -> None:
        self.restarts = 0

    def restart(self) -> bool:
        self.restarts += 1
        return True


def _host(tmp_path: Path, names: list[str]) -> Any:
    specs = [spec(name, write_plugin(tmp_path / "plugins", name)) for name in names]
    return _mod.PluginHost(
        specs,
        write_status=lambda entries: None,
        allowed_uids=_OWN_UIDS,
        status_dir=tmp_path / "untracked",
        marker_path=tmp_path / "untracked" / "supervise" / "marker.json",
    )


def _containment(
    tmp_path: Path, host: Any, recorder: _Recorder, machine: Any, log: Any = None
) -> Any:
    return _mod.PluginContainment(
        plugin_host=host,
        machine=machine,
        restart_worker=recorder.restart,
        log=log,
        status_dir=tmp_path / "untracked",
    )


def _boom() -> None:
    raise RuntimeError("boom")


def _machine() -> Any:
    return _mod.CompactStateMachine(_mod.CompactPolicy())


class TestTrip:
    def test_a_step_that_succeeds_runs_and_changes_nothing(self, tmp_path: Path) -> None:
        host, recorder = _host(tmp_path, ["a"]), _Recorder()
        containment = _containment(tmp_path, host, recorder, _machine())
        ran: list[int] = []
        containment.run(lambda: ran.append(1))
        assert ran == [1]
        assert containment.active
        assert recorder.restarts == 0
        assert host.status_entries()[0]["state"] == "loaded"

    def test_a_trip_disables_every_plugin_and_restarts_the_worker_without_flags(
        self, tmp_path: Path
    ) -> None:
        host, recorder = _host(tmp_path, ["a", "b"]), _Recorder()
        containment = _containment(tmp_path, host, recorder, _machine())
        assert "--plugin" in host.worker_argv()
        containment.run(_boom)
        assert not containment.active
        assert [e["state"] for e in host.status_entries()] == ["disabled", "disabled"]
        assert host.worker_argv() == []
        assert recorder.restarts == 1

    def test_a_trip_owes_the_session_exactly_one_notice(self, tmp_path: Path) -> None:
        host, recorder, machine = _host(tmp_path, ["a", "b"]), _Recorder(), _machine()
        containment = _containment(tmp_path, host, recorder, machine)
        containment.run(_boom)
        containment.run(_boom)
        assert machine.plugin_notices_pending == ("a|host-fault|on_idle",)
        rendered = _mod.render_plugin_notice("a", "host-fault", "on_idle")
        assert "every other plugin" in rendered
        assert "boom" not in rendered

    def test_a_trip_is_logged_once_through_the_uniform_audit_line(self, tmp_path: Path) -> None:
        host, recorder = _host(tmp_path, ["a"]), _Recorder()
        log = _mod.DecisionLog(tmp_path / "decision.log")
        containment = _containment(tmp_path, host, recorder, _machine(), log)
        containment.run(_boom)
        containment.run(_boom)
        text = (tmp_path / "decision.log").read_text()
        assert text.count("plugin a: host-fault in on_idle -> disabled") == 1
        assert text.count("plugin handling failed") == 1

    def test_later_steps_are_skipped_after_a_trip(self, tmp_path: Path) -> None:
        host, recorder = _host(tmp_path, ["a"]), _Recorder()
        containment = _containment(tmp_path, host, recorder, _machine())
        containment.run(_boom)
        ran: list[int] = []
        containment.run(lambda: ran.append(1))
        assert ran == []

    def test_a_worker_restart_that_itself_raises_cannot_escape(self, tmp_path: Path) -> None:
        host = _host(tmp_path, ["a"])

        def bad_restart() -> bool:
            raise OSError("cannot spawn")

        containment = _mod.PluginContainment(
            plugin_host=host,
            machine=_machine(),
            restart_worker=bad_restart,
            log=None,
            status_dir=tmp_path / "untracked",
        )
        containment.run(_boom)
        assert host.worker_argv() == []

    def test_a_host_with_no_plugins_trips_quietly(self, tmp_path: Path) -> None:
        recorder, machine = _Recorder(), _machine()
        containment = _mod.PluginContainment(
            plugin_host=None,
            machine=machine,
            restart_worker=recorder.restart,
            log=None,
            status_dir=tmp_path / "untracked",
        )
        containment.run(_boom)
        assert not containment.active
        assert recorder.restarts == 0
        assert machine.plugin_notices_pending == ()

    def test_already_failed_plugins_stay_failed_and_are_not_blamed(self, tmp_path: Path) -> None:
        host, recorder = _host(tmp_path, ["a", "b"]), _Recorder()
        host.record_failure("a", "exception", "on_idle")
        containment = _containment(tmp_path, host, recorder, _machine())
        containment.run(_boom)
        entries = host.status_entries()
        assert entries[0]["reason"] == "exception in on_idle"
        assert entries[1]["reason"] == "host-fault in on_idle"
        assert host.worker_argv() == []


# -- the hang-after-trip scenario, over a real worker subprocess and PTY ----------

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


def _hang_on_second_idle_body(counter: Path) -> str:
    return f"""
    def on_start(self):
        pass
    def on_idle(self, tick):
        import os, signal
        with open({str(counter)!r}, "a") as handle:
            handle.write("x")
        if os.path.getsize({str(counter)!r}) >= {_SECOND_IDLE_TICKS}:
            os.kill(os.getpid(), signal.SIGSTOP)
        return None
"""


class TestHangAfterTrip:
    def test_a_plugin_that_would_hang_after_the_trip_never_runs_again(
        self, live_env: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        counter = live_env / "idle-calls"
        path = write_plugin(live_env / "plugins", "culprit", _hang_on_second_idle_body(counter))
        untracked = live_env / "untracked"
        host = _mod.PluginHost(
            [spec("culprit", path)],
            write_status=lambda entries: None,
            allowed_uids=_OWN_UIDS,
            status_dir=untracked,
            marker_path=_mod._plugin_marker_path(untracked, os.getpid()),
        )
        worker = _mod.PolicyWorker(SCRIPT_PATH, dry_run=False, extra_argv=host.worker_argv)
        assert worker.start()
        restarts = _Recorder()

        def restart_worker() -> bool:
            restarts.restarts += 1
            return bool(worker.restart())

        real_handle = _mod.handle_plugin_outcome
        calls = [0]

        def exploding_handle(*args: Any, **kwargs: Any) -> None:
            calls[0] += 1
            if calls[0] == 1:
                raise RuntimeError("host bug")
            real_handle(*args, **kwargs)

        monkeypatch.setattr(_mod, "handle_plugin_outcome", exploding_handle)
        received = live_env / "received.bin"
        stdin_fd = os.open(os.devnull, os.O_RDONLY)
        started = time.monotonic()
        try:
            code = _mod.supervise(
                [_mod.sys.executable, "-c", _CHILD, str(received), "3.0"],
                dry_run=False,
                log=_mod.DecisionLog(live_env / "decision.log"),
                stdin_fd=stdin_fd,
                poll_seconds=0.05,
                sidecar_dir=untracked / "context-sidecar",
                decider=_mod._make_worker_decider(worker),
                plugin_host=host,
                restart_worker=restart_worker,
                restart_coordinator=_mod.RestartCoordinator(state_path=live_env / "restart.json"),
            )
        finally:
            os.close(stdin_fd)
            worker.close()
        assert code == 7
        assert restarts.restarts == 1
        assert host.worker_argv() == []
        assert host.status_entries()[0]["state"] == "disabled"
        # The plugin was asked once (the tick that tripped) and never again.
        assert counter.read_text() == "x"
        assert received.read_bytes().decode().count("plugin notice") == 1
        assert time.monotonic() - started < 15
