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

    def test_failure_is_reported_never_raised(self, scratch: archive_remote.ArchiveRepo) -> None:
        listing = remote_refs.list_remote_refs(scratch.clone, "no-such-remote")
        assert listing.failure is not None
        assert listing.refs == ()

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
