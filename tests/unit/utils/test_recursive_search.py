"""Tests for the recursive-search reach check (Plan 00483 batch H, D1; A2).

A recursive search reads every file under its roots without naming one, so the
roots are looked up in the protected-file index. Nothing here walks a tree.
"""

import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.utils import recursive_search as rs
from claude_code_hooks_daemon.utils.protected_file_index import (
    ProtectedFileIndex,
    TreeView,
    build_index,
)

PROTECTED_GLOB = "*.p483vault"
PATTERNS = (PROTECTED_GLOB,)
PROTECTED_NAME = "key.p483vault"


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def _index(root: Path) -> ProtectedFileIndex:
    index = build_index(root, PATTERNS)
    assert index is not None
    return index


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """``sub`` holds a protected file; ``clean`` holds none."""
    _git(tmp_path, "init", "-q")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / PROTECTED_NAME).write_text("x\n")
    (tmp_path / "clean").mkdir()
    (tmp_path / "clean" / "a.txt").write_text("x\n")
    _git(tmp_path, "add", "-A")
    return tmp_path


def _reach(command: str, cwd: Path | None, root: Path | None = None) -> str | None:
    """The protected glob a search in ``command`` reads, judged against ``root``'s index."""
    reads = rs.search_reads(command, None if cwd is None else str(cwd))
    found = rs.protected_reached(reads, _index(root if root is not None else cwd or Path()))
    return None if found is None else found[0]


@pytest.mark.parametrize(
    "command",
    [
        "grep -r x .",
        "grep -rl x sub",
        "grep -R x .",
        "grep --recursive x .",
        "grep -d recurse x .",
        "egrep -r x .",
        "rg x",
        "rg x sub",
        "ag x",
        "ack x",
        "ugrep -r x .",
        "sudo rg x",
        "timeout 5 grep -r x .",
        "FOO=1 grep -r x .",
        "find . | xargs rg x",
        "find . -type f | xargs -n 1 grep x",
        "find sub -print0 | xargs -0 grep x",
        "find . -name '*.txt' -exec grep x {} +",
        "find . -name '*.txt' -exec grep x {} \\;",
        "find . -execdir rg x {} +",
        "bash -c 'grep -r x .'",
        'sh -c "rg x"',
        'eval "grep -r x ."',
        "echo hi; grep -r x .",
    ],
)
def test_search_reaching_a_protected_file_is_reported(tree: Path, command: str) -> None:
    assert _reach(command, tree) == PROTECTED_GLOB


@pytest.mark.parametrize(
    "command",
    [
        "grep x .",
        "grep -r x clean",
        "rg x clean",
        "find clean | xargs rg x",
        "find . -name '*.txt'",
        "find . -exec cat {} +",
        "echo rg",
        "echo grep -r x .",
        "git commit -m 'grep -r x .'",
        "bash -c 'echo hi'",
        "cat sub",
        "grep -r x 'unclosed",
        "ls",
        "",
    ],
)
def test_other_commands_are_not_reported(tree: Path, command: str) -> None:
    assert _reach(command, tree) is None


def test_relative_roots_follow_the_payload_cwd(tree: Path) -> None:
    assert _reach("grep -r x .", tree / "clean", root=tree) is None
    assert _reach("grep -r x ..", tree / "clean", root=tree) == PROTECTED_GLOB


def test_absolute_root_is_judged(tree: Path) -> None:
    assert _reach(f"grep -r x {tree / 'sub'}", tree / "clean", root=tree) == PROTECTED_GLOB


def test_piped_rg_without_a_root_reads_stdin(tree: Path) -> None:
    assert _reach("echo hi | rg x", tree) is None


def test_xargs_after_a_non_find_producer_names_no_root(tree: Path) -> None:
    assert _reach("echo a | xargs grep x", tree) is None


def test_missing_cwd_leaves_relative_roots_unjudged(tree: Path) -> None:
    assert rs.search_reads("grep -r x .", None) == []


def test_the_read_is_the_searched_root_and_its_view(tree: Path) -> None:
    (read,) = rs.search_reads("grep -r x sub", str(tree))

    assert read.root == str(tree / "sub")
    assert read.view is TreeView.ALL
    assert rs.protected_reached([read], _index(tree)) == (PROTECTED_GLOB, str(tree / "sub"))


def test_exempt_file_does_not_flag_the_tree(tree: Path) -> None:
    exempt = str(tree / "sub" / PROTECTED_NAME)
    reads = rs.search_reads("grep -r x .", str(tree))

    found = rs.protected_reached(reads, _index(tree), is_exempt=lambda path: path == exempt)

    assert found is None


class TestWorkingDirectoryFollowsCd:
    """A literal ``cd`` before the search moves the root it is placed from."""

    def test_a_search_after_cd_into_a_clean_directory_reads_that_directory(
        self, tree: Path
    ) -> None:
        assert _reach(f"cd {tree / 'clean'} && grep -rn x .", tree) is None

    def test_a_search_after_cd_into_the_protected_directory_reads_it(self, tree: Path) -> None:
        assert _reach("cd sub && grep -rn x .", tree) == PROTECTED_GLOB

    def test_cd_steps_accumulate(self, tree: Path) -> None:
        assert _reach("cd clean && cd .. && grep -r x sub", tree) == PROTECTED_GLOB
        assert _reach("cd sub && cd .. && cd clean && grep -r x .", tree) is None

    def test_a_cd_with_a_computed_target_leaves_relative_roots_unplaced(self, tree: Path) -> None:
        assert rs.search_reads('cd "$D" && grep -r x .', str(tree)) == []
        assert rs.search_reads("cd $(pwd)/x && grep -r x .", str(tree)) == []

    def test_a_bare_cd_goes_home_which_is_unknown(self, tree: Path) -> None:
        assert rs.search_reads("cd && grep -r x .", str(tree)) == []

    def test_cd_dash_is_unknown(self, tree: Path) -> None:
        assert rs.search_reads("cd - && grep -r x .", str(tree)) == []

    def test_an_absolute_root_is_still_judged_after_an_unplaceable_cd(self, tree: Path) -> None:
        reads = rs.search_reads(f'cd "$D" && grep -r x {tree / "sub"}', str(tree))

        assert [read.root for read in reads] == [str(tree / "sub")]

    def test_a_cd_inside_a_nested_shell_moves_only_that_shell(self, tree: Path) -> None:
        assert _reach("bash -c 'cd sub && grep -r x .'", tree) == PROTECTED_GLOB
        assert _reach("bash -c 'cd clean' && grep -r x .", tree) == PROTECTED_GLOB


@pytest.mark.parametrize(
    ("command", "view"),
    [
        ("grep -r x .", TreeView.ALL),
        ("ack x", TreeView.ALL),
        ("rg --no-ignore x", TreeView.ALL),
        ("rg -uu x", TreeView.ALL),
        ("ag -u x", TreeView.ALL),
        ("rg x", TreeView.UNIGNORED),
        ("ag x", TreeView.UNIGNORED),
        ("git grep x", TreeView.TRACKED),
        ("git grep --no-index x", TreeView.ALL),
        ("git grep --untracked x", TreeView.ALL),
    ],
)
def test_each_tool_reads_the_view_it_reads(tree: Path, command: str, view: TreeView) -> None:
    assert [read.view for read in rs.search_reads(command, str(tree))] == [view]


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repository tracking ``tracked/<protected>`` and ignoring ``local/<protected>``."""
    _git(tmp_path, "init", "-q")
    (tmp_path / "tracked").mkdir()
    (tmp_path / "tracked" / PROTECTED_NAME).write_text("x\n")
    (tmp_path / "plain.txt").write_text("x\n")
    (tmp_path / ".gitignore").write_text("local/\n")
    (tmp_path / "local").mkdir()
    (tmp_path / "local" / PROTECTED_NAME).write_text("x\n")
    _git(tmp_path, "add", "tracked", "plain.txt", ".gitignore")
    return tmp_path


def test_git_grep_reaches_a_tracked_protected_file(repo: Path) -> None:
    assert _reach("git grep needle", repo) == PROTECTED_GLOB


def test_git_grep_with_a_clean_pathspec_is_not_reported(repo: Path) -> None:
    assert _reach("git grep needle -- plain.txt", repo) is None


def test_git_grep_does_not_read_an_untracked_file(repo: Path) -> None:
    _git(repo, "rm", "-q", "--cached", "-r", "tracked")
    assert _reach("git grep needle", repo) is None


def test_git_grep_no_index_reads_the_working_tree(repo: Path) -> None:
    _git(repo, "rm", "-q", "--cached", "-r", "tracked")
    assert _reach("git grep --no-index needle", repo) == PROTECTED_GLOB


@pytest.fixture
def hidden_tree(tmp_path: Path) -> Path:
    """The only protected files sit in a hidden directory and under a hidden name."""
    _git(tmp_path, "init", "-q")
    (tmp_path / ".hid").mkdir()
    (tmp_path / ".hid" / PROTECTED_NAME).write_text("x\n")
    (tmp_path / "a.txt").write_text("x\n")
    _git(tmp_path, "add", "-A")
    return tmp_path


@pytest.mark.parametrize("command", ["rg x", "ag x", "rg -u x", "rg x -g '!clean'"])
def test_rg_and_ag_skip_hidden_entries_by_default(hidden_tree: Path, command: str) -> None:
    assert _reach(command, hidden_tree) is None


@pytest.mark.parametrize(
    "command",
    [
        "rg --hidden x",
        "rg -. x",
        "rg -uu x",
        "rg -uuu x",
        "ag --hidden x",
        "ag -u x",
        "ag --unrestricted x",
        "grep -r x .",
        "ack x",
    ],
)
def test_hidden_entries_are_read_when_the_tool_reads_them(hidden_tree: Path, command: str) -> None:
    assert _reach(command, hidden_tree) == PROTECTED_GLOB


def test_rg_skips_a_hidden_protected_file_name(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-q")
    (tmp_path / f".{PROTECTED_NAME}").write_text("x\n")
    _git(tmp_path, "add", "-A")

    assert _reach("rg x", tmp_path) is None
    assert _reach("rg --hidden x", tmp_path) == PROTECTED_GLOB


def test_a_hidden_root_named_outright_is_searched(hidden_tree: Path) -> None:
    assert _reach("rg x .hid", hidden_tree) == PROTECTED_GLOB


@pytest.fixture
def ignored_repo(tmp_path: Path) -> Path:
    """A repository whose only protected file is gitignored."""
    _git(tmp_path, "init", "-q")
    (tmp_path / ".gitignore").write_text("local/\n")
    (tmp_path / "local").mkdir()
    (tmp_path / "local" / PROTECTED_NAME).write_text("x\n")
    (tmp_path / "plain.txt").write_text("x\n")
    _git(tmp_path, "add", ".gitignore", "plain.txt")
    return tmp_path


@pytest.mark.parametrize("command", ["rg x", "ag x"])
def test_rg_and_ag_honour_gitignore(ignored_repo: Path, command: str) -> None:
    assert _reach(command, ignored_repo) is None


@pytest.mark.parametrize(
    "command",
    ["rg --no-ignore x", "rg -u x", "ag -u x", "ag --skip-vcs-ignores x", "grep -r x .", "ack x"],
)
def test_gitignore_is_not_honoured_by_the_tools_that_do_not(
    ignored_repo: Path, command: str
) -> None:
    assert _reach(command, ignored_repo) == PROTECTED_GLOB


def test_an_ignored_directory_named_outright_is_read_by_rg(ignored_repo: Path) -> None:
    assert _reach("rg x local", ignored_repo) == PROTECTED_GLOB


@pytest.mark.parametrize(
    "command",
    [
        "grep -r --exclude-dir=sub x .",
        "grep -r --exclude-dir=sub/ x .",
        "grep -r --exclude-dir=s* x .",
        "grep -r --exclude=*.p483vault x .",
        "rg -g '!sub' x",
        "rg --glob '!sub' x",
        "rg -g '!*.p483vault' x",
        "rg -g '!sub/**' x",
    ],
)
def test_an_exclusion_that_removes_the_protected_path_allows_the_search(
    tree: Path, command: str
) -> None:
    assert _reach(command, tree) is None


@pytest.mark.parametrize(
    "command",
    [
        "grep -r --exclude-dir=clean x .",
        "grep -r --exclude=*.txt x .",
        "rg -g '!clean' x",
        "rg -g '!sub' -g '*.py' x",
        "rg -g '*.p483vault' x",
    ],
)
def test_an_exclusion_that_misses_the_protected_path_does_not_allow_it(
    tree: Path, command: str
) -> None:
    assert _reach(command, tree) == PROTECTED_GLOB


def test_the_size_of_the_tree_does_not_change_the_answer(
    ignored_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The index lists protected files, so a big ignored directory costs nothing and caps nothing."""
    (ignored_repo / ".gitignore").write_text("local/\nbulk/\n")
    (ignored_repo / "bulk").mkdir()
    for number in range(300):
        (ignored_repo / "bulk" / f"f{number}.txt").write_text("x\n")

    assert _reach("rg x .", ignored_repo) is None
    assert _reach("grep -r x local", ignored_repo) == PROTECTED_GLOB


def test_git_grep_finds_a_tracked_protected_file_listed_after_position_six_thousand(
    tmp_path: Path,
) -> None:
    _git(tmp_path, "init", "-q")
    (tmp_path / "a").mkdir()
    for number in range(6000):
        (tmp_path / "a" / f"f{number:05d}.txt").write_text("x\n")
    (tmp_path / "z").mkdir()
    (tmp_path / "z" / PROTECTED_NAME).write_text("x\n")
    _git(tmp_path, "add", "-A")

    assert _reach("git grep needle", tmp_path) == PROTECTED_GLOB
