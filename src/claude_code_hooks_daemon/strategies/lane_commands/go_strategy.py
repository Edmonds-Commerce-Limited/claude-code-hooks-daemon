"""Go lane-command strategy - go test, build, vet and the Go linter."""

from typing import Any

from claude_code_hooks_daemon.strategies.lane_commands.common import lane_acceptance_test

_LANGUAGE_NAME = "Go"
_LANE_PATTERNS: tuple[str, ...] = (
    r"^go\s+test\b",
    r"^go\s+(?:build|vet)\b",
    r"^golangci-lint\b",
)
_ACCEPTANCE_COMMAND = "go test ./..."


class GoLaneCommandStrategy:
    """Lane commands for Go projects."""

    @property
    def language_name(self) -> str:
        return _LANGUAGE_NAME

    @property
    def lane_patterns(self) -> tuple[str, ...]:
        return _LANE_PATTERNS

    def get_acceptance_tests(self) -> list[Any]:
        """A host seat's go test run is refused."""
        return [lane_acceptance_test(_LANGUAGE_NAME, _ACCEPTANCE_COMMAND)]
