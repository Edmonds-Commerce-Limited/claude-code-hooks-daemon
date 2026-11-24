"""The team rules reach CLAUDE.md only where the project declares teams (Plan 00474 R5).

Real team-only handlers, configured the way the registry configures them,
rendered through the real injector. With the default ``team_seat`` block no
team rule row and no team prose appears; with ``teams_in_use: true`` they do.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from claude_code_hooks_daemon.config.models import TeamSeatConfig
from claude_code_hooks_daemon.core.claude_md_injector import ClaudeMdInjector
from claude_code_hooks_daemon.core.handler import Handler
from claude_code_hooks_daemon.handlers.post_tool_use.ci_state_reading import (
    CiStateReadingHandler,
)
from claude_code_hooks_daemon.handlers.pre_tool_use.host_seat_lane_guard import (
    HostSeatLaneGuardHandler,
)
from claude_code_hooks_daemon.handlers.pre_tool_use.human_approval_check import (
    HumanApprovalCheckHandler,
)
from claude_code_hooks_daemon.handlers.stop.owner_wait_stop_guard import (
    OwnerWaitStopGuardHandler,
)

_TEAM_RULE_IDS = (
    "R-HOST-SEAT-LANE",
    "R-HUMAN-APPROVAL-MISSING",
    "R-STOP-OWNER-WAIT-UNBUMPED",
)
_TEAM_SECTION = "ci_state_reading"


def _block(tmp_path: Path, team_seat: TeamSeatConfig) -> str:
    handlers: list[Handler] = []
    for handler_cls in (
        HostSeatLaneGuardHandler,
        HumanApprovalCheckHandler,
        OwnerWaitStopGuardHandler,
        CiStateReadingHandler,
    ):
        handler = handler_cls()
        handler._team_seat = team_seat
        handlers.append(handler)
    claude_md = tmp_path / "CLAUDE.md"
    claude_md.write_text("# P\n")
    ClaudeMdInjector(workspace_root=tmp_path, handlers=handlers).inject()
    return claude_md.read_text(encoding="utf-8")


@pytest.mark.parametrize("rule_id", _TEAM_RULE_IDS)
def test_default_config_leaves_the_team_rules_out(tmp_path: Path, rule_id: str) -> None:
    assert rule_id not in _block(tmp_path, TeamSeatConfig())


@pytest.mark.parametrize("rule_id", _TEAM_RULE_IDS)
def test_declared_teams_keep_the_team_rules(tmp_path: Path, rule_id: str) -> None:
    assert rule_id in _block(tmp_path, TeamSeatConfig(teams_in_use=True))


@pytest.mark.parametrize(("teams_in_use", "present"), [(False, False), (True, True)])
def test_ci_state_reading_prose_follows_the_declaration(
    tmp_path: Path, teams_in_use: bool, present: bool
) -> None:
    block = _block(tmp_path, TeamSeatConfig(teams_in_use=teams_in_use))
    assert (_TEAM_SECTION in block) is present
