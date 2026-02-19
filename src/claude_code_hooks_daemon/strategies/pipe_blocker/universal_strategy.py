"""Universal pipe-blocker strategy - build/infrastructure commands always expensive."""

from typing import Any

_LANGUAGE_NAME = "Universal"

# Build and infrastructure commands that are always expensive regardless of project language
_BLACKLIST_PATTERNS: tuple[str, ...] = (
    r"^make\b",
    r"^cmake\b",
    r"^docker\s+build\b",
    r"^kubectl\b",
    r"^terraform\b",
    r"^helm\b",
)


class UniversalPipeBlockerStrategy:
    """Pipe-blocker strategy for build/infrastructure commands (language-agnostic).

    These commands are expensive across all project types and should never be
    piped to tail/head. This strategy is ALWAYS active and cannot be filtered
    out by language configuration.
    """

    @property
    def language_name(self) -> str:
        return _LANGUAGE_NAME

    @property
    def blacklist_patterns(self) -> tuple[str, ...]:
        return _BLACKLIST_PATTERNS

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for universal strategy."""
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="Universal: make piped to tail",
                command='echo "make build | tail -20"',
                description="Blocks make (universal build command) piped to tail",
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"Pipe to tail/head", r"expensive"],
                safety_notes="Uses echo - safe to test",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
