"""The pipe blocker must resolve the producer from the segment that actually feeds the pipe.

Two defects in ``_extract_source_segment``, one confirmed and one latent, both of
the mention-vs-invocation family tracked as Plan 00200 Task 3.6.

**Confirmed — newline is not a chain separator.** The chain split walked
``["&&", "||", ";"]`` only. A command written across lines therefore never split,
so the producer text for::

    cd /workspace
    grep -n foo bar.py | head -30

resolved to the whole two-line string, which no whitelist pattern anchors to
(they are anchored, e.g. ``^grep\\b``). A whitelisted producer was denied purely
because of how the caller happened to lay the command out — ``&&`` and ``;``
forms of the identical pipeline were allowed. Hit twice in one session while
running ordinary read-only greps.

**Latent — the chain split was not quote-aware.** ``rsplit(";", 1)`` cuts inside
a quoted argument, so ``grep -E "a;b" | head`` resolved its producer to ``b"``.
The sibling pipe split already had a quote-aware scanner; the chain split did
not, so the two disagreed about what a separator is.

The negative cases matter as much as the positives here: a fix that simply
widened the whitelist, or that split too eagerly, would let a genuinely
expensive producer through. Every allow-case below is paired with a deny-case
built from the same shape.
"""

from __future__ import annotations

import pytest

from claude_code_hooks_daemon.handlers.pre_tool_use.pipe_blocker import PipeBlockerHandler


def _matches(command: str) -> bool:
    """True when the handler would BLOCK ``command``."""
    return PipeBlockerHandler().matches({"tool_name": "Bash", "tool_input": {"command": command}})


class TestNewlineSeparatedChains:
    """A newline separates commands exactly as ``&&`` and ``;`` do."""

    @pytest.mark.parametrize(
        "command",
        [
            "cd /workspace\ngrep -n foo bar.py | head -30",
            "cd /workspace\n\ngrep -n foo bar.py | head -30",
            "export X=1\ncd /workspace\ngrep -rn foo src/ | tail -5",
            "cd /workspace\r\ngrep -n foo bar.py | head -30",
        ],
    )
    def test_whitelisted_producer_after_a_newline_is_allowed(self, command: str) -> None:
        assert not _matches(
            command
        ), "grep is whitelisted; a preceding cd on its own line must not change that"

    @pytest.mark.parametrize(
        "command",
        [
            "cd /workspace\npytest tests/ | head -30",
            "export X=1\ncd /workspace\npytest tests/ | tail -20",
        ],
    )
    def test_expensive_producer_after_a_newline_is_still_blocked(self, command: str) -> None:
        """The fix must not become a bypass: put pytest after a newline and it still blocks."""
        assert _matches(command), "a newline must not launder an expensive producer"

    def test_separator_forms_agree(self) -> None:
        """The same pipeline must get the same verdict however the caller chains it."""
        allowed = [
            "grep -n foo bar.py | head -30",
            "cd /workspace && grep -n foo bar.py | head -30",
            "cd /workspace ; grep -n foo bar.py | head -30",
            "cd /workspace\ngrep -n foo bar.py | head -30",
        ]
        assert [_matches(c) for c in allowed] == [False] * len(allowed)

        blocked = [
            "pytest tests/ | head -30",
            "cd /workspace && pytest tests/ | head -30",
            "cd /workspace ; pytest tests/ | head -30",
            "cd /workspace\npytest tests/ | head -30",
        ]
        assert [_matches(c) for c in blocked] == [True] * len(blocked)


class TestChainSplitIsQuoteAware:
    """A separator inside a quoted argument is data, not shell syntax."""

    @pytest.mark.parametrize(
        "command",
        [
            'grep -E "a;b" tests/ | head -20',
            "grep -E 'x && y' tests/ | head -20",
            'grep -n "line one\nline two" bar.py | head -5',
        ],
    )
    def test_quoted_separator_does_not_cut_the_producer(self, command: str) -> None:
        assert not _matches(
            command
        ), "the separator is inside a quoted pattern, so the producer is still grep"

    def test_quoted_separator_does_not_hide_an_expensive_producer(self) -> None:
        """Quote-awareness must not let a quoted separator mask a real blacklist hit."""
        assert _matches('pytest -k "a;b" | head -20')


class TestEscapedQuotesCannotHideAChain:
    """A backslash-escaped quote must not desynchronise the scanner.

    This one is a false NEGATIVE — a bypass, not an annoyance. A scanner blind
    to ``\\"`` flips its in-double-quote flag on the escaped quote and never
    leaves quoted state, so every later separator looks like data. Prefix an
    expensive command with a whitelisted one containing an escaped quote and the
    chain separator is never seen::

        echo "\\"" ; pytest tests/ | head -20   -> producer resolved to `echo ...`

    The whitelist then matched the leading ``echo`` and the pipe blocker allowed
    a full pytest run. The sibling splitter in the project's `enforce_llm_qa`
    handler already tracked escapes; this one did not, which is exactly the
    divergence two independent parsers produce.

    Bash rule being implemented: a backslash escapes the next character
    everywhere EXCEPT inside single quotes, where it is literal.
    """

    @pytest.mark.parametrize(
        "command",
        [
            r'echo "\"" ; pytest tests/ | head -20',
            r'grep -E "a\"b" bar.py ; pytest tests/ | head -20',
            'echo "\\"" \n pytest tests/ | head -20',
            r'echo "\"" && pytest tests/ | head -20',
        ],
    )
    def test_escaped_quote_cannot_launder_an_expensive_producer(self, command: str) -> None:
        assert _matches(
            command
        ), "an escaped quote must not hide the chain separator that precedes pytest"

    @pytest.mark.parametrize(
        "command",
        [
            r'grep -E "a\"b" bar.py | head -20',
            r"grep -E 'a\b' bar.py | head -20",
        ],
    )
    def test_escaped_quote_does_not_break_a_legitimate_allow(self, command: str) -> None:
        """Escape handling must not swing the other way into false positives."""
        assert not _matches(command)

    def test_backslash_is_literal_inside_single_quotes(self) -> None:
        """Bash does not honour escapes inside single quotes; nor may the scanner.

        If the scanner wrongly treated the backslash as escaping the closing
        quote, it would stay 'in quotes' and miss the `;` before pytest.
        """
        assert _matches(r"grep -E 'a\' bar.py ; pytest tests/ | head -20")


class TestSourceSegmentResolution:
    """Directly pin what the producer resolves to, not just the verdict."""

    @pytest.mark.parametrize(
        ("command", "expected"),
        [
            ("cd /workspace\ngrep -n foo bar.py | head -30", "grep -n foo bar.py"),
            ("cd /workspace && grep -n foo bar.py | head -30", "grep -n foo bar.py"),
            ("cd /workspace ; grep -n foo bar.py | head -30", "grep -n foo bar.py"),
            # The FULL segment is returned, arguments included — the quoted ";"
            # must not truncate it to 'b" bar.py' as it did before the fix.
            ('grep -E "a;b" bar.py | head -20', 'grep -E "a;b" bar.py'),
            ("cat a.txt | grep foo | head -5", "grep foo"),
        ],
    )
    def test_producer_is_the_segment_feeding_the_pipe(self, command: str, expected: str) -> None:
        handler = PipeBlockerHandler()

        assert handler._extract_source_segment(command) == expected
