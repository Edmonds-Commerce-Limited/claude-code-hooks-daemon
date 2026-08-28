"""Tests for ``docs_qa.structured_blocks`` (Plan 00284, Task 3.1f)."""

from claude_code_hooks_daemon.docs_qa.structured_blocks import (
    MIN_BLOCK_LENGTH_CHARS,
    MIN_LIST_ITEMS,
    BlockLocation,
    extract_structured_block_hashes,
    extract_structured_block_locations,
    extract_structured_blocks,
)

# A body long enough to clear MIN_BLOCK_LENGTH_CHARS after normalisation —
# mirrors the _LONG_SENTENCE idiom in test_quote_drift.py.
_LONG_FENCE_BODY = "\n".join(
    f"echo 'line number {n} of a long fenced example block'" for n in range(6)
)
_LONG_TABLE = "\n".join(
    [
        "| Column One | Column Two | Column Three |",
        "| ---------- | ---------- | ------------ |",
        "| aaaaaaaaaa | bbbbbbbbbb | cccccccccccc |",
        "| dddddddddd | eeeeeeeeee | ffffffffffff |",
        "| gggggggggg | hhhhhhhhhh | iiiiiiiiiiii |",
    ]
)
_LONG_LIST = "\n".join(
    [
        "1. This is the first sufficiently long enumerated list item here.",
        "2. This is the second sufficiently long enumerated list item here.",
        "3. This is the third sufficiently long enumerated list item here.",
        "4. This is the fourth sufficiently long enumerated list item here.",
    ]
)


def _fence(body: str, lang: str = "bash") -> str:
    return f"```{lang}\n{body}\n```"


class TestFencedCodeBlocks:
    def test_extracts_a_fenced_block_over_the_length_floor(self) -> None:
        text = f"Some prose.\n\n{_fence(_LONG_FENCE_BODY)}\n\nMore prose.\n"
        blocks = extract_structured_blocks(text)
        assert len(blocks) == 1
        assert "line number 0" in blocks[0]

    def test_tiny_fence_below_the_length_floor_is_never_returned(self) -> None:
        text = f"Restart the daemon:\n\n{_fence('./bin/hooks-daemon restart')}\n"
        hashes = extract_structured_block_hashes(text)
        assert hashes == ()

    def test_unclosed_fence_is_ignored_rather_than_guessed(self) -> None:
        text = f"Prose.\n\n```bash\n{_LONG_FENCE_BODY}\n"
        assert extract_structured_blocks(text) == []

    def test_tilde_fences_are_recognised(self) -> None:
        text = f"~~~bash\n{_LONG_FENCE_BODY}\n~~~\n"
        blocks = extract_structured_blocks(text)
        assert len(blocks) == 1

    def test_mismatched_fence_markers_do_not_close_each_other(self) -> None:
        # A ~~~ line cannot close a ``` fence -- the block runs to EOF and is
        # therefore unclosed and skipped, never mis-paired with the wrong marker.
        text = f"```bash\n{_LONG_FENCE_BODY}\n~~~\n```\n"
        blocks = extract_structured_blocks(text)
        assert len(blocks) == 1


class TestMarkdownTables:
    def test_extracts_a_contiguous_pipe_table(self) -> None:
        text = f"Prose.\n\n{_LONG_TABLE}\n\nMore prose.\n"
        blocks = extract_structured_blocks(text)
        assert len(blocks) == 1
        assert "Column One" in blocks[0]

    def test_a_single_pipe_line_is_not_a_table(self) -> None:
        text = "Prose with a | pipe | in it but not a real table.\n"
        assert extract_structured_blocks(text) == []

    def test_a_single_pipe_delimited_row_is_below_the_minimum_row_count(self) -> None:
        # Matches the pipe-row shape but is only one row -- below
        # _MIN_TABLE_ROWS, so no real table syntax (no delimiter row).
        text = "| just one lonely row |\n"
        assert extract_structured_blocks(text) == []


class TestEnumeratedListRuns:
    def test_extracts_a_run_of_three_or_more_ordered_items(self) -> None:
        blocks = extract_structured_blocks(_LONG_LIST)
        assert len(blocks) == 1
        assert "first sufficiently long" in blocks[0]

    def test_two_item_run_is_below_the_minimum_and_not_returned(self) -> None:
        text = "\n".join(_LONG_LIST.splitlines()[:2])
        assert extract_structured_blocks(text) == []

    def test_unordered_list_runs_are_recognised(self) -> None:
        text = "\n".join(
            [
                "- This is the first sufficiently long bullet item here today.",
                "- This is the second sufficiently long bullet item here today.",
                "- This is the third sufficiently long bullet item here today.",
            ]
        )
        blocks = extract_structured_blocks(text)
        assert len(blocks) == 1

    def test_min_list_items_constant_matches_the_documented_floor(self) -> None:
        assert MIN_LIST_ITEMS == 3


class TestSsotQuoteExclusion:
    def test_a_fence_inside_an_ssot_quote_body_is_excluded(self) -> None:
        text = (
            "<!-- ssot-quote: CLAUDE/Source.md#anchor -->\n"
            f"{_fence(_LONG_FENCE_BODY)}\n"
            "<!-- /ssot-quote -->\n"
        )
        assert extract_structured_blocks(text) == []

    def test_a_structured_block_outside_the_quote_span_is_still_found(self) -> None:
        text = (
            "<!-- ssot-quote: CLAUDE/Source.md#anchor -->\n"
            f"{_fence(_LONG_FENCE_BODY)}\n"
            "<!-- /ssot-quote -->\n\n"
            f"{_LONG_TABLE}\n"
        )
        blocks = extract_structured_blocks(text)
        assert len(blocks) == 1
        assert "Column One" in blocks[0]


class TestHashing:
    def test_identical_blocks_hash_identically(self) -> None:
        text_a = f"Doc A.\n\n{_fence(_LONG_FENCE_BODY)}\n"
        text_b = f"Doc B, totally different prose.\n\n{_fence(_LONG_FENCE_BODY)}\n"
        assert extract_structured_block_hashes(text_a) == extract_structured_block_hashes(text_b)

    def test_different_blocks_hash_differently(self) -> None:
        text_a = f"{_fence(_LONG_FENCE_BODY)}\n"
        text_b = f"{_fence(_LONG_FENCE_BODY + chr(10) + 'echo one more distinct line here')}\n"
        assert extract_structured_block_hashes(text_a) != extract_structured_block_hashes(text_b)

    def test_no_structured_blocks_yields_empty_tuple(self) -> None:
        assert extract_structured_block_hashes("Just plain prose, nothing structured here.\n") == ()

    def test_hashes_are_returned_in_document_order(self) -> None:
        text = f"{_fence(_LONG_FENCE_BODY)}\n\n{_LONG_TABLE}\n"
        hashes = extract_structured_block_hashes(text)
        assert len(hashes) == 2

    def test_normalisation_equates_trivial_formatting_differences(self) -> None:
        # Two orderings of table cell whitespace that mdformat-gfm normalises
        # to the same rendering must hash identically.
        loose = "\n".join(
            [
                "| Column One | Column Two | Column Three |",
                "|---|---|---|",
                "| aaaaaaaaaa | bbbbbbbbbb | cccccccccccc |",
                "| dddddddddd | eeeeeeeeee | ffffffffffff |",
                "| gggggggggg | hhhhhhhhhh | iiiiiiiiiiii |",
            ]
        )
        assert extract_structured_block_hashes(loose) == extract_structured_block_hashes(
            _LONG_TABLE
        )


class TestMinBlockLengthConstant:
    def test_documented_floor_excludes_the_known_noisy_two_line_fence(self) -> None:
        noisy = "./bin/hooks-daemon restart\n./bin/hooks-daemon status"
        assert len(noisy) < MIN_BLOCK_LENGTH_CHARS


class TestExtractStructuredBlockLocations:
    """Task 3.3 T1: duplicate-block findings must be able to cite
    ``path:start-end`` for both sides -- these tests pin the 1-indexed,
    inclusive line span each :class:`BlockLocation` carries."""

    def test_fenced_block_span_is_1_indexed_and_inclusive(self) -> None:
        text = f"Some prose.\n\n{_fence(_LONG_FENCE_BODY)}\n\nMore prose.\n"
        locations = extract_structured_block_locations(text)
        assert len(locations) == 1
        # Line 1: "Some prose.", line 2: blank, line 3: fence open.
        fence_line_count = _fence(_LONG_FENCE_BODY).count("\n") + 1
        assert locations[0].start_line == 3
        assert locations[0].end_line == 3 + fence_line_count - 1

    def test_table_span_covers_exactly_the_table_rows(self) -> None:
        text = f"Prose.\n\n{_LONG_TABLE}\n\nMore prose.\n"
        locations = extract_structured_block_locations(text)
        assert len(locations) == 1
        table_row_count = len(_LONG_TABLE.splitlines())
        assert locations[0].start_line == 3
        assert locations[0].end_line == 3 + table_row_count - 1

    def test_list_span_covers_exactly_the_list_items(self) -> None:
        locations = extract_structured_block_locations(_LONG_LIST)
        assert len(locations) == 1
        assert locations[0].start_line == 1
        assert locations[0].end_line == len(_LONG_LIST.splitlines())

    def test_two_blocks_report_independent_spans_in_document_order(self) -> None:
        text = f"{_fence(_LONG_FENCE_BODY)}\n\n{_LONG_TABLE}\n"
        locations = extract_structured_block_locations(text)
        assert len(locations) == 2
        assert locations[0].start_line == 1
        assert locations[1].start_line > locations[0].end_line

    def test_hash_matches_extract_structured_block_hashes(self) -> None:
        text = f"{_fence(_LONG_FENCE_BODY)}\n\n{_LONG_TABLE}\n"
        locations = extract_structured_block_locations(text)
        assert tuple(loc.block_hash for loc in locations) == extract_structured_block_hashes(text)

    def test_no_structured_blocks_yields_empty_tuple(self) -> None:
        assert extract_structured_block_locations("Just plain prose, nothing here.\n") == ()

    def test_below_floor_block_is_never_located(self) -> None:
        text = f"Restart the daemon:\n\n{_fence('./bin/hooks-daemon restart')}\n"
        assert extract_structured_block_locations(text) == ()

    def test_location_is_a_frozen_dataclass_with_named_fields(self) -> None:
        location = BlockLocation(block_hash="abc", start_line=1, end_line=2)
        assert location.block_hash == "abc"
        assert location.start_line == 1
        assert location.end_line == 2

    def test_ssot_quote_body_stripping_does_not_shift_later_block_line_numbers(self) -> None:
        """A quote body used to be REMOVED entirely, shifting every line
        after it -- the blank-out fix keeps line numbers stable."""
        text = (
            "Prose line 1.\n"
            "<!-- ssot-quote: CLAUDE/Source.md#anchor -->\n"
            "quoted body line\n"
            "<!-- /ssot-quote -->\n"
            "\n"
            f"{_LONG_TABLE}\n"
        )
        locations = extract_structured_block_locations(text)
        assert len(locations) == 1
        # The table starts at line 6 in the ORIGINAL text, regardless of the
        # 4-line quote span stripped ahead of it.
        assert locations[0].start_line == 6
