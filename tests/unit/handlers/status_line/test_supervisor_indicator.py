"""Tests for SupervisorIndicatorHandler.

Detects whether the ccy PTY supervisor (claude-supervise.py) is overseeing the
session by reading its status file and cross-checking pid liveness + cmdline.
State is rendered as a top hat (🎩) with a state-coloured ANSI background;
"not configured" (no status file) and any unexpected error render NO segment.
The immutable (pid, armed) identity is memoised after first resolution.
"""

import errno
import json
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.handlers.status_line.supervisor_indicator import (
    _ANSI_RESET,
    _BG_GREEN,
    _BG_ORANGE,
    _BG_YELLOW,
    _FG_BLACK,
    _ICON,
    _MESSAGE_LEVEL_WARNING,
    _NEGATIVE_CACHE_TTL_SECONDS,
    SupervisorIndicatorHandler,
    _SupervisorState,
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
_SCAN_PATCH = (
    "claude_code_hooks_daemon.handlers.status_line.supervisor_indicator."
    "SupervisorIndicatorHandler._scan_for_supervisor"
)
_NOW_PATCH = (
    "claude_code_hooks_daemon.handlers.status_line.supervisor_indicator."
    "SupervisorIndicatorHandler._now"
)
_MESSAGE_PATH_PATCH = (
    "claude_code_hooks_daemon.handlers.status_line.supervisor_indicator."
    "SupervisorIndicatorHandler._message_file_path"
)
_WALL_NOW_PATCH = (
    "claude_code_hooks_daemon.handlers.status_line.supervisor_indicator."
    "SupervisorIndicatorHandler._wall_now"
)
_DETECT_PATCH = (
    "claude_code_hooks_daemon.handlers.status_line.supervisor_indicator."
    "SupervisorIndicatorHandler._detect_state"
)


def _write_message(tmp_path: Path, text: str, expires_at: float, level: str) -> Path:
    message_file = tmp_path / "status-message.json"
    message_file.write_text(json.dumps({"text": text, "expires_at": expires_at, "level": level}))
    return message_file


def _write_status(tmp_path: Path, pid: int) -> Path:
    status_file = tmp_path / "supervisor-status.json"
    status_file.write_text(json.dumps({"pid": pid, "version": "3.41.0"}))
    return status_file


@pytest.fixture(autouse=True)
def _no_ambient_message(tmp_path: Path) -> Iterator[None]:
    """Isolate every test from any REAL supervisor message file.

    ``handle()`` now reads ``daemon_untracked_dir()/supervise/status-message.json``
    to render an attached notice; in a dogfooding checkout a live supervisor may
    have just written one (with a short TTL), which would non-deterministically
    perturb the plain-top-hat assertions. Point the message reader at a
    guaranteed-absent path by default; the message tests override this with their
    own ``patch(_MESSAGE_PATH_PATCH, ...)`` context.
    """
    missing = tmp_path / "no-such-message.json"
    with patch(_MESSAGE_PATH_PATCH, return_value=missing):
        yield


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
    @pytest.fixture(autouse=True)
    def _isolate_proc_scan(self) -> Iterator[None]:
        # Isolate every test in this class from the REAL /proc: unless a test
        # explicitly patches the scan, it returns None so the status-file-only
        # assertions are not perturbed by a live supervisor on the test host.
        with patch(_SCAN_PATCH, return_value=None):
            yield

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


class TestSupervisorIndicatorProcessScanFallback:
    """Detection must be grounded in the live PROCESS, not just the status file.

    The supervisor's status file was observed going missing while the
    supervisor (``claude-supervise.py --arm``) was still alive, which used to
    make the icon vanish. These tests pin the /proc-scan fallback that keeps the
    indicator lit whenever a live supervisor process exists.
    """

    def test_no_status_file_but_live_armed_process_is_green(self, tmp_path: Path) -> None:
        missing = tmp_path / "nope.json"
        handler = SupervisorIndicatorHandler()
        with (
            patch(_STATUS_PATH_PATCH, return_value=missing),
            patch(_SCAN_PATCH, return_value=(4321, True)),
            patch(_KILL_PATCH, return_value=None),
        ):
            result = handler.handle({})
        assert result.context
        assert _BG_GREEN in result.context[0]
        assert handler._cached_pid == 4321
        assert handler._cached_armed is True

    def test_no_status_file_but_live_dryrun_process_is_yellow(self, tmp_path: Path) -> None:
        missing = tmp_path / "nope.json"
        handler = SupervisorIndicatorHandler()
        with (
            patch(_STATUS_PATH_PATCH, return_value=missing),
            patch(_SCAN_PATCH, return_value=(4321, False)),
            patch(_KILL_PATCH, return_value=None),
        ):
            result = handler.handle({})
        assert _BG_YELLOW in result.context[0]

    def test_no_status_file_and_no_process_renders_nothing(self, tmp_path: Path) -> None:
        missing = tmp_path / "nope.json"
        handler = SupervisorIndicatorHandler()
        with (
            patch(_STATUS_PATH_PATCH, return_value=missing),
            patch(_SCAN_PATCH, return_value=None),
        ):
            result = handler.handle({})
        assert result.context == []

    def test_status_file_dead_pid_but_live_process_is_green(self, tmp_path: Path) -> None:
        # Status file names a dead pid, but a live supervisor exists under a
        # different pid -> the scan fallback keeps the icon green (armed).
        status_file = _write_status(tmp_path, pid=99999)
        handler = SupervisorIndicatorHandler()

        def _kill(pid: int, sig: int) -> None:
            if pid == 99999:
                raise OSError(errno.ESRCH, "No such process")

        with (
            patch(_STATUS_PATH_PATCH, return_value=status_file),
            patch(_KILL_PATCH, side_effect=_kill),
            patch(_SCAN_PATCH, return_value=(4321, True)),
        ):
            result = handler.handle({})
        assert _BG_GREEN in result.context[0]
        assert handler._cached_pid == 4321

    def test_status_file_dead_pid_and_no_process_is_orange(self, tmp_path: Path) -> None:
        status_file = _write_status(tmp_path, pid=99999)
        handler = SupervisorIndicatorHandler()
        with (
            patch(_STATUS_PATH_PATCH, return_value=status_file),
            patch(_KILL_PATCH, side_effect=OSError(errno.ESRCH, "No such process")),
            patch(_SCAN_PATCH, return_value=None),
        ):
            result = handler.handle({})
        assert _BG_ORANGE in result.context[0]


class TestSupervisorIndicatorScanHelper:
    """Directly exercise ``_scan_for_supervisor`` (host vs worker preference)."""

    def test_prefers_host_over_worker(self) -> None:
        handler = SupervisorIndicatorHandler()

        def _cmdline(pid: int) -> str | None:
            if pid == 100:
                return "python3 claude-supervise.py --arm --worker"
            if pid == 200:
                return "python3 claude-supervise.py --arm"
            return None

        with (
            patch(
                "claude_code_hooks_daemon.handlers.status_line.supervisor_indicator."
                "Path.iterdir",
                return_value=[Path("/proc/100"), Path("/proc/200")],
            ),
            patch(_CMDLINE_PATCH, side_effect=_cmdline),
        ):
            found = handler._scan_for_supervisor()
        assert found == (200, True)

    def test_falls_back_to_worker_when_no_host(self) -> None:
        handler = SupervisorIndicatorHandler()

        def _cmdline(pid: int) -> str | None:
            if pid == 100:
                return "python3 claude-supervise.py --worker"
            return None

        with (
            patch(
                "claude_code_hooks_daemon.handlers.status_line.supervisor_indicator."
                "Path.iterdir",
                return_value=[Path("/proc/100"), Path("/proc/xyz")],
            ),
            patch(_CMDLINE_PATCH, side_effect=_cmdline),
        ):
            found = handler._scan_for_supervisor()
        assert found == (100, False)

    def test_keeps_first_worker_when_multiple_workers_no_host(self) -> None:
        # Two workers, no host -> the first worker is retained and the second
        # is skipped (covers the "worker_match already set" loop branch).
        handler = SupervisorIndicatorHandler()

        def _cmdline(pid: int) -> str | None:
            if pid in (100, 200):
                return "python3 claude-supervise.py --arm --worker"
            return None

        with (
            patch(
                "claude_code_hooks_daemon.handlers.status_line.supervisor_indicator."
                "Path.iterdir",
                return_value=[Path("/proc/100"), Path("/proc/200")],
            ),
            patch(_CMDLINE_PATCH, side_effect=_cmdline),
        ):
            found = handler._scan_for_supervisor()
        assert found == (100, True)

    def test_returns_none_when_no_supervisor_process(self) -> None:
        handler = SupervisorIndicatorHandler()
        with (
            patch(
                "claude_code_hooks_daemon.handlers.status_line.supervisor_indicator."
                "Path.iterdir",
                return_value=[Path("/proc/100")],
            ),
            patch(_CMDLINE_PATCH, return_value="python3 unrelated.py"),
        ):
            assert handler._scan_for_supervisor() is None

    def test_returns_none_when_proc_unreadable(self) -> None:
        handler = SupervisorIndicatorHandler()
        with patch(
            "claude_code_hooks_daemon.handlers.status_line.supervisor_indicator.Path.iterdir",
            side_effect=OSError("boom"),
        ):
            assert handler._scan_for_supervisor() is None

    def test_scan_against_real_proc_returns_expected_shape(self) -> None:
        # Smoke test against the real /proc: whatever it finds (or None) must be
        # a well-formed (pid, armed) tuple. This host runs a live supervisor, so
        # this may legitimately return a tuple; assert only the shape.
        handler = SupervisorIndicatorHandler()
        found = handler._scan_for_supervisor()
        assert found is None or (
            isinstance(found, tuple) and isinstance(found[0], int) and isinstance(found[1], bool)
        )


class TestSupervisorIndicatorMemoisation:
    @pytest.fixture(autouse=True)
    def _isolate_proc_scan(self) -> Iterator[None]:
        with patch(_SCAN_PATCH, return_value=None):
            yield

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


class TestSupervisorIndicatorNegativeCaching:
    """A "no live supervisor" resolution is throttled so the expensive /proc scan
    is not repeated on every render for projects that never run the supervisor.
    """

    def test_negative_resolution_not_rescanned_within_window(self, tmp_path: Path) -> None:
        # No status file + no process -> NOT_CONFIGURED. The scan must run once,
        # then be skipped on the next render while inside the throttle window.
        missing = tmp_path / "nope.json"
        handler = SupervisorIndicatorHandler()
        with (
            patch(_STATUS_PATH_PATCH, return_value=missing),
            patch(_SCAN_PATCH, return_value=None) as scan_mock,
            patch(_NOW_PATCH, return_value=1000.0),
        ):
            first = handler.handle({})
            assert scan_mock.call_count == 1
            second = handler.handle({})
            assert scan_mock.call_count == 1  # NOT re-walked within the window
        assert first.context == []
        assert second.context == []

    def test_not_active_resolution_also_throttled(self, tmp_path: Path) -> None:
        # Status file present but pid dead + no process -> NOT_ACTIVE (orange).
        # That negative resolution is throttled the same way.
        status_file = _write_status(tmp_path, pid=99999)
        handler = SupervisorIndicatorHandler()
        with (
            patch(_STATUS_PATH_PATCH, return_value=status_file),
            patch(_KILL_PATCH, side_effect=OSError(errno.ESRCH, "No such process")),
            patch(_SCAN_PATCH, return_value=None) as scan_mock,
            patch(_NOW_PATCH, return_value=1000.0),
        ):
            first = handler.handle({})
            second = handler.handle({})
            assert scan_mock.call_count == 1
        assert _BG_ORANGE in first.context[0]
        assert _BG_ORANGE in second.context[0]

    def test_negative_cache_expires_and_rescans_after_ttl(self, tmp_path: Path) -> None:
        missing = tmp_path / "nope.json"
        handler = SupervisorIndicatorHandler()
        clock = {"t": 1000.0}
        with (
            patch(_STATUS_PATH_PATCH, return_value=missing),
            patch(_SCAN_PATCH, return_value=None) as scan_mock,
            patch(_NOW_PATCH, side_effect=lambda: clock["t"]),
        ):
            handler.handle({})
            assert scan_mock.call_count == 1
            clock["t"] = 1000.0 + _NEGATIVE_CACHE_TTL_SECONDS + 1.0
            handler.handle({})
            assert scan_mock.call_count == 2  # window elapsed -> re-walked

    def test_supervisor_appearing_after_ttl_is_detected_green(self, tmp_path: Path) -> None:
        # First render: nothing live -> negative cached. After the TTL a live
        # armed supervisor appears and must be picked up (green) on re-scan.
        missing = tmp_path / "nope.json"
        handler = SupervisorIndicatorHandler()
        clock = {"t": 1000.0}
        scan_result: dict[str, tuple[int, bool] | None] = {"value": None}
        with (
            patch(_STATUS_PATH_PATCH, return_value=missing),
            patch(_SCAN_PATCH, side_effect=lambda: scan_result["value"]),
            patch(_KILL_PATCH, return_value=None),
            patch(_NOW_PATCH, side_effect=lambda: clock["t"]),
        ):
            first = handler.handle({})
            assert first.context == []
            scan_result["value"] = (4321, True)
            clock["t"] = 1000.0 + _NEGATIVE_CACHE_TTL_SECONDS + 1.0
            second = handler.handle({})
        assert _BG_GREEN in second.context[0]
        assert handler._cached_pid == 4321

    def test_positive_resolution_clears_negative_cache(self, tmp_path: Path) -> None:
        # A live supervisor found on the FIRST render must not leave a negative
        # cache behind; the positive (pid) fast path takes over on later renders.
        missing = tmp_path / "nope.json"
        handler = SupervisorIndicatorHandler()
        with (
            patch(_STATUS_PATH_PATCH, return_value=missing),
            patch(_SCAN_PATCH, return_value=(4321, True)) as scan_mock,
            patch(_KILL_PATCH, return_value=None),
            patch(_NOW_PATCH, return_value=1000.0),
        ):
            handler.handle({})
            assert scan_mock.call_count == 1
            second = handler.handle({})  # pid fast path, no scan
            assert scan_mock.call_count == 1
        assert _BG_GREEN in second.context[0]
        assert handler._negative_cache_until is None


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


class TestSupervisorIndicatorMessage:
    """A transient supervisor message renders ATTACHED to the top hat.

    One segment, one top hat, the message text immediately adjacent on the same
    background (never a separate status section with a second top hat). A
    warning paints the whole block orange with black text for legibility; other
    levels ride the current state background; text is always black.
    """

    def _handle_with_message(
        self,
        tmp_path: Path,
        *,
        text: str,
        expires_at: float,
        level: str,
        wall_now: float,
        state: _SupervisorState,
    ) -> str | None:
        msg = _write_message(tmp_path, text, expires_at, level)
        handler = SupervisorIndicatorHandler()
        with (
            patch(_MESSAGE_PATH_PATCH, return_value=msg),
            patch(_WALL_NOW_PATCH, return_value=wall_now),
            patch(_DETECT_PATCH, return_value=state),
        ):
            result = handler.handle({})
        return result.context[0] if result.context else None

    def test_warning_attaches_to_single_tophat_orange_black(self, tmp_path: Path) -> None:
        segment = self._handle_with_message(
            tmp_path,
            text="⛔ Ctrl+Z ignored — use /exit to quit",
            expires_at=100.0,
            level=_MESSAGE_LEVEL_WARNING,
            wall_now=95.0,
            state=_SupervisorState.ACTIVE_ARMED,
        )
        assert segment is not None
        # Exactly ONE top hat, message adjacent, orange background, black text.
        assert segment.count(_ICON) == 1
        assert "Ctrl+Z ignored" in segment
        assert _BG_ORANGE in segment
        assert _FG_BLACK in segment
        assert segment.endswith(_ANSI_RESET)
        # Warning overrides the active-armed green background entirely.
        assert _BG_GREEN not in segment
        # Top hat comes before the message text (attached, hat first).
        assert segment.index(_ICON) < segment.index("Ctrl+Z ignored")

    def test_info_level_rides_state_background_black_text(self, tmp_path: Path) -> None:
        segment = self._handle_with_message(
            tmp_path,
            text="heads up",
            expires_at=100.0,
            level="info",
            wall_now=95.0,
            state=_SupervisorState.ACTIVE_ARMED,
        )
        assert segment is not None
        assert "heads up" in segment
        assert segment.count(_ICON) == 1
        # Non-warning rides the current state colour (green here), not orange.
        assert _BG_GREEN in segment
        assert _BG_ORANGE not in segment
        assert _FG_BLACK in segment

    def test_expired_message_falls_back_to_plain_state_tophat(self, tmp_path: Path) -> None:
        segment = self._handle_with_message(
            tmp_path,
            text="stale",
            expires_at=100.0,
            level=_MESSAGE_LEVEL_WARNING,
            wall_now=250.0,  # past expiry
            state=_SupervisorState.ACTIVE_ARMED,
        )
        # No message text; plain green top hat as if no message existed.
        assert segment == f"| {_BG_GREEN} {_ICON} {_ANSI_RESET}"

    def test_message_shows_even_when_state_not_configured(self, tmp_path: Path) -> None:
        # A message implies the supervisor was present; render the notice even if
        # state resolution says NOT_CONFIGURED (no status file this instant).
        segment = self._handle_with_message(
            tmp_path,
            text="notice",
            expires_at=100.0,
            level=_MESSAGE_LEVEL_WARNING,
            wall_now=95.0,
            state=_SupervisorState.NOT_CONFIGURED,
        )
        assert segment is not None
        assert _ICON in segment
        assert "notice" in segment
        assert _BG_ORANGE in segment

    def test_absent_message_renders_plain_tophat(self, tmp_path: Path) -> None:
        missing = tmp_path / "status-message.json"
        handler = SupervisorIndicatorHandler()
        with (
            patch(_MESSAGE_PATH_PATCH, return_value=missing),
            patch(_DETECT_PATCH, return_value=_SupervisorState.ACTIVE_ARMED),
        ):
            result = handler.handle({})
        assert result.context == [f"| {_BG_GREEN} {_ICON} {_ANSI_RESET}"]

    def test_malformed_message_ignored_plain_tophat(self, tmp_path: Path) -> None:
        bad = tmp_path / "status-message.json"
        bad.write_text("{not valid json")
        handler = SupervisorIndicatorHandler()
        with (
            patch(_MESSAGE_PATH_PATCH, return_value=bad),
            patch(_DETECT_PATCH, return_value=_SupervisorState.ACTIVE_ARMED),
        ):
            result = handler.handle({})
        assert result.context == [f"| {_BG_GREEN} {_ICON} {_ANSI_RESET}"]

    def test_message_renders_even_if_state_detection_raises(self, tmp_path: Path) -> None:
        # State detection failing must not suppress a live warning notice; the
        # background falls back to orange for a warning level.
        msg = _write_message(tmp_path, "still shown", 100.0, _MESSAGE_LEVEL_WARNING)
        handler = SupervisorIndicatorHandler()
        with (
            patch(_MESSAGE_PATH_PATCH, return_value=msg),
            patch(_WALL_NOW_PATCH, return_value=95.0),
            patch(_DETECT_PATCH, side_effect=RuntimeError("boom")),
        ):
            result = handler.handle({})
        assert len(result.context) == 1
        assert "still shown" in result.context[0]
        assert _BG_ORANGE in result.context[0]

    def test_empty_text_message_ignored_plain_tophat(self, tmp_path: Path) -> None:
        segment = self._handle_with_message(
            tmp_path,
            text="   ",
            expires_at=100.0,
            level=_MESSAGE_LEVEL_WARNING,
            wall_now=95.0,
            state=_SupervisorState.ACTIVE_ARMED,
        )
        assert segment == f"| {_BG_GREEN} {_ICON} {_ANSI_RESET}"
