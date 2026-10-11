"""A guard matching one command's own words reads past neither a comment nor a mention."""

from __future__ import annotations

import pytest

from claude_code_hooks_daemon.utils.command_position import (
    command_position_code_segments,
    without_comment,
)


class TestWithoutComment:
    @pytest.mark.parametrize(
        ("segment", "expected"),
        [
            ("true # sudo pip install x", "true "),
            ("# whole line", ""),
            ("echo a#b", "echo a#b"),
            ("echo '# not a comment'", "echo '# not a comment'"),
            ("ls -la", "ls -la"),
        ],
    )
    def test_cuts_only_a_word_that_starts_a_comment(self, segment: str, expected: str) -> None:
        assert without_comment(segment) == expected


class TestCommandPositionCodeSegments:
    def test_comment_text_is_not_a_command_but_a_later_command_is(self) -> None:
        segments = command_position_code_segments("true # note; sudo pip install x")
        assert not any("note" in s for s in segments)
        assert any("sudo pip install x" in s for s in segments)

    def test_mention_in_echo_is_blanked(self) -> None:
        segments = command_position_code_segments("echo 'sudo pip install x'")
        assert not any("sudo" in s for s in segments)
