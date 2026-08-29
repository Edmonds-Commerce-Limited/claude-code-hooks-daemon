"""Tests for Lint Strategy common utilities."""

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

    def test_common_skip_paths_contains_next(self) -> None:
        # Plan 00288 Task 3.2: newly-accepted core delta.
        assert ".next/" in COMMON_SKIP_PATHS

    def test_common_skip_paths_contains_third_party(self) -> None:
        # Plan 00288 Task 3.2: newly-accepted core delta.
        assert "third_party/" in COMMON_SKIP_PATHS

    def test_common_skip_paths_keeps_pycache_and_git_as_domain_extras(self) -> None:
        # Not part of the core; lint keeps these two as its own extras
        # (measurement doc §3).
        assert "__pycache__/" in COMMON_SKIP_PATHS
        assert ".git/" in COMMON_SKIP_PATHS

    def test_common_skip_paths_has_exact_membership(self) -> None:
        assert set(COMMON_SKIP_PATHS) == {
            "node_modules/",
            "vendor/",
            "third_party/",
            "dist/",
            "build/",
            ".build/",
            "target/",
            ".next/",
            ".venv/",
            "venv/",
            "coverage/",
            "__pycache__/",
            ".git/",
        }


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
        assert (
            matches_skip_path("/workspace/.venv/lib/python3.12/site.py", COMMON_SKIP_PATHS) is True
        )
