"""``utils.remote_refs``: one bounded ``ls-remote`` and the holder lookup (issue #166)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.utils import remote_refs
from claude_code_hooks_daemon.utils.git_repo import run_git
from tests.support import archive_remote


@pytest.fixture(scope="module")
def scratch(tmp_path_factory: pytest.TempPathFactory) -> archive_remote.ArchiveRepo:
    return archive_remote.build(tmp_path_factory.mktemp("archive"))


def _tip(scratch: archive_remote.ArchiveRepo, branch: str) -> str:
    return run_git(scratch.clone, "rev-parse", branch).stdout.strip()


class TestListRemoteRefs:
    def test_lists_refs_outside_refs_heads(self, scratch: archive_remote.ArchiveRepo) -> None:
        listing = remote_refs.list_remote_refs(scratch.clone, "origin")
        assert listing.failure is None
        assert dict(listing.refs)["refs/archive/archived"] == scratch.archived_tip

    def test_one_ls_remote_call_with_the_timeout_constant(
        self, scratch: archive_remote.ArchiveRepo
    ) -> None:
        with patch.object(remote_refs, "run_git", wraps=run_git) as spy:
            remote_refs.list_remote_refs(scratch.clone, "origin")
        assert spy.call_count == 1
        assert spy.call_args.args[1:3] == ("ls-remote", "origin")
        assert spy.call_args.kwargs["timeout"] == remote_refs.Timeout.GIT_LS_REMOTE

    def test_patterns_bound_the_listing_and_the_caller_sets_the_timeout(
        self, scratch: archive_remote.ArchiveRepo
    ) -> None:
        # The remote-delete proof (Plan 00571 Task 2.7) lists only the names it judges,
        # under the hook path's own timeout, through this one function.
        with patch.object(remote_refs, "run_git", wraps=run_git) as spy:
            listing = remote_refs.list_remote_refs(
                scratch.clone,
                "origin",
                patterns=("refs/heads/main",),
                timeout=remote_refs.Timeout.GIT_CONTEXT,
            )
        assert spy.call_args.args[1:] == ("ls-remote", "origin", "refs/heads/main")
        assert spy.call_args.kwargs["timeout"] == remote_refs.Timeout.GIT_CONTEXT
        assert listing.failure is None
        assert [ref for ref, _sha in listing.refs] == ["refs/heads/main"]

    def test_failure_is_reported_never_raised(self, scratch: archive_remote.ArchiveRepo) -> None:
        listing = remote_refs.list_remote_refs(scratch.clone, "no-such-remote")
        assert listing.failure is not None
        assert listing.refs == ()

    def test_ssh_auth_failure_without_agent_socket_names_the_missing_variable(
        self, scratch: archive_remote.ArchiveRepo, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A daemon restarted from a shell-less context has HOME but no SSH_AUTH_SOCK,
        # so ssh cannot authenticate; the reason must say so, not just "failed".
        monkeypatch.delenv("SSH_AUTH_SOCK", raising=False)
        denied = run_git(scratch.clone, "--version")
        denied = type(denied)(
            denied.args, 128, "", "git@host: Permission denied (publickey).\nfatal: Could not read"
        )
        with patch.object(remote_refs, "run_git", return_value=denied):
            listing = remote_refs.list_remote_refs(scratch.clone, "origin")
        assert listing.failure is not None
        assert "Permission denied (publickey)" in listing.failure
        assert "SSH_AUTH_SOCK" in listing.failure

    def test_ssh_auth_failure_with_agent_socket_adds_no_hint(
        self, scratch: archive_remote.ArchiveRepo, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SSH_AUTH_SOCK", "/run/agent.sock")
        base = run_git(scratch.clone, "--version")
        denied = type(base)(base.args, 128, "", "git@host: Permission denied (publickey).")
        with patch.object(remote_refs, "run_git", return_value=denied):
            listing = remote_refs.list_remote_refs(scratch.clone, "origin")
        assert listing.failure == "git@host: Permission denied (publickey)."

    def test_non_auth_failure_without_agent_socket_adds_no_hint(
        self, scratch: archive_remote.ArchiveRepo, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("SSH_AUTH_SOCK", raising=False)
        base = run_git(scratch.clone, "--version")
        failed = type(base)(base.args, 128, "", "fatal: 'nowhere' does not appear to be a repo")
        with patch.object(remote_refs, "run_git", return_value=failed):
            listing = remote_refs.list_remote_refs(scratch.clone, "origin")
        assert listing.failure is not None
        assert "SSH_AUTH_SOCK" not in listing.failure

    def test_peeled_and_head_lines_are_dropped(self) -> None:
        text = f"{'a' * 40}\tHEAD\n{'b' * 40}\trefs/tags/v1\n{'c' * 40}\trefs/tags/v1^{{}}\n"
        assert remote_refs.parse_listing(text) == (("refs/tags/v1", "b" * 40),)


class TestHolderOf:
    def test_equal_sha_is_held(self, scratch: archive_remote.ArchiveRepo) -> None:
        listing = remote_refs.list_remote_refs(scratch.clone, "origin")
        held = remote_refs.holder_of(scratch.clone, listing, scratch.archived_tip)
        assert held == "refs/archive/archived"

    def test_descendant_present_locally_is_held(self, scratch: archive_remote.ArchiveRepo) -> None:
        listing = remote_refs.list_remote_refs(scratch.clone, "origin")
        held = remote_refs.holder_of(scratch.clone, listing, _tip(scratch, "archived-child"))
        assert held == "refs/archive/kid-above"

    def test_unheld_tip_is_none(self, scratch: archive_remote.ArchiveRepo) -> None:
        listing = remote_refs.list_remote_refs(scratch.clone, "origin")
        assert remote_refs.holder_of(scratch.clone, listing, _tip(scratch, "unpushed")) is None

    def test_descendant_missing_locally_is_not_proof(
        self, scratch: archive_remote.ArchiveRepo
    ) -> None:
        listing = remote_refs.RemoteRefs("origin", (("refs/archive/x", "f" * 40),))
        assert remote_refs.holder_of(scratch.clone, listing, _tip(scratch, "unpushed")) is None

    def test_a_failed_listing_is_never_proof(self, scratch: archive_remote.ArchiveRepo) -> None:
        listing = remote_refs.RemoteRefs("origin", (), failure="timed out")
        assert remote_refs.holder_of(scratch.clone, listing, scratch.archived_tip) is None
