"""Tests for the shared glob-based path-exclusion utility.

Handlers use it to let a client project exempt paths (test fixtures of
deliberately-broken code, code that legitimately suppresses errors) via
gitignore-style globs. The set of handlers is deliberately NOT enumerated
here: an earlier revision of this docstring stated a specific count, and it
went stale the next time a handler adopted `handler_excludes_path` without
this file being updated in the same change (an R5 violation in miniature —
Plan 00288 DESIGN §1c). `handler_excludes_path` is the single entry point
they share, so grep for its callers rather than trusting a number in prose.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from claude_code_hooks_daemon.utils.path_exclusion import (
    handler_excludes_path,
    is_path_excluded,
    merge_exclude_patterns,
    path_matches_globs,
    resolve_project_root,
)


class TestPathMatchesGlobs:
    """`path_matches_globs` is the matcher; exclusion is one USE of the answer.

    `tdd_enforcement`'s `test_path_map` matches globs in order to treat paths
    SPECIALLY rather than to skip them (Plan 00251), so the matcher is public
    under a name that describes what it computes. These tests pin that the two
    names are the same behaviour, so a future change to one cannot silently
    diverge from the other.
    """

    @pytest.mark.parametrize(
        ("file_path", "patterns", "expected"),
        [
            pytest.param("a/qaConfig/PHPStan/Rules/F.php", ["**/qaConfig/**"], True, id="deep"),
            pytest.param("a/src/F.php", ["**/qaConfig/**"], False, id="no-match"),
            pytest.param("a/b.py", None, False, id="none-patterns"),
            pytest.param("a/b.py", [], False, id="empty-patterns"),
            pytest.param("a/b.py", ["", "a/*.py"], True, id="empty-pattern-skipped"),
        ],
    )
    def test_matching(self, file_path: str, patterns: list[str] | None, expected: bool) -> None:
        assert path_matches_globs(file_path, patterns) is expected

    def test_is_path_excluded_is_the_same_behaviour(self) -> None:
        """The alias must not drift: same inputs, same answer, both directions."""
        cases: list[tuple[str, list[str]]] = [
            ("a/qaConfig/x.php", ["**/qaConfig/**"]),
            ("a/src/x.php", ["**/qaConfig/**"]),
            ("proj/vendor/x.py", ["/vendor/**"]),
        ]
        for file_path, patterns in cases:
            assert path_matches_globs(file_path, patterns, project_root="proj") is is_path_excluded(
                file_path, patterns, project_root="proj"
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


class TestHandlerExcludesPath:
    """One definition of the handler-facing exclusion decision (Plan 00251).

    `_is_excluded` was copy-pasted into several handlers — byte-identical in
    most of them, with `error_hiding_blocker` differing only by prepending
    its own defaults and dropping a short-circuit. `handler_excludes_path`
    exists to be CALLED by every consumer rather than pasted into each one;
    grep its callers for the current count rather than trusting a number
    here (see this file's module docstring).
    """

    def test_a_handler_pattern_excludes(self) -> None:
        assert handler_excludes_path(
            "/proj/generated/x.py", handler_patterns=["**/generated/**"], project_patterns=None
        )

    def test_a_project_pattern_excludes(self) -> None:
        """`daemon.exclude_paths` must apply even when the handler configures none."""
        assert handler_excludes_path(
            "/proj/vendored/x.py", handler_patterns=None, project_patterns=["**/vendored/**"]
        )

    def test_defaults_exclude(self) -> None:
        """The `error_hiding_blocker` shape: built-in defaults, no user config."""
        assert handler_excludes_path(
            "/proj/node_modules/x.js",
            handler_patterns=None,
            project_patterns=None,
            defaults=["**/node_modules/**"],
        )

    def test_the_three_sources_are_additive_not_overriding(self) -> None:
        """None of the three sources may mask another — all must still match."""
        kwargs = {
            "handler_patterns": ["**/h/**"],
            "project_patterns": ["**/p/**"],
            "defaults": ["**/d/**"],
        }
        assert handler_excludes_path("/proj/h/x.py", **kwargs)
        assert handler_excludes_path("/proj/p/x.py", **kwargs)
        assert handler_excludes_path("/proj/d/x.py", **kwargs)

    def test_no_patterns_anywhere_never_excludes(self) -> None:
        assert not handler_excludes_path(
            "/proj/src/x.py", handler_patterns=None, project_patterns=None
        )

    def test_a_non_matching_path_is_not_excluded(self) -> None:
        assert not handler_excludes_path(
            "/proj/src/x.py", handler_patterns=["**/generated/**"], project_patterns=None
        )

    def test_empty_lists_behave_as_none(self) -> None:
        """A handler whose option is set to `[]` must not be treated as configured."""
        assert not handler_excludes_path(
            "/proj/src/x.py", handler_patterns=[], project_patterns=[], defaults=[]
        )
