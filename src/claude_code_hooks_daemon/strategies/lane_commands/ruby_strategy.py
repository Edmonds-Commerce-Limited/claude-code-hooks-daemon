"""Ruby lane-command strategy - the spec runner and the Ruby linter."""

from typing import Any

from claude_code_hooks_daemon.strategies.lane_commands.common import lane_acceptance_test

_LANGUAGE_NAME = "Ruby"
_LANE_PATTERNS: tuple[str, ...] = (
    r"^rubocop\b",
    # The shared classifier does not peel `bundle exec`, so it is spelled here.
    r"^(?:bundle\s+exec\s+)?rspec\b",
)
_ACCEPTANCE_COMMAND = "bundle exec rspec"


class RubyLaneCommandStrategy:
    """Lane commands for Ruby projects."""

    @property
    def language_name(self) -> str:
        return _LANGUAGE_NAME

    @property
    def lane_patterns(self) -> tuple[str, ...]:
        return _LANE_PATTERNS

    def get_acceptance_tests(self) -> list[Any]:
        """A host seat's rspec run is refused."""
        return [lane_acceptance_test(_LANGUAGE_NAME, _ACCEPTANCE_COMMAND)]
