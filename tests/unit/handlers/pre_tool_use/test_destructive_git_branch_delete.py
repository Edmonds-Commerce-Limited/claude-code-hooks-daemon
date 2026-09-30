"""destructive_git allows a forced branch delete only when a remote holds the tip (N267).

Clearing up a worktree branch must not need a human, and it cannot lose work
when every named branch's tip is already reachable from a remote-tracking ref.
Anything the check cannot establish -- an unpushed branch, an unknown one, an
unresolvable directory, a git failure -- is denied. These tests use real
throwaway repositories and a real bare remote.
"""

import subprocess
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use import destructive_git
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
        ["git", *_GIT_IDENTITY, *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def _commit(repo: Path, name: str) -> None:
    (repo / name).write_text(name)
    _git(repo, "add", name)
    _git(repo, "commit", "-m", name)


@pytest.fixture
def work(tmp_path: Path) -> Path:
    """A clone of a bare remote: `pushed` and `pushed2` are on it, `local-only*` are not."""
    remote = tmp_path / "remote.git"
    _git(tmp_path, "init", "--bare", "-b", "main", str(remote))
    repo = tmp_path / "work"
    _git(tmp_path, "init", "-b", "main", str(repo))
    _git(repo, "remote", "add", "origin", str(remote))
    _commit(repo, "base")
    _git(repo, "push", "-u", "origin", "main")
    for name in ("pushed", "pushed2"):
        _git(repo, "checkout", "-b", name)
        _commit(repo, name)
        _git(repo, "push", "origin", name)
    for name in ("local-only", "local-only2"):
        _git(repo, "checkout", "-b", name, "main")
        _commit(repo, name)
    _git(repo, "checkout", "main")
    return repo


@pytest.fixture
def other(tmp_path: Path) -> Path:
    """A second repository with no remote and one unpushed branch."""
    repo = tmp_path / "other"
    _git(tmp_path, "init", "-b", "main", str(repo))
    _commit(repo, "base")
    _git(repo, "checkout", "-b", "stranded")
    _commit(repo, "stranded")
    _git(repo, "checkout", "main")
    return repo


@pytest.fixture
def handler() -> DestructiveGitHandler:
    return DestructiveGitHandler()


def _input(command: str, cwd: Path) -> dict[str, Any]:
    return {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(cwd)}


def _allowed(handler: DestructiveGitHandler, command: str, cwd: Path) -> bool:
    hook_input = _input(command, cwd)
    assert handler.matches(hook_input) is True
    return handler.handle(hook_input).decision == Decision.ALLOW


def _reason(handler: DestructiveGitHandler, command: str, cwd: Path) -> str:
    result = handler.handle(_input(command, cwd))
    assert result.decision == Decision.DENY
    return result.reason or ""


class TestPushedBranchIsAllowed:
    @pytest.mark.parametrize(
        "command",
        [
            "git branch -D pushed",
            "git branch -d --force pushed",
            "git branch -d -f pushed",
            "git branch --delete --force pushed",
            "git branch -fd pushed",
            "git branch -D pushed pushed2",
            "git update-ref -d refs/heads/pushed",
            "git --no-pager branch -D pushed",
        ],
    )
    def test_allowed(self, handler: DestructiveGitHandler, work: Path, command: str) -> None:
        assert _allowed(handler, command, work)


class TestUnpushedBranchIsDenied:
    def test_denied_and_named_with_push_advice(
        self, handler: DestructiveGitHandler, work: Path
    ) -> None:
        reason = _reason(handler, "git branch -D local-only", work)
        assert "R-GIT-BRANCH-FORCE-DELETE" in reason
        assert "local-only" in reason
        assert "git push -u origin local-only" in reason

    def test_mixed_list_names_only_the_unpushed_branch(
        self, handler: DestructiveGitHandler, work: Path
    ) -> None:
        reason = _reason(handler, "git branch -D pushed local-only pushed2", work)
        assert "git push -u origin local-only" in reason
        assert "git push -u origin pushed" not in reason

    def test_two_unpushed_are_both_named(self, handler: DestructiveGitHandler, work: Path) -> None:
        reason = _reason(handler, "git branch -D local-only local-only2", work)
        assert "`local-only` (push it: `git push -u origin local-only`)" in reason
        assert "`local-only2` (push it: `git push -u origin local-only2`)" in reason

    @pytest.mark.parametrize(
        "command",
        [
            "git branch -d --force local-only",
            "git branch -f -d local-only",
            "git branch --delete --force local-only",
            "git branch -fd local-only",
        ],
    )
    def test_two_option_spellings_are_judged_too(
        self, handler: DestructiveGitHandler, work: Path, command: str
    ) -> None:
        assert "git push -u origin local-only" in _reason(handler, command, work)

    def test_plain_merge_checked_delete_is_not_this_handlers_business(
        self, handler: DestructiveGitHandler, work: Path
    ) -> None:
        for command in ("git branch -d local-only", "git branch -d feature-f"):
            assert handler.matches(_input(command, work)) is False

    def test_update_ref_spelling_denied_when_unpushed(
        self, handler: DestructiveGitHandler, work: Path
    ) -> None:
        reason = _reason(handler, "git update-ref -d refs/heads/local-only", work)
        assert "git push -u origin local-only" in reason

    def test_unknown_branch_is_denied(self, handler: DestructiveGitHandler, work: Path) -> None:
        reason = _reason(handler, "git branch -D no-such-branch", work)
        assert "no-such-branch" in reason

    def test_a_branch_pushed_then_advanced_is_denied(
        self, handler: DestructiveGitHandler, work: Path
    ) -> None:
        _git(work, "checkout", "pushed")
        _commit(work, "extra")
        _git(work, "checkout", "main")
        reason = _reason(handler, "git branch -D pushed", work)
        assert "git push -u origin pushed" in reason


class TestRepositoryJudged:
    def test_dash_c_elsewhere_is_judged_there(
        self, handler: DestructiveGitHandler, work: Path, other: Path
    ) -> None:
        # cwd holds the pushed branch, but the command runs in `other`.
        reason = _reason(handler, f"git -C {other} branch -D stranded", work)
        assert "stranded" in reason

    def test_dash_c_into_pushed_repo_from_elsewhere_is_allowed(
        self, handler: DestructiveGitHandler, work: Path, other: Path
    ) -> None:
        assert _allowed(handler, f"git -C {work} branch -D pushed", other)

    def test_cd_in_the_same_command_is_honoured(
        self, handler: DestructiveGitHandler, work: Path, other: Path
    ) -> None:
        assert _allowed(handler, f"cd {work} && git branch -D pushed", other)
        assert "stranded" in _reason(handler, f"cd {other} && git branch -D stranded", work)

    def test_relative_dash_c_resolves_against_cwd(
        self, handler: DestructiveGitHandler, work: Path
    ) -> None:
        assert _allowed(handler, "git -C ../work branch -D pushed", work)


class TestFailClosed:
    def test_git_failure_denies(
        self,
        handler: DestructiveGitHandler,
        work: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def broken(cwd: Path, *args: str, **kwargs: Any) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(["git", *args], 127, "", "git missing")

        monkeypatch.setattr(destructive_git, "run_git", broken)
        reason = _reason(handler, "git branch -D pushed", work)
        assert "pushed" in reason

    def test_failing_remote_query_denies(
        self,
        handler: DestructiveGitHandler,
        work: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        real = destructive_git.run_git

        def remote_query_fails(
            cwd: Path, *args: str, **kwargs: Any
        ) -> subprocess.CompletedProcess[str]:
            if args and args[0] == "for-each-ref":
                return subprocess.CompletedProcess(["git", *args], 128, "", "boom")
            return real(cwd, *args, **kwargs)

        monkeypatch.setattr(destructive_git, "run_git", remote_query_fails)
        assert "pushed" in _reason(handler, "git branch -D pushed", work)

    def test_a_bounded_timeout_is_passed_to_git(
        self,
        handler: DestructiveGitHandler,
        work: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        real = destructive_git.run_git
        seen: list[Any] = []

        def spy(cwd: Path, *args: str, **kwargs: Any) -> subprocess.CompletedProcess[str]:
            seen.append(kwargs.get("timeout"))
            return real(cwd, *args, **kwargs)

        monkeypatch.setattr(destructive_git, "run_git", spy)
        assert _allowed(handler, "git branch -D pushed", work)
        assert seen
        assert all(isinstance(timeout, (int, float)) and timeout > 0 for timeout in seen)

    def test_unknown_working_directory_denies(
        self, handler: DestructiveGitHandler, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def no_directory(_hook_input: dict[str, Any]) -> Path:
            raise RuntimeError("ProjectContext not initialized")

        monkeypatch.setattr(DestructiveGitHandler, "_cwd", staticmethod(no_directory))
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git branch -D pushed"}}
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY
        assert "unknown" in (result.reason or "")

    def test_unresolvable_directory_denies(
        self, handler: DestructiveGitHandler, work: Path, tmp_path: Path
    ) -> None:
        missing = tmp_path / "does-not-exist"
        reason = _reason(handler, f"git -C {missing} branch -D pushed", work)
        assert "does-not-exist" in reason

    def test_a_directory_that_is_not_a_repository_denies(
        self, handler: DestructiveGitHandler, work: Path, tmp_path: Path
    ) -> None:
        plain = tmp_path / "plain"
        plain.mkdir()
        assert "pushed" in _reason(handler, f"git -C {plain} branch -D pushed", work)

    @pytest.mark.parametrize(
        "command",
        [
            "git branch -D $BRANCH",
            "git branch -D $(git branch --list 'p*')",
            "git branch -D `echo pushed`",
            "git branch -D pushed*",
            "git --git-dir=/elsewhere branch -D pushed",
            "GIT_DIR=/elsewhere git branch -D pushed",
            "git branch --list | xargs git branch -D",
            "git branch -D",
            "git branch -Dr origin/pushed",
            "git branch -D --unknown-flag pushed",
            "cd - && git branch -D pushed",
            "git update-ref -d refs/heads/pushed $(git rev-parse pushed)",
        ],
    )
    def test_unreadable_commands_deny(
        self, handler: DestructiveGitHandler, work: Path, command: str
    ) -> None:
        result = handler.handle(_input(command, work))
        assert result.decision == Decision.DENY

    def test_another_destructive_command_in_the_same_line_still_denies(
        self, handler: DestructiveGitHandler, work: Path
    ) -> None:
        reason = _reason(handler, "git branch -D pushed && git commit --amend", work)
        assert "R-GIT-COMMIT-AMEND" in reason
        reason = _reason(handler, "git branch -D pushed; git push --force", work)
        assert "R-GIT-PUSH-FORCE" in reason

    def test_one_unpushed_invocation_among_pushed_ones_denies(
        self, handler: DestructiveGitHandler, work: Path
    ) -> None:
        reason = _reason(handler, "git branch -D pushed && git branch -D local-only", work)
        assert "git push -u origin local-only" in reason

    def test_prose_mentioning_the_command_is_not_trusted(
        self, handler: DestructiveGitHandler, work: Path
    ) -> None:
        result = handler.handle(_input('echo "git branch -D pushed"', work))
        assert result.decision == Decision.DENY


class TestGuidanceDescribesTheNewBehaviour:
    def test_rule_definition_mentions_remote(self, handler: DestructiveGitHandler) -> None:
        rule = next(r for r in handler.get_rules() if r.rule_id == "R-GIT-BRANCH-FORCE-DELETE")
        text = f"{rule.why} {rule.fix} {rule.verbose}"
        assert "remote" in text
        assert "git push -u origin" in text
        assert "ask the user" not in rule.fix.lower()

    def test_claude_md_row_describes_remote_condition(self, handler: DestructiveGitHandler) -> None:
        text = handler.get_claude_md() or ""
        assert "remote-tracking" in text

    def test_acceptance_tests_cover_the_denial_message(
        self, handler: DestructiveGitHandler
    ) -> None:
        branch_tests = [t for t in handler.get_acceptance_tests() if "branch" in t.title.lower()]
        assert branch_tests
        assert all(
            any("push" in pattern for pattern in t.expected_message_patterns) for t in branch_tests
        )
