"""Fixture for the ``stdlib-shlex-quadratic`` semgrep rule (Plan 00483 N197).

DELIBERATELY DEFECTIVE CODE. Nothing here is imported or executed. Each hit is
a spelling of the stdlib tokeniser, which is O(n^2) in the length of one word.

Markers drive the assertions in
``tests/unit/qa/test_semgrep_stdlib_shlex_quadratic.py``:

* ``# EXPECT-HIT``   — the rule MUST report this line
* ``# EXPECT-CLEAN`` — the rule MUST NOT report this line
"""

import shlex

from claude_code_hooks_daemon.utils.linear_shlex import LinearShlex, split


def stdlib_split(command: str) -> list[str]:
    return shlex.split(command)  # EXPECT-HIT


def stdlib_split_without_comments(command: str) -> list[str]:
    return shlex.split(command, comments=False)  # EXPECT-HIT


def stdlib_lexer(command: str) -> list[str]:
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)  # EXPECT-HIT
    return list(lexer)


def stdlib_split_in_comprehension(stages: list[str]) -> list[list[str]]:
    return [shlex.split(stage) for stage in stages]  # EXPECT-HIT


def linear_split(command: str) -> list[str]:
    return split(command)  # EXPECT-CLEAN


def linear_lexer(command: str) -> list[str]:
    lexer = LinearShlex(command, posix=True, punctuation_chars=True)  # EXPECT-CLEAN
    return list(lexer)


def quote_is_linear(word: str) -> str:
    return shlex.quote(word)  # EXPECT-CLEAN


def join_is_linear(words: list[str]) -> str:
    return shlex.join(words)  # EXPECT-CLEAN
