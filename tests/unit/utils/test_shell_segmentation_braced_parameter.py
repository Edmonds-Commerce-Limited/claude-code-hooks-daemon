"""A braced parameter (`${NAME}`, `${x:-a b}`) is part of its word, like `$NAME` (Plan 00478).

Stopping the word stream at a `${` hid every word after it:
`awk '{print > FILENAME}' ${PWD}/protected/x` lost its operand, and with an
operator form (`${IN:-a.txt} protected/x`) so did every later literal operand.
The scanner reads the braces balanced, skipping quotes, escapes and nested
braces inside them; only a command substitution or an unclosed brace still
ends the stream.
"""

import pytest

from claude_code_hooks_daemon.utils.shell_segmentation import (
    iter_shell_words,
    shell_word_spans,
)


@pytest.mark.parametrize(
    ("text", "words"),
    [
        ("awk x ${PWD}/protected/x", ["awk", "x", "${PWD}/protected/x"]),
        ('cat "${PWD}"/a b', ["cat", '"${PWD}"/a', "b"]),
        ("ls ${HOME}/../p q", ["ls", "${HOME}/../p", "q"]),
        ('echo "${A}x${_b1}" z', ["echo", '"${A}x${_b1}"', "z"]),
    ],
)
def test_a_simple_braced_parameter_keeps_the_word_stream_going(text: str, words: list[str]) -> None:
    assert list(iter_shell_words(text)) == words
    assert [text[start:end] for start, end in shell_word_spans(text)] == words


@pytest.mark.parametrize(
    ("text", "words"),
    [
        ("echo ${x:-a b} c", ["echo", "${x:-a b}", "c"]),
        ("echo ${#x} c", ["echo", "${#x}", "c"]),
        ("echo ${x[@]} c", ["echo", "${x[@]}", "c"]),
        ('echo "${x/a/b c}" d', ["echo", '"${x/a/b c}"', "d"]),
        ("rm ${PWD:-.}/protected/x y", ["rm", "${PWD:-.}/protected/x", "y"]),
        ('rm "${PWD:-.}"/protected/x y', ["rm", '"${PWD:-.}"/protected/x', "y"]),
        ("rm ${HOME#x}/p ${x:+a}/q", ["rm", "${HOME#x}/p", "${x:+a}/q"]),
        ("echo ${x:-${y:-a b}} c", ["echo", "${x:-${y:-a b}}", "c"]),
        ("echo ${x:-'}'} c", ["echo", "${x:-'}'}", "c"]),
        ('echo "${x:-"a } b"}" c', ["echo", '"${x:-"a } b"}"', "c"]),
        ("echo ${x:-\\}} c", ["echo", "${x:-\\}}", "c"]),
        ("echo ${x:-$y} c", ["echo", "${x:-$y}", "c"]),
    ],
)
def test_an_operator_form_is_read_brace_balanced_as_part_of_the_word(
    text: str, words: list[str]
) -> None:
    """An operator form is an unresolved expansion like `$NAME`; its extent is its braces."""
    assert list(iter_shell_words(text)) == words
    assert [text[start:end] for start, end in shell_word_spans(text)] == words


@pytest.mark.parametrize(
    "text",
    [
        "echo ${ c",
        "echo ${x:-a c",
        "echo ${x:-$(id)} c",
        "echo ${x:-`id`} c",
        'echo "${x:-$(id)}" c',
        "echo ${x:-'a} c",
    ],
)
def test_an_unterminated_or_substituting_operator_form_still_ends_the_stream(text: str) -> None:
    """A command substitution or an unclosed brace hides the extent: the stream ends."""
    assert list(iter_shell_words(text))[-1] is None
    assert [text[start:end] for start, end in shell_word_spans(text)] == ["echo"]
