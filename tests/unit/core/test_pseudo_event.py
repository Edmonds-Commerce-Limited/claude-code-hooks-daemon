"""Tests for pseudo-event infrastructure.

TDD RED phase: These tests define the expected behavior of PseudoEventTrigger,
PseudoEventConfig, PseudoEventDispatcher, and result merging.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from claude_code_hooks_daemon.core.chain import ChainExecutionResult
from claude_code_hooks_daemon.core.event import EventType
from claude_code_hooks_daemon.core.hook_result import Decision, HookResult
from claude_code_hooks_daemon.core.pseudo_event import (
    PseudoEventConfig,
    PseudoEventDispatcher,
    PseudoEventTrigger,
    merge_pseudo_results,
)

# ─── PseudoEventTrigger ───


class TestPseudoEventTriggerParsing:
    """Test parsing of trigger notation strings."""

    def test_parse_pre_tool_use_1_of_5(self) -> None:
        """Parse 'pre_tool_use:1/5' → EventType.PRE_TOOL_USE, 1, 5."""
        trigger = PseudoEventTrigger.from_string("pre_tool_use:1/5")
        assert trigger.event_type == EventType.PRE_TOOL_USE
        assert trigger.numerator == 1
        assert trigger.denominator == 5

    def test_parse_stop_1_of_1(self) -> None:
        """Parse 'stop:1/1' → EventType.STOP, 1, 1 (every occurrence)."""
        trigger = PseudoEventTrigger.from_string("stop:1/1")
        assert trigger.event_type == EventType.STOP
        assert trigger.numerator == 1
        assert trigger.denominator == 1

    def test_parse_post_tool_use_2_of_10(self) -> None:
        """Parse 'post_tool_use:2/10' → fire twice every 10."""
        trigger = PseudoEventTrigger.from_string("post_tool_use:2/10")
        assert trigger.event_type == EventType.POST_TOOL_USE
        assert trigger.numerator == 2
        assert trigger.denominator == 10

    def test_parse_session_start(self) -> None:
        """Parse 'session_start:1/1'."""
        trigger = PseudoEventTrigger.from_string("session_start:1/1")
        assert trigger.event_type == EventType.SESSION_START

    def test_parse_preserves_case_insensitive(self) -> None:
        """Event type parsing is case-insensitive for snake_case."""
        trigger = PseudoEventTrigger.from_string("Pre_Tool_Use:1/3")
        assert trigger.event_type == EventType.PRE_TOOL_USE


class TestPseudoEventTriggerValidation:
    """Test validation of trigger parameters."""

    def test_invalid_format_no_colon(self) -> None:
        """Raise ValueError when no colon separator."""
        with pytest.raises(ValueError, match="format"):
            PseudoEventTrigger.from_string("pre_tool_use_1_5")

    def test_invalid_format_no_slash(self) -> None:
        """Raise ValueError when no slash in frequency."""
        with pytest.raises(ValueError, match="format"):
            PseudoEventTrigger.from_string("pre_tool_use:15")

    def test_numerator_zero(self) -> None:
        """Raise ValueError when numerator is 0."""
        with pytest.raises(ValueError, match="numerator"):
            PseudoEventTrigger.from_string("pre_tool_use:0/5")

    def test_denominator_zero(self) -> None:
        """Raise ValueError when denominator is 0."""
        with pytest.raises(ValueError, match="denominator"):
            PseudoEventTrigger.from_string("pre_tool_use:1/0")

    def test_numerator_greater_than_denominator(self) -> None:
        """Raise ValueError when numerator > denominator."""
        with pytest.raises(ValueError, match="numerator"):
            PseudoEventTrigger.from_string("pre_tool_use:6/5")

    def test_negative_numerator(self) -> None:
        """Raise ValueError for negative numerator."""
        with pytest.raises(ValueError):
            PseudoEventTrigger.from_string("pre_tool_use:-1/5")

    def test_unknown_event_type(self) -> None:
        """Raise ValueError for unknown event type."""
        with pytest.raises(ValueError):
            PseudoEventTrigger.from_string("unknown_event:1/5")

    def test_non_numeric_frequency(self) -> None:
        """Raise ValueError for non-numeric frequency parts."""
        with pytest.raises(ValueError):
            PseudoEventTrigger.from_string("pre_tool_use:a/b")


class TestPseudoEventTriggerEquality:
    """Test trigger dataclass behavior."""

    def test_frozen_dataclass(self) -> None:
        """Trigger is immutable (frozen dataclass)."""
        trigger = PseudoEventTrigger.from_string("pre_tool_use:1/5")
        with pytest.raises((AttributeError, TypeError)):
            trigger.numerator = 2

    def test_equality(self) -> None:
        """Two triggers with same values are equal."""
        t1 = PseudoEventTrigger.from_string("pre_tool_use:1/5")
        t2 = PseudoEventTrigger.from_string("pre_tool_use:1/5")
        assert t1 == t2


# ─── PseudoEventConfig ───


class TestPseudoEventConfig:
    """Test configuration parsing for pseudo-events."""

    def test_from_dict_basic(self) -> None:
        """Parse basic config with name, triggers, and handler config."""
        config = PseudoEventConfig.from_dict(
            "nitpick",
            {
                "enabled": True,
                "triggers": ["pre_tool_use:1/5", "stop:1/1"],
                "handlers": {
                    "dismissive_language": {"enabled": True},
                    "hedging_language": {"enabled": True},
                },
            },
        )
        assert config.name == "nitpick"
        assert config.enabled is True
        assert len(config.triggers) == 2
        assert config.triggers[0].event_type == EventType.PRE_TOOL_USE
        assert config.triggers[1].event_type == EventType.STOP
        assert config.handler_configs["dismissive_language"]["enabled"] is True

    def test_from_dict_disabled(self) -> None:
        """Disabled pseudo-event."""
        config = PseudoEventConfig.from_dict(
            "nitpick",
            {"enabled": False, "triggers": ["pre_tool_use:1/5"], "handlers": {}},
        )
        assert config.enabled is False

    def test_from_dict_defaults_enabled(self) -> None:
        """Default to enabled when not specified."""
        config = PseudoEventConfig.from_dict(
            "nitpick",
            {"triggers": ["pre_tool_use:1/5"], "handlers": {}},
        )
        assert config.enabled is True

    def test_from_dict_empty_triggers(self) -> None:
        """Raise ValueError when no triggers specified."""
        with pytest.raises(ValueError, match="trigger"):
            PseudoEventConfig.from_dict(
                "nitpick",
                {"triggers": [], "handlers": {}},
            )

    def test_from_dict_missing_triggers(self) -> None:
        """Raise ValueError when triggers key missing."""
        with pytest.raises(ValueError, match="trigger"):
            PseudoEventConfig.from_dict("nitpick", {"handlers": {}})


# ─── PseudoEventDispatcher Counter Logic ───


class TestPseudoEventDispatcherCounters:
    """Test frequency counter logic."""

    def _make_dispatcher(
        self,
        trigger_str: str = "pre_tool_use:1/5",
        pseudo_event_name: str = "nitpick",
    ) -> PseudoEventDispatcher:
        """Create dispatcher with a single pseudo-event and mock setup/chain."""
        config = PseudoEventConfig.from_dict(
            pseudo_event_name,
            {
                "enabled": True,
                "triggers": [trigger_str],
                "handlers": {},
            },
        )
        dispatcher = PseudoEventDispatcher()
        setup_fn = MagicMock(side_effect=lambda hook_input, sid: hook_input)
        chain = MagicMock()
        chain.execute.return_value = ChainExecutionResult(result=HookResult.allow())
        dispatcher.register(config, setup_fn=setup_fn, chain=chain)
        return dispatcher

    def test_fires_on_nth_occurrence(self) -> None:
        """Fire on every 5th PreToolUse with '1/5' trigger."""
        dispatcher = self._make_dispatcher("pre_tool_use:1/5")
        hook_input: dict[str, Any] = {"tool_name": "Bash"}
        session_id = "test-session"

        results_by_call: list[list[HookResult]] = []
        for _ in range(10):
            results = dispatcher.check_and_fire(EventType.PRE_TOOL_USE, hook_input, session_id)
            results_by_call.append(results)

        # Should fire on calls 5 and 10 (0-indexed: 4 and 9)
        fired = [i for i, r in enumerate(results_by_call) if len(r) > 0]
        assert fired == [4, 9]

    def test_fires_every_time_with_1_of_1(self) -> None:
        """Fire every time with '1/1' trigger."""
        dispatcher = self._make_dispatcher("stop:1/1")
        hook_input: dict[str, Any] = {}
        session_id = "test-session"

        for _ in range(3):
            results = dispatcher.check_and_fire(EventType.STOP, hook_input, session_id)
            assert len(results) == 1

    def test_no_fire_for_unrelated_event(self) -> None:
        """Don't fire for event types not in triggers."""
        dispatcher = self._make_dispatcher("pre_tool_use:1/5")
        hook_input: dict[str, Any] = {}

        results = dispatcher.check_and_fire(EventType.STOP, hook_input, "test-session")
        assert results == []

    def test_counter_per_session(self) -> None:
        """Each session has independent counters."""
        dispatcher = self._make_dispatcher("pre_tool_use:1/3")
        hook_input: dict[str, Any] = {"tool_name": "Bash"}

        # Session A: 3 calls → fire on 3rd
        for i in range(3):
            results = dispatcher.check_and_fire(EventType.PRE_TOOL_USE, hook_input, "session-a")
            if i == 2:
                assert len(results) == 1
            else:
                assert len(results) == 0

        # Session B: 3 calls → fire on 3rd (independent counter)
        for i in range(3):
            results = dispatcher.check_and_fire(EventType.PRE_TOOL_USE, hook_input, "session-b")
            if i == 2:
                assert len(results) == 1
            else:
                assert len(results) == 0

    def test_disabled_pseudo_event_never_fires(self) -> None:
        """Disabled pseudo-events are skipped entirely."""
        config = PseudoEventConfig.from_dict(
            "nitpick",
            {
                "enabled": False,
                "triggers": ["pre_tool_use:1/1"],
                "handlers": {},
            },
        )
        dispatcher = PseudoEventDispatcher()
        setup_fn = MagicMock(side_effect=lambda hook_input, sid: hook_input)
        chain = MagicMock()
        dispatcher.register(config, setup_fn=setup_fn, chain=chain)

        results = dispatcher.check_and_fire(
            EventType.PRE_TOOL_USE, {"tool_name": "Bash"}, "test-session"
        )
        assert results == []
        chain.execute.assert_not_called()

    def test_fires_2_of_6(self) -> None:
        """With '2/6' trigger, fire on last 2 of each 6-call window."""
        dispatcher = self._make_dispatcher("pre_tool_use:2/6")
        hook_input: dict[str, Any] = {"tool_name": "Bash"}
        session_id = "test-session"

        results_by_call: list[list[HookResult]] = []
        for _ in range(12):
            results = dispatcher.check_and_fire(EventType.PRE_TOOL_USE, hook_input, session_id)
            results_by_call.append(results)

        fired = [i for i, r in enumerate(results_by_call) if len(r) > 0]
        # 2/6 means fire on 5th and 6th of each window (last N in each D-window)
        # Counts 1-6: fire at 5 (rem=5>4) and 6 (rem=0) → 0-indexed: 4, 5
        # Counts 7-12: fire at 11 (rem=5>4) and 12 (rem=0) → 0-indexed: 10, 11
        assert fired == [4, 5, 10, 11]


# ─── PseudoEventDispatcher Setup & Dispatch ───


class TestPseudoEventDispatcherSetupAndDispatch:
    """Test setup function invocation and handler chain dispatch."""

    def test_setup_function_called_with_hook_input_and_session(self) -> None:
        """Setup function receives hook_input and session_id."""
        config = PseudoEventConfig.from_dict(
            "nitpick",
            {"triggers": ["pre_tool_use:1/1"], "handlers": {}},
        )
        dispatcher = PseudoEventDispatcher()
        setup_fn = MagicMock(side_effect=lambda hook_input, sid: {**hook_input, "enriched": True})
        chain = MagicMock()
        chain.execute.return_value = ChainExecutionResult(result=HookResult.allow())
        dispatcher.register(config, setup_fn=setup_fn, chain=chain)

        hook_input: dict[str, Any] = {"tool_name": "Bash"}
        dispatcher.check_and_fire(EventType.PRE_TOOL_USE, hook_input, "session-1")

        setup_fn.assert_called_once_with(hook_input, "session-1")

    def test_enriched_input_passed_to_chain(self) -> None:
        """Handler chain receives enriched hook_input from setup function."""
        config = PseudoEventConfig.from_dict(
            "nitpick",
            {"triggers": ["pre_tool_use:1/1"], "handlers": {}},
        )
        dispatcher = PseudoEventDispatcher()
        enriched = {"tool_name": "Bash", "pseudo_event": "nitpick", "assistant_messages": []}
        setup_fn = MagicMock(return_value=enriched)
        chain = MagicMock()
        chain.execute.return_value = ChainExecutionResult(result=HookResult.allow())
        dispatcher.register(config, setup_fn=setup_fn, chain=chain)

        dispatcher.check_and_fire(EventType.PRE_TOOL_USE, {"tool_name": "Bash"}, "session-1")

        chain.execute.assert_called_once_with(enriched)

    def test_setup_returning_none_skips_dispatch(self) -> None:
        """If setup returns None, skip handler chain dispatch (no new data)."""
        config = PseudoEventConfig.from_dict(
            "nitpick",
            {"triggers": ["pre_tool_use:1/1"], "handlers": {}},
        )
        dispatcher = PseudoEventDispatcher()
        setup_fn = MagicMock(return_value=None)
        chain = MagicMock()
        dispatcher.register(config, setup_fn=setup_fn, chain=chain)

        results = dispatcher.check_and_fire(
            EventType.PRE_TOOL_USE, {"tool_name": "Bash"}, "session-1"
        )
        assert results == []
        chain.execute.assert_not_called()

    def test_chain_result_returned(self) -> None:
        """Handler chain result is returned to caller."""
        config = PseudoEventConfig.from_dict(
            "nitpick",
            {"triggers": ["pre_tool_use:1/1"], "handlers": {}},
        )
        dispatcher = PseudoEventDispatcher()
        setup_fn = MagicMock(side_effect=lambda hi, sid: hi)
        expected_result = HookResult.deny(reason="Dismissive language detected")
        chain = MagicMock()
        chain.execute.return_value = ChainExecutionResult(result=expected_result)
        dispatcher.register(config, setup_fn=setup_fn, chain=chain)

        results = dispatcher.check_and_fire(
            EventType.PRE_TOOL_USE, {"tool_name": "Bash"}, "session-1"
        )
        assert len(results) == 1
        assert results[0].decision == Decision.DENY


class TestPseudoEventDispatcherMultiTrigger:
    """Test pseudo-events with multiple triggers."""

    def test_multiple_triggers_fire_independently(self) -> None:
        """A pseudo-event with triggers on PreToolUse and Stop fires from either."""
        config = PseudoEventConfig.from_dict(
            "nitpick",
            {
                "triggers": ["pre_tool_use:1/3", "stop:1/1"],
                "handlers": {},
            },
        )
        dispatcher = PseudoEventDispatcher()
        setup_fn = MagicMock(side_effect=lambda hi, sid: hi)
        chain = MagicMock()
        chain.execute.return_value = ChainExecutionResult(
            result=HookResult.allow(context=["nitpick context"])
        )
        dispatcher.register(config, setup_fn=setup_fn, chain=chain)

        session = "test"

        # Stop fires every time
        results = dispatcher.check_and_fire(EventType.STOP, {}, session)
        assert len(results) == 1

        # PreToolUse: 1st and 2nd don't fire
        results = dispatcher.check_and_fire(EventType.PRE_TOOL_USE, {}, session)
        assert len(results) == 0
        results = dispatcher.check_and_fire(EventType.PRE_TOOL_USE, {}, session)
        assert len(results) == 0

        # PreToolUse: 3rd fires
        results = dispatcher.check_and_fire(EventType.PRE_TOOL_USE, {}, session)
        assert len(results) == 1


# ─── Result Merging ───


class TestMergePseudoResults:
    """Test merging pseudo-event results into real chain results."""

    def test_allow_plus_allow_stays_allow(self) -> None:
        """Allow from both real and pseudo stays allow."""
        real = ChainExecutionResult(result=HookResult.allow())
        pseudo = [HookResult.allow(context=["pseudo context"])]

        merged = merge_pseudo_results(real, pseudo)
        assert merged.result.decision == Decision.ALLOW
        assert "pseudo context" in merged.result.context

    def test_deny_from_pseudo_overrides_allow(self) -> None:
        """Deny from pseudo-event overrides real allow."""
        real = ChainExecutionResult(result=HookResult.allow(context=["real context"]))
        pseudo = [HookResult.deny(reason="Dismissive language")]

        merged = merge_pseudo_results(real, pseudo)
        assert merged.result.decision == Decision.DENY
        assert merged.result.reason == "Dismissive language"
        assert "real context" in merged.result.context

    def test_deny_from_real_preserved_over_pseudo_allow(self) -> None:
        """Deny from real is preserved even if pseudo allows."""
        real = ChainExecutionResult(result=HookResult.deny(reason="Real denial"))
        pseudo = [HookResult.allow(context=["pseudo context"])]

        merged = merge_pseudo_results(real, pseudo)
        assert merged.result.decision == Decision.DENY
        assert merged.result.reason == "Real denial"
        assert "pseudo context" in merged.result.context

    def test_ask_upgrades_allow(self) -> None:
        """Ask from pseudo upgrades real allow to ask."""
        real = ChainExecutionResult(result=HookResult.allow())
        pseudo = [HookResult.ask(reason="Please confirm")]

        merged = merge_pseudo_results(real, pseudo)
        assert merged.result.decision == Decision.ASK
        assert merged.result.reason == "Please confirm"

    def test_deny_beats_ask(self) -> None:
        """Deny from pseudo beats ask."""
        real = ChainExecutionResult(result=HookResult.ask(reason="Ask first"))
        pseudo = [HookResult.deny(reason="Blocked")]

        merged = merge_pseudo_results(real, pseudo)
        assert merged.result.decision == Decision.DENY
        assert merged.result.reason == "Blocked"

    def test_context_accumulates_from_multiple_pseudo(self) -> None:
        """Context from multiple pseudo results accumulates."""
        real = ChainExecutionResult(result=HookResult.allow(context=["real"]))
        pseudo = [
            HookResult.allow(context=["pseudo-1"]),
            HookResult.allow(context=["pseudo-2"]),
        ]

        merged = merge_pseudo_results(real, pseudo)
        assert "real" in merged.result.context
        assert "pseudo-1" in merged.result.context
        assert "pseudo-2" in merged.result.context

    def test_empty_pseudo_results_no_change(self) -> None:
        """Empty pseudo results leave real result unchanged."""
        real = ChainExecutionResult(
            result=HookResult.allow(context=["real"]),
            handlers_executed=["handler-a"],
        )

        merged = merge_pseudo_results(real, [])
        assert merged.result.decision == Decision.ALLOW
        assert merged.result.context == ["real"]

    def test_multiple_deny_first_reason_wins(self) -> None:
        """With multiple denials, first denial reason wins."""
        real = ChainExecutionResult(result=HookResult.allow())
        pseudo = [
            HookResult.deny(reason="First denial"),
            HookResult.deny(reason="Second denial"),
        ]

        merged = merge_pseudo_results(real, pseudo)
        assert merged.result.decision == Decision.DENY
        assert merged.result.reason == "First denial"
