"""Stop handlers for claude-code-hooks-daemon.

``auto_continue_stop`` is the only handler here, and that is now a deliberate
invariant rather than an accident: it is ``terminal=True`` at priority 10 and
matches nearly every Stop event, so ANY handler registered above it is
unreachable on an ordinary stop. Plan 00237 removed three that had been sitting
there silently (``task_completion_checker`` and the two language detectors,
whose live twins run on the ``nitpick`` pseudo-event instead). Before adding a
Stop handler, read tests/integration/test_stop_chain_terminal_shadowing.py.
"""

from .auto_continue_stop import AutoContinueStopHandler

__all__ = [
    "AutoContinueStopHandler",
]
