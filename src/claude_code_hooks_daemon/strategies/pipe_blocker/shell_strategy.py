"""Shell pipe-blocker strategy - expensive shell linting commands."""

from typing import Any

_LANGUAGE_NAME = "Shell"

# Shell linting/checking tools — expensive to pipe to tail/head
_BLACKLIST_PATTERNS: tuple[str, ...] = (r"^shellcheck\b",)


class ShellPipeBlockerStrategy:
    """Pipe-blocker strategy for Shell linting commands."""

    @property
    def language_name(self) -> str:
        return _LANGUAGE_NAME

    @property
    def blacklist_patterns(self) -> tuple[str, ...]:
        return _BLACKLIST_PATTERNS

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for Shell strategy."""
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="Shell: shellcheck piped to tail",
                command='echo "shellcheck script.sh | tail -5"',
                description="Blocks shellcheck (expensive linter) piped to tail",
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"Pipe to tail/head", r"expensive"],
                safety_notes="Uses echo - safe to test",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
