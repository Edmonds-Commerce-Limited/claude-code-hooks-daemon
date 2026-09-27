"""Tests for LinearShlex: stdlib shlex's tokens at a cost linear in token length."""

from __future__ import annotations

import random
import shlex

import pytest

from claude_code_hooks_daemon.utils.linear_shlex import LinearShlex
from tests.scaling import SIZE_FACTOR, SUPERLINEAR_RATIO, scaling_ratio

# Every character class the state machine branches on: word characters,
# whitespace and newlines, both quotes, the escape, a commenter, and each
# punctuation character the project's callers configure.
_ALPHABET = "ab_./-~*=$` \t\n'\"\\#(){}!<>;|&"
_PUNCTUATION_CHARS = "(){}!<>"
_CORPUS = (
    "",
    "   ",
    "echo hello world",
    "echo 'single quoted' \"double quoted\"",
    'echo "a \\" b" \'c \\ d\'',
    "echo a\\ b c\\\\d",
    "echo \"\\x\" '\\x' \\x",
    "(./run_all.sh)",
    "{a,b}!x<in>out",
    "a((b))c",
    "CI=1 ./scripts/qa/run_all.sh >out.txt",
    "echo a # a comment\necho b",
    "echo ''",
    'echo ""',
    "echo a''b",
    'echo "unterminated',
    "echo 'unterminated",
    "echo trailing\\",
)


def _tokens(
    lexer_cls: type[shlex.shlex], text: str, configuration: tuple[bool, bool, bool]
) -> list[str] | str:
    """Every token ``lexer_cls`` yields for ``text``, or the error it raised.

    ``configuration`` is ``(posix, punctuation_chars set, whitespace_split)``.
    """
    posix, punctuation, whitespace_split = configuration
    if punctuation:
        lexer = lexer_cls(text, posix=posix, punctuation_chars=_PUNCTUATION_CHARS)
    else:
        lexer = lexer_cls(text, posix=posix)
    lexer.whitespace_split = whitespace_split
    try:
        return list(lexer)
    except ValueError as exc:
        return f"ValueError: {exc}"


_CONFIGURATIONS = [
    pytest.param(
        (posix, punctuation, split),
        id=f"posix={posix},punctuation={punctuation},whitespace_split={split}",
    )
    for posix in (True, False)
    for punctuation in (True, False)
    for split in (True, False)
]


class TestTokensMatchTheStdlib:
    """LinearShlex changes the cost of a token, never the token."""

    @pytest.mark.parametrize("configuration", _CONFIGURATIONS)
    @pytest.mark.parametrize("text", _CORPUS)
    def test_the_corpus_tokenises_identically(
        self, text: str, configuration: tuple[bool, bool, bool]
    ) -> None:
        assert _tokens(LinearShlex, text, configuration) == _tokens(
            shlex.shlex, text, configuration
        )

    @pytest.mark.parametrize("configuration", _CONFIGURATIONS)
    def test_random_text_tokenises_identically(
        self, configuration: tuple[bool, bool, bool]
    ) -> None:
        generator = random.Random(466196)
        mismatches = []
        for _ in range(3000):
            text = "".join(generator.choice(_ALPHABET) for _ in range(generator.randint(0, 24)))
            ours = _tokens(LinearShlex, text, configuration)
            theirs = _tokens(shlex.shlex, text, configuration)
            if ours != theirs:
                mismatches.append(f"{text!r}: {ours!r} != {theirs!r}")
        assert not mismatches, "\n".join(mismatches[:10])

    def test_the_token_attribute_is_reset_after_each_token(self) -> None:
        lexer = LinearShlex("alpha beta", posix=True)
        lexer.whitespace_split = True
        assert lexer.get_token() == "alpha"
        assert lexer.token == ""


class TestCostIsLinearInTokenLength:
    """A long word is the input the stdlib's per-character copy is quadratic in."""

    @pytest.mark.parametrize(
        "shape",
        [
            pytest.param("a", id="bare word"),
            pytest.param("'", id="single-quoted"),
            pytest.param('"', id="double-quoted"),
        ],
    )
    def test_a_long_token_costs_linear_time(self, shape: str) -> None:
        small_n = 50 * 1024

        def text_at(size: int) -> str:
            if shape == "a":
                return "echo " + "a" * size
            return f"echo {shape}{'a' * size}{shape}"

        def work_at(size: int) -> None:
            lexer = LinearShlex(text_at(size), posix=True, punctuation_chars=_PUNCTUATION_CHARS)
            lexer.whitespace_split = True
            list(lexer)

        ratio = scaling_ratio(work_at, small_n, text_at(SIZE_FACTOR * small_n))
        assert ratio <= SUPERLINEAR_RATIO, f"cost grew {ratio:.0f}x for {SIZE_FACTOR}x input"
