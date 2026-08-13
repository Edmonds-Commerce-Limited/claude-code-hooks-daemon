"""Tests for quoted-span blanking (Plan 00225).

The dismissive- and hedging-language detectors match trigger phrases by plain
substring, so they cannot tell a phrase being USED to deflect from one being
MENTIONED while acknowledging the advisory. Since the advisory itself says
"acknowledge and offer to fix instead of deflecting", naming the phrase is the
natural way to comply — and re-triggers the advisory. The instruction is
unsatisfiable as written.

The fix mirrors ``pipe_blocker._strip_message_bodies`` (Plan 00222): blank the
exempt span and scan a COPY, leaving the pattern lists untouched.
"""

from __future__ import annotations

from claude_code_hooks_daemon.utils.quoted_spans import blank_quoted_spans


class TestDoubleQuotesMarkAMention:
    def test_double_quoted_content_is_blanked(self) -> None:
        text = 'The hook flagged my "out of scope" and it was right.'
        assert "out of scope" not in blank_quoted_spans(text)

    def test_text_outside_the_quotes_survives(self) -> None:
        """Only the quoted span goes — the rest must still be scannable."""
        text = 'The hook flagged my "out of scope" and it was right.'
        result = blank_quoted_spans(text)
        assert "The hook flagged my" in result
        assert "and it was right" in result

    def test_an_unquoted_phrase_elsewhere_still_survives(self) -> None:
        """Quoting one span must not launder a genuine deflection beside it."""
        text = 'She said "hello" but that is out of scope for this change.'
        assert "out of scope" in blank_quoted_spans(text)


class TestBackticksMarkAMention:
    def test_backticked_content_is_blanked(self) -> None:
        text = "The `out of scope` pattern is the one that fired."
        assert "out of scope" not in blank_quoted_spans(text)


class TestSingleQuotesAreNotMentionMarkers:
    """Apostrophes make single quotes unreliable in English prose.

    ``pipe_blocker`` records the same constraint: an apostrophe inside a word
    ("doesn't") would read as an opening quote. Prose is full of apostrophes,
    so pairing on them would blank arbitrary spans of real sentences — and a
    blanked span is a span the detector can no longer see.
    """

    def test_apostrophes_do_not_blank_the_text_between_them(self) -> None:
        text = "I don't think it's worth doing."
        assert blank_quoted_spans(text) == text

    def test_a_single_quoted_deflection_still_fires(self) -> None:
        text = "That is 'out of scope' and I will not be fixing it."
        assert "out of scope" in blank_quoted_spans(text)


class TestFailsOpen:
    """An unparseable span must leave the text scannable, never blank it."""

    def test_unterminated_double_quote_leaves_text_unchanged(self) -> None:
        text = 'He said "that is out of scope and never closed the quote'
        assert blank_quoted_spans(text) == text

    def test_unterminated_backtick_leaves_text_unchanged(self) -> None:
        text = "The `out of scope pattern never closed"
        assert blank_quoted_spans(text) == text

    def test_text_without_quotes_is_returned_unchanged(self) -> None:
        text = "That is out of scope for this change."
        assert blank_quoted_spans(text) == text

    def test_empty_text_is_handled(self) -> None:
        assert blank_quoted_spans("") == ""


class TestBlankingPreservesLength:
    """Offsets must stay stable so any future span-reporting still lines up."""

    def test_blanked_text_is_the_same_length(self) -> None:
        text = 'The hook flagged my "out of scope" and it was right.'
        assert len(blank_quoted_spans(text)) == len(text)
