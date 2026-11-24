"""Tests for the Rust lane-command strategy."""

import pytest

from claude_code_hooks_daemon.strategies.lane_commands.common import runs_any
from claude_code_hooks_daemon.strategies.lane_commands.rust_strategy import (
    RustLaneCommandStrategy,
)

STRATEGY = RustLaneCommandStrategy()


def test_language_name() -> None:
    assert STRATEGY.language_name == "Rust"


@pytest.mark.parametrize(
    "command",
    [
        "cargo test",
        "cargo bench",
        "cargo build --release",
        "cargo check",
        "cargo clippy",
        "cargo fmt",
    ],
)
def test_lane(command: str) -> None:
    assert runs_any(command, STRATEGY.lane_patterns) is True


@pytest.mark.parametrize("command", ["cargo run", "cargo install x", "cargo update"])
def test_not_lane(command: str) -> None:
    assert runs_any(command, STRATEGY.lane_patterns) is False
