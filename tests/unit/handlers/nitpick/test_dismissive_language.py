"""Tests for DismissiveLanguageNitpickHandler.

TDD RED phase: Tests define expected behavior for the nitpick pseudo-event
handler that detects dismissive language in assistant messages.
"""

from __future__ import annotations

from typing import Any

from claude_code_hooks_daemon.handlers.nitpick.dismissive_language import (
    DismissiveLanguageNitpickHandler,
)


def _make_hook_input(messages: list[dict[str, str]]) -> dict[str, Any]:
    """Create hook_input with assistant_messages (as provided by NitpickSetup)."""
    return {
        "pseudo_event": "nitpick",
        "assistant_messages": messages,
        "tool_name": "Bash",
    }


class TestDismissiveLanguageNitpickInit:
    """Test handler initialisation."""

    def test_handler_id(self) -> None:
        """Handler has correct config_key."""
        handler = DismissiveLanguageNitpickHandler()
        assert handler.name == "nitpick-dismissive-language"

    def test_priority(self) -> None:
        """Handler has a priority value."""
        handler = DismissiveLanguageNitpickHandler()
        assert handler.priority >= 0

    def test_non_terminal(self) -> None:
        """Handler is non-terminal (advisory)."""
        handler = DismissiveLanguageNitpickHandler()
        assert handler.terminal is False


class TestDismissiveLanguageNitpickMatches:
    """Test matches() behavior."""

    def test_matches_when_assistant_messages_present(self) -> None:
        """Matches when hook_input has assistant_messages."""
        handler = DismissiveLanguageNitpickHandler()
        hook_input = _make_hook_input([{"uuid": "u1", "content": "Some text"}])
        assert handler.matches(hook_input) is True

    def test_no_match_without_assistant_messages(self) -> None:
        """Does not match when assistant_messages is missing."""
        handler = DismissiveLanguageNitpickHandler()
        assert handler.matches({"tool_name": "Bash"}) is False

    def test_no_match_with_empty_messages(self) -> None:
        """Does not match when assistant_messages is empty."""
        handler = DismissiveLanguageNitpickHandler()
        assert handler.matches(_make_hook_input([])) is False


class TestDismissiveLanguageNitpickHandle:
    """Test handle() behavior."""

    def test_detects_not_our_problem(self) -> None:
        """Detects 'pre-existing issue' as dismissive language."""
        handler = DismissiveLanguageNitpickHandler()
        hook_input = _make_hook_input(
            [{"uuid": "u1", "content": "This is a pre-existing issue, not related to my changes"}]
        )
        result = handler.handle(hook_input)
        assert len(result.context) > 0
        assert any("dismissive" in c.lower() for c in result.context)

    def test_detects_out_of_scope(self) -> None:
        """Detects 'outside the scope' as dismissive language."""
        handler = DismissiveLanguageNitpickHandler()
        hook_input = _make_hook_input(
            [{"uuid": "u1", "content": "That issue is outside the scope of this task"}]
        )
        result = handler.handle(hook_input)
        assert len(result.context) > 0

    def test_detects_defer_ignore(self) -> None:
        """Detects 'can be addressed later' as dismissive language."""
        handler = DismissiveLanguageNitpickHandler()
        hook_input = _make_hook_input(
            [{"uuid": "u1", "content": "This can be addressed later in a follow-up"}]
        )
        result = handler.handle(hook_input)
        assert len(result.context) > 0

    def test_no_findings_for_clean_text(self) -> None:
        """No findings when text is clean."""
        handler = DismissiveLanguageNitpickHandler()
        hook_input = _make_hook_input(
            [{"uuid": "u1", "content": "I have implemented the feature and all tests pass."}]
        )
        result = handler.handle(hook_input)
        assert len(result.context) == 0

    def test_scans_all_messages(self) -> None:
        """Scans all assistant messages, not just the first."""
        handler = DismissiveLanguageNitpickHandler()
        hook_input = _make_hook_input(
            [
                {"uuid": "u1", "content": "Clean text here."},
                {"uuid": "u2", "content": "This is a pre-existing issue."},
            ]
        )
        result = handler.handle(hook_input)
        assert len(result.context) > 0

    def test_returns_allow_decision(self) -> None:
        """Handler always returns allow (advisory only)."""
        handler = DismissiveLanguageNitpickHandler()
        hook_input = _make_hook_input([{"uuid": "u1", "content": "This is a pre-existing issue."}])
        result = handler.handle(hook_input)
        assert result.decision.value == "allow"

    def test_empty_content_message_skipped(self) -> None:
        """Messages with empty content are skipped (line 92)."""
        handler = DismissiveLanguageNitpickHandler()
        hook_input = _make_hook_input(
            [
                {"uuid": "u1", "content": ""},
                {"uuid": "u2", "content": "This is a pre-existing issue."},
            ]
        )
        result = handler.handle(hook_input)
        # Only the second message triggers detection
        assert len(result.context) > 0


class TestDismissiveLanguageNitpickDedupe:
    """Identical advisory lines must not be repeated (Plan 00146).

    Dogfooding evidence: six identical 'Dismissive language detected (out of
    scope)' lines injected in one advisory — one per matching pattern per
    message. The handler must emit at most ONE line per category regardless of
    how many patterns or messages match it.
    """

    def test_multiple_patterns_same_category_emit_one_line(self) -> None:
        """Several patterns of one category matching one message → one line."""
        handler = DismissiveLanguageNitpickHandler()
        hook_input = _make_hook_input(
            [
                {
                    "uuid": "u1",
                    "content": (
                        "That is out of scope and falls outside the scope of "
                        "this task; it is beyond the scope of the plan."
                    ),
                }
            ]
        )
        result = handler.handle(hook_input)
        assert len(result.context) == 1
        assert "out of scope" in result.context[0]

    def test_same_category_across_messages_emits_one_line(self) -> None:
        """The same category matching in several messages → one line."""
        handler = DismissiveLanguageNitpickHandler()
        hook_input = _make_hook_input(
            [
                {"uuid": "u1", "content": "This is out of scope."},
                {"uuid": "u2", "content": "That also falls outside our remit, out of scope."},
                {"uuid": "u3", "content": "Again: out of scope."},
            ]
        )
        result = handler.handle(hook_input)
        assert len(result.context) == 1

    def test_distinct_categories_emit_one_line_each(self) -> None:
        """Two different categories → two lines, one per category."""
        handler = DismissiveLanguageNitpickHandler()
        hook_input = _make_hook_input(
            [
                {"uuid": "u1", "content": "This is a pre-existing issue."},
                {"uuid": "u2", "content": "And that is out of scope."},
            ]
        )
        result = handler.handle(hook_input)
        assert len(result.context) == 2
