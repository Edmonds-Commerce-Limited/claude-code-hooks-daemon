"""Tests for TDD common utilities."""

from claude_code_hooks_daemon.strategies.tdd.common import (
    COMMON_TEST_DIRECTORIES,
    is_in_common_test_directory,
    matches_directory,
)


def test_common_test_directories_is_tuple() -> None:
    """COMMON_TEST_DIRECTORIES should be a tuple."""
    assert isinstance(COMMON_TEST_DIRECTORIES, tuple)


def test_common_test_directories_has_expected_entries() -> None:
    """COMMON_TEST_DIRECTORIES should contain expected test directory patterns."""
    assert "/tests/" in COMMON_TEST_DIRECTORIES
    assert "/test/" in COMMON_TEST_DIRECTORIES
    assert "/__tests__/" in COMMON_TEST_DIRECTORIES
    assert "/spec/" in COMMON_TEST_DIRECTORIES


def test_is_in_common_test_directory_positive_cases() -> None:
    """Files in common test directories should return True."""
    assert is_in_common_test_directory("/workspace/tests/unit/test_file.py") is True
    assert is_in_common_test_directory("/workspace/test/helpers.go") is True
    assert is_in_common_test_directory("/app/__tests__/Component.test.tsx") is True
    assert is_in_common_test_directory("/project/spec/model_spec.rb") is True


def test_is_in_common_test_directory_negative_cases() -> None:
    """Files NOT in common test directories should return False."""
    assert is_in_common_test_directory("/workspace/src/module.py") is False
    assert is_in_common_test_directory("/workspace/lib/helper.js") is False
    assert is_in_common_test_directory("/workspace/app/controller.php") is False


def test_matches_directory_with_leading_slash() -> None:
    """Directory patterns with leading slash should match."""
    directories = ("/vendor/", "/node_modules/")
    assert matches_directory("/workspace/vendor/package/file.php", directories) is True
    assert matches_directory("/app/node_modules/lib/index.js", directories) is True
    assert matches_directory("/workspace/src/file.py", directories) is False


def test_matches_directory_without_leading_slash() -> None:
    """Directory patterns without leading slash should be normalized and match."""
    directories = ("vendor/", "node_modules/")
    assert matches_directory("/workspace/vendor/package/file.php", directories) is True
    assert matches_directory("/app/node_modules/lib/index.js", directories) is True


def test_matches_directory_without_trailing_slash() -> None:
    """Directory patterns without trailing slash should be normalized and match."""
    directories = ("/vendor", "/node_modules")
    assert matches_directory("/workspace/vendor/package/file.php", directories) is True
    assert matches_directory("/app/node_modules/lib/index.js", directories) is True


def test_matches_directory_no_patterns() -> None:
    """Empty directory tuple should return False for all paths."""
    directories: tuple[str, ...] = ()
    assert matches_directory("/workspace/src/file.py", directories) is False
    assert matches_directory("/workspace/vendor/file.php", directories) is False


def test_matches_directory_complex_patterns() -> None:
    """Complex nested directory patterns should match correctly."""
    directories = ("/tests/fixtures/", "/.venv/", "/migrations/")
    assert matches_directory("/workspace/tests/fixtures/data.json", directories) is True
    assert (
        matches_directory("/project/.venv/lib/python/site-packages/module.py", directories) is True
    )
    assert matches_directory("/app/migrations/001_initial.sql", directories) is True
    assert matches_directory("/workspace/tests/unit/test_file.py", directories) is False
