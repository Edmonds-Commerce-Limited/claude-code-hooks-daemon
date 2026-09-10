"""Plan 00291 Task 3.3 — ``version_check`` never calls a branch install current.

A guarded branch install is stamped ``vX.Y.Z+<ref>.<sha>``. On every new
session the handler must say so and point at a release-tag reinstall. It
must not compare versions, consult the cache or touch the network for such
an install, because any of those could answer "up to date".
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from claude_code_hooks_daemon.core.hook_result import Decision
from claude_code_hooks_daemon.handlers.session_start.version_check import VersionCheckHandler
from claude_code_hooks_daemon.install.install_stamp import InstallStamp

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
