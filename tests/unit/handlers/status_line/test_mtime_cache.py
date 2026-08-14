"""Tests for the shared mtime-gated file cache (Plan 00238 Phase 3).

Four status-line handlers read a small file on EVERY render, forever, with no
cache of any kind — ~9,000-12,500 avoidable file operations/hour at the
measured render rate, for values that almost never change (an account
username: effectively never; an upgrade cache: at most daily).

``settings_reader.py`` already solved this for one file. Rather than
copy-pasting its mtime gate three more times, the gate moves here and
``settings_reader`` becomes a caller — so there is ONE implementation to reason
about, and a bug in it is one fix rather than four.
"""

from pathlib import Path

from claude_code_hooks_daemon.handlers.status_line.mtime_cache import MtimeCachedFile

_MISSING = "<<absent>>"


def _reader() -> MtimeCachedFile[str]:
    return MtimeCachedFile(parse=lambda text: text.strip(), default=_MISSING)


class TestCachesUntilMtimeChanges:
    def test_first_read_parses(self, tmp_path: Path) -> None:
        target = tmp_path / "f.conf"
        target.write_text("alpha\n")

        assert _reader().read(target) == "alpha"

    def test_second_read_does_not_reparse(self, tmp_path: Path) -> None:
        """The whole point — pin that the parse is SKIPPED, not just correct.

        Asserting the returned value alone would pass just as happily with no
        cache at all, which is exactly the vacuous check this plan keeps
        finding.
        """
        target = tmp_path / "f.conf"
        target.write_text("alpha\n")
        calls = 0

        def parse(text: str) -> str:
            nonlocal calls
            calls += 1
            return text.strip()

        reader = MtimeCachedFile(parse=parse, default=_MISSING)
        reader.read(target)
        reader.read(target)
        reader.read(target)

        assert calls == 1

    def test_a_changed_mtime_reparses(self, tmp_path: Path) -> None:
        target = tmp_path / "f.conf"
        target.write_text("alpha\n")
        reader = _reader()
        assert reader.read(target) == "alpha"

        target.write_text("beta\n")
        # Filesystem mtime granularity can be coarse; force a distinct stamp so
        # the test proves invalidation rather than accidentally reading a
        # same-mtime write.
        stat = target.stat()
        import os

        os.utime(target, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))

        assert reader.read(target) == "beta"


class TestFailsSilently:
    """A broken status line is worse than a missing element (see the
    directory's CLAUDE.md concurrency rules) — every failure yields the
    default, never an exception."""

    def test_missing_file_returns_the_default(self, tmp_path: Path) -> None:
        assert _reader().read(tmp_path / "nope.conf") == _MISSING

    def test_a_parse_failure_returns_the_default(self, tmp_path: Path) -> None:
        target = tmp_path / "f.conf"
        target.write_text("anything")

        def explode(_text: str) -> str:
            raise ValueError("bad content")

        assert MtimeCachedFile(parse=explode, default=_MISSING).read(target) == _MISSING

    def test_a_parse_failure_is_not_cached_as_success(self, tmp_path: Path) -> None:
        """A transient read of a half-written file must not poison the cache.

        Status-line files are written by other processes (the ccy supervisor
        among them). Caching a failure as if it were the value would keep
        showing nothing until the file's mtime happened to change again.
        """
        target = tmp_path / "f.conf"
        target.write_text("good")
        fail_next = True

        def parse(text: str) -> str:
            nonlocal fail_next
            if fail_next:
                fail_next = False
                raise ValueError("transient")
            return text

        reader = MtimeCachedFile(parse=parse, default=_MISSING)
        assert reader.read(target) == _MISSING
        assert reader.read(target) == "good"


class TestCacheIsBounded:
    def test_one_entry_per_path(self, tmp_path: Path) -> None:
        """A long-lived daemon must not accumulate entries without bound."""
        reader = _reader()
        for name in ("a", "b", "c"):
            target = tmp_path / f"{name}.conf"
            target.write_text(name)
            reader.read(target)
            reader.read(target)

        assert len(reader._cache) == 3

    def test_clear_empties_it(self, tmp_path: Path) -> None:
        target = tmp_path / "f.conf"
        target.write_text("alpha")
        reader = _reader()
        reader.read(target)

        reader.clear()

        assert not reader._cache
