"""Every handler's bounded map, under contention and at its cap (Plan 00449).

Handlers are daemon-lifetime singletons and ``server.py`` dispatches on a
thread pool, so a bounded map evicted in two unlocked steps (select a victim,
then delete it) lets two threads pick the same victim — the second delete
raises ``KeyError``, and iterating a map another thread resized raises
``RuntimeError``. The ``unlocked-select-then-evict`` semgrep rule found the
sites below; write_clobber_guard has its own module.

Each site gets two tests. The contention test drives the site's bookkeeping
method from many threads against a map already AT its cap, at CPython's
minimum switch interval (``tests/thread_contention.py``). The FIFO test names
WHICH entry an overflowing insert evicts — a size assertion alone passes for
LIFO too, which is how ``popitem()`` once inverted the shared counter's order
unnoticed.
"""

from __future__ import annotations

import itertools
from typing import Any

import pytest
from tests.thread_contention import hammer

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.post_tool_use.command_hints import (
    _MAX_TRACKED_FIRE_STATES,
    CommandHintsHandler,
)
from claude_code_hooks_daemon.handlers.post_tool_use.goal_injection import (
    _MAX_TRACKED_LATCHES,
    GoalInjectionHandler,
)
from claude_code_hooks_daemon.handlers.post_tool_use.recovery_cron_advisor import (
    _MAX_TRACKED_PLANS,
    RecoveryCronAdvisorHandler,
)
from claude_code_hooks_daemon.handlers.pre_tool_use.flaggable_work_advisor import (
    _MAX_ADVISED_KEYS as _FLAGGABLE_CAP,
)
from claude_code_hooks_daemon.handlers.pre_tool_use.flaggable_work_advisor import (
    FlaggableWorkAdvisorHandler,
)
from claude_code_hooks_daemon.handlers.pre_tool_use.reference_repo_freshness import (
    _MAX_TRACKED_SESSIONS as _REFERENCE_CAP,
)
from claude_code_hooks_daemon.handlers.pre_tool_use.reference_repo_freshness import (
    ReferenceRepoFreshnessHandler,
)
from claude_code_hooks_daemon.handlers.session_start.model_fallback_detector import (
    _MAX_ADVISED_KEYS as _FALLBACK_CAP,
)
from claude_code_hooks_daemon.handlers.session_start.model_fallback_detector import (
    ModelFallbackDetectorHandler,
)
from claude_code_hooks_daemon.handlers.user_prompt_submit.git_context_injector import (
    _MAX_TRACKED_SESSIONS as _GIT_CONTEXT_CAP,
)
from claude_code_hooks_daemon.handlers.user_prompt_submit.git_context_injector import (
    GitContextInjectorHandler,
)
from claude_code_hooks_daemon.handlers.user_prompt_submit.idle_housekeeping_advisor import (
    _MAX_TRACKED_SESSIONS as _HOUSEKEEPING_CAP,
)
from claude_code_hooks_daemon.handlers.user_prompt_submit.idle_housekeeping_advisor import (
    IdleHousekeepingAdvisoryHandler,
)
from claude_code_hooks_daemon.handlers.user_prompt_submit.standing_authorisations import (
    _MAX_TRACKED_SESSIONS as _STANDING_CAP,
)
from claude_code_hooks_daemon.handlers.user_prompt_submit.standing_authorisations import (
    StandingAuthorisationsHandler,
)


def _no_errors(errors: list[BaseException]) -> None:
    assert not errors, f"concurrent callers raised: {errors[:3]}"


class TestGoalInjectionLatches:
    """RV5-M1/RV5-m4 (Plan 00466): ``_record_latch`` is a generic staticmethod
    shared by ``handler._fired`` and ``handler._reasserted`` (RV3-m4), so
    every call names WHICH map it is inserting into."""

    def test_concurrent_latching_never_raises(self) -> None:
        handler = GoalInjectionHandler()
        for index in range(_MAX_TRACKED_LATCHES):
            handler._record_latch(handler._fired, (f"seed{index}", "00001"))

        _no_errors(
            hammer(lambda w, i: handler._record_latch(handler._fired, (f"w{w}-{i}", "00001")))
        )
        assert len(handler._fired) == _MAX_TRACKED_LATCHES

    def test_overflow_evicts_the_oldest_latch(self) -> None:
        handler = GoalInjectionHandler()
        for index in range(_MAX_TRACKED_LATCHES):
            handler._record_latch(handler._fired, (f"s{index}", "00001"))

        handler._record_latch(handler._fired, ("newcomer", "00001"))

        assert not handler._fired.get(("s0", "00001"))
        assert handler._fired.get((f"s{_MAX_TRACKED_LATCHES - 1}", "00001"))


class TestFlaggableWorkAdvisorKeys:
    def test_concurrent_recording_never_raises(self) -> None:
        handler = FlaggableWorkAdvisorHandler()
        for index in range(_FLAGGABLE_CAP):
            handler._record_advised(f"seed{index}", "key")

        _no_errors(hammer(lambda w, i: handler._record_advised(f"w{w}-{i}", "key")))
        assert len(handler._advised) == _FLAGGABLE_CAP

    def test_overflow_evicts_the_oldest_key(self) -> None:
        handler = FlaggableWorkAdvisorHandler()
        for index in range(_FLAGGABLE_CAP):
            handler._record_advised(f"s{index}", "key")

        handler._record_advised("newcomer", "key")

        assert ("s0", "key") not in handler._advised
        assert (f"s{_FLAGGABLE_CAP - 1}", "key") in handler._advised


class TestModelFallbackDetectorDedupe:
    """Three maps, one shape: "True the FIRST time this key is seen"."""

    @pytest.mark.parametrize(
        "mark", ["_mark_advised", "_mark_recovered_noted", "_mark_snapshotted"]
    )
    def test_concurrent_marking_never_raises(self, mark: str) -> None:
        handler = ModelFallbackDetectorHandler()
        call = _fallback_marker(handler, mark)
        for index in range(_FALLBACK_CAP):
            call(f"seed{index}")

        _no_errors(hammer(lambda w, i: call(f"w{w}-{i}")))

    @pytest.mark.parametrize(
        "mark", ["_mark_advised", "_mark_recovered_noted", "_mark_snapshotted"]
    )
    def test_each_key_is_claimed_exactly_once_under_contention(self, mark: str) -> None:
        """The check and the insert are one step, so "first time" means once."""
        handler = ModelFallbackDetectorHandler()
        call = _fallback_marker(handler, mark)
        claims: list[bool] = []
        distinct = _FALLBACK_CAP // 2

        def claim(worker: int, index: int) -> None:
            claims.append(call(f"k{index % distinct}"))

        _no_errors(hammer(claim))
        assert claims.count(True) == distinct

    @pytest.mark.parametrize(
        "mark", ["_mark_advised", "_mark_recovered_noted", "_mark_snapshotted"]
    )
    def test_overflow_evicts_the_oldest_key(self, mark: str) -> None:
        handler = ModelFallbackDetectorHandler()
        call = _fallback_marker(handler, mark)
        for index in range(_FALLBACK_CAP):
            call(f"s{index}")

        call("newcomer")

        assert call(f"s{_FALLBACK_CAP - 1}") is False, "the newest key was evicted (LIFO)"
        assert call("s0") is True, "the oldest key survived the overflow"


def _fallback_marker(handler: ModelFallbackDetectorHandler, mark: str) -> Any:
    if mark == "_mark_advised":
        return lambda identity: handler._mark_advised("session", identity)
    return getattr(handler, mark)


class TestReferenceRepoFreshnessReported:
    def test_concurrent_recording_never_raises(self) -> None:
        handler = ReferenceRepoFreshnessHandler()
        for index in range(_REFERENCE_CAP):
            handler._record(f"seed{index}", "repo")

        _no_errors(hammer(lambda w, i: handler._record(f"w{w}-{i}", "repo")))
        assert len(handler._reported) == _REFERENCE_CAP

    def test_overflow_evicts_the_oldest_session(self) -> None:
        handler = ReferenceRepoFreshnessHandler()
        for index in range(_REFERENCE_CAP):
            handler._record(f"s{index}", "repo")

        handler._record("newcomer", "repo")

        assert not handler._already_reported("s0", "repo")
        assert handler._already_reported(f"s{_REFERENCE_CAP - 1}", "repo")


class TestIdleHousekeepingPasses:
    def test_concurrent_recording_never_raises(self) -> None:
        handler = IdleHousekeepingAdvisoryHandler()
        for index in range(_HOUSEKEEPING_CAP):
            handler._record_pass(f"seed{index}")

        _no_errors(hammer(lambda w, i: handler._record_pass(f"w{w}-{i}")))
        assert len(handler._passes_by_session) == _HOUSEKEEPING_CAP

    def test_overflow_evicts_the_oldest_session(self) -> None:
        handler = IdleHousekeepingAdvisoryHandler()
        for index in range(_HOUSEKEEPING_CAP):
            handler._record_pass(f"s{index}")

        handler._record_pass("newcomer")

        assert "s0" not in handler._passes_by_session
        assert handler._passes_by_session[f"s{_HOUSEKEEPING_CAP - 1}"] == 1


class TestCommandHintsFireState:
    @staticmethod
    def _full() -> CommandHintsHandler:
        handler = CommandHintsHandler()
        for index in range(_MAX_TRACKED_FIRE_STATES):
            handler._record_fire((f"s{index}", "hint"), 0.0)
        handler._journal.commit()
        return handler

    def test_concurrent_firing_never_raises(self) -> None:
        handler = self._full()
        _no_errors(hammer(lambda w, i: handler._record_fire((f"w{w}-{i}", "hint"), 0.0)))
        assert len(handler._fire_state) == _MAX_TRACKED_FIRE_STATES

    def test_overflow_evicts_the_oldest_state(self) -> None:
        handler = self._full()
        handler._record_fire(("newcomer", "hint"), 0.0)

        assert ("s0", "hint") not in handler._fire_state
        assert (f"s{_MAX_TRACKED_FIRE_STATES - 1}", "hint") in handler._fire_state

    def test_a_denied_call_restores_the_full_map_exactly(self) -> None:
        """Rollback must bring the victim back and evict nobody in its place."""
        handler = self._full()
        before = dict(handler._fire_state)
        hint = handler._resolve_hints()[0]

        assert handler._should_fire("newcomer", hint) is True
        handler.commit_side_effects({}, Decision.DENY)

        assert dict(handler._fire_state) == before


class TestRecoveryCronAdvisorPlans:
    @staticmethod
    def _full() -> RecoveryCronAdvisorHandler:
        handler = RecoveryCronAdvisorHandler()
        for index in range(_MAX_TRACKED_PLANS):
            handler._should_advise_progress(f"p{index}")
            handler._should_advise_once(handler._creation_seen, f"p{index}")
        handler._journal.commit()
        return handler

    def test_concurrent_progress_never_raises(self) -> None:
        handler = self._full()
        _no_errors(hammer(lambda w, i: handler._should_advise_progress(f"w{w}-{i}")))
        assert len(handler._progress_counts) == _MAX_TRACKED_PLANS

    def test_concurrent_once_never_raises(self) -> None:
        handler = self._full()
        _no_errors(
            hammer(lambda w, i: handler._should_advise_once(handler._creation_seen, f"w{w}-{i}"))
        )
        assert len(handler._creation_seen) == _MAX_TRACKED_PLANS

    def test_overflow_evicts_the_oldest_plan(self) -> None:
        handler = self._full()
        handler._should_advise_progress("newcomer")
        handler._should_advise_once(handler._creation_seen, "newcomer")

        assert "p0" not in handler._progress_counts
        assert "p0" not in handler._creation_seen
        assert f"p{_MAX_TRACKED_PLANS - 1}" in handler._progress_counts
        assert f"p{_MAX_TRACKED_PLANS - 1}" in handler._creation_seen

    def test_a_denied_call_restores_the_full_maps_exactly(self) -> None:
        handler = self._full()
        progress_before = dict(handler._progress_counts)
        creation_before = dict(handler._creation_seen)

        handler._should_advise_progress("newcomer")
        handler._should_advise_once(handler._creation_seen, "newcomer")
        handler.commit_side_effects({}, Decision.DENY)

        assert dict(handler._progress_counts) == progress_before
        assert dict(handler._creation_seen) == creation_before


class TestGitContextInjectorSessions:
    """This map evicts the LEAST RECENTLY INJECTED session, not the first inserted."""

    def test_concurrent_injection_never_raises(self) -> None:
        handler = GitContextInjectorHandler()
        for index in range(_GIT_CONTEXT_CAP):
            handler._should_inject(f"seed{index}", "payload")

        _no_errors(hammer(lambda w, i: handler._should_inject(f"w{w}-{i}", "payload")))
        assert len(handler._last_injected) == _GIT_CONTEXT_CAP

    def test_overflow_evicts_the_least_recently_injected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        handler = GitContextInjectorHandler()
        clock = itertools.count()
        monkeypatch.setattr(handler, "_now", lambda: float(next(clock)))
        for index in range(_GIT_CONTEXT_CAP):
            handler._should_inject(f"s{index}", "payload")
        # s0 is the first inserted, but re-injecting it makes s1 the stalest.
        assert handler._should_inject("s0", "changed") is True

        handler._should_inject("newcomer", "payload")

        assert "s0" in handler._last_injected
        assert "s1" not in handler._last_injected


class TestStandingAuthorisationsSessions:
    def test_concurrent_state_creation_never_raises(self) -> None:
        handler = StandingAuthorisationsHandler()
        for index in range(_STANDING_CAP):
            handler._state_for(f"seed{index}")

        _no_errors(hammer(lambda w, i: handler._state_for(f"w{w}-{i}")))
        assert len(handler._session_states) == _STANDING_CAP

    def test_overflow_evicts_the_oldest_session(self) -> None:
        handler = StandingAuthorisationsHandler()
        states = {f"s{index}": handler._state_for(f"s{index}") for index in range(_STANDING_CAP)}

        handler._state_for("newcomer")

        newest = f"s{_STANDING_CAP - 1}"
        assert handler._state_for(newest) is states[newest]
        assert handler._state_for("s0") is not states["s0"]
