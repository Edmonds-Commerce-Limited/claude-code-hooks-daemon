"""Ruby pipe-blocker strategy - expensive Ruby test/lint commands."""

from typing import Any

_LANGUAGE_NAME = "Ruby"

# Ruby test runners, linters, and task runners — expensive to pipe to tail/head
_BLACKLIST_PATTERNS: tuple[str, ...] = (
    r"^rspec\b",
    r"^rubocop\b",
    r"^rake\b",
    r"^bundle\s+exec\b",
)


class RubyPipeBlockerStrategy:
    """Pipe-blocker strategy for Ruby test/lint commands."""

    @property
    def language_name(self) -> str:
        return _LANGUAGE_NAME

    @property
    def blacklist_patterns(self) -> tuple[str, ...]:
        return _BLACKLIST_PATTERNS

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for Ruby strategy."""
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="Ruby: rspec piped to tail",
                command='echo "rspec | tail -20"',
                description="Blocks rspec (expensive test runner) piped to tail",
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"Pipe to tail/head", r"expensive"],
                safety_notes="Uses echo - safe to test",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
