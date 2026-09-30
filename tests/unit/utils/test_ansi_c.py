"""Bash's ANSI-C ``$'...'`` quoting, decoded once for every shell reader.

Plan 00466 N120. The write-target tokeniser, the heredoc scanner and the
segment splitter each have to know where a ``$'...'`` string ends: read as a
plain single quote, ``$'it\\'s'`` closes at the escaped quote and every later
boundary moves. Each expected value was checked against bash 5.2.
"""

from __future__ import annotations

import pytest

from claude_code_hooks_daemon.utils.ansi_c import ansi_c_string


class TestAnsiCString:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("$'it\\'s' tail", ("it's", 8)),
            ("$'a\\x41b'", ("aAb", 9)),
            ("$'\\101'", ("A", 7)),
            ("$'\\u00e9'", ("é", 9)),
            ("$'\\U0001F600'", ("\U0001f600", 13)),
            ("$'\\cA'", ("\x01", 6)),
            ("$'tab\\there'", ("tab\there", 12)),
            ("$'\\\\'", ("\\", 5)),
            ("$'n\\0ul'", ("n", 8)),
            ("$'\\q'", ("\\q", 5)),
            ("$''", ("", 3)),
        ],
    )
    def test_the_value_and_the_index_past_the_closing_quote(
        self, text: str, expected: tuple[str, int]
    ) -> None:
        assert ansi_c_string(text, 2) == expected

    @pytest.mark.parametrize("text", ["$'it", "$'it\\'", "$'\\"])
    def test_an_unterminated_string_is_none(self, text: str) -> None:
        assert ansi_c_string(text, 2) is None
