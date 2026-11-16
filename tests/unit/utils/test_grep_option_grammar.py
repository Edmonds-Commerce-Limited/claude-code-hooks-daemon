"""Tests for the grep-family option grammar (Plan 00618 older holes, Unit 1).

The grammar says, per tool, which options take a value, which supply the
pattern and which the tool does not know. Anything it cannot prove is reported
as ``uncertain`` so a caller judges every operand rather than skipping one.
"""

import pytest

from claude_code_hooks_daemon.utils.grep_option_grammar import (
    Arity,
    ParsedArguments,
    grammar_for,
    parse_arguments,
)


def _parse(command: str, *arguments: str, git: bool = False) -> ParsedArguments:
    return parse_arguments(grammar_for(command, git_grep=git), list(arguments))


class TestOperandsPerTool:
    """Which argument positions are operands (the pattern included)."""

    @pytest.mark.parametrize(
        ("command", "arguments", "operands"),
        [
            ("grep", ["-r", "zz", "sub"], [1, 2]),
            ("grep", ["-rn", "zz", "sub"], [1, 2]),
            ("grep", ["-r", "--line-number", "zz", "sub"], [2, 3]),
            ("grep", ["-r", "--line-n", "zz", "sub"], [2, 3]),
            # -T and a separate --color word take no value in GNU grep or ugrep.
            ("grep", ["-rT", "x", "deep", "sub"], [1, 2, 3]),
            ("grep", ["-r", "--color", "x", "deep", "sub"], [2, 3, 4]),
            ("grep", ["-5", "x", "d"], [1, 2]),
            ("grep", ["-A", "2", "x", "d"], [2, 3]),
            ("grep", ["-A2", "x", "d"], [1, 2]),
            ("ugrep", ["-K", "5", "x", "d"], [2, 3]),
            ("ugrep", ["-m", "3", "x", "d"], [2, 3]),
            ("ugrep", ["-j", "x", "d"], [1, 2]),
            ("rg", ["--color", "never", "x", "sub"], [2, 3]),
            ("rg", ["-n", "zz", "sub"], [1, 2]),
            ("rg", ["-r", "REPL", "x", "sub"], [2, 3]),
            ("rg", ["-g", "*.py", "x", "sub"], [2, 3]),
            ("/usr/bin/rg", ["-g", "*.py", "x", "sub"], [2, 3]),
            ("grep", ["--", "-e", "x"], [1, 2]),
            ("grep", ["-r", "x", "--", "-d"], [1, 3]),
            ("git", ["-n", "x", "--", "p"], [1, 3]),
            ("git", ["-5", "x"], [1]),
        ],
    )
    def test_operand_positions(
        self, command: str, arguments: list[str], operands: list[int]
    ) -> None:
        parsed = _parse(command, *arguments, git=command == "git")
        assert parsed.operands == operands
        assert not parsed.uncertain
        assert not parsed.pattern_supplied


class TestPatternSupplyingOptions:
    """A pattern given by option leaves no pattern operand to skip."""

    @pytest.mark.parametrize(
        ("command", "arguments"),
        [
            ("grep", ["-e", "zz", "d"]),
            ("grep", ["-ezz", "d"]),
            ("grep", ["-iezz", "d"]),
            ("grep", ["-fzz", "d"]),
            ("grep", ["-f", "pats", "d"]),
            ("grep", ["--regexp=zz", "d"]),
            ("grep", ["--regexp", "zz", "d"]),
            ("grep", ["--regex=zz", "d"]),
            ("grep", ["--reg=zz", "d"]),
            ("egrep", ["--rege=zz", "d"]),
            ("grep", ["--file=p", "d"]),
            ("grep", ["--fil=p", "d"]),
            ("grep", ["--and=zz", "d"]),
            ("ugrep", ["--and", "zz", "d"]),
            ("ugrep", ["--not=zz", "d"]),
            ("ugrep", ["-N", "zz", "d"]),
            ("rg", ["-ezz", "d"]),
            ("rg", ["--regexp=zz", "d"]),
            ("rg", ["--files", "d"]),
            ("git", ["-e", "zz"]),
        ],
    )
    def test_pattern_is_supplied(self, command: str, arguments: list[str]) -> None:
        parsed = _parse(command, *arguments, git=command == "git")
        assert parsed.pattern_supplied
        assert not parsed.uncertain


class TestUncertainty:
    """Positive proof only: what the grammar cannot place makes the parse uncertain."""

    def test_ambiguous_abbreviation_is_uncertain_and_may_recurse(self) -> None:
        parsed = _parse("grep", "--fi=pats", "deep", "/dev/null")
        assert parsed.uncertain
        assert parsed.recursive
        assert parsed.operands == [1, 2]

    def test_unknown_long_option_without_value_may_consume_a_word(self) -> None:
        parsed = _parse("grep", "--no-such-option", "x", "sub")
        assert parsed.uncertain
        assert parsed.maybe_consumed == 1

    def test_unknown_long_option_with_value_consumes_nothing(self) -> None:
        parsed = _parse("grep", "--no-such-option=1", "x", "sub")
        assert parsed.uncertain
        assert parsed.maybe_consumed == 0

    def test_unknown_short_letter_last_in_cluster_may_consume_a_word(self) -> None:
        parsed = _parse("grep", "-r_", "x", "sub")
        assert parsed.uncertain
        assert parsed.recursive
        assert parsed.maybe_consumed == 1

    def test_unknown_short_letter_does_not_hide_a_later_recursion_flag(self) -> None:
        parsed = _parse("grep", "-_r", "x", "sub")
        assert parsed.uncertain
        assert parsed.recursive

    def test_ug_is_always_uncertain_because_it_reads_a_config(self) -> None:
        parsed = _parse("ug", "-n", "x", "sub")
        assert parsed.uncertain
        assert parsed.recursive

    def test_ag_and_ack_do_not_share_context_option_arity(self) -> None:
        for command in ("ag", "ack"):
            assert _parse(command, "-A", "5", "x").uncertain

    def test_optional_value_cluster_letters_are_not_trusted(self) -> None:
        # ugrep reads the rest of ``-Zfoo`` as -Z's value; GNU grep as flags.
        assert _parse("grep", "-Zr", "x", "sub").uncertain


class TestRecursion:
    @pytest.mark.parametrize(
        "arguments",
        [
            ["-r", "x"],
            ["-R", "x"],
            ["-rn", "x"],
            ["--recursive", "x"],
            ["--recurs", "x"],
            ["--dereference-recursive", "x"],
        ],
    )
    def test_grep_recursion_spellings(self, arguments: list[str]) -> None:
        assert _parse("grep", *arguments).recursive

    def test_plain_grep_is_not_recursive(self) -> None:
        assert not _parse("grep", "-n", "x", "sub").recursive

    def test_rg_dash_r_is_a_value_option_not_recursion(self) -> None:
        assert not _parse("rg", "-r", "X", "x").recursive

    def test_directories_recurse_is_recorded_as_a_value(self) -> None:
        parsed = _parse("grep", "-d", "recurse", "x")
        assert ("-d", "recurse") in parsed.values


class TestValues:
    def test_long_value_is_recorded_under_its_full_name(self) -> None:
        parsed = _parse("grep", "-r", "--exclude-d=sub", "x", ".")
        assert ("--exclude-dir", "sub") in parsed.values

    def test_separate_and_attached_values(self) -> None:
        parsed = _parse("rg", "-g", "*.py", "--glob=*.md", "x")
        assert ("-g", "*.py") in parsed.values
        assert ("--glob", "*.md") in parsed.values


class TestArity:
    def test_enum_members(self) -> None:
        assert {member.name for member in Arity} == {"FLAG", "VALUE", "OPTIONAL", "UNKNOWN"}

    @pytest.mark.parametrize(
        ("command", "letter", "arity"),
        [
            ("grep", "T", Arity.FLAG),
            ("grep", "A", Arity.VALUE),
            ("grep", "Z", Arity.OPTIONAL),
            ("ugrep", "K", Arity.VALUE),
            ("ugrep", "m", Arity.VALUE),
            ("rg", "r", Arity.VALUE),
            ("rg", "n", Arity.FLAG),
            ("grep", "_", Arity.UNKNOWN),
        ],
    )
    def test_short_arity(self, command: str, letter: str, arity: Arity) -> None:
        assert grammar_for(command).short(letter) is arity
