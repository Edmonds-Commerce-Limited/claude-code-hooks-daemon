"""Path predicates that cannot raise, and cannot silently pick a side.

``pathlib`` treats a small set of stat failures as "the answer is no": ENOENT,
ENOTDIR, EBADF and ELOOP are swallowed and the predicate returns ``False``.
**EACCES is not in that set.** So ``Path.exists()``, ``Path.is_file()`` and
``Path.is_dir()`` all raise ``PermissionError`` when any directory in the parent
chain lacks ``+x`` for the daemon's user.

Handlers call those predicates on paths taken straight from a user's tool input.
The daemon has no say in whether it can stat them, and ``chain.py`` catching the
raise does not rescue it: with ``strict_mode: false`` (the client default) the
handler's guard silently stops applying, and with ``strict_mode: true`` it
becomes a spurious DENY on legitimate work.

Why the fallback is a required argument
---------------------------------------

The first design here was a single canonical answer -- treat an unstattable path
as not-a-directory, mirroring what pathlib does for the failures it already
ignores. Plan 00347's classification of all 73 call sites falsified that.
``write_clobber_guard.matches()`` reads::

    # Creating a new file destroys nothing.
    if not Path(path).is_file():
        return False

A ``False`` there means "not a file" means "nothing to destroy", so the guard
declines to fire and the clobber it exists to prevent is allowed. The safe
answer at that site is ``True``. At ``comment_size`` it is ``False``. At
``plan_qa_edit`` no boolean is safe at all, because a downstream consumer tests
``is not True`` and so is disabled by ``False`` and ``None`` alike.

A default would therefore be one guess, made in this file, on behalf of call
sites that provably disagree -- and it would read as principled while inverting
a DENY guard. ``unreadable_means`` is keyword-only and has no default so that
the choice, and the reasoning behind it, is visible in review at every site.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

logger = logging.getLogger(__name__)

_Fallback = TypeVar("_Fallback")


@dataclass(frozen=True)
class TextOrReason:
    """A file's text, or the reason there is none -- never both, never neither.

    ``text`` of ``""`` is a real answer (an empty file) and is NOT the same as
    ``None``; callers testing truthiness would agree with the failure case, so
    ``reason`` is what separates them.
    """

    text: str | None = None
    reason: str | None = None


def read_text_or_reason(path: str | Path, *, encoding: str = "utf-8") -> TextOrReason:
    """Read ``path``, carrying any failure back as a reason rather than raising.

    The read counterpart of the predicates below, for the same reason: a
    handler that raises at session start or on a tool call costs the whole
    response, and one that swallows the error cannot explain its own silence
    afterwards. Returning a bare ``None`` collapsed "absent" and "unreadable"
    into one fact, and a ``return None`` inside an ``except`` body is error
    hiding, which this project's own audit denies.
    """
    try:
        return TextOrReason(text=Path(path).read_text(encoding=encoding))
    except OSError as exc:
        logger.debug("read_text_or_reason: %s unreadable: %s", path, exc)
        return TextOrReason(reason=str(exc))


def _answer_or_fallback(
    path: str | Path,
    predicate_name: str,
    fallback: _Fallback,
) -> bool | _Fallback:
    """Run ``Path.<predicate_name>()``, substituting ``fallback`` on a raise.

    Only the failures pathlib does NOT already ignore reach the handler below --
    a missing path answers ``False`` through the normal return, never through
    the fallback. "Not there" and "could not look" are different facts, and a
    guard that conflates them is telling a louder lie than the one this fixes.
    """
    try:
        return bool(getattr(Path(path), predicate_name)())
    except OSError as exc:
        # Logged, not swallowed. Without a record, "the guard decided no" and
        # "the guard could not look" are indistinguishable to whoever asks why
        # a policy did not fire -- which is the silent-fallback antipattern
        # this repo's own error-hiding auditor exists to catch.
        logger.warning(
            "Could not stat %r for %s (%s) -- assuming %r. A guard keyed on "
            "this path is answering from an assumption, not an observation.",
            str(path),
            predicate_name,
            exc,
            fallback,
        )
        return fallback


def path_exists(path: str | Path, *, unreadable_means: _Fallback) -> bool | _Fallback:
    """``Path.exists()`` that answers ``unreadable_means`` instead of raising.

    Args:
        path: The path to test. Typically caller-supplied, hence the guard.
        unreadable_means: The answer this call site wants when the path cannot
            be stat'ed. Required, and keyword-only: see the module docstring for
            why no default is safe.
    """
    return _answer_or_fallback(path, "exists", unreadable_means)


def path_is_file(path: str | Path, *, unreadable_means: _Fallback) -> bool | _Fallback:
    """``Path.is_file()`` that answers ``unreadable_means`` instead of raising.

    Args:
        path: The path to test. Typically caller-supplied, hence the guard.
        unreadable_means: The answer this call site wants when the path cannot
            be stat'ed. Required, and keyword-only: see the module docstring for
            why no default is safe.
    """
    return _answer_or_fallback(path, "is_file", unreadable_means)


def path_is_dir(path: str | Path, *, unreadable_means: _Fallback) -> bool | _Fallback:
    """``Path.is_dir()`` that answers ``unreadable_means`` instead of raising.

    Args:
        path: The path to test. Typically caller-supplied, hence the guard.
        unreadable_means: The answer this call site wants when the path cannot
            be stat'ed. Required, and keyword-only: see the module docstring for
            why no default is safe.
    """
    return _answer_or_fallback(path, "is_dir", unreadable_means)
