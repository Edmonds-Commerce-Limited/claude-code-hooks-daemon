"""Tests for RustSecurityStrategy."""

import re

import pytest

from claude_code_hooks_daemon.strategies.security.rust_strategy import (
    RustSecurityStrategy,
)


class TestRustSecurityStrategy:
    """Test suite for RustSecurityStrategy."""

    @pytest.fixture
    def strategy(self):
        return RustSecurityStrategy()

    # ── Properties ────────────────────────────────────────────────────

    def test_language_name(self, strategy):
        assert strategy.language_name == "Rust"

    def test_extensions(self, strategy):
        assert strategy.extensions == (".rs",)

    def test_patterns_not_empty(self, strategy):
        assert len(strategy.patterns) > 0

    def test_all_patterns_have_a03_owasp(self, strategy):
        for pattern in strategy.patterns:
            assert pattern.owasp == "A03"

    # ── Pattern Matching ──────────────────────────────────────────────

    def test_matches_from_raw_parts(self, strategy):
        content = "let slice = std::slice::from_raw_parts(ptr, len);"
        matched = any(re.search(p.regex, content) for p in strategy.patterns)
        assert matched is True

    def test_matches_transmute(self, strategy):
        content = "let x: u32 = std::mem::transmute(y);"
        matched = any(re.search(p.regex, content) for p in strategy.patterns)
        assert matched is True

    def test_no_match_clean_rust(self, strategy):
        content = 'println!("Hello, World!");'
        matched = any(re.search(p.regex, content) for p in strategy.patterns)
        assert matched is False

    def test_no_match_process_command(self, strategy):
        content = 'let output = std::process::Command::new("ls").output()?;'
        matched = any(re.search(p.regex, content) for p in strategy.patterns)
        assert matched is False

    # ── Acceptance Tests ──────────────────────────────────────────────

    def test_acceptance_tests_not_empty(self, strategy):
        tests = strategy.get_acceptance_tests()
        assert len(tests) > 0
