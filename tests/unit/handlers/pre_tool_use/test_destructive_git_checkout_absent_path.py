"""`git checkout <commit> -- <path>` with nothing local to lose is allowed (Plan 00474, N753).

Bringing one file back from another commit was denied as "discards local changes" even
when the path was absent from the working tree and the index, so nothing could be lost,
and `git restore --source` is denied too. The allowance is narrow: ONE plain
`git checkout <commit> -- <paths>` whose every path is either absent from the worktree
and the index, or a tracked regular file, AND for which `git diff` (worktree vs index)
and `git diff --cached` (index vs HEAD) are both clean. Every other shape, and any git
failure, still denies.
"""

import subprocess
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use import destructive_git
from claude_code_hooks_daemon.handlers.pre_tool_use.destructive_git import (
    DestructiveGitHandler,
    _checkout_restore_loss,
)
from claude_code_hooks_daemon.utils.git_commit_parsing import git_invocations
from claude_code_hooks_daemon.utils.git_repo import run_git

_GIT_IDENTITY = (
    "-c",
    "user.name=Test",
    "-c",
    "user.email=test@example.invalid",
    "-c",
    "commit.gpgsign=false",
)
_OLD = "HEAD~1"


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *_GIT_IDENTITY, *args], cwd=cwd, capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """HEAD~1 holds `gone.txt`, `gone2.txt` and `gonedir/f.txt`; HEAD deleted them.

    `a.txt` and `sub/c.txt` are tracked and clean in both commits.
    """
    repo = tmp_path / "repo"
    _git(tmp_path, "init", "-b", "main", str(repo))
    (repo / "sub").mkdir()
    (repo / "gonedir").mkdir()
    for name in ("a.txt", "sub/c.txt", "gone.txt", "gone2.txt", "gonedir/f.txt"):
        (repo / name).write_text(f"content of {name}\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "base")
    _git(repo, "rm", "-q", "-r", "gone.txt", "gone2.txt", "gonedir")
    _git(repo, "commit", "-m", "drop")
    return repo


@pytest.fixture
def handler() -> DestructiveGitHandler:
    return DestructiveGitHandler()


def _verdict(handler: DestructiveGitHandler, command: str, cwd: Path) -> tuple[Decision, str]:
    hook_input: dict[str, Any] = {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": str(cwd),
    }
    assert handler.matches(hook_input) is True
    result = handler.handle(hook_input)
    return result.decision, result.rule or ""


def _denied(handler: DestructiveGitHandler, command: str, cwd: Path) -> None:
    assert _verdict(handler, command, cwd) == (Decision.DENY, RuleID.GIT_CHECKOUT_DISCARD)


class TestNothingLocalToLoseIsAllowed:
    def test_a_path_absent_from_worktree_and_index_is_allowed(
        self, handler: DestructiveGitHandler, repo: Path
    ) -> None:
        decision, _ = _verdict(handler, f"git checkout {_OLD} -- gone.txt", repo)
        assert decision == Decision.ALLOW

    def test_a_commit_hash_is_allowed(self, handler: DestructiveGitHandler, repo: Path) -> None:
        commit = _git(repo, "rev-parse", "--short", _OLD)
        decision, _ = _verdict(handler, f"git checkout {commit} -- gone.txt", repo)
        assert decision == Decision.ALLOW

    def test_every_named_path_absent_is_allowed(
        self, handler: DestructiveGitHandler, repo: Path
    ) -> None:
        decision, _ = _verdict(handler, f"git checkout {_OLD} -- gone.txt gone2.txt", repo)
        assert decision == Decision.ALLOW

    def test_an_absent_directory_is_allowed(
        self, handler: DestructiveGitHandler, repo: Path
    ) -> None:
        decision, _ = _verdict(handler, f"git checkout {_OLD} -- gonedir", repo)
        assert decision == Decision.ALLOW

    def test_a_clean_tracked_file_is_allowed(
        self, handler: DestructiveGitHandler, repo: Path
    ) -> None:
        decision, _ = _verdict(handler, f"git checkout {_OLD} -- a.txt sub/c.txt", repo)
        assert decision == Decision.ALLOW

    def test_a_dash_c_directory_is_judged_in_that_directory(
        self, handler: DestructiveGitHandler, repo: Path, tmp_path: Path
    ) -> None:
        decision, _ = _verdict(handler, f"git -C {repo} checkout {_OLD} -- gone.txt", tmp_path)
        assert decision == Decision.ALLOW

    def test_the_allowed_command_really_restores_the_file(
        self, handler: DestructiveGitHandler, repo: Path
    ) -> None:
        decision, _ = _verdict(handler, f"git checkout {_OLD} -- gone.txt", repo)
        assert decision == Decision.ALLOW
        _git(repo, "checkout", _OLD, "--", "gone.txt")
        assert (repo / "gone.txt").read_text() == "content of gone.txt\n"


class TestLocalChangesStayDenied:
    def test_a_path_with_unstaged_changes_is_denied(
        self, handler: DestructiveGitHandler, repo: Path
    ) -> None:
        (repo / "a.txt").write_text("my unsaved edit\n")
        _denied(handler, f"git checkout {_OLD} -- a.txt", repo)

    def test_a_path_with_staged_changes_is_denied(
        self, handler: DestructiveGitHandler, repo: Path
    ) -> None:
        (repo / "a.txt").write_text("my staged edit\n")
        _git(repo, "add", "a.txt")
        _denied(handler, f"git checkout {_OLD} -- a.txt", repo)

    def test_one_absent_and_one_modified_path_is_denied(
        self, handler: DestructiveGitHandler, repo: Path
    ) -> None:
        (repo / "a.txt").write_text("my unsaved edit\n")
        _denied(handler, f"git checkout {_OLD} -- gone.txt a.txt", repo)

    def test_an_untracked_path_that_exists_is_denied(
        self, handler: DestructiveGitHandler, repo: Path
    ) -> None:
        (repo / "gone.txt").write_text("new local work\n")
        _denied(handler, f"git checkout {_OLD} -- gone.txt", repo)

    def test_an_unstaged_deletion_of_an_indexed_path_is_denied(
        self, handler: DestructiveGitHandler, repo: Path
    ) -> None:
        (repo / "a.txt").unlink()
        _denied(handler, f"git checkout {_OLD} -- a.txt", repo)

    def test_a_staged_deletion_is_denied(self, handler: DestructiveGitHandler, repo: Path) -> None:
        _git(repo, "rm", "-q", "a.txt")
        _denied(handler, f"git checkout {_OLD} -- a.txt", repo)

    def test_a_directory_holding_a_modified_file_is_denied(
        self, handler: DestructiveGitHandler, repo: Path
    ) -> None:
        (repo / "sub" / "c.txt").write_text("my unsaved edit\n")
        _denied(handler, f"git checkout {_OLD} -- sub", repo)

    def test_a_present_directory_is_denied_even_when_clean(
        self, handler: DestructiveGitHandler, repo: Path
    ) -> None:
        _denied(handler, f"git checkout {_OLD} -- sub", repo)

    def test_a_symlink_path_is_denied(self, handler: DestructiveGitHandler, repo: Path) -> None:
        (repo / "link.txt").symlink_to("a.txt")
        _git(repo, "add", "link.txt")
        _git(repo, "commit", "-q", "-m", "link")
        _denied(handler, "git checkout HEAD~1 -- link.txt", repo)

    def test_a_dangling_symlink_is_denied(self, handler: DestructiveGitHandler, repo: Path) -> None:
        (repo / "gone.txt").symlink_to("nowhere.txt")
        _denied(handler, f"git checkout {_OLD} -- gone.txt", repo)

    def test_a_restore_from_the_index_is_denied(
        self, handler: DestructiveGitHandler, repo: Path
    ) -> None:
        """No commit: `git checkout -- p` restores from the index, which still discards."""
        _denied(handler, "git checkout -- gone.txt", repo)

    def test_a_directory_outside_any_repository_is_denied(
        self, handler: DestructiveGitHandler, tmp_path: Path
    ) -> None:
        outside = tmp_path / "plain"
        outside.mkdir()
        _denied(handler, f"git checkout {_OLD} -- gone.txt", outside)

    def test_an_ignored_path_that_exists_is_denied(
        self, handler: DestructiveGitHandler, repo: Path
    ) -> None:
        (repo / ".gitignore").write_text("gone.txt\n")
        _git(repo, "add", ".gitignore")
        _git(repo, "commit", "-q", "-m", "ignore")
        (repo / "gone.txt").write_text("ignored local work\n")
        _denied(handler, "git checkout HEAD~2 -- gone.txt", repo)

    def test_an_untracked_directory_at_the_path_is_denied(
        self, handler: DestructiveGitHandler, repo: Path
    ) -> None:
        (repo / "gone.txt").mkdir()
        (repo / "gone.txt" / "x").write_text("untracked local work\n")
        _denied(handler, f"git checkout {_OLD} -- gone.txt", repo)

    def test_an_intent_to_add_path_is_denied(
        self, handler: DestructiveGitHandler, repo: Path
    ) -> None:
        (repo / "gone.txt").write_text("intent to add\n")
        _git(repo, "add", "-N", "gone.txt")
        _denied(handler, f"git checkout {_OLD} -- gone.txt", repo)

    def test_a_symlink_pointing_outside_the_repository_is_denied(
        self, handler: DestructiveGitHandler, repo: Path, tmp_path: Path
    ) -> None:
        (tmp_path / "secret.txt").write_text("outside\n")
        (repo / "gone.txt").symlink_to(tmp_path / "secret.txt")
        _denied(handler, f"git checkout {_OLD} -- gone.txt", repo)

    def test_a_submodule_with_local_work_is_denied(
        self, handler: DestructiveGitHandler, repo: Path, tmp_path: Path
    ) -> None:
        source = tmp_path / "module-source"
        _git(tmp_path, "init", "-q", "-b", "main", str(source))
        (source / "f").write_text("module\n")
        _git(source, "add", "f")
        _git(source, "commit", "-q", "-m", "module")
        _git(repo, "-c", "protocol.file.allow=always", "submodule", "add", "-q", str(source), "mod")
        _git(repo, "commit", "-q", "-m", "submodule")
        (repo / "mod" / "f").write_text("local module work\n")
        _denied(handler, "git checkout HEAD -- mod", repo)
        _denied(handler, "git checkout HEAD~1 -- mod", repo)


class TestAParentThatIsNotADirectoryStaysDenied:
    """Second review of PR 293: git removes a FILE where the commit has a directory.

    `d/x` is absent and unindexed, so the path alone looks clean, but restoring it
    first deletes whatever sits at `d`.
    """

    def test_a_tracked_modified_file_at_the_parent_is_denied(
        self, handler: DestructiveGitHandler, repo: Path
    ) -> None:
        (repo / "d").mkdir()
        (repo / "d" / "x").write_text("old x\n")
        _git(repo, "add", "d")
        _git(repo, "commit", "-q", "-m", "dir d")
        _git(repo, "rm", "-q", "-r", "d")
        (repo / "d").write_text("file d\n")
        _git(repo, "add", "d")
        _git(repo, "commit", "-q", "-m", "file d")
        (repo / "d").write_text("my unsaved edit\n")
        _denied(handler, "git checkout HEAD~1 -- d/x", repo)

    def test_a_tracked_clean_file_at_the_parent_is_denied(
        self, handler: DestructiveGitHandler, repo: Path
    ) -> None:
        (repo / "d").mkdir()
        (repo / "d" / "x").write_text("old x\n")
        _git(repo, "add", "d")
        _git(repo, "commit", "-q", "-m", "dir d")
        _git(repo, "rm", "-q", "-r", "d")
        (repo / "d").write_text("file d\n")
        _git(repo, "add", "d")
        _git(repo, "commit", "-q", "-m", "file d")
        _denied(handler, "git checkout HEAD~1 -- d/x", repo)

    def test_an_untracked_file_at_the_parent_is_denied(
        self, handler: DestructiveGitHandler, repo: Path
    ) -> None:
        (repo / "gonedir").write_text("untracked local work\n")
        _denied(handler, f"git checkout {_OLD} -- gonedir/f.txt", repo)

    def test_an_ignored_file_at_the_parent_is_denied(
        self, handler: DestructiveGitHandler, repo: Path
    ) -> None:
        (repo / ".gitignore").write_text("gonedir\n")
        _git(repo, "add", ".gitignore")
        _git(repo, "commit", "-q", "-m", "ignore")
        (repo / "gonedir").write_text("ignored local work\n")
        _denied(handler, "git checkout HEAD~2 -- gonedir/f.txt", repo)

    def test_a_modified_file_at_a_deeper_parent_is_denied(
        self, handler: DestructiveGitHandler, repo: Path
    ) -> None:
        (repo / "e" / "f").mkdir(parents=True)
        (repo / "e" / "f" / "g").write_text("old g\n")
        _git(repo, "add", "e")
        _git(repo, "commit", "-q", "-m", "dir e/f")
        _git(repo, "rm", "-q", "-r", "e/f")
        (repo / "e").mkdir(exist_ok=True)
        (repo / "e" / "f").write_text("file e/f\n")
        _git(repo, "add", "e/f")
        _git(repo, "commit", "-q", "-m", "file e/f")
        (repo / "e" / "f").write_text("my unsaved edit\n")
        _denied(handler, "git checkout HEAD~1 -- e/f/g", repo)

    def test_an_index_entry_at_an_absent_parent_is_denied(
        self, handler: DestructiveGitHandler, repo: Path
    ) -> None:
        """The parent is deleted from the worktree but its file entry is still indexed."""
        (repo / "a.txt").unlink()
        _denied(handler, f"git checkout {_OLD} -- a.txt/x", repo)

    def test_a_symlinked_parent_inside_the_repository_is_denied(
        self, handler: DestructiveGitHandler, repo: Path
    ) -> None:
        (repo / "ln").symlink_to("sub")
        _denied(handler, "git checkout HEAD -- ln/c.txt", repo)

    def test_a_parent_lstat_error_denies(
        self, handler: DestructiveGitHandler, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        real_lstat = Path.lstat

        def refusing(self: Path) -> Any:
            if self.name == "gonedir":
                raise PermissionError("lstat refused")
            return real_lstat(self)

        monkeypatch.setattr(Path, "lstat", refusing)
        _denied(handler, f"git checkout {_OLD} -- gonedir/f.txt", repo)

    def test_a_nested_absent_path_under_a_real_directory_is_allowed(
        self, handler: DestructiveGitHandler, repo: Path
    ) -> None:
        decision, _ = _verdict(handler, f"git checkout {_OLD} -- gonedir/f.txt", repo)
        assert decision == Decision.ALLOW

    def test_an_existing_directory_holding_untracked_files_is_denied(
        self, handler: DestructiveGitHandler, repo: Path
    ) -> None:
        """The reverse shape: the commit has a file where the worktree has a directory."""
        (repo / "gone.txt").mkdir()
        (repo / "gone.txt" / "mine").write_text("untracked local work\n")
        _denied(handler, f"git checkout {_OLD} -- gone.txt", repo)


class TestIndexFlagsThatHideChangesStayDenied:
    """Review of PR 293: `git diff` skips these entries, so a clean diff proves nothing."""

    def test_an_assume_unchanged_edit_is_denied(
        self, handler: DestructiveGitHandler, repo: Path
    ) -> None:
        (repo / "a.txt").write_text("my unsaved edit\n")
        _git(repo, "update-index", "--assume-unchanged", "a.txt")
        _denied(handler, f"git checkout {_OLD} -- a.txt", repo)
        _denied(handler, "git checkout HEAD -- a.txt", repo)

    def test_a_skip_worktree_edit_is_denied(
        self, handler: DestructiveGitHandler, repo: Path
    ) -> None:
        (repo / "a.txt").write_text("my unsaved edit\n")
        _git(repo, "update-index", "--skip-worktree", "a.txt")
        _denied(handler, f"git checkout {_OLD} -- a.txt", repo)
        _denied(handler, "git checkout HEAD -- a.txt", repo)

    def test_an_assume_unchanged_flag_alone_is_denied(
        self, handler: DestructiveGitHandler, repo: Path
    ) -> None:
        """The flag is denied whatever the content: the checkout would clear it."""
        _git(repo, "update-index", "--assume-unchanged", "a.txt")
        _denied(handler, "git checkout HEAD -- a.txt", repo)

    def test_a_sparse_path_outside_the_cone_is_denied(
        self, handler: DestructiveGitHandler, repo: Path
    ) -> None:
        _git(repo, "sparse-checkout", "set", "--no-cone", "/a.txt")
        (repo / "sub").mkdir(exist_ok=True)
        (repo / "sub" / "c.txt").write_text("local work outside the cone\n")
        _denied(handler, f"git checkout {_OLD} -- sub/c.txt", repo)

    def test_a_sparse_path_outside_the_cone_and_absent_is_denied(
        self, handler: DestructiveGitHandler, repo: Path
    ) -> None:
        _git(repo, "sparse-checkout", "set", "--no-cone", "/a.txt")
        _denied(handler, f"git checkout {_OLD} -- sub/c.txt", repo)

    def test_an_unmerged_path_is_denied(self, handler: DestructiveGitHandler, repo: Path) -> None:
        _git(repo, "checkout", "-q", "-b", "other", _OLD)
        (repo / "a.txt").write_text("other side\n")
        _git(repo, "commit", "-q", "-a", "-m", "other")
        _git(repo, "checkout", "-q", "main")
        (repo / "a.txt").write_text("main side\n")
        _git(repo, "commit", "-q", "-a", "-m", "main")
        merge = subprocess.run(
            ["git", *_GIT_IDENTITY, "merge", "-q", "other"], cwd=repo, capture_output=True
        )
        assert merge.returncode != 0
        _denied(handler, "git checkout HEAD -- a.txt", repo)

    def test_an_unparseable_index_listing_denies(
        self, handler: DestructiveGitHandler, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def garbled(cwd: Path, *args: str, **kwargs: Any) -> subprocess.CompletedProcess[str]:
            if "ls-files" in args:
                return subprocess.CompletedProcess(["git", *args], 0, "not a listing\0", "")
            return run_git(cwd, *args, **kwargs)

        monkeypatch.setattr(destructive_git, "run_git", garbled)
        _denied(handler, f"git checkout {_OLD} -- a.txt", repo)


class TestBytesTheDiffCannotSeeStayDenied:
    def test_crlf_endings_normalised_away_by_autocrlf_are_denied(
        self, handler: DestructiveGitHandler, repo: Path
    ) -> None:
        """Review of PR 293: under `core.autocrlf=input` the diff is clean, the bytes are not."""
        _git(repo, "config", "core.autocrlf", "input")
        (repo / "a.txt").write_bytes(b"content of a.txt\r\n")
        _denied(handler, "git checkout HEAD -- a.txt", repo)
        _denied(handler, f"git checkout {_OLD} -- a.txt", repo)

    def test_an_exec_bit_hidden_by_filemode_false_is_denied(
        self, handler: DestructiveGitHandler, repo: Path
    ) -> None:
        _git(repo, "config", "core.fileMode", "false")
        (repo / "a.txt").chmod(0o755)
        _denied(handler, "git checkout HEAD -- a.txt", repo)

    def test_a_hash_object_failure_denies(
        self, handler: DestructiveGitHandler, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def hash_fails(cwd: Path, *args: str, **kwargs: Any) -> subprocess.CompletedProcess[str]:
            if "hash-object" in args:
                return subprocess.CompletedProcess(["git", *args], 128, "", "fatal: broken")
            return run_git(cwd, *args, **kwargs)

        monkeypatch.setattr(destructive_git, "run_git", hash_fails)
        _denied(handler, f"git checkout {_OLD} -- a.txt", repo)


class TestAnUnreadablePathDeniesCleanly:
    def test_a_name_too_long_for_the_filesystem_is_denied_not_raised(
        self, handler: DestructiveGitHandler, repo: Path
    ) -> None:
        """Review of PR 293: `exists()` raised OSError out of handle()."""
        _denied(handler, f"git checkout {_OLD} -- {'x' * 300}", repo)

    def test_a_filesystem_error_on_a_probe_is_denied(
        self, handler: DestructiveGitHandler, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def broken(self: Path) -> bool:
            raise PermissionError("probe refused")

        monkeypatch.setattr(Path, "is_symlink", broken)
        _denied(handler, f"git checkout {_OLD} -- gone.txt", repo)


class TestShapesThisReadingCannotSettleStayDenied:
    @pytest.mark.parametrize(
        "paths",
        [
            ".",
            "'*.txt'",
            "'gone?.txt'",
            "'[g]one.txt'",
            ":/",
            "':(glob)gone*'",
            "':(top)gone.txt'",
            "sub/.",
            "sub/",
            "gonedir/../a.txt",
            "./gone.txt",
            "'gone\\.txt'",
            "$P",
            '"$P"',
            "${P}",
            "$(echo gone.txt)",
            "`echo gone.txt`",
            "../outside.txt",
        ],
    )
    def test_a_path_that_is_not_one_literal_in_repo_name_is_denied(
        self, handler: DestructiveGitHandler, repo: Path, paths: str
    ) -> None:
        _denied(handler, f"git checkout {_OLD} -- {paths}", repo)

    def test_an_absolute_path_outside_the_repository_is_denied(
        self, handler: DestructiveGitHandler, repo: Path, tmp_path: Path
    ) -> None:
        _denied(handler, f"git checkout {_OLD} -- {tmp_path / 'outside.txt'}", repo)

    def test_a_path_through_a_symlinked_directory_is_denied(
        self, handler: DestructiveGitHandler, repo: Path, tmp_path: Path
    ) -> None:
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        (repo / "out").symlink_to(elsewhere)
        _denied(handler, f"git checkout {_OLD} -- out/gone.txt", repo)

    @pytest.mark.parametrize(
        "options",
        ["-f", "--force", "-p", "--patch", "--ours", "--theirs", "-m", "--merge", "-q"],
    )
    def test_an_option_is_denied(
        self, handler: DestructiveGitHandler, repo: Path, options: str
    ) -> None:
        decision, _ = _verdict(handler, f"git checkout {options} {_OLD} -- gone.txt", repo)
        assert decision == Decision.DENY

    @pytest.mark.parametrize(
        "command",
        [
            f"git checkout {_OLD} {_OLD} -- gone.txt",
            "git checkout '$C' -- gone.txt",
            f"git checkout {_OLD} -- gone.txt && git checkout {_OLD} -- a.txt",
            f"git checkout {_OLD} -- gone.txt; git checkout {_OLD} -- a.txt",
            f"git checkout {_OLD} -- gone.txt || git checkout {_OLD} -- a.txt",
            f"git checkout {_OLD} -- gone.txt\ngit checkout {_OLD} -- a.txt",
            f"mv a.txt gone.txt && git checkout {_OLD} -- gone.txt",
            f"cd sub && git checkout {_OLD} -- gone.txt",
            f"echo a.txt | xargs git checkout {_OLD} -- gone.txt",
            f"env git checkout {_OLD} -- gone.txt",
            f"GIT_WORK_TREE=../other git checkout {_OLD} -- gone.txt",
            f"GIT_INDEX_FILE=/tmp/i git checkout {_OLD} -- gone.txt",
            f"git --work-tree=../other checkout {_OLD} -- gone.txt",
            f"git --literal-pathspecs checkout {_OLD} -- gone.txt",
            f"git checkout {_OLD} --pathspec-from-file=list.txt -- gone.txt",
            f"bash -c 'git checkout {_OLD} -- gone.txt; git checkout {_OLD} -- a.txt'",
        ],
    )
    def test_a_command_that_does_more_than_one_plain_checkout_is_denied(
        self, handler: DestructiveGitHandler, repo: Path, command: str
    ) -> None:
        """`a.txt` holds unsaved work in every case, so a denial is the only safe verdict."""
        (repo / "a.txt").write_text("my unsaved edit\n")
        decision, _ = _verdict(handler, command, repo)
        assert decision == Decision.DENY

    def test_a_checkout_beside_a_hard_rule_is_denied(
        self, handler: DestructiveGitHandler, repo: Path
    ) -> None:
        decision, rule = _verdict(
            handler, f"git checkout {_OLD} -- gone.txt && git reset --hard", repo
        )
        assert (decision, rule) == (Decision.DENY, RuleID.GIT_RESET_HARD)

    def test_a_checkout_beside_an_empty_file_restore_is_denied(
        self, handler: DestructiveGitHandler, repo: Path
    ) -> None:
        (repo / "a.txt").write_text("")
        decision, _ = _verdict(
            handler, f"git restore a.txt && git checkout {_OLD} -- gone.txt", repo
        )
        assert decision == Decision.DENY


class TestTheProofFailsClosed:
    def test_a_checkout_without_the_double_dash_gets_the_same_proof(self, repo: Path) -> None:
        """N764: git reads `X p` as `X -- p` when X is a commit and no path, so it is judged."""
        (run,) = git_invocations(f"git checkout {_OLD} gone.txt")
        assert _checkout_restore_loss(run, repo) is None
        (repo / "a.txt").write_text("my unsaved edit\n")
        (run,) = git_invocations(f"git checkout {_OLD} a.txt")
        assert _checkout_restore_loss(run, repo) is not None

    def test_a_git_failure_denies(
        self, handler: DestructiveGitHandler, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def failing(cwd: Path, *args: str, **kwargs: Any) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(["git", *args], 128, "", "fatal: broken")

        monkeypatch.setattr(destructive_git, "run_git", failing)
        _denied(handler, f"git checkout {_OLD} -- gone.txt", repo)

    def test_a_diff_that_reports_an_error_denies(
        self, handler: DestructiveGitHandler, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        real = run_git

        def diff_fails(cwd: Path, *args: str, **kwargs: Any) -> subprocess.CompletedProcess[str]:
            if "diff" in args:
                return subprocess.CompletedProcess(["git", *args], 128, "", "fatal: broken")
            return real(cwd, *args, **kwargs)

        monkeypatch.setattr(destructive_git, "run_git", diff_fails)
        _denied(handler, f"git checkout {_OLD} -- gone.txt", repo)

    def test_an_exhausted_deadline_denies(
        self, handler: DestructiveGitHandler, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(destructive_git, "_CHECKOUT_PROOF_BUDGET", 0.0)
        _denied(handler, f"git checkout {_OLD} -- gone.txt", repo)

    def test_the_denial_names_the_reason(self, handler: DestructiveGitHandler, repo: Path) -> None:
        (repo / "a.txt").write_text("my unsaved edit\n")
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": f"git checkout {_OLD} -- a.txt"},
            "cwd": str(repo),
        }
        result = handler.handle(hook_input)
        assert "`a.txt`" in (result.reason or "")
