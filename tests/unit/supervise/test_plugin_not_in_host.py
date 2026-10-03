"""Plan 00487 review defect 2 -- a plugin NEVER runs in the PTY host process.

When the policy worker is silent or dead the host decides in-process. That
fallback runs the built-in families only: no plugin is imported, started or
asked, because a plugin that wedges the GIL or leaks a thread in the host
would take the session with it. Plugins resume when a worker answers again.
"""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING, Any

from tests.unit.supervise._load import load_supervisor_module
from tests.unit.supervise._plugin_helpers import spec, write_plugin

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

_mod = load_supervisor_module()
_OWN_UIDS = frozenset({os.getuid(), 0})
_SESSION = "host-sess-1"

# A plugin whose start and every idle call leave a trace on disk.
_TRACING_BODY = """
    def on_start(self):
        import os
        open(os.path.join(str(self.api.state_dir), "started"), "w").close()
    def on_idle(self, tick):
        import os
        open(os.path.join(str(self.api.state_dir), "asked"), "w").close()
        return self.api.ExitForRestart("must never be honoured in the host")
"""

_CHILD = "import time; time.sleep(1.0)"


def _host(tmp_path: Path) -> Any:
    path = write_plugin(tmp_path / "plugins", "tracer", _TRACING_BODY)
    return _mod.PluginHost(
        [spec("tracer", path)],
        write_status=lambda entries: None,
        allowed_uids=_OWN_UIDS,
        status_dir=tmp_path / "untracked",
        marker_path=tmp_path / "untracked" / "supervise" / "marker.json",
    )


def _supervise(tmp_path: Path, host: Any, *, decider: Any = None) -> int:
    stdin_fd = os.open(os.devnull, os.O_RDONLY)
    try:
        return int(
            _mod.supervise(
                [sys.executable, "-c", _CHILD],
                dry_run=False,
                log=_mod.DecisionLog(tmp_path / "decision.log"),
                stdin_fd=stdin_fd,
                poll_seconds=0.05,
                sidecar_dir=tmp_path / "untracked" / "context-sidecar",
                decider=decider,
                plugin_host=host,
                restart_coordinator=_mod.RestartCoordinator(
                    state_path=tmp_path / "state" / "restart-request.json"
                ),
            )
        )
    finally:
        os.close(stdin_fd)


def _assert_never_ran(tmp_path: Path) -> None:
    state_dir = tmp_path / "plugin-state" / "tracer"
    assert not (state_dir / "started").exists()
    assert not (state_dir / "asked").exists()
    assert f"{_mod._PLUGIN_MODULE_PREFIX}tracer" not in sys.modules


class TestThePluginsNeverRunInTheHost:
    def test_the_host_registry_has_no_in_process_runtime(self, tmp_path: Path) -> None:
        assert not hasattr(_mod.PluginHost, "in_process_runtime")
        assert not hasattr(_host(tmp_path), "in_process_runtime")

    def test_no_worker_at_all_means_built_in_families_only(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_mod, "cached_own_session_ids", lambda *a, **k: frozenset({_SESSION}))
        code = _supervise(tmp_path, _host(tmp_path), decider=None)
        assert code == 0  # the child ran to its own end; nothing exited it
        _assert_never_ran(tmp_path)
        assert not (tmp_path / "state" / "restart-request.json").exists()

    def test_a_silent_worker_means_built_in_families_only(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_mod, "cached_own_session_ids", lambda *a, **k: frozenset({_SESSION}))
        asked = {"n": 0}

        def silent(facts: object) -> None:
            asked["n"] += 1
            return None

        code = _supervise(tmp_path, _host(tmp_path), decider=silent)
        assert code == 0
        assert asked["n"] > 1  # the fallback really carried many ticks
        _assert_never_ran(tmp_path)

    def test_the_fallback_still_runs_the_built_in_families(self, tmp_path: Path) -> None:
        # A failure already known to the host is still told to the session by
        # the fallback: the built-in plugin-notice family needs no plugin code.
        machine = _mod.CompactStateMachine(_mod.CompactPolicy())
        machine.arm_plugin_notice("tracer", "exception", "on_idle")
        sidecars = tmp_path / "untracked" / "context-sidecar"
        sidecars.mkdir(parents=True)
        typed: list[bytes] = []
        _mod._poll_once(
            machine,
            sidecar_dir=sidecars,
            now_wall=1000.0,
            idle=True,
            dry_run=False,
            master_writer=typed.append,
            log=None,
            freshness_seconds=60.0,
            own_sessions=frozenset({_SESSION}),
            plugins=None,
        )
        assert b"plugin `tracer` raised an exception" in b"".join(typed)
