"""#153: a many-branch remote delete is judged with ONE `git ls-remote` per remote.

The per-branch `ls-remote` made a 37-branch delete exceed the handler's dispatch
budget. Git is stubbed here so the tests assert on the calls made, not on wall time.
"""

import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core.data_layer import reset_data_layer
from claude_code_hooks_daemon.handlers.pre_tool_use import destructive_git
from claude_code_hooks_daemon.handlers.pre_tool_use.destructive_git import DestructiveGitHandler

_TIP = "a" * 40
_OTHER = "b" * 40

# (cwd-relative git argv) -> completed process
GitCalls = list[tuple[str, ...]]


@pytest.fixture(autouse=True)
def _reset_disclosure_tracker() -> Any:
    reset_data_layer()
    yield
    reset_data_layer()


def _done(returncode: int = 0, stdout: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr="")


class _FakeGit:
    """Every branch is merged with tracking tip ``_TIP``; ls-remote is scripted."""

    def __init__(self, listing: Callable[[tuple[str, ...]], subprocess.CompletedProcess[str]]):
        self.calls: GitCalls = []
        self._listing = listing

    def __call__(self, cwd: Path, *args: str, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append(args)
        if args[0] == "ls-remote":
            assert kwargs["env"] == {"GIT_TERMINAL_PROMPT": "0"}
            assert kwargs["timeout"] > 0
            return self._listing(args)
        if args[0] == "rev-parse" and args[3].startswith("refs/tags/"):
            return _done(1)
        if args[0] == "rev-parse":
            return _done(0, _TIP + "\n")
        if args[0] == "merge-base":
            return _done(0)
        raise AssertionError(f"unexpected git call {args}")

    @property
    def ls_remote_calls(self) -> GitCalls:
        return [call for call in self.calls if call[0] == "ls-remote"]


def _listing_of(tips: dict[str, str]) -> Callable[[tuple[str, ...]], Any]:
    def listing(args: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        wanted = args[2:]
        return _done(0, "".join(f"{tip}\trefs/heads/{n}\n" for n, tip in tips.items() if f"refs/heads/{n}" in wanted))

    return listing


@pytest.fixture
def install(monkeypatch: pytest.MonkeyPatch) -> Callable[[_FakeGit], _FakeGit]:
    def _install(fake: _FakeGit) -> _FakeGit:
        monkeypatch.setattr(destructive_git, "run_git", fake)
        monkeypatch.setattr(destructive_git, "default_branch", lambda _directory: "main")
        return fake

    return _install


def _handle(command: str, cwd: Path) -> Any:
    hook_input = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(cwd)}
    return DestructiveGitHandler().handle(hook_input)


def test_many_branches_cost_one_ls_remote(
    install: Callable[[_FakeGit], _FakeGit], tmp_path: Path
) -> None:
    names = [f"b{i}" for i in range(40)]
    fake = install(_FakeGit(_listing_of({n: _TIP for n in names})))
    result = _handle("git push origin --delete " + " ".join(names), tmp_path)
    assert result.decision == "allow"
    assert len(fake.ls_remote_calls) == 1
    assert fake.ls_remote_calls[0] == ("ls-remote", "origin", *[f"refs/heads/{n}" for n in names])


def test_each_remote_gets_its_own_single_call(
    install: Callable[[_FakeGit], _FakeGit], tmp_path: Path
) -> None:
    fake = install(_FakeGit(_listing_of({"a": _TIP, "b": _TIP})))
    result = _handle("git push origin --delete a b && git push other --delete a b", tmp_path)
    assert result.decision == "allow"
    assert [call[1] for call in fake.ls_remote_calls] == ["origin", "other"]


def test_one_differing_tip_denies_and_names_the_branch(
    install: Callable[[_FakeGit], _FakeGit], tmp_path: Path
) -> None:
    install(_FakeGit(_listing_of({"a": _TIP, "stale": _OTHER, "c": _TIP})))
    result = _handle("git push origin --delete a stale c", tmp_path)
    assert result.decision == "deny"
    assert RuleID.GIT_PUSH_DELETE_REMOTE in (result.reason or "")
    assert "`stale`" in (result.reason or "")
    assert "`a`" not in (result.reason or "")


def test_a_branch_missing_from_the_listing_is_denied(
    install: Callable[[_FakeGit], _FakeGit], tmp_path: Path
) -> None:
    install(_FakeGit(_listing_of({"a": _TIP})))
    result = _handle("git push origin --delete a gone", tmp_path)
    assert result.decision == "deny"
    assert "`gone`" in (result.reason or "")


@pytest.mark.parametrize("returncode", [1, 124])
def test_a_failed_or_timed_out_listing_denies_every_branch(
    install: Callable[[_FakeGit], _FakeGit], tmp_path: Path, returncode: int
) -> None:
    install(_FakeGit(lambda _args: _done(returncode, f"{_TIP}\trefs/heads/a\n")))
    result = _handle("git push origin --delete a b", tmp_path)
    assert result.decision == "deny"
    assert "`a`" in (result.reason or "")
    assert "`b`" in (result.reason or "")


def test_a_prefix_of_another_branch_is_matched_exactly(
    install: Callable[[_FakeGit], _FakeGit], tmp_path: Path
) -> None:
    # The remote lists only feat-2; `feat` must not borrow its tip.
    def listing(_args: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        return _done(0, f"{_TIP}\trefs/heads/feat-2\n")

    install(_FakeGit(listing))
    result = _handle("git push origin --delete feat feat-2", tmp_path)
    assert result.decision == "deny"
    assert "`feat`" in (result.reason or "")
    assert "`feat-2`" not in (result.reason or "")


def test_a_foreign_ref_ending_in_the_name_does_not_count(
    install: Callable[[_FakeGit], _FakeGit], tmp_path: Path
) -> None:
    def listing(_args: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        return _done(0, f"{_TIP}\trefs/other/refs/heads/a\n")

    install(_FakeGit(listing))
    assert _handle("git push origin --delete a", tmp_path).decision == "deny"


def test_a_huge_delete_is_chunked_not_one_giant_argv(
    install: Callable[[_FakeGit], _FakeGit], tmp_path: Path
) -> None:
    names = [f"b{i}" for i in range(1200)]
    fake = install(_FakeGit(_listing_of({n: _TIP for n in names})))
    result = _handle("git push origin --delete " + " ".join(names), tmp_path)
    assert result.decision == "allow"
    assert len(fake.ls_remote_calls) == 3
    assert max(len(call) - 2 for call in fake.ls_remote_calls) == destructive_git._LS_REMOTE_CHUNK
