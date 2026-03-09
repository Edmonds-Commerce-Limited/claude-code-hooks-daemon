"""Tests for security strategy common utilities."""

from claude_code_hooks_daemon.strategies.security.common import (
    SKIP_PATTERNS,
    UNIVERSAL_EXTENSION,
    should_skip,
)


class TestShouldSkip:
    """Test should_skip() function."""

    def test_skips_vendor_directory(self):
        assert should_skip("/workspace/vendor/lib/auth.php") is True

    def test_skips_node_modules(self):
        assert should_skip("/workspace/node_modules/pkg/index.js") is True

    def test_skips_test_fixtures(self):
        assert should_skip("/workspace/tests/fixtures/payload.php") is True

    def test_skips_test_assets(self):
        assert should_skip("/workspace/tests/assets/payload.js") is True

    def test_skips_env_example(self):
        assert should_skip("/workspace/.env.example") is True

    def test_skips_docs(self):
        assert should_skip("/workspace/docs/security.md") is True

    def test_skips_claude_dir(self):
        assert should_skip("/workspace/CLAUDE/notes.md") is True

    def test_skips_eslint_rules(self):
        assert should_skip("/workspace/eslint-rules/no-eval.js") is True

    def test_skips_phpstan_rules(self):
        assert should_skip("/workspace/tests/PHPStan/rules/test.php") is True

    def test_allows_source_file(self):
        assert should_skip("/workspace/src/config.ts") is False

    def test_allows_root_file(self):
        assert should_skip("/workspace/app.php") is False


class TestConstants:
    """Test module-level constants."""

    def test_skip_patterns_is_tuple(self):
        assert isinstance(SKIP_PATTERNS, tuple)

    def test_skip_patterns_not_empty(self):
        assert len(SKIP_PATTERNS) > 0

    def test_universal_extension_is_star(self):
        assert UNIVERSAL_EXTENSION == "*"
