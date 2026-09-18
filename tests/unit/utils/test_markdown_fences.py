"""Tests for the shared fenced-code-block splitter.

Plan 00439. The splitter was written for ``plan_qa.model`` and then acquired
callers in ``docs_qa`` and ``utils``; it moved to ``utils`` so the dependency
between the two QA packages runs the way both of them claim it does. It had no
direct tests at any point in that history — every caller exercised it
incidentally — so they are written here as part of the move.
"""

from claude_code_hooks_daemon.utils.markdown_fences import lines_outside_fences


class TestLinesOutsideFences:
    def test_prose_with_no_fence_is_returned_line_for_line(self) -> None:
        assert lines_outside_fences("one\ntwo\n") == ["one", "two"]

    def test_a_backtick_fence_and_its_delimiters_are_dropped(self) -> None:
        text = "before\n```\ninside\n```\nafter\n"
        assert lines_outside_fences(text) == ["before", "after"]

    def test_a_tilde_fence_is_dropped_too(self) -> None:
        text = "before\n~~~\ninside\n~~~\nafter\n"
        assert lines_outside_fences(text) == ["before", "after"]

    def test_a_backtick_run_inside_a_tilde_fence_does_not_close_it(self) -> None:
        """The closing delimiter has to match the marker that opened the block.

        A tilde fence holding a backtick-fenced example is the shape markdown
        uses to show fenced code, so mismatched markers must not close.
        """
        text = "before\n~~~\n```\nstill inside\n```\n~~~\nafter\n"
        assert lines_outside_fences(text) == ["before", "after"]

    def test_an_unclosed_fence_swallows_the_rest_of_the_document(self) -> None:
        text = "before\n```\ninside\nstill inside\n"
        assert lines_outside_fences(text) == ["before"]

    def test_an_indented_fence_still_opens_a_block(self) -> None:
        text = "before\n  ```\ninside\n  ```\nafter\n"
        assert lines_outside_fences(text) == ["before", "after"]

    def test_a_blank_line_outside_a_fence_is_kept(self) -> None:
        assert lines_outside_fences("one\n\ntwo\n") == ["one", "", "two"]

    def test_two_separate_fences_are_both_dropped(self) -> None:
        text = "a\n```\nx\n```\nb\n```\ny\n```\nc\n"
        assert lines_outside_fences(text) == ["a", "b", "c"]

    def test_an_empty_document_yields_nothing(self) -> None:
        assert lines_outside_fences("") == []
