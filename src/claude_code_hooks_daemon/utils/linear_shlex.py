"""``shlex.shlex`` with a token cost linear in the token's length (00466 N196).

The stdlib ``read_token`` grows each token with ``self.token += nextchar``.
CPython only appends to a str in place when the target is a local variable, so
on an attribute every character copies the whole token so far, and one long
word costs time quadratic in its length: measured at 0.25 s for a 100 KB word,
0.82 s at 200 KB and 3.3 s at 400 KB (Python 3.11; the method is unchanged
through 3.13). A hook command is untrusted input, so a guard that tokenises it
with the stdlib can be made slow at will.

``LinearShlex.read_token`` is the stdlib state machine, kept in the stdlib's
own shape so the two can be read side by side, except that the token is
gathered in a local list and joined once. Its tokens, and the ``ValueError``
it raises on an unterminated quote or escape, are the stdlib's;
``tests/unit/utils/test_linear_shlex.py`` checks that differentially. The
stdlib's ``debug`` tracing is not reproduced.
"""

from __future__ import annotations

import shlex
from collections import deque

_STATE_WHITESPACE = " "
_STATE_WORD = "a"
_STATE_PUNCTUATION = "c"


class LinearShlex(shlex.shlex):
    """A ``shlex.shlex`` whose ``read_token`` is linear in the token's length."""

    # Set by ``shlex.shlex.__init__`` but absent from typeshed's stub.
    posix: bool
    state: str | None
    pushback: deque[str]
    _pushback_chars: deque[str]

    def read_token(self) -> str | None:
        """The next raw token, exactly as ``shlex.shlex.read_token`` returns it.

        Raises:
            ValueError: A quote or an escape is not closed before the input ends.
        """
        quoted = False
        escapedstate = _STATE_WHITESPACE
        token: list[str] = []
        while True:
            if self.punctuation_chars and self._pushback_chars:
                nextchar = self._pushback_chars.pop()
            else:
                nextchar = self.instream.read(1)
            if nextchar == "\n":
                self.lineno += 1
            if self.state is None:
                token = []
                break
            if self.state == _STATE_WHITESPACE:
                if not nextchar:
                    self.state = None
                    break
                if nextchar in self.whitespace:
                    if token or (self.posix and quoted):
                        break
                    continue
                if nextchar in self.commenters:
                    self.instream.readline()
                    self.lineno += 1
                elif self.posix and nextchar in self.escape:
                    escapedstate = _STATE_WORD
                    self.state = nextchar
                elif nextchar in self.wordchars:
                    token = [nextchar]
                    self.state = _STATE_WORD
                elif nextchar in self.punctuation_chars:
                    token = [nextchar]
                    self.state = _STATE_PUNCTUATION
                elif nextchar in self.quotes:
                    if not self.posix:
                        token = [nextchar]
                    self.state = nextchar
                elif self.whitespace_split:
                    token = [nextchar]
                    self.state = _STATE_WORD
                else:
                    token = [nextchar]
                    break
            elif self.state in self.quotes:
                quoted = True
                if not nextchar:
                    raise ValueError("No closing quotation")
                if nextchar == self.state:
                    if not self.posix:
                        token.append(nextchar)
                        self.state = _STATE_WHITESPACE
                        break
                    self.state = _STATE_WORD
                elif self.posix and nextchar in self.escape and self.state in self.escapedquotes:
                    escapedstate = self.state
                    self.state = nextchar
                else:
                    token.append(nextchar)
            elif self.state in self.escape:
                if not nextchar:
                    raise ValueError("No escaped character")
                # In posix shells only the quote itself or the escape
                # character may be escaped within quotes.
                if (
                    escapedstate in self.quotes
                    and nextchar != self.state
                    and nextchar != escapedstate
                ):
                    token.append(self.state)
                token.append(nextchar)
                self.state = escapedstate
            elif self.state in (_STATE_WORD, _STATE_PUNCTUATION):
                if not nextchar:
                    self.state = None
                    break
                if nextchar in self.whitespace:
                    self.state = _STATE_WHITESPACE
                    if token or (self.posix and quoted):
                        break
                    continue
                if nextchar in self.commenters:
                    self.instream.readline()
                    self.lineno += 1
                    if self.posix:
                        self.state = _STATE_WHITESPACE
                        if token or quoted:
                            break
                        continue
                elif self.state == _STATE_PUNCTUATION:
                    if nextchar in self.punctuation_chars:
                        token.append(nextchar)
                    else:
                        if nextchar not in self.whitespace:
                            self._pushback_chars.append(nextchar)
                        self.state = _STATE_WHITESPACE
                        break
                elif self.posix and nextchar in self.quotes:
                    self.state = nextchar
                elif self.posix and nextchar in self.escape:
                    escapedstate = _STATE_WORD
                    self.state = nextchar
                elif (
                    nextchar in self.wordchars
                    or nextchar in self.quotes
                    or (self.whitespace_split and nextchar not in self.punctuation_chars)
                ):
                    token.append(nextchar)
                else:
                    if self.punctuation_chars:
                        self._pushback_chars.append(nextchar)
                    else:
                        self.pushback.appendleft(nextchar)
                    self.state = _STATE_WHITESPACE
                    if token or (self.posix and quoted):
                        break
                    continue
        # ``self.token`` is never written, so it keeps the empty string
        # ``shlex.shlex.__init__`` gave it, which is what the stdlib leaves
        # there between tokens.
        result = "".join(token)
        if self.posix and not quoted and result == "":
            return None
        return result
