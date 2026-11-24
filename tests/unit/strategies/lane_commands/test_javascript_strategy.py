"""Tests for the JavaScript lane-command strategy."""

import pytest

from claude_code_hooks_daemon.strategies.lane_commands.common import runs_any
from claude_code_hooks_daemon.strategies.lane_commands.javascript_strategy import (
    JavaScriptLaneCommandStrategy,
)

STRATEGY = JavaScriptLaneCommandStrategy()


def test_language_name() -> None:
    assert STRATEGY.language_name == "JavaScript"


@pytest.mark.parametrize(
    "command",
    [
        "jest",
        "vitest run",
        "playwright test",
        "mocha",
        "npm test",
        "yarn test",
        "pnpm test",
        "bun test",
        "npm run test:unit",
        "npm t",
        "pnpm t",
        "npm build",
        "npm run build",
        "yarn build",
        "tsc -p .",
        "webpack",
        "eslint .",
        "prettier --check .",
        "stylelint x.css",
        "npm run lint",
        "yarn typecheck",
        "npm run llm:lint",
        "npx jest",
        "npx tsc",
    ],
)
def test_lane(command: str) -> None:
    assert runs_any(command, STRATEGY.lane_patterns) is True


@pytest.mark.parametrize(
    "command",
    [
        "npm install",
        "npm i",
        "npm token list",
        "npm start",
        "npm run deploy",
        "npx create-react-app x",
    ],
)
def test_not_lane(command: str) -> None:
    assert runs_any(command, STRATEGY.lane_patterns) is False
