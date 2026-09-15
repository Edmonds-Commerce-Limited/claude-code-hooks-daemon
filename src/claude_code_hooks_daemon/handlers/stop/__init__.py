"""Stop handlers for claude-code-hooks-daemon.

``auto_continue_stop`` is ``terminal=True`` at priority 10 (this project's own
override; the daemon ships 15) and matches nearly every Stop event. When it
BLOCKS a stop (no ``STOPPING BECAUSE:`` line — most stops), that deny ends the
chain, so a handler registered ABOVE it (a lower priority number) never runs
on those stops; a handler registered AFTER it (Plan 00416's
``cron_stop_enforcer``, priority 40) still runs on any stop it ALLOWS, because
an ALLOW never ends the chain (Plan 00242) — which is every stop that is
actually about to end the session, the only turn enforcement must not miss.
Plan 00237 removed three handlers that had been sitting above it silently
(``task_completion_checker`` and the two language detectors, whose live twins
run on the ``nitpick`` pseudo-event instead). Before adding a Stop handler,
read tests/integration/test_stop_chain_terminal_shadowing.py.
"""

from .auto_continue_stop import AutoContinueStopHandler
from .cron_stop_enforcer import CronStopEnforcerHandler

__all__ = [
    "AutoContinueStopHandler",
    "CronStopEnforcerHandler",
]
