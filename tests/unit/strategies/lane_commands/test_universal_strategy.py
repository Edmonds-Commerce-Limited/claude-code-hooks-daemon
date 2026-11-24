"""Tests for the Universal lane-command strategy."""

import pytest

from claude_code_hooks_daemon.strategies.lane_commands.common import runs_any
from claude_code_hooks_daemon.strategies.lane_commands.universal_strategy import (
    UniversalLaneCommandStrategy,
)

STRATEGY = UniversalLaneCommandStrategy()


def test_language_name() -> None:
    assert STRATEGY.language_name == "Universal"


@pytest.mark.parametrize(
    "command",
    [
        "make",
        "make -j4",
        "make test",
        "make -j4 build",
        "make check",
        "make lint",
        "make ci",
        "cmake --build .",
        "ninja",
        "bazel build //...",
        "./scripts/qa/llm_qa.py changed",
        "bash scripts/qa/run_all.sh",
        "./run_tests.sh",
        "./qa.sh",
        "lint.sh",
        "python3 tests/test_thing.py",
        "pre-commit run",
        "pre-commit run --all-files",
        "hadolint Dockerfile",
        "markdownlint x.md",
        "yamllint x.yml",
    ],
)
def test_lane(command: str) -> None:
    assert runs_any(command, STRATEGY.lane_patterns) is True


@pytest.mark.parametrize(
    "command",
    [
        "make deploy",
        "./deploy-qa.sh",
        "./deploy_test.sh",
        "./smoke_test.sh",
        "./test-connection.sh",
        "pre-commit install",
        "pre-commit autoupdate",
        "./deploy.sh production",
    ],
)
def test_not_lane(command: str) -> None:
    assert runs_any(command, STRATEGY.lane_patterns) is False
