"""An echo/printf glob rule does not read into a substitution (GitHub #198)."""

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.core.hook_result import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use.plan_number_helper import (
    PlanNumberHelperHandler,
)

PLAN_DIR = "CLAUDE/Plan"


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


def _handler(tmp_path: Path) -> PlanNumberHelperHandler:
    handler = PlanNumberHelperHandler()
    handler._workspace_root = tmp_path
    handler._track_plans_in_project = PLAN_DIR
    return handler


def _bash(command: str) -> dict[str, Any]:
    return {"tool_name": "Bash", "tool_input": {"command": command}}


class TestEchoGlobInsideSubstitutionAllowed:
    """A glob inside a substitution belongs to the inner command."""

    @pytest.mark.parametrize(
        "command",
        [
            f"echo \"found: $(grep -rl takeover {PLAN_DIR}/00001*/subagent-reports/ | tr '\\n' ' ')\"",
            f'for p in a b; do echo "== $p: $(grep -rlE x {PLAN_DIR}/00001*/)"; done',
            f'echo "found: `grep -rl takeover {PLAN_DIR}/00001*/subagent-reports/`"',
            f"echo {PLAN_DIR}/00001*/PLAN.md",
            f"echo {PLAN_DIR}/00001-*",
            f"echo <(grep -rl x {PLAN_DIR}/0*/)",
        ],
    )
    def test_allowed(self, tmp_path: Path, command: str) -> None:
        assert _handler(tmp_path).matches(_bash(command)) is False


class TestEchoDiscoveryStillDenied:
    """A real echo scan, or a scan inside the substitution, still denies."""

    @pytest.mark.parametrize(
        "command",
        [
            f"echo {PLAN_DIR}/*",
            f"echo {PLAN_DIR}/0*",
            f"printf '%s\\n' {PLAN_DIR}/*/",
            f"echo $(ls {PLAN_DIR}/*)",
            f"echo `ls -d {PLAN_DIR}/0*`",
            f'echo "$(ls -d {PLAN_DIR}/* | tail -1)"',
            f'echo "$(ls {PLAN_DIR}/0*)" {PLAN_DIR}/*',
            f"echo $((1+2)) {PLAN_DIR}/*",
            f'echo "$(( 1 + 1 ))" {PLAN_DIR}/0*',
            f"echo $(foo (bar)) {PLAN_DIR}/*",
        ],
    )
    def test_denied(self, tmp_path: Path, command: str) -> None:
        handler = _handler(tmp_path)
        assert handler.matches(_bash(command)) is True
        assert handler.handle(_bash(command)).decision == Decision.DENY
