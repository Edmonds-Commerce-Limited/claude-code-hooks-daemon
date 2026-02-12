"""Tests for Lint Strategy common utilities."""

import pytest

from claude_code_hooks_daemon.strategies.lint.common import (
    COMMON_SKIP_PATHS,
    matches_skip_path,
)


class TestCommonSkipPaths:
    def test_common_skip_paths_is_tuple(self) -> None:
        assert isinstance(COMMON_SKIP_PATHS, tuple)

    def test_common_skip_paths_contains_node_modules(self) -> None:
        assert "node_modules/" in COMMON_SKIP_PATHS

    def test_common_skip_paths_contains_dist(self) -> None:
        assert "dist/" in COMMON_SKIP_PATHS

    def test_common_skip_paths_contains_vendor(self) -> None:
        assert "vendor/" in COMMON_SKIP_PATHS

    def test_common_skip_paths_contains_build(self) -> None:
        assert ".build/" in COMMON_SKIP_PATHS

    def test_common_skip_paths_contains_coverage(self) -> None:
        assert "coverage/" in COMMON_SKIP_PATHS

    def test_common_skip_paths_contains_venv(self) -> None:
        assert ".venv/" in COMMON_SKIP_PATHS

    def test_common_skip_paths_contains_venv_no_dot(self) -> None:
        assert "venv/" in COMMON_SKIP_PATHS


class TestMatchesSkipPath:
    def test_matches_node_modules(self) -> None:
        assert matches_skip_path("/workspace/node_modules/pkg/index.js", COMMON_SKIP_PATHS) is True

    def test_matches_dist(self) -> None:
        assert matches_skip_path("/workspace/dist/bundle.js", COMMON_SKIP_PATHS) is True

    def test_matches_vendor(self) -> None:
        assert matches_skip_path("/workspace/vendor/lib/foo.rb", COMMON_SKIP_PATHS) is True

    def test_does_not_match_src(self) -> None:
        assert matches_skip_path("/workspace/src/app/main.py", COMMON_SKIP_PATHS) is False

    def test_does_not_match_lib(self) -> None:
        assert matches_skip_path("/workspace/lib/helper.rb", COMMON_SKIP_PATHS) is False

    def test_matches_custom_skip_paths(self) -> None:
        custom = ("custom_skip/",)
        assert matches_skip_path("/workspace/custom_skip/foo.py", custom) is True

    def test_does_not_match_custom_skip_paths(self) -> None:
        custom = ("custom_skip/",)
        assert matches_skip_path("/workspace/src/foo.py", custom) is False

    def test_empty_skip_paths(self) -> None:
        assert matches_skip_path("/workspace/anything/foo.py", ()) is False

    def test_matches_venv(self) -> None:
        assert matches_skip_path("/workspace/.venv/lib/python3.12/site.py", COMMON_SKIP_PATHS) is True
