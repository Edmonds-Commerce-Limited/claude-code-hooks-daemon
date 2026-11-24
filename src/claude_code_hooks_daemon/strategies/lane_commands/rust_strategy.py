"""Rust lane-command strategy - cargo test, build, lint and format."""

from typing import Any

from claude_code_hooks_daemon.strategies.lane_commands.common import lane_acceptance_test

_LANGUAGE_NAME = "Rust"
_LANE_PATTERNS: tuple[str, ...] = (
    r"^cargo\s+(?:test|bench)\b",
    r"^cargo\s+(?:build|check|clippy)\b",
    r"^cargo\s+fmt\b",
)
_ACCEPTANCE_COMMAND = "cargo test"


class RustLaneCommandStrategy:
    """Lane commands for Rust projects."""

    @property
    def language_name(self) -> str:
        return _LANGUAGE_NAME

    @property
    def lane_patterns(self) -> tuple[str, ...]:
        return _LANE_PATTERNS

    def get_acceptance_tests(self) -> list[Any]:
        """A host seat's cargo test run is refused."""
        return [lane_acceptance_test(_LANGUAGE_NAME, _ACCEPTANCE_COMMAND)]
