"""Tests for the Shell lane-command strategy."""

import pytest

from claude_code_hooks_daemon.strategies.lane_commands.common import runs_any
from claude_code_hooks_daemon.strategies.lane_commands.shell_strategy import (
    ShellLaneCommandStrategy,
)

STRATEGY = ShellLaneCommandStrategy()


def test_language_name() -> None:
    assert STRATEGY.language_name == "Shell"


@pytest.mark.parametrize("command", ["shellcheck x.sh", "timeout 30 shellcheck scripts/*.sh"])
def test_lane(command: str) -> None:
    assert runs_any(command, STRATEGY.lane_patterns) is True


@pytest.mark.parametrize("command", ["bash deploy.sh", "shellcheckers", "cat x.sh"])
def test_not_lane(command: str) -> None:
    assert runs_any(command, STRATEGY.lane_patterns) is False
