"""Tests for the Ruby lane-command strategy."""

import pytest

from claude_code_hooks_daemon.strategies.lane_commands.common import runs_any
from claude_code_hooks_daemon.strategies.lane_commands.ruby_strategy import (
    RubyLaneCommandStrategy,
)

STRATEGY = RubyLaneCommandStrategy()


def test_language_name() -> None:
    assert STRATEGY.language_name == "Ruby"


@pytest.mark.parametrize(
    "command", ["rspec", "rspec spec/x_spec.rb", "bundle exec rspec", "rubocop"]
)
def test_lane(command: str) -> None:
    assert runs_any(command, STRATEGY.lane_patterns) is True


@pytest.mark.parametrize(
    "command",
    ["bundle install", "bundle exec rails s", "rails s", "rspec-x", "bundle exec rspec-queue"],
)
def test_not_lane(command: str) -> None:
    assert runs_any(command, STRATEGY.lane_patterns) is False
