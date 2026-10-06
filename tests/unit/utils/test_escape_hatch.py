"""Tests for the shared MUST_*_BECAUSE escape-hatch reason check (Plan 00484 G2)."""

from __future__ import annotations

import pytest

from claude_code_hooks_daemon.utils.escape_hatch import (
    in_command_hatch_pattern,
    is_acceptable_reason,
)


class TestIsAcceptableReason:
    """A reason must carry content: not empty, not a bare comment closer, not a placeholder."""

    @pytest.mark.parametrize(
        "reason",
        ["", "   ", "-->", " --> ", "*/", "*/ ", '""', "'", "...", "!!"],
    )
    def test_empty_or_closer_only_is_rejected(self, reason: str) -> None:
        assert is_acceptable_reason(reason) is False

    @pytest.mark.parametrize(
        "reason",
        [
            "because",
            "Because.",
            "needed",
            "n/a",
            "N/A",
            "none",
            "reason",
            "explain why",
            "<reason>",
            "tbd",
            "todo",
            "required --> ",
            "needed */",
        ],
    )
    def test_generic_placeholder_is_rejected(self, reason: str) -> None:
        assert is_acceptable_reason(reason) is False

    @pytest.mark.parametrize(
        "reason",
        [
            "verbatim upstream licence text",
            "need to test stash recovery flow",
            "platform mandates squash-only merging",
            "diagnostic sweep -->",
            "generated table */",
        ],
    )
    def test_specific_reason_is_accepted(self, reason: str) -> None:
        assert is_acceptable_reason(reason) is True


class TestInCommandHatchPattern:
    """The compiled pattern captures the quoted reason of one named hatch."""

    def test_captures_double_quoted_reason(self) -> None:
        match = in_command_hatch_pattern("MUST_STASH_BECAUSE").search(
            'MUST_STASH_BECAUSE="a real reason"; git stash'
        )
        assert match is not None
        assert match.group(1) == "a real reason"

    def test_empty_quotes_do_not_match(self) -> None:
        assert (
            in_command_hatch_pattern("MUST_STASH_BECAUSE").search("MUST_STASH_BECAUSE=''") is None
        )
