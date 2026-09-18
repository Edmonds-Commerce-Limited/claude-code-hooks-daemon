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
import os
import sys
import threading
from pathlib import Path
from typing import Final

import pytest

from claude_code_hooks_daemon.utils.config_cache import load_config_cached, reset_config_cache

_YAML: Final[str] = "daemon:\n  enabled: true\n"
_OTHER_YAML: Final[str] = "daemon:\n  enabled: false\n"


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
