"""Shared typed-coercion helpers for blind-``setattr`` YAML handler options.

Handler options arrive from ``hooks-daemon.yaml`` by blind ``setattr``
(``handlers/registry.py``), so a handler's ``_threshold``/``_strict``-style
attribute is typed ``Any`` and its own accessor must not trust the runtime
type: a YAML author can write a string where an int or bool is expected, and
the handler must degrade to its own default rather than raise or misbehave.

Before this module, that guard was hand-rolled independently at three call
sites -- ``dispatch_declaration._is_strict()``, ``bash_safe_mode._threshold()``
and ``subagent_report_size_blocker._threshold()`` -- and had already drifted:
the int coercions disagreed with each other on whether a numeric STRING
(``"4000"``) should be parsed. Both directions were already fail-safe (a
malformed value always degrades to the caller's own default, never raises),
so unifying them here is a maintenance-cost fix, not a correctness one.
"""

from __future__ import annotations

_TRUE_STRING: str = "true"
_FALSE_STRING: str = "false"


def coerce_bool_option(value: object, *, default: bool) -> bool:
    """Coerce a blind-``setattr`` option to ``bool``.

    A real ``bool`` is used as-is. A string is matched case-insensitively
    against ``"true"``/``"false"``. Anything else -- including a plausible
    but unrecognised spelling such as ``"yes"`` or ``"1"`` -- degrades to
    ``default`` rather than surprising the caller with unintended
    enforcement.

    Args:
        value: The raw attribute value, of untrusted runtime type.
        default: Returned for anything not recognised as a real or
            string-spelled boolean.

    Returns:
        The coerced boolean.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized == _TRUE_STRING:
            return True
        if normalized == _FALSE_STRING:
            return False
    return default


def coerce_int_option(value: object, *, default: int, minimum: int = 1) -> int:
    """Coerce a blind-``setattr`` option to ``int``.

    A real ``int`` at or above ``minimum`` is used as-is -- ``bool`` is
    explicitly excluded despite being an ``int`` subclass in Python, so a
    stray ``True``/``False`` is never silently read as ``1``/``0``. A
    numeric string is parsed the same way. Anything else -- a non-numeric
    string, a float, ``None``, a list -- degrades to ``default``.

    Args:
        value: The raw attribute value, of untrusted runtime type.
        default: Returned for anything not recognised as a valid int at or
            above ``minimum``.
        minimum: The smallest value accepted as-is (default ``1``, matching
            every call site this helper was extracted from).

    Returns:
        The coerced integer.
    """
    if isinstance(value, bool):
        return default
    if isinstance(value, int) and value >= minimum:
        return value
    if isinstance(value, str):
        try:
            parsed = int(value.strip())
        except ValueError:
            return default
        if parsed >= minimum:
            return parsed
    return default
