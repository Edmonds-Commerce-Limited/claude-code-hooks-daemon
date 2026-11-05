"""Plan 00558 (DESIGN.md section 7): integration lines in R-GIT-PUSH-DELETE-REMOTE.

A remote branch is provably merged when its remote-tracking tip is an ancestor of the
default branch OR of any integration line (`branches.integration_lines`). The default,
the lines themselves, exempt names and protected names are refused outright, whatever
the proof. The proof is one `git for-each-ref --merged` per target, never one
`merge-base` per branch, and the live `ls-remote` stays one call per remote.
"""

import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from tests.support.git_fixtures import run_git

from claude_code_hooks_daemon.config.models import BranchesConfig
from claude_code_hooks_daemon.constants import Timeout
from claude_code_hooks_daemon.core.data_layer import reset_data_layer
from claude_code_hooks_daemon.handlers.pre_tool_use import destructive_git
from claude_code_hooks_daemon.handlers.pre_tool_use.destructive_git import DestructiveGitHandler

_LINES = BranchesConfig(integration_lines=["release/*"], exempt=["keep/*"])


@pytest.fixture(autouse=True)
def _reset_disclosure_tracker() -> Any:
    reset_data_layer()
    yield
    reset_data_layer()


def _handler(branches: BranchesConfig = _LINES) -> DestructiveGitHandler:
    handler = DestructiveGitHandler()
    handler._branches = branches
    return handler


def _input(command: str, cwd: Path) -> dict[str, Any]:
    return {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(cwd)}


@pytest.fixture
def clone(tmp_path: Path) -> Path:
    """origin has `main`, `release/x` one commit ahead, and `feature` at release/x's tip."""
    origin = tmp_path / "origin.git"
    work = tmp_path / "work"
    run_git(tmp_path, "init", "--bare", "--initial-branch=main", str(origin))
    run_git(tmp_path, "init", "--initial-branch=main", str(work))
    run_git(work, "config", "user.email", "t@example.invalid")
    run_git(work, "config", "user.name", "Tester")
    run_git(work, "config", "commit.gpgsign", "false")
    run_git(work, "remote", "add", "origin", str(origin))
    run_git(work, "commit", "--allow-empty", "-m", "base")
    run_git(work, "push", "-u", "origin", "main")
    run_git(work, "remote", "set-head", "origin", "main")
    run_git(work, "checkout", "-b", "release/x")
    run_git(work, "commit", "--allow-empty", "-m", "only on the release line")
    run_git(work, "push", "-u", "origin", "release/x")
    run_git(work, "push", "origin", "release/x:refs/heads/feature")
    run_git(work, "push", "origin", "release/x:refs/heads/keep/me")
    run_git(work, "push", "origin", "release/x:refs/heads/develop")
    run_git(work, "checkout", "main")
    run_git(work, "fetch", "origin")
    return work


def test_a_branch_merged_only_into_an_integration_line_is_allowed(clone: Path) -> None:
    result = _handler().handle(_input("git push origin --delete feature", clone))
    assert result.decision == "allow"


def test_without_the_line_configured_the_same_branch_is_unmerged(clone: Path) -> None:
    result = _handler(BranchesConfig()).handle(_input("git push origin --delete feature", clone))
    assert result.decision == "deny"
    assert "not merged" in (result.reason or "")


def test_an_unmerged_integration_line_is_denied_as_not_yet_merged(clone: Path) -> None:
    result = _handler().handle(_input("git push origin --delete release/x", clone))
    assert result.decision == "deny"
    assert "`release/x`" in (result.reason or "")
    assert "integration line" in (result.reason or "")
    assert "not yet merged into" in (result.reason or "")
    assert "`main`" in (result.reason or "")


@pytest.fixture
def merged_line_clone(clone: Path) -> Path:
    """`release/x` has been merged into `main` and `main` pushed."""
    run_git(clone, "merge", "--no-ff", "-m", "Merge release/x", "release/x")
    run_git(clone, "push", "origin", "main")
    run_git(clone, "fetch", "origin")
    return clone


def test_a_line_merged_into_the_default_branch_is_allowed(merged_line_clone: Path) -> None:
    result = _handler().handle(_input("git push origin --delete release/x", merged_line_clone))
    assert result.decision == "allow"


def test_a_merged_line_is_still_held_to_the_live_remote_tip(merged_line_clone: Path) -> None:
    run_git(merged_line_clone, "checkout", "release/x")
    run_git(merged_line_clone, "commit", "--allow-empty", "-m", "pushed since the last fetch")
    run_git(merged_line_clone, "push", "origin", "release/x")
    run_git(merged_line_clone, "update-ref", "refs/remotes/origin/release/x", "release/x~1")
    run_git(merged_line_clone, "checkout", "main")
    result = _handler().handle(_input("git push origin --delete release/x", merged_line_clone))
    assert result.decision == "deny"
    assert "remote tip" in (result.reason or "")


def test_a_line_merged_only_into_another_line_is_denied(clone: Path) -> None:
    run_git(clone, "checkout", "-b", "release/y", "release/x")
    run_git(clone, "commit", "--allow-empty", "-m", "only on release/y")
    run_git(clone, "push", "-u", "origin", "release/y")
    run_git(clone, "checkout", "main")
    run_git(clone, "fetch", "origin")
    result = _handler().handle(_input("git push origin --delete release/x", clone))
    assert result.decision == "deny"
    assert "not yet merged into" in (result.reason or "")


def test_an_exempt_name_is_refused_although_merged(clone: Path) -> None:
    result = _handler().handle(_input("git push origin --delete keep/me", clone))
    assert result.decision == "deny"
    assert "exempt" in (result.reason or "")


def test_a_protected_name_is_refused_although_merged(clone: Path) -> None:
    result = _handler().handle(_input("git push origin :develop", clone))
    assert result.decision == "deny"
    assert "protected" in (result.reason or "")


def test_the_default_branch_is_refused_and_named_as_the_default(clone: Path) -> None:
    result = _handler().handle(_input("git push origin --delete main", clone))
    assert result.decision == "deny"
    assert "default branch" in (result.reason or "")


def test_the_handler_declares_the_branches_attribute_with_model_defaults() -> None:
    assert DestructiveGitHandler()._branches == BranchesConfig()


# --- call shape, with git stubbed --------------------------------------------------

_TIP = "a" * 40
_LINE_TIP = "c" * 40


def _done(returncode: int = 0, stdout: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr="")


class _FakeGit:
    """Every named branch is tracked at ``_TIP`` and merged; ls-remote agrees."""

    def __init__(self, names: list[str], *, merged_fails: bool = False) -> None:
        self.calls: list[tuple[str, ...]] = []
        self._names = names
        self._merged_fails = merged_fails

    def _listing(self) -> str:
        rows = [f"{_TIP} commit refs/remotes/origin/{name}" for name in self._names]
        rows.append(f"{_TIP} commit refs/remotes/origin/main")
        rows.append(f"{_LINE_TIP} commit refs/remotes/origin/release/x")
        rows.append(f"{_TIP} commit refs/heads/main")
        return "".join(f"{row}\n" for row in rows)

    def __call__(self, cwd: Path, *args: str, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append(args)
        if args[0] == "ls-remote":
            return _done(0, "".join(f"{_TIP}\trefs/heads/{n}\n" for n in self._names))
        if args[0] == "for-each-ref" and any(a.startswith("--merged") for a in args):
            if self._merged_fails:
                return _done(128)
            named = [a for a in args if a.startswith("refs/remotes/origin/")]
            return _done(0, "".join(f"{ref}\n" for ref in named))
        if args[0] == "for-each-ref":
            return _done(0, self._listing())
        raise AssertionError(f"unexpected git call {args}")

    def count(self, verb: str) -> int:
        return sum(1 for call in self.calls if call[0] == verb)


@pytest.fixture
def install(monkeypatch: pytest.MonkeyPatch) -> Callable[[_FakeGit], _FakeGit]:
    def _install(fake: _FakeGit) -> _FakeGit:
        monkeypatch.setattr(destructive_git, "run_git", fake)
        monkeypatch.setattr(
            destructive_git, "resolve_default_branch", lambda _config, _directory: "main"
        )
        return fake

    return _install


def test_forty_branches_cost_one_ls_remote_and_one_for_each_ref_per_target(
    install: Callable[[_FakeGit], _FakeGit], tmp_path: Path
) -> None:
    few = install(_FakeGit(["b0", "b1"]))
    assert _handler().handle(_input("git push origin --delete b0 b1", tmp_path)).decision == (
        "allow"
    )
    names = [f"b{i}" for i in range(40)]
    many = install(_FakeGit(names))
    command = "git push origin --delete " + " ".join(names)
    assert _handler().handle(_input(command, tmp_path)).decision == "allow"
    assert many.count("ls-remote") == 1
    assert many.count("merge-base") == 0
    assert many.count("rev-parse") == 0
    # Targets: origin/main, local main, origin/release/x -- plus one listing call.
    assert many.count("for-each-ref") == few.count("for-each-ref") == 4


def test_forty_branches_are_judged_within_the_dispatch_budget(
    install: Callable[[_FakeGit], _FakeGit], tmp_path: Path
) -> None:
    names = [f"b{i}" for i in range(40)]
    install(_FakeGit(names))
    command = "git push origin --delete " + " ".join(names)
    started = time.monotonic()
    result = _handler().handle(_input(command, tmp_path))
    elapsed_ms = (time.monotonic() - started) * 1000
    assert result.decision == "allow"
    assert elapsed_ms < Timeout.HOOK_DISPATCH


def test_a_for_each_ref_failure_denies(
    install: Callable[[_FakeGit], _FakeGit], tmp_path: Path
) -> None:
    install(_FakeGit(["b0"], merged_fails=True))
    result = _handler().handle(_input("git push origin --delete b0", tmp_path))
    assert result.decision == "deny"
    assert "`b0`" in (result.reason or "")


def test_a_failed_listing_denies(
    install: Callable[[_FakeGit], _FakeGit], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake = install(_FakeGit(["b0"]))

    def failing(cwd: Path, *args: str, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if args[0] == "for-each-ref":
            fake.calls.append(args)
            return _done(128)
        return fake(cwd, *args, **kwargs)

    monkeypatch.setattr(destructive_git, "run_git", failing)
    result = _handler().handle(_input("git push origin --delete b0", tmp_path))
    assert result.decision == "deny"
    assert "`b0`" in (result.reason or "")
