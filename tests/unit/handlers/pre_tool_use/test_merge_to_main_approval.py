"""Tests for MergeToMainApprovalHandler (Plan 00367 Phase 4).

With ``worktree.merge_to_main_requires_human_approval`` true, a Bash
``git merge <branch>`` (or ``gh pr merge``) run in the MAIN checkout while it
is on the default branch is denied unless a human recorded a one-shot
approval for that branch with ``hooks-daemon approve-merge <branch>``. A merge
in a linked worktree (child -> parent) is never gated, and with the key false
(the shipped default) the handler never matches.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import Decision, TestType
from claude_code_hooks_daemon.core.data_layer import reset_data_layer
from claude_code_hooks_daemon.handlers.pre_tool_use import merge_to_main_approval as module
from claude_code_hooks_daemon.handlers.pre_tool_use.merge_to_main_approval import (
    MergeToMainApprovalHandler,
    merge_target,
)
from claude_code_hooks_daemon.utils.one_shot_approval import OneShotApprovalStore

_MAIN = "/repo"
_STORE = OneShotApprovalStore(module.APPROVAL_SUBDIR)


@pytest.fixture(autouse=True)
def _reset_disclosure_tracker() -> Iterator[None]:
    reset_data_layer()
    yield
    reset_data_layer()


@pytest.fixture
def checkout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """A main checkout on its default branch, with the untracked dir patched."""
    monkeypatch.setattr(module, "is_linked_worktree", lambda path: False)
    monkeypatch.setattr(module, "current_branch", lambda path: "main")
    monkeypatch.setattr(module, "default_branch", lambda path: "main")
    with patch.object(module.ProjectContext, "daemon_untracked_dir", return_value=tmp_path):
        yield tmp_path


def _handler(*, gate_on: bool = True) -> MergeToMainApprovalHandler:
    handler = MergeToMainApprovalHandler()
    handler._merge_to_main_requires_human_approval = gate_on
    return handler


def _bash(command: str, cwd: str = _MAIN) -> dict[str, Any]:
    return {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": cwd}


class TestMergeTarget:
    @pytest.mark.parametrize(
        ("command", "expected"),
        [
            ("git merge worktree-plan-00367", "worktree-plan-00367"),
            ("git merge --no-ff worktree-plan-00367", "worktree-plan-00367"),
            ("git merge worktree-plan-00367 --no-edit", "worktree-plan-00367"),
            ('git merge -m "merge it" worktree-plan-00367', "worktree-plan-00367"),
            ("git merge --no-ff -m 'msg' feature/x", "feature/x"),
            ("git -C /repo merge worktree-plan-00367", "worktree-plan-00367"),
            ("cd /repo && git merge worktree-plan-00367 && git push", "worktree-plan-00367"),
            ("gh pr merge 42 --merge", "42"),
            ("gh pr merge --merge worktree-plan-00367", "worktree-plan-00367"),
        ],
    )
    def test_names_the_branch_being_merged(self, command: str, expected: str) -> None:
        assert merge_target(command) == expected

    @pytest.mark.parametrize(
        "command",
        [
            "git merge --abort",
            "git merge --continue",
            "git merge --quit",
            "git status",
            "git merge-base main feature",
            "git mergetool",
            "echo 'git merge x'",
        ],
    )
    def test_ignores_non_merges(self, command: str) -> None:
        assert merge_target(command) is None


class TestIdentity:
    def test_identity(self) -> None:
        handler = MergeToMainApprovalHandler()
        assert handler.handler_id == HandlerID.MERGE_TO_MAIN_APPROVAL
        assert handler.name == "merge-to-main-approval"
        assert handler.priority == Priority.MERGE_TO_MAIN_APPROVAL
        assert HandlerTag.GIT in handler.tags
        assert HandlerTag.BLOCKING in handler.tags

    def test_rule_and_guidance_name_the_key_and_the_command(self) -> None:
        handler = MergeToMainApprovalHandler()
        rules = handler.get_rules()
        assert [rule.rule_id for rule in rules] == [RuleID.MERGE_TO_MAIN_APPROVAL]
        guidance = handler.get_claude_md()
        assert guidance is not None
        assert "worktree.merge_to_main_requires_human_approval" in guidance
        assert "approve-merge" in guidance

    def test_acceptance_tests_cover_both_branches(self) -> None:
        tests = MergeToMainApprovalHandler().get_acceptance_tests()
        assert {test.expected_decision for test in tests} == {Decision.DENY, Decision.ALLOW}
        assert all(test.test_type == TestType.BLOCKING for test in tests)


class TestMatches:
    def test_default_off_never_matches(self, checkout: Path) -> None:
        assert _handler(gate_on=False).matches(_bash("git merge feature")) is False

    def test_matches_a_merge_in_the_main_checkout_on_main(self, checkout: Path) -> None:
        assert _handler().matches(_bash("git merge feature")) is True
        assert _handler().matches(_bash("gh pr merge 42 --merge")) is True

    def test_ignores_non_merge_commands(self, checkout: Path) -> None:
        assert _handler().matches(_bash("git merge --abort")) is False
        assert _handler().matches(_bash("git status")) is False

    def test_ignores_non_bash(self, checkout: Path) -> None:
        payload = {"tool_name": "Write", "tool_input": {"file_path": "/x", "content": "git merge"}}
        assert _handler().matches(payload) is False

    def test_a_linked_worktree_is_never_gated(
        self, checkout: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(module, "is_linked_worktree", lambda path: True)
        assert _handler().matches(_bash("git merge child", cwd="/repo/untracked/wt")) is False

    def test_main_checkout_on_a_feature_branch_is_not_gated(
        self, checkout: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(module, "current_branch", lambda path: "feature")
        assert _handler().matches(_bash("git merge other")) is False

    def test_detached_head_is_not_gated(
        self, checkout: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(module, "current_branch", lambda path: None)
        assert _handler().matches(_bash("git merge other")) is False

    def test_no_cwd_is_not_gated(self, checkout: Path) -> None:
        payload = {"tool_name": "Bash", "tool_input": {"command": "git merge other"}}
        assert _handler().matches(payload) is False


class TestGate:
    def test_denied_without_approval(self, checkout: Path) -> None:
        result = _handler().handle(_bash("git merge --no-ff worktree-plan-00367"))
        assert result.decision == Decision.DENY
        assert result.reason is not None
        assert "worktree.merge_to_main_requires_human_approval" in result.reason
        assert "approve-merge worktree-plan-00367" in result.reason
        assert RuleID.MERGE_TO_MAIN_APPROVAL in result.reason

    def test_approval_lets_exactly_one_merge_through(self, checkout: Path) -> None:
        _STORE.record(checkout, "worktree-plan-00367")
        first = _handler().handle(_bash("git merge worktree-plan-00367"))
        assert first.decision == Decision.ALLOW
        assert any("approval" in line for line in first.context)
        second = _handler().handle(_bash("git merge worktree-plan-00367"))
        assert second.decision == Decision.DENY

    def test_approval_for_another_branch_does_not_count(self, checkout: Path) -> None:
        _STORE.record(checkout, "other")
        assert _handler().handle(_bash("git merge worktree-plan-00367")).decision == Decision.DENY
        assert _STORE.path(checkout, "other").exists()

    def test_deny_reason_is_terse_after_first_fire(self, checkout: Path) -> None:
        payload = _bash("git merge worktree-plan-00367")
        payload["transcript_path"] = "/tmp/transcript.jsonl"
        handler = _handler()
        first = handler.handle(payload)
        second = handler.handle(payload)
        assert first.reason is not None and second.reason is not None
        assert len(second.reason) < len(first.reason)
        assert "approve-merge worktree-plan-00367" in second.reason
