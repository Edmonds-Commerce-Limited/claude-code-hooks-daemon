"""Tests for Ruby QA suppression strategy."""

import re

from claude_code_hooks_daemon.strategies.qa_suppression.protocol import (
    QaSuppressionStrategy,
)
from claude_code_hooks_daemon.strategies.qa_suppression.ruby_strategy import (
    RubyQaSuppressionStrategy,
)


def _rubocop_disable_text() -> str:
    return "# rubocop" + ":disable"


def test_implements_protocol() -> None:
    """RubyQaSuppressionStrategy should implement protocol."""
    strategy = RubyQaSuppressionStrategy()
    assert isinstance(strategy, QaSuppressionStrategy)


def test_language_name() -> None:
    """Language name should be 'Ruby'."""
    strategy = RubyQaSuppressionStrategy()
    assert strategy.language_name == "Ruby"


def test_extensions() -> None:
    """Extensions should be ('.rb',)."""
    strategy = RubyQaSuppressionStrategy()
    assert strategy.extensions == (".rb",)


def test_forbidden_patterns_not_empty() -> None:
    """Should have forbidden patterns defined."""
    strategy = RubyQaSuppressionStrategy()
    assert len(strategy.forbidden_patterns) > 0


def test_forbidden_patterns_are_valid_regex() -> None:
    """All forbidden patterns should be valid regex."""
    strategy = RubyQaSuppressionStrategy()
    for pattern in strategy.forbidden_patterns:
        re.compile(pattern)


def test_matches_rubocop_disable() -> None:
    """Should match rubocop:disable comments."""
    strategy = RubyQaSuppressionStrategy()
    patterns = strategy.forbidden_patterns
    text = f"x = 1 {_rubocop_disable_text()} Style/FrozenStringLiteral"
    assert any(re.search(p, text, re.IGNORECASE) for p in patterns)


def test_skip_directories_not_empty() -> None:
    """Should have skip directories defined."""
    strategy = RubyQaSuppressionStrategy()
    assert len(strategy.skip_directories) > 0


def test_skip_directories_include_vendor() -> None:
    """Skip directories should include vendor/."""
    strategy = RubyQaSuppressionStrategy()
    assert "vendor/" in strategy.skip_directories


def test_tool_names_not_empty() -> None:
    """Should have tool names defined."""
    strategy = RubyQaSuppressionStrategy()
    assert len(strategy.tool_names) > 0


def test_tool_docs_urls_not_empty() -> None:
    """Should have tool docs URLs defined."""
    strategy = RubyQaSuppressionStrategy()
    assert len(strategy.tool_docs_urls) > 0


def test_skip_directories_do_not_match_system_tmp() -> None:
    """Skip directories must not match system /tmp/ paths.

    Bug: "tmp/" in skip_directories matches /tmp/ in absolute paths like
    /tmp/acceptance-test-qa-ruby/example.rb, causing the handler to
    incorrectly skip files in system temp directories.
    """
    strategy = RubyQaSuppressionStrategy()
    system_tmp_path = "/tmp/acceptance-test-qa-ruby/example.rb"
    # None of the skip directories should match a system /tmp/ path
    assert not any(skip_dir in system_tmp_path for skip_dir in strategy.skip_directories), (
        f"Skip directories {strategy.skip_directories} incorrectly match "
        f"system /tmp/ path: {system_tmp_path}"
    )


def test_skip_directories_match_project_relative_vendor() -> None:
    """Skip directories should still match project-relative vendor/ paths."""
    strategy = RubyQaSuppressionStrategy()
    vendor_path = "/home/user/project/vendor/bundle/gems/example.rb"
    assert any(skip_dir in vendor_path for skip_dir in strategy.skip_directories)


def test_acceptance_tests_provided() -> None:
    """Should provide at least one acceptance test."""
    strategy = RubyQaSuppressionStrategy()
    tests = strategy.get_acceptance_tests()
    assert len(tests) > 0
