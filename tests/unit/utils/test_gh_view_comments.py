"""Direct tests for the shared gh view comment reader (ledger N408)."""

from __future__ import annotations

import pytest

from claude_code_hooks_daemon.utils.gh_view_comments import (
    suggest_with_comments,
    uncommented_view_segment,
)


class TestUncommentedViewSegment:
    def test_plain_view_is_returned(self) -> None:
        assert uncommented_view_segment("gh pr view 5", "pr") == "gh pr view 5"

    def test_other_noun_is_not_a_view_of_this_noun(self) -> None:
        assert uncommented_view_segment("gh issue view 5", "pr") is None

    @pytest.mark.parametrize(
        "command",
        [
            "gh pr view 5 --comments",
            "gh pr view 5 --json comments",
            "gh pr view 5 --json=title,comments",
            "gh pr view 5 --jq '.a | .b' --json=comments",
        ],
    )
    def test_commented_view_is_none(self, command: str) -> None:
        assert uncommented_view_segment(command, "pr") is None

    def test_json_flag_without_value_does_not_count(self) -> None:
        assert uncommented_view_segment("gh pr view 5 --json", "pr") == "gh pr view 5 --json"

    def test_unreadable_word_is_skipped_not_trusted(self) -> None:
        view = uncommented_view_segment("gh pr view 5 $(printf x)", "pr")
        assert view is not None

    def test_comments_substring_in_other_field_does_not_count(self) -> None:
        assert uncommented_view_segment("gh pr view 5 --json commentsX", "pr") is not None


class TestSuggestWithComments:
    def test_appends_flag(self) -> None:
        assert suggest_with_comments("gh pr view 5", "gh pr view 5") == "gh pr view 5 --comments"

    def test_keeps_gap_before_chained_command(self) -> None:
        command = "gh pr view 5 && echo done"
        assert (
            suggest_with_comments(command, "gh pr view 5 ")
            == "gh pr view 5 --comments && echo done"
        )

    def test_extends_json_field_list(self) -> None:
        assert (
            suggest_with_comments("gh pr view 5 --json title", "gh pr view 5 --json title")
            == "gh pr view 5 --json title,comments"
        )

    def test_extends_json_equals_field_list(self) -> None:
        assert (
            suggest_with_comments("gh pr view 5 --json=title", "gh pr view 5 --json=title")
            == "gh pr view 5 --json=title,comments"
        )

    def test_json_flag_without_value_gets_comments_flag(self) -> None:
        assert (
            suggest_with_comments("gh pr view 5 --json", "gh pr view 5 --json")
            == "gh pr view 5 --json --comments"
        )

    def test_view_not_in_command_is_fixed_on_its_own(self) -> None:
        assert suggest_with_comments("bash -c 'x'", "gh pr view 5") == "gh pr view 5 --comments"
