"""PHP QA suppression strategy implementation."""

from typing import Any

# ── Language-specific constants ──────────────────────────────────
_LANGUAGE_NAME = "PHP"
_EXTENSIONS: tuple[str, ...] = (".php",)
_FORBIDDEN_PATTERNS: tuple[str, ...] = (
    # PHPStan patterns (all variants)
    r"@phpstan-" + "ignore-next-line",
    r"@phpstan-" + "ignore-line",
    r"@phpstan-" + "ignore",  # Base pattern - catches all @phpstan-ignore variants
    # Psalm patterns
    r"@psalm-" + "suppress",
    # PHPCS patterns (current syntax)
    r"phpcs:" + "ignore",
    r"phpcs:" + "disable",
    r"phpcs:" + "enable",
    r"phpcs:" + "ignoreFile",
    # PHPCS patterns (deprecated, removed in v4.0)
    r"@codingStandards" + "IgnoreLine",
    r"@codingStandards" + "IgnoreStart",
    r"@codingStandards" + "IgnoreEnd",
    r"@codingStandards" + "IgnoreFile",
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
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="PHP @phpstan-ignore-next-line blocked",
                command=(
                    'Write file_path="/tmp/acceptance-test-qa-php/phpstan-next-line.php"'
                    ' content="<?php /** @phpstan-' + "ignore-next-line" + ' */ $x = 1;"'
                ),
                description="Should block @phpstan-ignore-next-line suppression",
                expected_decision=Decision.DENY,
                expected_message_patterns=["suppression", "BLOCKED", "PHP"],
                test_type=TestType.BLOCKING,
                safety_notes="Uses /tmp path - safe",
                setup_commands=["mkdir -p /tmp/acceptance-test-qa-php"],
                cleanup_commands=["rm -rf /tmp/acceptance-test-qa-php"],
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="PHP @phpstan-ignore (with identifier) blocked",
                command=(
                    'Write file_path="/tmp/acceptance-test-qa-php/phpstan-ignore.php"'
                    ' content="<?php /** @phpstan-' + "ignore" + ' argument.type */ $x = 1;"'
                ),
                description="Should block @phpstan-ignore with error identifier (modern pattern)",
                expected_decision=Decision.DENY,
                expected_message_patterns=["suppression", "BLOCKED", "PHP"],
                test_type=TestType.BLOCKING,
                safety_notes="Uses /tmp path - safe",
                setup_commands=["mkdir -p /tmp/acceptance-test-qa-php"],
                cleanup_commands=["rm -rf /tmp/acceptance-test-qa-php"],
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="PHP phpcs:disable blocked",
                command=(
                    'Write file_path="/tmp/acceptance-test-qa-php/phpcs-disable.php"'
                    ' content="<?php // phpcs:' + "disable" + '\\n$x = 1;"'
                ),
                description="Should block phpcs:disable block-level suppression",
                expected_decision=Decision.DENY,
                expected_message_patterns=["suppression", "BLOCKED", "PHP"],
                test_type=TestType.BLOCKING,
                safety_notes="Uses /tmp path - safe",
                setup_commands=["mkdir -p /tmp/acceptance-test-qa-php"],
                cleanup_commands=["rm -rf /tmp/acceptance-test-qa-php"],
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
