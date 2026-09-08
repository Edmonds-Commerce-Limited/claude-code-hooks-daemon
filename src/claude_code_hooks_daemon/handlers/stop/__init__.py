"""Stop handlers for claude-code-hooks-daemon.

``auto_continue_stop`` is the only handler here, and that is a deliberate
invariant rather than an accident: it is ``terminal=True`` at priority 10 and
matches nearly every Stop event. When it BLOCKS a stop (no ``STOPPING
BECAUSE:`` line — most stops), that deny ends the chain, so any handler
registered above it never runs on those stops; on an allowed stop it does
run, because an ALLOW never ends the chain (Plan 00242). Plan 00237 removed
three handlers that had been sitting above it silently
(``task_completion_checker`` and the two language detectors, whose live twins
run on the ``nitpick`` pseudo-event instead). Before adding a Stop handler,
read tests/integration/test_stop_chain_terminal_shadowing.py.
"""

from .auto_continue_stop import AutoContinueStopHandler

__all__ = [
    "AutoContinueStopHandler",
]
