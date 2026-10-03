"""Plan 00487 -- the harness a plugin author unit-tests a worker half with.

``PluginTestHarness`` loads a worker half through the REAL loader (the same
vetting, API-major check and budgeted hook calls the supervisor uses) but with
no worker process, no PTY and no live session. Unlike the supervisor, which
disables a failing plugin and carries on, the harness raises: a test wants the
failure, with the traceback.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from tests.unit.supervise._load import load_supervisor_module
from tests.unit.supervise._plugin_helpers import GOOD_BODY, plugin_source, write_plugin

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

_mod = load_supervisor_module()

_ASKS = """
    def on_start(self):
        self.api.audit("started")
    def on_idle(self, tick):
        self.api.status("restart soon", "warning", 5)
        self.seen = tick
        if tick.session_id is None:
            return None
        return self.api.ExitForRestart("max age " + tick.session_id)
"""
_RAISES = """
    def on_start(self):
        pass
    def on_idle(self, tick):
        raise ValueError("visible to the author")
"""


class TestHarness:
    def test_start_loads_the_half_and_runs_on_start(
        self, plugin_harness: Callable[..., Any], tmp_path: Path
    ) -> None:
        harness = plugin_harness("asker", write_plugin(tmp_path / "p", "asker", _ASKS))
        harness.start()
        assert harness.half.name == "asker"
        assert harness.audit_lines() == ("plugin asker: started",)

    def test_idle_returns_the_exit_request_with_the_tick_it_was_given(
        self, plugin_harness: Callable[..., Any], tmp_path: Path
    ) -> None:
        harness = plugin_harness(
            "asker", write_plugin(tmp_path / "p", "asker", _ASKS), session_ids=("s-1",)
        )
        harness.start()
        request = harness.idle(now=123.0)
        assert request == _mod.PluginExitRequest(plugin="asker", reason="max age s-1")
        assert harness.half.seen == _mod.IdleTick(now=123.0, session_id="s-1")

    def test_idle_returns_none_when_the_plugin_has_nothing_to_do(
        self, plugin_harness: Callable[..., Any], tmp_path: Path
    ) -> None:
        harness = plugin_harness("good", write_plugin(tmp_path / "p", "good", GOOD_BODY))
        harness.start()
        assert harness.idle() is None
        assert harness.half.idles == 1

    def test_an_ambiguous_session_reaches_the_plugin_as_none(
        self, plugin_harness: Callable[..., Any], tmp_path: Path
    ) -> None:
        harness = plugin_harness(
            "asker", write_plugin(tmp_path / "p", "asker", _ASKS), session_ids=("a", "b")
        )
        harness.start()
        assert harness.idle() is None
        assert harness.half.seen.session_id is None

    def test_status_calls_are_recorded_not_written(
        self, plugin_harness: Callable[..., Any], tmp_path: Path
    ) -> None:
        harness = plugin_harness("asker", write_plugin(tmp_path / "p", "asker", _ASKS))
        harness.start()
        harness.idle()
        assert harness.status_messages == [("restart soon", "warning", 5)]

    def test_the_state_dir_is_private_and_inside_the_work_dir(
        self, plugin_harness: Callable[..., Any], tmp_path: Path
    ) -> None:
        harness = plugin_harness("good", write_plugin(tmp_path / "p", "good", GOOD_BODY))
        harness.start()
        assert harness.state_dir.is_dir()
        assert harness.state_dir.stat().st_mode & 0o077 == 0

    def test_a_hook_failure_raises_with_the_traceback(
        self, plugin_harness: Callable[..., Any], tmp_path: Path
    ) -> None:
        harness = plugin_harness("bad", write_plugin(tmp_path / "p", "bad", _RAISES))
        harness.start()
        with pytest.raises(_mod.PluginHarnessError) as caught:
            harness.idle()
        assert "bad" in str(caught.value)
        assert "visible to the author" in str(caught.value)

    def test_a_load_failure_raises(
        self, plugin_harness: Callable[..., Any], tmp_path: Path
    ) -> None:
        path = write_plugin(tmp_path / "p", "old", source=plugin_source("old", api=2))
        harness = plugin_harness("old", path)
        with pytest.raises(_mod.PluginHarnessError) as caught:
            harness.start()
        assert "api-mismatch" in str(caught.value)

    def test_idle_before_start_is_a_usage_error(
        self, plugin_harness: Callable[..., Any], tmp_path: Path
    ) -> None:
        harness = plugin_harness("good", write_plugin(tmp_path / "p", "good", GOOD_BODY))
        with pytest.raises(_mod.PluginHarnessError):
            harness.idle()
