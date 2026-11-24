"""PHP lane-command strategy - the test runner, composer test scripts, analysers."""

from typing import Any

from claude_code_hooks_daemon.strategies.lane_commands.common import lane_acceptance_test

_LANGUAGE_NAME = "PHP"
_LANE_PATTERNS: tuple[str, ...] = (
    r"^(?:phpstan|psalm|phpcs)\b",
    r"^phpunit\b",
    r"^composer\s+(?:test|run(?:-script)?\s+test\S*)(?=\s|$)",
)
_ACCEPTANCE_COMMAND = "composer test"


class PhpLaneCommandStrategy:
    """Lane commands for PHP projects."""

    @property
    def language_name(self) -> str:
        return _LANGUAGE_NAME

    @property
    def lane_patterns(self) -> tuple[str, ...]:
        return _LANE_PATTERNS

    def get_acceptance_tests(self) -> list[Any]:
        """A host seat's composer test run is refused."""
        return [lane_acceptance_test(_LANGUAGE_NAME, _ACCEPTANCE_COMMAND)]
