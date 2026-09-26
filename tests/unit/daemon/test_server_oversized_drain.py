"""The oversized-request drain has an overall time limit (Plan 00466 N40 review 2 nit 1).

Each read was bounded (0.5s) and the total bytes were bounded (16 MiB), but not
the elapsed time: a sender trickling 1 KiB every 0.4s kept the coroutine
draining for hours. Proved by a deterministic count of reads against a fake
clock, not by timing anything.
"""

from __future__ import annotations

import itertools
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.daemon import server
from claude_code_hooks_daemon.daemon.server import HooksDaemon

_TRICKLE_CHUNK = b"x" * 1024
# How far the fake clock moves per read: just under the per-read timeout, so
# no single read ever times out -- the trickling sender's shape.
_TRICKLE_INTERVAL = server._OVERSIZED_REQUEST_DRAIN_PER_READ_TIMEOUT_SECONDS * 0.8


class _TricklingReader:
    """Never reaches EOF and never goes quiet for a whole per-read timeout."""

    def __init__(self) -> None:
        self.reads = 0

    async def read(self, n: int = -1) -> bytes:
        self.reads += 1
        return _TRICKLE_CHUNK


class _FinishingReader:
    """Sends two chunks, then EOF."""

    def __init__(self) -> None:
        self.chunks = [_TRICKLE_CHUNK, _TRICKLE_CHUNK, b""]

    async def read(self, n: int = -1) -> bytes:
        return self.chunks.pop(0)


@pytest.mark.anyio
async def test_a_trickling_sender_is_cut_off_at_the_total_deadline() -> None:
    reader = _TricklingReader()
    ticks = itertools.count()

    with patch.object(server, "_drain_clock", lambda: next(ticks) * _TRICKLE_INTERVAL):
        await HooksDaemon._drain_oversized_request(reader)

    reads_allowed = server._OVERSIZED_REQUEST_DRAIN_TOTAL_SECONDS / _TRICKLE_INTERVAL
    assert reader.reads <= reads_allowed + 1
    # Far short of the byte cap, which is all that stopped it before.
    assert reader.reads * len(_TRICKLE_CHUNK) < server._OVERSIZED_REQUEST_DRAIN_CAP_BYTES


@pytest.mark.anyio
async def test_a_sender_that_finishes_is_drained_to_its_end() -> None:
    reader = _FinishingReader()

    await HooksDaemon._drain_oversized_request(reader)

    assert reader.chunks == []
