"""The shared initial-thread gate of the three declared-cron handlers (Plan 00470 Task 6.4)."""

from __future__ import annotations

from pathlib import Path

from claude_code_hooks_daemon.config.models import PersistentCronsConfig
from claude_code_hooks_daemon.constants.protocol import HookInputField
from claude_code_hooks_daemon.handlers.utils.initial_thread_exemption import (
    InitialThreadExemption,
    render_non_holder_note,
)
from claude_code_hooks_daemon.utils.session_thread_group import PROC_ROOT, THREAD_GROUPS_FILENAME


class _Gate(InitialThreadExemption):
    pass


class TestDefaults:
    def test_the_proc_root_is_the_real_proc(self) -> None:
        assert _Gate()._proc_root() == PROC_ROOT

    def test_the_registry_path_is_none_without_a_project_context(self) -> None:
        # No ProjectContext is initialised for a bare unit test.
        path = _Gate()._thread_groups_path()
        assert path is None or path.name == THREAD_GROUPS_FILENAME


class TestOptionOff:
    def test_a_pid_stamped_payload_is_never_exempt_when_the_option_is_off(
        self, tmp_path: Path
    ) -> None:
        class Gate(_Gate):
            def _thread_groups_path(self) -> Path | None:
                return tmp_path / "groups.json"

        crons = PersistentCronsConfig(initial_thread_only=False)
        payload = {HookInputField.SESSION_ID: "s", HookInputField.PEER_PID: 1234}

        assert Gate()._exempt_holder(payload, crons) is None
        assert not (tmp_path / "groups.json").exists()


class TestNote:
    def test_it_names_the_holder_and_the_way_out(self) -> None:
        note = "\n".join(render_non_holder_note("abc-123"))

        assert "abc-123" in note
        assert "initial_thread_only" in note
        assert "CronCreate" in note
