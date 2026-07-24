"""Tests for core.worktree_naming (Plan 00188).

The daemon owns WorktreeCreate and gives each worktree a human-friendly
semantic directory name — a slug derived from the Claude Code ``name`` field
plus a short stable hash suffix for uniqueness. These are pure functions so the
naming policy is independently TDD-able, separate from the git side effects in
the handler.
"""

from __future__ import annotations

from pathlib import Path

from claude_code_hooks_daemon.core.worktree_naming import (
    HASH_SUFFIX_LENGTH,
    WORKTREES_SUBDIR,
    slugify,
    worktree_dir_name,
    worktree_path,
)


class TestSlugify:
    def test_lowercases_and_hyphenates(self) -> None:
        assert slugify("Refactor Auth Layer") == "refactor-auth-layer"

    def test_collapses_non_alnum_runs_to_single_hyphen(self) -> None:
        assert slugify("feat/foo__bar  baz!!!") == "feat-foo-bar-baz"

    def test_strips_leading_and_trailing_separators(self) -> None:
        assert slugify("--hello--") == "hello"

    def test_empty_input_falls_back(self) -> None:
        assert slugify("") == "worktree"

    def test_all_punctuation_falls_back(self) -> None:
        assert slugify("///___") == "worktree"

    def test_caps_length(self) -> None:
        result = slugify("x" * 200)
        assert len(result) <= 40
        # Cap must not leave a trailing hyphen
        assert not result.endswith("-")

    def test_preserves_existing_agent_name(self) -> None:
        assert slugify("agent-a780b14327056ac9b") == "agent-a780b14327056ac9b"


class TestWorktreeDirName:
    def test_prefix_is_slug_suffix_is_hash(self) -> None:
        name = worktree_dir_name("Refactor Auth", "pid-123", "sid-456")
        prefix, _, suffix = name.rpartition("-")
        assert prefix == "refactor-auth"
        assert len(suffix) == HASH_SUFFIX_LENGTH
        assert all(c in "0123456789abcdef" for c in suffix)

    def test_is_deterministic(self) -> None:
        a = worktree_dir_name("foo", "pid", "sid")
        b = worktree_dir_name("foo", "pid", "sid")
        assert a == b

    def test_distinct_prompt_ids_give_distinct_suffixes(self) -> None:
        a = worktree_dir_name("foo", "pid-A", "sid")
        b = worktree_dir_name("foo", "pid-B", "sid")
        assert a != b

    def test_same_name_different_agents_do_not_collide(self) -> None:
        # Two agents both named "refactor-auth" must get different worktrees.
        a = worktree_dir_name("refactor-auth", "pid-A", "sid-A")
        b = worktree_dir_name("refactor-auth", "pid-B", "sid-B")
        assert a != b

    def test_none_name_uses_fallback_slug(self) -> None:
        name = worktree_dir_name(None, "pid", "sid")
        assert name.startswith("worktree-")

    def test_never_contains_template_braces(self) -> None:
        # The original bug was an unexpanded "{}"; guard against any brace.
        name = worktree_dir_name("weird {name}", "pid", "sid")
        assert "{" not in name and "}" not in name


class TestWorktreePath:
    def test_path_is_under_worktrees_subdir_of_cwd(self) -> None:
        path = worktree_path("/workspace", "Refactor Auth", "pid", "sid")
        assert isinstance(path, Path)
        assert str(path).startswith(f"/workspace/{WORKTREES_SUBDIR}/")
        assert path.name.startswith("refactor-auth-")

    def test_path_is_absolute(self) -> None:
        path = worktree_path("/workspace", "foo", "pid", "sid")
        assert path.is_absolute()

    def test_no_braces_in_path(self) -> None:
        path = worktree_path("/workspace", "{}", "pid", "sid")
        assert "{" not in str(path) and "}" not in str(path)
