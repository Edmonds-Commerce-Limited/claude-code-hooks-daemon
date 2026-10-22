"""Tests for ReleaseMergeFreezeHandler (Plan 00476 Task 3.2, Design 4).

While `untracked/release-state.json` records an open release pull request, the
commit CI gated must be the commit that gets tagged, so nothing else may move
`main`: not a `git merge` on main, not a push to main, not a `gh pr merge` of
any other pull request.
"""

import json
from pathlib import Path
from typing import Any

import pytest
from release_merge_freeze import RULE_ID, ReleaseMergeFreezeHandler

from claude_code_hooks_daemon.core.hook_result import Decision

_SHA = "a" * 40
_RELEASE_PR = 12


def _state(pr_number: object = _RELEASE_PR) -> dict[str, Any]:
    return {
        "version": "3.99.0",
        "last_completed_step": 8,
        "ci": {
            "pr_number": pr_number,
            "run_id": 987654,
            "head_sha": _SHA,
            "conclusion": "success",
        },
    }


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A project root; the handler is pointed at it and every branch is `main`."""
    monkeypatch.setattr(ReleaseMergeFreezeHandler, "_project_root", staticmethod(lambda _h: tmp_path))
    (tmp_path / "untracked").mkdir()
    monkeypatch.setattr(
        "release_merge_freeze.current_branch", lambda _directory: "main", raising=True
    )
    return tmp_path


def _write_state(root: Path, state: object) -> None:
    (root / "untracked" / "release-state.json").write_text(json.dumps(state), encoding="utf-8")


@pytest.fixture
def frozen(root: Path) -> Path:
    _write_state(root, _state())
    return root


@pytest.fixture
def handler() -> ReleaseMergeFreezeHandler:
    return ReleaseMergeFreezeHandler()


def _input(command: str, cwd: Path) -> dict[str, Any]:
    return {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(cwd)}


class TestIdentity:
    def test_shape(self, handler: ReleaseMergeFreezeHandler) -> None:
        assert handler.name == "release-merge-freeze"
        assert handler.terminal is True
        assert "project" in handler.tags
        assert "blocking" in handler.tags


class TestNoStateFile:
    @pytest.mark.parametrize(
        "command",
        ["git merge feature", "git push origin main", "gh pr merge 99 --merge"],
    )
    def test_allows_everything_without_a_state_file(
        self, handler: ReleaseMergeFreezeHandler, root: Path, command: str
    ) -> None:
        assert handler.matches(_input(command, root)) is False

    def test_does_not_parse_json_on_the_hot_path(
        self, handler: ReleaseMergeFreezeHandler, root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def boom(*_a: object, **_k: object) -> object:
            raise AssertionError("parsed JSON with no state file")

        monkeypatch.setattr("release_merge_freeze.json.loads", boom)
        assert handler.matches(_input("git push origin main", root)) is False

    def test_ignores_non_bash_tools(self, handler: ReleaseMergeFreezeHandler, frozen: Path) -> None:
        assert handler.matches({"tool_name": "Read", "tool_input": {}}) is False


class TestFrozenMovesOfMain:
    @pytest.mark.parametrize(
        "command",
        [
            "git merge feature",
            "git merge --no-ff worktree-x -m 'merge it'",
            "git -C . merge feature",
            "git fetch && git merge feature",
            "git push origin main",
            "git push",
            "git push -u origin HEAD:main",
            "git push origin HEAD:refs/heads/main",
            "git push origin +feature:main",
            "git push origin :main",
            "git push origin --force-with-lease main",
            "git push --all origin",
            "gh pr merge 99 --merge",
            "gh pr merge --merge",
            "gh pr merge feature-branch --merge",
            "gh pr merge 120 --merge --delete-branch",
        ],
    )
    def test_denied(
        self, handler: ReleaseMergeFreezeHandler, frozen: Path, command: str
    ) -> None:
        payload = _input(command, frozen)
        assert handler.matches(payload) is True
        result = handler.handle(payload)
        assert result.decision == Decision.DENY
        assert result.reason is not None
        assert RULE_ID in result.reason
        assert "#12" in result.reason
        assert "RELEASING.md" in result.reason
        assert "gated" in result.reason

    @pytest.mark.parametrize(
        "command",
        [
            "gh pr merge 12 --merge",
            "gh pr merge 12 --merge --delete-branch",
            "gh pr merge --merge 12",
            "gh pr merge https://github.com/o/r/pull/12 --merge",
            "git push origin release/3.99.0",
            "git push -u origin HEAD:release/3.99.0",
            "git push origin v3.99.0",
            "git merge --abort",
            "git merge-base main feature",
            "git status",
            "echo 'git push origin main'",
            "grep 'gh pr merge 99' notes.md",
            "git pull",
        ],
    )
    def test_allowed(
        self, handler: ReleaseMergeFreezeHandler, frozen: Path, command: str
    ) -> None:
        assert handler.matches(_input(command, frozen)) is False

    def test_merge_off_main_is_allowed(
        self, handler: ReleaseMergeFreezeHandler, frozen: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Child-to-parent merges in a worktree on another branch are not main."""
        monkeypatch.setattr("release_merge_freeze.current_branch", lambda _d: "worktree-x")
        assert handler.matches(_input("git merge feature", frozen)) is False
        assert handler.matches(_input("git push", frozen)) is False
        assert handler.matches(_input("git push origin HEAD", frozen)) is False

    def test_push_head_from_main_is_denied(
        self, handler: ReleaseMergeFreezeHandler, frozen: Path
    ) -> None:
        assert handler.matches(_input("git push origin HEAD", frozen)) is True

    def test_cd_into_a_directory_is_judged_there(
        self, handler: ReleaseMergeFreezeHandler, frozen: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: list[Path] = []

        def branch(directory: Path) -> str:
            seen.append(directory)
            return "main"

        monkeypatch.setattr("release_merge_freeze.current_branch", branch)
        assert handler.matches(_input("cd sub && git merge feature", frozen)) is True
        assert seen == [frozen / "sub"]

    def test_unplaceable_directory_fails_closed(
        self, handler: ReleaseMergeFreezeHandler, frozen: Path
    ) -> None:
        assert handler.matches(_input("cd - && git merge feature", frozen)) is True


class TestNoOpenPullRequest:
    def test_state_without_a_ci_record_allows(
        self, handler: ReleaseMergeFreezeHandler, root: Path
    ) -> None:
        """Before the pull request exists nothing is frozen yet."""
        _write_state(root, {"version": "3.99.0", "last_completed_step": 2})
        assert handler.matches(_input("git merge feature", root)) is False


class TestUnreadableState:
    @pytest.mark.parametrize("command", ["git merge feature", "git push origin main"])
    @pytest.mark.parametrize(
        "content",
        [
            "{not json",
            "[]",
            json.dumps({"ci": "nope"}),
            json.dumps({"ci": {"run_id": 1}}),
            json.dumps(_state(0)),
            json.dumps(_state("12")),
            json.dumps(_state(True)),
        ],
    )
    def test_malformed_denies_loudly_naming_the_file(
        self, handler: ReleaseMergeFreezeHandler, root: Path, content: str, command: str
    ) -> None:
        (root / "untracked" / "release-state.json").write_text(content, encoding="utf-8")
        payload = _input(command, root)
        assert handler.matches(payload) is True
        result = handler.handle(payload)
        assert result.decision == Decision.DENY
        assert result.reason is not None
        assert "release-state.json" in result.reason
        assert RULE_ID in result.reason

    def test_unreadable_denies(self, handler: ReleaseMergeFreezeHandler, root: Path) -> None:
        (root / "untracked" / "release-state.json").mkdir()
        payload = _input("git push origin main", root)
        assert handler.matches(payload) is True
        reason = handler.handle(payload).reason
        assert reason is not None
        assert "release-state.json" in reason

    def test_malformed_state_still_allows_unrelated_commands(
        self, handler: ReleaseMergeFreezeHandler, root: Path
    ) -> None:
        (root / "untracked" / "release-state.json").write_text("{not json", encoding="utf-8")
        assert handler.matches(_input("git status", root)) is False


class TestRuleAndAcceptance:
    def test_rule_is_declared(self, handler: ReleaseMergeFreezeHandler) -> None:
        assert [rule.rule_id for rule in handler.get_rules()] == [RULE_ID]

    def test_acceptance_tests_are_declared_and_safe(
        self, handler: ReleaseMergeFreezeHandler
    ) -> None:
        tests = handler.get_acceptance_tests()
        assert tests
        assert all(t.command.startswith("echo ") for t in tests)

    def test_project_root_prefers_event_cwd_when_no_context(self) -> None:
        root = ReleaseMergeFreezeHandler._project_root({"cwd": "/somewhere"})
        assert isinstance(root, Path)
