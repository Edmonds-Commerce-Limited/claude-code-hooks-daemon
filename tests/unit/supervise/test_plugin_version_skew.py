"""Plan 00487 -- the host and the worker may run different versions of the supervisor.

The host is long-lived and the worker hot-reloads, so a new worker can answer
an old host and, after a relaunch, a new host can briefly meet an old worker.
Both directions must keep working. The baseline here is the supervisor as
released at ``v3.68.0``, the last release before the plugin API (read with
``git show``). It is pinned to a tag, not to ``main``, because once the API
merged, ``main`` and the module under test were the same code, and a skew test
that compares a version with itself proves nothing.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from tests.unit.supervise._load import SCRIPT_PATH, load_supervisor_module

_mod = load_supervisor_module()
_REPO_ROOT = SCRIPT_PATH.parents[2]
_RELATIVE_PATH = ".claude/ccy/claude-supervise.py"
_BASELINE_REF = "v3.68.0"


@pytest.fixture(scope="module")
def baseline(tmp_path_factory: pytest.TempPathFactory) -> Any:
    """The supervisor module as released at the baseline tag; the test skips if it cannot be read."""
    completed = subprocess.run(
        ["git", "-C", str(_REPO_ROOT), "show", f"{_BASELINE_REF}:{_RELATIVE_PATH}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        pytest.skip(f"cannot read {_BASELINE_REF}:{_RELATIVE_PATH}: {completed.stderr.strip()}")
    path = tmp_path_factory.mktemp("baseline") / "baseline_supervise.py"
    path.write_text(completed.stdout)
    name = "claude_supervise_baseline"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _outcome(module: Any, *, decision_value: str = "noop", **fields: Any) -> Any:
    return module.TickOutcome(
        decision_value=decision_value,
        reason="r",
        payload=fields.pop("payload", None),
        submit=True,
        consume_signal_path=None,
        deferred_log=None,
        **fields,
    )


class TestNewWorkerOldHost:
    def test_the_old_host_imports_the_new_workers_machine_state(self, baseline: Any) -> None:
        new_machine = _mod.CompactStateMachine(_mod.CompactPolicy())
        new_machine.arm_plugin_notice("x", "exception", "on_idle")
        new_machine.arm_session_notice("restart-soon", "30", now_wall=100.0)
        old_machine = baseline.CompactStateMachine(baseline.CompactPolicy())
        old_machine.import_state(new_machine.export_state())  # unknown keys are ignored

    def test_the_old_host_decodes_the_new_workers_reply(self, baseline: Any) -> None:
        new_machine = _mod.CompactStateMachine(_mod.CompactPolicy())
        new_machine.arm_session_notice("deadline-reached", "", now_wall=1.0)
        reply = _outcome(
            _mod,
            machine_state=new_machine.export_state(),
            exit_for_restart=("x", "y"),
            plugin_failures=(("p", "exit-stuck", "on_idle", ""),),
        )
        decoded = baseline._outcome_from_json(_mod._outcome_to_json(reply))
        assert decoded.decision_value == "noop"

    def test_a_session_notice_is_a_plain_injection_to_an_old_host(self, baseline: Any) -> None:
        # The old host does not know the decision value, but only ever acts on
        # the payload, and its bookkeeping simply has no branch for it.
        reply = _outcome(_mod, decision_value="would-session-notice", payload="line")
        decoded = baseline._outcome_from_json(_mod._outcome_to_json(reply))
        assert decoded.payload == "line"
        assert decoded.submit is True


class TestNewHostOldWorker:
    def test_the_new_host_decodes_an_old_workers_reply(self, baseline: Any) -> None:
        old_reply = _outcome(baseline, machine_state=None)
        decoded = _mod._outcome_from_json(baseline._outcome_to_json(old_reply))
        assert decoded.plugin_failures == ()
        assert decoded.plugin_versions == ()
        assert decoded.plugin_log_lines == ()
        assert decoded.exit_for_restart is None

    def test_the_new_host_imports_an_old_workers_machine_state(self, baseline: Any) -> None:
        old_machine = baseline.CompactStateMachine(baseline.CompactPolicy())
        new_machine = _mod.CompactStateMachine(_mod.CompactPolicy())
        new_machine.arm_session_notice("restart-soon", "30", now_wall=1.0)
        new_machine.import_state(old_machine.export_state())
        # A peer that predates the keys leaves the queue and the rate limit alone.
        assert new_machine.session_notices_pending == ("restart-soon|30",)
        assert not new_machine.arm_session_notice("restart-soon", "29", now_wall=2.0)

    def test_a_new_worker_takes_empty_plugin_flags_from_an_old_hosts_argv(self) -> None:
        assert _mod._parse_worker_plugin_flags(["--worker", "--arm"]) == ([], frozenset())


class TestNoPluginsBehavesAsBefore:
    def test_no_plugin_flag_builds_no_host(self) -> None:
        flags = _mod._parse_supervisor_flags(["--", "claude"])
        assert flags.plugin == []
        assert _mod._make_plugin_host(flags, lambda plugins: None, Path("/nonexistent")) is None

    def test_the_status_payload_has_no_plugins_key_without_plugins(self, tmp_path: Path) -> None:
        path = _mod.write_supervisor_status(
            tmp_path, version="1", source_hash="h", pid=1, started_at=0.0
        )
        assert path is not None
        assert "plugins" not in path.read_text()

    def test_the_machine_state_of_a_session_without_notices_round_trips_unchanged(self) -> None:
        machine = _mod.CompactStateMachine(_mod.CompactPolicy())
        state = machine.export_state()
        assert state["session_notices_pending"] == []
        assert state["session_notice_last"] == {}
