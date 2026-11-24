"""Tests for the Go lane-command strategy."""

import pytest

from claude_code_hooks_daemon.strategies.lane_commands.common import runs_any
from claude_code_hooks_daemon.strategies.lane_commands.go_strategy import GoLaneCommandStrategy

STRATEGY = GoLaneCommandStrategy()


def test_language_name() -> None:
    assert STRATEGY.language_name == "Go"


@pytest.mark.parametrize(
    "command", ["go test ./...", "go build ./...", "go vet ./...", "golangci-lint run"]
)
def test_lane(command: str) -> None:
    assert runs_any(command, STRATEGY.lane_patterns) is True


@pytest.mark.parametrize("command", ["go run .", "go install x", "go mod tidy"])
def test_not_lane(command: str) -> None:
    assert runs_any(command, STRATEGY.lane_patterns) is False
