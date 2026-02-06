"""Tests for LanguageConfig dataclass and language registry."""

import pytest

from claude_code_hooks_daemon.core.language_config import (
    GO_CONFIG,
    PHP_CONFIG,
    PYTHON_CONFIG,
    LanguageConfig,
    get_language_config,
)


class TestLanguageConfig:
    """Test LanguageConfig dataclass."""

    def test_language_config_is_frozen(self) -> None:
        """LanguageConfig instances should be immutable."""
        config = LanguageConfig(
            name="test",
            extensions=(".test",),
            qa_forbidden_patterns=(),
            test_file_pattern="test_{filename}",
            qa_tool_names=(),
            qa_tool_docs_urls=(),
            skip_directories=(),
        )

        # Frozen dataclass should raise when trying to modify
        with pytest.raises(AttributeError):
            config.name = "modified"

    def test_language_config_requires_all_fields(self) -> None:
        """LanguageConfig should require all fields."""
        with pytest.raises(TypeError):
            LanguageConfig()

    def test_python_config_has_correct_extensions(self) -> None:
        """Python config should recognize .py files."""
        assert PYTHON_CONFIG.extensions == (".py",)
        assert PYTHON_CONFIG.name == "Python"

    def test_python_config_has_qa_patterns(self) -> None:
        """Python config should have QA suppression patterns."""
        patterns = PYTHON_CONFIG.qa_forbidden_patterns
        assert len(patterns) > 0
        # Should include common Python QA suppressions
        assert any("type:" in p for p in patterns)
        assert any("noqa" in p for p in patterns)

    def test_go_config_has_correct_extensions(self) -> None:
        """Go config should recognize .go files."""
        assert GO_CONFIG.extensions == (".go",)
        assert GO_CONFIG.name == "Go"

    def test_go_config_has_qa_patterns(self) -> None:
        """Go config should have QA suppression patterns."""
        patterns = GO_CONFIG.qa_forbidden_patterns
        assert len(patterns) > 0
        assert any("nolint" in p for p in patterns)

    def test_php_config_has_correct_extensions(self) -> None:
        """PHP config should recognize .php files."""
        assert PHP_CONFIG.extensions == (".php",)
        assert PHP_CONFIG.name == "PHP"

    def test_php_config_has_qa_patterns(self) -> None:
        """PHP config should have QA suppression patterns."""
        patterns = PHP_CONFIG.qa_forbidden_patterns
        assert len(patterns) > 0
        assert any("phpstan" in p for p in patterns)

    def test_python_config_has_test_file_pattern(self) -> None:
        """Python config should define test file naming convention."""
        assert PYTHON_CONFIG.test_file_pattern == "test_{filename}"

    def test_go_config_has_test_file_pattern(self) -> None:
        """Go config should define test file naming convention."""
        assert GO_CONFIG.test_file_pattern == "{basename}_test.go"

    def test_php_config_has_test_file_pattern(self) -> None:
        """PHP config should define test file naming convention."""
        assert PHP_CONFIG.test_file_pattern == "{basename}Test.php"

    def test_get_language_config_python(self) -> None:
        """get_language_config should return Python config for .py files."""
        config = get_language_config("/path/to/file.py")
        assert config is PYTHON_CONFIG

    def test_get_language_config_go(self) -> None:
        """get_language_config should return Go config for .go files."""
        config = get_language_config("/path/to/file.go")
        assert config is GO_CONFIG

    def test_get_language_config_php(self) -> None:
        """get_language_config should return PHP config for .php files."""
        config = get_language_config("/path/to/file.php")
        assert config is PHP_CONFIG

    def test_get_language_config_case_insensitive(self) -> None:
        """get_language_config should be case-insensitive."""
        assert get_language_config("/path/to/FILE.PY") is PYTHON_CONFIG
        assert get_language_config("/path/to/FILE.GO") is GO_CONFIG
        assert get_language_config("/path/to/FILE.PHP") is PHP_CONFIG

    def test_get_language_config_unknown_extension(self) -> None:
        """get_language_config should return None for unknown extensions."""
        config = get_language_config("/path/to/file.unknown")
        assert config is None

    def test_get_language_config_no_extension(self) -> None:
        """get_language_config should return None for files without extension."""
        config = get_language_config("/path/to/file")
        assert config is None

    def test_python_config_has_skip_directories(self) -> None:
        """Python config should define directories to skip."""
        skip_dirs = PYTHON_CONFIG.skip_directories
        assert "vendor/" in skip_dirs
        assert "venv/" in skip_dirs
        assert ".venv/" in skip_dirs

    def test_go_config_has_skip_directories(self) -> None:
        """Go config should define directories to skip."""
        skip_dirs = GO_CONFIG.skip_directories
        assert "vendor/" in skip_dirs
        assert "testdata/" in skip_dirs

    def test_php_config_has_skip_directories(self) -> None:
        """PHP config should define directories to skip."""
        skip_dirs = PHP_CONFIG.skip_directories
        assert "vendor/" in skip_dirs
        assert "tests/fixtures/" in skip_dirs
