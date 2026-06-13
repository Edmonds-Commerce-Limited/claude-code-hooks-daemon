"""Shared, mtime-cached reader for ``~/.claude/settings.json``.

Both :class:`ThinkingModeHandler` and :class:`ModelContextHandler` need values
out of the user's Claude settings on every status-line render. The status line
re-renders on every Claude Code refresh, so parsing the file each time is
wasteful. This module parses once and re-parses only when the file's mtime
changes — a cheap ``stat()`` per call replaces a full read + JSON parse.

Caching is keyed by resolved path string with a single entry per path (the
newest mtime wins), so the cache stays bounded in a long-running daemon.
"""

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_CLAUDE_DIR = ".claude"
_SETTINGS_FILENAME = "settings.json"

# path string -> (mtime_ns, parsed settings dict). One entry per distinct path.
_settings_cache: dict[str, tuple[int, dict[str, Any]]] = {}


def get_settings_path() -> Path:
    """Return the canonical Claude settings path (``~/.claude/settings.json``)."""
    return Path.home() / _CLAUDE_DIR / _SETTINGS_FILENAME


def clear_settings_cache() -> None:
    """Empty the module-level cache (used by tests for isolation)."""
    _settings_cache.clear()


def read_claude_settings(settings_path: Path | None = None) -> dict[str, Any]:
    """Read and parse the Claude settings file, caching by mtime.

    Args:
        settings_path: Explicit settings path. Defaults to ``get_settings_path()``.

    Returns:
        The parsed settings object, or an empty dict if the file is missing,
        unreadable, not valid JSON, or not a JSON object. Never raises.
    """
    path = settings_path if settings_path is not None else get_settings_path()

    try:
        mtime_ns = path.stat().st_mtime_ns
    except OSError:
        logger.debug("Claude settings file not accessible: %s", path)
        return {}

    path_key = str(path)
    cached = _settings_cache.get(path_key)
    if cached is not None and cached[0] == mtime_ns:
        return cached[1]

    try:
        parsed = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        logger.debug("Cannot parse Claude settings %s: %s", path, exc)
        return {}

    if not isinstance(parsed, dict):
        logger.debug("Claude settings %s is not a JSON object", path)
        return {}

    result: dict[str, Any] = parsed
    _settings_cache[path_key] = (mtime_ns, result)
    return result
