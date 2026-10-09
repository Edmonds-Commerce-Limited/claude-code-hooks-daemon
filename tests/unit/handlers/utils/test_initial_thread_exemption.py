"""The shared initial-thread gate of the declared-cron handlers (Plan 00470 Task 6.4)."""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.fake_proc import (
    DAEMON_ARGV,
    INITIAL_WORKER_ARGV,
    SPARE_WORKER_ARGV,
    add_proc,
    add_thread,
)

from claude_code_hooks_daemon.config.models import PersistentCronsConfig
from claude_code_hooks_daemon.constants.protocol import HookInputField
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.handlers.utils.initial_thread_exemption import (
    InitialThreadExemption,
    render_non_holder_note,
)
from claude_code_hooks_daemon.utils.session_thread_group import (
    PROC_ROOT,
    THREAD_GROUPS_FILENAME,
    OtherHolder,
)


class _Gate(InitialThreadExemption):
    def __init__(self, root: Path | None = None, state: Path | None = None) -> None:
        self._root = root
        self._state = state
        self.walks = 0

    def _proc_root(self) -> Path:
        self.walks += 1
        return self._root if self._root is not None else PROC_ROOT

    def _thread_groups_path(self) -> Path | None:
        return self._state


class TestDefaults:
    def test_the_proc_root_is_the_real_proc(self) -> None:
        assert InitialThreadExemption._proc_root(_Gate()) == PROC_ROOT

    def test_without_a_project_context_there_is_no_registry_path(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(ProjectContext, "is_initialized", classmethod(lambda cls: False))

        assert InitialThreadExemption._thread_groups_path(_Gate()) is None

    def test_with_a_project_context_the_registry_lives_in_the_untracked_dir(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(ProjectContext, "is_initialized", classmethod(lambda cls: True))
        monkeypatch.setattr(
            ProjectContext, "daemon_untracked_dir", classmethod(lambda cls: tmp_path)
        )

        assert InitialThreadExemption._thread_groups_path(_Gate()) == (
            tmp_path / THREAD_GROUPS_FILENAME
        )


class TestExemptHolder:
    def _tree(self, tmp_path: Path) -> Path:
        root = tmp_path / "proc"
        root.mkdir()
        add_proc(root, 1, 0, ["init"])
        add_proc(root, 589, 1, DAEMON_ARGV, start=777)
        add_thread(root, 589, 591, 700, INITIAL_WORKER_ARGV)
        add_thread(root, 589, 592, 701, SPARE_WORKER_ARGV)
        return root

    def test_the_option_off_reads_nothing(self, tmp_path: Path) -> None:
        gate = _Gate(self._tree(tmp_path), tmp_path / "groups.json")
        payload = {HookInputField.SESSION_ID: "s", HookInputField.PEER_PID: 701}

        assert (
            gate._exempt_holder(payload, PersistentCronsConfig(initial_thread_only=False)) is None
        )
        assert not (tmp_path / "groups.json").exists()

    def test_a_later_thread_is_exempt_and_the_verdict_is_walked_once_per_payload(
        self, tmp_path: Path
    ) -> None:
        gate = _Gate(self._tree(tmp_path), tmp_path / "groups.json")
        crons = PersistentCronsConfig()
        first = {HookInputField.SESSION_ID: "t1", HookInputField.PEER_PID: 700}
        second = {HookInputField.SESSION_ID: "t2", HookInputField.PEER_PID: 701}
        assert gate._exempt_holder(first, crons) is None

        walks_before = gate.walks
        verdicts = [gate._exempt_holder(second, crons) for _ in range(3)]

        assert verdicts == [OtherHolder(session_id="t1")] * 3
        assert gate.walks - walks_before == 1

    def test_a_different_payload_object_is_walked_again(self, tmp_path: Path) -> None:
        gate = _Gate(self._tree(tmp_path), tmp_path / "groups.json")
        crons = PersistentCronsConfig()

        gate._exempt_holder({HookInputField.SESSION_ID: "t1", HookInputField.PEER_PID: 700}, crons)
        gate._exempt_holder({HookInputField.SESSION_ID: "t1", HookInputField.PEER_PID: 700}, crons)

        assert gate.walks == 2


class TestNote:
    def test_it_names_the_holder_and_the_way_out(self) -> None:
        note = "\n".join(render_non_holder_note("abc-123"))

        assert "abc-123" in note
        assert "initial_thread_only" in note
        assert "CronCreate" in note

    def test_an_unknown_holder_session_is_not_invented(self) -> None:
        note = "\n".join(render_non_holder_note(None))

        assert "None" not in note
        assert "holds none" in note
