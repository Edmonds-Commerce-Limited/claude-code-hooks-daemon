"""Tests for the .NET lane-command strategy."""

import pytest

from claude_code_hooks_daemon.strategies.lane_commands.common import runs_any
from claude_code_hooks_daemon.strategies.lane_commands.dotnet_strategy import (
    DotNetLaneCommandStrategy,
)

STRATEGY = DotNetLaneCommandStrategy()


def test_language_name() -> None:
    assert STRATEGY.language_name == ".NET"


@pytest.mark.parametrize("command", ["dotnet test", "dotnet build -c Release"])
def test_lane(command: str) -> None:
    assert runs_any(command, STRATEGY.lane_patterns) is True


@pytest.mark.parametrize(
    "command", ["dotnet publish", "dotnet run", "dotnet restore", "dotnet build-server shutdown"]
)
def test_not_lane(command: str) -> None:
    assert runs_any(command, STRATEGY.lane_patterns) is False
