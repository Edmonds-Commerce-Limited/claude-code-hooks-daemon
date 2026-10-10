"""Reasons on config exceptions (Plan 00484 G4, owner ruling B3).

An entry of ``exclude_paths`` or ``extra_whitelist`` is an exception to a guard.
It is written either as a plain string, or as a mapping carrying why the
exception exists::

    exclude_paths:
      - "legacy/**"                                   # plain, always accepted
      - pattern: "vendor/**"                          # reasoned
        reason: "third-party code we do not edit"

Both forms are normalised once, at config load, to the plain pattern, so no
handler ever sees the mapping. A reason is checked with the same hygiene as the
``MUST_*_BECAUSE`` hatches: a placeholder is rejected (a config error, not a
silent drop, because a config is not an input a guard can fall back from).
Under ``daemon.strict_mode`` a plain string loads and is reported as a warning
(``Config.config_problems``, shown by the SessionStart config-problem advisory);
a reason is required of everyone at the next major.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from claude_code_hooks_daemon.utils.escape_hatch import is_acceptable_reason

#: Handler option keys whose entries are exceptions and may carry a reason.
EXCEPTION_OPTION_KEYS: Final[tuple[str, ...]] = ("exclude_paths", "extra_whitelist")

_PATTERN_KEY: Final[str] = "pattern"
_REASON_KEY: Final[str] = "reason"


@dataclass(frozen=True)
class NormalisedExceptions:
    """The plain patterns of an exception list, and which of them had no reason."""

    patterns: list[str]
    unreasoned: list[str]


def entry_pattern(entry: object) -> str:
    """The pattern of one entry, whichever form it is written in."""
    if isinstance(entry, Mapping):
        return str(entry.get(_PATTERN_KEY, ""))
    return str(entry)


def normalise_exception_entries(entries: list[Any], *, where: str) -> NormalisedExceptions:
    """Reduce ``entries`` to plain patterns, validating every mapping entry.

    Args:
        entries: The configured list, each item a string or a
            ``{pattern, reason}`` mapping.
        where: Config location, named in any error.

    Raises:
        ValueError: An item is neither form, a mapping has an unknown key or no
            pattern, or its reason is missing or a placeholder.
    """
    patterns: list[str] = []
    unreasoned: list[str] = []
    for entry in entries:
        if isinstance(entry, str):
            patterns.append(entry)
            unreasoned.append(entry)
        elif isinstance(entry, Mapping):
            patterns.append(_pattern_of_mapping(entry, where))
        else:
            raise ValueError(
                f"{where}: entry {entry!r} must be a string or a "
                f"{{pattern, reason}} mapping, got {type(entry).__name__}"
            )
    return NormalisedExceptions(patterns=patterns, unreasoned=unreasoned)


def _pattern_of_mapping(entry: Mapping[str, Any], where: str) -> str:
    unknown = sorted(set(entry) - {_PATTERN_KEY, _REASON_KEY})
    if unknown:
        raise ValueError(f"{where}: entry has unknown key(s) {unknown}; expected pattern, reason")
    pattern = entry.get(_PATTERN_KEY)
    if not isinstance(pattern, str) or not pattern:
        raise ValueError(f"{where}: entry {dict(entry)!r} needs a non-empty string 'pattern'")
    reason = entry.get(_REASON_KEY)
    if not isinstance(reason, str) or not is_acceptable_reason(reason):
        raise ValueError(
            f"{where}: entry {pattern!r} needs a specific 'reason' saying why it is "
            f"exempt (got {reason!r}); a placeholder such as 'tbd' or 'because' is not a reason"
        )
    return pattern


def plain_patterns(value: Any, *, where: str) -> Any:
    """``value`` with mapping entries reduced to patterns; a non-list is returned untouched."""
    if not isinstance(value, list):
        return value
    return normalise_exception_entries(value, where=where).patterns


def unreasoned_entries(value: Any, *, where: str) -> list[str]:
    """The plain-string entries of ``value``; empty for a non-list."""
    if not isinstance(value, list):
        return []
    return normalise_exception_entries(value, where=where).unreasoned
