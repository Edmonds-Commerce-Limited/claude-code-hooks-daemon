"""A listing INSIDE one numbered plan folder is not a plan-number discovery (GitHub #151)."""

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.core.hook_result import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use.plan_number_helper import (
    PlanNumberHelperHandler,
)

# The shape that was denied: a compound read-only inspection of ONE plan whose
# `grep` carries a digit class, next to an `ls` of that plan's JOURNAL/.
ISSUE_COMMAND = (
    'bin/hooks-daemon find-plan 554 && grep -n -E "^\\*\\*Status|[0-9]+ tasks" '
    "CLAUDE/Plan/00554-rust-relay-transport-default/PLAN.md && "
    "ls CLAUDE/Plan/00554-rust-relay-transport-default/JOURNAL/ && "
    'git log --oneline --grep="00554" -8'
)


@pytest.fixture(autouse=True)
def _project_root() -> Any:
    with patch("claude_code_hooks_daemon.core.project_context.ProjectContext.project_root") as m:
        m.return_value = Path("/tmp/test")
        yield m


@pytest.fixture(autouse=True)
def _reset_data_layer() -> Any:
    from claude_code_hooks_daemon.core.data_layer import reset_data_layer

    reset_data_layer()
    yield
    reset_data_layer()


def _handler(tmp_path: Path, plan_dir: str = "CLAUDE/Plan") -> PlanNumberHelperHandler:
    handler = PlanNumberHelperHandler()
    handler._workspace_root = tmp_path
    handler._track_plans_in_project = plan_dir
    return handler


def _bash(command: str) -> dict[str, Any]:
    return {"tool_name": "Bash", "tool_input": {"command": command}}


class TestListingInsideANumberedPlanFolder:
    """Targets inside `NNNNN-name/` are lookups of one plan, not scans."""

    @pytest.mark.parametrize(
        "command",
        [
            ISSUE_COMMAND,
            "ls CLAUDE/Plan/00554-x/JOURNAL/",
            "ls CLAUDE/Plan/Completed/00512-x/subagent-reports/",
            "find CLAUDE/Plan/00554-x -name '*.md'",
            "ls CLAUDE/Plan/00554-x",
            "ls -la CLAUDE/Plan/00554-x/JOURNAL/ | grep '[0-9]'",
        ],
    )
    def test_allowed(self, tmp_path: Path, command: str) -> None:
        assert _handler(tmp_path).matches(_bash(command)) is False

    def test_respects_a_custom_plan_directory(self, tmp_path: Path) -> None:
        handler = _handler(tmp_path, "docs/plans")
        assert handler.matches(_bash("ls docs/plans/00554-x/JOURNAL/ | grep '[0-9]'")) is False
        assert handler.matches(_bash("ls docs/plans | sort | tail -1")) is True


class TestPlanRootListingStillDenied:
    """Listings that read plan-folder names off the root stay denied."""

    @pytest.mark.parametrize(
        "command",
        [
            "ls CLAUDE/Plan | sort | tail -1",
            "ls CLAUDE/Plan/ | grep '[0-9]'",
            "find CLAUDE/Plan -maxdepth 1 -type d",
            "ls CLAUDE/Plan/0*",
            "ls CLAUDE/Plan/00554-x/JOURNAL/ && ls CLAUDE/Plan/0*",
            "ls CLAUDE/Plan/00554-x/ && find CLAUDE/Plan -maxdepth 1",
            "ls CLAUDE/Plan/00554-x/ | grep '[0-9]' && ls CLAUDE/Plan | grep '[0-9]'",
        ],
    )
    def test_denied(self, tmp_path: Path, command: str) -> None:
        handler = _handler(tmp_path)
        assert handler.matches(_bash(command)) is True
        assert handler.handle(_bash(command)).decision == Decision.DENY
