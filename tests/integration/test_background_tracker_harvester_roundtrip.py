"""The tracker's writes must satisfy the harvester's reads (Plan 00236, DBF).

Plan 00234 found the wall-TTL half of ``harvest-background`` structurally
unable to fire: the tracker wrote ``{command, session_id, run_in_background}``
while the harvester read a ``pgid`` key nobody emitted, so
``read_tracked_pgids`` always returned ``[]``.

**What let it survive is more interesting than the bug.** Both sides were
thoroughly unit-tested — and both tests fabricated their own fixtures. The
harvester's test invented ``{"pgid": 100}`` records; the tracker's test
asserted the fields it did write. Neither could see the disagreement, because
neither ran the other's code. A seam tested only from both ends with synthetic
data is not tested at all.

So this file exists to hold the SEAM: the real writer produces the file, the
real reader consumes it, and the correlation actually resolves. Any future
change to either schema fails here rather than silently disabling a feature.
"""

from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.daemon.background_harvester import (
    find_breaches,
    parse_ps_output,
    read_tracked_commands,
)
from claude_code_hooks_daemon.handlers.post_tool_use.background_process_tracker import (
    BackgroundProcessTrackerHandler,
)

_BACKGROUNDED_COMMAND = "./scripts/qa/llm_qa.py all > untracked/qa.txt 2>&1"

# How the backgrounded command above actually appears in ``ps -eo args`` —
# copied from a live observation, not invented: Claude Code runs a background
# Bash call as a wrapper shell that ``eval``s the command verbatim, so the
# recorded text is present in the process's args.
_PS_OUTPUT = (
    "PID PGID ELAPSED %CPU COMMAND\n"
    "667222 667222 4000 0.1 /bin/bash -c source /root/.claude/snapshot.sh && "
    f"eval '{_BACKGROUNDED_COMMAND}' < /dev/null\n"
    "1 1 999999 0.0 /sbin/init\n"
)


class _TrackerWritingTo(BackgroundProcessTrackerHandler):
    """The production handler, pointed at a temp state file.

    Subclassed rather than mocked so the record SCHEMA under test is the one
    ``handle()`` really writes — mocking the writer would recreate exactly the
    fabricated-fixture blind spot this file exists to close.
    """

    def __init__(self, state_file: Path) -> None:
        super().__init__()
        self._state_file = state_file

    def _resolve_state_file(self) -> Any | None:
        return self._state_file


def _track(tmp_path: Path, command: str) -> Path:
    state_file = tmp_path / "background-processes.jsonl"
    handler = _TrackerWritingTo(state_file)
    handler.handle(
        {
            "tool_name": "Bash",
            "tool_input": {"command": command, "run_in_background": True},
            "session_id": "sess-1",
        }
    )
    return state_file


def test_harvester_reads_what_the_tracker_writes(tmp_path):
    """The reader must find something in a file the writer produced.

    This is the assertion the old ``pgid`` schema could never satisfy.
    """
    state_file = _track(tmp_path, _BACKGROUNDED_COMMAND)

    assert read_tracked_commands(state_file) == [_BACKGROUNDED_COMMAND]


def test_tracked_command_correlates_to_a_live_process(tmp_path):
    """End to end: a tracked command breaching the wall TTL is surfaced."""
    state_file = _track(tmp_path, _BACKGROUNDED_COMMAND)

    breaches = find_breaches(
        parse_ps_output(_PS_OUTPUT),
        max_wall_seconds=600,
        max_cpu_percent=400,
        min_cpu_runtime_seconds=60,
        tracked_commands=read_tracked_commands(state_file),
    )

    assert [b.record.pid for b in breaches] == [667222]
    assert any("TTL" in reason for reason in breaches[0].reasons)


def test_untracked_long_lived_process_is_still_left_alone(tmp_path):
    """The narrowing that makes the TTL bearable must survive the fix.

    ``init`` runs forever at 0% CPU. It is only spared because nothing tracked
    it — if correlation ever matched too loosely, this is what would start
    nagging.
    """
    state_file = _track(tmp_path, _BACKGROUNDED_COMMAND)

    breaches = find_breaches(
        parse_ps_output(_PS_OUTPUT),
        max_wall_seconds=600,
        max_cpu_percent=400,
        min_cpu_runtime_seconds=60,
        tracked_commands=read_tracked_commands(state_file),
    )

    assert 1 not in {b.record.pid for b in breaches}
