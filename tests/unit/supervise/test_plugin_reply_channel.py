"""Plan 00487 review defect 1 -- plugin output must never corrupt the worker reply channel.

A plugin's hook runs inside the worker, whose stdout IS the reply pipe to the
PTY host. Anything the plugin prints, writes to ``sys.stdout`` or writes to
file descriptor 1 must therefore never reach that pipe, and whatever does
arrive on it that is not a well-formed reply must be a bad reply the host
recovers from -- never an exception in the PTY loop.
"""

from __future__ import annotations

import os
import stat
import sys
from typing import TYPE_CHECKING, Any

import pytest

from tests.unit.supervise._load import SCRIPT_PATH, load_supervisor_module
from tests.unit.supervise._plugin_helpers import idle_facts, spec, write_plugin

if TYPE_CHECKING:
    from pathlib import Path

_mod = load_supervisor_module()
_OWN_UIDS = frozenset({os.getuid(), 0})
_CHILD_INTERPRETER_TIMEOUT_SECONDS = 30.0

# Each on_idle writes to the process's stdout in a different way, then records
# that it ran (so the test can prove the hook was really called).
_NOISE = {
    "print-scalar": "print(42)",
    "print-garbage": 'print("garbage {not json")',
    "print-json-list": "print([1, 2, 3])",
    "print-json-null": "print('null')",
    "sys-stdout-write": "sys.stdout.write('x\\n'); sys.stdout.flush()",
    "raw-fd-one": "os.write(1, b'raw bytes\\n')",
    "raw-fd-one-no-newline": "os.write(1, b'no newline at all')",
    "print-fake-reply": 'print(\'{"decision_value": "noop", "tick_id": 999999}\')',
}


def _noisy_body(statement: str) -> str:
    return f"""
    def on_start(self):
        pass
    def on_idle(self, tick):
        import os, sys
        with open(os.path.join(str(self.api.state_dir), "calls"), "a") as handle:
            handle.write("x")
        {statement}
        return None
"""


def _calls(state_root: Path, name: str) -> int:
    marker = state_root / name / "calls"
    return len(marker.read_text()) if marker.exists() else 0


def _live_worker(live_env: Path, name: str, body: str) -> Any:
    path = write_plugin(live_env / "plugins", name, body)
    host = _mod.PluginHost(
        [spec(name, path)],
        write_status=lambda entries: None,
        allowed_uids=_OWN_UIDS,
        status_dir=live_env / "untracked",
        marker_path=_mod._plugin_marker_path(live_env / "untracked", os.getpid()),
    )
    worker = _mod.PolicyWorker(SCRIPT_PATH, dry_run=False, extra_argv=host.worker_argv)
    assert worker.start()
    return worker


class _ScriptedWorker:
    """A policy worker whose script answers every tick with a fixed raw line."""

    def __init__(self, tmp_path: Path, reply_source: str) -> None:
        script = tmp_path / "fake_worker.py"
        script.write_text(
            "import sys\nfor _ in sys.stdin:\n    sys.stdout.write("
            + reply_source
            + ")\n    sys.stdout.flush()\n"
        )
        script.chmod(stat.S_IRUSR | stat.S_IWUSR)
        self.worker = _mod.PolicyWorker(script, dry_run=True)
        assert self.worker.start()

    def close(self) -> None:
        self.worker.close()


class TestHostDecodeIsTotal:
    @pytest.mark.parametrize(
        "reply_source",
        [
            repr("42\n"),
            repr('"a string"\n'),
            repr("[1, 2]\n"),
            repr("null\n"),
            repr("true\n"),
            repr("{}\n"),
            repr("garbage {\n"),
            repr('{"decision_value": 5, "reason": null}\n'),
            repr(
                '{"decision_value": "noop", "reason": "r", "payload": null, "submit": true,'
                ' "consume_signal_path": null, "deferred_log": null, "tick_id": [1]}\n'
            ),
            repr(
                '{"decision_value": "noop", "reason": "r", "payload": null, "submit": true,'
                ' "consume_signal_path": null, "deferred_log": null, "tick_id": 0,'
                ' "confirm_enters": {}}\n'
            ),
        ],
    )
    def test_any_malformed_reply_is_a_bad_reply_not_an_exception(
        self, tmp_path: Path, reply_source: str
    ) -> None:
        scripted = _ScriptedWorker(tmp_path, reply_source)
        try:
            assert scripted.worker.decide(idle_facts()) is None
        finally:
            scripted.close()

    def test_an_unexpected_error_from_the_decoder_is_contained(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        scripted = _ScriptedWorker(tmp_path, repr("{}\n"))

        def explode(line: str) -> object:
            raise RuntimeError("decoder bug")

        monkeypatch.setattr(_mod, "_outcome_from_json", explode)
        try:
            assert scripted.worker.decide(idle_facts()) is None
        finally:
            scripted.close()


class TestPluginOutputNeverReachesTheReplyChannel:
    @pytest.mark.parametrize("statement", list(_NOISE.values()), ids=list(_NOISE))
    def test_a_noisy_plugin_leaves_every_reply_well_formed(
        self, live_env: Path, statement: str
    ) -> None:
        worker = _live_worker(live_env, "noisy", _noisy_body(statement))
        try:
            outcomes = [worker.decide(idle_facts()) for _ in range(4)]
        finally:
            worker.close()
        assert all(outcome is not None for outcome in outcomes)
        # The hook really ran on every tick, was never disabled, and the host
        # was told of no failure.
        assert _calls(live_env / "ccy-state" / "plugins", "noisy") == 4
        assert all(outcome.plugin_failures == () for outcome in outcomes)

    def test_the_plugins_output_lands_in_the_worker_error_log_not_nowhere(
        self, live_env: Path
    ) -> None:
        # The worker subprocess resolves its own log from CLAUDE_PROJECT_DIR.
        log_path = live_env / "untracked" / _mod._WORKER_ERROR_LOG_NAME
        worker = _live_worker(live_env, "noisy", _noisy_body("print('PLUGIN-WAS-HERE')"))
        try:
            assert worker.decide(idle_facts()) is not None
        finally:
            worker.close()
        assert "PLUGIN-WAS-HERE" in log_path.read_text()

    def test_a_plugin_cannot_read_the_hosts_ticks_from_stdin(self, live_env: Path) -> None:
        body = """
    def on_start(self):
        pass
    def on_idle(self, tick):
        import os, sys
        stolen = sys.stdin.readline() + repr(os.read(0, 10))
        with open(os.path.join(str(self.api.state_dir), "stolen"), "w") as handle:
            handle.write(stolen)
        return None
"""
        worker = _live_worker(live_env, "thief", body)
        try:
            assert worker.decide(idle_facts()) is not None
            assert worker.decide(idle_facts()) is not None
        finally:
            worker.close()
        stolen = (live_env / "ccy-state" / "plugins" / "thief" / "stolen").read_text()
        assert "now_wall" not in stolen

    def test_the_isolation_hands_back_private_streams_and_repoints_the_standard_ones(
        self, tmp_path: Path
    ) -> None:
        # Run in a child interpreter: it swaps the real fds 0 and 1.
        import subprocess

        script = (
            "import importlib.util, os, sys\n"
            f"spec = importlib.util.spec_from_file_location('sup', {str(SCRIPT_PATH)!r})\n"
            "mod = importlib.util.module_from_spec(spec)\n"
            "sys.modules['sup'] = mod\n"
            "spec.loader.exec_module(mod)\n"
            "reader, writer = mod._isolate_worker_channels()\n"
            "writer.write('REPLY\\n'); writer.flush()\n"
            "print('NOISE'); os.write(1, b'RAWNOISE\\n')\n"
            "sys.stdout.flush()\n"
            "sys.stderr.write('ERR\\n'); sys.stderr.flush()\n"
            "sys.stdout.write(repr(reader.readline()))\n"
        )
        result = subprocess.run(  # nosec B603 - fixed argv, no shell
            [sys.executable, "-c", script],
            input="TICK\n",
            capture_output=True,
            text=True,
            timeout=_CHILD_INTERPRETER_TIMEOUT_SECONDS,
            check=False,
            env={**os.environ, "CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.stdout == "REPLY\n"
        assert "NOISE" in result.stderr
        assert "RAWNOISE" in result.stderr
        assert "'TICK\\n'" in result.stderr
