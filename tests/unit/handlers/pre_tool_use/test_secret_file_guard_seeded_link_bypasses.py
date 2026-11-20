"""Bypasses of the seeded-link read guard found by the F-BYPS review (Plan 00613).

``conf`` is a directory link from a worktree into the main checkout, and the
protected glob is ``conf/vault.txt`` (no shipped default names it, so only
RESOLVING the link can deny a read through it). Every command runs with the
hook ``cwd`` in the worktree, once with the daemon rooted at the main checkout
and once with it rooted at the worktree.

- F1: ``fd -x/-X`` runs a reader on each walked file, as ``find -exec`` does.
- F3: a brace operand of a recursive search is judged as each spelling.
- F4: ``link/..`` leaves the daemon's project when the link leads out of it.
- F5: a link made earlier in the command is judged as if it already existed.
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

_GLOBS = ["conf/vault.txt"]


class _Layout:
    def __init__(self, root: Path, tree: Path) -> None:
        self.root = root
        self.tree = tree


@pytest.fixture(params=["main-root", "worktree-root"])
def layout(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[_Layout]:
    """A main checkout with ``conf/vault.txt`` and a worktree whose ``conf`` links to it."""
    root = tmp_path / "project"
    (root / "conf").mkdir(parents=True)
    (root / "conf/vault.txt").write_bytes(b"fixture\n")
    (root / "docs").mkdir()
    (root / "docs/notes.txt").write_bytes(b"ordinary\n")
    tree = root / ".claude/worktrees/alpha-1234abcd"
    tree.mkdir(parents=True)
    (tree / "plain.txt").write_bytes(b"ordinary\n")
    (tree / "docs").mkdir()
    (tree / "conf").symlink_to(root / "conf")
    daemon_root = root if request.param == "main-root" else tree
    protected_file_index.reset_index_cache()
    with patch.object(guard_module, "resolve_project_root", return_value=str(daemon_root)):
        handler = SecretFileGuardHandler()
        handler._protected_paths = _GLOBS
        index_project(daemon_root, handler._patterns())
        yield _Layout(root, tree)
    protected_file_index.reset_index_cache()


def _decision(layout: _Layout, command: str) -> Decision:
    command = command.replace("@ROOT", str(layout.root)).replace("@WT", str(layout.tree))
    hook_input: dict[str, Any] = {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": str(layout.tree),
    }
    handler = SecretFileGuardHandler()
    handler._protected_paths = _GLOBS
    if not handler.matches(hook_input):
        return Decision.ALLOW
    return handler.handle(hook_input).decision


class TestFdExecRunsAReaderOnEachWalkedFile:
    @pytest.mark.parametrize(
        "command",
        [
            "fd -x cat",
            "fd -L -x cat",
            "fd -L . -x cat",
            "fd . conf/ -x cat",
            "fd . conf -X cat",
            "fd vault -x cat",
            "fd --exec cat",
            "fd --exec-batch cat",
            "fd -u -X cat",
            "fd --search-path conf -x cat",
            "fd -e txt . conf -x cat {}",
            "fd --base-directory conf -x cat",
            "fdfind -x cat",
            "fd -x grep -r x",
            "fd . conf -x sh -c 'cat {}'",
            "bfs -L conf -exec cat {} +",
            "bfs conf -exec cat {} ;",
        ],
    )
    def test_denied(self, layout: _Layout, command: str) -> None:
        assert _decision(layout, command) == Decision.DENY

    @pytest.mark.parametrize(
        "command",
        [
            "fd",
            "fd conf",
            "fd . docs",
            "fd -x echo",
            "fd . docs -x cat",
            "fd -L . docs -X cat",
            "fd pattern -x ls",
        ],
    )
    def test_controls_are_allowed(self, layout: _Layout, command: str) -> None:
        assert _decision(layout, command) == Decision.ALLOW


class TestBraceOperandsOfARecursiveSearch:
    @pytest.mark.parametrize(
        "command",
        [
            "grep -r fixture {conf,docs}",
            "rg fixture {conf,docs}",
            "grep -R fixture {docs,conf}",
            "grep -r fixture {conf,docs}/",
            "ag fixture {conf,docs}",
            "find {conf,docs} -type f -exec cat {} +",
            "grep -r fixture {conf,x}{,}",
            "grep -r fixture {x,y}/../{conf,z}",
        ],
    )
    def test_denied(self, layout: _Layout, command: str) -> None:
        assert _decision(layout, command) == Decision.DENY

    @pytest.mark.parametrize(
        "command",
        [
            "grep -r fixture {docs,plain.txt}",
            "rg fixture {docs,plain.txt}",
            "grep -r fixture {a,b}",
        ],
    )
    def test_controls_are_allowed(self, layout: _Layout, command: str) -> None:
        assert _decision(layout, command) == Decision.ALLOW

    def test_too_many_spellings_is_denied(self, layout: _Layout) -> None:
        command = "grep -r fixture " + "{a,b}" * 12
        assert _decision(layout, command) == Decision.DENY


class TestParentOfALinkLeavesTheProject:
    @pytest.mark.parametrize(
        "command",
        [
            "grep -r fixture conf/..",
            "rg fixture conf/..",
            "grep -R fixture conf/..",
            "grep -r fixture conf/../",
        ],
    )
    def test_denied(self, layout: _Layout, command: str) -> None:
        assert _decision(layout, command) == Decision.DENY

    @pytest.mark.parametrize(
        "command",
        ["grep -r fixture docs/..", "rg fixture docs/../docs", "grep -r fixture ."],
    )
    def test_a_parent_that_leaves_no_link_is_allowed(self, layout: _Layout, command: str) -> None:
        assert _decision(layout, command) == Decision.ALLOW


class TestALinkMadeEarlierInTheCommand:
    @pytest.mark.parametrize(
        "command",
        [
            "ln -s @ROOT/conf conf2 && cat conf2/vault.txt",
            "ln -s @ROOT/conf conf2 && grep -R fixture .",
            "ln -s @ROOT/conf conf2; grep -R fixture conf2",
            "ln -sfn @ROOT/conf conf2 && grep -r fixture conf2/",
            "ln --symbolic @ROOT/conf conf2 && cat conf2/vault.txt",
            "ln -s ../../../conf conf2 && cat conf2/vault.txt",
            "ln -s @ROOT/conf -t docs && cat docs/conf/vault.txt",
            "ln -s @ROOT/conf conf2 && cd conf2 && cat vault.txt",
            "ln -s @ROOT/conf conf2 && cp -rL conf2 copy",
            "ln -s @ROOT/conf conf2 && tar -chf out.tar conf2",
            "ln -s @ROOT/conf conf2 && echo done && cat conf2/vault.txt",
            "ln -s @ROOT/conf $DEST && cat plain.txt $DEST/vault.txt",
            "ln -s @ROOT/conf conf2 && bash -c 'cat conf2/vault.txt'",
            "cp -rs @ROOT/conf conf2 && cat conf2/vault.txt",
            "hooks-daemon seed-worktree @WT && grep -R x @WT",
            "bin/hooks-daemon seed-worktree wt && grep -R x wt",
            ".claude/hooks-daemon/bin/hooks-daemon seed-worktree wt && cat wt/conf/vault.txt",
        ],
    )
    def test_denied(self, layout: _Layout, command: str) -> None:
        assert _decision(layout, command) == Decision.DENY

    @pytest.mark.parametrize(
        "command",
        [
            "ln -s @ROOT/conf conf2",
            "ln -s @ROOT/conf conf2 && ls conf2",
            "ln -s @ROOT/docs docs2 && cat docs2/notes.txt",
            "ln -s @ROOT/docs docs2 && grep -R ordinary docs",
            "ln -s plain.txt alias.txt && cat alias.txt",
            "cat plain.txt && ln -s @ROOT/conf conf2",
            "ln -s @ROOT/docs docs2 && cat @ROOT/docs/notes.txt",
            "hooks-daemon seed-worktree wt",
            "hooks-daemon seed-worktree wt && ls wt",
        ],
    )
    def test_controls_are_allowed(self, layout: _Layout, command: str) -> None:
        assert _decision(layout, command) == Decision.ALLOW

    def test_a_later_read_that_touches_nothing_near_the_link_is_allowed(
        self, layout: _Layout
    ) -> None:
        command = "ln -s @ROOT/conf conf2 && cat plain.txt"
        assert _decision(layout, command) == Decision.ALLOW
