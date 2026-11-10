"""pipe_blocker: Task 2.2f review minors (heredoc-authored script, py.test)."""

from typing import Any

import pytest

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use.pipe_blocker import PipeBlockerHandler


def _event(command: str) -> dict[str, Any]:
    return {"tool_name": "Bash", "tool_input": {"command": command}}


@pytest.fixture
def handler() -> PipeBlockerHandler:
    return PipeBlockerHandler()


class TestHeredocAuthoredScriptRunInSameCommand:
    """A script written by heredoc and run in the same command names its producer."""

    @pytest.mark.parametrize(
        "command",
        [
            "cat > t.sh <<'EOF'\npytest -q\nEOF\nbash t.sh | tail -5",
            "cat > t.sh <<'EOF'\npytest -q tests/\nEOF\nbash t.sh 2>&1 | tail -20",
            "tee t.sh <<'EOF'\npytest -q\nEOF\nsh t.sh | tail",
        ],
    )
    def test_denies(self, handler: PipeBlockerHandler, command: str) -> None:
        assert handler.matches(_event(command))
        assert handler.handle(_event(command)).decision == Decision.DENY

    def test_heredoc_without_blacklisted_name_keeps_allowing(
        self, handler: PipeBlockerHandler
    ) -> None:
        command = "cat > t.sh <<'EOF'\necho hello\nEOF\nbash t.sh | tail -5"
        assert handler.handle(_event(command)).decision == Decision.ALLOW


class TestLegacyPyTestEntryPoint:
    """`py.test` is pytest."""

    @pytest.mark.parametrize(
        "command",
        [
            "py.test | tail",
            "python -m py.test | tail",
            "uv run py.test | tail",
            "py.test tests/ 2>&1 | head -5",
        ],
    )
    def test_denies(self, handler: PipeBlockerHandler, command: str) -> None:
        assert handler.handle(_event(command)).decision == Decision.DENY
