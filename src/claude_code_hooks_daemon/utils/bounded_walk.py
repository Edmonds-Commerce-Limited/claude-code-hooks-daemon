"""One result type for every walk that may stop before it finishes (Plan 00623).

The secret and flaggable guards place a command's words with bounded walks:
the project link scan, the directory glob walk, the placement stat and the
nested-body walkers. Each used to say "I stopped" in its own way -- a ``None``,
an empty list, a ``complete`` flag, or a silent ``return`` -- and a caller that
read one of those as "nothing found" allowed what it never looked at.

A walk now returns :class:`Bounded`. ``complete`` says whether it finished;
``reason`` says why not. A caller that needs the whole answer calls
:meth:`Bounded.required`, which raises
:class:`~claude_code_hooks_daemon.utils.resolution_failure.IncompleteScanError`
for an unfinished walk, and every guard denies that error.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

from claude_code_hooks_daemon.utils.resolution_failure import IncompleteScanError

_Value = TypeVar("_Value")


@dataclass(frozen=True)
class Bounded(Generic[_Value]):
    """What a bounded walk found, and whether it looked everywhere it had to."""

    value: _Value
    complete: bool
    #: Why the walk stopped; empty exactly when it finished.
    reason: str = ""

    def __post_init__(self) -> None:
        if self.complete and self.reason:
            raise ValueError("a finished walk has no reason to report")
        if not self.complete and not self.reason:
            raise ValueError("a walk that stopped must say why")

    def required(self) -> _Value:
        """The value, when the walk finished; else :class:`IncompleteScanError`."""
        if not self.complete:
            raise IncompleteScanError(self.reason)
        return self.value


def finished(value: _Value) -> Bounded[_Value]:
    """A walk that reached everything it had to."""
    return Bounded(value=value, complete=True)


def stopped(value: _Value, reason: str) -> Bounded[_Value]:
    """A walk that stopped early: ``value`` is what it found before ``reason`` stopped it."""
    return Bounded(value=value, complete=False, reason=reason)
