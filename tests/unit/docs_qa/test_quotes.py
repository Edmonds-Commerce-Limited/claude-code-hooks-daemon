"""Tests for ``docs_qa.quotes`` (Plan 00284, Task 3.1d)."""

from pathlib import Path

from claude_code_hooks_daemon.docs_qa.quotes import (
    MIN_QUOTE_LENGTH_CHARS,
    QuoteBlock,
    normalise_markdown,
    parse_quote_blocks,
    resolve_anchor_span,
    slugify_heading,
    verify_quote,
)


class TestSlugifyHeading:
    def test_lowercases_and_hyphenates_spaces(self) -> None:
        assert slugify_heading("Daemon Restart Verification") == "daemon-restart-verification"

    def test_strips_punctuation(self) -> None:
        assert slugify_heading("Overview: What This Is") == "overview-what-this-is"

    def test_strips_emoji_and_symbols(self) -> None:
        assert slugify_heading("🚨 CRITICAL: Read This") == "critical-read-this"

    def test_collapses_internal_whitespace(self) -> None:
        assert slugify_heading("Two   Spaces") == "two-spaces"

    def test_strips_leading_trailing_whitespace(self) -> None:
        assert slugify_heading("  Padded  ") == "padded"


class TestResolveAnchorSpanByHeading:
    def test_extracts_section_up_to_next_same_level_heading(self) -> None:
        text = "# Title\n\n## Overview\n\nBody line one.\n\nBody line two.\n\n## Next\n\nOther.\n"
        span = resolve_anchor_span(text, "overview")
        assert span is not None
        assert "Body line one." in span
        assert "Body line two." in span
        assert "Other." not in span
        assert "## Next" not in span

    def test_extracts_section_up_to_next_higher_level_heading(self) -> None:
        text = "# Title\n\n## Section\n\n### Sub\n\nSub body.\n\n## Next\n\nOther.\n"
        span = resolve_anchor_span(text, "section")
        assert span is not None
        assert "### Sub" in span
        assert "Sub body." in span
        assert "Other." not in span

    def test_extracts_to_end_of_document_when_no_later_heading(self) -> None:
        text = "# Title\n\n## Last\n\nFinal content.\n"
        span = resolve_anchor_span(text, "last")
        assert span is not None
        assert "Final content." in span

    def test_returns_none_for_unknown_anchor(self) -> None:
        text = "# Title\n\n## Overview\n\nBody.\n"
        assert resolve_anchor_span(text, "nonexistent") is None

    def test_heading_inside_fence_is_not_a_boundary(self) -> None:
        text = (
            "## Overview\n\nBody.\n\n```markdown\n## Fake Heading\nFenced content.\n```\n\n"
            "More real body.\n\n## Next\n\nOther.\n"
        )
        span = resolve_anchor_span(text, "overview")
        assert span is not None
        assert "Fenced content." in span
        assert "More real body." in span
        assert "Other." not in span

    def test_matches_first_heading_on_duplicate_slugs(self) -> None:
        text = "## Dup\n\nFirst.\n\n## Dup\n\nSecond.\n"
        span = resolve_anchor_span(text, "dup")
        assert span is not None
        assert "First." in span
        assert "Second." not in span


class TestFenceMaskMismatchedMarkers:
    def test_a_tilde_fence_line_inside_a_backtick_fence_does_not_close_it(self) -> None:
        text = "## Overview\n\n```\n~~~\n## Fake Heading\n```\n\nReal body.\n\n## Next\n\nOther.\n"
        span = resolve_anchor_span(text, "overview")
        assert span is not None
        assert "Real body." in span
        assert "Other." not in span


class TestResolveAnchorSpanByMarker:
    def test_explicit_marker_is_preferred_over_heading_slug(self) -> None:
        text = (
            "## Overview\n\nIntro.\n\n<!-- ssot-anchor: overview -->\n\nMarked body.\n\n"
            "## Next\n\nOther.\n"
        )
        span = resolve_anchor_span(text, "overview")
        assert span is not None
        assert "Marked body." in span
        assert "Intro." not in span
        assert "Other." not in span

    def test_marker_span_bounded_by_enclosing_heading_level(self) -> None:
        text = (
            "## Section\n\n<!-- ssot-anchor: marked -->\n\nBody.\n\n### Sub\n\nSub body.\n\n"
            "## Next\n\nOther.\n"
        )
        span = resolve_anchor_span(text, "marked")
        assert span is not None
        assert "Body." in span
        assert "### Sub" in span
        assert "Sub body." in span
        assert "Other." not in span

    def test_marker_inside_fence_is_ignored(self) -> None:
        text = "## Overview\n\n```\n<!-- ssot-anchor: overview -->\n```\n\nReal body.\n"
        span = resolve_anchor_span(text, "overview")
        assert span is not None
        # Falls back to the heading match since the fenced marker doesn't count.
        assert "Real body." in span


class TestParseQuoteBlocks:
    def test_parses_a_single_block(self, tmp_path: Path) -> None:
        text = (
            "prose\n\n<!-- ssot-quote: CLAUDE/Doc.md#anchor -->\nquoted text\n"
            "<!-- /ssot-quote -->\n\nmore prose\n"
        )
        blocks = parse_quote_blocks(text)
        assert len(blocks) == 1
        assert blocks[0] == QuoteBlock(
            source_path="CLAUDE/Doc.md", anchor="anchor", body="quoted text"
        )

    def test_parses_multiple_blocks(self) -> None:
        text = (
            "<!-- ssot-quote: A.md#one -->\nbody one\n<!-- /ssot-quote -->\n\n"
            "<!-- ssot-quote: B.md#two -->\nbody two\n<!-- /ssot-quote -->\n"
        )
        blocks = parse_quote_blocks(text)
        assert [b.source_path for b in blocks] == ["A.md", "B.md"]
        assert [b.anchor for b in blocks] == ["one", "two"]

    def test_multiline_body_preserved(self) -> None:
        text = "<!-- ssot-quote: A.md#x -->\nline one\nline two\n<!-- /ssot-quote -->\n"
        blocks = parse_quote_blocks(text)
        assert blocks[0].body == "line one\nline two"

    def test_no_blocks_returns_empty_list(self) -> None:
        assert parse_quote_blocks("just prose, no quotes here\n") == []

    def test_markers_inside_fence_are_ignored(self) -> None:
        text = "```\n<!-- ssot-quote: A.md#x -->\nfake\n<!-- /ssot-quote -->\n```\n\nreal prose\n"
        assert parse_quote_blocks(text) == []

    def test_body_may_itself_contain_a_fence(self) -> None:
        text = "<!-- ssot-quote: A.md#x -->\n```bash\necho hi\n```\n<!-- /ssot-quote -->\n"
        blocks = parse_quote_blocks(text)
        assert blocks[0].body == "```bash\necho hi\n```"

    def test_unclosed_block_is_ignored(self) -> None:
        text = "<!-- ssot-quote: A.md#x -->\nno closing marker\n"
        assert parse_quote_blocks(text) == []


class TestNormaliseMarkdown:
    def test_uses_the_shared_mdformat_pipeline(self) -> None:
        # format_markdown_text collapses inconsistent emphasis markers etc.;
        # this just proves normalise_markdown delegates rather than reimplementing.
        from claude_code_hooks_daemon.utils.markdown_format import format_markdown_text

        text = "Some   *text*  here.\n"
        assert normalise_markdown(text) == format_markdown_text(text)


class TestVerifyQuote:
    def test_matching_substring_verifies_clean(self) -> None:
        quote = (
            "This exact sentence appears verbatim in the source section below, and it "
            "is long enough to clear the minimum quote length."
        )
        span = f"Intro.\n\n{quote}\n\nMore text.\n"
        assert len(quote) >= MIN_QUOTE_LENGTH_CHARS
        assert verify_quote(quote, span) is True

    def test_drifted_text_fails(self) -> None:
        quote = (
            "This sentence was changed and no longer matches the source at all, so it "
            "should be reported as drift."
        )
        span = (
            "Intro.\n\nThe original sentence is entirely different unrelated content "
            "that shares no meaningful overlap.\n"
        )
        assert len(quote) >= MIN_QUOTE_LENGTH_CHARS
        assert verify_quote(quote, span) is False

    def test_below_minimum_length_fails_even_if_present(self) -> None:
        quote = "short"
        span = f"Intro.\n\n{quote}\n\nMore.\n"
        assert len(quote) < MIN_QUOTE_LENGTH_CHARS
        assert verify_quote(quote, span) is False
