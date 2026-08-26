"""Tests for skill_scan.state (Plan 00274).

TTL state follows the ``version_check`` cache pattern: state lives under the
daemon untracked dir, a corrupt or missing file is treated as expired (fails
toward a suggestion, never toward silence forever), and write failures are
logged and swallowed.
"""

from __future__ import annotations

from pathlib import Path

from claude_code_hooks_daemon.skill_scan.state import (
    is_advisory_due,
    load_state,
    record_attempt,
    record_success,
)

_DAY = 86_400.0


class TestLoadState:
    def test_missing_file_yields_empty_state(self, tmp_path: Path) -> None:
        state = load_state(tmp_path / "absent.json")
        assert state.last_scan_at is None
        assert state.last_attempt_at is None
        assert state.last_report_path is None

    def test_corrupt_file_yields_empty_state(self, tmp_path: Path) -> None:
        path = tmp_path / "state.json"
        path.write_text("{not json")
        state = load_state(path)
        assert state.last_scan_at is None

    def test_wrong_types_yield_empty_fields(self, tmp_path: Path) -> None:
        path = tmp_path / "state.json"
        path.write_text('{"last_scan_at": "nope", "last_report_path": 42}')
        state = load_state(path)
        assert state.last_scan_at is None
        assert state.last_report_path is None


class TestRecording:
    def test_record_success_round_trips(self, tmp_path: Path) -> None:
        path = tmp_path / "state.json"
        record_success(path, report_path="/reports/r.md", now=1000.0)
        state = load_state(path)
        assert state.last_scan_at == 1000.0
        assert state.last_attempt_at == 1000.0
        assert state.last_report_path == "/reports/r.md"

    def test_record_attempt_leaves_last_scan_untouched(self, tmp_path: Path) -> None:
        path = tmp_path / "state.json"
        record_success(path, report_path="/r.md", now=1000.0)
        record_attempt(path, now=2000.0)
        state = load_state(path)
        assert state.last_scan_at == 1000.0
        assert state.last_attempt_at == 2000.0
        assert state.last_report_path == "/r.md"

    def test_write_failure_is_swallowed(self, tmp_path: Path) -> None:
        record_attempt(tmp_path / "no-such-dir-parent-is-file" / "x.json", now=1.0)
        # parent creation failing must not raise
        blocker = tmp_path / "blocker"
        blocker.write_text("file, not dir")
        record_attempt(blocker / "state.json", now=1.0)


class TestIsAdvisoryDue:
    def test_no_state_is_due(self, tmp_path: Path) -> None:
        state = load_state(tmp_path / "absent.json")
        assert is_advisory_due(state, interval_days=7, now=100.0) is True

    def test_recent_scan_not_due(self, tmp_path: Path) -> None:
        path = tmp_path / "state.json"
        record_success(path, report_path="/r.md", now=1000.0)
        assert is_advisory_due(load_state(path), interval_days=7, now=1000.0 + _DAY) is False

    def test_stale_scan_due(self, tmp_path: Path) -> None:
        path = tmp_path / "state.json"
        record_success(path, report_path="/r.md", now=1000.0)
        assert (
            is_advisory_due(load_state(path), interval_days=7, now=1000.0 + 8 * _DAY) is True
        )

    def test_recent_failed_attempt_quietens_the_advisory(self, tmp_path: Path) -> None:
        # A permanently-offline box must not be nagged every session: a recent
        # ATTEMPT (even without success) suppresses the advisory for a day.
        path = tmp_path / "state.json"
        record_attempt(path, now=1000.0)
        state = load_state(path)
        assert is_advisory_due(state, interval_days=7, now=1000.0 + 3600.0) is False
        assert is_advisory_due(state, interval_days=7, now=1000.0 + 2 * _DAY) is True
