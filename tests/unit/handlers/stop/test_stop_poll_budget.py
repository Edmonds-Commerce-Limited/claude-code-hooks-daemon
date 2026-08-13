"""The stop-explanation poll budget must exceed the observed flush lag.

Claude Code records an assistant message and flushes it to the transcript
asynchronously. The Stop payload carries no message text, so the handler must
read the transcript — and if the text is not yet readable it polls. When that
poll expires the handler cannot see the explanation that WAS written, and denies
a perfectly good stop.

Measured on 2026-08-13 against a 72 MB session transcript, correlating
`untracked/stop-events.jsonl` denies with the preceding transcript entry. Three
false denies, each on a message whose text carried `STOPPING BECAUSE:`:

    deny 11:13:54  gap  903 ms
    deny 12:00:22  gap  892 ms
    deny 12:21:02  gap 1752 ms

against a budget of 6 x 0.1 s = 600 ms. The gap is measured from the entry's
recorded timestamp to the deny, and already includes the hook-fire delay and
the poll itself, so the true flush lag is LONGER than the gap in every case.

This test pins the budget against that evidence rather than against a number,
so a future edit that shrinks it has to argue with the measurement.
"""

from typing import Final

from claude_code_hooks_daemon.handlers.stop import auto_continue_stop

#: Worst observed message-recorded-to-deny gap, in seconds (12:21:02 above).
_OBSERVED_WORST_LAG_SECONDS: Final[float] = 1.752

#: Margin over the worst observation. The samples come from ONE session on one
#: transcript size; the lag plausibly scales with transcript growth, so the
#: budget is set above the observed maximum rather than at it.
_REQUIRED_MARGIN: Final[float] = 1.5


def _poll_budget_seconds() -> float:
    return (
        auto_continue_stop._HAS_EXPLANATION_RETRY_ATTEMPTS
        * auto_continue_stop._HAS_EXPLANATION_RETRY_DELAY_SECONDS
    )


class TestPollBudgetCoversObservedFlushLag:
    def test_budget_exceeds_worst_observed_lag_with_margin(self) -> None:
        """A budget below the measured lag denies stops that DID explain."""
        required = _OBSERVED_WORST_LAG_SECONDS * _REQUIRED_MARGIN
        assert _poll_budget_seconds() >= required, (
            f"poll budget {_poll_budget_seconds():.2f}s is below the "
            f"{required:.2f}s needed to cover the observed "
            f"{_OBSERVED_WORST_LAG_SECONDS}s flush lag — stops carrying a valid "
            "STOPPING BECAUSE: will be denied"
        )

    def test_budget_stays_well_inside_the_client_socket_ceiling(self) -> None:
        """The forwarder's whole connect+send+recv budget is 30s by default.

        Polling is the dominant cost on the miss path, so the budget must leave
        generous room for the rest of dispatch. A hook that outruns the socket
        timeout is reported as a dead daemon — the Plan 00177 failure shape.
        """
        client_socket_budget_seconds = 30.0
        assert _poll_budget_seconds() < client_socket_budget_seconds / 4

    def test_polling_is_not_on_the_happy_path(self) -> None:
        """A visible, fresh message must return without ever polling.

        This is what makes a wider budget nearly free: it is spent only when
        the message is not yet readable, which is exactly when waiting is the
        correct behaviour.
        """
        source = auto_continue_stop.AutoContinueStopHandler._resolve_current_turn_message
        import inspect

        body = inspect.getsource(source)
        early_return = body.index("if complete and not suspect_stale:")
        poll_call = body.index("_await_fresh_assistant_message")
        assert early_return < poll_call, (
            "the complete-and-fresh early return must precede the poll, "
            "otherwise a wider budget would slow every ordinary stop"
        )
