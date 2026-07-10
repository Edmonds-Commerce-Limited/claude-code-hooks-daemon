"""Tests for the shared glob-based path-exclusion utility.

The three content-scanning blocking handlers (security_antipattern,
qa_suppression, error_hiding_blocker) use is_path_excluded() to let a client
project exempt paths (test fixtures of deliberately-broken code, code that
legitimately suppresses errors) via gitignore-style globs.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from claude_code_hooks_daemon.utils.path_exclusion import (
    is_path_excluded,
    merge_exclude_patterns,
    resolve_project_root,
)


class TestMergeExcludePatterns:
    def test_none_and_empty_groups_yield_empty(self) -> None:
        assert merge_exclude_patterns(None, [], None) == []

    def test_union_preserves_first_seen_order(self) -> None:
        assert merge_exclude_patterns(["a/**", "b/**"], ["c/**"]) == ["a/**", "b/**", "c/**"]

    def test_duplicates_are_removed(self) -> None:
        assert merge_exclude_patterns(["a/**"], ["a/**", "b/**"]) == ["a/**", "b/**"]

    def test_empty_pattern_strings_skipped(self) -> None:
        assert merge_exclude_patterns(["a/**", ""], [""]) == ["a/**"]


class TestEmptyAndNoMatch:
    def test_no_patterns_never_excludes(self) -> None:
        assert is_path_excluded("/proj/src/main.py", []) is False

    def test_none_patterns_never_excludes(self) -> None:
        assert is_path_excluded("/proj/src/main.py", None) is False

    def test_unrelated_pattern_does_not_match(self) -> None:
        assert is_path_excluded("/proj/src/main.py", ["tests/fixtures/**"]) is False


class TestDirectoryGlobs:
    def test_dir_glob_matches_absolute_path(self) -> None:
        assert is_path_excluded("/proj/tests/fixtures/bad.py", ["tests/fixtures/**"]) is True

    def test_dir_glob_matches_relative_path(self) -> None:
        assert is_path_excluded("tests/fixtures/bad.py", ["tests/fixtures/**"]) is True

    def test_dir_glob_matches_nested_file(self) -> None:
        assert is_path_excluded("/proj/tests/fixtures/a/b/bad.py", ["tests/fixtures/**"]) is True

    def test_dir_glob_does_not_match_sibling(self) -> None:
        assert is_path_excluded("/proj/tests/unit/ok.py", ["tests/fixtures/**"]) is False


class TestDoubleStarSemantics:
    def test_leading_globstar_matches_any_depth(self) -> None:
        assert is_path_excluded("/proj/src/pkg/fixtures/x.py", ["**/fixtures/**"]) is True

    def test_leading_globstar_matches_at_root(self) -> None:
        assert is_path_excluded("fixtures/x.py", ["**/fixtures/**"]) is True

    def test_middle_globstar_matches_zero_dirs(self) -> None:
        # gitignore semantics: a/**/b matches a/b (zero intermediate dirs).
        assert is_path_excluded("samples/x.py", ["samples/**/*.py"]) is True

    def test_middle_globstar_matches_many_dirs(self) -> None:
        assert is_path_excluded("samples/a/b/x.py", ["samples/**/*.py"]) is True

    def test_middle_globstar_respects_extension(self) -> None:
        assert is_path_excluded("samples/a/x.txt", ["samples/**/*.py"]) is False


class TestSingleStarAndQuestion:
    def test_single_star_does_not_cross_directory(self) -> None:
        # '*' matches within a single segment only.
        assert is_path_excluded("a/b/c.py", ["a/*.py"]) is False

    def test_single_star_matches_within_segment(self) -> None:
        assert is_path_excluded("a/c.py", ["a/*.py"]) is True

    def test_bare_extension_glob_matches_any_depth(self) -> None:
        assert is_path_excluded("/proj/deep/nested/thing.py", ["*.py"]) is True

    def test_question_mark_matches_single_char(self) -> None:
        assert is_path_excluded("v1.py", ["v?.py"]) is True

    def test_question_mark_does_not_match_two_chars(self) -> None:
        assert is_path_excluded("v12.py", ["v?.py"]) is False


class TestAnchoredPatterns:
    def test_leading_slash_anchors_to_project_root(self) -> None:
        assert (
            is_path_excluded(
                "/proj/tests/fixtures/x.py",
                ["/tests/fixtures/**"],
                project_root="/proj",
            )
            is True
        )

    def test_leading_slash_does_not_match_nested_same_name(self) -> None:
        # Anchored: must be at the project root, not a nested tests/fixtures.
        assert (
            is_path_excluded(
                "/proj/src/tests/fixtures/x.py",
                ["/tests/fixtures/**"],
                project_root="/proj",
            )
            is False
        )


class TestProjectRootRelative:
    def test_relative_resolution_under_root(self) -> None:
        assert (
            is_path_excluded(
                "/proj/pkg/fixtures/x.py",
                ["pkg/fixtures/**"],
                project_root="/proj",
            )
            is True
        )

    def test_path_outside_root_still_matched_by_unanchored(self) -> None:
        # File not under project_root: fall back to matching the raw path.
        assert is_path_excluded("/other/tests/fixtures/x.py", ["tests/fixtures/**"]) is True


class TestMultiplePatterns:
    def test_any_pattern_matches(self) -> None:
        patterns = ["vendor/**", "**/fixtures/**", "samples/**/*.py"]
        assert is_path_excluded("/proj/a/fixtures/b.py", patterns) is True

    def test_no_pattern_matches(self) -> None:
        patterns = ["vendor/**", "**/fixtures/**"]
        assert is_path_excluded("/proj/src/app/main.py", patterns) is False


class TestResolveProjectRoot:
    def test_returns_none_when_context_uninitialised(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from claude_code_hooks_daemon.core import project_context as pc

        monkeypatch.setattr(pc.ProjectContext, "_initialized", False, raising=False)
        assert resolve_project_root() is None

    def test_returns_root_when_initialised(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from claude_code_hooks_daemon.core import project_context as pc

        monkeypatch.setattr(pc.ProjectContext, "_initialized", True, raising=False)
        monkeypatch.setattr(
            pc.ProjectContext, "project_root", classmethod(lambda cls: Path("/proj")), raising=False
        )
        assert resolve_project_root() == "/proj"
