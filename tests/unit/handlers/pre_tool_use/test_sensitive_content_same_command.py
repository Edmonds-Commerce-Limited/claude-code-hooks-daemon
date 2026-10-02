"""sensitive_content judges what a commit records when the SAME command stages or commits more.

Ledger 00474 N246 (and 00466 N61): ``git add leak.txt && git commit -m x`` records
``leak.txt``, but the gate asked git what the index holds BEFORE the add ran.
N307: only the first of two ``git commit``s was judged. N306: a ``cd`` chain that
may land in several directories was judged only from the hook directory and the
last move.

Every row runs real git in a temporary repository, so each verdict is checked
against what the command would really record.
"""

import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.data_layer import reset_data_layer
from claude_code_hooks_daemon.handlers.pre_tool_use.sensitive_content import (
    SensitiveContentHandler,
)
from claude_code_hooks_daemon.utils import secret_redaction as sr
from claude_code_hooks_daemon.utils.git_repo import run_git

_TERM = "alpha-term"
_STAGING_RUN_GIT = "claude_code_hooks_daemon.utils.staging_simulation.run_git"


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(  # nosec B603 B607 - trusted git binary, fixed argv, test fixture only
        ["git", "-C", str(repo), *args],
        capture_output=True,
        check=True,
        text=True,
        timeout=Timeout.GIT_CONTEXT,
    )
    return result.stdout


@pytest.fixture(autouse=True)
def _reset_caches() -> Iterator[None]:
    reset_data_layer()
    sr.reset_terms_cache()
    sr.reset_active_path_cache()
    yield
    reset_data_layer()
    sr.reset_terms_cache()
    sr.reset_active_path_cache()


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """A repository of clean tracked files, an ignore rule and a nested directory."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "T")
    _git(root, "config", "commit.gpgsign", "false")
    for name in ("a.txt", "b.txt", "f.txt", "g.txt", "sub/f.txt", "sub/g.txt"):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("clean\n")
    (root / ".gitignore").write_text("ignored.txt\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "initial")
    return root


@pytest.fixture()
def handler(tmp_path: Path) -> SensitiveContentHandler:
    wordlist = tmp_path / "wordlist.txt"
    wordlist.write_text(f"{_TERM}\n")
    gate = SensitiveContentHandler()
    gate._secret_word_list_path = wordlist.name
    gate._project_root_override = wordlist.parent
    return gate


def _decision(handler: SensitiveContentHandler, cwd: Path, command: str) -> Decision:
    hook_input: dict[str, Any] = {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": str(cwd),
    }
    return handler.handle(hook_input).decision


class TestACommandThatStagesThenCommits:
    """N246: the commit records what the add stages, so that is what is judged."""

    @pytest.mark.parametrize(
        "command",
        [
            "git add leak.txt && git commit -q -m x",
            "git add leak.txt; git commit -q -m x",
            "git add a.txt leak.txt && git commit -q -m x",
            "git add -A && git commit -q -m x",
            "git add --all && git commit -q -m x",
            "git add . && git commit -q -m x",
            "git add -- leak.txt && git commit -q -m x",
            "git add leak.txt && git commit -q -m x leak.txt",
            "git add leak.txt && git commit -q -a -m x",
            "git add 'leak*' && git commit -q -m x",
        ],
    )
    def test_an_untracked_file_the_add_stages_is_judged(
        self, repo: Path, handler: SensitiveContentHandler, command: str
    ) -> None:
        (repo / "leak.txt").write_text(f"{_TERM}\n")

        assert _decision(handler, repo, command) == Decision.DENY

    @pytest.mark.parametrize(
        "command",
        [
            "git add -u && git commit -q -m x",
            "git add --update && git commit -q -m x",
            "git add a.txt && git commit -q -m x",
            "git add a.txt; git commit -q -m x",
            "git add -u a.txt && git commit -q -m x",
            "git commit -q -m x; git add leak.txt",
            "git add a.txt && git commit -q -m x a.txt",
        ],
    )
    def test_an_untracked_file_the_add_does_not_stage_is_not_judged(
        self, repo: Path, handler: SensitiveContentHandler, command: str
    ) -> None:
        (repo / "leak.txt").write_text(f"{_TERM}\n")
        (repo / "a.txt").write_text("fine\n")

        assert _decision(handler, repo, command) == Decision.ALLOW

    @pytest.mark.parametrize(
        "command",
        [
            "git add -u && git commit -q -m x",
            "git add a.txt && git commit -q -m x",
            "git add . && git commit -q -m x",
            "git add -A && git commit -q -m x",
        ],
    )
    def test_a_tracked_edit_the_add_stages_is_judged(
        self, repo: Path, handler: SensitiveContentHandler, command: str
    ) -> None:
        (repo / "a.txt").write_text(f"{_TERM}\n")

        assert _decision(handler, repo, command) == Decision.DENY

    def test_an_ignored_file_is_judged_only_when_the_add_forces_it(
        self, repo: Path, handler: SensitiveContentHandler
    ) -> None:
        (repo / "ignored.txt").write_text(f"{_TERM}\n")

        assert _decision(handler, repo, "git add -f ignored.txt && git commit -q -m x") == (
            Decision.DENY
        )
        assert _decision(handler, repo, "git add ignored.txt; git commit -q -m x") == (
            Decision.ALLOW
        )
        assert _decision(handler, repo, "git add -A && git commit -q -m x") == Decision.ALLOW

    def test_a_clean_add_then_commit_is_allowed(
        self, repo: Path, handler: SensitiveContentHandler
    ) -> None:
        (repo / "new.txt").write_text("fine\n")

        assert _decision(handler, repo, "git add new.txt && git commit -q -m x") == Decision.ALLOW

    def test_the_add_is_read_from_the_directory_it_runs_in(
        self, repo: Path, handler: SensitiveContentHandler
    ) -> None:
        (repo / "sub" / "leak.txt").write_text(f"{_TERM}\n")

        assert _decision(handler, repo, "cd sub && git add leak.txt && git commit -q -m x") == (
            Decision.DENY
        )
        assert _decision(handler, repo, "git -C sub add leak.txt && git commit -q -m x") == (
            Decision.DENY
        )
        assert _decision(handler, repo, "git add sub/leak.txt && git commit -q -m x") == (
            Decision.DENY
        )

    def test_an_add_that_names_a_path_in_the_other_directory_does_not_stage_this_one(
        self, repo: Path, handler: SensitiveContentHandler
    ) -> None:
        (repo / "leak.txt").write_text(f"{_TERM}\n")
        (repo / "sub" / "leak.txt").write_text("fine\n")

        assert _decision(handler, repo, "cd sub && git add leak.txt && git commit -q -m x") == (
            Decision.ALLOW
        )

    @pytest.mark.parametrize(
        "command",
        [
            "F=leak.txt; git add $F && git commit -q -m x",
            "git add $(echo leak.txt) && git commit -q -m x",
            "git add {leak,zz}.txt && git commit -q -m x",
            "git add -p && git commit -q -m x",
            "git add --pathspec-from-file=list && git commit -q -m x",
        ],
    )
    def test_an_add_whose_scope_cannot_be_read_is_judged_as_staging_everything(
        self, repo: Path, handler: SensitiveContentHandler, command: str
    ) -> None:
        (repo / "leak.txt").write_text(f"{_TERM}\n")

        assert _decision(handler, repo, command) == Decision.DENY

    def test_an_add_of_a_path_git_rejects_stages_nothing(
        self, repo: Path, handler: SensitiveContentHandler
    ) -> None:
        (repo / "leak.txt").write_text(f"{_TERM}\n")

        assert _decision(handler, repo, "git add nosuch.txt; git commit -q -m x") == Decision.ALLOW

    def test_the_real_index_and_object_store_are_left_untouched(
        self, repo: Path, handler: SensitiveContentHandler
    ) -> None:
        (repo / "leak.txt").write_text("a file the simulated add would hash\n")
        index_before = (repo / ".git" / "index").read_bytes()
        objects_before = _git(repo, "count-objects", "-v")

        _decision(handler, repo, "git add -A && git commit -q -m x")

        assert (repo / ".git" / "index").read_bytes() == index_before
        assert _git(repo, "count-objects", "-v") == objects_before
        assert _git(repo, "diff", "--cached", "--name-only") == ""

    def test_an_add_in_another_repository_stages_nothing_here(
        self, repo: Path, handler: SensitiveContentHandler, tmp_path: Path
    ) -> None:
        other = tmp_path / "other"
        other.mkdir()
        _git(other, "init", "-q")
        (other / "leak.txt").write_text(f"{_TERM}\n")

        assert _decision(handler, repo, f"git -C {other} add leak.txt; git commit -q -m x") == (
            Decision.ALLOW
        )


class TestEveryCommitInTheCommandIsJudged:
    """N307: a second ``git commit`` has its own pathspecs, directory and ``-a``."""

    def test_the_second_commits_pathspec_is_judged(
        self, repo: Path, handler: SensitiveContentHandler
    ) -> None:
        (repo / "b.txt").write_text(f"{_TERM}\n")

        command = "git commit -q -m a a.txt; git commit -q -m b b.txt"

        assert _decision(handler, repo, command) == Decision.DENY

    def test_the_second_commit_may_commit_the_whole_working_tree(
        self, repo: Path, handler: SensitiveContentHandler
    ) -> None:
        (repo / "b.txt").write_text(f"{_TERM}\n")

        command = "git commit -q -m a a.txt && git commit -q -a -m b"

        assert _decision(handler, repo, command) == Decision.DENY

    def test_each_commit_reads_its_pathspec_from_its_own_directory(
        self, repo: Path, handler: SensitiveContentHandler
    ) -> None:
        (repo / "g.txt").write_text(f"{_TERM}\n")

        command = "cd sub && git commit -q -m x f.txt; cd .. && git commit -q -m y g.txt"

        assert _decision(handler, repo, command) == Decision.DENY

    def test_a_file_neither_commit_names_is_not_judged(
        self, repo: Path, handler: SensitiveContentHandler
    ) -> None:
        (repo / "f.txt").write_text(f"{_TERM}\n")

        command = "cd sub && git commit -q -m x f.txt; cd .. && git commit -q -m y g.txt"

        assert _decision(handler, repo, command) == Decision.ALLOW

    def test_a_clean_pair_of_commits_is_allowed(
        self, repo: Path, handler: SensitiveContentHandler
    ) -> None:
        (repo / "a.txt").write_text("fine\n")
        (repo / "b.txt").write_text("fine\n")

        command = "git commit -q -m a a.txt && git commit -q -m b b.txt"

        assert _decision(handler, repo, command) == Decision.ALLOW

    def test_an_add_between_two_commits_is_judged(
        self, repo: Path, handler: SensitiveContentHandler
    ) -> None:
        (repo / "leak.txt").write_text(f"{_TERM}\n")

        command = "git commit -q -m a a.txt; git add leak.txt; git commit -q -m b"

        assert _decision(handler, repo, command) == Decision.DENY


class TestACdThatMayLandInSeveralDirectories:
    """N306: every directory a ``cd`` in the chain could land in is judged."""

    @pytest.mark.parametrize(
        "command",
        [
            "cd sub || cd x; git commit -q -m x f.txt",
            "cd x || cd sub; git commit -q -m x f.txt",
            "cd x || cd sub && git commit -q -m x f.txt",
            "cd sub || cd x && git commit -q -m x f.txt",
        ],
    )
    def test_the_directory_of_every_cd_is_judged(
        self, repo: Path, handler: SensitiveContentHandler, command: str
    ) -> None:
        (repo / "x").mkdir()
        (repo / "x" / "f.txt").write_text("fine\n")
        (repo / "sub" / "f.txt").write_text(f"{_TERM}\n")

        assert _decision(handler, repo, command) == Decision.DENY

    def test_the_hooks_directory_is_still_judged(
        self, repo: Path, handler: SensitiveContentHandler
    ) -> None:
        (repo / "x").mkdir()
        (repo / "x" / "f.txt").write_text("fine\n")
        (repo / "f.txt").write_text(f"{_TERM}\n")

        assert _decision(handler, repo, "cd sub || cd x; git commit -q -m x f.txt") == (
            Decision.DENY
        )

    def test_a_term_in_a_file_no_chain_can_reach_is_not_judged(
        self, repo: Path, handler: SensitiveContentHandler
    ) -> None:
        (repo / "x").mkdir()
        (repo / "x" / "f.txt").write_text("fine\n")
        (repo / "sub" / "g.txt").write_text(f"{_TERM}\n")

        assert _decision(handler, repo, "cd sub || cd x; git commit -q -m x f.txt") == (
            Decision.ALLOW
        )

    def test_a_certain_move_is_still_read_only_from_where_it_lands(
        self, repo: Path, handler: SensitiveContentHandler
    ) -> None:
        (repo / "f.txt").write_text(f"{_TERM}\n")

        assert _decision(handler, repo, "cd sub && git commit -q -m x f.txt") == Decision.ALLOW


class TestAStagingThatCannotBeSimulatedIsDenied:
    """A simulation that did not finish is not a clean index: the gate says so."""

    @staticmethod
    def _fail_every_add() -> Any:
        real = run_git

        def run(directory: Path, *args: str, **kwargs: Any) -> "subprocess.CompletedProcess[str]":
            if "add" in args[:3]:
                return subprocess.CompletedProcess(["git"], 127, "", "timed out after 5s")
            return real(directory, *args, **kwargs)

        return run

    def test_handle_denies_and_tells_the_user_to_stage_first(
        self, repo: Path, handler: SensitiveContentHandler
    ) -> None:
        (repo / "leak.txt").write_text(f"{_TERM}\n")
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "git add leak.txt && git commit -q -m x"},
            "cwd": str(repo),
        }

        with patch(_STAGING_RUN_GIT, side_effect=self._fail_every_add()):
            result = handler.handle(hook_input)

        assert result.decision == Decision.DENY
        assert "separate command" in (result.reason or "")

    def test_matches_selects_the_command_so_the_chain_reaches_handle(
        self, repo: Path, handler: SensitiveContentHandler
    ) -> None:
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "git add leak.txt && git commit -q -m x"},
            "cwd": str(repo),
        }

        with patch(_STAGING_RUN_GIT, side_effect=self._fail_every_add()):
            assert handler.matches(hook_input) is True
