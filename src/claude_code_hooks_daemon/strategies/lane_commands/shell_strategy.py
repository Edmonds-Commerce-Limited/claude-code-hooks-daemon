"""Shell lane-command strategy - the shell linter."""

from typing import Any

from claude_code_hooks_daemon.strategies.lane_commands.common import lane_acceptance_test

_LANGUAGE_NAME = "Shell"
_LANE_PATTERNS: tuple[str, ...] = (r"^shellcheck\b",)
_ACCEPTANCE_COMMAND = "shellcheck scripts/install.sh"


class ShellLaneCommandStrategy:
    """Lane commands for shell scripts."""

    @property
    def language_name(self) -> str:
        return _LANGUAGE_NAME

    @property
    def lane_patterns(self) -> tuple[str, ...]:
        return _LANE_PATTERNS

    def get_acceptance_tests(self) -> list[Any]:
        """A host seat's shellcheck run is refused."""
        return [lane_acceptance_test(_LANGUAGE_NAME, _ACCEPTANCE_COMMAND)]
