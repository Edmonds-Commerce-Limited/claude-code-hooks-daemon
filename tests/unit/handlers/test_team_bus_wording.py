"""Team handlers name no bus program of their own; the adapters do (Plan 00474 R6)."""

from __future__ import annotations

from claude_code_hooks_daemon.handlers.session_start import coordinator_board
from claude_code_hooks_daemon.handlers.stop.owner_wait_stop_guard import (
    OwnerWaitStopGuardHandler,
)
from claude_code_hooks_daemon.utils import teamchat_seat
from claude_code_hooks_daemon.utils.owner_wait_bus import NOTIFY_PROGRAM, TeamchatOwnerWaitBus


def _owner_wait_text() -> str:
    handler = OwnerWaitStopGuardHandler()
    rules = " ".join(
        f"{rule.blocked} {rule.why} {rule.fix} {rule.verbose}" for rule in handler.get_rules()
    )
    return f"{handler.get_claude_md()} {rules}"


def test_owner_wait_guidance_names_no_bus_program() -> None:
    text = _owner_wait_text()
    assert NOTIFY_PROGRAM not in text
    assert "pingbus" not in text


def test_the_adapter_still_prints_the_concrete_command() -> None:
    asked, owner_started = TeamchatOwnerWaitBus().notify_commands("t")
    assert asked.startswith(NOTIFY_PROGRAM)
    assert owner_started.startswith(NOTIFY_PROGRAM)


def test_board_note_takes_the_status_command_from_the_kit_adapter() -> None:
    assert teamchat_seat.STATUS_COMMAND in coordinator_board.BOARD_NOTE
