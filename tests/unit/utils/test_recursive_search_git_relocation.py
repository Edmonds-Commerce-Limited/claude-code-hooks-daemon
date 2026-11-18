"""A ``git grep`` moved by a global option reads the tree it is moved to (Plan 00618 S-1).

``git -C <dir> grep --no-index`` reads ``<dir>`` exactly as ``cd <dir> && git
grep --no-index`` does, so it is judged the same way. A move that cannot be
placed literally (an expansion in the value, ``--git-dir``, a ``core.worktree``
override, a relocating environment variable) is judged over every indexed file:
it fails closed, never open. Nothing here walks a tree.
"""

import shlex
import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.utils import recursive_search as rs
from claude_code_hooks_daemon.utils.protected_file_index import (
    ProtectedFileIndex,
    TreeView,
    build_index,
)

PROTECTED_GLOB = "*.p618vault"
PATTERNS = (PROTECTED_GLOB,)
PROTECTED_NAME = "key.p618vault"


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def _index(root: Path) -> ProtectedFileIndex:
    index = build_index(root, PATTERNS)
    assert index is not None
    return index


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """``deep`` (gitignored) holds a protected file, ``sub`` is clean and tracked."""
    _git(tmp_path, "init", "-q")
    (tmp_path / ".gitignore").write_text("deep/\n")
    (tmp_path / "deep").mkdir()
    (tmp_path / "deep" / PROTECTED_NAME).write_text("x\n")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "plain.txt").write_text("x\n")
    _git(tmp_path, "add", ".gitignore", "sub")
    return tmp_path


def _reach(command: str, cwd: Path | None, root: Path) -> str | None:
    reads = rs.search_reads(command, None if cwd is None else str(cwd))
    found = rs.protected_reached(reads, _index(root))
    return None if found is None else found[0]


class TestTheReviewedShapesAreJudged:
    """The three ALLOW shapes of the Step 10 re-run, and their spellings."""

    @pytest.mark.parametrize(
        "command",
        [
            "git -C deep grep --no-index -e .",
            "git --no-pager -C deep grep --no-index -e .",
            "git -C deep grep --no-index -e . .",
            "git -C deep grep --untracked -e .",
            "git -C deep -c color.ui=never grep --no-index -e .",
            "git -C sub -C ../deep grep --no-index -e .",
            "git -C sub grep --no-index -e . ../deep",
            "git -C sub grep --no-index -e . -- ../deep",
            "bash -c 'git -C deep grep --no-index -e .'",
            "sudo git -C deep grep --no-index -e .",
            "echo a | xargs git -C deep grep --no-index -e .",
        ],
    )
    def test_a_literal_dash_c_into_the_protected_tree_is_reported(
        self, repo: Path, command: str
    ) -> None:
        assert _reach(command, repo, repo) == PROTECTED_GLOB

    def test_an_absolute_dash_c_is_placed_without_a_payload_cwd(self, repo: Path) -> None:
        command = f"git -C {repo / 'deep'} grep --no-index -e ."
        assert _reach(command, None, repo) == PROTECTED_GLOB

    def test_the_dash_c_directory_is_the_root_read(self, repo: Path) -> None:
        reads = rs.search_reads("git -C deep grep --no-index -e .", str(repo))

        assert [(read.root, read.view) for read in reads] == [(str(repo / "deep"), TreeView.ALL)]


class TestEquivalentToTheCdForm:
    """``git -C <dir>`` is judged exactly as ``cd <dir> && git ...`` is."""

    @pytest.mark.parametrize(
        ("relocated", "changed_directory"),
        [
            ("git -C deep grep --no-index -e .", "cd deep && git grep --no-index -e ."),
            ("git -C deep grep --no-index -e . .", "cd deep && git grep --no-index -e . ."),
            ("git -C sub grep --no-index -e .", "cd sub && git grep --no-index -e ."),
            ("git -C sub grep -e x", "cd sub && git grep -e x"),
            ("git -C deep grep -e x", "cd deep && git grep -e x"),
            ("git -C sub grep -e x ../deep", "cd sub && git grep -e x ../deep"),
            (
                "git -C sub -C .. grep --no-index -e .",
                "cd sub && cd .. && git grep --no-index -e .",
            ),
        ],
    )
    def test_same_reads(self, repo: Path, relocated: str, changed_directory: str) -> None:
        assert rs.search_reads(relocated, str(repo)) == rs.search_reads(
            changed_directory, str(repo)
        )

    def test_a_relative_dash_c_without_a_payload_cwd_is_left_out_like_cd(self, repo: Path) -> None:
        assert rs.search_reads("git -C deep grep --no-index -e .", None) == []
        assert rs.search_reads("cd deep && git grep --no-index -e .", None) == []


class TestAnUnplaceableMoveFailsClosed:
    """A move whose target is not literal is judged over every indexed file."""

    @pytest.mark.parametrize(
        "command",
        [
            "git -C $D grep --no-index -e .",
            'git -C "$D" grep -e x',
            'git -C "$(pwd)/deep" grep --no-index -e .',
            "git -C `pwd` grep --no-index -e .",
            "git -C d* grep --no-index -e .",
            'cd sub && git -C "$X" grep --no-index -e .',
            "git -C sub -C $D grep --no-index -e .",
            "git --git-dir=.git grep -e x",
            "git --git-dir .git grep --no-index -e .",
            "git -c core.worktree=deep grep -e x",
            "git -c Core.WorkTree=deep grep -e x",
            "git --config-env core.worktree=WT grep -e x",
            "git --config-env=core.worktree=WT grep -e x",
            "git --work-tree=$W grep --untracked -e x",
            "GIT_DIR=.git git grep -e x",
            "GIT_WORK_TREE=deep git grep --untracked -e x",
            "env GIT_INDEX_FILE=/tmp/i git grep -e x",
        ],
    )
    def test_reported(self, repo: Path, command: str) -> None:
        assert _reach(command, repo, repo) == PROTECTED_GLOB

    def test_the_fallback_is_a_read_of_everything(self, repo: Path) -> None:
        reads = rs.search_reads("git -C $D grep -e x", str(repo))

        assert [(read.root, read.view) for read in reads] == [("/", TreeView.ALL)]


class TestALiteralWorkTreeIsJudged:
    @pytest.mark.parametrize(
        "command",
        [
            "git --work-tree=deep grep --untracked -e x",
            "git --work-tree deep grep --untracked -e x",
            "git --work-tree=deep grep -e x",
            "git -C sub --work-tree=../deep grep -e x",
            "git --work-tree={repo}/deep grep -e x",
        ],
    )
    def test_the_work_tree_is_read_in_full(self, repo: Path, command: str) -> None:
        assert _reach(command.format(repo=repo), repo, repo) == PROTECTED_GLOB

    def test_the_project_index_does_not_describe_another_work_tree(self, repo: Path) -> None:
        views = {read.view for read in rs.search_reads("git --work-tree=sub grep -e x", str(repo))}

        assert views == {TreeView.ALL}


class TestGlobalOptionsTakingASeparateValue:
    """The value of ``--attr-source``/``--config-env`` is not the subcommand."""

    @pytest.mark.parametrize(
        "command",
        [
            "git --attr-source HEAD grep --no-index -e .",
            "git --config-env core.pager=XV grep --no-index -e .",
            "git --namespace n grep --no-index -e .",
        ],
    )
    def test_the_search_is_still_found(self, repo: Path, command: str) -> None:
        assert _reach(command, repo, repo) == PROTECTED_GLOB


class TestOrdinaryRelocatedSearchesStayAllowed:
    @pytest.mark.parametrize(
        "command",
        [
            "git -C sub grep --no-index -e .",
            "git -C sub grep -e x",
            "git -C deep grep -e x",
            "git -C sub grep --untracked -e x",
            "git --no-pager -C sub grep -n x",
            "git -C '' grep -e x",
            "git -C sub -c color.ui=never grep -e x",
        ],
    )
    def test_not_reported(self, repo: Path, command: str) -> None:
        assert _reach(command, repo, repo) is None

    def test_an_absolute_clean_dash_c_is_not_reported(self, repo: Path) -> None:
        assert _reach(f"git -C {repo / 'sub'} grep --no-index -e .", repo, repo) is None


class TestTheFlaggableGuardSharesThePlacement:
    """``git_search_directory`` is the one reader of git's global options for a search."""

    @pytest.mark.parametrize(
        ("command", "expected"),
        [
            ("git -C deep grep x", "/r/deep"),
            ("git -C /abs grep x", "/abs"),
            ("git -C sub -C ../deep grep x", "/r/deep"),
            ("git --no-pager grep x", "/r"),
            ("git -C '' grep x", "/r"),
        ],
    )
    def test_a_literal_move_is_placed(self, command: str, expected: str) -> None:
        assert rs.git_search_directory(shlex.split(command), "/r") == expected

    @pytest.mark.parametrize(
        "command",
        [
            "git -C $D grep x",
            "git --git-dir=x grep x",
            "git --work-tree=x grep x",
            "git -c core.worktree=x grep x",
        ],
    )
    def test_an_unplaceable_or_foreign_move_is_none(self, command: str) -> None:
        assert rs.git_search_directory(shlex.split(command), "/r") is None

    @pytest.mark.parametrize(
        ("command", "expected"),
        [
            # A wrapper's value named `git` is not the git that runs.
            ("sudo -u git git -C deep grep x", "/r/deep"),
            ("/x/git git -C .. grep x", "/"),
            ("git -C /x/git grep x", "/x/git"),
        ],
    )
    def test_the_git_that_runs_is_placed(self, command: str, expected: str) -> None:
        assert rs.git_search_directory(shlex.split(command), "/r") == expected

    def test_search_command_finds_the_git_that_runs(self) -> None:
        words = shlex.split("sudo -u git git -C deep grep -e x")
        assert rs.search_command(words) == (rs.TOOL_GIT, words.index("grep") + 1, True)

    def test_a_later_grep_word_is_not_a_git_search(self) -> None:
        assert rs.search_command(shlex.split("git log grep")) is None


class TestACoreWorktreeOverride:
    """``git_overrides_worktree`` reads every global option, in any order."""

    @pytest.mark.parametrize(
        "command",
        [
            "git -c core.worktree=.. grep x",
            "git -C . -c core.worktree=.. grep x",
            "git -C $X -c core.worktree=.. grep x",
            "git -c CORE.WORKTREE=x grep x",
            "git --config-env=core.worktree=WT grep x",
            "git --config-env core.worktree=WT -C . grep x",
            "sudo -u git git -C . -c core.worktree=.. grep x",
        ],
    )
    def test_detected(self, command: str) -> None:
        assert rs.git_overrides_worktree(shlex.split(command)) is True

    @pytest.mark.parametrize(
        "command",
        [
            "git grep x",
            "git -c core.pager=cat -C . grep x",
            "git --config-env=core.pager=PG grep x",
            "git grep -e core.worktree=x",
            "grep -r core.worktree=x .",
        ],
    )
    def test_not_detected(self, command: str) -> None:
        assert rs.git_overrides_worktree(shlex.split(command)) is False
