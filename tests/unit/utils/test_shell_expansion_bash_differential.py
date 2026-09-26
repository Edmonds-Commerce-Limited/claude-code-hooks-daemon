"""The guard's spellings of a shell word, checked against bash's own
(Plan 00466 N101 round 7, N107, N111).

Each generated word is built from quoting and brace primitives around
harmless names, and bash prints its expansion with ``printf '%s\\n' WORD``
under ``set -f`` in an empty temporary directory: the words hold no
substitution or parameter, so nothing runs and nothing is read. Every
spelling bash prints must be one the guard reads. A word the guard gives up
on (:class:`TooManyToEnumerateError`) is failed closed by the guard, so it
is not compared.
"""

from __future__ import annotations

import random
import shutil
import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.utils.shell_expansion import (
    TooManyToEnumerateError,
    expand_braces,
    iter_shell_brace_words,
    normalise_word,
    python_program_streams,
    shell_word_spellings,
)

#: Quoting and brace primitives. None holds whitespace, a substitution or a
#: parameter, and every quote is closed within its own primitive.
_PRIMITIVES = (
    "{",
    "}",
    ",",
    ".qq-",
    "pass",
    "q",
    "1..2",
    "'}'",
    "'{'",
    "','",
    '"}"',
    '"{"',
    '","',
    "\\}",
    "\\{",
    "\\,",
    "$'\\x7b'",
    "$'\\x7d'",
    "$'\\x2c'",
    "$'\\173'",
    '$"a"',
    '$"}"',
    '$","',
    "$'a'",
    '"a"',
    "'b'",
)

#: Brace primitives with no quoting character (Plan 00466 N115): bash's
#: grouping of such a word differs from the quote-blind reading too.
_QUOTE_FREE_PRIMITIVES = ("{", "}", "{}", ",", "..", ".qq-", "pass", "q", "1..2", "a")

#: Python escapes that change a literal's braces or commas, for words read
#: inside a program.
_PYTHON_ESCAPES = ("\\x7b", "\\x7d", "\\173", "\\175", "\\x2c", "\\u007b")

#: Separates one word's output from the next.
_MARKER = "@@end@@"


def _generated_words(seed: int, count: int, primitives: tuple[str, ...]) -> list[str]:
    """Half free-form runs of primitives; a quarter a group
    ``PRE{ALT,ALT}POST`` whose parts are runs of primitives, so most words
    hold a group bash expands; and a quarter the same group with a ``}``
    or ``{}`` leading its first alternative, which bash reads as text."""
    rng = random.Random(seed)

    def run(low: int, high: int) -> str:
        return "".join(rng.choice(primitives) for _ in range(rng.randint(low, high)))

    words = [run(2, 9) for _ in range(count // 2)]
    words += [f"{run(0, 2)}{{{run(0, 3)},{run(0, 3)}}}{run(0, 2)}" for _ in range(count // 4)]
    words += [
        f"{run(0, 2)}{{{rng.choice(('}', '{}'))}{run(0, 3)},{run(0, 3)}}}{run(0, 2)}"
        for _ in range(count - len(words))
    ]
    return words


def _bash_spellings(words: list[str], tmp_path: Path) -> list[set[str]]:
    """What bash prints for each word, one set of spellings per word. An
    empty spelling names nothing, so it is left out."""
    bash = shutil.which("bash")
    assert bash is not None
    script = "set -f\n" + "".join(f"printf '%s\\n' {word}\necho {_MARKER}\n" for word in words)
    result = subprocess.run(
        [bash, "--norc", "--noprofile", "-c", script],
        cwd=tmp_path,
        env={"LC_ALL": "C", "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    chunks = result.stdout.split(f"{_MARKER}\n")
    assert chunks[-1] == ""
    return [{line for line in chunk.splitlines() if line} for chunk in chunks[:-1]]


def _guard_spellings(word: str) -> set[str] | None:
    """Every spelling the guard reads for ``word``, or ``None`` when it
    gives up on it."""
    try:
        found = {normalise_word(word)}
        found.update(normalise_word(spelling) for spelling in expand_braces(word))
        for shell_word in iter_shell_brace_words(word):
            found.update(shell_word_spellings(shell_word))
    except TooManyToEnumerateError:
        return None
    return found


class TestTheGuardReadsEverySpellingBashDoes:
    """Words from shell quoting and brace primitives."""

    def test_every_spelling_bash_prints_is_one_the_guard_reads(self, tmp_path: Path) -> None:
        words = _generated_words(107, 2000, _PRIMITIVES)
        missed = []
        for word, spellings in zip(words, _bash_spellings(words, tmp_path), strict=True):
            guard = _guard_spellings(word)
            if guard is not None and not spellings <= guard:
                missed.append((word, sorted(spellings - guard)))
        assert missed == []

    def test_every_spelling_bash_prints_of_a_quote_free_word_is_one_the_guard_reads(
        self, tmp_path: Path
    ) -> None:
        """Plan 00466 N115: only a word holding a quoting character reached
        bash's own grouping rules, so ``.qq-{},pass}`` was read as a ``{}``
        pair and never spelled ``.qq-pass``."""
        words = _generated_words(115, 2000, _QUOTE_FREE_PRIMITIVES)
        missed = []
        for word, spellings in zip(words, _bash_spellings(words, tmp_path), strict=True):
            guard = _guard_spellings(word)
            if guard is not None and not spellings <= guard:
                missed.append((word, sorted(spellings - guard)))
        assert missed == []

    @pytest.mark.parametrize(
        ("word", "expected"),
        [('$"a"b', "ab"), ('x$"}"', "x}"), ('"$"', "$"), ("$'a'$\"b\"", "ab")],
    )
    def test_locale_quoting_reads_as_double_quoting_n111(self, word: str, expected: str) -> None:
        assert normalise_word(word) == expected


class TestTheGuardReadsEveryWordBashSplitsFromAProgram:
    """D-RULE-6 MAJOR 1: a Python literal whose quoting bash reads
    differently, so part of it is an unquoted shell word to bash, holding
    an escape that changes the literal's decoded braces."""

    def test_every_spelling_bash_prints_is_one_the_program_streams_read(
        self, tmp_path: Path
    ) -> None:
        words = _generated_words(111, 1000, (*_PRIMITIVES[:7], *_PYTHON_ESCAPES))
        missed = []
        for word, spellings in zip(words, _bash_spellings(words, tmp_path), strict=True):
            streams = python_program_streams(f"s = '''a' {word} 'b'''\n")
            assert streams is not None
            try:
                guard = {normalise_word(word)}
                for shell_word in streams.shell_words:
                    guard.update(shell_word_spellings(shell_word))
            except TooManyToEnumerateError:
                continue
            if not spellings <= guard:
                missed.append((word, sorted(spellings - guard)))
        assert missed == []
