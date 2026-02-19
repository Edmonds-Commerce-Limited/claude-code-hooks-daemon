"""Go pipe-blocker strategy - expensive Go tooling commands."""

from typing import Any

_LANGUAGE_NAME = "Go"

# Go test/build/vet commands — expensive to pipe to tail/head
_BLACKLIST_PATTERNS: tuple[str, ...] = (
    r"^go\s+test\b",
    r"^go\s+build\b",
    r"^go\s+vet\b",
)


class GoPipeBlockerStrategy:
    """Pipe-blocker strategy for Go build/test commands."""

    @property
    def language_name(self) -> str:
        return _LANGUAGE_NAME

    @property
    def blacklist_patterns(self) -> tuple[str, ...]:
        return _BLACKLIST_PATTERNS

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for Go strategy."""
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="Go: go test piped to tail",
                command='echo "go test ./... | tail -20"',
                description="Blocks go test (expensive) piped to tail",
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"Pipe to tail/head", r"expensive"],
                safety_notes="Uses echo - safe to test",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
