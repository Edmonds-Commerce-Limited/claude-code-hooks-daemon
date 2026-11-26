"""A restore of a tracked file whose working copy is EMPTY loses nothing (Plan 00586 Task 1.6, F).

A host reboot left a tracked file at zero bytes. `git restore <file>` puts the committed
content back, and discarding an empty working copy discards no content, yet the guard denied
it and only a human could run the restore. The allowance is narrow: every named path must be
a tracked, regular, zero-byte file; anything with content, any shape this reading cannot
settle, and any restore that can touch more than the named files stays denied.
"""

import subprocess
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use.destructive_git import DestructiveGitHandler

_GIT_IDENTITY = (
    "-c",
    "user.name=Test",
    "-c",
    "user.email=test@example.invalid",
    "-c",
    "commit.gpgsign=false",
)


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *_GIT_IDENTITY, *args], cwd=cwd, capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Tracked `a.txt` and `b.txt` committed with content; `sub/c.txt` too."""
    repo = tmp_path / "repo"
    _git(tmp_path, "init", "-b", "main", str(repo))
    (repo / "sub").mkdir()
    for name in ("a.txt", "b.txt", "sub/c.txt"):
        (repo / name).write_text(f"content of {name}\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "base")
    return repo


@pytest.fixture
def handler() -> DestructiveGitHandler:
    return DestructiveGitHandler()


def _input(command: str, cwd: Path) -> dict[str, Any]:
    return {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(cwd)}


def _verdict(handler: DestructiveGitHandler, command: str, cwd: Path) -> tuple[Decision, str]:
    hook_input = _input(command, cwd)
    assert handler.matches(hook_input) is True
    result = handler.handle(hook_input)
    return result.decision, result.rule or ""


def _empty(repo: Path, name: str) -> None:
    (repo / name).write_text("")


class TestAnEmptyWorkingCopyIsRestorable:
    def test_a_zero_byte_tracked_file_is_allowed(
        self, handler: DestructiveGitHandler, repo: Path
    ) -> None:
        _empty(repo, "a.txt")
        decision, _ = _verdict(handler, "git restore a.txt", repo)
        assert decision == Decision.ALLOW

    def test_every_named_file_empty_is_allowed(
        self, handler: DestructiveGitHandler, repo: Path
    ) -> None:
        _empty(repo, "a.txt")
        _empty(repo, "sub/c.txt")
        decision, _ = _verdict(handler, "git restore a.txt sub/c.txt", repo)
        assert decision == Decision.ALLOW

    def test_the_double_dash_spelling_is_allowed(
        self, handler: DestructiveGitHandler, repo: Path
    ) -> None:
        _empty(repo, "a.txt")
        decision, _ = _verdict(handler, "git restore -- a.txt", repo)
        assert decision == Decision.ALLOW

    def test_a_dash_c_directory_is_judged_in_that_directory(
        self, handler: DestructiveGitHandler, repo: Path, tmp_path: Path
    ) -> None:
        _empty(repo, "a.txt")
        decision, _ = _verdict(handler, f"git -C {repo} restore a.txt", tmp_path)
        assert decision == Decision.ALLOW


class TestAnythingWithContentStaysDenied:
    def test_a_modified_non_empty_file_is_denied(
        self, handler: DestructiveGitHandler, repo: Path
    ) -> None:
        (repo / "a.txt").write_text("my unsaved edit\n")
        decision, rule = _verdict(handler, "git restore a.txt", repo)
        assert (decision, rule) == (Decision.DENY, RuleID.GIT_RESTORE)

    def test_one_empty_and_one_non_empty_file_is_denied(
        self, handler: DestructiveGitHandler, repo: Path
    ) -> None:
        _empty(repo, "a.txt")
        (repo / "b.txt").write_text("my unsaved edit\n")
        decision, rule = _verdict(handler, "git restore a.txt b.txt", repo)
        assert (decision, rule) == (Decision.DENY, RuleID.GIT_RESTORE)

    def test_an_untouched_file_is_denied_as_before(
        self, handler: DestructiveGitHandler, repo: Path
    ) -> None:
        decision, _ = _verdict(handler, "git restore a.txt", repo)
        assert decision == Decision.DENY

    def test_a_missing_file_is_denied(self, handler: DestructiveGitHandler, repo: Path) -> None:
        (repo / "a.txt").unlink()
        decision, _ = _verdict(handler, "git restore a.txt", repo)
        assert decision == Decision.DENY

    def test_an_empty_untracked_file_is_denied(
        self, handler: DestructiveGitHandler, repo: Path
    ) -> None:
        _empty(repo, "new.txt")
        decision, _ = _verdict(handler, "git restore new.txt", repo)
        assert decision == Decision.DENY


class TestShapesThatReachBeyondTheNamedFilesStayDenied:
    @pytest.mark.parametrize(
        "command",
        [
            "git restore .",
            "git restore sub",
            "git restore '*.txt'",
            "git restore :/",
            "git restore --source=HEAD~1 a.txt",
            "git restore -p a.txt",
            "git restore --pathspec-from-file=list.txt",
            "git restore $(echo a.txt)",
        ],
    )
    def test_is_denied_even_when_the_named_file_is_empty(
        self, handler: DestructiveGitHandler, repo: Path, command: str
    ) -> None:
        _empty(repo, "a.txt")
        decision, _ = _verdict(handler, command, repo)
        assert decision == Decision.DENY

    @pytest.mark.parametrize(
        "command",
        [
            "bash <<'EOF'\ngit restore b.txt\nEOF",
            "echo 'git restore b.txt' | bash",
            "echo b.txt | xargs git restore a.txt",
            "mv b.txt a.txt && git restore a.txt",
            "export GIT_WORK_TREE=../other; git restore a.txt",
            "GIT_WORK_TREE=../other git restore a.txt",
            "git --work-tree=../other restore a.txt",
            "env git restore a.txt",
            "git restore a.txt; git checkout -- b.txt",
        ],
    )
    def test_a_command_that_does_more_than_restore_is_denied(
        self, handler: DestructiveGitHandler, repo: Path, command: str
    ) -> None:
        """Review of PR 276: each of these was allowed while ``a.txt`` was empty.

        ``b.txt`` holds unsaved work in every case, so a denial is the only safe verdict.
        """
        _empty(repo, "a.txt")
        (repo / "b.txt").write_text("my unsaved edit\n")
        decision, _ = _verdict(handler, command, repo)
        assert decision == Decision.DENY

    def test_a_cd_then_restore_of_an_empty_file_is_allowed(
        self, handler: DestructiveGitHandler, repo: Path
    ) -> None:
        _empty(repo, "sub/c.txt")
        decision, _ = _verdict(handler, "cd sub && git restore c.txt", repo)
        assert decision == Decision.ALLOW

    def test_two_chained_restores_of_empty_files_are_allowed(
        self, handler: DestructiveGitHandler, repo: Path
    ) -> None:
        _empty(repo, "a.txt")
        _empty(repo, "b.txt")
        decision, _ = _verdict(handler, "git restore a.txt && git restore b.txt", repo)
        assert decision == Decision.ALLOW

    def test_a_symlink_to_an_empty_file_is_denied(
        self, handler: DestructiveGitHandler, repo: Path
    ) -> None:
        _empty(repo, "target.txt")
        (repo / "a.txt").unlink()
        (repo / "a.txt").symlink_to("target.txt")
        decision, _ = _verdict(handler, "git restore a.txt", repo)
        assert decision == Decision.DENY

    def test_an_empty_file_beside_a_hard_rule_in_one_command_is_denied(
        self, handler: DestructiveGitHandler, repo: Path
    ) -> None:
        _empty(repo, "a.txt")
        decision, _ = _verdict(handler, "git restore a.txt && git reset --hard", repo)
        assert decision == Decision.DENY
