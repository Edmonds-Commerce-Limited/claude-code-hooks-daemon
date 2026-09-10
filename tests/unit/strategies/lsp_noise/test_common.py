"""Tests for lsp_noise strategy shared utilities."""

from pathlib import Path

from claude_code_hooks_daemon.strategies.lsp_noise.common import (
    entry_covers,
    json_list,
    strip_jsonc_comments,
    tree_contains_extension,
)


class TestEntryCovers:
    def test_exact_match_covers(self) -> None:
        assert entry_covers("untracked", "untracked") is True

    def test_trailing_slash_is_ignored(self) -> None:
        assert entry_covers("untracked/", "untracked") is True
        assert entry_covers("untracked", "untracked/") is True

    def test_parent_directory_covers_a_child(self) -> None:
        assert entry_covers("CLAUDE/", "CLAUDE/Plan") is True

    def test_unrelated_entry_does_not_cover(self) -> None:
        assert entry_covers("remote-docs", "CLAUDE/Plan") is False

    def test_bare_name_covers_its_any_depth_glob(self) -> None:
        assert entry_covers("venv", "**/venv") is True

    def test_any_depth_glob_covers_its_bare_name(self) -> None:
        assert entry_covers("**/venv", "venv") is True

    def test_empty_strings_never_cover(self) -> None:
        assert entry_covers("", "venv") is False
        assert entry_covers("venv", "") is False


class TestJsonList:
    def test_renders_one_quoted_entry_per_line(self) -> None:
        assert json_list(["a", "b"]) == ['  "a",', '  "b",']

    def test_empty_list_renders_nothing(self) -> None:
        assert json_list([]) == []


class TestStripJsoncComments:
    def test_strips_line_comments(self) -> None:
        text = '{\n  "exclude": ["a"] // trailing comment\n}'
        stripped = strip_jsonc_comments(text)
        assert "// trailing comment" not in stripped
        assert '"exclude": ["a"]' in stripped

    def test_strips_block_comments(self) -> None:
        text = '{\n  /* block */\n  "exclude": ["a"]\n}'
        stripped = strip_jsonc_comments(text)
        assert "/* block */" not in stripped
        assert '"exclude": ["a"]' in stripped

    def test_does_not_strip_slashes_inside_strings(self) -> None:
        text = '{"exclude": ["a//b"]}'
        assert strip_jsonc_comments(text) == text

    def test_respects_escaped_quotes_inside_strings(self) -> None:
        text = '{"path": "a\\"//not a comment"}'
        stripped = strip_jsonc_comments(text)
        assert "//not a comment" in stripped


class TestTreeContainsExtension:
    def test_missing_tree_reports_false(self, tmp_path: Path) -> None:
        assert tree_contains_extension(tmp_path, "nope", ".go", prune_names=frozenset()) is False

    def test_finds_a_matching_file(self, tmp_path: Path) -> None:
        target = tmp_path / "untracked" / "sub"
        target.mkdir(parents=True)
        (target / "main.go").write_text("package main\n", encoding="utf-8")
        assert (
            tree_contains_extension(tmp_path, "untracked", ".go", prune_names=frozenset()) is True
        )

    def test_no_matching_file_reports_false(self, tmp_path: Path) -> None:
        target = tmp_path / "untracked"
        target.mkdir()
        (target / "README.md").write_text("x", encoding="utf-8")
        assert (
            tree_contains_extension(tmp_path, "untracked", ".go", prune_names=frozenset()) is False
        )

    def test_prunes_named_directories(self, tmp_path: Path) -> None:
        pruned = tmp_path / "untracked" / "vendor"
        pruned.mkdir(parents=True)
        (pruned / "lib.go").write_text("package lib\n", encoding="utf-8")
        assert (
            tree_contains_extension(tmp_path, "untracked", ".go", prune_names=frozenset({"vendor"}))
            is False
        )

    def test_a_bare_tree_that_is_itself_a_file_is_checked_directly(self, tmp_path: Path) -> None:
        (tmp_path / "main.go").write_text("package main\n", encoding="utf-8")
        assert tree_contains_extension(tmp_path, "main.go", ".go", prune_names=frozenset()) is True
