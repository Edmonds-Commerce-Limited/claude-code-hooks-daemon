"""Plan 00291 Task 3.3 — ``version_check`` never calls a branch install current.

A guarded branch install is stamped ``vX.Y.Z+<ref>.<sha>``. On every new
session the handler must say so and point at a release-tag reinstall. It
must not compare versions, consult the cache or touch the network for such
an install, because any of those could answer "up to date".
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from claude_code_hooks_daemon.constants import Timeout
from claude_code_hooks_daemon.core.hook_result import Decision
from claude_code_hooks_daemon.daemon.metadata import DaemonVenvMetadata
from claude_code_hooks_daemon.handlers.session_start.version_check import VersionCheckHandler
from claude_code_hooks_daemon.install.install_stamp import InstallStamp
from claude_code_hooks_daemon.utils.remote_refs import RemoteRefs

_MODULE = "claude_code_hooks_daemon.handlers.session_start.version_check"
_BRANCH_STAMP = InstallStamp(
    raw="v3.63.0+main.8d011476", version="3.63.0", ref="main", sha="8d011476"
)
_RELEASE_STAMP = InstallStamp(raw="v3.63.0", version="3.63.0", ref=None, sha=None)


@pytest.fixture
def handler() -> VersionCheckHandler:
    return VersionCheckHandler()


@pytest.fixture
def new_session_input(tmp_path: Path) -> dict[str, Any]:
    return {
        "hook_event_name": "SessionStart",
        "session_id": "s",
        "transcript_path": str(tmp_path / "nonexistent.jsonl"),
        "cwd": "/workspace",
    }


def _context_text(result: Any) -> str:
    assert result.context is not None
    return "\n".join(result.context)


class TestBranchInstallIsFlaggedEverySession:
    def test_advises_reinstall_from_a_release_tag(
        self, handler: VersionCheckHandler, new_session_input: dict[str, Any]
    ) -> None:
        with patch(f"{_MODULE}.read_install_stamp", return_value=_BRANCH_STAMP):
            result = handler.handle(new_session_input)

        assert result.decision == Decision.ALLOW
        text = _context_text(result)
        assert "v3.63.0+main.8d011476" in text
        assert "not a release" in text.lower()
        assert "release tag" in text.lower()
        assert "up to date" not in text.lower()

    def test_never_touches_the_network_or_the_cache(
        self, handler: VersionCheckHandler, new_session_input: dict[str, Any], tmp_path: Path
    ) -> None:
        cache_file = tmp_path / "cache.json"
        with (
            patch(f"{_MODULE}.read_install_stamp", return_value=_BRANCH_STAMP),
            patch(f"{_MODULE}.run_git") as run_git,
            patch.object(handler, "_get_cache_file", return_value=cache_file),
        ):
            handler.handle(new_session_input)

        run_git.assert_not_called()
        assert not cache_file.exists()

    def test_a_valid_up_to_date_cache_does_not_silence_it(
        self, handler: VersionCheckHandler, new_session_input: dict[str, Any]
    ) -> None:
        with (
            patch(f"{_MODULE}.read_install_stamp", return_value=_BRANCH_STAMP),
            patch.object(handler, "_is_cache_valid", return_value=True),
            patch.object(handler, "_get_cached_result", return_value={"is_outdated": False}),
        ):
            result = handler.handle(new_session_input)

        assert result.context


class TestReleaseInstallIsUnaffected:
    @patch(f"{_MODULE}.__version__", "2.7.0")
    def test_release_stamp_takes_the_normal_path(
        self, handler: VersionCheckHandler, new_session_input: dict[str, Any], tmp_path: Path
    ) -> None:
        ls_remote = MagicMock(returncode=0, stdout="abc\trefs/tags/v2.7.0\n", stderr="")
        with (
            patch(f"{_MODULE}.read_install_stamp", return_value=_RELEASE_STAMP),
            patch(f"{_MODULE}.run_git", return_value=ls_remote),
            patch.object(handler, "_get_cache_file", return_value=tmp_path / "cache.json"),
        ):
            result = handler.handle(new_session_input)

        assert result.context == []

    @patch(f"{_MODULE}.__version__", "2.7.0")
    def test_no_stamp_at_all_takes_the_normal_path(
        self, handler: VersionCheckHandler, new_session_input: dict[str, Any], tmp_path: Path
    ) -> None:
        ls_remote = MagicMock(returncode=0, stdout="abc\trefs/tags/v2.7.0\n", stderr="")
        with (
            patch(f"{_MODULE}.read_install_stamp", return_value=None),
            patch(f"{_MODULE}.run_git", return_value=ls_remote),
            patch.object(handler, "_get_cache_file", return_value=tmp_path / "cache.json"),
        ):
            result = handler.handle(new_session_input)

        assert result.context == []


# ---------------------------------------------------------------------------
# Plan 00594 Task 5.1: a branch install notices when its tracked ref moves
# ---------------------------------------------------------------------------

_OLD_SHA = "1111111" + "a" * 33
_NEW_SHA = "2222222" + "b" * 33


def _tracking(ref: str = "rc/1.2.3", sha: str = _OLD_SHA, last: str | None = "v3.8.0") -> Any:
    return DaemonVenvMetadata(
        python_path="/usr/bin/python3.11",
        fingerprint="fp",
        lock_hash="sha256:" + "a" * 64,
        daemon_version="v3.9.0+rc-1.2.3.1111111",
        written_at="2026-04-24T10:00:00Z",
        tracked_ref=ref,
        tracked_sha=sha,
        last_release_tag=last,
    )


def _listing(ref: str, sha: str | None, failure: str | None = None) -> RemoteRefs:
    refs = () if sha is None else ((f"refs/heads/{ref}", sha),)
    return RemoteRefs("origin", refs=refs, failure=failure)


@pytest.fixture
def cache_file(handler: VersionCheckHandler, tmp_path: Path) -> Any:
    path = tmp_path / "tip_cache.json"
    with patch.object(handler, "_get_cache_file", return_value=path):
        yield path


class TestMovedRefIsReported:
    def test_a_moved_tip_names_both_shas_and_the_way_to_follow_it(
        self, handler: VersionCheckHandler, new_session_input: dict[str, Any], cache_file: Path
    ) -> None:
        with (
            patch(f"{_MODULE}.read_install_stamp", return_value=_BRANCH_STAMP),
            patch(f"{_MODULE}.read_daemon_metadata", return_value=_tracking()),
            patch(f"{_MODULE}.list_remote_refs", return_value=_listing("rc/1.2.3", _NEW_SHA)),
        ):
            text = _context_text(handler.handle(new_session_input))

        assert "tracked ref rc/1.2.3 moved 1111111..2222222" in text
        assert "re-run the guarded install you used for rc/1.2.3 to follow it" in text

    def test_a_moved_tip_never_prints_the_branch_install_gate(
        self, handler: VersionCheckHandler, new_session_input: dict[str, Any], cache_file: Path
    ) -> None:
        """The gate stays non-obvious (Plan 00291): handler text reaches HOOKS-DAEMON.md."""
        with (
            patch(f"{_MODULE}.read_install_stamp", return_value=_BRANCH_STAMP),
            patch(f"{_MODULE}.read_daemon_metadata", return_value=_tracking()),
            patch(f"{_MODULE}.list_remote_refs", return_value=_listing("rc/1.2.3", _NEW_SHA)),
        ):
            text = _context_text(handler.handle(new_session_input))

        assert "HOOKS_DAEMON_UNSAFE_TRACK_REF" not in text

    def test_one_listing_of_exactly_the_tracked_branch(
        self, handler: VersionCheckHandler, new_session_input: dict[str, Any], cache_file: Path
    ) -> None:
        with (
            patch(f"{_MODULE}.read_install_stamp", return_value=_BRANCH_STAMP),
            patch(f"{_MODULE}.read_daemon_metadata", return_value=_tracking()),
            patch(
                f"{_MODULE}.list_remote_refs", return_value=_listing("rc/1.2.3", _NEW_SHA)
            ) as listing,
        ):
            handler.handle(new_session_input)

        listing.assert_called_once()
        assert listing.call_args.kwargs["patterns"] == (
            "refs/heads/rc/1.2.3",
            "refs/tags/rc/1.2.3",
        )
        assert listing.call_args.kwargs["timeout"] == Timeout.VERSION_CHECK

    def test_a_tip_that_has_not_moved_says_so_but_never_up_to_date(
        self, handler: VersionCheckHandler, new_session_input: dict[str, Any], cache_file: Path
    ) -> None:
        with (
            patch(f"{_MODULE}.read_install_stamp", return_value=_BRANCH_STAMP),
            patch(f"{_MODULE}.read_daemon_metadata", return_value=_tracking()),
            patch(f"{_MODULE}.list_remote_refs", return_value=_listing("rc/1.2.3", _OLD_SHA)),
        ):
            text = _context_text(handler.handle(new_session_input))

        assert "moved" not in text.lower().replace("not moved", "")
        assert "has not moved" in text
        assert "up to date" not in text.lower()


class TestMoveCheckNeverClaimsCurrent:
    @pytest.mark.parametrize(
        "listing",
        [
            _listing("rc/1.2.3", None, failure="timed out"),
            _listing("rc/1.2.3", None),
        ],
        ids=["listing-failed", "ref-absent"],
    )
    def test_an_unreadable_tip_says_not_checked(
        self,
        handler: VersionCheckHandler,
        new_session_input: dict[str, Any],
        cache_file: Path,
        listing: RemoteRefs,
    ) -> None:
        with (
            patch(f"{_MODULE}.read_install_stamp", return_value=_BRANCH_STAMP),
            patch(f"{_MODULE}.read_daemon_metadata", return_value=_tracking()),
            patch(f"{_MODULE}.list_remote_refs", return_value=listing),
        ):
            text = _context_text(handler.handle(new_session_input))

        assert "not checked" in text.lower()
        assert "has not moved" not in text

    def test_a_tag_ref_is_named_as_a_tag_not_as_an_unreadable_remote(
        self, handler: VersionCheckHandler, new_session_input: dict[str, Any], cache_file: Path
    ) -> None:
        tag_listing = RemoteRefs("origin", refs=(("refs/tags/rc/1.2.3", _NEW_SHA),))
        with (
            patch(f"{_MODULE}.read_install_stamp", return_value=_BRANCH_STAMP),
            patch(f"{_MODULE}.read_daemon_metadata", return_value=_tracking()),
            patch(f"{_MODULE}.list_remote_refs", return_value=tag_listing),
        ):
            text = _context_text(handler.handle(new_session_input))

        assert "is a tag" in text
        assert "could not be read" not in text
        assert "moved" not in text.lower().replace("not moved", "")

    def test_no_tracking_record_says_not_checked_without_the_network(
        self, handler: VersionCheckHandler, new_session_input: dict[str, Any], cache_file: Path
    ) -> None:
        with (
            patch(f"{_MODULE}.read_install_stamp", return_value=_BRANCH_STAMP),
            patch(f"{_MODULE}.read_daemon_metadata", return_value=None),
            patch(f"{_MODULE}.list_remote_refs") as listing,
        ):
            text = _context_text(handler.handle(new_session_input))

        listing.assert_not_called()
        assert "not checked" in text.lower()


class TestPinAndReleaseMakeNoNetworkCall:
    def test_a_full_sha_pin_never_moves(
        self, handler: VersionCheckHandler, new_session_input: dict[str, Any], cache_file: Path
    ) -> None:
        pin = _tracking(ref=_OLD_SHA, sha=_OLD_SHA)
        with (
            patch(f"{_MODULE}.read_install_stamp", return_value=_BRANCH_STAMP),
            patch(f"{_MODULE}.read_daemon_metadata", return_value=pin),
            patch(f"{_MODULE}.list_remote_refs") as listing,
        ):
            text = _context_text(handler.handle(new_session_input))

        listing.assert_not_called()
        assert "pinned" in text.lower()

    @patch(f"{_MODULE}.__version__", "2.7.0")
    def test_a_release_install_makes_no_tip_listing(
        self, handler: VersionCheckHandler, new_session_input: dict[str, Any], tmp_path: Path
    ) -> None:
        ls_remote = MagicMock(returncode=0, stdout="abc\trefs/tags/v2.7.0\n", stderr="")
        with (
            patch(f"{_MODULE}.read_install_stamp", return_value=_RELEASE_STAMP),
            patch(f"{_MODULE}.run_git", return_value=ls_remote),
            patch(f"{_MODULE}.list_remote_refs") as listing,
            patch.object(handler, "_get_cache_file", return_value=tmp_path / "cache.json"),
        ):
            handler.handle(new_session_input)

        listing.assert_not_called()


class TestTipLookupIsCached:
    def test_a_second_session_inside_the_ttl_makes_no_second_listing(
        self, handler: VersionCheckHandler, new_session_input: dict[str, Any], cache_file: Path
    ) -> None:
        with (
            patch(f"{_MODULE}.read_install_stamp", return_value=_BRANCH_STAMP),
            patch(f"{_MODULE}.read_daemon_metadata", return_value=_tracking()),
            patch(
                f"{_MODULE}.list_remote_refs", return_value=_listing("rc/1.2.3", _NEW_SHA)
            ) as listing,
        ):
            first = _context_text(handler.handle(new_session_input))
            second = _context_text(handler.handle(new_session_input))

        assert listing.call_count == 1
        assert "moved 1111111..2222222" in second
        assert first == second

    def test_following_a_move_does_not_report_the_old_cached_tip_as_a_move(
        self, handler: VersionCheckHandler, new_session_input: dict[str, Any], cache_file: Path
    ) -> None:
        """A tip cached against one installed commit is not reused for another."""
        with (
            patch(f"{_MODULE}.read_install_stamp", return_value=_BRANCH_STAMP),
            patch(f"{_MODULE}.read_daemon_metadata", return_value=_tracking(sha=_OLD_SHA)),
            patch(f"{_MODULE}.list_remote_refs", return_value=_listing("rc/1.2.3", _OLD_SHA)),
        ):
            handler.handle(new_session_input)
        with (
            patch(f"{_MODULE}.read_install_stamp", return_value=_BRANCH_STAMP),
            patch(f"{_MODULE}.read_daemon_metadata", return_value=_tracking(sha=_NEW_SHA)),
            patch(
                f"{_MODULE}.list_remote_refs", return_value=_listing("rc/1.2.3", _NEW_SHA)
            ) as listing,
        ):
            text = _context_text(handler.handle(new_session_input))

        listing.assert_called_once()
        assert "has not moved" in text
        assert "..1111111" not in text

    def test_a_failed_listing_is_cached_so_an_offline_start_does_not_wait_again(
        self, handler: VersionCheckHandler, new_session_input: dict[str, Any], cache_file: Path
    ) -> None:
        failed = _listing("rc/1.2.3", None, failure="timed out")
        with (
            patch(f"{_MODULE}.read_install_stamp", return_value=_BRANCH_STAMP),
            patch(f"{_MODULE}.read_daemon_metadata", return_value=_tracking()),
            patch(f"{_MODULE}.list_remote_refs", return_value=failed) as listing,
        ):
            first = _context_text(handler.handle(new_session_input))
            second = _context_text(handler.handle(new_session_input))

        assert listing.call_count == 1
        assert "not checked" in first.lower()
        assert "not checked" in second.lower()

    def test_a_failed_listing_expires_sooner_than_a_good_one(
        self, handler: VersionCheckHandler, new_session_input: dict[str, Any], cache_file: Path
    ) -> None:
        def _run(listing_result: RemoteRefs) -> Any:
            with (
                patch(f"{_MODULE}.read_install_stamp", return_value=_BRANCH_STAMP),
                patch(f"{_MODULE}.read_daemon_metadata", return_value=_tracking()),
                patch(f"{_MODULE}.list_remote_refs", return_value=listing_result) as listing,
            ):
                handler.handle(new_session_input)
            return listing

        def _age_cache(seconds: float) -> None:
            entry = json.loads(cache_file.read_text())
            entry["cached_at"] -= seconds
            cache_file.write_text(json.dumps(entry))

        two_hours = 2 * 3600
        _run(_listing("rc/1.2.3", None, failure="timed out"))
        _age_cache(two_hours)
        assert _run(_listing("rc/1.2.3", _NEW_SHA)).call_count == 1  # failure retried

        _age_cache(two_hours)
        assert _run(_listing("rc/1.2.3", _NEW_SHA)).call_count == 0  # good entry still fresh

    def test_a_cache_for_another_ref_is_not_used(
        self, handler: VersionCheckHandler, new_session_input: dict[str, Any], cache_file: Path
    ) -> None:
        with (
            patch(f"{_MODULE}.read_install_stamp", return_value=_BRANCH_STAMP),
            patch(f"{_MODULE}.read_daemon_metadata", return_value=_tracking(ref="rc/1.2.3")),
            patch(f"{_MODULE}.list_remote_refs", return_value=_listing("rc/1.2.3", _NEW_SHA)),
        ):
            handler.handle(new_session_input)
        with (
            patch(f"{_MODULE}.read_install_stamp", return_value=_BRANCH_STAMP),
            patch(f"{_MODULE}.read_daemon_metadata", return_value=_tracking(ref="other")),
            patch(
                f"{_MODULE}.list_remote_refs", return_value=_listing("other", _NEW_SHA)
            ) as listing,
        ):
            handler.handle(new_session_input)

        listing.assert_called_once()

    def test_the_tip_cache_never_shares_the_release_cache_file(
        self, handler: VersionCheckHandler
    ) -> None:
        assert handler._get_cache_file().name != handler._get_cache_file(tip=True).name


class TestReturnRoute:
    def test_the_advisory_names_the_one_step_return(
        self, handler: VersionCheckHandler, new_session_input: dict[str, Any], cache_file: Path
    ) -> None:
        with (
            patch(f"{_MODULE}.read_install_stamp", return_value=_BRANCH_STAMP),
            patch(f"{_MODULE}.read_daemon_metadata", return_value=_tracking()),
            patch(f"{_MODULE}.list_remote_refs", return_value=_listing("rc/1.2.3", _OLD_SHA)),
        ):
            text = _context_text(handler.handle(new_session_input))

        assert "--release" in text
        assert "v3.8.0" in text
