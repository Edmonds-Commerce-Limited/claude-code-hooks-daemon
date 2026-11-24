"""Tests for the Java lane-command strategy."""

import pytest

from claude_code_hooks_daemon.strategies.lane_commands.common import runs_any
from claude_code_hooks_daemon.strategies.lane_commands.java_strategy import (
    JavaLaneCommandStrategy,
)

STRATEGY = JavaLaneCommandStrategy()


def test_language_name() -> None:
    assert STRATEGY.language_name == "Java"


@pytest.mark.parametrize(
    "command",
    [
        "mvn test",
        "mvn verify",
        "mvn package",
        "gradle build",
        "gradle test",
        "./gradlew test",
        "ant compile",
    ],
)
def test_lane(command: str) -> None:
    assert runs_any(command, STRATEGY.lane_patterns) is True


@pytest.mark.parametrize(
    "command",
    ["mvn deploy", "mvn clean deploy -DskipTests", "gradle publish", "./gradlew publish"],
)
def test_shipping_goals_are_deployment(command: str) -> None:
    assert runs_any(command, STRATEGY.lane_patterns) is False
