"""Ledger 00474 N246: the index a command's own ``git add`` leaves, read without running it.

``simulated_staging`` runs the add against a COPY of the index and a scratch
object directory, so what a commit gate asks git afterwards (with the returned
environment) is what the commit will record, while the real repository is left
exactly as it was.
"""

import os
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.utils import staging_simulation as staging_module
from claude_code_hooks_daemon.utils.git_commit_parsing import read_commit_form
from claude_code_hooks_daemon.utils.git_repo import run_git
from claude_code_hooks_daemon.utils.staging_simulation import simulated_staging


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(  # nosec B603 B607 - trusted git binary, fixed argv, test fixture only
        ["git", "-C", str(repo), *args],
        capture_output=True,
        check=True,
        text=True,
        timeout=Timeout.GIT_CONTEXT,
    )
    return result.stdout


def _write(root: Path, name: str, text: str) -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "T")
    _git(root, "config", "commit.gpgsign", "false")
    _write(root, "a.txt", "clean\n")
    _write(root, "sub/f.txt", "clean\n")
    _write(root, ".gitignore", "ignored.txt\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "initial")
    _write(root, "leak.txt", "new\n")
    return root


def _staged(repo: Path, env: dict[str, str] | None) -> set[str]:
    result = run_git(repo, "diff", "--cached", "--name-only", "-z", env=env)
    return {path for path in result.stdout.split("\0") if path}


class TestNothingToSimulate:
    @pytest.mark.parametrize(
        "command",
        [
            "git commit -m x",
            "git commit -m x; git add leak.txt",
            "echo hi",
        ],
    )
    def test_a_command_with_no_add_before_its_commit_yields_no_environment(
        self, repo: Path, command: str
    ) -> None:
        with simulated_staging(read_commit_form(command), repo, repo) as env:
            assert env is None

    def test_a_dry_run_add_stages_nothing(self, repo: Path) -> None:
        reading = read_commit_form("git add -n leak.txt && git commit -m x")

        with simulated_staging(reading, repo, repo) as env:
            assert _staged(repo, env) == set()


class TestTheAddIsAppliedToACopy:
    @pytest.mark.parametrize(
        ("command", "expected"),
        [
            ("git add leak.txt && git commit -m x", {"leak.txt"}),
            ("git add -- leak.txt && git commit -m x", {"leak.txt"}),
            ("git add -A && git commit -m x", {"leak.txt"}),
            ("git add . && git commit -m x", {"leak.txt"}),
            ("git add 'leak*' && git commit -m x", {"leak.txt"}),
            ("git add a.txt && git commit -m x", set()),
            ("git add -u && git commit -m x", set()),
            ("cd sub && git add f.txt && git commit -m x", set()),
        ],
    )
    def test_the_environment_shows_what_the_add_stages(
        self, repo: Path, command: str, expected: set[str]
    ) -> None:
        with simulated_staging(read_commit_form(command), repo, repo) as env:
            assert env is not None
            assert _staged(repo, env) == expected

    def test_a_tracked_edit_is_staged_by_update(self, repo: Path) -> None:
        _write(repo, "a.txt", "edited\n")
        reading = read_commit_form("git add -u && git commit -m x")

        with simulated_staging(reading, repo, repo) as env:
            assert _staged(repo, env) == {"a.txt"}

    def test_a_forced_add_stages_an_ignored_file(self, repo: Path) -> None:
        _write(repo, "ignored.txt", "x\n")

        forced = read_commit_form("git add -f ignored.txt && git commit -m x")
        plain = read_commit_form("git add ignored.txt; git commit -m x")
        with simulated_staging(forced, repo, repo) as env:
            assert _staged(repo, env) == {"ignored.txt"}
        with simulated_staging(plain, repo, repo) as env:
            assert _staged(repo, env) == set()

    @pytest.mark.parametrize(
        "command",
        [
            "cd sub && git add leak.txt && git commit -m x",
            "git -C sub add leak.txt && git commit -m x",
        ],
    )
    def test_an_add_runs_where_the_command_moves_to(self, repo: Path, command: str) -> None:
        _write(repo, "sub/leak.txt", "new\n")

        with simulated_staging(read_commit_form(command), repo, repo) as env:
            assert _staged(repo, env) == {"sub/leak.txt"}

    def test_every_directory_an_uncertain_cd_may_land_in_is_tried(self, repo: Path) -> None:
        _write(repo, "sub/leak.txt", "new\n")
        reading = read_commit_form("cd sub || cd x; git add leak.txt; git commit -m x")

        with simulated_staging(reading, repo, repo) as env:
            assert _staged(repo, env) == {"leak.txt", "sub/leak.txt"}

    def test_the_real_repository_is_not_touched(self, repo: Path) -> None:
        index_before = (repo / ".git" / "index").read_bytes()
        objects_before = _git(repo, "count-objects", "-v")
        reading = read_commit_form("git add -A && git commit -m x")

        with simulated_staging(reading, repo, repo) as env:
            assert _staged(repo, env) == {"leak.txt"}

        assert (repo / ".git" / "index").read_bytes() == index_before
        assert _git(repo, "count-objects", "-v") == objects_before
        assert _git(repo, "diff", "--cached", "--name-only") == ""

    def test_the_scratch_files_are_removed_afterwards(self, repo: Path) -> None:
        reading = read_commit_form("git add -A && git commit -m x")

        with simulated_staging(reading, repo, repo) as env:
            assert env is not None
            scratch = Path(env["GIT_INDEX_FILE"]).parent
            assert scratch.is_dir()

        assert not scratch.exists()

    def test_a_staged_blob_is_readable_through_the_environment(self, repo: Path) -> None:
        reading = read_commit_form("git add -A && git commit -m x")

        with simulated_staging(reading, repo, repo) as env:
            shown = run_git(repo, "show", ":leak.txt", env=env)

        assert shown.stdout == "new\n"

    def test_a_repository_with_no_commit_and_no_index_is_simulated(self, tmp_path: Path) -> None:
        fresh = tmp_path / "fresh"
        fresh.mkdir()
        _git(fresh, "init", "-q")
        _write(fresh, "leak.txt", "new\n")
        reading = read_commit_form("git add . && git commit -m x")

        with simulated_staging(reading, fresh, fresh) as env:
            assert _staged(fresh, env) == {"leak.txt"}

    def test_a_linked_worktree_keeps_its_own_index(self, repo: Path, tmp_path: Path) -> None:
        linked = tmp_path / "linked"
        _git(repo, "worktree", "add", "-q", str(linked), "-b", "side")
        _write(linked, "leak.txt", "new\n")
        reading = read_commit_form("git add leak.txt && git commit -m x")

        with simulated_staging(reading, linked, linked) as env:
            assert _staged(linked, env) == {"leak.txt"}
        assert _git(linked, "diff", "--cached", "--name-only") == ""


class TestAnAddThatCannotBeReadStagesEverything:
    @pytest.mark.parametrize(
        "command",
        [
            "F=leak.txt; git add $F && git commit -m x",
            "git add $(echo leak.txt) && git commit -m x",
            "git add {leak,zz}.txt && git commit -m x",
            "git add -p && git commit -m x",
            "git add --pathspec-from-file=list && git commit -m x",
            "git add --chmod=+x leak.txt && git commit -m x",
            "cd - && git add leak.txt && git commit -m x",
        ],
    )
    def test_the_whole_working_tree_is_taken_as_the_add(self, repo: Path, command: str) -> None:
        with simulated_staging(read_commit_form(command), repo, repo) as env:
            assert _staged(repo, env) == {"leak.txt"}


class TestAnAddThatGitRejects:
    def test_a_pathspec_that_matches_nothing_stages_nothing(self, repo: Path) -> None:
        reading = read_commit_form("git add nosuch.txt; git commit -m x")

        with simulated_staging(reading, repo, repo) as env:
            assert _staged(repo, env) == set()

    def test_an_ignored_path_without_force_stages_nothing(self, repo: Path) -> None:
        _write(repo, "ignored.txt", "x\n")
        reading = read_commit_form("git add ignored.txt; git commit -m x")

        with simulated_staging(reading, repo, repo) as env:
            assert _staged(repo, env) == set()


class TestAnAddInAnotherRepository:
    def test_it_stages_nothing_here(self, repo: Path, tmp_path: Path) -> None:
        other = tmp_path / "other"
        other.mkdir()
        _git(other, "init", "-q")
        _write(other, "leak.txt", "new\n")
        reading = read_commit_form(f"git -C {other} add leak.txt; git commit -m x")

        with simulated_staging(reading, repo, repo) as env:
            assert _staged(repo, env) == set()


def test_the_process_environment_is_not_changed(repo: Path) -> None:
    before = dict(os.environ)

    with simulated_staging(read_commit_form("git add -A && git commit -m x"), repo, repo):
        pass

    assert dict(os.environ) == before


class TestWhenGitCannotAnswer:
    def test_a_directory_that_is_not_a_repository_yields_no_environment(
        self, tmp_path: Path
    ) -> None:
        reading = read_commit_form("git add -A && git commit -m x")

        with simulated_staging(reading, tmp_path, tmp_path) as env:
            assert env is None

    def test_an_add_that_fails_for_another_reason_takes_every_change(self, repo: Path) -> None:
        refused = subprocess.CompletedProcess(["git"], 1, "", "fatal: unable to index file")
        accepted = subprocess.CompletedProcess(["git"], 0, "", "")
        reading = read_commit_form("git add leak.txt && git commit -m x")

        with patch.object(staging_module, "run_git") as spy:
            spy.side_effect = _fail_the_first_add(refused, accepted)
            with simulated_staging(reading, repo, repo) as env:
                assert env is not None

        added = [call.args[1:] for call in spy.call_args_list if call.args[1] == "add"]
        assert added == [("add", "leak.txt"), ("add", "-A")]

    def test_an_add_everything_that_fails_is_reported_not_raised(
        self, repo: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        refused = subprocess.CompletedProcess(["git"], 1, "", "fatal: unable to index file")
        reading = read_commit_form("F=leak.txt; git add $F && git commit -m x")

        with patch.object(staging_module, "run_git") as spy:
            spy.side_effect = _fail_every_add(refused)
            with caplog.at_level("WARNING"), simulated_staging(reading, repo, repo) as env:
                assert env is not None

        assert "add -A failed" in caplog.text


def _fail_the_first_add(
    refused: "subprocess.CompletedProcess[str]", accepted: "subprocess.CompletedProcess[str]"
) -> Callable[..., "subprocess.CompletedProcess[str]"]:
    answers = iter([refused, accepted])

    def run(directory: Path, *args: str, **kwargs: Any) -> "subprocess.CompletedProcess[str]":
        if args and args[0] == "add":
            return next(answers)
        return run_git(directory, *args, **kwargs)

    return run


def _fail_every_add(
    refused: "subprocess.CompletedProcess[str]",
) -> Callable[..., "subprocess.CompletedProcess[str]"]:
    def run(directory: Path, *args: str, **kwargs: Any) -> "subprocess.CompletedProcess[str]":
        if args and args[0] == "add":
            return refused
        return run_git(directory, *args, **kwargs)

    return run
