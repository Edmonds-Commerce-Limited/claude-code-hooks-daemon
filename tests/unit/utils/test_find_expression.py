"""Tests for the leaf reader of a ``find`` expression (ledger 00474 N124)."""

from __future__ import annotations

import pytest

from claude_code_hooks_daemon.utils import find_expression as fe


class TestFindRegexOperandIndexes:
    @pytest.mark.parametrize(
        ("words", "expected"),
        [
            (["find", ".", "-regex", ".*x"], [3]),
            (["find", ".", "-iregex", ".*x"], [3]),
            (["/usr/bin/find", ".", "-regex", "a", "-o", "-iregex", "b"], [3, 6]),
            (["find", ".", "-name", "*.py"], []),
            (["find", ".", "-path", "*/x/*", "-wholename", "*y"], []),
            (["find", ".", "-regex"], []),
            (["find", ".", "-regex", ".*x", "-fprint", "names"], [3]),
            (["grep", "-regex", "x"], []),
            ([], []),
        ],
    )
    def test_the_word_after_each_regex_test(self, words: list[str], expected: list[int]) -> None:
        assert fe.find_regex_operand_indexes(words) == expected

    @pytest.mark.parametrize("action", [*sorted(fe.FIND_EXEC_ACTIONS), fe.FIND_DELETE_ACTION])
    def test_a_find_that_acts_on_its_matches_has_none(self, action: str) -> None:
        words = ["find", ".", "-regex", ".*x", action, "cat", "{}", ";"]

        assert fe.find_regex_operand_indexes(words) == []


class TestFindExecEnd:
    def test_the_first_terminator_from_start(self) -> None:
        words = ["cat", "{}", ";", "-print", "+"]

        assert fe.find_exec_end(words, 0) == 2

    def test_none_when_the_command_runs_to_the_end(self) -> None:
        assert fe.find_exec_end(["cat", "{}"], 0) is None

    def test_a_custom_terminator_set(self) -> None:
        assert fe.find_exec_end(["cat", "\\;"], 0, frozenset({"\\;"})) == 1
