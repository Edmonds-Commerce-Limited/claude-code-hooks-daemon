"""Tests for SecretDetectionStrategy."""

import re

import pytest

from claude_code_hooks_daemon.strategies.security.common import UNIVERSAL_EXTENSION
from claude_code_hooks_daemon.strategies.security.secret_strategy import (
    SecretDetectionStrategy,
)


class TestSecretDetectionStrategy:
    """Test suite for SecretDetectionStrategy."""

    @pytest.fixture
    def strategy(self):
        return SecretDetectionStrategy()

    # ── Properties ────────────────────────────────────────────────────

    def test_language_name(self, strategy):
        assert strategy.language_name == "Secrets"

    def test_extensions_is_universal(self, strategy):
        assert UNIVERSAL_EXTENSION in strategy.extensions

    def test_patterns_not_empty(self, strategy):
        assert len(strategy.patterns) > 0

    def test_all_patterns_have_a02_owasp(self, strategy):
        for pattern in strategy.patterns:
            assert pattern.owasp == "A02"

    # ── Pattern Matching ──────────────────────────────────────────────

    def test_matches_aws_access_key(self, strategy):
        content = 'const key = "AKIAIOSFODNN7EXAMPLE1";'
        matched = any(re.search(p.regex, content) for p in strategy.patterns)
        assert matched is True

    def test_matches_stripe_secret_key(self, strategy):
        content = 'const stripe = "sk_live_abcdefghijklmnopqrstuvwx";'
        matched = any(re.search(p.regex, content) for p in strategy.patterns)
        assert matched is True

    def test_matches_stripe_publishable_live_key(self, strategy):
        content = 'const pk = "pk_live_abcdefghijklmnopqrstuvwx";'
        matched = any(re.search(p.regex, content) for p in strategy.patterns)
        assert matched is True

    def test_matches_github_personal_token(self, strategy):
        content = 'const token = "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghij";'
        matched = any(re.search(p.regex, content) for p in strategy.patterns)
        assert matched is True

    def test_matches_github_oauth_token(self, strategy):
        content = 'const token = "gho_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghij";'
        matched = any(re.search(p.regex, content) for p in strategy.patterns)
        assert matched is True

    def test_matches_rsa_private_key(self, strategy):
        content = "-----BEGIN RSA PRIVATE KEY-----\nMIIEow..."
        matched = any(re.search(p.regex, content) for p in strategy.patterns)
        assert matched is True

    def test_matches_generic_private_key(self, strategy):
        content = "-----BEGIN PRIVATE KEY-----\nMIIEvg..."
        matched = any(re.search(p.regex, content) for p in strategy.patterns)
        assert matched is True

    def test_no_match_clean_content(self, strategy):
        content = "const greeting = 'Hello World';"
        matched = any(re.search(p.regex, content) for p in strategy.patterns)
        assert matched is False

    # ── Acceptance Tests ──────────────────────────────────────────────

    def test_acceptance_tests_not_empty(self, strategy):
        tests = strategy.get_acceptance_tests()
        assert len(tests) > 0

    def test_acceptance_tests_have_blocking_test(self, strategy):
        tests = strategy.get_acceptance_tests()
        blocking = [t for t in tests if t.test_type.value == "blocking"]
        assert len(blocking) > 0
