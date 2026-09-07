"""Tests for the failsafe-cron cadence primitive (Plan 00337 Phase 4).

The per-session record of how many cron ticks have been dropped since one was
last allowed, and how sparse the current cadence is.

Modelled deliberately on ``test_blockage_marker.py``'s contract: every
read/write path fails OPEN, because a cadence bug that denied every tick would
silently disable session recovery -- the worst failure this subsystem has,
since its symptom is nothing happening.
"""

from pathlib import Path

from claude_code_hooks_daemon.utils.cron_cadence import (
    CADENCE_FILENAME,
    MAX_CADENCE_HOURS,
    CadenceState,
    next_tick_decision,
    read_cadence,
    reset_cadence,
    write_cadence,
)


class TestRoundTrip:
    def test_write_then_read_returns_the_same_state(self, tmp_path: Path) -> None:
        path = tmp_path / CADENCE_FILENAME
        write_cadence(path, CadenceState("sess-1", dropped_since_allowed=2, cadence_hours=4))
        assert read_cadence(path) == CadenceState("sess-1", 2, 4)

    def test_missing_file_reads_as_none(self, tmp_path: Path) -> None:
        assert read_cadence(tmp_path / CADENCE_FILENAME) is None

    def test_corrupt_file_reads_as_none(self, tmp_path: Path) -> None:
        path = tmp_path / CADENCE_FILENAME
        path.write_text("{not json", encoding="utf-8")
        assert read_cadence(path) is None

    def test_wrong_shape_reads_as_none(self, tmp_path: Path) -> None:
        path = tmp_path / CADENCE_FILENAME
        path.write_text('["a", "list"]', encoding="utf-8")
        assert read_cadence(path) is None

    def test_a_boolean_is_not_accepted_as_a_count(self, tmp_path: Path) -> None:
        """bool subclasses int, so a JSON `true` would silently become 1.

        A file we did not write is a file we cannot trust -- reject it rather
        than coerce, so a corrupt state cannot quietly become a valid one.
        """
        path = tmp_path / CADENCE_FILENAME
        path.write_text(
            '{"session_id": "s", "dropped_since_allowed": true, "cadence_hours": 1}',
            encoding="utf-8",
        )
        assert read_cadence(path) is None

    def test_a_nonsensical_cadence_reads_as_none(self, tmp_path: Path) -> None:
        path = tmp_path / CADENCE_FILENAME
        path.write_text(
            '{"session_id": "s", "dropped_since_allowed": -1, "cadence_hours": 0}',
            encoding="utf-8",
        )
        assert read_cadence(path) is None

    def test_a_cadence_beyond_the_cap_is_clamped(self, tmp_path: Path) -> None:
        """A state file written by a future version with a higher cap must not
        make THIS version sparser than its own ceiling allows."""
        path = tmp_path / CADENCE_FILENAME
        path.write_text(
            '{"session_id": "s", "dropped_since_allowed": 0, "cadence_hours": 999}',
            encoding="utf-8",
        )
        state = read_cadence(path)
        assert state is not None
        assert state.cadence_hours == MAX_CADENCE_HOURS

    def test_unwritable_parent_is_swallowed(self, tmp_path: Path) -> None:
        # A file where the parent directory should be -- mkdir must fail.
        blocker = tmp_path / "blocker"
        blocker.write_text("x", encoding="utf-8")
        assert write_cadence(blocker / CADENCE_FILENAME, CadenceState("s", 0, 1)) is False


class TestDecision:
    """The Phase 4 backoff, expressed as pure arithmetic over the state.

    Kept as a free function rather than handler logic so the truth table can be
    tested without a hook input, a marker file or a project context.
    """

    def test_first_backoff_tick_is_allowed_at_hourly_cadence(self) -> None:
        allow, nxt = next_tick_decision(CadenceState("s", 0, 1), session_id="s")
        assert allow is True
        assert nxt.dropped_since_allowed == 0
        assert nxt.cadence_hours == 2

    def test_a_two_hour_cadence_drops_one_tick_then_allows(self) -> None:
        allow, nxt = next_tick_decision(CadenceState("s", 0, 2), session_id="s")
        assert allow is False
        assert nxt.dropped_since_allowed == 1
        assert nxt.cadence_hours == 2

        allow, nxt = next_tick_decision(nxt, session_id="s")
        assert allow is True
        assert nxt.dropped_since_allowed == 0
        assert nxt.cadence_hours == 4

    def test_cadence_is_capped_and_never_becomes_silence(self) -> None:
        state = CadenceState("s", 0, MAX_CADENCE_HOURS)
        for _ in range(MAX_CADENCE_HOURS - 1):
            allow, state = next_tick_decision(state, session_id="s")
            assert allow is False
        allow, state = next_tick_decision(state, session_id="s")
        assert allow is True
        assert state.cadence_hours == MAX_CADENCE_HOURS

    def test_twelve_consecutive_ticks_deliver_four(self) -> None:
        """The whole point, asserted as the observable pattern rather than as
        three separate invariants: hourly, then every 2h, then every 4h."""
        state = None
        delivered = []
        for hour in range(1, 13):
            allow, state = next_tick_decision(state, session_id="s")
            if allow:
                delivered.append(hour)
        assert delivered == [1, 3, 7, 11]

    def test_no_state_yet_allows(self) -> None:
        allow, nxt = next_tick_decision(None, session_id="s")
        assert allow is True
        assert nxt.session_id == "s"

    def test_state_from_another_session_is_ignored(self) -> None:
        """The daemon outlives any one session; inheriting a stale backoff
        would withdraw the safety net from a session that never earned it."""
        allow, nxt = next_tick_decision(CadenceState("other", 5, 4), session_id="s")
        assert allow is True
        assert nxt.session_id == "s"
        assert nxt.cadence_hours == 2


class TestReset:
    def test_reset_removes_the_file(self, tmp_path: Path) -> None:
        path = tmp_path / CADENCE_FILENAME
        write_cadence(path, CadenceState("s", 3, 4))
        reset_cadence(path)
        assert read_cadence(path) is None

    def test_reset_on_missing_file_is_a_no_op(self, tmp_path: Path) -> None:
        reset_cadence(tmp_path / CADENCE_FILENAME)
