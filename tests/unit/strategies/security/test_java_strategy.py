"""Tests for JavaSecurityStrategy."""

import re

import pytest

from claude_code_hooks_daemon.strategies.security.java_strategy import (
    JavaSecurityStrategy,
)


class TestJavaSecurityStrategy:
    """Test suite for JavaSecurityStrategy."""

    @pytest.fixture
    def strategy(self):
        return JavaSecurityStrategy()

    # ── Properties ────────────────────────────────────────────────────

    def test_language_name(self, strategy):
        assert strategy.language_name == "Java"

    def test_extensions(self, strategy):
        assert strategy.extensions == (".java",)

    def test_patterns_not_empty(self, strategy):
        assert len(strategy.patterns) > 0

    def test_all_patterns_have_a03_owasp(self, strategy):
        for pattern in strategy.patterns:
            assert pattern.owasp == "A03"

    # ── Pattern Matching ──────────────────────────────────────────────

    def test_matches_runtime_exec(self, strategy):
        content = 'Runtime.getRuntime().exec("ls -la");'
        matched = any(re.search(p.regex, content) for p in strategy.patterns)
        assert matched is True

    def test_matches_object_input_stream(self, strategy):
        content = "ObjectInputStream ois = new ObjectInputStream(socket.getInputStream());"
        matched = any(re.search(p.regex, content) for p in strategy.patterns)
        assert matched is True

    def test_matches_xml_decoder(self, strategy):
        content = "XMLDecoder decoder = new XMLDecoder(inputStream);"
        matched = any(re.search(p.regex, content) for p in strategy.patterns)
        assert matched is True

    def test_matches_script_engine_manager(self, strategy):
        content = "ScriptEngineManager manager = new ScriptEngineManager();"
        matched = any(re.search(p.regex, content) for p in strategy.patterns)
        assert matched is True

    def test_no_match_clean_java(self, strategy):
        content = 'System.out.println("Hello World");'
        matched = any(re.search(p.regex, content) for p in strategy.patterns)
        assert matched is False

    def test_no_match_process_builder(self, strategy):
        content = 'new ProcessBuilder("git", "status").start();'
        matched = any(re.search(p.regex, content) for p in strategy.patterns)
        assert matched is False

    # ── Acceptance Tests ──────────────────────────────────────────────

    def test_acceptance_tests_not_empty(self, strategy):
        tests = strategy.get_acceptance_tests()
        assert len(tests) > 0
