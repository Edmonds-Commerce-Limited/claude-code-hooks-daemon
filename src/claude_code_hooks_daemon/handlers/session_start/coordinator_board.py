"""CoordinatorBoardHandler - where a coordinator reads peers' state (Plan 00636 Task 2.5, s7 and B5).

The coordinator retrospective (00630 DESIGN.md section 19, s7) asked for the
parallel peers' state in one view, and B5 (section 7) for seat liveness on a
coordinator seat. Both are to come from ``teamchat status`` (or fedora-desktop
Plan 00251), never from teamchat's files. The output contract of ``teamchat
status`` is not recorded in this repository and no teamchat binary is present
to check it against, so this handler parses nothing and runs no status command: on
SessionStart it tells a coordinator seat where the board is, that teamchat's
files are not it, and that a seat it cannot read is unknown, not down.

Advisory only: never denies, never terminal, restarts and reassigns nothing
(DESIGN.md Q6, a supervisor action, is the owner's question). It runs no
`teamchat status` and opens no teamchat file; the only command it runs is the
shared `whoami` seat probe. It relays no status text, so no peer-controlled
label reaches the context. The gate is the shared
``coordinator_advisory_armed``: a declared coordinator, a coordinator duty, an
unreadable role or an unresolved probe hear it; a declared worker, no team and
a sub-agent do not. A fault reading the seat counts as armed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final, Protocol

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import AdvisoryResult, Decision
from claude_code_hooks_daemon.core.handler_bases import SessionStartHandlerBase
from claude_code_hooks_daemon.utils.team_role_gate import probe_coordinator_advisory_armed
from claude_code_hooks_daemon.utils.teamchat_seat import (
    SeatContext,
    SessionSignals,
    TeamOnlyGuidance,
    shared_resolver,
)

if TYPE_CHECKING:
    from claude_code_hooks_daemon.config.models import TeamSeatConfig

BOARD_NOTE: Final[str] = (
    "COORDINATOR BOARD (s7, B5): peers' state, where teamchat shows it, is `teamchat status`; "
    "run it yourself when you need the board. Never read teamchat's files for it "
    "(status.json, the run directory, the seat store). A seat that view does not "
    "show, or whose state you cannot read, is unknown, not down: ask it on the bus "
    "before you reassign its work or tell the team it is gone. This note never "
    "restarts or reassigns a seat, and the daemon does not read the board for you."
)


class _SeatResolver(Protocol):
    def resolve(self, signals: SessionSignals) -> SeatContext: ...


class CoordinatorBoardHandler(TeamOnlyGuidance, SessionStartHandlerBase):
    """Tell a coordinator seat where the board is: `teamchat status`. Advisory, never denies."""

    def __init__(self) -> None:
        """Initialise as a non-terminal advisory handler (see the module docstring)."""
        super().__init__(
            handler_id=HandlerID.COORDINATOR_BOARD,
            priority=Priority.COORDINATOR_BOARD,
            terminal=False,
            tags=[HandlerTag.ADVISORY, HandlerTag.WORKFLOW, HandlerTag.NON_TERMINAL],
        )
        # Injected by the registry from the top-level ``team_seat:`` block.
        self._team_seat: TeamSeatConfig | None = None
        # Seam, not a config option.
        self._resolver: _SeatResolver | None = None

    def get_default_enabled(self) -> bool:
        """On by default; silent off a coordinator seat."""
        return True

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Every SessionStart: new, resumed, cleared and compacted sessions all need the board."""
        return True

    def _seat_resolver(self) -> _SeatResolver:
        return self._resolver if self._resolver is not None else shared_resolver(self._team_seat)

    def _armed(self, hook_input: dict[str, Any]) -> bool:
        return probe_coordinator_advisory_armed(
            hook_input,
            lambda: self._seat_resolver().resolve(SessionSignals.from_hook_input(hook_input)),
            handler="coordinator_board",
        )

    def handle(self, hook_input: dict[str, Any]) -> AdvisoryResult:
        """Add the board note on a seat the coordinator gate arms."""
        if not self._armed(hook_input):
            return AdvisoryResult(decision=Decision.ALLOW, context=[])
        return AdvisoryResult(decision=Decision.ALLOW, context=[BOARD_NOTE])

    def get_claude_md(self) -> str | None:
        """None: the session-start note is the whole message (see the guidance coverage table)."""
        return None

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for this handler.

        Only the silent default is testable: the note needs a teamchat
        coordinator seat, which an acceptance run does not hold.
        """
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="Coordinator board note is silent without a team seat",
                command='echo "test"',
                description=(
                    "Default state check. A session with no teamchat seat (no"
                    " TEAMCHAT_RUNTIME) must get NO coordinator board note at"
                    " session start. Verify by starting a session and confirming"
                    " no COORDINATOR BOARD line appears in the system-reminders."
                ),
                expected_decision=Decision.ALLOW,
                # Deliberately empty: this test asserts that NOTHING is injected.
                expected_message_patterns=[],
                safety_notes=(
                    "Advisory only - never blocks. This test asserts ABSENCE, so"
                    " it fails loudly if the note ever speaks off a team seat."
                ),
                test_type=TestType.CONTEXT,
                requires_event="SessionStart event",
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=True,
            ),
        ]
