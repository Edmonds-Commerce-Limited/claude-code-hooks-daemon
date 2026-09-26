"""Find heredocs in shell text, by bash's grammar.

Plan 00466 N120. Every caller that separates a heredoc body from the shell
around it must first agree on where a heredoc STARTS and what closes it. Three
regexes did that with three delimiter charsets, and none accepted ``<<\\EOF``.
A delimiter a site failed to recognise exposed the body to it as shell, so a
prose apostrophe there broke the tokeniser behind the write-target guards.

The rules pinned here, all bash's:

1. ``<<`` and ``<<-`` open a heredoc; ``<<<`` is a here-string and never does.
2. The delimiter is the next WORD: optional blanks, then characters up to an
   unquoted metacharacter (blank, newline, ``|&;()<>``). Any word is legal,
   ``EOF-1``, ``END.MD`` and ``my-notes`` included.
3. The delimiter is that word after quote removal (``'...'``, ``"..."``,
   ``\\x``, ``$'...'`` decoded, ``$"..."``). ANY quoting in it makes the body
   literal, so ``<<\\EOF``, ``<<E"O"F`` and ``<<$'EOF'`` are quoted heredocs
   closed by ``EOF``. A ``$( )``, ``$(( ))`` or backtick span in the word is
   kept verbatim, blanks and quotes included, and quotes inside it do not
   make the heredoc quoted: ``<<$(echo)`` is closed by the line ``$(echo)``.
4. ``<<`` inside quotes, a comment or an arithmetic expansion is not an
   operator. Inside a double-quoted ``$( )`` or backtick substitution it is,
   which is what makes ``-m "$(cat <<'EOF' ... EOF)"`` a heredoc. An ANSI-C
   ``$'...'`` string ends at its first UNESCAPED quote; ``$$`` is the pid,
   so a quote after it is a plain one.
5. Bodies start after the next newline that is not inside a quote, and one
   closes only on a line that IS the delimiter (after leading tabs, for
   ``<<-``). Inside a substitution, ``EOF)`` also ends it, as bash does.

A word left open by an unterminated quote is not an operator: bash would read
on past the line, and reporting a delimiter here would hide text bash runs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

from claude_code_hooks_daemon.utils.ansi_c import ansi_c_string

#: Characters after which an unquoted ``#`` starts a WORD, and so a comment.
COMMENT_PRECEDERS: Final[str] = " \t\n;&|()<>"

_HEREDOC: Final[str] = "<<"
_STRIP_TABS: Final[str] = "-"
_BLANKS: Final[str] = " \t"
_NEWLINE: Final[str] = "\n"
_TAB: Final[str] = "\t"
_METACHARACTERS: Final[str] = " \t\n|&;()<>"
_DOUBLE_QUOTE_ESCAPABLE: Final[str] = '$`"\\\n'
_SUBSTITUTION_CLOSE: Final[str] = ")"
_PID: Final[str] = "$$"
_ANSI_C_OPEN: Final[str] = "$'"
_LOCALE_OPEN: Final[str] = '$"'
_SUBSTITUTION_OPEN: Final[str] = "$("

_UNQUOTED: Final[str] = "unquoted"
_DOUBLE: Final[str] = "double"
_SUBSTITUTION: Final[str] = "substitution"
_BACKTICK: Final[str] = "backtick"
_ARITHMETIC: Final[str] = "arithmetic"


@dataclass(frozen=True)
class HeredocOperator:
    """One ``<<`` operator: its span in the text and the delimiter it names."""

    start: int
    end: int
    delimiter: str
    quoted: bool
    strip_tabs: bool


@dataclass(frozen=True)
class Heredoc:
    """An operator and its body, as offsets into the scanned text.

    ``body_start`` to ``closer_end`` covers the body lines and the closing line,
    without the newline after it. Unterminated, all three run to the end.
    """

    operator: HeredocOperator
    body_start: int
    closer_start: int
    closer_end: int
    terminated: bool

    def body(self, text: str) -> str:
        """The body lines, without the newline before the closer."""
        if not self.terminated:
            return text[self.body_start :]
        return text[self.body_start : max(self.body_start, self.closer_start - 1)]


@dataclass(frozen=True)
class HeredocScan:
    """Every heredoc in the text, and each newline that ENDS a command.

    ``breaks`` are top-level newlines only: one inside a quoted argument or a
    substitution continues the command, and one inside a body is data.
    """

    heredocs: list[Heredoc] = field(default_factory=list)
    breaks: list[int] = field(default_factory=list)


def find_heredoc_operators(line: str) -> list[HeredocOperator]:
    """Every heredoc operator on one line, in order. See the module docstring."""
    return [heredoc.operator for heredoc in scan_heredocs(line).heredocs]


def scan_heredocs(text: str) -> HeredocScan:
    """Every heredoc in ``text`` with its body, and where each command ends."""
    return _Scanner(text).run()


@dataclass
class _Frame:
    """One scanning context, and its open-paren depth where that matters."""

    context: str
    depth: int = 0


class _Scanner:
    """A context stack over the text: quotes, substitutions, arithmetic."""

    def __init__(self, text: str) -> None:
        self._text = text
        self._index = 0
        self._stack: list[_Frame] = [_Frame(_UNQUOTED)]
        self._pending: list[HeredocOperator] = []
        self._scan = HeredocScan()

    def run(self) -> HeredocScan:
        while self._index < len(self._text):
            context = self._stack[-1].context
            if context == _DOUBLE:
                advanced = self._double_quoted()
            elif context == _ARITHMETIC:
                advanced = self._arithmetic()
            else:
                advanced = self._unquoted(context)
            if not advanced:
                break
        # An operator whose line never ended has an empty, unclosed body.
        end = len(self._text)
        self._scan.heredocs.extend(
            Heredoc(operator, end, end, end, terminated=False) for operator in self._pending
        )
        return self._scan

    def _double_quoted(self) -> bool:
        text, index = self._text, self._index
        char = text[index]
        if char == "\\":
            self._index += 2
        elif char == '"':
            self._stack.pop()
            self._index += 1
        elif text.startswith("$((", index):
            self._stack.append(_Frame(_ARITHMETIC, 2))
            self._index += 3
        elif text.startswith("$(", index):
            self._stack.append(_Frame(_SUBSTITUTION, 1))
            self._index += 2
        elif char == "`":
            self._stack.append(_Frame(_BACKTICK))
            self._index += 1
        else:
            self._index += 1
        return True

    def _arithmetic(self) -> bool:
        char = self._text[self._index]
        if char in "()":
            self._count_paren(char)
        self._index += 1
        return True

    def _unquoted(self, context: str) -> bool:
        text, index = self._text, self._index
        char = text[index]
        if char == _NEWLINE:
            return self._newline(context)
        if char == "\\" or text.startswith(_PID, index):
            self._index += 2
            return True
        if text.startswith(_ANSI_C_OPEN, index):
            ansi_c = ansi_c_string(text, index + len(_ANSI_C_OPEN))
            if ansi_c is None:
                return False
            self._index = ansi_c[1]
            return True
        if char == "'":
            closing = text.find("'", index + 1)
            if closing < 0:
                return False
            self._index = closing + 1
            return True
        if char == '"':
            self._stack.append(_Frame(_DOUBLE))
            self._index += 1
            return True
        if char == "#" and (index == 0 or text[index - 1] in COMMENT_PRECEDERS):
            line_end = text.find(_NEWLINE, index)
            self._index = len(text) if line_end < 0 else line_end
            return True
        if char == "`":
            if context == _BACKTICK:
                self._stack.pop()
            else:
                self._stack.append(_Frame(_BACKTICK))
            self._index += 1
            return True
        if text.startswith("$((", index):
            self._stack.append(_Frame(_ARITHMETIC, 2))
            self._index += 3
            return True
        if text.startswith("$(", index):
            self._stack.append(_Frame(_SUBSTITUTION, 1))
            self._index += 2
            return True
        if context == _SUBSTITUTION and char in "()":
            self._count_paren(char)
            self._index += 1
            return True
        if char == "<":
            return self._redirection(context)
        self._index += 1
        return True

    def _count_paren(self, char: str) -> None:
        """Track nesting in a substitution or arithmetic; pop it at its close."""
        frame = self._stack[-1]
        frame.depth += 1 if char == "(" else -1
        if frame.depth == 0:
            self._stack.pop()

    def _newline(self, context: str) -> bool:
        """A command ends here at top level; any pending bodies start after it."""
        if len(self._stack) == 1:
            self._scan.breaks.append(self._index)
        self._index += 1
        pending, self._pending = self._pending, []
        for position, operator in enumerate(pending):
            if position > 0 and self._text.startswith(_NEWLINE, self._index):
                # The next body starts on the line after the previous closer.
                self._index += 1
            heredoc = self._read_body(operator, inside_substitution=context == _SUBSTITUTION)
            self._scan.heredocs.append(heredoc)
            if not heredoc.terminated:
                # The rest of the text is this body; later operators get none.
                self._pending = pending[position + 1 :]
                self._index = len(self._text)
                return False
        return True

    def _read_body(self, operator: HeredocOperator, *, inside_substitution: bool) -> Heredoc:
        text = self._text
        body_start = cursor = self._index
        while cursor < len(text):
            line_end = text.find(_NEWLINE, cursor)
            line_end = len(text) if line_end < 0 else line_end
            line = text[cursor:line_end]
            candidate = line.lstrip(_TAB) if operator.strip_tabs else line
            if candidate == operator.delimiter:
                self._index = line_end
                return Heredoc(operator, body_start, cursor, line_end, terminated=True)
            if inside_substitution and candidate.startswith(
                operator.delimiter + _SUBSTITUTION_CLOSE
            ):
                closer_end = cursor + (len(line) - len(candidate)) + len(operator.delimiter)
                self._index = closer_end
                return Heredoc(operator, body_start, cursor, closer_end, terminated=True)
            cursor = line_end + 1
        end = len(text)
        return Heredoc(operator, body_start, end, end, terminated=False)

    def _redirection(self, context: str) -> bool:
        text, start = self._text, self._index
        run_end = start
        while run_end < len(text) and text[run_end] == "<":
            run_end += 1
        self._index = run_end
        if run_end - start != len(_HEREDOC):
            return True
        strip_tabs = text.startswith(_STRIP_TABS, run_end)
        cursor = run_end + (1 if strip_tabs else 0)
        while cursor < len(text) and text[cursor] in _BLANKS:
            cursor += 1
        # Inside backticks the closing backtick ends the word: bash has already
        # cut the substitution's text out before it reads the heredoc.
        terminators = _METACHARACTERS + ("`" if context == _BACKTICK else "")
        word = _read_word(text, cursor, terminators)
        if word is None:
            # The word runs into an unterminated quote: nothing later can be
            # judged, and bash would read on past it.
            return False
        delimiter, quoted, word_end = word
        if word_end == cursor:
            return True
        self._pending.append(HeredocOperator(start, word_end, delimiter, quoted, strip_tabs))
        self._index = word_end
        return True


def _read_word(text: str, start: int, terminators: str) -> tuple[str, bool, int] | None:
    """``(delimiter, quoted, end)`` for the word at ``start``; None if left open."""
    parts: list[str] = []
    quoted = False
    index = start
    while index < len(text) and text[index] not in terminators:
        char = text[index]
        if char == "\\":
            if index + 1 >= len(text):
                return None
            parts.append(text[index + 1])
            quoted = True
            index += 2
        elif text.startswith(_PID, index):
            parts.append(_PID)
            index += len(_PID)
        elif text.startswith(_ANSI_C_OPEN, index):
            ansi_c = ansi_c_string(text, index + len(_ANSI_C_OPEN))
            if ansi_c is None:
                return None
            parts.append(ansi_c[0])
            quoted = True
            index = ansi_c[1]
        elif text.startswith(_LOCALE_OPEN, index):
            closing, inner = _double_quoted_span(text, index + len(_LOCALE_OPEN))
            if closing < 0:
                return None
            parts.append(inner)
            quoted = True
            index = closing + 1
        elif text.startswith(_SUBSTITUTION_OPEN, index) or char == "`":
            span_end = _verbatim_span_end(text, index)
            if span_end < 0:
                return None
            parts.append(text[index:span_end])
            index = span_end
        elif char == "'":
            closing = text.find("'", index + 1)
            if closing < 0:
                return None
            parts.append(text[index + 1 : closing])
            quoted = True
            index = closing + 1
        elif char == '"':
            closing, inner = _double_quoted_span(text, index + 1)
            if closing < 0:
                return None
            parts.append(inner)
            quoted = True
            index = closing + 1
        else:
            parts.append(char)
            index += 1
    return "".join(parts), quoted, index


def _verbatim_span_end(text: str, start: int) -> int:
    """Index past the ``$( )``, ``$(( ))`` or backtick span at ``start``, or -1.

    Quotes inside the span are skipped whole, so a ``)`` or a blank in them
    does not end it.
    """
    if text[start] == "`":
        index = start + 1
        while index < len(text):
            if text[index] == "\\":
                index += 2
            elif text[index] == "`":
                return index + 1
            else:
                index += 1
        return -1
    depth = 0
    index = start + 1
    while index < len(text):
        char = text[index]
        if char == "\\" or text.startswith(_PID, index):
            index += 2
        elif text.startswith(_ANSI_C_OPEN, index):
            ansi_c = ansi_c_string(text, index + len(_ANSI_C_OPEN))
            if ansi_c is None:
                return -1
            index = ansi_c[1]
        elif char == "'":
            closing = text.find("'", index + 1)
            if closing < 0:
                return -1
            index = closing + 1
        elif char == '"':
            closing, _inner = _double_quoted_span(text, index + 1)
            if closing < 0:
                return -1
            index = closing + 1
        else:
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
            index += 1
            if depth == 0:
                return index
    return -1


def _double_quoted_span(text: str, start: int) -> tuple[int, str]:
    """Index of the closing ``"`` (or -1) and the text inside, escapes removed."""
    parts: list[str] = []
    index = start
    while index < len(text):
        char = text[index]
        if char == '"':
            return index, "".join(parts)
        if char == "\\" and index + 1 < len(text) and text[index + 1] in _DOUBLE_QUOTE_ESCAPABLE:
            parts.append(text[index + 1])
            index += 2
            continue
        parts.append(char)
        index += 1
    return -1, ""
