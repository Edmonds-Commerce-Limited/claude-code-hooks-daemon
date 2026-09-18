"""Stop handlers for claude-code-hooks-daemon.

``auto_continue_stop`` is ``terminal=True`` at priority 10 (this project's own
override; the daemon ships 15) and matches nearly every Stop event. When it
BLOCKS a stop (no ``STOPPING BECAUSE:`` line — most stops), that deny ends the
chain, so a handler registered AFTER it (a higher priority number) never runs
on those stops — which is the common case, not the exception, so "still
reachable on an allowed stop" is not good enough:
``tests/integration/test_stop_chain_terminal_shadowing.py`` denies that
placement outright. Plan 00416's ``cron_stop_enforcer`` therefore sits BEFORE
it, at priority 7 — not 8, which the ``release_blocker`` project handler
already occupies — and Plan 00237 removed three handlers that had been sitting
after it silently (``task_completion_checker`` and the two language
detectors, whose live twins run on the ``nitpick`` pseudo-event instead).
Before adding a Stop handler, read that test module.
"""

from .auto_continue_stop import AutoContinueStopHandler
from .cron_stop_enforcer import CronStopEnforcerHandler
from .teammate_reap_advisor import TeammateReapAdvisorHandler

__all__ = [
    "AutoContinueStopHandler",
    "CronStopEnforcerHandler",
    "TeammateReapAdvisorHandler",
]
