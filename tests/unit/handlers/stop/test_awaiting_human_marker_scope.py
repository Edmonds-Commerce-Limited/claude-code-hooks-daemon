"""A teammate or sub-agent stop never writes the lead's `[awaiting-human]` marker (Plan 00470 Task 3.4).

The marker (`utils.blockage_marker`) is keyed by SESSION id and silences the
lead's failsafe and declared cron ticks. A teammate or sub-agent runs inside the
lead's session, so a stop of theirs that said `[awaiting-human]` would, if it
reached the writer, switch off the lead's ticks while real work is still owed.

Two facts keep that from happening, and each is pinned here:

- the only writer is `auto_continue_stop` (a source scan below fails when a
  second one appears), and
- that handler is scoped to the main thread, whose discriminator is the absence
  of `agent_id`. A Claude Code teammate's payload carries a 30-character
  `agent_id` and an Agent-tool sub-agent's a 17-character one (see
  `core/handler_scope.py`), so both are refused by the chain before
  `matches()` runs.

Driven through the real `HandlerChain`, so the scope gate is part of what is
under test: a direct `handle()` call would bypass exactly the seam that protects
the marker.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.core.chain import HandlerChain
from claude_code_hooks_daemon.core.handler_scope import HandlerScope
from claude_code_hooks_daemon.handlers.stop.auto_continue_stop import AutoContinueStopHandler
from claude_code_hooks_daemon.utils.blockage_marker import MARKER_FILENAME

_AWAITING_HUMAN_STOP = (
    "STOPPING BECAUSE: [awaiting-human] the owner has to choose between A and B "
    "before anything else can move."
)
_SESSION_ID = "lead-session"
_TEAMMATE_AGENT_ID = "teammate-in-process-agent-id-30c"
_SUBAGENT_AGENT_ID = "agent_01H9XQK2M4N7P"

_HANDLERS_DIR = (
    Path(__file__).resolve().parents[4] / "src" / "claude_code_hooks_daemon" / "handlers"
)


def _calls_write_marker(path: Path) -> bool:
    """Whether the module CALLS ``write_marker`` (a docstring mention is not a writer)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return any(
        isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Name) and node.func.id == "write_marker")
            or (isinstance(node.func, ast.Attribute) and node.func.attr == "write_marker")
        )
        for node in ast.walk(tree)
    )


def _transcript(tmp_path: Path) -> Path:
    path = tmp_path / "transcript.jsonl"
    message = {
        "type": "message",
        "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": _AWAITING_HUMAN_STOP}],
        },
    }
    path.write_text(json.dumps(message) + "\n", encoding="utf-8")
    return path


def _stop_through_the_chain(tmp_path: Path, **extra: Any) -> Path:
    """Dispatch an `[awaiting-human]` Stop and return where the marker would be."""
    marker_dir = tmp_path / "untracked"
    chain = HandlerChain()
    chain.add(AutoContinueStopHandler())
    hook_input = {
        "hook_event_name": "Stop",
        "session_id": _SESSION_ID,
        "transcript_path": str(_transcript(tmp_path)),
        "stop_hook_active": False,
        **extra,
    }
    with patch(
        "claude_code_hooks_daemon.handlers.stop.auto_continue_stop."
        "ProjectContext.daemon_untracked_dir",
        return_value=marker_dir,
    ):
        chain.execute(hook_input)
    return marker_dir / MARKER_FILENAME


class TestOnlyTheLeadsOwnStopArmsTheMarker:
    def test_a_main_thread_stop_arms_it(self, tmp_path: Path) -> None:
        """Positive control: without it, the negative cases below prove nothing."""
        assert _stop_through_the_chain(tmp_path).exists()

    def test_a_teammate_stop_does_not(self, tmp_path: Path) -> None:
        marker = _stop_through_the_chain(tmp_path, agent_id=_TEAMMATE_AGENT_ID)
        assert not marker.exists()

    def test_a_sub_agent_stop_does_not(self, tmp_path: Path) -> None:
        marker = _stop_through_the_chain(tmp_path, agent_id=_SUBAGENT_AGENT_ID)
        assert not marker.exists()

    def test_a_subagent_stop_event_does_not(self, tmp_path: Path) -> None:
        """A `SubagentStop` always carries `agent_id`; even offered to the writer it is refused."""
        marker = _stop_through_the_chain(
            tmp_path, hook_event_name="SubagentStop", agent_id=_SUBAGENT_AGENT_ID
        )
        assert not marker.exists()


class TestTheScopeIsWhatProtectsTheMarker:
    def test_without_the_main_scope_a_teammate_stop_would_arm_it(self, tmp_path: Path) -> None:
        """Sensitivity check: the negative cases above are not passing vacuously."""
        marker_dir = tmp_path / "untracked"
        handler = AutoContinueStopHandler()
        handler.scope = HandlerScope.ALL
        chain = HandlerChain()
        chain.add(handler)
        hook_input = {
            "hook_event_name": "Stop",
            "session_id": _SESSION_ID,
            "transcript_path": str(_transcript(tmp_path)),
            "stop_hook_active": False,
            "agent_id": _TEAMMATE_AGENT_ID,
        }
        with patch(
            "claude_code_hooks_daemon.handlers.stop.auto_continue_stop."
            "ProjectContext.daemon_untracked_dir",
            return_value=marker_dir,
        ):
            chain.execute(hook_input)
        assert (marker_dir / MARKER_FILENAME).exists()


class TestTheWriterStaysSingleAndMainScoped:
    def test_auto_continue_stop_is_main_scoped(self) -> None:
        assert AutoContinueStopHandler().scope is HandlerScope.MAIN

    def test_no_other_handler_writes_the_marker(self) -> None:
        writers = sorted(
            str(path.relative_to(_HANDLERS_DIR))
            for path in _HANDLERS_DIR.rglob("*.py")
            if _calls_write_marker(path)
        )
        assert writers == ["stop/auto_continue_stop.py"], (
            "A second writer of the human-input blockage marker exists. It must be "
            "scoped to the main thread and added to this test deliberately: the "
            f"marker silences the lead's cron ticks. Writers found: {writers}"
        )


@pytest.mark.parametrize("agent_id", [_TEAMMATE_AGENT_ID, _SUBAGENT_AGENT_ID])
def test_the_scope_gate_refuses_every_agent_shaped_stop(agent_id: str) -> None:
    from claude_code_hooks_daemon.core.handler_scope import scope_admits

    handler = AutoContinueStopHandler()
    assert not scope_admits(handler.scope, {"hook_event_name": "Stop", "agent_id": agent_id})
