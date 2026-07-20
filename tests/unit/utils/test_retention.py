"""Tests for the shared disk-usage retention primitives (Plan 00181).

Two primitives bound the daemon's untracked writers:
  * ``cap_log_file``   -- front-truncate an append-only line log to a byte cap,
                          keeping the NEWEST whole lines.
  * ``prune_directory``-- bound a directory to a max count and/or max age,
                          newest kept, protected paths never touched.
Both are best-effort housekeeping: a missing file/dir is a no-op, never a raise.
"""

from __future__ import annotations

import os
from pathlib import Path

from claude_code_hooks_daemon.utils.retention import cap_log_file, prune_directory


def _write(path: Path, text: str, *, mtime: float | None = None) -> Path:
    path.write_text(text, encoding="utf-8")
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


# ── cap_log_file ─────────────────────────────────────────────────────────────


class TestCapLogFile:
    def test_under_cap_is_noop(self, tmp_path: Path) -> None:
        f = _write(tmp_path / "log.jsonl", "a\nb\nc\n")
        assert cap_log_file(f, max_bytes=1000) is False
        assert f.read_text(encoding="utf-8") == "a\nb\nc\n"

    def test_over_cap_keeps_newest_whole_lines(self, tmp_path: Path) -> None:
        # 10 lines "line0\n".."line9\n" (6 bytes each = 60 bytes). Cap at 20
        # bytes -> keep the last whole lines that fit, dropping the partial head.
        f = _write(tmp_path / "log.jsonl", "".join(f"line{i}\n" for i in range(10)))
        assert cap_log_file(f, max_bytes=20) is True
        out = f.read_text(encoding="utf-8")
        assert f.stat().st_size <= 20
        # Only whole lines, and they are the NEWEST ones.
        assert out.endswith("line9\n")
        assert "line0" not in out
        for line in out.splitlines():
            assert line.startswith("line")

    def test_missing_file_is_noop(self, tmp_path: Path) -> None:
        assert cap_log_file(tmp_path / "nope.jsonl", max_bytes=10) is False

    def test_exact_cap_is_noop(self, tmp_path: Path) -> None:
        f = _write(tmp_path / "log.jsonl", "abcde")  # 5 bytes
        assert cap_log_file(f, max_bytes=5) is False
        assert f.read_text(encoding="utf-8") == "abcde"

    def test_single_line_larger_than_cap_keeps_tail(self, tmp_path: Path) -> None:
        # Pathological: one line longer than the cap. Keep the last max_bytes
        # rather than emptying the file (documented edge behaviour).
        f = _write(tmp_path / "log.jsonl", "x" * 100)
        assert cap_log_file(f, max_bytes=10) is True
        assert f.stat().st_size <= 10


# ── prune_directory ──────────────────────────────────────────────────────────


class TestPruneDirectory:
    def test_keeps_newest_max_count(self, tmp_path: Path) -> None:
        for i in range(5):
            _write(tmp_path / f"t{i}.json", "x", mtime=1000.0 + i)  # t4 newest
        deleted = prune_directory(tmp_path, pattern="*.json", max_count=2, now=2000.0)
        names = {p.name for p in deleted}
        assert names == {"t0.json", "t1.json", "t2.json"}  # oldest 3 gone
        assert (tmp_path / "t3.json").exists() and (tmp_path / "t4.json").exists()

    def test_deletes_older_than_max_age(self, tmp_path: Path) -> None:
        _write(tmp_path / "old.json", "x", mtime=1000.0)
        _write(tmp_path / "new.json", "x", mtime=1990.0)
        deleted = prune_directory(tmp_path, pattern="*.json", max_age_seconds=100.0, now=2000.0)
        assert {p.name for p in deleted} == {"old.json"}
        assert (tmp_path / "new.json").exists()

    def test_protected_path_never_deleted(self, tmp_path: Path) -> None:
        keep = _write(tmp_path / "keep.json", "x", mtime=1000.0)  # oldest
        _write(tmp_path / "other.json", "x", mtime=1500.0)
        deleted = prune_directory(
            tmp_path, pattern="*.json", max_count=1, now=2000.0, protect=(keep,)
        )
        assert keep.exists()
        assert keep not in deleted

    def test_missing_directory_is_noop(self, tmp_path: Path) -> None:
        assert prune_directory(tmp_path / "nope", pattern="*", max_count=1, now=1.0) == []

    def test_no_criteria_deletes_nothing(self, tmp_path: Path) -> None:
        _write(tmp_path / "a.json", "x", mtime=1.0)
        assert prune_directory(tmp_path, pattern="*.json", now=2000.0) == []
        assert (tmp_path / "a.json").exists()

    def test_count_or_age_union(self, tmp_path: Path) -> None:
        # count=3 keeps newest 3, but age also drops anything older than 100s.
        for i in range(5):
            _write(tmp_path / f"t{i}.json", "x", mtime=1000.0 + i * 10)  # t4 = 1040
        deleted = prune_directory(
            tmp_path,
            pattern="*.json",
            max_count=3,
            max_age_seconds=25.0,
            now=1040.0,
        )
        # newest 3 by count = t2,t3,t4; but age>25 from now(1040): t0(1000),t1(1010)
        # -> also drop anything older than 1015. t2=1020 within age+within count.
        # deleted = count-excess (t0,t1) UNION age-excess (t0,t1) = {t0,t1}.
        assert {p.name for p in deleted} == {"t0.json", "t1.json"}

    def test_only_matches_pattern(self, tmp_path: Path) -> None:
        _write(tmp_path / "keep.txt", "x", mtime=1.0)
        _write(tmp_path / "drop.json", "x", mtime=1.0)
        deleted = prune_directory(tmp_path, pattern="*.json", max_age_seconds=1.0, now=1000.0)
        assert {p.name for p in deleted} == {"drop.json"}
        assert (tmp_path / "keep.txt").exists()
