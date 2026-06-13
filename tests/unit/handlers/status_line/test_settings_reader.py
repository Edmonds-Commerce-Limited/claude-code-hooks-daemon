"""Tests for the shared, mtime-cached Claude settings reader.

Both ThinkingModeHandler and ModelContextHandler read ~/.claude/settings.json on
every status-line render. This shared reader parses once and re-parses only when
the file's mtime changes, so the status line does no redundant per-render work.
"""

import json
from pathlib import Path

import pytest

from claude_code_hooks_daemon.handlers.status_line import settings_reader


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    """Ensure each test starts with an empty module-level cache."""
    settings_reader.clear_settings_cache()


class TestReadClaudeSettings:
    """read_claude_settings parses the settings file with mtime caching."""

    def test_reads_and_parses_settings(self, tmp_path: Path) -> None:
        """A valid JSON object is parsed and returned."""
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(json.dumps({"effortLevel": "high"}))

        result = settings_reader.read_claude_settings(settings_file)

        assert result == {"effortLevel": "high"}

    def test_missing_file_returns_empty_dict(self, tmp_path: Path) -> None:
        """A non-existent file yields an empty dict, never raises."""
        result = settings_reader.read_claude_settings(tmp_path / "nope.json")

        assert result == {}

    def test_invalid_json_returns_empty_dict(self, tmp_path: Path) -> None:
        """Malformed JSON yields an empty dict, never raises."""
        settings_file = tmp_path / "settings.json"
        settings_file.write_text("{not valid json")

        result = settings_reader.read_claude_settings(settings_file)

        assert result == {}

    def test_non_object_json_returns_empty_dict(self, tmp_path: Path) -> None:
        """Top-level JSON that is not an object yields an empty dict."""
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(json.dumps([1, 2, 3]))

        result = settings_reader.read_claude_settings(settings_file)

        assert result == {}

    def test_cached_result_avoids_reparse(self, tmp_path: Path) -> None:
        """A second call with unchanged mtime does not re-read the file."""
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(json.dumps({"effortLevel": "low"}))

        first = settings_reader.read_claude_settings(settings_file)

        # Delete the file but keep the same path; cached value must persist
        # because we never re-stat past the cache hit... but we DO stat each
        # call, so deletion would miss. Instead, mutate content WITHOUT
        # changing mtime to prove the parse was skipped.
        original_mtime_ns = settings_file.stat().st_mtime_ns
        settings_file.write_text(json.dumps({"effortLevel": "high"}))
        import os

        os.utime(settings_file, ns=(original_mtime_ns, original_mtime_ns))

        second = settings_reader.read_claude_settings(settings_file)

        assert first == {"effortLevel": "low"}
        assert second == {"effortLevel": "low"}  # cache hit, not re-parsed

    def test_mtime_change_triggers_reparse(self, tmp_path: Path) -> None:
        """A changed mtime invalidates the cache and re-reads the file."""
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(json.dumps({"effortLevel": "low"}))
        first = settings_reader.read_claude_settings(settings_file)

        # Rewrite with a newer mtime
        import os

        new_mtime_ns = settings_file.stat().st_mtime_ns + 1_000_000_000
        settings_file.write_text(json.dumps({"effortLevel": "high"}))
        os.utime(settings_file, ns=(new_mtime_ns, new_mtime_ns))

        second = settings_reader.read_claude_settings(settings_file)

        assert first == {"effortLevel": "low"}
        assert second == {"effortLevel": "high"}

    def test_default_path_is_home_claude_settings(self) -> None:
        """get_settings_path resolves to ~/.claude/settings.json."""
        path = settings_reader.get_settings_path()

        assert path == Path.home() / ".claude" / "settings.json"

    def test_clear_settings_cache_empties_cache(self, tmp_path: Path) -> None:
        """clear_settings_cache forces a re-read on the next call."""
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(json.dumps({"effortLevel": "low"}))
        settings_reader.read_claude_settings(settings_file)

        settings_reader.clear_settings_cache()

        # Mutate without changing mtime; after clear the file is re-read
        original_mtime_ns = settings_file.stat().st_mtime_ns
        settings_file.write_text(json.dumps({"effortLevel": "high"}))
        import os

        os.utime(settings_file, ns=(original_mtime_ns, original_mtime_ns))

        result = settings_reader.read_claude_settings(settings_file)

        assert result == {"effortLevel": "high"}
