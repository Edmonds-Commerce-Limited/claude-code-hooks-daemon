"""Shared test helper for waiting on `HooksDaemon.started_event`.

Plan 00466 N39 review1 MEDIUM-1: a plain
`asyncio.wait_for(daemon.started_event.wait(), timeout=...)` blocks for the
full timeout when `start()` raises before it reaches
`started_event.set()` -- the real exception (e.g. a bind `OSError`) sits
unretrieved on the server task, and the caller sees only a `TimeoutError`
with no clue what actually failed. `wait_for_daemon_started` races the
event against the task itself so a failed start surfaces its real exception
immediately instead of after the full wait.
"""

from __future__ import annotations

import asyncio
from typing import Any, Protocol


class _StartedEventOwner(Protocol):
    """Structural type for anything exposing a `started_event` attribute --
    avoids importing `HooksDaemon` just for a type hint here."""

    started_event: asyncio.Event


async def wait_for_daemon_started(
    daemon: _StartedEventOwner,
    server_task: asyncio.Task[Any],
    timeout: float,
) -> None:
    """Wait for `daemon.started_event` to be set, or for `server_task` to
    finish first.

    Args:
        daemon: The daemon (or stand-in) exposing `started_event`.
        server_task: The task running `daemon.start()`.
        timeout: Seconds to wait before giving up on both.

    Raises:
        BaseException: Whatever `server_task` raised, if it finished before
            `started_event` was set.
        TimeoutError: If neither `started_event` nor `server_task` settled
            within `timeout`.
    """
    waiter = asyncio.ensure_future(daemon.started_event.wait())
    try:
        done, _pending = await asyncio.wait(
            {waiter, server_task}, timeout=timeout, return_when=asyncio.FIRST_COMPLETED
        )
    finally:
        if not waiter.done():
            waiter.cancel()

    if waiter in done:
        return

    if server_task in done:
        exc = server_task.exception()
        if exc is not None:
            raise exc

    raise TimeoutError(
        f"daemon did not start within {timeout}s "
        "(started_event unset, server_task not done)"
    )
