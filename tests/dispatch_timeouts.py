"""Wait budgets for the BoundedDispatcher / chain-deadline tests.

Test-only, so they live with the tests rather than in the shipped
``constants.timeout`` (Plan 00466 N40 review 2). Named by role, since many
call sites share a budget for the same reason. None of them is an assertion
about how fast anything runs: each is either a timeout the test forces to
expire, or an upper bound on a wait that normally ends at once.
"""

from typing import Final


class DispatchTestTimeout:
    """Seconds, by role."""

    INSTANT: Final = 0.01  # sub-tick: forces an already-expired wait
    VERY_SHORT: Final = 0.02  # forces DispatchTimeout against a blocked callable
    SHORT: Final = 0.05  # forces DispatchTimeout with a slightly larger margin
    NORMAL: Final = 1.0  # upper bound on waiting for a background thread to settle
    GENEROUS: Final = 5.0  # the same, under CI/host load
    OUTER_BOUND: Final = 10  # outer ceiling for a probe socket's own settimeout()
