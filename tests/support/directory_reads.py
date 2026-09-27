"""Count the directories a piece of code lists (00466 N222).

A test that a walk is "refused immediately" used to assert on wall time, which
failed on a loaded host. What it means is that no directory is read at all,
and that is countable.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest


def record_directory_reads(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record every ``os.scandir`` made through ``shell_expansion`` for the
    rest of the test. ``bounded_recursive_glob`` and ``Path.glob`` both list
    directories through ``os.scandir``; the returned list grows as they do."""
    reads: list[str] = []
    real_scandir = os.scandir

    def recording_scandir(path: str = ".") -> Iterator[os.DirEntry[str]]:
        reads.append(str(path))
        return real_scandir(path)

    monkeypatch.setattr(
        "claude_code_hooks_daemon.utils.shell_expansion.os.scandir", recording_scandir
    )
    return reads
