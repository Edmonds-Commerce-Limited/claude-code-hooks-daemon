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

    # Review finding 3: shapes the seam missed (shared with dangerous_permissions).
    @pytest.mark.parametrize(
        "command",
        [
            "chmod a=rwx f",
            "chmod o=rwx f",
            "chmod ugo+w f",
            "chmod u+x,o+w f",
            "chmod 00777 f",
            "install -m 777 a b",
            "sudo install -m 0666 a b",
            "install --mode=a+w a b",
            "setfacl -m o::rwx f",
            "setfacl -m other::rw- f",
            "setfacl -R -m d:o::rwx d",
            "umask 000",
            "umask 0",
            "umask a=rwx",
        ],
    )
    def test_world_writable_beyond_chmod_octal(self, command: str) -> None:
        assert sets_world_writable(command) is True

    @pytest.mark.parametrize(
        "command",
        [
            "chmod u=rwx f",
            "chmod go=rx f",
            "chmod 0755 f",
            "chmod 00755 f",
            "install -m 755 a b",
            "install -d dir",
            "umask 022",
            "umask 077",
            "umask 002",
            "umask",
            "umask -S",
            "setfacl -m u:bob:rwx f",
            "setfacl -m o::r-x f",
            "echo umask 000",
            "pip install requests",
        ],
    )
    def test_safe_modes_stay_allowed(self, command: str) -> None:
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
        "command",
        ["gh -R o/r pr merge 5", "gh --repo=o/r pr merge 5", "gh pr -R o/r merge 5"],
    )
    def test_pr_merge_with_repo_flag(self, command: str) -> None:
        """Review finding 3: the repo flag before `pr` hid the merge (shared seam)."""
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

    # Review finding 3: tag deletes, API ref deletes and removing ref files.
    @pytest.mark.parametrize(
        "command",
        [
            "git tag -d v1",
            "git tag --delete v1",
            "gh api -X DELETE repos/o/r/git/refs/heads/foo",
            "gh api --method DELETE repos/o/r/git/refs/tags/v1",
            "gh api repos/o/r/git/refs/heads/foo -XDELETE",
            "rm -rf .git/refs/heads/foo",
            "sudo rm ../repo/.git/refs/tags/v1",
            "rm -f .git/packed-refs",
        ],
    )
    def test_other_ref_deletions(self, command: str) -> None:
        assert names_a_deletion(command) is True

    @pytest.mark.parametrize(
        "command",
        [
            "git tag v1",
            "git tag -l",
            "gh api repos/o/r/git/refs/heads/foo",
            "gh api -X DELETE repos/o/r/issues/comments/1",
            "echo rm -rf .git/refs/heads/foo",
            "rm -rf build/",
            "git commit -m 'git tag -d v1'",
        ],
    )
    def test_not_a_ref_deletion(self, command: str) -> None:
        assert names_a_deletion(command) is False
