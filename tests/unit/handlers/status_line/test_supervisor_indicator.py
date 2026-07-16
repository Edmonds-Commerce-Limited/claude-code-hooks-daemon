"""Tests for SupervisorIndicatorHandler.

Detects whether the ccy PTY supervisor (claude-supervise.py) is overseeing the
session by reading its status file and cross-checking pid liveness + cmdline.
State is rendered as a top hat (🎩) with a state-coloured ANSI background;
"not configured" (no status file) and any unexpected error render NO segment.
The immutable (pid, armed) identity is memoised after first resolution.
"""

import json
from pathlib import Path
from unittest.mock import patch

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.handlers.status_line.supervisor_indicator import (
    _BG_GREEN,
    _BG_ORANGE,
    _BG_YELLOW,
    _ICON,
    SupervisorIndicatorHandler,
)

_STATUS_PATH_PATCH = (
    "claude_code_hooks_daemon.handlers.status_line.supervisor_indicator."
    "SupervisorIndicatorHandler._status_file_path"
)
_KILL_PATCH = "claude_code_hooks_daemon.handlers.status_line.supervisor_indicator.os.kill"
_CMDLINE_PATCH = (
    "claude_code_hooks_daemon.handlers.status_line.supervisor_indicator."
    "SupervisorIndicatorHandler._read_cmdline"
)


def _write_status(tmp_path: Path, pid: int) -> Path:
    status_file = tmp_path / "supervisor-status.json"
    status_file.write_text(json.dumps({"pid": pid, "version": "3.41.0"}))
    return status_file


class TestSupervisorIndicatorInit:
    def test_identity_and_flags(self) -> None:
        handler = SupervisorIndicatorHandler()
        assert handler.handler_id == HandlerID.SUPERVISOR_INDICATOR
        assert handler.priority == Priority.SUPERVISOR_INDICATOR
        assert handler.terminal is False
        assert HandlerTag.STATUSLINE in handler.tags
        assert HandlerTag.NON_TERMINAL in handler.tags

    def test_default_enabled(self) -> None:
        assert SupervisorIndicatorHandler().get_default_enabled() is True

    def test_matches_always_true(self) -> None:
        assert SupervisorIndicatorHandler().matches({}) is True

    def test_get_claude_md_is_none(self) -> None:
        assert SupervisorIndicatorHandler().get_claude_md() is None

    def test_get_acceptance_tests_nonempty(self) -> None:
        assert len(SupervisorIndicatorHandler().get_acceptance_tests()) >= 1


class TestSupervisorIndicatorDetection:
    def test_active_armed_is_green(self, tmp_path: Path) -> None:
        status_file = _write_status(tmp_path, pid=1234)
        handler = SupervisorIndicatorHandler()
        with (
            patch(_STATUS_PATH_PATCH, return_value=status_file),
            patch(_KILL_PATCH, return_value=None),
            patch(_CMDLINE_PATCH, return_value="python3 claude-supervise.py --arm"),
        ):
            result = handler.handle({})
        assert result.context
        assert _BG_GREEN in result.context[0]
        assert _ICON in result.context[0]

    def test_active_dryrun_is_yellow(self, tmp_path: Path) -> None:
        status_file = _write_status(tmp_path, pid=1234)
        handler = SupervisorIndicatorHandler()
        with (
            patch(_STATUS_PATH_PATCH, return_value=status_file),
            patch(_KILL_PATCH, return_value=None),
            patch(_CMDLINE_PATCH, return_value="python3 claude-supervise.py"),
        ):
            result = handler.handle({})
        assert _BG_YELLOW in result.context[0]
        assert _ICON in result.context[0]

    def test_not_configured_when_file_absent_renders_nothing(self, tmp_path: Path) -> None:
        missing = tmp_path / "nope.json"
        handler = SupervisorIndicatorHandler()
        with patch(_STATUS_PATH_PATCH, return_value=missing):
            result = handler.handle({})
        assert result.context == []

    def test_not_active_orange_when_pid_dead_but_file_present(self, tmp_path: Path) -> None:
        status_file = _write_status(tmp_path, pid=99999)
        handler = SupervisorIndicatorHandler()

        def _raise_esrch(pid: int, sig: int) -> None:
            import errno as errno_mod

            raise OSError(errno_mod.ESRCH, "No such process")

        with (
            patch(_STATUS_PATH_PATCH, return_value=status_file),
            patch(_KILL_PATCH, side_effect=_raise_esrch),
        ):
            result = handler.handle({})
        assert _BG_ORANGE in result.context[0]

    def test_active_when_pid_alive_but_not_ours_eperm(self, tmp_path: Path) -> None:
        status_file = _write_status(tmp_path, pid=1)

        def _raise_eperm(pid: int, sig: int) -> None:
            import errno as errno_mod

            raise OSError(errno_mod.EPERM, "Operation not permitted")

        handler = SupervisorIndicatorHandler()
        with (
            patch(_STATUS_PATH_PATCH, return_value=status_file),
            patch(_KILL_PATCH, side_effect=_raise_eperm),
            patch(_CMDLINE_PATCH, return_value="python3 claude-supervise.py --arm"),
        ):
            result = handler.handle({})
        assert _BG_GREEN in result.context[0]

    def test_orange_when_pid_reused_by_other_process(self, tmp_path: Path) -> None:
        status_file = _write_status(tmp_path, pid=1234)
        handler = SupervisorIndicatorHandler()
        with (
            patch(_STATUS_PATH_PATCH, return_value=status_file),
            patch(_KILL_PATCH, return_value=None),
            patch(_CMDLINE_PATCH, return_value="python3 some_unrelated_process.py"),
        ):
            result = handler.handle({})
        assert _BG_ORANGE in result.context[0]

    def test_orange_when_cmdline_unreadable(self, tmp_path: Path) -> None:
        status_file = _write_status(tmp_path, pid=1234)
        handler = SupervisorIndicatorHandler()
        with (
            patch(_STATUS_PATH_PATCH, return_value=status_file),
            patch(_KILL_PATCH, return_value=None),
            patch(_CMDLINE_PATCH, return_value=None),
        ):
            result = handler.handle({})
        assert _BG_ORANGE in result.context[0]

    def test_orange_when_status_json_malformed(self, tmp_path: Path) -> None:
        status_file = tmp_path / "supervisor-status.json"
        status_file.write_text("{not valid json")
        handler = SupervisorIndicatorHandler()
        with patch(_STATUS_PATH_PATCH, return_value=status_file):
            result = handler.handle({})
        assert _BG_ORANGE in result.context[0]

    def test_orange_when_pid_field_missing(self, tmp_path: Path) -> None:
        status_file = tmp_path / "supervisor-status.json"
        status_file.write_text(json.dumps({"version": "3.41.0"}))
        handler = SupervisorIndicatorHandler()
        with patch(_STATUS_PATH_PATCH, return_value=status_file):
            result = handler.handle({})
        assert _BG_ORANGE in result.context[0]

    def test_fail_safe_renders_nothing_on_unexpected_exception(self, tmp_path: Path) -> None:
        status_file = _write_status(tmp_path, pid=1234)
        handler = SupervisorIndicatorHandler()
        with (
            patch(_STATUS_PATH_PATCH, return_value=status_file),
            patch(_KILL_PATCH, side_effect=RuntimeError("boom")),
        ):
            result = handler.handle({})
        assert result.context == []

    def test_segment_has_separator_prefix(self, tmp_path: Path) -> None:
        status_file = _write_status(tmp_path, pid=1234)
        handler = SupervisorIndicatorHandler()
        with (
            patch(_STATUS_PATH_PATCH, return_value=status_file),
            patch(_KILL_PATCH, return_value=None),
            patch(_CMDLINE_PATCH, return_value="python3 claude-supervise.py --arm"),
        ):
            result = handler.handle({})
        assert result.context[0].startswith("|")


class TestSupervisorIndicatorMemoisation:
    def test_identity_memoised_cmdline_not_reread_on_second_render(self, tmp_path: Path) -> None:
        status_file = _write_status(tmp_path, pid=1234)
        handler = SupervisorIndicatorHandler()
        with (
            patch(_STATUS_PATH_PATCH, return_value=status_file),
            patch(_KILL_PATCH, return_value=None),
            patch(_CMDLINE_PATCH, return_value="python3 claude-supervise.py --arm") as cmdline_mock,
        ):
            handler.handle({})  # first render resolves + memoises
            assert cmdline_mock.call_count == 1
            result2 = handler.handle({})  # second render uses the fast path
            assert cmdline_mock.call_count == 1  # cmdline NOT re-read
        assert _BG_GREEN in result2.context[0]
        assert handler._cached_pid == 1234
        assert handler._cached_armed is True

    def test_cache_dropped_and_reresolved_when_supervisor_dies(self, tmp_path: Path) -> None:
        status_file = _write_status(tmp_path, pid=1234)
        handler = SupervisorIndicatorHandler()
        with (
            patch(_STATUS_PATH_PATCH, return_value=status_file),
            patch(_KILL_PATCH, return_value=None),
            patch(_CMDLINE_PATCH, return_value="python3 claude-supervise.py --arm"),
        ):
            first = handler.handle({})
        assert _BG_GREEN in first.context[0]
        assert handler._cached_pid == 1234

        def _raise_esrch(pid: int, sig: int) -> None:
            import errno as errno_mod

            raise OSError(errno_mod.ESRCH, "No such process")

        with (
            patch(_STATUS_PATH_PATCH, return_value=status_file),
            patch(_KILL_PATCH, side_effect=_raise_esrch),
        ):
            after = handler.handle({})
        assert _BG_ORANGE in after.context[0]  # crash -> orange
        assert handler._cached_pid is None  # cache dropped


class TestSupervisorIndicatorHelpers:
    def test_status_file_path_uses_supervise_subdirectory(self, tmp_path: Path) -> None:
        handler = SupervisorIndicatorHandler()
        with patch(
            "claude_code_hooks_daemon.handlers.status_line.supervisor_indicator."
            "ProjectContext.daemon_untracked_dir",
            return_value=tmp_path,
        ):
            path = handler._status_file_path()
        assert path.name == "supervisor-status.json"
        assert path.parent.name == "supervise"

    def test_read_status_returns_none_for_non_dict_json(self, tmp_path: Path) -> None:
        status_file = tmp_path / "supervisor-status.json"
        status_file.write_text(json.dumps([1, 2, 3]))
        handler = SupervisorIndicatorHandler()
        assert handler._read_status(status_file) is None

    def test_read_cmdline_reads_real_proc_entry(self) -> None:
        handler = SupervisorIndicatorHandler()
        # pid 1 (init/pid-namespace root) always exists in a Linux container.
        cmdline = handler._read_cmdline(1)
        assert cmdline is None or isinstance(cmdline, str)

    def test_read_cmdline_returns_none_for_nonexistent_pid(self) -> None:
        handler = SupervisorIndicatorHandler()
        assert handler._read_cmdline(999999999) is None
