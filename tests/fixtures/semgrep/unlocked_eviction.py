"""Fixture for the ``unlocked-select-then-evict`` semgrep rule (Plan 00449).

DELIBERATELY DEFECTIVE CODE. Nothing here is imported or executed — it exists
so the rule can be proved non-vacuous, and each HIT reconstructs a spelling a
real handler in this project carried.

Markers drive the assertions in
``tests/unit/qa/test_semgrep_unlocked_eviction.py``:

* ``# EXPECT-HIT``   — the rule MUST report this line
* ``# EXPECT-CLEAN`` — the rule MUST NOT report this line

A two-statement defect is reported on its FIRST statement (the victim
selection), so that is where its marker goes.
"""

import threading
from typing import Any

_CAP = 32


class Handler:
    """A handler singleton holding bounded maps, evicting every way it can."""

    def __init__(self) -> None:
        self._known: dict[str, set[str]] = {}
        self._fired: dict[tuple[str, str], bool] = {}
        self._state: dict[str, float] = {}
        self._lock = threading.Lock()

    def record_pop_no_default(self, session: str) -> None:
        """write_clobber_guard's spelling: ``pop`` with no default raises too."""
        if session not in self._known and len(self._known) >= _CAP:
            self._known.pop(next(iter(self._known)))  # EXPECT-HIT
        self._known.setdefault(session, set())

    def record_pop_with_default(self, session: str) -> None:
        """A default absorbs the KeyError but not the RuntimeError from iter()."""
        if len(self._known) >= _CAP:
            self._known.pop(next(iter(self._known)), None)  # EXPECT-HIT
        self._known.setdefault(session, set())

    def record_del_inline(self, key: tuple[str, str]) -> None:
        """goal_injection / flaggable_work_advisor / model_fallback_detector."""
        if key not in self._fired and len(self._fired) >= _CAP:
            del self._fired[next(iter(self._fired))]  # EXPECT-HIT
        self._fired[key] = True

    def record_via_keys(self, key: tuple[str, str]) -> None:
        if len(self._fired) >= _CAP:
            del self._fired[next(iter(self._fired.keys()))]  # EXPECT-HIT
        self._fired[key] = True

    def record_two_step(self, session: str, journal: Any) -> None:
        """command_hints / standing_authorisations: select, work, then delete."""
        if len(self._state) >= _CAP:
            oldest = next(iter(self._state))  # EXPECT-HIT
            journal.snapshot(self._state, oldest)
            del self._state[oldest]
        self._state[session] = 0.0

    def record_two_step_pop(self, session: str) -> None:
        if len(self._state) >= _CAP:
            oldest = next(iter(self._state))  # EXPECT-HIT
            self._state.pop(oldest)
        self._state[session] = 0.0

    def record_stalest(self, session: str, now: float) -> None:
        """git_context_injector: ``min`` iterates the map as well."""
        if session not in self._state and len(self._state) >= _CAP:
            oldest = min(self._state, key=lambda key: self._state[key])  # EXPECT-HIT
            del self._state[oldest]
        self._state[session] = now

    def record_under_lock(self, key: tuple[str, str]) -> None:
        """The shared primitives' spelling: the same two steps, made atomic."""
        with self._lock:
            if len(self._fired) >= _CAP:
                self._fired.pop(next(iter(self._fired)), None)  # EXPECT-CLEAN
            self._fired[key] = True

    def record_two_step_under_lock(self, session: str) -> None:
        with self._lock:
            if len(self._state) >= _CAP:
                oldest = next(iter(self._state))  # EXPECT-CLEAN
                del self._state[oldest]
            self._state[session] = 0.0

    def forget(self, session: str) -> None:
        """Deleting a KNOWN key is not an eviction: no victim is selected."""
        self._known.pop(session, None)  # EXPECT-CLEAN

    def first_without_delete(self) -> str | None:
        """Selecting without deleting reads, it does not evict."""
        return next(iter(self._known), None)  # EXPECT-CLEAN


def evict_oldest_if_full(tracked: dict[str, Any]) -> None:
    """recovery_cron_advisor: a module helper handed the handler's map."""
    if len(tracked) >= _CAP:
        oldest_key = next(iter(tracked))  # EXPECT-HIT
        del tracked[oldest_key]
