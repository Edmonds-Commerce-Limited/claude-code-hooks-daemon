"""Check the handler a report names (Plan 00403 Task 3.2).

The task asked to "surface the named handler's options". Half of that is real
and half rests on a premise that does not hold, and this module does the real
half rather than approximating the other one.

``options cannot be enumerated authoritatively``
    A handler's options are not declared in any schema. They are whatever the
    project's config supplies, read at registration time by
    ``HandlerRegistry.register_all``. There is no list to print, so nothing
    here invents one — the refusal points at
    ``hooks-daemon explain-handler <name>``, which IS the authoritative source,
    and says so plainly. A generated list that looked authoritative and was not
    would be worse than no list, because a reporter would trust it.

``the NAME can be checked, and that is the part with teeth``
    127 handler config keys are machine-readable in
    :class:`~claude_code_hooks_daemon.constants.handlers.HandlerID`. A report
    naming a handler that does not exist is one a maintainer cannot route, and
    the reporter has probably been debugging something other than what they
    think — worth catching before it becomes a public issue rather than after.

A handler is optional: not every defect belongs to one. The daemon has a CLI, a
config loader, a supervisor and an install path, and a report about any of them
names no handler at all.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from typing import Final

from claude_code_hooks_daemon.constants.handlers import HandlerID, HandlerIDMeta

#: How many near-misses to offer. A typo has one likely correction; a list of
#: ten is a way of admitting you do not know which.
_MAX_SUGGESTIONS: Final[int] = 3

#: Minimum similarity for a suggestion to be worth making. Below this the
#: "did you mean" is noise that makes a real refusal harder to read.
_SUGGESTION_CUTOFF: Final[float] = 0.6

_EXPLAIN_HINT: Final[str] = (
    "`hooks-daemon explain-handler <name>` prints that handler's full guidance and the "
    "options it honours — there is no option schema to list from here, so that command is "
    "the authoritative source."
)


@dataclass(frozen=True)
class HandlerVerdict:
    """Whether the handler a report names is one this daemon has.

    Attributes:
        resolved: True when the name matches a known handler, and ALSO when no
            handler was named — an absent name is a legitimate report about
            some other part of the daemon, not a failure.
        detail: What to do next. For a resolved name that is where to read its
            options; for an unresolved one, the nearest real names.
    """

    resolved: bool
    detail: str


def _entries() -> list[HandlerIDMeta]:
    return [value for value in vars(HandlerID).values() if isinstance(value, HandlerIDMeta)]


def known_handler_keys() -> frozenset[str]:
    """Every handler config key this daemon ships.

    Read from the registry rather than hardcoded, so a handler added tomorrow
    is recognised without anyone remembering to update a list here — the
    failure mode of a hardcoded copy is that it silently rejects new handlers,
    which is exactly when a report about one is most likely.
    """
    return frozenset(entry.config_key for entry in _entries())


def _normalise(name: str) -> str:
    """Config keys use underscores; rule IDs and docs use hyphens."""
    return name.strip().lower().replace("-", "_")


def check_handler_name(name: str | None) -> HandlerVerdict:
    """Resolve the handler a report names, or suggest what was meant.

    Args:
        name: The handler as the reporter wrote it, in any of the spellings
            the project uses, or ``None`` when the report names no handler.

    Returns:
        A :class:`HandlerVerdict`. Never raises.
    """
    if name is None or not name.strip():
        return HandlerVerdict(
            resolved=True,
            detail=(
                "No handler named. That is fine — a report can be about the CLI, the "
                "config loader, the installer or the supervisor."
            ),
        )

    keys = known_handler_keys()
    normalised = _normalise(name)
    if normalised in keys:
        return HandlerVerdict(resolved=True, detail=f"Handler `{normalised}`. {_EXPLAIN_HINT}")

    suggestions = difflib.get_close_matches(
        normalised, sorted(keys), n=_MAX_SUGGESTIONS, cutoff=_SUGGESTION_CUTOFF
    )
    if suggestions:
        names = ", ".join(f"`{candidate}`" for candidate in suggestions)
        return HandlerVerdict(
            resolved=False,
            detail=(
                f"This daemon has no handler called `{name}`. Did you mean {names}? "
                "A report naming a handler that does not exist cannot be routed, and "
                "usually means the behaviour came from somewhere else."
            ),
        )

    return HandlerVerdict(
        resolved=False,
        detail=(
            f"This daemon has no handler called `{name}`, and nothing close to it. "
            "`hooks-daemon handlers` lists what is loaded; leave the field empty if the "
            "report is about some other part of the daemon."
        ),
    )
