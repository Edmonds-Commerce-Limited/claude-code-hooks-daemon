"""Tests for UpgradeNotifierHandler.

Extracted from DaemonStatsHandler's "Upgrade indicator" block (Plan 00167) so
the upgrade prompt reaches every client on-by-default, independent of the
off-by-default developer health line. Reads the version_check_cache.json
produced by the SessionStart version_check handler and reproduces the
daemon_stats upgrade logic exactly: is_outdated + stale-cache defense.
"""

import json
from pathlib import Path
from unittest.mock import patch

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.handlers.status_line.upgrade_notifier import (
    UpgradeNotifierHandler,
)

_DAEMON_UNTRACKED_DIR_PATCH = (
    "claude_code_hooks_daemon.handlers.status_line.upgrade_notifier."
    "ProjectContext.daemon_untracked_dir"
)
_VERSION_PATCH = "claude_code_hooks_daemon.version.__version__"


def _write_cache(tmp_path: Path, **data: object) -> Path:
    cache_file = tmp_path / "version_check_cache.json"
    cache_file.write_text(json.dumps(data))
    return cache_file


class TestUpgradeNotifierInit:
    def test_identity_and_flags(self) -> None:
        handler = UpgradeNotifierHandler()
        assert handler.handler_id == HandlerID.UPGRADE_NOTIFIER
        assert handler.priority == Priority.UPGRADE_NOTIFIER
        assert handler.terminal is False
        assert HandlerTag.STATUSLINE in handler.tags
        assert HandlerTag.NON_TERMINAL in handler.tags

    def test_default_enabled(self) -> None:
        assert UpgradeNotifierHandler().get_default_enabled() is True

    def test_matches_always_true(self) -> None:
        assert UpgradeNotifierHandler().matches({}) is True

    def test_get_claude_md_is_none(self) -> None:
        assert UpgradeNotifierHandler().get_claude_md() is None

    def test_get_acceptance_tests_nonempty(self) -> None:
        assert len(UpgradeNotifierHandler().get_acceptance_tests()) >= 1


class TestUpgradeNotifierDetection:
    def test_emits_arrow_when_outdated_and_current_matches_running_version(
        self, tmp_path: Path
    ) -> None:
        _write_cache(
            tmp_path,
            is_outdated=True,
            current_version="1.0.0",
            latest_version="2.0.0",
        )
        handler = UpgradeNotifierHandler()
        with (
            patch(_DAEMON_UNTRACKED_DIR_PATCH, return_value=tmp_path),
            patch(_VERSION_PATCH, "1.0.0"),
        ):
            result = handler.handle({})
        assert result.context == ["📦 v1.0.0 → v2.0.0"]

    def test_emits_generic_arrow_when_no_current_version_recorded(self, tmp_path: Path) -> None:
        _write_cache(tmp_path, is_outdated=True, latest_version="2.0.0")
        handler = UpgradeNotifierHandler()
        with (
            patch(_DAEMON_UNTRACKED_DIR_PATCH, return_value=tmp_path),
            patch(_VERSION_PATCH, "1.0.0"),
        ):
            result = handler.handle({})
        assert result.context == ["📦 upgrade → v2.0.0"]

    def test_emits_nothing_when_cached_current_version_is_stale(self, tmp_path: Path) -> None:
        # Cache from before an upgrade already happened: cached current_version
        # no longer matches the running __version__ -- ignore it.
        _write_cache(
            tmp_path,
            is_outdated=True,
            current_version="0.9.0",
            latest_version="2.0.0",
        )
        handler = UpgradeNotifierHandler()
        with (
            patch(_DAEMON_UNTRACKED_DIR_PATCH, return_value=tmp_path),
            patch(_VERSION_PATCH, "1.0.0"),
        ):
            result = handler.handle({})
        assert result.context == []

    def test_emits_nothing_when_cache_file_missing(self, tmp_path: Path) -> None:
        handler = UpgradeNotifierHandler()
        with patch(_DAEMON_UNTRACKED_DIR_PATCH, return_value=tmp_path):
            result = handler.handle({})
        assert result.context == []

    def test_emits_nothing_when_not_outdated(self, tmp_path: Path) -> None:
        _write_cache(
            tmp_path,
            is_outdated=False,
            current_version="1.0.0",
            latest_version="1.0.0",
        )
        handler = UpgradeNotifierHandler()
        with (
            patch(_DAEMON_UNTRACKED_DIR_PATCH, return_value=tmp_path),
            patch(_VERSION_PATCH, "1.0.0"),
        ):
            result = handler.handle({})
        assert result.context == []

    def test_fail_safe_on_malformed_cache_json(self, tmp_path: Path) -> None:
        cache_file = tmp_path / "version_check_cache.json"
        cache_file.write_text("{not valid json")
        handler = UpgradeNotifierHandler()
        with patch(_DAEMON_UNTRACKED_DIR_PATCH, return_value=tmp_path):
            result = handler.handle({})
        assert result.context == []

    def test_fail_safe_on_unexpected_exception(self, tmp_path: Path) -> None:
        handler = UpgradeNotifierHandler()
        with patch(_DAEMON_UNTRACKED_DIR_PATCH, side_effect=RuntimeError("boom")):
            result = handler.handle({})
        assert result.context == []
