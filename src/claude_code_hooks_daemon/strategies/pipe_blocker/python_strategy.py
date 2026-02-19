"""Python pipe-blocker strategy - expensive Python tooling commands."""

from typing import Any

_LANGUAGE_NAME = "Python"

# Python test runners, linters, and QA tools — all expensive to pipe
_BLACKLIST_PATTERNS: tuple[str, ...] = (
    r"^pytest\b",
    r"^python\s+-m\s+pytest\b",
    r"^mypy\b",
    r"^ruff\s+check\b",
    r"^black\b",
    r"^bandit\b",
    r"^coverage\b",
    r"^tox\b",
    r"^pylint\b",
    r"^flake8\b",
)


class PythonPipeBlockerStrategy:
    """Pipe-blocker strategy for Python test/QA commands."""

    @property
    def language_name(self) -> str:
        return _LANGUAGE_NAME

    @property
    def blacklist_patterns(self) -> tuple[str, ...]:
        return _BLACKLIST_PATTERNS

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for Python strategy."""
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="Python: pytest piped to tail",
                command='echo "pytest | tail -20"',
                description="Blocks pytest (expensive test runner) piped to tail",
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"Pipe to tail/head", r"expensive"],
                safety_notes="Uses echo - safe to test",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
