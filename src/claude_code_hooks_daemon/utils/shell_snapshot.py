"""Which glob options the Bash tool's shell runs with, read from its snapshots (#142).

Claude Code starts the Bash tool's shell from a snapshot of the user's profile
(``<config dir>/shell-snapshots/snapshot-bash-*.sh``), and that snapshot records
the user's ``shopt`` state. A bare ``**`` only recurses, and only reaches hidden
names, when ``globstar`` and ``dotglob`` are on; with both off (bash's default)
it expands like ``*``.

The hook payload names no snapshot and nothing inside one names a session, so
the running shell's own snapshot cannot be picked out. The verdict is therefore
the narrow one the owner ruled: bash's default expansion is assumed only when
EVERY readable snapshot records both options as off. Any snapshot that turns
either on, that cannot be read, that does not record both, or no snapshot at
all, leaves the caller on the conservative reading. So does a command that
runs ``shopt`` or ``set -O`` itself, since it may switch the options on for its
own run.
"""

from __future__ import annotations

import logging
import os
import re
import threading
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.utils.claude_config import claude_config_dir
from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue

logger = logging.getLogger(__name__)

#: The config directory's subdirectory holding the snapshots.
SNAPSHOT_DIRNAME: Final[str] = "shell-snapshots"

#: At most this many snapshots are read, newest first. The directory accumulates
#: one file per shell start; beyond the cap the older ones are not read, so a
#: stale file from long ago cannot pin the verdict and the cost stays bounded.
MAX_SNAPSHOTS_READ: int = 200

_GLOB_OPTIONS: Final[tuple[str, ...]] = ("globstar", "dotglob")
_SHOPT_LINE: Final[re.Pattern[str]] = re.compile(
    r"^[ \t]*shopt[ \t]+-(?P<state>[su])[ \t]+(?P<option>globstar|dotglob)[ \t]*$", re.MULTILINE
)
#: A command that can change the options for its own run: ``shopt ...``, ``set -O ...``,
#: ``bash -O ...``.
_SWITCHES_OPTIONS: Final[re.Pattern[str]] = re.compile(r"\bshopt\b|(?<!\S)[-+]O\b")

_Signature = tuple[int, tuple[tuple[str, int], ...]]

_lock = threading.Lock()
_cache: dict[str, tuple[_Signature, bool]] = {}


def reset_snapshot_cache() -> None:
    """Forget every cached verdict (tests, and a daemon restart)."""
    with _lock:
        _cache.clear()


def default_glob_semantics(command: str, *, config_dir: Path | None = None) -> bool:
    """Is a bare ``**`` in ``command`` expanded by bash's defaults (like ``*``)?

    ``config_dir`` defaults to Claude Code's own (:func:`claude_config_dir`).
    ``False`` is the conservative answer and is returned whenever the question
    cannot be answered with certainty.
    """
    if _SWITCHES_OPTIONS.search(command):
        return False
    directory = (config_dir if config_dir is not None else claude_config_dir()) / SNAPSHOT_DIRNAME
    return _snapshots_all_off(directory)


def _snapshots_all_off(directory: Path) -> bool:
    try:
        signature, newest = _signature(directory)
    except OSError as error:
        log_and_continue(
            logger,
            error,
            reason=f"shell snapshots unreadable in {directory}: conservative reading applies",
            level=logging.DEBUG,
        )
        return False
    key = str(directory)
    with _lock:
        cached = _cache.get(key)
    if cached is not None and cached[0] == signature:
        return cached[1]
    verdict = bool(newest) and all(_records_both_off(directory / name) for name in newest)
    with _lock:
        _cache[key] = (signature, verdict)
    return verdict


def _signature(directory: Path) -> tuple[_Signature, list[str]]:
    """The directory's mtime with the (name, mtime) of the newest snapshots, and their names."""
    directory_mtime = directory.stat().st_mtime_ns
    entries = []
    with os.scandir(directory) as scan:
        for entry in scan:
            if entry.is_file():
                entries.append((entry.stat().st_mtime_ns, entry.name))
    entries.sort(reverse=True)
    if len(entries) > MAX_SNAPSHOTS_READ:
        logger.debug(
            "%d shell snapshots in %s: reading only the newest %d",
            len(entries),
            directory,
            MAX_SNAPSHOTS_READ,
        )
        entries = entries[:MAX_SNAPSHOTS_READ]
    return (directory_mtime, tuple((name, mtime) for mtime, name in entries)), [
        name for _, name in entries
    ]


def _records_both_off(path: Path) -> bool:
    """Does the snapshot record ``globstar`` and ``dotglob`` as off, and neither as on?"""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        log_and_continue(
            logger,
            error,
            reason=f"shell snapshot {path} unreadable: the conservative glob reading applies",
            level=logging.DEBUG,
        )
        return False
    states: dict[str, set[str]] = {option: set() for option in _GLOB_OPTIONS}
    for match in _SHOPT_LINE.finditer(text):
        states[match.group("option")].add(match.group("state"))
    return all(states[option] == {"u"} for option in _GLOB_OPTIONS)
