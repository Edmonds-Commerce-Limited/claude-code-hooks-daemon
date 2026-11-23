"""Public detector seams the human-approval guard reuses (Plan 00634 Task 2.2).

The guard must not import the sibling handler CLASSES (discovery would register
each one twice), so each sibling exposes its detection as a module function.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from claude_code_hooks_daemon.handlers.pre_tool_use import merge_to_main_approval as merge_module
from claude_code_hooks_daemon.handlers.pre_tool_use.dangerous_permissions import (
    sets_world_writable,
)
from claude_code_hooks_daemon.handlers.pre_tool_use.destructive_git import names_a_deletion
from claude_code_hooks_daemon.handlers.pre_tool_use.merge_to_main_approval import (
    is_pr_merge,
    merge_lands_on_main,
)


class TestSetsWorldWritable:
    @pytest.mark.parametrize("command", ["chmod 777 f", "chmod -R a+rwx d", "x && chmod o+w f"])
    def test_world_writable_chmod(self, command: str) -> None:
        assert sets_world_writable(command) is True

    @pytest.mark.parametrize("command", ["chmod 755 f", "chmod go-w f", "echo chmod 777"])
    def test_not_world_writable(self, command: str) -> None:
        assert sets_world_writable(command) is False


class TestMergeLandsOnMain:
    def _patch(
        self,
        monkeypatch: pytest.MonkeyPatch,
        *,
        linked: bool = False,
        branch: str | None = "main",
    ) -> None:
        monkeypatch.setattr(merge_module, "is_linked_worktree", lambda path: linked)
        monkeypatch.setattr(merge_module, "current_branch", lambda path: branch)
        monkeypatch.setattr(merge_module, "default_branch", lambda path: "main")

    def test_main_checkout_on_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._patch(monkeypatch)
        assert merge_lands_on_main(Path("/repo"), "feature") is True

    def test_linked_worktree_is_definite_no(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._patch(monkeypatch, linked=True, branch=None)
        assert merge_lands_on_main(Path("/repo"), "feature") is False

    def test_unreadable_branch_is_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._patch(monkeypatch, branch=None)
        assert merge_lands_on_main(Path("/repo"), "feature") is None

    def test_default_into_itself_is_no(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._patch(monkeypatch)
        assert merge_lands_on_main(Path("/repo"), "main") is False

    def test_handler_maps_unreadable_to_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._patch(monkeypatch, branch=None)
        handler_check = merge_module.MergeToMainApprovalHandler
        assert handler_check._merges_into_main_checkout_default_branch(Path("/r"), "f") is False


class TestIsPrMerge:
    @pytest.mark.parametrize("command", ["gh pr merge 12 --merge", "cd x && gh pr merge"])
    def test_pr_merge(self, command: str) -> None:
        assert is_pr_merge(command) is True

    @pytest.mark.parametrize(
        "command", ["gh pr view 12", "git commit -m 'gh pr merge 12'", "git merge feature"]
    )
    def test_not_pr_merge(self, command: str) -> None:
        assert is_pr_merge(command) is False


class TestNamesADeletion:
    @pytest.mark.parametrize(
        "command",
        [
            "git branch -D feature",
            "git update-ref -d refs/heads/feature",
            "git push origin --delete feature",
            "git push origin :feature",
            "git worktree remove ../wt",
            "git worktree remove --force ../wt",
            # Unverifiable shapes count as a deletion: fail closed.
            "git branch -Dr origin/feature",
            "git worktree remove",
            "git push --mirror origin",
        ],
    )
    def test_deletion(self, command: str) -> None:
        assert names_a_deletion(command) is True

    @pytest.mark.parametrize(
        "command",
        ["git push origin feature", "git branch feature", "git commit -m 'git branch -D x'"],
    )
    def test_not_deletion(self, command: str) -> None:
        assert names_a_deletion(command) is False
