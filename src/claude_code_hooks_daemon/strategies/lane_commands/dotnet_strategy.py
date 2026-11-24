""".NET lane-command strategy - dotnet test and build."""

from typing import Any

from claude_code_hooks_daemon.strategies.lane_commands.common import lane_acceptance_test

_LANGUAGE_NAME = ".NET"
_LANE_PATTERNS: tuple[str, ...] = (r"^dotnet\s+(?:test|build)(?=\s|$)",)
_ACCEPTANCE_COMMAND = "dotnet test"


class DotNetLaneCommandStrategy:
    """Lane commands for .NET projects."""

    @property
    def language_name(self) -> str:
        return _LANGUAGE_NAME

    @property
    def lane_patterns(self) -> tuple[str, ...]:
        return _LANE_PATTERNS

    def get_acceptance_tests(self) -> list[Any]:
        """A host seat's dotnet test run is refused."""
        return [lane_acceptance_test(_LANGUAGE_NAME, _ACCEPTANCE_COMMAND)]
