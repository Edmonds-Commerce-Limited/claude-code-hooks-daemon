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

    def test_a_trailing_slash_glob_names_directories_only_so_matches_no_file(
        self, nested: Path
    ) -> None:
        index = _index(nested, _NESTED)
        for token in ("*/", "d*/", str(nested / "*") + "/"):
            assert index.glob_matches(token, (str(nested),)) is None

    def test_the_directories_a_search_reads_are_the_ones_the_glob_expands_to(
        self, nested: Path
    ) -> None:
        roots = {read.root for read in search_reads("grep -r x */", str(nested))}
        assert roots == {str(nested / "dir"), str(nested / "docs")}


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
