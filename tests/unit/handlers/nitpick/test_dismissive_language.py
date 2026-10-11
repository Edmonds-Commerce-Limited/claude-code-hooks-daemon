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


class TestPrematureHaltIsDetected:
    """Plan 00237: the running detector must see premature-halt language.

    ``PREMATURE_STOP_PATTERNS`` lived only on the Stop-event twin, which
    ``auto_continue_stop`` shadows, and the nitpick handler imported four of
    the five dismissive pattern sets — so this whole category has never fired
    in production. The Stop twin is being deleted, which makes carrying this
    set across a behaviour CHANGE rather than a refactor, and it gets its own
    test rather than riding on the four that were already wired.
    """

    def test_dressing_up_a_mid_task_halt_fires(self) -> None:
        handler = DismissiveLanguageNitpickHandler()
        text = "Phase 1 is done — this is a natural checkpoint, pausing here."
        result = handler.handle(_make_hook_input([{"uuid": "u1", "content": text}]))
        assert result.context, "premature-halt phrasing must be flagged"

    def test_awaiting_instruction_fires(self) -> None:
        handler = DismissiveLanguageNitpickHandler()
        text = "I have committed the change and am awaiting your instruction."
        result = handler.handle(_make_hook_input([{"uuid": "u1", "content": text}]))
        assert result.context

    def test_quoting_the_phrase_is_still_a_mention_not_a_halt(self) -> None:
        """The Plan 00225 quoting rule must hold for this category too.

        Without this, carrying the set across would reintroduce the exact
        unsatisfiable-advisory bug that rule exists to prevent.
        """
        handler = DismissiveLanguageNitpickHandler()
        text = 'The hook flagged my "pausing here" and it was right — continuing now.'
        result = handler.handle(_make_hook_input([{"uuid": "u1", "content": text}]))
        assert not result.context

    def test_ordinary_completion_prose_does_not_fire(self) -> None:
        """Guard the guard: the category must not fire on any finished-work text."""
        handler = DismissiveLanguageNitpickHandler()
        text = "All five handlers are removed, QA passes, and the daemon restarts."
        result = handler.handle(_make_hook_input([{"uuid": "u1", "content": text}]))
        assert not result.context


class TestMentioningAPhraseIsNotDeflecting:
    """Plan 00225: a QUOTED trigger phrase is a mention, not a deflection.

    The advisory says "acknowledge and offer to fix instead of deflecting".
    Naming the phrase is how one acknowledges, so quoting it re-fired the
    advisory and made the instruction unsatisfiable.
    """

    def test_a_quoted_phrase_does_not_fire(self) -> None:
        handler = DismissiveLanguageNitpickHandler()
        text = 'The hook flagged my "out of scope" and it was right — I will fix it.'
        result = handler.handle(_make_hook_input([{"uuid": "u1", "content": text}]))
        assert not result.context

    def test_a_genuine_deflection_still_fires(self) -> None:
        """The other half: a fix that merely muted the detector must not pass."""
        handler = DismissiveLanguageNitpickHandler()
        text = "That is out of scope for this change."
        result = handler.handle(_make_hook_input([{"uuid": "u1", "content": text}]))
        assert result.context

    def test_quoting_elsewhere_does_not_launder_a_real_deflection(self) -> None:
        handler = DismissiveLanguageNitpickHandler()
        text = 'She said "hello" but that is out of scope and I will not fix it.'
        result = handler.handle(_make_hook_input([{"uuid": "u1", "content": text}]))
        assert result.context


class TestOutOfScopeGroundedInACitedReason:
    """N353: "out of scope" grounded in a cited reason is a finding, not a deflection."""

    def _fires(self, text: str) -> bool:
        handler = DismissiveLanguageNitpickHandler()
        result = handler.handle(_make_hook_input([{"uuid": "u1", "content": text}]))
        return bool(result.context)

    def test_threat_model_citation_does_not_fire(self) -> None:
        text = "The threat model already treats that kind of deliberate evasion as out of scope."
        assert not self._fires(text)

    def test_out_of_scope_under_the_threat_model_does_not_fire(self) -> None:
        assert not self._fires("Deliberate evasion is out of scope under the threat model.")

    def test_out_of_scope_per_owner_ruling_does_not_fire(self) -> None:
        assert not self._fires("That case is out of scope per owner ruling A1.")

    def test_out_of_scope_per_plan_non_goals_does_not_fire(self) -> None:
        assert not self._fires("Renaming is out of scope per the plan's Non-Goals.")

    def test_bare_out_of_scope_still_fires(self) -> None:
        assert self._fires("That is out of scope for this change.")

    def test_reason_in_another_sentence_does_not_launder_a_bare_deflection(self) -> None:
        text = "The threat model is documented. That failing test is out of scope."
        assert self._fires(text)

    def test_a_bare_per_the_plan_does_not_ground_a_deflection(self) -> None:
        text = "Per the plan I ran the tests, and the lint failure is out of scope."
        assert self._fires(text)

    def test_a_semicolon_separates_the_reason_from_the_deflection(self) -> None:
        text = "The threat model is documented; that failing test is out of scope."
        assert self._fires(text)

    def test_a_passing_limb_number_does_not_ground_a_deflection(self) -> None:
        text = "I fixed limb 2 first, and the other failure is out of scope."
        assert self._fires(text)

    def test_per_plan_with_an_id_does_not_fire(self) -> None:
        assert not self._fires("That is out of scope per plan 00483.")

    def test_limb_citation_shapes_do_not_fire(self) -> None:
        assert not self._fires("Evasion is out of scope under limb 2 of the rule.")
        assert not self._fires("Deliberate evasion is out of scope (limb 1).")

    def test_owner_decision_does_not_fire(self) -> None:
        assert not self._fires("That is out of scope by the owner decision A1.")

    def test_per_ruling_does_not_fire(self) -> None:
        assert not self._fires("That is out of scope per ruling R3.")

    def test_other_categories_are_not_exempted_by_a_citation(self) -> None:
        assert self._fires("Per the threat model, that was a pre-existing issue.")


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
