"""Tests for PHP QA suppression strategy."""

import re

from claude_code_hooks_daemon.strategies.qa_suppression.php_strategy import (
    PhpQaSuppressionStrategy,
)
from claude_code_hooks_daemon.strategies.qa_suppression.protocol import (
    QaSuppressionStrategy,
)


def _phpstan_ignore_text() -> str:
    return "@phpstan-ignore" + "-next-line"


def _psalm_suppress_text() -> str:
    return "@psalm" + "-suppress"


def _phpstan_ignore_base_text() -> str:
    return "@phpstan" + "-ignore"


def _phpcs_disable_text() -> str:
    return "phpcs:" + "disable"


def _phpcs_enable_text() -> str:
    return "phpcs:" + "enable"


def _phpcs_ignore_file_text() -> str:
    return "phpcs:" + "ignoreFile"


def _coding_standards_ignore_start_text() -> str:
    return "@codingStandards" + "IgnoreStart"


def _coding_standards_ignore_end_text() -> str:
    return "@codingStandards" + "IgnoreEnd"


def _coding_standards_ignore_file_text() -> str:
    return "@codingStandards" + "IgnoreFile"


def test_implements_protocol() -> None:
    """PhpQaSuppressionStrategy should implement QaSuppressionStrategy protocol."""
    strategy = PhpQaSuppressionStrategy()
    assert isinstance(strategy, QaSuppressionStrategy)


def test_language_name() -> None:
    """Language name should be 'PHP'."""
    strategy = PhpQaSuppressionStrategy()
    assert strategy.language_name == "PHP"


def test_extensions() -> None:
    """Extensions should be ('.php',)."""
    strategy = PhpQaSuppressionStrategy()
    assert strategy.extensions == (".php",)


def test_forbidden_patterns_not_empty() -> None:
    """Should have forbidden patterns defined."""
    strategy = PhpQaSuppressionStrategy()
    assert len(strategy.forbidden_patterns) > 0


def test_forbidden_patterns_are_valid_regex() -> None:
    """All forbidden patterns should be valid regex."""
    strategy = PhpQaSuppressionStrategy()
    for pattern in strategy.forbidden_patterns:
        re.compile(pattern)


def test_matches_phpstan_ignore() -> None:
    """Should match phpstan-ignore-next-line."""
    strategy = PhpQaSuppressionStrategy()
    patterns = strategy.forbidden_patterns
    text = f"/** {_phpstan_ignore_text()} */"
    assert any(re.search(p, text, re.IGNORECASE) for p in patterns)


def test_matches_psalm_suppress() -> None:
    """Should match psalm-suppress."""
    strategy = PhpQaSuppressionStrategy()
    patterns = strategy.forbidden_patterns
    text = f"/** {_psalm_suppress_text()} InvalidArgument */"
    assert any(re.search(p, text, re.IGNORECASE) for p in patterns)


def test_skip_directories_not_empty() -> None:
    """Should have skip directories defined."""
    strategy = PhpQaSuppressionStrategy()
    assert len(strategy.skip_directories) > 0


def test_skip_directories_include_vendor() -> None:
    """Skip directories should include vendor/."""
    strategy = PhpQaSuppressionStrategy()
    assert "vendor/" in strategy.skip_directories


def test_tool_names_not_empty() -> None:
    """Should have tool names defined."""
    strategy = PhpQaSuppressionStrategy()
    assert len(strategy.tool_names) > 0


def test_tool_docs_urls_not_empty() -> None:
    """Should have tool docs URLs defined."""
    strategy = PhpQaSuppressionStrategy()
    assert len(strategy.tool_docs_urls) > 0


def test_acceptance_tests_provided() -> None:
    """Should provide at least one acceptance test."""
    strategy = PhpQaSuppressionStrategy()
    tests = strategy.get_acceptance_tests()
    assert len(tests) > 0


# ── Tests for Missing Patterns (Bug Fix) ────────────────────────────


def test_matches_phpstan_ignore_base() -> None:
    """Should match @phpstan-ignore (base pattern without suffix).

    Bug: @phpstan-ignore is the modern PHPStan suppression pattern (v1.11+)
    that allows error identifier specification like @phpstan-ignore argument.type
    This test MUST FAIL before the fix.
    """
    strategy = PhpQaSuppressionStrategy()
    patterns = strategy.forbidden_patterns
    text = f"/** {_phpstan_ignore_base_text()} argument.type */"
    assert any(
        re.search(p, text, re.IGNORECASE) for p in patterns
    ), "Should block @phpstan-ignore with error identifier"


def test_matches_phpstan_ignore_without_identifier() -> None:
    """Should match @phpstan-ignore even without error identifier."""
    strategy = PhpQaSuppressionStrategy()
    patterns = strategy.forbidden_patterns
    text = f"// {_phpstan_ignore_base_text()}"
    assert any(
        re.search(p, text, re.IGNORECASE) for p in patterns
    ), "Should block @phpstan-ignore base pattern"


def test_matches_phpcs_disable() -> None:
    """Should match phpcs:disable (block start suppression).

    Bug: phpcs:disable allows block-level suppression of PHPCS checks.
    This test MUST FAIL before the fix.
    """
    strategy = PhpQaSuppressionStrategy()
    patterns = strategy.forbidden_patterns
    text = f"// {_phpcs_disable_text()}"
    assert any(re.search(p, text, re.IGNORECASE) for p in patterns), "Should block phpcs:disable"


def test_matches_phpcs_disable_with_sniffs() -> None:
    """Should match phpcs:disable even with specific sniff names."""
    strategy = PhpQaSuppressionStrategy()
    patterns = strategy.forbidden_patterns
    text = f"// {_phpcs_disable_text()} PEAR,Squiz.Arrays"
    assert any(
        re.search(p, text, re.IGNORECASE) for p in patterns
    ), "Should block phpcs:disable with sniff specifications"


def test_matches_phpcs_enable() -> None:
    """Should match phpcs:enable (block end suppression).

    Bug: phpcs:enable re-enables checks after phpcs:disable block.
    This test MUST FAIL before the fix.
    """
    strategy = PhpQaSuppressionStrategy()
    patterns = strategy.forbidden_patterns
    text = f"// {_phpcs_enable_text()}"
    assert any(re.search(p, text, re.IGNORECASE) for p in patterns), "Should block phpcs:enable"


def test_matches_phpcs_ignore_file() -> None:
    """Should match phpcs:ignoreFile (entire file suppression).

    Bug: phpcs:ignoreFile exempts entire files from PHPCS checks.
    This test MUST FAIL before the fix.
    """
    strategy = PhpQaSuppressionStrategy()
    patterns = strategy.forbidden_patterns
    text = f"// {_phpcs_ignore_file_text()}"
    assert any(re.search(p, text, re.IGNORECASE) for p in patterns), "Should block phpcs:ignoreFile"


def test_matches_coding_standards_ignore_start() -> None:
    """Should match @codingStandardsIgnoreStart (deprecated PHPCS syntax).

    Bug: Deprecated but still used in legacy codebases.
    This test MUST FAIL before the fix.
    """
    strategy = PhpQaSuppressionStrategy()
    patterns = strategy.forbidden_patterns
    text = f"// {_coding_standards_ignore_start_text()}"
    assert any(
        re.search(p, text, re.IGNORECASE) for p in patterns
    ), "Should block @codingStandardsIgnoreStart (deprecated)"


def test_matches_coding_standards_ignore_end() -> None:
    """Should match @codingStandardsIgnoreEnd (deprecated PHPCS syntax).

    Bug: Deprecated but still used in legacy codebases.
    This test MUST FAIL before the fix.
    """
    strategy = PhpQaSuppressionStrategy()
    patterns = strategy.forbidden_patterns
    text = f"// {_coding_standards_ignore_end_text()}"
    assert any(
        re.search(p, text, re.IGNORECASE) for p in patterns
    ), "Should block @codingStandardsIgnoreEnd (deprecated)"


def test_matches_coding_standards_ignore_file() -> None:
    """Should match @codingStandardsIgnoreFile (deprecated PHPCS syntax).

    Bug: Deprecated but still used in legacy codebases.
    This test MUST FAIL before the fix.
    """
    strategy = PhpQaSuppressionStrategy()
    patterns = strategy.forbidden_patterns
    text = f"// {_coding_standards_ignore_file_text()}"
    assert any(
        re.search(p, text, re.IGNORECASE) for p in patterns
    ), "Should block @codingStandardsIgnoreFile (deprecated)"
