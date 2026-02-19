"""Java pipe-blocker strategy - expensive Java build/test commands."""

from typing import Any

_LANGUAGE_NAME = "Java"

# Java build tools and compilers — expensive to pipe to tail/head
_BLACKLIST_PATTERNS: tuple[str, ...] = (
    r"^mvn\b",
    r"^gradle\b",
    r"^\./gradlew\b",
    r"^javac\b",
)


class JavaPipeBlockerStrategy:
    """Pipe-blocker strategy for Java build/test commands."""

    @property
    def language_name(self) -> str:
        return _LANGUAGE_NAME

    @property
    def blacklist_patterns(self) -> tuple[str, ...]:
        return _BLACKLIST_PATTERNS

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for Java strategy."""
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="Java: mvn test piped to tail",
                command='echo "mvn test | tail -20"',
                description="Blocks mvn test (expensive) piped to tail",
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"Pipe to tail/head", r"expensive"],
                safety_notes="Uses echo - safe to test",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
