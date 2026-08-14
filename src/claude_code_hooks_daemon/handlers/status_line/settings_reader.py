"""Shared, mtime-cached reader for ``~/.claude/settings.json``.

:class:`ModelContextHandler` needs values out of the user's Claude settings on
every status-line render. The status line re-renders on every Claude Code
refresh, so parsing the file each time is wasteful. This module parses once
and re-parses only when the file's mtime changes — a cheap ``stat()`` per call
replaces a full read + JSON parse.

The gate itself lives in ``mtime_cache.py``. It started here, and Plan 00238
moved it out when three sibling handlers turned out to need the same thing:
copying it four times would have meant four places to fix one bug. This module
is now just the settings-specific parts — where the file is and what counts as
a valid document.
"""

import json
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.handlers.status_line.mtime_cache import MtimeCachedFile

_CLAUDE_DIR = ".claude"
_SETTINGS_FILENAME = "settings.json"


def _parse_settings(content: str) -> dict[str, Any]:
    """Parse the settings document, rejecting anything but a JSON object."""
    parsed = json.loads(content)
    if not isinstance(parsed, dict):
        raise ValueError("Claude settings is not a JSON object")
    result: dict[str, Any] = parsed
    return result


_settings_reader: MtimeCachedFile[dict[str, Any]] = MtimeCachedFile(
    parse=_parse_settings,
    default={},
)


def get_settings_path() -> Path:
    """Return the canonical Claude settings path (``~/.claude/settings.json``)."""
    return Path.home() / _CLAUDE_DIR / _SETTINGS_FILENAME


def clear_settings_cache() -> None:
    """Empty the module-level cache (used by tests for isolation)."""
    _settings_reader.clear()


def read_claude_settings(settings_path: Path | None = None) -> dict[str, Any]:
    """Read and parse the Claude settings file, caching by mtime.

    Args:
        settings_path: Explicit settings path. Defaults to ``get_settings_path()``.

    Returns:
        The parsed settings object, or an empty dict if the file is missing,
        unreadable, not valid JSON, or not a JSON object. Never raises.
    """
    path = settings_path if settings_path is not None else get_settings_path()
    return _settings_reader.read(path)
