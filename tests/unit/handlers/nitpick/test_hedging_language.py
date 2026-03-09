"""Tests for HedgingLanguageNitpickHandler.

TDD RED phase: Tests define expected behavior for the nitpick pseudo-event
handler that detects hedging language in assistant messages.
"""

from __future__ import annotations

from typing import Any

from claude_code_hooks_daemon.handlers.nitpick.hedging_language import (
    HedgingLanguageNitpickHandler,
)


def _make_hook_input(messages: list[dict[str, str]]) -> dict[str, Any]:
    """Create hook_input with assistant_messages (as provided by NitpickSetup)."""
    return {
        "pseudo_event": "nitpick",
        "assistant_messages": messages,
        "tool_name": "Bash",
    }


class TestHedgingLanguageNitpickInit:
    """Test handler initialisation."""

    def test_handler_id(self) -> None:
        """Handler has correct display name."""
        handler = HedgingLanguageNitpickHandler()
        assert handler.name == "nitpick-hedging-language"

    def test_priority(self) -> None:
        """Handler has a priority value."""
        handler = HedgingLanguageNitpickHandler()
        assert handler.priority >= 0

    def test_non_terminal(self) -> None:
        """Handler is non-terminal (advisory)."""
        handler = HedgingLanguageNitpickHandler()
        assert handler.terminal is False


class TestHedgingLanguageNitpickMatches:
    """Test matches() behavior."""

    def test_matches_when_assistant_messages_present(self) -> None:
        """Matches when hook_input has assistant_messages."""
        handler = HedgingLanguageNitpickHandler()
        hook_input = _make_hook_input([{"uuid": "u1", "content": "Some text"}])
        assert handler.matches(hook_input) is True

    def test_no_match_without_assistant_messages(self) -> None:
        """Does not match when assistant_messages is missing."""
        handler = HedgingLanguageNitpickHandler()
        assert handler.matches({"tool_name": "Bash"}) is False

    def test_no_match_with_empty_messages(self) -> None:
        """Does not match when assistant_messages is empty."""
        handler = HedgingLanguageNitpickHandler()
        assert handler.matches(_make_hook_input([])) is False


class TestHedgingLanguageNitpickHandle:
    """Test handle() behavior."""

    def test_detects_memory_guessing(self) -> None:
        """Detects 'if I recall' as hedging language."""
        handler = HedgingLanguageNitpickHandler()
        hook_input = _make_hook_input(
            [{"uuid": "u1", "content": "If I recall correctly, this API uses REST"}]
        )
        result = handler.handle(hook_input)
        assert len(result.context) > 0
        assert any("hedging" in c.lower() for c in result.context)

    def test_detects_uncertainty(self) -> None:
        """Detects 'probably' as hedging language."""
        handler = HedgingLanguageNitpickHandler()
        hook_input = _make_hook_input(
            [{"uuid": "u1", "content": "This should probably work with the new version"}]
        )
        result = handler.handle(hook_input)
        assert len(result.context) > 0

    def test_detects_weak_confidence(self) -> None:
        """Detects 'I'm not sure but' as hedging language."""
        handler = HedgingLanguageNitpickHandler()
        hook_input = _make_hook_input(
            [{"uuid": "u1", "content": "I'm not sure but I think the config uses YAML"}]
        )
        result = handler.handle(hook_input)
        assert len(result.context) > 0

    def test_no_findings_for_clean_text(self) -> None:
        """No findings when text is clean."""
        handler = HedgingLanguageNitpickHandler()
        hook_input = _make_hook_input(
            [{"uuid": "u1", "content": "I have verified the API uses REST by checking the docs."}]
        )
        result = handler.handle(hook_input)
        assert len(result.context) == 0

    def test_scans_all_messages(self) -> None:
        """Scans all assistant messages, not just the first."""
        handler = HedgingLanguageNitpickHandler()
        hook_input = _make_hook_input(
            [
                {"uuid": "u1", "content": "Clean verified text here."},
                {"uuid": "u2", "content": "If I recall correctly, this uses YAML."},
            ]
        )
        result = handler.handle(hook_input)
        assert len(result.context) > 0

    def test_returns_allow_decision(self) -> None:
        """Handler always returns allow (advisory only)."""
        handler = HedgingLanguageNitpickHandler()
        hook_input = _make_hook_input(
            [{"uuid": "u1", "content": "If I recall correctly, this uses YAML."}]
        )
        result = handler.handle(hook_input)
        assert result.decision.value == "allow"
