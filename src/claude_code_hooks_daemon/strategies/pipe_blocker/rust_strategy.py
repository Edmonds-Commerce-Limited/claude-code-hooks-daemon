"""Rust pipe-blocker strategy - expensive Rust cargo commands."""

from typing import Any

_LANGUAGE_NAME = "Rust"

# Rust cargo commands — expensive to pipe to tail/head
_BLACKLIST_PATTERNS: tuple[str, ...] = (
    r"^cargo\s+test\b",
    r"^cargo\s+build\b",
    r"^cargo\s+check\b",
    r"^cargo\s+clippy\b",
)


class RustPipeBlockerStrategy:
    """Pipe-blocker strategy for Rust cargo commands."""

    @property
    def language_name(self) -> str:
        return _LANGUAGE_NAME

    @property
    def blacklist_patterns(self) -> tuple[str, ...]:
        return _BLACKLIST_PATTERNS

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for Rust strategy."""
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="Rust: cargo test piped to tail",
                command='echo "cargo test | tail -20"',
                description="Blocks cargo test (expensive) piped to tail",
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"Pipe to tail/head", r"expensive"],
                safety_notes="Uses echo - safe to test",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
