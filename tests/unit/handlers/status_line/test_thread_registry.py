"""Unit tests for the multithread-indicator thread registry (Plan 00158 Phase 6).

These cover the *pure* registry helpers in isolation from the Handler:

- ``safe_session_stem``  — path-safe filename stem for an untrusted session id
- ``upsert_heartbeat``   — atomic per-session write that PRESERVES first_seen
- ``read_live_entries``  — read all heartbeats, pruning stale/garbled ones
- ``compute_indicator``  — count + stable rank → ``🧵 Y/X`` (or "" when alone)

The audit verdict (Plan 00158 Truth #6) mandates that every artifact is keyed
by ``session_id`` and written atomically, never via shared global state — these
helpers are that mechanism, so the tests assert the keying and atomicity too.
"""

import json
from pathlib import Path

from claude_code_hooks_daemon.handlers.status_line.thread_registry import (
    _FRESH_WINDOW_S,
    _SESSION_ID_FALLBACK,
    compute_indicator,
    read_live_entries,
    safe_session_stem,
    upsert_heartbeat,
)


class TestSafeSessionStem:
    def test_uuid_passes_through_unchanged(self) -> None:
        sid = "2b651a46-3737-478c-bd8f-3a1965557dbd"
        assert safe_session_stem(sid) == sid

    def test_empty_falls_back(self) -> None:
        assert safe_session_stem("") == _SESSION_ID_FALLBACK

    def test_path_separators_are_neutralised(self) -> None:
        assert safe_session_stem("../../etc/passwd") == ".._.._etc_passwd"


class TestUpsertHeartbeat:
    def test_creates_file_keyed_by_session_id(self, tmp_path: Path) -> None:
        upsert_heartbeat(tmp_path, "sess-a", "name-a", None, now=100.0)
        written = tmp_path / "sess-a.json"
        assert written.exists()
        entry = json.loads(written.read_text(encoding="utf-8"))
        assert entry["session_id"] == "sess-a"
        assert entry["first_seen"] == 100.0
        assert entry["last_seen"] == 100.0
        assert entry["session_name"] == "name-a"
        assert entry["agent_type"] is None

    def test_second_render_preserves_first_seen_but_advances_last_seen(
        self, tmp_path: Path
    ) -> None:
        upsert_heartbeat(tmp_path, "sess-a", "name-a", None, now=100.0)
        upsert_heartbeat(tmp_path, "sess-a", "name-a", None, now=175.0)
        entry = json.loads((tmp_path / "sess-a.json").read_text(encoding="utf-8"))
        assert entry["first_seen"] == 100.0  # preserved across renders
        assert entry["last_seen"] == 175.0  # advanced to the newest render

    def test_leaves_no_tmp_files_behind(self, tmp_path: Path) -> None:
        upsert_heartbeat(tmp_path, "sess-a", "name-a", None, now=100.0)
        leftovers = [p.name for p in tmp_path.iterdir() if p.name != "sess-a.json"]
        assert leftovers == []

    def test_garbled_prior_file_does_not_crash_and_resets_first_seen(self, tmp_path: Path) -> None:
        (tmp_path / "sess-a.json").write_text("{not json", encoding="utf-8")
        upsert_heartbeat(tmp_path, "sess-a", "name-a", None, now=200.0)
        entry = json.loads((tmp_path / "sess-a.json").read_text(encoding="utf-8"))
        assert entry["first_seen"] == 200.0

    def test_non_numeric_prior_first_seen_resets_to_now(self, tmp_path: Path) -> None:
        # A valid JSON prior whose first_seen is not a number must not be trusted.
        (tmp_path / "sess-a.json").write_text(
            json.dumps({"first_seen": "bogus", "last_seen": 5.0}), encoding="utf-8"
        )
        upsert_heartbeat(tmp_path, "sess-a", "name-a", None, now=300.0)
        entry = json.loads((tmp_path / "sess-a.json").read_text(encoding="utf-8"))
        assert entry["first_seen"] == 300.0


class TestReadLiveEntries:
    def test_missing_dir_returns_empty(self, tmp_path: Path) -> None:
        assert read_live_entries(tmp_path / "nope", now=100.0) == []

    def test_prunes_stale_entries(self, tmp_path: Path) -> None:
        upsert_heartbeat(tmp_path, "fresh", "f", None, now=100.0)
        upsert_heartbeat(tmp_path, "stale", "s", None, now=10.0)
        live = read_live_entries(tmp_path, now=100.0, window_s=_FRESH_WINDOW_S)
        ids = {e["session_id"] for e in live}
        assert ids == {"fresh"}

    def test_keeps_entry_exactly_on_the_window_boundary(self, tmp_path: Path) -> None:
        upsert_heartbeat(tmp_path, "edge", "e", None, now=100.0)
        live = read_live_entries(tmp_path, now=100.0 + _FRESH_WINDOW_S, window_s=_FRESH_WINDOW_S)
        assert {e["session_id"] for e in live} == {"edge"}

    def test_skips_non_json_and_garbled_files(self, tmp_path: Path) -> None:
        upsert_heartbeat(tmp_path, "good", "g", None, now=100.0)
        (tmp_path / "note.txt").write_text("ignore me", encoding="utf-8")
        (tmp_path / "broken.json").write_text("{oops", encoding="utf-8")
        live = read_live_entries(tmp_path, now=100.0)
        assert {e["session_id"] for e in live} == {"good"}

    def test_skips_entry_with_non_numeric_last_seen(self, tmp_path: Path) -> None:
        upsert_heartbeat(tmp_path, "good", "g", None, now=100.0)
        (tmp_path / "weird.json").write_text(
            json.dumps({"session_id": "weird", "last_seen": "soon"}), encoding="utf-8"
        )
        live = read_live_entries(tmp_path, now=100.0)
        assert {e["session_id"] for e in live} == {"good"}


class TestComputeIndicator:
    def test_single_thread_renders_nothing(self) -> None:
        entries = [{"session_id": "solo", "first_seen": 1.0}]
        assert compute_indicator(entries, "solo") == ""

    def test_empty_renders_nothing(self) -> None:
        assert compute_indicator([], "solo") == ""

    def test_two_threads_render_rank_and_total(self) -> None:
        entries = [
            {"session_id": "a", "first_seen": 1.0},
            {"session_id": "b", "first_seen": 2.0},
        ]
        assert compute_indicator(entries, "a") == "🧵 1/2"
        assert compute_indicator(entries, "b") == "🧵 2/2"

    def test_rank_is_stable_by_first_seen_regardless_of_read_order(self) -> None:
        # Registry iteration order is filesystem-dependent; rank must be by
        # first_seen so a thread keeps the same number for its whole lifetime.
        entries = [
            {"session_id": "late", "first_seen": 30.0},
            {"session_id": "early", "first_seen": 10.0},
            {"session_id": "mid", "first_seen": 20.0},
        ]
        assert compute_indicator(entries, "early") == "🧵 1/3"
        assert compute_indicator(entries, "mid") == "🧵 2/3"
        assert compute_indicator(entries, "late") == "🧵 3/3"

    def test_tie_on_first_seen_breaks_by_session_id_deterministically(self) -> None:
        entries = [
            {"session_id": "zzz", "first_seen": 5.0},
            {"session_id": "aaa", "first_seen": 5.0},
        ]
        assert compute_indicator(entries, "aaa") == "🧵 1/2"
        assert compute_indicator(entries, "zzz") == "🧵 2/2"

    def test_unknown_session_in_crowd_renders_nothing(self) -> None:
        entries = [
            {"session_id": "a", "first_seen": 1.0},
            {"session_id": "b", "first_seen": 2.0},
        ]
        assert compute_indicator(entries, "ghost") == ""
