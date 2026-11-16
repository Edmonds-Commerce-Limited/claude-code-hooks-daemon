"""A failure while working out where a command's words lead is a finding, not an allow.

Review 614b (Plan 00614): a ``cd`` to a name the filesystem refuses to stat made
``Path.is_dir()`` raise inside the directory walk, and the raise reached the
secret guard's catch-all, which allows the call with an advisory (Plan 00483 A1:
an internal error never denies). Every protected read in the same command then
went unjudged. The functions that PLACE a command's words -- the directories it
moves through, where a link leads, what a glob reaches -- are wrapped in
:func:`fails_closed`, so a raise there surfaces as :class:`ResolutionFailedError`
and the guard denies instead.

The scan's own limits are not failures of placement and pass through unchanged:
a deadline (``TimeoutError``) and an expansion cap
(:class:`~claude_code_hooks_daemon.utils.shell_expansion.TooManyToEnumerateError`)
keep their advisory routes.
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import ParamSpec, TypeVar

from claude_code_hooks_daemon.utils.shell_expansion import TooManyToEnumerateError

_Params = ParamSpec("_Params")
_Result = TypeVar("_Result")


class ResolutionFailedError(Exception):
    """Where a command's words lead could not be worked out; the caller must deny."""


#: Raised on purpose by the scan, and judged by their own routes.
_PASSED_THROUGH: tuple[type[BaseException], ...] = (
    TimeoutError,
    TooManyToEnumerateError,
    ResolutionFailedError,
)


def fails_closed(function: Callable[_Params, _Result]) -> Callable[_Params, _Result]:
    """``function``, with any unexpected ``Exception`` re-raised as :class:`ResolutionFailedError`."""

    @functools.wraps(function)
    def wrapper(*args: _Params.args, **kwargs: _Params.kwargs) -> _Result:
        try:
            return function(*args, **kwargs)
        except _PASSED_THROUGH:
            raise
        except Exception as exc:
            raise ResolutionFailedError(
                f"{function.__qualname__} raised {type(exc).__name__}"
            ) from exc

    return wrapper
