"""Tests for core/disclosure_tracker.py — DisclosureTracker.

Phase 2 of Plan 00116: in-memory disclosure state keyed by transcript_path.

Design contract (Decision G from PLAN.md):
  - In-memory dict[transcript_path, set[rule_id]]
  - was_disclosed(transcript_path, rule_id) -> bool
  - mark_disclosed(transcript_path, rule_id) -> None
  - reset(transcript_path) -> None
  - Two different transcript_paths are INDEPENDENT (multi-agent correctness)
  - No file I/O, no transcript file reading
"""

from __future__ import annotations

import pytest

from claude_code_hooks_daemon.core.disclosure_tracker import DisclosureTracker

# ---------------------------------------------------------------------------
# Constants for tests
# ---------------------------------------------------------------------------

_PATH_A = "/tmp/agent-a/transcript.jsonl"
_PATH_B = "/tmp/agent-b/transcript.jsonl"
_RULE_1 = "R-GIT-RESET-HARD"
_RULE_2 = "R-SED-FILE-MODIFICATION"
_RULE_3 = "R-PIPE-TO-TAIL"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDisclosureTrackerBasicBehaviour:
    """Core was_disclosed / mark_disclosed / reset behaviour."""

    @pytest.fixture()
    def tracker(self) -> DisclosureTracker:
        """Fresh DisclosureTracker for each test."""
        return DisclosureTracker()

    def test_tracker_instantiation(self, tracker: DisclosureTracker) -> None:
        """DisclosureTracker can be instantiated with no arguments."""
        assert tracker is not None

    def test_not_disclosed_initially(self, tracker: DisclosureTracker) -> None:
        """A rule is not disclosed before mark_disclosed is called."""
        assert tracker.was_disclosed(_PATH_A, _RULE_1) is False

    def test_not_disclosed_for_unknown_path(self, tracker: DisclosureTracker) -> None:
        """A rule is not disclosed for a path that has never been seen."""
        assert tracker.was_disclosed("/never/seen/path.jsonl", _RULE_1) is False

    def test_mark_disclosed_makes_it_disclosed(self, tracker: DisclosureTracker) -> None:
        """After mark_disclosed, was_disclosed returns True."""
        tracker.mark_disclosed(_PATH_A, _RULE_1)
        assert tracker.was_disclosed(_PATH_A, _RULE_1) is True

    def test_mark_disclosed_is_idempotent(self, tracker: DisclosureTracker) -> None:
        """Calling mark_disclosed twice does not raise and result stays True."""
        tracker.mark_disclosed(_PATH_A, _RULE_1)
        tracker.mark_disclosed(_PATH_A, _RULE_1)
        assert tracker.was_disclosed(_PATH_A, _RULE_1) is True

    def test_disclosed_rule_does_not_affect_other_rules(self, tracker: DisclosureTracker) -> None:
        """Marking one rule disclosed does not affect others for the same path."""
        tracker.mark_disclosed(_PATH_A, _RULE_1)
        assert tracker.was_disclosed(_PATH_A, _RULE_2) is False

    def test_multiple_rules_independently_tracked(self, tracker: DisclosureTracker) -> None:
        """Multiple rules for the same path are tracked independently."""
        tracker.mark_disclosed(_PATH_A, _RULE_1)
        tracker.mark_disclosed(_PATH_A, _RULE_2)
        assert tracker.was_disclosed(_PATH_A, _RULE_1) is True
        assert tracker.was_disclosed(_PATH_A, _RULE_2) is True
        assert tracker.was_disclosed(_PATH_A, _RULE_3) is False

    def test_reset_clears_disclosed_state(self, tracker: DisclosureTracker) -> None:
        """reset() clears all disclosures for the given path."""
        tracker.mark_disclosed(_PATH_A, _RULE_1)
        tracker.mark_disclosed(_PATH_A, _RULE_2)
        tracker.reset(_PATH_A)
        assert tracker.was_disclosed(_PATH_A, _RULE_1) is False
        assert tracker.was_disclosed(_PATH_A, _RULE_2) is False

    def test_reset_restores_verbose_behaviour(self, tracker: DisclosureTracker) -> None:
        """After reset, the first query returns False (verbose will fire again)."""
        tracker.mark_disclosed(_PATH_A, _RULE_1)
        tracker.reset(_PATH_A)
        # First fire after reset → not disclosed → verbose block
        result = tracker.was_disclosed(_PATH_A, _RULE_1)
        assert result is False

    def test_reset_then_mark_works(self, tracker: DisclosureTracker) -> None:
        """After reset, mark_disclosed works correctly again."""
        tracker.mark_disclosed(_PATH_A, _RULE_1)
        tracker.reset(_PATH_A)
        tracker.mark_disclosed(_PATH_A, _RULE_1)
        assert tracker.was_disclosed(_PATH_A, _RULE_1) is True

    def test_reset_unknown_path_does_not_raise(self, tracker: DisclosureTracker) -> None:
        """reset() on an unknown path does not raise an error."""
        tracker.reset("/never/seen/path.jsonl")  # Should not raise


class TestDisclosureTrackerMultiAgentIsolation:
    """Two different transcript_paths are completely independent.

    This is the critical multi-agent correctness property from Decision G:
    a Task sub-agent has its own transcript_path and MUST NOT inherit the
    parent agent's disclosure state.
    """

    @pytest.fixture()
    def tracker(self) -> DisclosureTracker:
        """Fresh DisclosureTracker for each test."""
        return DisclosureTracker()

    def test_path_a_disclosed_does_not_affect_path_b(self, tracker: DisclosureTracker) -> None:
        """Disclosing a rule for path A does not affect path B."""
        tracker.mark_disclosed(_PATH_A, _RULE_1)
        assert tracker.was_disclosed(_PATH_B, _RULE_1) is False

    def test_path_b_disclosed_does_not_affect_path_a(self, tracker: DisclosureTracker) -> None:
        """Disclosing a rule for path B does not affect path A."""
        tracker.mark_disclosed(_PATH_B, _RULE_1)
        assert tracker.was_disclosed(_PATH_A, _RULE_1) is False

    def test_reset_path_a_does_not_affect_path_b(self, tracker: DisclosureTracker) -> None:
        """reset(path_A) does not clear disclosures for path_B."""
        tracker.mark_disclosed(_PATH_A, _RULE_1)
        tracker.mark_disclosed(_PATH_B, _RULE_1)
        tracker.reset(_PATH_A)
        # Path A cleared
        assert tracker.was_disclosed(_PATH_A, _RULE_1) is False
        # Path B untouched
        assert tracker.was_disclosed(_PATH_B, _RULE_1) is True

    def test_independent_tracking_many_paths(self, tracker: DisclosureTracker) -> None:
        """Many paths are independently tracked simultaneously."""
        paths = [f"/agent/{i}/transcript.jsonl" for i in range(5)]
        # Mark different rules for different paths
        for i, path in enumerate(paths):
            tracker.mark_disclosed(path, _RULE_1)
            if i % 2 == 0:
                tracker.mark_disclosed(path, _RULE_2)

        # Verify each path's state is correct
        for i, path in enumerate(paths):
            assert tracker.was_disclosed(path, _RULE_1) is True
            if i % 2 == 0:
                assert tracker.was_disclosed(path, _RULE_2) is True
            else:
                assert tracker.was_disclosed(path, _RULE_2) is False

    def test_sub_agent_gets_verbose_even_if_parent_disclosed(
        self, tracker: DisclosureTracker
    ) -> None:
        """Sub-agent transcript_path gets verbose (not disclosed) even if parent disclosed.

        This is the core correctness property: agent B should not get terse
        reminders for rules it has never seen the verbose block for, even if
        agent A has seen them.
        """
        parent_path = "/session/main/transcript.jsonl"
        subagent_path = "/session/sidechain/transcript.jsonl"

        # Parent agent has seen R-GIT-RESET-HARD verbose
        tracker.mark_disclosed(parent_path, _RULE_1)
        assert tracker.was_disclosed(parent_path, _RULE_1) is True

        # Sub-agent has NOT seen it — must get verbose (False = not disclosed)
        assert tracker.was_disclosed(subagent_path, _RULE_1) is False


class TestDisclosureTrackerStateManagement:
    """Verify the tracker manages internal state correctly."""

    @pytest.fixture()
    def tracker(self) -> DisclosureTracker:
        """Fresh DisclosureTracker for each test."""
        return DisclosureTracker()

    def test_empty_tracker_has_no_state(self, tracker: DisclosureTracker) -> None:
        """A freshly instantiated tracker has no disclosed state."""
        # Querying any path/rule combination should return False
        assert tracker.was_disclosed(_PATH_A, _RULE_1) is False
        assert tracker.was_disclosed(_PATH_B, _RULE_2) is False

    def test_tracker_accumulates_multiple_disclosures(self, tracker: DisclosureTracker) -> None:
        """Tracker correctly accumulates many mark_disclosed calls."""
        rules = [_RULE_1, _RULE_2, _RULE_3]
        for rule in rules:
            tracker.mark_disclosed(_PATH_A, rule)
        for rule in rules:
            assert tracker.was_disclosed(_PATH_A, rule) is True

    def test_was_disclosed_returns_bool(self, tracker: DisclosureTracker) -> None:
        """was_disclosed always returns a bool (not truthy/falsy other types)."""
        result_before = tracker.was_disclosed(_PATH_A, _RULE_1)
        assert isinstance(result_before, bool)
        tracker.mark_disclosed(_PATH_A, _RULE_1)
        result_after = tracker.was_disclosed(_PATH_A, _RULE_1)
        assert isinstance(result_after, bool)

    def test_progressive_disclosure_workflow(self, tracker: DisclosureTracker) -> None:
        """Full progressive-disclosure workflow: verbose first, terse after, verbose after reset.

        Simulates:
          1. First fire → not disclosed → emit verbose → mark_disclosed
          2. Second fire → disclosed → emit terse
          3. PreCompact → reset
          4. Third fire (post-compact) → not disclosed → emit verbose again
        """
        # Step 1: First fire
        assert tracker.was_disclosed(_PATH_A, _RULE_1) is False
        tracker.mark_disclosed(_PATH_A, _RULE_1)

        # Step 2: Second fire
        assert tracker.was_disclosed(_PATH_A, _RULE_1) is True

        # Step 3: PreCompact reset
        tracker.reset(_PATH_A)

        # Step 4: Third fire (post-compact) → verbose again
        assert tracker.was_disclosed(_PATH_A, _RULE_1) is False
