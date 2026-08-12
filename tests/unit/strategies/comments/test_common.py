"""Tests for shared comment-strategy defaults."""

from claude_code_hooks_daemon.strategies.comments.common import (
    DEFAULT_SKIP_DIRECTORIES,
)


class TestDefaultSkipDirectories:
    def test_is_nonempty_tuple_of_strings(self) -> None:
        assert isinstance(DEFAULT_SKIP_DIRECTORIES, tuple)
        assert len(DEFAULT_SKIP_DIRECTORIES) > 0
        assert all(isinstance(entry, str) for entry in DEFAULT_SKIP_DIRECTORIES)

    def test_includes_common_vendor_and_build_dirs(self) -> None:
        assert "vendor/" in DEFAULT_SKIP_DIRECTORIES
        assert "node_modules/" in DEFAULT_SKIP_DIRECTORIES
        assert "tests/fixtures/" in DEFAULT_SKIP_DIRECTORIES
