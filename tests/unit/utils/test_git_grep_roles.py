"""N390: one reader places the words of a ``git grep``.

``secret_file_matching`` (which words are patterns) and ``command_position``
(which words are data to blank) used to each walk the options of ``git grep``.
Both now read ``git_grep_word_roles``; these tests pin the reader and the
parity of the two consumers over the option shapes.
"""

from __future__ import annotations

import pytest

from claude_code_hooks_daemon.utils.command_evasion import (
    GitGrepRole,
    git_grep_word_roles,
    git_subcommand_index,
)
from claude_code_hooks_daemon.utils.command_position import (
    _GIT_RUNNABLE_MARKERS,
    _GIT_TEXT_OPTION_PREFIXES,
    _GIT_TEXT_OPTIONS,
    _READ_ONLY_GIT_SUBCOMMANDS,
    _blank_literal,
    blank_quoted_text_arguments,
)
from claude_code_hooks_daemon.utils.secret_file_matching import _git_grep_pattern_spans
from claude_code_hooks_daemon.utils.shell_segmentation import shell_word_spans

#: The option shapes of ``git grep`` that move the pattern operand.
SHAPES: tuple[str, ...] = (
    "git grep 'a b'",
    "git grep 'a b' src",
    "git grep -n 'a b' src",
    "git grep -e 'a b' src",
    "git grep -e 'a b' -e 'c d' src",
    "git grep -e'a b' src",
    "git grep --regexp 'a b' src",
    "git grep --regexp='a b' src",
    "git grep -f patterns.txt 'a b'",
    "git grep -A 3 'a b' src",
    "git grep -m 5 -C 2 'a b'",
    "git grep 'a b' 'c d'",
    "git grep 'a b' -- 'c d'",
    "git grep -- 'a b'",
    "git grep 'a b' HEAD -- src",
    "git grep 'a b' -e 'c d'",
    "git -C /tmp grep -e 'a b'",
    "git --no-pager grep -n 'a b'",
    "git grep -e",
    "git grep",
    "git log --grep 'a b'",
)


def _words(command: str) -> tuple[list[str], int | None]:
    words = [command[start:end] for start, end in shell_word_spans(command)]
    git_at = next(i for i, word in enumerate(words) if word == "git")
    return words, git_subcommand_index(words, git_at)


class TestGitGrepWordRoles:
    def test_the_first_positional_is_the_pattern(self) -> None:
        words, sub = _words("git grep -n 'a b' src")
        assert sub is not None
        roles = git_grep_word_roles(words, sub)
        assert roles[2] is GitGrepRole.OPTION
        assert roles[3] is GitGrepRole.PATTERN
        assert roles[4] is GitGrepRole.OPERAND

    def test_a_dash_e_value_is_the_pattern_and_the_positional_is_not(self) -> None:
        words, sub = _words("git grep -e 'a b' src")
        assert sub is not None
        roles = git_grep_word_roles(words, sub)
        assert roles[3] is GitGrepRole.PATTERN
        assert roles[4] is GitGrepRole.OPERAND

    def test_an_attached_pattern_is_its_own_role(self) -> None:
        for command in ("git grep -e'a b'", "git grep --regexp='a b'"):
            words, sub = _words(command)
            assert sub is not None
            assert git_grep_word_roles(words, sub)[2] is GitGrepRole.PATTERN_ATTACHED

    def test_the_value_of_another_option_is_an_operand(self) -> None:
        words, sub = _words("git grep -f patterns.txt 'a b'")
        assert sub is not None
        roles = git_grep_word_roles(words, sub)
        assert roles[3] is GitGrepRole.OPERAND
        assert roles[4] is GitGrepRole.PATTERN

    def test_everything_after_double_dash_is_an_operand(self) -> None:
        words, sub = _words("git grep -- 'a b'")
        assert sub is not None
        assert git_grep_word_roles(words, sub)[3] is GitGrepRole.OPERAND

    def test_no_pattern_is_found_after_the_first_operand_that_follows_one(self) -> None:
        words, sub = _words("git grep 'a b' src -e 'c d'")
        assert sub is not None
        roles = git_grep_word_roles(words, sub)
        assert roles[2] is GitGrepRole.PATTERN
        assert roles[3] is GitGrepRole.OPERAND
        assert roles[4] is GitGrepRole.OPTION
        assert roles[5] is GitGrepRole.OPERAND


class TestTheTwoConsumersAgree:
    @pytest.mark.parametrize("command", SHAPES)
    def test_the_secret_matcher_spans_are_the_pattern_roles(self, command: str) -> None:
        spans = shell_word_spans(command)
        words, sub = _words(command)
        expected: list[tuple[int, int]] = []
        if sub is not None and words[sub] == "grep":
            roles = git_grep_word_roles(words, sub)
            expected = [
                spans[index]
                for index, role in sorted(roles.items())
                if role in (GitGrepRole.PATTERN, GitGrepRole.PATTERN_ATTACHED)
                and index < len(words)
                and ("'" in words[index] or '"' in words[index])
            ]
        assert _git_grep_pattern_spans(command) == expected

    @pytest.mark.parametrize("command", SHAPES)
    def test_command_position_output_is_unchanged_from_the_per_word_rule(
        self, command: str
    ) -> None:
        """The rule before N390: a `git grep` word is data unless it starts with a dash."""
        words, sub = _words(command)
        expected = list(words)
        if sub is not None and words[sub] in _READ_ONLY_GIT_SUBCOMMANDS:
            for index in range(sub + 1, len(words)):
                word = words[index]
                after_option = words[index - 1] in _GIT_TEXT_OPTIONS and index - 1 > sub
                if after_option or (words[sub] == "grep" and not word.startswith("-")):
                    expected[index] = _blank_literal(word, _GIT_RUNNABLE_MARKERS, True)
                elif word.startswith(_GIT_TEXT_OPTION_PREFIXES):
                    expected[index] = _blank_literal(word, _GIT_RUNNABLE_MARKERS, False)
        blanked = blank_quoted_text_arguments(command)
        assert [blanked[s:e] for s, e in shell_word_spans(blanked)] == expected

    @pytest.mark.parametrize("command", SHAPES)
    def test_command_position_blanks_exactly_the_non_option_words(self, command: str) -> None:
        spans = shell_word_spans(command)
        words, sub = _words(command)
        blanked = blank_quoted_text_arguments(command)
        blanked_words = [blanked[s:e] for s, e in shell_word_spans(blanked)]
        assert len(blanked_words) == len(words)
        if sub is None or words[sub] != "grep":
            return
        roles = git_grep_word_roles(words, sub)
        for index, word in enumerate(words):
            if index <= sub:
                continue
            changed = blanked_words[index] != word
            if changed:
                assert roles[index] is not GitGrepRole.OPTION, (command, word)
        assert spans  # the command had words to compare
