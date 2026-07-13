"""Tests for dead-file reaping in the standalone supervisor (Plan 00160 Phase 1).

Nothing ever cleaned up the per-session ``{session}.json`` context sidecars or
``{session}.compacting`` signals: a live dir accumulated 17 files, most dead for
days, plus test fixtures. The reaper deletes files whose mtime is older than a
TTL (>> the freshness and compaction-signal windows, so an aged file is
definitively from a closed session and never still actionable), while ALWAYS
sparing the single newest ``*.json`` — the supervisor's current reading source —
so it is never removed even when every session is dead.
"""

import json
import os
from pathlib import Path

import pytest

from tests.unit.supervise._load import load_supervisor_module

_mod = load_supervisor_module()

_NOW = 1_000_000.0
_TTL = 1800.0  # matches the supervisor's default reap TTL


def _write(path: Path, *, ts: float, age: float, now: float = _NOW) -> Path:
    """Create a sidecar/signal file with content ts and a back-dated mtime."""
    path.write_text(json.dumps({"ts": ts, "session_id": path.stem}), encoding="utf-8")
    mtime = now - age
    os.utime(path, (mtime, mtime))
    return path


class TestReapStaleSidecars:
    def test_reaps_json_and_compacting_older_than_ttl(self, tmp_path: Path) -> None:
        dead_json = _write(tmp_path / "dead.json", ts=_NOW - 5000, age=5000)
        dead_sig = _write(tmp_path / "dead.compacting", ts=_NOW - 5000, age=5000)
        # A fresh foreground sidecar so a newer json exists to spare.
        fresh = _write(tmp_path / "fresh.json", ts=_NOW - 5, age=5)

        reaped = _mod.reap_stale_sidecars(tmp_path, now=_NOW, ttl_seconds=_TTL)

        assert set(reaped) == {dead_json, dead_sig}
        assert not dead_json.exists()
        assert not dead_sig.exists()
        assert fresh.exists()

    def test_spares_files_within_ttl(self, tmp_path: Path) -> None:
        young = _write(tmp_path / "young.json", ts=_NOW - 100, age=100)
        young_sig = _write(tmp_path / "young.compacting", ts=_NOW - 100, age=100)

        reaped = _mod.reap_stale_sidecars(tmp_path, now=_NOW, ttl_seconds=_TTL)

        assert reaped == []
        assert young.exists()
        assert young_sig.exists()

    def test_always_spares_the_newest_json_even_when_all_dead(self, tmp_path: Path) -> None:
        """All sessions dead: keep exactly the freshest json (bounded residue)."""
        older = _write(tmp_path / "older.json", ts=_NOW - 9000, age=9000)
        newest = _write(tmp_path / "newest.json", ts=_NOW - 4000, age=4000)

        reaped = _mod.reap_stale_sidecars(tmp_path, now=_NOW, ttl_seconds=_TTL)

        assert reaped == [older]
        assert not older.exists()
        assert newest.exists()  # spared despite being older than TTL

    def test_newest_json_spared_but_stale_compacting_still_reaped(self, tmp_path: Path) -> None:
        newest = _write(tmp_path / "newest.json", ts=_NOW - 4000, age=4000)
        dead_sig = _write(tmp_path / "dead.compacting", ts=_NOW - 4000, age=4000)

        reaped = _mod.reap_stale_sidecars(tmp_path, now=_NOW, ttl_seconds=_TTL)

        assert reaped == [dead_sig]
        assert newest.exists()
        assert not dead_sig.exists()

    def test_malformed_file_reaped_by_mtime_without_parse(self, tmp_path: Path) -> None:
        """A file that is not valid JSON is still reaped on age (mtime-based)."""
        bad = tmp_path / "bad.json"
        bad.write_text("{not json", encoding="utf-8")
        mtime = _NOW - 5000
        os.utime(bad, (mtime, mtime))
        # A spare newest json so `bad` is not protected as the freshest.
        _write(tmp_path / "fresh.json", ts=_NOW - 5, age=5)

        reaped = _mod.reap_stale_sidecars(tmp_path, now=_NOW, ttl_seconds=_TTL)

        assert bad in reaped
        assert not bad.exists()

    def test_ignores_tmp_and_foreign_files(self, tmp_path: Path) -> None:
        """Atomic-write temp files and unrelated files are never touched."""
        tmp = tmp_path / ".fresh.1234.tmp"
        tmp.write_text("{}", encoding="utf-8")
        mtime = _NOW - 5000
        os.utime(tmp, (mtime, mtime))
        other = tmp_path / "decision.log"
        other.write_text("log", encoding="utf-8")
        os.utime(other, (mtime, mtime))
        _write(tmp_path / "fresh.json", ts=_NOW - 5, age=5)

        _mod.reap_stale_sidecars(tmp_path, now=_NOW, ttl_seconds=_TTL)

        assert tmp.exists()
        assert other.exists()

    def test_missing_directory_returns_empty(self, tmp_path: Path) -> None:
        assert _mod.reap_stale_sidecars(tmp_path / "nope", now=_NOW, ttl_seconds=_TTL) == []

    def test_unlink_race_is_tolerated(self, tmp_path: Path) -> None:
        """A file vanishing between stat and unlink does not raise."""
        dead = _write(tmp_path / "dead.json", ts=_NOW - 5000, age=5000)
        _write(tmp_path / "fresh.json", ts=_NOW - 5, age=5)
        # missing_ok=True means a concurrently-removed file is a no-op, not a crash.
        dead.unlink()

        reaped = _mod.reap_stale_sidecars(tmp_path, now=_NOW, ttl_seconds=_TTL)

        assert dead not in reaped  # already gone; nothing to report

    def test_default_ttl_constant_is_large(self) -> None:
        """The default reap TTL is well beyond freshness and the signal TTL."""
        assert _mod._DEFAULT_REAP_TTL_SECONDS >= _mod._DEFAULT_COMPACTION_SIGNAL_TTL_SECONDS
        assert _mod._DEFAULT_REAP_TTL_SECONDS > _mod._DEFAULT_FRESHNESS_SECONDS

    def test_logs_summary_when_files_are_reaped(self, tmp_path: Path) -> None:
        dead = _write(tmp_path / "dead.json", ts=_NOW - 5000, age=5000)
        _write(tmp_path / "fresh.json", ts=_NOW - 5, age=5)
        log_path = tmp_path / "decision.log"
        log = _mod.DecisionLog(log_path)

        reaped = _mod.reap_stale_sidecars(tmp_path, now=_NOW, ttl_seconds=_TTL, log=log)

        assert reaped == [dead]
        assert "reaped 1 stale sidecar/signal file(s)" in log_path.read_text(encoding="utf-8")

    def test_unlink_error_is_logged_not_raised(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A genuine unlink failure is logged and skipped, never propagated.

        Only ``dead.json`` is a reap candidate here (``fresh.json`` is the spared
        freshest and is never unlinked), so a stub that always raises exercises
        exactly the reaper's unlink-error branch.
        """
        dead = _write(tmp_path / "dead.json", ts=_NOW - 5000, age=5000)
        _write(tmp_path / "fresh.json", ts=_NOW - 5, age=5)
        log_path = tmp_path / "decision.log"
        log = _mod.DecisionLog(log_path)

        def _boom(self: Path, **kwargs: object) -> None:
            raise OSError("permission denied")

        monkeypatch.setattr(Path, "unlink", _boom)

        reaped = _mod.reap_stale_sidecars(tmp_path, now=_NOW, ttl_seconds=_TTL, log=log)

        assert dead not in reaped  # unlink failed -> not reported as reaped
        assert dead.exists()  # still there
        assert "could not reap stale file" in log_path.read_text(encoding="utf-8")
