"""The write-clobber guard's session map under contention (Plan 00449).

The guard is a daemon-lifetime singleton and dispatch runs on a thread pool, so
two Reads from different sessions can record at the same moment. With the map
at its session cap, both select the same oldest session to evict and the second
eviction raises ``KeyError`` out of ``handle()`` — for a Read, which the guard
exists to ALLOW. A fail-open chain then loses the guard for that request; a
strict chain DENIES a Read. Neither is "fails closed".
"""

from pathlib import Path
from typing import Any

import pytest
from tests.thread_contention import hammer

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.data_layer import reset_data_layer
from claude_code_hooks_daemon.handlers.pre_tool_use.write_clobber_guard import (
    _MAX_TRACKED_SESSIONS,
    WriteClobberGuardHandler,
)


@pytest.fixture(autouse=True)
def _reset_disclosure_tracker():
    reset_data_layer()
    yield
    reset_data_layer()


def _event(tool: str, path: str, session: str) -> dict[str, Any]:
    tool_input: dict[str, Any] = {"file_path": path}
    if tool == "Write":
        tool_input["content"] = "replacement"
    return {
        "hook_event_name": "PreToolUse",
        "session_id": session,
        "tool_name": tool,
        "tool_input": tool_input,
    }


def _full_guard() -> WriteClobberGuardHandler:
    """A guard whose session map is already AT its cap, so every new session evicts."""
    handler = WriteClobberGuardHandler()
    for index in range(_MAX_TRACKED_SESSIONS):
        handler.handle(_event("Read", f"/seed/{index}", f"seed-{index}"))
    return handler


class TestConcurrentReadsNeverRaise:
    def test_no_exception_escapes_a_read_under_concurrent_eviction(self) -> None:
        handler = _full_guard()

        def read(worker: int, index: int) -> None:
            result = handler.handle(_event("Read", "/some/file", f"w{worker}-{index}"))
            assert result.decision == Decision.ALLOW

        errors = hammer(read)

        assert not errors, f"concurrent Reads raised: {errors[:3]}"

    def test_the_guard_still_denies_after_contention(self, tmp_path: Path) -> None:
        """Fail-closed is about the NEXT clobber, not only about not crashing."""
        handler = _full_guard()
        errors = hammer(
            lambda worker, index: handler.handle(_event("Read", "/some/file", f"w{worker}-{index}"))
        )
        target = tmp_path / "existing.txt"
        target.write_text("ORIGINAL\n")

        result = handler.handle(_event("Write", str(target), "fresh-session"))

        assert not errors
        assert result.decision == Decision.DENY


class TestSessionEvictionIsFifo:
    def test_a_new_session_evicts_the_oldest_not_the_newest(self, tmp_path: Path) -> None:
        """LIFO would satisfy a size assertion exactly as well as FIFO does.

        Evicting the NEWEST instead turns the last slot into a revolving door:
        the session that just arrived loses what it read on the next new
        session, and its next legitimate rewrite is blocked.
        """
        target = tmp_path / "existing.txt"
        target.write_text("ORIGINAL\n")
        handler = WriteClobberGuardHandler()
        for index in range(_MAX_TRACKED_SESSIONS):
            handler.handle(_event("Read", str(target), f"s{index}"))

        handler.handle(_event("Read", "/other", "newcomer"))

        newest = f"s{_MAX_TRACKED_SESSIONS - 1}"
        assert handler.handle(_event("Write", str(target), newest)).decision == Decision.ALLOW
        assert handler.handle(_event("Write", str(target), "s0")).decision == Decision.DENY
