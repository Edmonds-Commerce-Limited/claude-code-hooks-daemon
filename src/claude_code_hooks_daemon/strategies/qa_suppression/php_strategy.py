"""PHP QA suppression strategy implementation."""

from typing import Any

# ── Language-specific constants ──────────────────────────────────
_LANGUAGE_NAME = "PHP"
_EXTENSIONS: tuple[str, ...] = (".php",)
_FORBIDDEN_PATTERNS: tuple[str, ...] = (
    r"@phpstan-" + "ignore-next-line",
    r"@psalm-" + "suppress",
    r"phpcs:" + "ignore",
    r"@codingStandards" + "IgnoreLine",
    r"@phpstan-" + "ignore-line",
)
_SKIP_DIRECTORIES: tuple[str, ...] = (
    "tests/fixtures/",
    "vendor/",
)
_TOOL_NAMES: tuple[str, ...] = ("PHPStan", "Psalm", "PHP_CodeSniffer")
_TOOL_DOCS_URLS: tuple[str, ...] = (
    "https://phpstan.org/",
    "https://psalm.dev/",
    "https://github.com/squizlabs/PHP_CodeSniffer",
)


class PhpQaSuppressionStrategy:
    """QA suppression strategy for PHP."""

    @property
    def language_name(self) -> str:
        return _LANGUAGE_NAME

    @property
    def extensions(self) -> tuple[str, ...]:
        return _EXTENSIONS

    @property
    def forbidden_patterns(self) -> tuple[str, ...]:
        return _FORBIDDEN_PATTERNS

    @property
    def skip_directories(self) -> tuple[str, ...]:
        return _SKIP_DIRECTORIES

    @property
    def tool_names(self) -> tuple[str, ...]:
        return _TOOL_NAMES

    @property
    def tool_docs_urls(self) -> tuple[str, ...]:
        return _TOOL_DOCS_URLS

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for PHP QA suppression strategy."""
        from claude_code_hooks_daemon.core import AcceptanceTest, Decision, TestType

        return [
            AcceptanceTest(
                title="PHP QA suppression blocked",
                command=(
                    'Write file_path="/tmp/acceptance-test-qa-php/example.php"'
                    ' content="<?php /** @phpstan-' + "ignore-next-line" + ' */ $x = 1;"'
                ),
                description="Should block PHP QA suppression comment",
                expected_decision=Decision.DENY,
                expected_message_patterns=["suppression", "BLOCKED", "PHP"],
                test_type=TestType.BLOCKING,
                safety_notes="Uses /tmp path - safe",
                setup_commands=["mkdir -p /tmp/acceptance-test-qa-php"],
                cleanup_commands=["rm -rf /tmp/acceptance-test-qa-php"],
            ),
        ]
