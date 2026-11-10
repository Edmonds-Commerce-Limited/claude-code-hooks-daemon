"""A simple braced parameter (`${NAME}`) has a known extent, like `$NAME` (Plan 00478).

The word scanner stops at any `${` because an operator form (`${x:-a b}`) can
hide whitespace. A bare `${NAME}` cannot, so stopping there hid every word
after it: `awk '{print > FILENAME}' ${PWD}/protected/x` lost its operand and
write_protected_paths could not see the protected directory it names.
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
    "text",
    ["echo ${x:-a b} c", "echo ${#x} c", "echo ${x[@]} c", 'echo "${x/a/b c}" d', "echo ${ c"],
)
def test_an_operator_form_still_ends_the_stream(text: str) -> None:
    assert list(iter_shell_words(text))[-1] is None
