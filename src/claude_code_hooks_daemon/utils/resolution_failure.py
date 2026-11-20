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
import itertools
from collections.abc import Callable, Sequence
from typing import ParamSpec, TypeVar

from claude_code_hooks_daemon.utils.shell_expansion import TooManyToEnumerateError

_Params = ParamSpec("_Params")
_Result = TypeVar("_Result")


class ResolutionFailedError(Exception):
    """Where a command's words lead could not be worked out; the caller must deny."""


class IncompleteScanError(ResolutionFailedError):
    """A scan a placement depends on stopped before it finished; the caller must deny.

    Independent review of Plan 00614 (D1, D2): a scan that stops early is not
    evidence that what it did not reach is harmless, so it is never logged and
    allowed.
    """


class ProcessViewRefusedError(ResolutionFailedError):
    """A word leads through the calling process's own view (see :data:`_PROCESS_VIEWS`).

    A subclass so the Bash mention scan can tell this refusal from every other
    placement failure and judge it as a mention, in the positions a protected
    name is judged (release review F2). Everywhere else it is a plain
    :class:`ResolutionFailedError`.
    """


#: Raised on purpose by the scan, and judged by their own routes.
_PASSED_THROUGH: tuple[type[BaseException], ...] = (
    TimeoutError,
    TooManyToEnumerateError,
    ResolutionFailedError,
)


#: Adjacent components that name the CALLING process's own view (ledger N668):
#: resolved by the daemon they lead through the daemon's cwd and descriptors,
#: not the shell's, so a word through one cannot be placed.
_PROCESS_VIEWS: frozenset[tuple[str, str]] = frozenset(
    {("proc", "self"), ("proc", "thread-self"), ("dev", "fd")}
)


#: Plain files directly under ``/proc/self`` (and ``thread-self``) that hold no
#: link onward, so naming one places nothing outside it. An allowlist, not a
#: denylist of ``cwd``/``root``/``fd``/...: a link entry a kernel adds later
#: stays unplaceable. ``/dev/fd`` has no such file; every entry is a descriptor.
_PLAIN_PROCESS_FILES: frozenset[str] = frozenset(
    {
        "cgroup",
        "cmdline",
        "comm",
        "io",
        "limits",
        "loginuid",
        "maps",
        "mountinfo",
        "mounts",
        "mountstats",
        "oom_score",
        "oom_score_adj",
        "sched",
        "schedstat",
        "sessionid",
        "smaps",
        "smaps_rollup",
        "stat",
        "statm",
        "status",
        "wchan",
    }
)


def _is_plain_process_file(parts: list[str], view_end: int) -> bool:
    """Whether the ``/proc`` view ending at ``parts[view_end]`` is followed by one plain file and no more."""
    return (
        parts[view_end - 1] == "proc"
        and len(parts) == view_end + 2
        and parts[view_end + 1] in _PLAIN_PROCESS_FILES
    )


def refuse_process_view(path: str) -> None:
    """Raise :class:`ProcessViewRefusedError` when ``path`` passes through ``/proc/self`` and kin.

    ``//`` and ``.`` are collapsed; ``..`` is not, because after a link it
    climbs from where the link leads. ``path`` is the word as placed: a
    relative word is joined to its base first by the caller. The one exception
    is a single plain file directly under ``/proc/self`` (``status``,
    ``cgroup``...), which leads nowhere else; a path that only ENDS at the view
    (``/proc/self``) is still refused, since a later word may be placed under it.
    """
    parts = [part for part in path.split("/") if part not in ("", ".")]
    for index, pair in enumerate(itertools.pairwise(parts), start=1):
        if pair in _PROCESS_VIEWS and not _is_plain_process_file(parts, index):
            raise ProcessViewRefusedError(
                "a path through the calling process's own /proc view cannot be placed"
            )


def fail_closed_finding(patterns: Sequence[str], detail: str) -> tuple[str, str] | None:
    """The finding every guard returns for a :class:`ResolutionFailedError` (Plan 00623).

    One handler for the secret, quarantine and flaggable guards and payload
    capture: a placement that could not finish is reported against the first
    protected pattern, with ``detail`` naming what could not be placed. With no
    pattern nothing is protected, so there is nothing to find.
    """
    return (patterns[0], detail) if patterns else None


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
