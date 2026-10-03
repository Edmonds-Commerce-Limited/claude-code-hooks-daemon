"""Plan 00487 review defects 4 and 5 -- nothing a plugin does escapes its budget or the setup.

Defect 4: the text of an ``ExitForRestart`` reason is plugin-controlled, so
reading it (``str()`` and all) happens inside the hook's time budget, and a
reason that is not a plain ``str`` is a bad result.

Defect 5: an unexpected exception anywhere in the HOST's plugin setup or
handling must not stop the session starting or running -- plugins are simply
switched off.
"""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING, Any

import pytest

from tests.unit.supervise._load import load_supervisor_module
from tests.unit.supervise._plugin_helpers import NOW, make_runtime, spec, write_plugin

if TYPE_CHECKING:
    from pathlib import Path

_mod = load_supervisor_module()
_OWN_UIDS = frozenset({os.getuid(), 0})

_HOSTILE_REASONS = {
    "non-str": "self.api.ExitForRestart(12345)",
    "bytes": "self.api.ExitForRestart(b'bytes')",
    "none": "self.api.ExitForRestart(None)",
    "str-subclass": "self.api.ExitForRestart(Sub('x'))",
}


def _asking_body(expression: str, preamble: str = "") -> str:
    return f"""
    def on_start(self):
        pass
    def on_idle(self, tick):
{preamble}
        return {expression}
"""


_SUBCLASS = "        class Sub(str):\n            def __str__(self):\n                raise RuntimeError('boom')\n"


class TestReasonIsReadInsideTheBudget:
    @pytest.mark.parametrize(
        "expression", list(_HOSTILE_REASONS.values()), ids=list(_HOSTILE_REASONS)
    )
    def test_a_reason_that_is_not_a_plain_str_is_a_bad_result(
        self, tmp_path: Path, expression: str
    ) -> None:
        runtime = make_runtime(tmp_path, {"p": _asking_body(expression, _SUBCLASS)})
        assert runtime.run_idle(NOW) is None
        assert [(f.kind, f.hook) for f in runtime.failures] == [("bad-result", "on_idle")]

    def test_a_reason_property_that_hangs_is_an_overrun_not_a_stall_of_the_caller(
        self, tmp_path: Path
    ) -> None:
        preamble = """
        import time
        class Slow(self.api.ExitForRestart):
            def __init__(self, *args):
                pass
            @property
            def reason(self):
                time.sleep(30)
                return "late"
"""
        body = _asking_body("Slow('x')", preamble)
        runtime = make_runtime(tmp_path, {"p": body}, hook_budget=0.2)
        started = _mod.time.monotonic()
        assert runtime.run_idle(NOW) is None
        assert _mod.time.monotonic() - started < 5
        assert [(f.kind, f.hook) for f in runtime.failures] == [("overrun", "on_idle")]

    def test_a_reason_property_that_raises_is_an_exception_failure(self, tmp_path: Path) -> None:
        preamble = """
        class Bad(self.api.ExitForRestart):
            def __init__(self, *args):
                pass
            @property
            def reason(self):
                raise ValueError("no reason for you")
"""
        runtime = make_runtime(tmp_path, {"p": _asking_body("Bad('x')", preamble)})
        assert runtime.run_idle(NOW) is None
        assert [(f.kind, f.hook) for f in runtime.failures] == [("exception", "on_idle")]

    def test_a_plain_reason_is_cleaned_and_bounded(self, tmp_path: Path) -> None:
        body = _asking_body("self.api.ExitForRestart('line one\\nline two \\x1b[31m' + 'x' * 500)")
        request = make_runtime(tmp_path, {"p": body}).run_idle(NOW)
        assert request is not None
        assert request.plugin == "p"
        assert "\n" not in request.reason
        assert "\x1b" not in request.reason
        assert len(request.reason) <= _mod._PLUGIN_REASON_MAX_CHARS


class TestHostSetupIsContained:
    def test_an_unexpected_error_vetting_one_flag_skips_only_that_plugin(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        good = write_plugin(tmp_path / "plugins", "good")
        bad = write_plugin(tmp_path / "plugins", "bad")
        real_check = _mod.check_plugin_file

        def flaky(path: Path, **kwargs: Any) -> str | None:
            if path.name == "bad.py":
                raise RuntimeError("unexpected")
            verdict: str | None = real_check(path, **kwargs)
            return verdict

        monkeypatch.setattr(_mod, "check_plugin_file", flaky)
        host = _mod.PluginHost(
            [spec("bad", bad), spec("good", good)],
            write_status=lambda entries: None,
            allowed_uids=_OWN_UIDS,
            marker_path=tmp_path / "marker.json",
        )
        states = {entry["name"]: entry["state"] for entry in host.status_entries()}
        assert states["good"] == "loaded"
        assert states["bad"] == "failed"

    def test_building_the_host_never_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def explode(*args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("setup bug")

        monkeypatch.setattr(_mod, "PluginHost", explode)
        flags = _mod._parse_supervisor_flags(["--plugin", "p=/nowhere/p.py", "--", "claude"])
        assert _mod._make_plugin_host(flags, lambda plugins: None, tmp_path) is None

    def test_no_plugin_flag_means_no_host(self, tmp_path: Path) -> None:
        flags = _mod._parse_supervisor_flags(["--", "claude"])
        assert _mod._make_plugin_host(flags, lambda plugins: None, tmp_path) is None

    def test_a_failing_argv_provider_starts_the_worker_without_plugins(
        self, tmp_path: Path
    ) -> None:
        script = tmp_path / "quiet_worker.py"
        script.write_text("import sys\nfor _ in sys.stdin:\n    pass\n")

        def broken() -> list[str]:
            raise RuntimeError("argv bug")

        worker = _mod.PolicyWorker(script, dry_run=True, extra_argv=broken)
        try:
            assert worker.start()
            assert worker.alive()
        finally:
            worker.close()


class _ExplodingHost:
    """A plugin host stand-in whose every method raises."""

    def __init__(self) -> None:
        self.calls = 0

    def take_startup_failures(self) -> list[Any]:
        self.calls += 1
        raise RuntimeError("startup bug")

    def record_loaded(self, name: str, version: str) -> None:
        self.calls += 1
        raise RuntimeError("loaded bug")

    def record_failure(self, *args: Any, **kwargs: Any) -> bool:
        self.calls += 1
        raise RuntimeError("failure bug")

    def detect_wedge(self, now_wall: float) -> Any:
        self.calls += 1
        raise RuntimeError("wedge bug")

    def worker_argv(self) -> list[str]:
        raise RuntimeError("argv bug")


def _supervise_with(tmp_path: Path, host: Any, decider: Any, *, linger: float = 0.6) -> int:
    stdin_fd = os.open(os.devnull, os.O_RDONLY)
    try:
        return int(
            _mod.supervise(
                [sys.executable, "-c", f"import time; time.sleep({linger}); raise SystemExit(5)"],
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


class TestHostHandlingIsContained:
    def test_a_host_that_fails_at_startup_does_not_stop_the_session_starting(
        self, tmp_path: Path
    ) -> None:
        assert _supervise_with(tmp_path, _ExplodingHost(), decider=None) == 5

    def test_a_host_that_fails_while_handling_a_reply_does_not_stop_the_session(
        self, tmp_path: Path
    ) -> None:
        def noop_with_plugin_news(facts: object) -> Any:
            return _mod.TickOutcome(
                decision_value="noop",
                reason="r",
                payload=None,
                submit=True,
                consume_signal_path=None,
                deferred_log=None,
                plugin_versions=(("p", "1"),),
                plugin_failures=(("p", "exception", "on_idle", ""),),
            )

        host = _ExplodingHost()
        assert _supervise_with(tmp_path, host, decider=noop_with_plugin_news) == 5
        # Disabled wholesale after the first containment: not retried every tick.
        assert host.calls <= 3
        assert "plugin handling failed" in (tmp_path / "decision.log").read_text()

    def test_a_host_that_fails_while_judging_a_silent_worker_does_not_stop_the_session(
        self, tmp_path: Path
    ) -> None:
        host = _ExplodingHost()
        assert _supervise_with(tmp_path, host, decider=lambda facts: None) == 5
        assert host.calls <= 3
