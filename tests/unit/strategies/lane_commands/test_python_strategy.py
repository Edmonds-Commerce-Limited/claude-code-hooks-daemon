"""Tests for the Python lane-command strategy."""

import pytest

from claude_code_hooks_daemon.strategies.lane_commands.common import runs_any
from claude_code_hooks_daemon.strategies.lane_commands.python_strategy import (
    PythonLaneCommandStrategy,
)

STRATEGY = PythonLaneCommandStrategy()


def test_language_name() -> None:
    assert STRATEGY.language_name == "Python"


@pytest.mark.parametrize(
    "command",
    [
        "pytest tests/",
        "py.test",
        "python3 -m pytest -x",
        "uv run pytest",
        "tox -e py",
        "nox -s tests",
        "uv build",
        "ruff check src",
        "mypy src",
        "pyright",
        "pylint x",
        "flake8",
        "black --check src",
        "isort .",
        "bandit -r src",
        "python3 -m unittest discover",
    ],
)
def test_lane(command: str) -> None:
    assert runs_any(command, STRATEGY.lane_patterns) is True


@pytest.mark.parametrize(
    "command",
    ["pip install x", "uv sync", "python3 app.py", "ruffle", "which pytest", "echo pytest"],
)
def test_not_lane(command: str) -> None:
    assert runs_any(command, STRATEGY.lane_patterns) is False
