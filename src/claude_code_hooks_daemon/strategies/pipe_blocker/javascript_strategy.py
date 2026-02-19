"""JavaScript/TypeScript pipe-blocker strategy - expensive JS tooling commands."""

from typing import Any

_LANGUAGE_NAME = "JavaScript"

# JavaScript/TypeScript test runners, bundlers, and linters — expensive to pipe
_BLACKLIST_PATTERNS: tuple[str, ...] = (
    r"^npm\s+test\b",
    r"^npm\s+run\b",
    r"^npm\s+build\b",
    r"^npm\s+audit\b",
    r"^jest\b",
    r"^vitest\b",
    r"^eslint\b",
    r"^tsc\b",
    r"^webpack\b",
    r"^yarn\s+test\b",
)


class JavaScriptPipeBlockerStrategy:
    """Pipe-blocker strategy for JavaScript/TypeScript test/build commands."""

    @property
    def language_name(self) -> str:
        return _LANGUAGE_NAME

    @property
    def blacklist_patterns(self) -> tuple[str, ...]:
        return _BLACKLIST_PATTERNS

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for JavaScript strategy."""
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="JavaScript: npm test piped to tail",
                command='echo "npm test | tail -10"',
                description="Blocks npm test (expensive) piped to tail",
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"Pipe to tail/head", r"expensive"],
                safety_notes="Uses echo - safe to test",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
