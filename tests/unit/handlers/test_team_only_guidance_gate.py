"""The team-only handlers keep their guidance out of a project with no teams (Plan 00474 R5).

Every handler that serves teamchat seats AND emits guidance carries the
``TeamOnlyGuidance`` gate: its CLAUDE.md prose and rule rows appear only where
the project declares ``team_seat.teams_in_use``, and the optimise review calls
it "not applicable here" otherwise. ``auto_continue_stop`` serves every session
and must never carry the gate.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from claude_code_hooks_daemon.config.models import TeamSeatConfig
from claude_code_hooks_daemon.core.claude_md_injector import HasGuidanceRelevance
from claude_code_hooks_daemon.core.handler import Handler
from claude_code_hooks_daemon.core.relevance import RelevanceContext
from claude_code_hooks_daemon.handlers.post_tool_use.ci_state_reading import (
    CiStateReadingHandler,
)
from claude_code_hooks_daemon.handlers.post_tool_use.model_downgrade_recorder import (
    ModelDowngradeRecorderHandler,
)
from claude_code_hooks_daemon.handlers.pre_tool_use.host_seat_lane_guard import (
    HostSeatLaneGuardHandler,
)
from claude_code_hooks_daemon.handlers.pre_tool_use.human_approval_check import (
    HumanApprovalCheckHandler,
)
from claude_code_hooks_daemon.handlers.session_start.coordinator_board import (
    CoordinatorBoardHandler,
)
from claude_code_hooks_daemon.handlers.stop.auto_continue_stop import AutoContinueStopHandler
from claude_code_hooks_daemon.handlers.stop.owner_wait_stop_guard import (
    OwnerWaitStopGuardHandler,
)

TEAM_ONLY_GUIDANCE: tuple[type[Handler], ...] = (
    HostSeatLaneGuardHandler,
    HumanApprovalCheckHandler,
    OwnerWaitStopGuardHandler,
    CoordinatorBoardHandler,
    CiStateReadingHandler,
)


def _with_seat(handler_cls: type[Handler], config: TeamSeatConfig | None) -> Handler:
    """A handler with ``config`` injected the way the registry injects it."""
    handler = handler_cls()
    handler._team_seat = config
    return handler


@pytest.mark.parametrize("handler_cls", TEAM_ONLY_GUIDANCE)
class TestTeamOnlyGuidanceGate:
    def test_carries_the_gate(self, handler_cls: type[Handler]) -> None:
        # coordinator_board emits no prose today; it carries the gate for its
        # optimise-review relevance and so any prose it gains is gated too.
        assert isinstance(handler_cls(), HasGuidanceRelevance)

    def test_bare_handler_has_no_relevant_guidance(self, handler_cls: type[Handler]) -> None:
        handler = handler_cls()
        assert isinstance(handler, HasGuidanceRelevance)
        assert handler.guidance_relevant() is False

    def test_default_config_keeps_guidance_out(self, handler_cls: type[Handler]) -> None:
        handler = _with_seat(handler_cls, TeamSeatConfig())
        assert isinstance(handler, HasGuidanceRelevance)
        assert handler.guidance_relevant() is False

    def test_detection_off_keeps_guidance_out(self, handler_cls: type[Handler]) -> None:
        handler = _with_seat(handler_cls, TeamSeatConfig(teams_in_use=True, detection="off"))
        assert isinstance(handler, HasGuidanceRelevance)
        assert handler.guidance_relevant() is False

    def test_declared_teams_keep_guidance_in(self, handler_cls: type[Handler]) -> None:
        handler = _with_seat(handler_cls, TeamSeatConfig(teams_in_use=True))
        assert isinstance(handler, HasGuidanceRelevance)
        assert handler.guidance_relevant() is True

    def test_relevance_follows_the_context_not_the_instance(
        self, handler_cls: type[Handler], tmp_path: Path
    ) -> None:
        handler = _with_seat(handler_cls, TeamSeatConfig(teams_in_use=True))
        bare = RelevanceContext.probe(tmp_path, declared_languages=[])
        declared = RelevanceContext.probe(tmp_path, declared_languages=[], teams_declared=True)
        assert handler.get_relevance(bare).applicable is False
        assert handler_cls().get_relevance(declared).applicable is True


def test_relevance_context_defaults_to_no_teams(tmp_path: Path) -> None:
    assert RelevanceContext.probe(tmp_path, declared_languages=[]).teams_declared is False


def test_auto_continue_stop_never_carries_the_gate() -> None:
    assert not isinstance(AutoContinueStopHandler(), HasGuidanceRelevance)


def test_model_downgrade_recorder_is_supervisor_only(tmp_path: Path) -> None:
    context = RelevanceContext.probe(tmp_path, declared_languages=[])
    relevance = ModelDowngradeRecorderHandler().get_relevance(context)
    assert relevance.applicable is False
    assert "supervisor" in relevance.reason
