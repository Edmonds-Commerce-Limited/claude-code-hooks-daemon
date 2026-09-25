"""Tests for the shared, mtime-invalidated config accessor.

Plan 00440, from ledger 00422 N5 row (b). ``Config.load_or_default`` measures
76 ms median on this repository's config, and ``cron_stop_enforcer`` calls it
from both ``matches()`` and ``handle()`` — ``matches()`` on every Stop event.

Two properties matter and pull against each other: a second load of an
unchanged file must not re-parse, and an operator editing the file must see the
change on the next event without restarting a daemon that may have been up for
days. Both are tested here, as is the lock — dispatch runs on a thread pool
(``daemon/server.py:1443``), so an unguarded cache is the hazard Plan 00437
measured on a different daemon-lifetime singleton.
"""

from __future__ import annotations

import concurrent.futures
import copy
import os
import pickle
import sys
import threading
from pathlib import Path
from typing import Final
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.config.models import Config
from claude_code_hooks_daemon.utils.config_cache import (
    CachedConfigLoadError,
    load_config_cached,
    reset_config_cache,
)

_YAML: Final[str] = "daemon:\n  enabled: true\n"
_OTHER_YAML: Final[str] = "daemon:\n  enabled: false\n"
_BROKEN_YAML: Final[str] = "daemon: [unterminated\n"


@pytest.fixture(autouse=True)
def _clean_cache() -> None:
    """Every test starts from an empty cache; the cache is process-global."""
    reset_config_cache()


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


class TestAnUnchangedFileIsParsedOnce:
    def test_a_second_call_returns_the_same_object(self, tmp_path: Path) -> None:
        config_file = tmp_path / "hooks-daemon.yaml"
        _write(config_file, _YAML)

        first = load_config_cached(config_file)
        second = load_config_cached(config_file)

        assert first is second

    def test_a_missing_file_is_cached_as_defaults(self, tmp_path: Path) -> None:
        """``load_or_default`` tolerates absence; so must the cache."""
        absent = tmp_path / "nothing-here.yaml"

        first = load_config_cached(absent)
        second = load_config_cached(absent)

        assert first is second

    def test_two_different_paths_do_not_share_an_entry(self, tmp_path: Path) -> None:
        one = tmp_path / "one.yaml"
        two = tmp_path / "two.yaml"
        _write(one, _YAML)
        _write(two, _OTHER_YAML)

        assert load_config_cached(one) is not load_config_cached(two)


class TestAnEditedFileIsReparsed:
    """A long-lived daemon must not pin a config an operator has since changed."""

    def test_a_changed_mtime_forces_a_reparse(self, tmp_path: Path) -> None:
        config_file = tmp_path / "hooks-daemon.yaml"
        _write(config_file, _YAML)
        first = load_config_cached(config_file)

        _write(config_file, _OTHER_YAML)
        # Same byte count would otherwise hide the edit behind an unchanged
        # size; the mtime is what has to catch it, so move it explicitly
        # rather than relying on the filesystem's clock resolution.
        stat = config_file.stat()
        os.utime(config_file, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))

        assert load_config_cached(config_file) is not first

    def test_a_changed_size_forces_a_reparse(self, tmp_path: Path) -> None:
        config_file = tmp_path / "hooks-daemon.yaml"
        _write(config_file, _YAML)
        first = load_config_cached(config_file)
        original = config_file.stat()

        _write(config_file, _YAML + "\n# a comment, so the size differs\n")
        # Pin the mtime back, so SIZE is the only thing that changed and the
        # test cannot pass for the other reason.
        os.utime(config_file, ns=(original.st_atime_ns, original.st_mtime_ns))

        assert load_config_cached(config_file) is not first

    def test_a_file_appearing_where_there_was_none_is_picked_up(self, tmp_path: Path) -> None:
        config_file = tmp_path / "hooks-daemon.yaml"
        first = load_config_cached(config_file)

        _write(config_file, _YAML)

        assert load_config_cached(config_file) is not first


class TestABrokenConfigIsCachedByFailure:
    """RV7-M1 item 3: a config that fails to parse must not be re-parsed on
    every call while it stays broken -- only on the next edit."""

    def test_a_second_call_on_the_same_broken_file_re_raises_without_reparsing(
        self, tmp_path: Path
    ) -> None:
        config_file = tmp_path / "hooks-daemon.yaml"
        _write(config_file, _BROKEN_YAML)

        with patch.object(Config, "load_or_default", wraps=Config.load_or_default) as spy:
            with pytest.raises(ValueError):
                load_config_cached(config_file)
            with pytest.raises(ValueError):
                load_config_cached(config_file)

        assert spy.call_count == 1

    def test_fixing_the_file_is_picked_up_on_the_next_call(self, tmp_path: Path) -> None:
        config_file = tmp_path / "hooks-daemon.yaml"
        _write(config_file, _BROKEN_YAML)
        with pytest.raises(ValueError):
            load_config_cached(config_file)

        _write(config_file, _YAML)
        stat = config_file.stat()
        os.utime(config_file, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))

        assert load_config_cached(config_file).daemon.enabled is True


class TestABrokenConfigNeverGrowsATraceback:
    """RV8-M1: re-raising the CACHED exception INSTANCE prepends each call's
    frames to its one shared ``__traceback__`` forever -- a daemon-lifetime
    leak, and a splice of unrelated threads' frames into one chain. A hit
    must raise a FRESH exception object every time, with no growing chain."""

    def test_a_cache_hit_never_returns_the_same_exception_object(self, tmp_path: Path) -> None:
        config_file = tmp_path / "hooks-daemon.yaml"
        _write(config_file, _BROKEN_YAML)

        with pytest.raises(ValueError) as first:
            load_config_cached(config_file)
        with pytest.raises(ValueError) as second:
            load_config_cached(config_file)

        assert first.value is not second.value

    def test_traceback_depth_does_not_grow_with_repeated_hits(self, tmp_path: Path) -> None:
        config_file = tmp_path / "hooks-daemon.yaml"
        _write(config_file, _BROKEN_YAML)

        def _tb_depth(exc: BaseException) -> int:
            depth = 0
            tb = exc.__traceback__
            while tb is not None:
                depth += 1
                tb = tb.tb_next
            return depth

        depths = []
        for _ in range(50):
            with pytest.raises(ValueError) as caught:
                load_config_cached(config_file)
            depths.append(_tb_depth(caught.value))

        # The FIRST call is a genuine MISS -- it propagates straight out of
        # Config.load_or_default's own parse, a different (and irrelevant)
        # call shape from every later HIT. Every hit after it raises its OWN
        # fresh exception from the SAME call site inside load_config_cached,
        # so THEIR depth is constant -- not merely bounded, which a
        # growing-but-capped chain would also satisfy.
        assert len(set(depths[1:])) == 1


class TestATransientOSErrorIsNeverCached:
    """RV8-M2: the cache key identifies the file's CONTENT
    (``st_mtime_ns``/``st_size``); a transient read failure (EMFILE, EACCES,
    a momentary EIO) is a property of the READ, not of the content, so
    caching it under that signature makes a VALID config read as broken
    until an edit changes the signature -- which a permission fix alone
    never does."""

    def test_a_flaky_read_recovers_on_the_very_next_call(self, tmp_path: Path) -> None:
        config_file = tmp_path / "hooks-daemon.yaml"
        _write(config_file, _YAML)

        calls = {"n": 0}
        real_load_or_default = Config.load_or_default

        def flaky(path: str | Path | None = None) -> Config:
            calls["n"] += 1
            if calls["n"] == 1:
                raise OSError(24, "Too many open files")
            return real_load_or_default(path)

        with patch.object(Config, "load_or_default", side_effect=flaky):
            with pytest.raises(OSError):
                load_config_cached(config_file)
            assert load_config_cached(config_file).daemon.enabled is True

    def test_a_repair_is_picked_up_without_an_mtime_change(self, tmp_path: Path) -> None:
        """A repair that changes neither mtime nor size must still be picked
        up, so if the OSError were cached by signature (as a deterministic
        failure is), this second call would still see the cached failure.

        A REAL filesystem-level OSError, not a mocked one (RV9-n3) -- a
        mocked side effect proves only that this cache does not add its own
        caching on top of whatever the caller raises, never that an actual
        filesystem failure goes uncached. ``chmod 000`` cannot demonstrate
        that: root ignores ordinary permission bits, and every test here
        must run (and pass) as root (RV9-review10). Swapping the path for a
        DIRECTORY instead works unconditionally -- ``Path.open()`` raises
        ``IsADirectoryError`` at the io layer before permission bits are
        even consulted, root included -- and the swap-back restores the
        original bytes and mtime, so the signature is provably unchanged.
        """
        config_file = tmp_path / "hooks-daemon.yaml"
        _write(config_file, _YAML)
        original_bytes = config_file.read_bytes()
        stat_before = config_file.stat()
        signature_before = (stat_before.st_mtime_ns, stat_before.st_size)

        config_file.unlink()
        config_file.mkdir()
        try:
            with pytest.raises(OSError):
                load_config_cached(config_file)
        finally:
            config_file.rmdir()
            config_file.write_bytes(original_bytes)
            os.utime(config_file, ns=(stat_before.st_atime_ns, stat_before.st_mtime_ns))

        signature_after = (config_file.stat().st_mtime_ns, config_file.stat().st_size)
        assert signature_after == signature_before

        result = load_config_cached(config_file)
        assert result.daemon.enabled is True


class TestAPathologicallyNestedConfigIsCachedAsAFailure:
    """RV9-n1: ``Config.load`` converts a nested-too-deep config's
    ``RecursionError`` to ``ValueError`` (same door as a YAML syntax error),
    so it is cacheable by content signature exactly like any other
    deterministic parse failure -- not re-parsed (at ~1.6 s a call) on every
    hit while the file stays broken."""

    def test_a_5000_deep_config_yields_a_cached_load_failure(self, tmp_path: Path) -> None:
        config_file = tmp_path / "hooks-daemon.yaml"
        _write(config_file, "[" * 5000 + "]" * 5000)

        with patch.object(Config, "load_or_default", wraps=Config.load_or_default) as spy:
            with pytest.raises(ValueError):
                load_config_cached(config_file)
            with pytest.raises(ValueError):
                load_config_cached(config_file)

        # A second hit must be answered from the cache, not by re-parsing --
        # counted, not timed, so the assertion cannot flake on machine speed.
        assert spy.call_count == 1


class TestCachedConfigLoadErrorIsCopyableAndPicklable:
    """RV9-n2: nothing copies this exception today, but an object nothing
    can copy or pickle is a latent trap for the next caller that does
    (a retry wrapper, a multiprocessing boundary, a test helper)."""

    def _make(self) -> CachedConfigLoadError:
        return CachedConfigLoadError(ValueError, "Invalid YAML in x: boom")

    def test_copy_copy_preserves_the_fields(self) -> None:
        original = self._make()

        copied = copy.copy(original)

        assert copied is not original
        assert copied.original_type is original.original_type
        assert copied.message == original.message
        assert str(copied) == str(original)

    def test_copy_deepcopy_preserves_the_fields(self) -> None:
        original = self._make()

        copied = copy.deepcopy(original)

        assert copied is not original
        assert copied.original_type is original.original_type
        assert copied.message == original.message
        assert str(copied) == str(original)

    def test_reduce_rebuilds_an_equivalent_instance(self) -> None:
        """Exercise the ``__reduce__`` contract directly: both ``copy`` and
        ``pickle`` call ``fn(*args)`` on whatever it returns, so proving that
        call alone reconstructs the fields proves both callers work without
        needing pickle's own load path (which ``security_antipattern`` flags
        as deserialization of untrusted input -- not what this is)."""
        original = self._make()

        fn, args = original.__reduce__()
        rebuilt = fn(*args)

        assert rebuilt is not original
        assert rebuilt.original_type is original.original_type
        assert rebuilt.message == original.message
        assert str(rebuilt) == str(original)

    def test_pickle_dumps_succeeds(self) -> None:
        """``pickle.dumps`` calls ``__reduce__`` too, so a broken one would
        raise here before ever reaching ``loads``."""
        original = self._make()

        pickle.dumps(original)


class TestConcurrentCallersShareOneEntry:
    """Dispatch is threaded; the cache is a daemon-lifetime singleton."""

    def test_many_threads_hammering_one_path_agree_on_one_object(self, tmp_path: Path) -> None:
        config_file = tmp_path / "hooks-daemon.yaml"
        _write(config_file, _YAML)

        original_interval = sys.getswitchinterval()
        # An unlocked cache survives the default 5 ms interval untouched: the
        # GIL simply does not preempt inside the read-modify-write. Plan 00437
        # had to drive the interval to its floor before the failure appeared at
        # all, and a concurrency test that has never been seen failing is not
        # evidence of anything.
        sys.setswitchinterval(1e-9)
        barrier = threading.Barrier(16)
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:

                def hammer() -> int:
                    barrier.wait()
                    return id(load_config_cached(config_file))

                seen = {future.result() for future in [pool.submit(hammer) for _ in range(16)]}
        finally:
            sys.setswitchinterval(original_interval)

        assert len(seen) == 1
