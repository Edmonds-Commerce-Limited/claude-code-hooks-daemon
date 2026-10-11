"""A guard matching one command's own words reads past neither a comment nor a mention."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from claude_code_hooks_daemon.utils.command_position import (
    command_position_code_segments,
    command_position_code_segments_with_separators,
    without_comment,
)

_CORPUS = Path(__file__).resolve().parents[2] / "fixtures" / "ordinary_command_corpus.yaml"


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
        segments = command_position_code_segments("true # note; x\nsudo pip install x")
        assert not any("note" in s for s in segments)
        assert any("sudo pip install x" in s for s in segments)

    def test_mention_in_echo_is_blanked(self) -> None:
        segments = command_position_code_segments("echo 'sudo pip install x'")
        assert not any("sudo" in s for s in segments)


class TestCommandPositionCodeSegmentsWithSeparators:
    @pytest.mark.parametrize(
        ("command", "expected"),
        [
            ("a; b && c", [("", "a"), (";", "b"), ("&&", "c")]),
            ("a | b || c", [("", "a"), ("|", "b"), ("||", "c")]),
            ("a |& b", [("", "a"), ("|&", "b")]),
            ("a # note", [("", "a")]),
        ],
    )
    def test_pairs_each_segment_with_the_operator_before_it(
        self, command: str, expected: list[tuple[str, str]]
    ) -> None:
        got = command_position_code_segments_with_separators(command)
        assert [(sep, seg.strip()) for sep, seg in got] == expected

    @pytest.mark.parametrize(
        ("command", "expected"),
        [
            ("a\nb", [("", "a"), ("\n", "b")]),
            ("a & b", [("", "a"), ("&", "b")]),
            ("a ;; b", [("", "a"), (";;", "b")]),
            ("a 2>&1 | b", [("", "a 2>&1"), ("|", "b")]),
        ],
    )
    def test_keeps_newline_background_double_semicolon_and_redirect_pipe(
        self, command: str, expected: list[tuple[str, str]]
    ) -> None:
        got = command_position_code_segments_with_separators(command)
        assert [(sep, seg.strip()) for sep, seg in got] == expected

    def test_segments_match_the_plain_accessor_over_the_whole_corpus(self) -> None:
        corpus = yaml.safe_load(_CORPUS.read_text(encoding="utf-8"))["rows"]
        assert corpus
        for row in corpus:
            command = row["command"]
            plain = [s for s in command_position_code_segments(command) if s.strip()]
            paired = [s for _, s in command_position_code_segments_with_separators(command)]
            assert paired == plain, command
