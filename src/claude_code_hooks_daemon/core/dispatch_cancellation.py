"""Per-dispatch cancellation signal for straggling handler code (Plan 00466 N40 m2).

Plan 00466 N40 M2 releases a timed-out dispatch's capacity the moment the
caller gives up waiting on it (see ``core.bounded_dispatch``), rather than
holding it hostage until the straggler eventually finishes. The straggler
itself keeps running in the background, and a handler still executing at
that point can mutate PROCESS-LIFETIME state for a verdict nobody will ever
see: ``sensitive_content``'s cached dispatch haystack, or
``github_auto_close_keywords``'s disclosure tracker.

A :class:`DispatchCancellation` token is created once per event dispatch
(``HandlerChain.execute``) and bound to a :class:`contextvars.ContextVar` for
the duration of ``HandlerChain._execute_handlers``'s run. Deeply-nested
handler code -- several call frames and, for the direct-call
(``deadline_seconds is None``) path, the SAME thread the caller itself runs
on -- can then call :func:`is_dispatch_cancelled` right before a
state-mutating write, with no signature change threaded through every
intervening call. ``execute()`` calls the token's own ``cancel()`` the
moment it gives up waiting on a straggling dispatch.

Binding is per :class:`contextvars.ContextVar` semantics: it is visible to
everything called SYNCHRONOUSLY from the binding call's own thread (exactly
how a handler's ``matches()``/``handle()`` is invoked, from inside the same
chain loop), and invisible to an unrelated thread with nothing bound of its
own -- so two concurrent dispatches, one abandoned and one fresh, never see
each other's cancellation state.
"""

from __future__ import annotations

import contextvars
import threading


class DispatchCancellation:
    """One dispatch's cancellation flag: starts live, ``cancel()`` is one-way."""

    __slots__ = ("_event",)

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        """Mark this dispatch as abandoned. Idempotent."""
        self._event.set()

    @property
    def is_cancelled(self) -> bool:
        """True once :meth:`cancel` has been called."""
        return self._event.is_set()


_current_dispatch_cancellation: contextvars.ContextVar[DispatchCancellation | None] = (
    contextvars.ContextVar("current_dispatch_cancellation", default=None)
)


def bind_dispatch_cancellation(
    token: DispatchCancellation,
) -> contextvars.Token[DispatchCancellation | None]:
    """Bind ``token`` as the cancellation signal for code called from here on,
    on THIS thread. Returns the reset handle -- callers MUST pass it to
    :func:`reset_dispatch_cancellation` in a ``finally``, so a reused thread
    (the ``deadline_seconds is None`` direct-call path never spawns a new
    one) never leaks one dispatch's token into the next.
    """
    return _current_dispatch_cancellation.set(token)


def reset_dispatch_cancellation(ctx_token: contextvars.Token[DispatchCancellation | None]) -> None:
    """Undo :func:`bind_dispatch_cancellation`. See its own docstring."""
    _current_dispatch_cancellation.reset(ctx_token)


def is_dispatch_cancelled() -> bool:
    """True when the dispatch currently bound on THIS thread has been
    abandoned by its caller. False with no token bound at all -- every
    caller that predates this mechanism, and a handler under test in
    isolation, keep their pre-existing behaviour.
    """
    token = _current_dispatch_cancellation.get()
    return token.is_cancelled if token is not None else False
