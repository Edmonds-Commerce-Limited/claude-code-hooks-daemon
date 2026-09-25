"""Tests for core.dispatch_cancellation (Plan 00466 N40 m2).

A straggling ``HandlerChain._execute_handlers`` call keeps running on its
own thread after the caller has already given up on it (Plan 00466 N40 M2's
"release the slot" fix means the caller no longer even WAITS for it). A
handler still running at that point can mutate PROCESS-LIFETIME state
(``sensitive_content``'s cached dispatch, ``github_auto_close_keywords``'s
disclosure tracker) for a verdict nobody will ever see. A
``DispatchCancellation`` token, created once per dispatch and threaded via a
``contextvars.ContextVar`` so deeply-nested handler code can consult it
without a signature change, lets that handler code skip the write instead.
"""

from __future__ import annotations

import contextvars

from claude_code_hooks_daemon.core.dispatch_cancellation import (
    DispatchCancellation,
    bind_dispatch_cancellation,
    is_dispatch_cancelled,
    reset_dispatch_cancellation,
)


class TestDispatchCancellation:
    """The token itself: starts live, ``cancel()`` is one-way and idempotent."""

    def test_starts_not_cancelled(self) -> None:
        token = DispatchCancellation()
        assert token.is_cancelled is False

    def test_cancel_marks_it_cancelled(self) -> None:
        token = DispatchCancellation()
        token.cancel()
        assert token.is_cancelled is True

    def test_cancel_is_idempotent(self) -> None:
        token = DispatchCancellation()
        token.cancel()
        token.cancel()
        assert token.is_cancelled is True


class TestIsDispatchCancelled:
    """The module-level accessor deeply-nested handler code calls."""

    def test_defaults_to_not_cancelled_with_no_bound_token(self) -> None:
        # No bind() call in this test -- exactly a handler under test in
        # isolation, or a caller that predates this mechanism entirely.
        assert is_dispatch_cancelled() is False

    def test_reflects_a_bound_tokens_state(self) -> None:
        token = DispatchCancellation()
        ctx_token = bind_dispatch_cancellation(token)
        try:
            assert is_dispatch_cancelled() is False
            token.cancel()
            assert is_dispatch_cancelled() is True
        finally:
            reset_dispatch_cancellation(ctx_token)
        # Reset restores the pre-bind (unbound) state.
        assert is_dispatch_cancelled() is False

    def test_bound_token_is_visible_to_nested_calls_on_the_same_thread(self) -> None:
        """The whole point: a handler deep in the call stack sees the SAME
        token its dispatcher bound, with no parameter threaded through
        every intervening call."""
        token = DispatchCancellation()

        def _nested_handler_code() -> bool:
            return is_dispatch_cancelled()

        ctx_token = bind_dispatch_cancellation(token)
        try:
            assert _nested_handler_code() is False
            token.cancel()
            assert _nested_handler_code() is True
        finally:
            reset_dispatch_cancellation(ctx_token)

    def test_bound_token_does_not_leak_across_separate_binds(self) -> None:
        """Simulates two sequential dispatches sharing a thread (e.g. the
        `deadline_seconds is None` direct-call path, which never spawns a
        new thread): the second dispatch's fresh token must not see the
        first one's cancellation."""
        first = DispatchCancellation()
        ctx1 = bind_dispatch_cancellation(first)
        first.cancel()
        assert is_dispatch_cancelled() is True
        reset_dispatch_cancellation(ctx1)

        second = DispatchCancellation()
        ctx2 = bind_dispatch_cancellation(second)
        try:
            assert is_dispatch_cancelled() is False
        finally:
            reset_dispatch_cancellation(ctx2)

    def test_bound_token_isolated_per_thread(self) -> None:
        """A straggler's OWN thread must not see a DIFFERENT, concurrent
        dispatch's cancellation (or lack of it) -- contextvars are
        per-thread, not process-global."""
        import threading

        token_a = DispatchCancellation()
        token_a.cancel()
        seen_in_thread: dict[str, bool] = {}

        def _worker() -> None:
            # No bind() here at all -- an independent thread with nothing
            # bound must see the unbound default, never `token_a`'s state.
            seen_in_thread["cancelled"] = is_dispatch_cancelled()

        ctx = bind_dispatch_cancellation(token_a)
        try:
            thread = threading.Thread(target=_worker)
            thread.start()
            thread.join(timeout=5.0)
        finally:
            reset_dispatch_cancellation(ctx)

        assert seen_in_thread["cancelled"] is False

    def test_context_var_is_the_documented_public_surface(self) -> None:
        """Not asserting the private variable's name, only that binding
        goes through a real contextvars.ContextVar (the mechanism the
        module docstring promises), so a caller integrating this into an
        executor/threadpool boundary can reason about propagation rules."""
        token = DispatchCancellation()
        ctx_token = bind_dispatch_cancellation(token)
        try:
            assert isinstance(ctx_token, contextvars.Token)
        finally:
            reset_dispatch_cancellation(ctx_token)
