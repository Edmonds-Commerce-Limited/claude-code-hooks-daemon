"""Tests for the recursive-search reach check (Plan 00483 batch H, D1).

A recursive search reads every file under its roots without naming one, so the
roots are walked with the same bounded walk the Grep tool route uses.
"""

import subprocess  # nosec B404 - fixed git argv in a tmp repository
from pathlib import Path

import pytest

from claude_code_hooks_daemon.utils import recursive_search as rs
from claude_code_hooks_daemon.utils import secret_file_matching as sfm

PROTECTED_GLOB = "*.p483vault"
PATTERNS = (PROTECTED_GLOB,)
PROTECTED_NAME = "key.p483vault"


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """``sub`` holds a protected file; ``clean`` holds none."""
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / PROTECTED_NAME).write_text("x\n")
    (tmp_path / "clean").mkdir()
    (tmp_path / "clean" / "a.txt").write_text("x\n")
    return tmp_path


def _reach(command: str, cwd: Path) -> str | None:
    found = rs.protected_reached_by_search(command, PATTERNS, cwd=str(cwd))
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
    assert _reach("grep -r x .", tree / "clean") is None
    assert _reach("grep -r x ..", tree / "clean") == PROTECTED_GLOB


def test_absolute_root_is_walked(tree: Path) -> None:
    assert _reach(f"grep -r x {tree / 'sub'}", tree / "clean") == PROTECTED_GLOB


def test_piped_rg_without_a_root_reads_stdin(tree: Path) -> None:
    assert _reach("echo hi | rg x", tree) is None


def test_xargs_after_a_non_find_producer_names_no_root(tree: Path) -> None:
    assert _reach("echo a | xargs grep x", tree) is None


def test_missing_cwd_leaves_relative_roots_unjudged(tree: Path) -> None:
    assert rs.protected_reached_by_search("grep -r x .", PATTERNS, cwd=None) is None


def test_detail_is_the_searched_root(tree: Path) -> None:
    found = rs.protected_reached_by_search("grep -r x sub", PATTERNS, cwd=str(tree))
    assert found == (PROTECTED_GLOB, str(tree / "sub"))


def test_exempt_file_does_not_flag_the_tree(tree: Path) -> None:
    exempt = str(tree / "sub" / PROTECTED_NAME)
    found = rs.protected_reached_by_search(
        "grep -r x .", PATTERNS, cwd=str(tree), is_exempt=lambda path: path == exempt
    )
    assert found is None


def test_the_walk_is_the_shared_bounded_walk(tree: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The cap and the answer past it belong to the directory walk, not to this module."""
    roots: list[str] = []

    def _walk(directory: str, patterns: tuple[str, ...], **kwargs: object) -> str | None:
        roots.append(directory)
        return None

    monkeypatch.setattr(sfm, "directory_contains_protected", _walk)
    assert _reach("grep -r x .", tree) is None
    assert roots == [str(tree)]


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True
    )  # nosec B603 B607


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


def test_git_grep_does_not_read_an_ignored_file(repo: Path) -> None:
    _git(repo, "rm", "-q", "--cached", "-r", "tracked")
    assert _reach("git grep needle", repo) is None


def test_git_grep_no_index_reads_the_working_tree(repo: Path) -> None:
    _git(repo, "rm", "-q", "--cached", "-r", "tracked")
    assert _reach("git grep --no-index needle", repo) == PROTECTED_GLOB


def test_git_grep_outside_a_repository_is_not_reported(tree: Path) -> None:
    assert _reach("git grep needle", tree) is None


@pytest.fixture
def hidden_tree(tmp_path: Path) -> Path:
    """The only protected files sit in a hidden directory and under a hidden name."""
    (tmp_path / ".hid").mkdir()
    (tmp_path / ".hid" / PROTECTED_NAME).write_text("x\n")
    (tmp_path / "a.txt").write_text("x\n")
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
    (tmp_path / f".{PROTECTED_NAME}").write_text("x\n")
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


def test_the_walk_skips_what_the_caller_prunes(tree: Path) -> None:
    pruned = sfm.directory_contains_protected(
        str(tree), PATTERNS, skip=lambda path, is_dir: is_dir and path.endswith("sub")
    )
    assert pruned is None
    kept = sfm.directory_contains_protected(str(tree), PATTERNS, skip=lambda path, is_dir: False)
    assert kept == PROTECTED_GLOB
