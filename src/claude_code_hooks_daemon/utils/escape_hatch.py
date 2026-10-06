"""Shared hygiene for the daemon's ``MUST_*_BECAUSE`` escape hatches.

Every hatch (``MUST_STASH_BECAUSE``, ``MUST_SQUASH_BECAUSE``,
``MUST_SCAN_ROOT_BECAUSE``, ``MUST_SKIP_SAFE_MODE_BECAUSE``,
``MUST_EXCEED_COMMENT_SIZE_BECAUSE``, ``MUST_EXCEED_PLAN_SIZE_BECAUSE``) is an
ESCAPE from a guard (owner ruling B1, Plan 00483). A reason that is empty, is
only a comment closer, or is a placeholder is not honoured, and the guard then
applies exactly as if no hatch had been written. Rejecting a reason never
creates a deny of its own (owner ruling A1).

The generic-reason check is deliberately small: it cannot judge whether a
reason is TRUE, only that it says something.
"""

from __future__ import annotations

import re
from typing import Final

#: Comment terminators that can trail a reason written inside a comment.
_COMMENT_CLOSERS: Final[tuple[str, ...]] = ("-->", "*/")

#: Placeholder reasons (compared after lower-casing and stripping punctuation).
GENERIC_REASONS: Final[frozenset[str]] = frozenset(
    {
        "because",
        "needed",
        "need",
        "necessary",
        "required",
        "reason",
        "a reason",
        "explain why",
        "why",
        "n/a",
        "na",
        "none",
        "nothing",
        "tbd",
        "todo",
        "test",
        "yes",
        "ok",
    }
)

_EDGE_PUNCTUATION: Final[str] = " \t\r\n\"'`.,;:!?<>()[]{}-_*/"


def is_acceptable_reason(reason: str) -> bool:
    """Whether ``reason`` is specific enough for a hatch to be honoured.

    Args:
        reason: Text after the hatch marker; may still carry a trailing
            comment closer (``-->`` or ``*/``).

    Returns:
        False when the reason is empty, only a comment closer or punctuation,
        or one of the generic placeholders; True otherwise.
    """
    text = reason.strip()
    for closer in _COMMENT_CLOSERS:
        if text.endswith(closer):
            text = text[: -len(closer)]
    stripped = text.strip(_EDGE_PUNCTUATION)
    if not stripped:
        return False
    return stripped.lower() not in GENERIC_REASONS


def in_command_hatch_pattern(marker: str) -> re.Pattern[str]:
    """Pattern capturing the quoted reason of an in-command ``marker="reason"``."""
    return re.compile(rf"""{re.escape(marker)}=["']([^"']+)["']""", re.IGNORECASE)


def command_declares_hatch(command: str, marker: str) -> bool:
    """Whether ``command`` carries ``marker="<specific reason>"``.

    A bare marker, an empty value, or a placeholder reason is not honoured.
    """
    return any(
        is_acceptable_reason(match.group(1))
        for match in in_command_hatch_pattern(marker).finditer(command)
    )
