"""A glob ending in ``/`` is judged as the directories it expands to (issue #204).

In the shell a trailing ``/`` makes a glob expand to directories only, so it can
never name a file at its own level. ``ls -d */`` in a project whose root holds a
protected file must be allowed, while a recursive reader of ``*/`` is judged
exactly as it is for the literal directory the glob expands to.
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from tests.indexed_project import index_project
from tests.load_scaling import scaled_seconds

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use import secret_file_guard as guard_module
from claude_code_hooks_daemon.handlers.pre_tool_use.secret_file_guard import (
    SecretFileGuardHandler,
)
from claude_code_hooks_daemon.utils import protected_file_index
from claude_code_hooks_daemon.utils.protected_file_index import IndexedFile, ProtectedFileIndex
from claude_code_hooks_daemon.utils.recursive_search import search_reads

# Assembled so this file never spells a protected name itself.
_SUFFIX = "sec" + "ret"
# Idle-host budget for one pathological glob match; atomic groups keep it near 0.2 ms.
_BACKTRACK_BUDGET_SECONDS = 0.1
_TOP_LEVEL = f"example.{_SUFFIX}"
_NESTED = f"dir/key.{_SUFFIX}"


def _make_project(tmp_path: Path, *relpaths: str) -> Path:
    root = tmp_path / "project"
    (root / "docs").mkdir(parents=True)
    (root / "docs" / "plain.txt").write_bytes(b"hello\n")
    for relpath in relpaths:
        (root / relpath).parent.mkdir(parents=True, exist_ok=True)
        (root / relpath).write_bytes(b"not-a-real-secret\n")
    return root


def _verdict(root: Path, command: str) -> Decision:
    hook_input: dict[str, Any] = {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": str(root),
    }
    handler = SecretFileGuardHandler()
    if not handler.matches(hook_input):
        return Decision.ALLOW
    return handler.handle(hook_input).decision


@pytest.fixture()
def top_level_only(tmp_path: Path) -> Iterator[Path]:
    """A project whose only protected file sits at its root."""
    root = _make_project(tmp_path, _TOP_LEVEL)
    protected_file_index.reset_index_cache()
    with patch.object(guard_module, "resolve_project_root", return_value=str(root)):
        index_project(root, SecretFileGuardHandler()._patterns())
        yield root
    protected_file_index.reset_index_cache()


@pytest.fixture()
def nested(tmp_path: Path) -> Iterator[Path]:
    """A project with a protected file at its root and another under ``dir``."""
    root = _make_project(tmp_path, _TOP_LEVEL, _NESTED)
    protected_file_index.reset_index_cache()
    with patch.object(guard_module, "resolve_project_root", return_value=str(root)):
        index_project(root, SecretFileGuardHandler()._patterns())
        yield root
    protected_file_index.reset_index_cache()


def _index(root: Path, *relpaths: str) -> ProtectedFileIndex:
    pattern = "*." + _SUFFIX + "*"
    files = tuple(IndexedFile(r, pattern, tracked=True, ignored=False) for r in relpaths)
    return ProtectedFileIndex(str(root), (pattern,), files)


class TestIndexLevel:
    def test_a_trailing_slash_glob_never_matches_a_file_at_its_own_level(
        self, top_level_only: Path
    ) -> None:
        index = _index(top_level_only, _TOP_LEVEL)
        assert index.glob_matches("*/", (str(top_level_only),)) is None
        assert index.glob_matches("*", (str(top_level_only),)) is not None

    def test_a_root_level_file_is_in_no_directory_a_trailing_slash_glob_names(
        self, tmp_path: Path
    ) -> None:
        index = _index(tmp_path, _TOP_LEVEL)
        assert index.directories_matching("*/", (str(tmp_path),)) == ()

    @pytest.mark.parametrize(
        "token", ["*/", "d*/", "d?r/", "[a-e]*/", "[!x]*/", "[^x]*/", "*/*/", "ROOT/*/"]
    )
    def test_the_ancestor_directories_of_a_protected_file_are_matched(
        self, tmp_path: Path, token: str
    ) -> None:
        index = _index(tmp_path, _NESTED)
        glob = token.replace("ROOT", str(tmp_path))
        found = index.directories_matching(glob, (str(tmp_path),))
        if token == "*/*/":
            assert found == ()
        else:
            assert found == (f"{tmp_path}/dir",)

    @pytest.mark.parametrize("token", ["[!d]*/", "[^d]*/", "x*/", "dir/*/"])
    def test_a_glob_that_names_no_ancestor_directory_matches_none(
        self, tmp_path: Path, token: str
    ) -> None:
        index = _index(tmp_path, _NESTED)
        assert index.directories_matching(token, (str(tmp_path),)) == ()

    def test_a_dot_directory_is_reached_only_by_a_glob_that_starts_with_a_dot(
        self, tmp_path: Path
    ) -> None:
        index = _index(tmp_path, f".hidden/key.{_SUFFIX}")
        assert index.directories_matching("*/", (str(tmp_path),)) == ()
        assert index.directories_matching(".*/", (str(tmp_path),)) == (f"{tmp_path}/.hidden",)
        assert index.directories_matching(".h*/", (str(tmp_path),)) == (f"{tmp_path}/.hidden",)

    def test_a_double_star_follows_the_default_expansion_flag(self, tmp_path: Path) -> None:
        index = _index(tmp_path, f"a/b/key.{_SUFFIX}")
        bases = (str(tmp_path),)
        spanning = index.directories_matching("**/", bases)
        # globstar also matches zero directories: the base itself.
        assert set(spanning) == {str(tmp_path), f"{tmp_path}/a", f"{tmp_path}/a/b"}
        one_level = index.directories_matching("**/", bases, default_expansion=True)
        assert one_level == (f"{tmp_path}/a",)

    def test_a_bracket_negation_with_a_caret_reads_like_the_shell(self, tmp_path: Path) -> None:
        index = _index(tmp_path, f"xa/key.{_SUFFIX}")
        assert index.directories_matching("[^x]*/", (str(tmp_path),)) == ()
        assert index.directories_matching("[!x]*/", (str(tmp_path),)) == ()
        assert index.directories_matching("[^y]*/", (str(tmp_path),)) == (f"{tmp_path}/xa",)

    @pytest.mark.parametrize(
        "token",
        ["[[:alpha:]]*/", "[[:lower:]]*/", "[[:alnum:]]*/", "[![:digit:]]*/", "[^[:upper:]]*/"],
    )
    def test_a_posix_class_is_translated_for_a_directory_glob(
        self, tmp_path: Path, token: str
    ) -> None:
        index = _index(tmp_path, _NESTED)
        assert index.directories_matching(token, (str(tmp_path),)) == (f"{tmp_path}/dir",)

    @pytest.mark.parametrize("token", ["[[:digit:]]*/", "[[:upper:]]*/", "[![:alpha:]]*/"])
    def test_a_posix_class_that_misses_the_directory_matches_none(
        self, tmp_path: Path, token: str
    ) -> None:
        index = _index(tmp_path, _NESTED)
        assert index.directories_matching(token, (str(tmp_path),)) == ()

    def test_a_posix_class_is_translated_for_a_file_glob_too(self, tmp_path: Path) -> None:
        index = _index(tmp_path, f"dir/key.{_SUFFIX}")
        assert index.glob_matches("dir/[[:alpha:]]*", (str(tmp_path),)) is not None
        assert index.glob_matches("dir/[[:digit:]]*", (str(tmp_path),)) is None

    @pytest.mark.parametrize(
        ("token", "expected"),
        [
            ("[z-a]*/", False),
            ("[a-]*/", False),
            ("d[*/", False),
            ("d[i]r/", True),
            ("[]d]*/", True),
            ("\\d*/", True),
            ("[\\d]*/", True),
            ("[[:bogus:]]*/", False),
            ("[[:punct:]d]*/", True),
            ("[a-c-e]*/", False),
            ("[[:alpha:]-]*/", True),
        ],
    )
    def test_odd_bracket_shapes_are_read_like_bash(
        self, tmp_path: Path, token: str, expected: bool
    ) -> None:
        index = _index(tmp_path, _NESTED)
        found = index.directories_matching(token, (str(tmp_path),))
        assert bool(found) is expected

    def test_a_posix_class_mixed_with_other_members(self, tmp_path: Path) -> None:
        index = _index(tmp_path, f"7x/key.{_SUFFIX}")
        assert index.directories_matching("[[:alpha:]7]*/", (str(tmp_path),)) != ()
        assert index.directories_matching("[[:alpha:]_]*/", (str(tmp_path),)) == ()

    def test_a_symlink_to_a_protected_directory_is_matched_by_the_glob(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "dir").mkdir()
        (tmp_path / "l").symlink_to(tmp_path / "dir")
        index = _index(tmp_path, _NESTED)
        found = index.directories_matching("l*/", (str(tmp_path),))
        assert found == (f"{tmp_path}/l",)

    def test_a_symlink_to_a_directory_without_a_protected_file_is_not_matched(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "dir").mkdir()
        (tmp_path / "docs").mkdir()
        (tmp_path / "l").symlink_to(tmp_path / "docs")
        index = _index(tmp_path, _NESTED)
        assert index.directories_matching("l*/", (str(tmp_path),)) == ()

    def test_a_symlink_to_a_file_or_a_dangling_symlink_is_ignored(self, tmp_path: Path) -> None:
        (tmp_path / "dir").mkdir()
        (tmp_path / "f.txt").write_text("x")
        (tmp_path / "lf").symlink_to(tmp_path / "f.txt")
        (tmp_path / "ld").symlink_to(tmp_path / "gone")
        index = _index(tmp_path, _NESTED)
        assert index.directories_matching("l*/", (str(tmp_path),)) == ()

    def test_a_hidden_symlink_is_reached_only_by_a_dot_glob(self, tmp_path: Path) -> None:
        (tmp_path / "dir").mkdir()
        (tmp_path / ".l").symlink_to(tmp_path / "dir")
        index = _index(tmp_path, _NESTED)
        assert index.directories_matching("*/", (str(tmp_path),)) == (f"{tmp_path}/dir",)
        assert index.directories_matching(".l*/", (str(tmp_path),)) == (f"{tmp_path}/.l",)

    def test_a_missing_literal_parent_is_not_an_error(self, tmp_path: Path) -> None:
        index = _index(tmp_path, _NESTED)
        assert index.directories_matching("nope/l*/", (str(tmp_path),)) == ()

    def test_a_search_read_of_a_trailing_slash_glob_is_not_expanded_on_disk(
        self, nested: Path
    ) -> None:
        reads = search_reads("grep -r x */", str(nested))
        assert [(read.root, read.glob) for read in reads] == [(f"{nested}/*/", True)]


class TestCommandLevel:
    @pytest.mark.parametrize("command", ["ls -d */", "ls -d ./*/", "echo */"])
    def test_a_listing_of_directories_ignores_a_protected_file_at_the_root(
        self, top_level_only: Path, command: str
    ) -> None:
        assert _verdict(top_level_only, command) == Decision.ALLOW

    def test_a_recursive_reader_of_a_literal_directory_is_denied(self, nested: Path) -> None:
        assert _verdict(nested, "grep -r x dir/") == Decision.DENY

    def test_a_recursive_reader_of_the_matching_glob_is_denied_too(self, nested: Path) -> None:
        assert _verdict(nested, "grep -r x */") == Decision.DENY
        assert _verdict(nested, "grep -r x d*/") == Decision.DENY

    @pytest.mark.parametrize(
        "command",
        [
            "grep -r x [^x]*/",
            "grep -r x [!x]*/",
            "grep -r x d?r/",
            "grep -r x di[r]/",
            "grep -r x ./*/",
            "rg x */",
            "cd docs && grep -r x ../*/",
        ],
    )
    def test_other_trailing_slash_shapes_are_denied_through_a_matching_directory(
        self, nested: Path, command: str
    ) -> None:
        assert _verdict(nested, command) == Decision.DENY

    @pytest.mark.parametrize(
        "command",
        [
            "grep -r x [[:alpha:]]*/",
            "grep -r x [[:lower:]][[:lower:]]?/",
            "rg x [[:alnum:]]*/",
            "grep -r x [![:digit:]]*/",
        ],
    )
    def test_a_posix_class_glob_is_denied_through_a_matching_directory(
        self, nested: Path, command: str
    ) -> None:
        assert _verdict(nested, command) == Decision.DENY

    def test_a_posix_class_glob_that_misses_is_allowed(self, nested: Path) -> None:
        assert _verdict(nested, "grep -r x [[:digit:]]*/") == Decision.ALLOW

    def test_a_posix_class_file_glob_is_judged_like_the_plain_one(self, nested: Path) -> None:
        assert _verdict(nested, "cat dir/[[:alpha:]]*") == _verdict(nested, "cat dir/k*")
        assert _verdict(nested, "cat dir/[[:alpha:]]*") == Decision.DENY

    def test_a_glob_matching_a_symlink_to_a_protected_directory_is_denied(
        self, nested: Path
    ) -> None:
        (nested / "l").symlink_to(nested / "dir")
        assert _verdict(nested, "grep -r x l/") == Decision.DENY
        assert _verdict(nested, "grep -r x l*/") == Decision.DENY
        assert _verdict(nested, "grep -r x ./?/") == Decision.DENY

    def test_a_glob_matching_only_a_symlink_to_a_harmless_directory_is_allowed(
        self, top_level_only: Path
    ) -> None:
        (top_level_only / "l").symlink_to(top_level_only / "docs")
        assert _verdict(top_level_only, "grep -r x l*/") == Decision.ALLOW

    def test_an_absolute_trailing_slash_glob_is_denied_too(self, nested: Path) -> None:
        assert _verdict(nested, f"grep -r x {nested}/*/") == Decision.DENY

    def test_a_dot_directory_is_reached_only_by_a_dot_glob(self, tmp_path: Path) -> None:
        root = _make_project(tmp_path, f".hidden/key.{_SUFFIX}")
        protected_file_index.reset_index_cache()
        with patch.object(guard_module, "resolve_project_root", return_value=str(root)):
            index_project(root, SecretFileGuardHandler()._patterns())
            assert _verdict(root, "grep -r x */") == Decision.ALLOW
            assert _verdict(root, "grep -r x .*/") == Decision.DENY
        protected_file_index.reset_index_cache()

    @pytest.mark.parametrize("command", ["grep -r x [^d]*/", "grep -r x [!d]*/", "grep -r x x*/"])
    def test_a_glob_that_misses_the_protected_directory_is_allowed(
        self, nested: Path, command: str
    ) -> None:
        assert _verdict(nested, command) == Decision.ALLOW

    def test_a_recursive_reader_of_directories_without_a_protected_file_is_allowed(
        self, top_level_only: Path
    ) -> None:
        assert _verdict(top_level_only, "grep -r x */") == Decision.ALLOW

    @pytest.mark.parametrize("command", ["ls -d */", "ls */", "ls -d d*/"])
    def test_a_glob_agrees_with_the_literal_directory_it_expands_to(
        self, nested: Path, command: str
    ) -> None:
        literal = _verdict(nested, "ls -d dir/")
        assert _verdict(nested, command) == literal


class TestReviewFindings:
    """Opus review of Plan 00612: backtracking, symlinked literal parents, bare globs."""

    @pytest.mark.parametrize(
        ("glob", "name"),
        [
            ("*a*a*a*a*b", "a" * 255),
            ("*-*-*-*-*.json", "-" * 244),
            ("*a*a*a*a*[b]", "a" * 255),
        ],
    )
    def test_a_many_star_glob_does_not_backtrack_polynomially(self, glob: str, name: str) -> None:
        import time

        from claude_code_hooks_daemon.utils.protected_file_index import _segments_match

        started = time.perf_counter()
        assert _segments_match([name], [glob]) is False
        assert time.perf_counter() - started < scaled_seconds(_BACKTRACK_BUDGET_SECONDS)

    @pytest.mark.parametrize(
        ("glob", "name", "expected"),
        [
            ("*a", "aa", True),
            ("*[ab]c", "xbac", True),
            ("a*b*c", "aXbYbc", True),
            ("a*b*c", "aXbYb", False),
            ("*", "anything", True),
            ("**", "anything", True),
            ("a*", "a", True),
            ("*a*", "xax", True),
            ("x*?y", "xaay", True),
        ],
    )
    def test_atomic_stars_keep_the_same_answers(self, glob: str, name: str, expected: bool) -> None:
        from claude_code_hooks_daemon.utils.protected_file_index import _segments_match

        assert _segments_match([name], [glob]) is expected

    def test_a_glob_under_a_symlinked_literal_parent_is_judged(self, tmp_path: Path) -> None:
        (tmp_path / "up").symlink_to(tmp_path)
        index = _index(tmp_path, _NESTED)
        assert index.directories_matching("up/di?/", (str(tmp_path),)) == (f"{tmp_path}/dir",)
        assert index.glob_matches(f"up/dir/ke?.{_SUFFIX}", (str(tmp_path),)) is not None

    def test_the_symlink_scan_runs_under_a_symlinked_literal_parent(self, tmp_path: Path) -> None:
        (tmp_path / "dir").mkdir()
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "l").symlink_to(tmp_path / "dir")
        (tmp_path / "up").symlink_to(tmp_path / "sub")
        index = _index(tmp_path, _NESTED)
        assert index.directories_matching("up/l*/", (str(tmp_path),)) == (f"{tmp_path}/sub/l",)

    def test_a_real_directory_named_with_a_glob_character_stays_literal(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "a*b").mkdir()
        (tmp_path / "a*b" / "dir").mkdir()
        (tmp_path / "up").symlink_to(tmp_path / "a*b")
        index = _index(tmp_path, f"a*b/dir/key.{_SUFFIX}", f"axb/dir/key.{_SUFFIX}")
        found = index.directories_matching("up/d*/", (str(tmp_path),))
        assert found == (f"{tmp_path}/a*b/dir",)

    def test_a_symlinked_parent_is_denied_at_the_handler(self, nested: Path) -> None:
        (nested / "up").symlink_to(nested)
        assert _verdict(nested, "grep -r x up/dir/") == Decision.DENY
        assert _verdict(nested, "grep -r x up/di?/") == Decision.DENY

    @pytest.mark.parametrize("command", ["grep -r x d*", "grep -r x di?", "rg x d*"])
    def test_a_recursive_reader_of_a_glob_without_a_slash_is_judged(
        self, nested: Path, command: str
    ) -> None:
        assert _verdict(nested, command) == Decision.DENY

    @pytest.mark.parametrize("command", ["grep -r x x*", "grep -r x [!de]?", "ls d*", "grep x d*"])
    def test_other_bare_globs_are_unchanged(self, nested: Path, command: str) -> None:
        assert _verdict(nested, command) == Decision.ALLOW
