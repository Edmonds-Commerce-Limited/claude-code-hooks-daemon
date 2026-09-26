"""Find heredocs in shell text, by bash's grammar.

Plan 00466 N120. Every caller that separates a heredoc body from the shell
around it must first agree on where a heredoc STARTS and what closes it. Three
regexes did that with three delimiter charsets, and none accepted ``<<\\EOF``.
A delimiter a site failed to recognise exposed the body to it as shell, so a
prose apostrophe there broke the tokeniser behind the write-target guards.

The rules pinned here, all bash's (5.2):

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
4. ``<<`` is an operator only where bash reads a command: at top level, in a
   ``$( )`` and in a backtick substitution (also inside double quotes, which
   is what makes ``-m "$(cat <<'EOF' ... EOF)"`` a heredoc). Inside quotes, a
   comment, ``${ }``, ``$[ ]``, ``$(( ))``, a bare ``(( ))``, an array
   ``a=( )`` or a pattern ``@( )`` it is text or a shift. A ``#`` right after
   an opening backtick starts a comment, which ends at the newline or at the
   closing backtick. An ANSI-C ``$'...'`` string ends at its first UNESCAPED
   quote; ``$$`` is the pid, so a quote after it is a plain one.
5. A backtick substitution ends at its first unescaped backtick, whatever
   quotes sit in between; an operator it opened gets no body outside it.
6. Bodies start after the next newline that is not inside a quote, and one
   closes only on a line that IS the delimiter (after leading tabs, for
   ``<<-``). Inside a substitution, ``EOF)`` also ends it, as bash does. An
   UNQUOTED body joins a line ending in an odd run of backslashes to the next
   before it compares; a quoted body joins nothing.
7. A backslash-newline outside a quoted body, a single-quoted string, an
   ANSI-C string and a comment is removed before bash reads the line.

**Where the scanner cannot be sure how bash splits operators from bodies, it
STOPS** (Plan 00466 N101 round 10, coordinator ruling). A heredoc bash sees
and the scanner misses is as unsafe as the reverse: its body is then read as
commands, and a fake ``<<Y`` in it hides later lines bash runs. So past
``stopped_at`` no body is reported, every newline is a command break, and a
caller that denies on what a command does must treat that text as
unreadable. The uncertain shapes: an unterminated quote or substitution, a
``$((``/``((`` bash re-parses as subshells, a backslash-newline that glues a
two-character token (``$\\⏎(``, ``a\\⏎#``), a ``${``/``$[`` in a delimiter
word, a newline inside an expansion or array while a body is pending, and a
backtick substitution whose end falls inside a quote, a comment or a body.
"""

from __future__ import annotations

import re
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
_BACKSLASH: Final[str] = "\\"
_CONTINUATION: Final[str] = "\\\n"
_METACHARACTERS: Final[str] = " \t\n|&;()<>"
_DOUBLE_QUOTE_ESCAPABLE: Final[str] = '$`"\\\n'
_SUBSTITUTION_CLOSE: Final[str] = ")"
_PID: Final[str] = "$$"
_ANSI_C_OPEN: Final[str] = "$'"
_LOCALE_OPEN: Final[str] = '$"'
_SUBSTITUTION_OPEN: Final[str] = "$("
_ARITHMETIC_OPEN: Final[str] = "$(("
_PARAMETER_OPEN: Final[str] = "${"
_BRACKET_OPEN: Final[str] = "$["
_BARE_ARITHMETIC_OPEN: Final[str] = "(("
#: Characters before a bare ``((`` that leave it at the start of a command.
_COMMAND_START_PRECEDERS: Final[str] = " \t\n;&|("
#: What a ``$`` joined by a backslash-newline would turn into a token.
_GLUE_AFTER_DOLLAR: Final[str] = "({['\"$"
#: What a word character joined by a backslash-newline would turn into a
#: token: ``a(`` opens an array or pattern, ``a#`` is no comment.
_GLUE_AFTER_WORD: Final[str] = "(#"
_ASSIGNMENT_WORD: Final[re.Pattern[str]] = re.compile(
    r"[A-Za-z_][A-Za-z0-9_]*(?:\[[^\]]*\])?\+?=\Z"
)

_UNQUOTED: Final[str] = "unquoted"
_DOUBLE: Final[str] = "double"
_SUBSTITUTION: Final[str] = "substitution"
_BACKTICK: Final[str] = "backtick"
_ARITHMETIC: Final[str] = "arithmetic"
_PARAMETER: Final[str] = "parameter"
_BRACKET: Final[str] = "bracket"
_ARRAY: Final[str] = "array"
_PATTERN: Final[str] = "pattern"

#: Frames in which bash reads a command, so ``<<`` can be an operator.
_OPERATOR_FRAMES: Final[frozenset[str]] = frozenset({_UNQUOTED, _SUBSTITUTION, _BACKTICK})
#: Frames in which an unquoted ``#`` at a word start begins a comment.
_COMMENT_FRAMES: Final[frozenset[str]] = frozenset({_UNQUOTED, _SUBSTITUTION, _BACKTICK, _ARRAY})
#: Frames holding words, not commands: a body cannot start inside one.
_WORD_FRAMES: Final[frozenset[str]] = frozenset(
    {_PARAMETER, _BRACKET, _ARITHMETIC, _ARRAY, _PATTERN}
)
#: Frames that close at their matching ``)``.
_PAREN_FRAMES: Final[frozenset[str]] = frozenset({_SUBSTITUTION, _ARRAY, _PATTERN})


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
    """Every heredoc in the text, each newline that ENDS a command, and more.

    ``breaks`` are top-level newlines only: one inside a quoted argument or a
    substitution continues the command, and one inside a body is data.

    ``stopped_at`` is where the scanner could no longer be sure how bash
    splits operators from bodies (see the module docstring), or None. No
    heredoc is reported past it and every later newline is a break.

    ``continuations`` are the offsets of the backslashes whose
    backslash-newline :func:`remove_line_continuations` removes: every one
    bash removes, plus those in quoted strings and quoted bodies whose removal
    moves no boundary. Kept: one in a comment, one that stopped the scan, and
    one in a quoted body whose removal would change which line closes it.
    """

    heredocs: list[Heredoc] = field(default_factory=list)
    breaks: list[int] = field(default_factory=list)
    stopped_at: int | None = None
    continuations: list[int] = field(default_factory=list)


def find_heredoc_operators(line: str) -> list[HeredocOperator]:
    """Every heredoc operator on one line, in order. See the module docstring.

    A line is often a fragment -- the opener of ``-m "$(cat <<'EOF'`` leaves
    its substitution open -- so every operator the scan read is reported,
    whether or not the scan could place its body.
    """
    scanner = _Scanner(line)
    scanner.run()
    return scanner.operators


def scan_heredocs(text: str) -> HeredocScan:
    """Every heredoc in ``text`` with its body, and where each command ends."""
    return _Scanner(text).run()


def substitution_end(text: str, open_paren: int) -> int | None:
    """Index just past the ``)`` closing the command or process substitution
    whose ``(`` is at ``open_paren``, read by bash's grammar: heredoc bodies,
    quotes, comments and nested expansions included. None when the scan
    cannot be sure where it ends (see ``stopped_at``) or it never does."""
    scanner = _Scanner(text, start=open_paren + 1, outer=_Frame(_SUBSTITUTION, open_paren, 1))
    return scanner.run_to_close()


def remove_line_continuations(command: str) -> str:
    """``command`` with each backslash-newline in ``scan.continuations`` removed.

    Derived from the scan, so a rescan of the result finds the same heredocs,
    breaks and stop as the raw text did (Plan 00466 N101 round 10, MAJOR B).
    """
    if _CONTINUATION not in command:
        return command
    removed = set(scan_heredocs(command).continuations)
    if not removed:
        return command
    parts: list[str] = []
    copied_to = 0
    for index in sorted(removed):
        parts.append(command[copied_to:index])
        copied_to = index + len(_CONTINUATION)
    parts.append(command[copied_to:])
    return "".join(parts)


@dataclass
class _Frame:
    """One scanning context: where it opened, its paren depth, and for a
    backtick substitution the offset of its closing backtick."""

    context: str
    start: int = 0
    depth: int = 0
    end: int = -1


class _Scanner:
    """A context stack over the text: quotes, substitutions, expansions."""

    def __init__(self, text: str, *, start: int = 0, outer: _Frame | None = None) -> None:
        self._text = text
        self._index = start
        self._stack: list[_Frame] = [_Frame(_UNQUOTED)]
        if outer is not None:
            self._stack.append(outer)
        self._backticks: list[_Frame] = []
        self._pending: list[HeredocOperator] = []
        self.operators: list[HeredocOperator] = []
        self._continuations: set[int] = set()
        self._heredocs: list[Heredoc] = []
        self._breaks: list[int] = []
        self._stopped_at: int | None = None

    def run(self) -> HeredocScan:
        while self._step():
            pass
        return self._finish()

    def run_to_close(self) -> int | None:
        """Scan until the frame the scan started in closes; see
        :func:`substitution_end`."""
        outer = self._stack[1]
        while self._step():
            if all(frame is not outer for frame in self._stack):
                return None if self._stopped_at is not None else self._index
        return None

    def _step(self) -> bool:
        """Advance over one construct; False once the text is done with."""
        if self._index >= len(self._text):
            return False
        if self._backticks and self._index >= self._backticks[-1].end:
            innermost = self._backticks[-1]
            if self._stack[-1] is not innermost or self._index > innermost.end:
                self._leave_backtick_early(innermost)
                return True
        frame = self._stack[-1]
        if frame.context == _DOUBLE:
            return self._double_quoted(frame)
        return self._unquoted(frame)

    # -- stopping ----------------------------------------------------------

    def _stop(self, at: int) -> None:
        """Report nothing as a body from ``at`` on; see the module docstring."""
        self._stopped_at = at if self._stopped_at is None else min(self._stopped_at, at)
        self._pending = []

    def _leave_backtick_early(self, frame: _Frame) -> None:
        """Bash ended ``frame`` at its first unescaped backtick, and the scan
        reached it inside something else: resume after it, uncertain."""
        self._stop(frame.start)
        while self._stack[-1] is not frame:
            self._stack.pop()
        self._stack.pop()
        self._backticks.pop()
        self._index = frame.end + 1

    def _finish(self) -> HeredocScan:
        end = len(self._text)
        if len(self._stack) > 1:
            # An expansion, quote or substitution still open at the end: bash
            # reads on for its close, so nothing after its start is certain.
            self._stop(self._stack[1].start)
        heredocs = self._heredocs + [
            Heredoc(operator, end, end, end, terminated=False) for operator in self._pending
        ]
        breaks = self._breaks
        stopped_at = self._stopped_at
        if stopped_at is not None:
            heredocs = [heredoc for heredoc in heredocs if heredoc.closer_end <= stopped_at]
            later = (i for i in range(stopped_at, end) if self._text[i] == _NEWLINE)
            breaks = sorted({*(b for b in breaks if b < stopped_at), *later})
        return HeredocScan(heredocs, breaks, stopped_at, sorted(self._continuations))

    # -- contexts ----------------------------------------------------------

    def _double_quoted(self, frame: _Frame) -> bool:
        text, index = self._text, self._index
        char = text[index]
        if char == _BACKSLASH:
            if text.startswith(_CONTINUATION, index):
                self._continuations.add(index)
            self._index += 2
        elif char == '"':
            self._stack.pop()
            self._index += 1
        elif text.startswith(_PID, index):
            self._index += len(_PID)
        elif self._open_expansion(index):
            pass
        elif char == "`":
            return self._backtick(frame)
        else:
            self._index += 1
        return True

    def _unquoted(self, frame: _Frame) -> bool:
        text, index = self._text, self._index
        char = text[index]
        context = frame.context
        if char == _NEWLINE:
            return self._newline(frame)
        if char == _BACKSLASH:
            return self._backslash()
        if text.startswith(_PID, index):
            self._index += len(_PID)
            return True
        if text.startswith(_ANSI_C_OPEN, index):
            ansi_c = ansi_c_string(text, index + len(_ANSI_C_OPEN))
            if ansi_c is None:
                self._stop(index)
                return False
            self._add_quoted_continuations(index + len(_ANSI_C_OPEN), ansi_c[1], escapes=True)
            self._index = ansi_c[1]
            return True
        if char == "'":
            closing = text.find("'", index + 1)
            if closing < 0:
                self._stop(index)
                return False
            self._add_quoted_continuations(index + 1, closing, escapes=False)
            self._index = closing + 1
            return True
        if char == '"':
            self._stack.append(_Frame(_DOUBLE, index))
            self._index += 1
            return True
        if char == "#" and context in _COMMENT_FRAMES and self._starts_word(frame, index):
            self._comment(index)
            return True
        if char == "`":
            return self._backtick(frame)
        if self._open_expansion(index):
            return True
        if context == _PARAMETER:
            if char == "}":
                self._stack.pop()
            self._index += 1
            return True
        if context == _BRACKET:
            self._count(frame, char, "[", "]")
            self._index += 1
            return True
        if context == _ARITHMETIC:
            return self._arithmetic(frame, char)
        if char == "(":
            self._open_paren(frame)
            return True
        if char == ")" and context in _PAREN_FRAMES:
            self._count(frame, char, "(", ")")
            self._index += 1
            return True
        if char == "<" and context in _OPERATOR_FRAMES:
            return self._redirection(frame)
        self._index += 1
        return True

    def _open_expansion(self, index: int) -> bool:
        """Push the ``$((``, ``$(``, ``${`` or ``$[`` opening at ``index``."""
        text = self._text
        if text.startswith(_ARITHMETIC_OPEN, index):
            self._stack.append(_Frame(_ARITHMETIC, index, 2))
            self._index += len(_ARITHMETIC_OPEN)
        elif text.startswith(_SUBSTITUTION_OPEN, index):
            self._stack.append(_Frame(_SUBSTITUTION, index, 1))
            self._index += len(_SUBSTITUTION_OPEN)
        elif text.startswith(_PARAMETER_OPEN, index):
            self._stack.append(_Frame(_PARAMETER, index))
            self._index += len(_PARAMETER_OPEN)
        elif text.startswith(_BRACKET_OPEN, index):
            self._stack.append(_Frame(_BRACKET, index, 1))
            self._index += len(_BRACKET_OPEN)
        else:
            return False
        return True

    def _count(self, frame: _Frame, char: str, opener: str, closer: str) -> None:
        """Track nesting in ``frame``; pop it at its close."""
        if char == opener:
            frame.depth += 1
        elif char == closer:
            frame.depth -= 1
            if frame.depth == 0:
                self._stack.pop()

    def _arithmetic(self, frame: _Frame, char: str) -> bool:
        """``(`` and ``)`` in ``$(( ))`` or ``(( ))``; quotes stay live.

        A ``)`` that leaves one paren open with no second ``)`` after it means
        bash re-parses the text as subshells, and ran what we read as data.
        """
        text, index = self._text, self._index
        if char == "(":
            frame.depth += 1
        elif char == ")":
            frame.depth -= 1
            if frame.depth == 1:
                if text.startswith(")", index + 1):
                    self._stack.pop()
                    self._index += 2
                    return True
                self._stop(frame.start)
                frame.context = _SUBSTITUTION
        self._index += 1
        return True

    def _open_paren(self, frame: _Frame) -> None:
        text, index = self._text, self._index
        before = self._char_before(index)
        if (
            text.startswith(_BARE_ARITHMETIC_OPEN, index)
            and frame.context in _OPERATOR_FRAMES
            and (before == "" or before in _COMMAND_START_PRECEDERS)
        ):
            self._stack.append(_Frame(_ARITHMETIC, index, 2))
            self._index += len(_BARE_ARITHMETIC_OPEN)
            return
        if before != "" and before not in _METACHARACTERS:
            kind = _ARRAY if _ASSIGNMENT_WORD.match(self._word_before(index)) else _PATTERN
            self._stack.append(_Frame(kind, index, 1))
        elif frame.context in _PAREN_FRAMES:
            frame.depth += 1
        self._index += 1

    def _word_before(self, index: int) -> str:
        start = index
        while start > 0 and self._text[start - 1] not in _METACHARACTERS:
            start -= 1
        return self._text[start:index]

    def _starts_word(self, frame: _Frame, index: int) -> bool:
        if index == 0 or self._text[index - 1] in COMMENT_PRECEDERS:
            return True
        return frame.context == _BACKTICK and index - 1 == frame.start

    def _comment(self, index: int) -> None:
        """Skip a comment: to the newline, or to the backtick closing a
        substitution it sits in. A backslash-newline in it is kept."""
        end = self._text.find(_NEWLINE, index)
        end = len(self._text) if end < 0 else end
        if self._backticks:
            end = min(end, self._backticks[-1].end)
        self._index = end

    def _backtick(self, frame: _Frame) -> bool:
        if frame.context == _BACKTICK and self._index == frame.end:
            # Bash reads the substitution's text on its own: an operator
            # opened in it has an empty body there and none outside it
            # (bash 5.2 runs the lines after `x=`cat <<X`` as commands).
            self._pending = [op for op in self._pending if op.start < frame.start]
            self._stack.pop()
            self._backticks.pop()
            self._index += 1
            return True
        end = _verbatim_span_end(self._text, self._index)
        if end < 0:
            self._stop(self._index)
            return False
        opened = _Frame(_BACKTICK, self._index, end=end - 1)
        self._stack.append(opened)
        self._backticks.append(opened)
        self._index += 1
        return True

    # -- continuations -----------------------------------------------------

    def _backslash(self) -> bool:
        index = self._index
        if self._text.startswith(_CONTINUATION, index):
            if self._glues_a_token(index):
                self._stop(index)
            else:
                self._continuations.add(index)
        self._index += 2
        return True

    def _glues_a_token(self, index: int) -> bool:
        """Would removing the backslash-newline at ``index`` make a
        two-character token the raw text does not have?"""
        before = self._char_before(index)
        after = self._char_after_continuations(index + len(_CONTINUATION))
        if before == "$":
            return after != "" and after in _GLUE_AFTER_DOLLAR
        if before in ("(", "<"):
            return after == before
        return before != "" and before not in _METACHARACTERS and after in _GLUE_AFTER_WORD

    def _char_before(self, index: int) -> str:
        """The character bash sees before ``index``, past removed continuations."""
        cursor = index - 1
        while cursor >= 1 and (cursor - 1) in self._continuations:
            cursor -= len(_CONTINUATION)
        return self._text[cursor] if cursor >= 0 else ""

    def _char_after_continuations(self, index: int) -> str:
        while self._text.startswith(_CONTINUATION, index):
            index += len(_CONTINUATION)
        return self._text[index] if index < len(self._text) else ""

    def _add_quoted_continuations(self, start: int, end: int, *, escapes: bool) -> None:
        """Record the backslash-newlines in a quoted span, which bash keeps.

        Removing them moves no boundary and lets a pattern read ``'git
        pu\\⏎sh'`` handed to ``bash -c`` as the command it becomes. In an
        ANSI-C string ``\\\\`` is one escape, so pairs are walked.
        """
        text = self._text
        index = start
        while index < end:
            if text[index] == _BACKSLASH:
                if text.startswith(_CONTINUATION, index) and index + 1 < end:
                    self._continuations.add(index)
                index += 2 if escapes else 1
            else:
                index += 1

    # -- heredocs ----------------------------------------------------------

    def _newline(self, frame: _Frame) -> bool:
        """A command ends here at top level; any pending bodies start after it."""
        if self._pending and frame.context in _WORD_FRAMES:
            # Bash starts a pending body only once the word this newline sits
            # in is complete, which it may not be (bash 5.2 read
            # `cat <<X ${y:-a⏎b}` with the body after `b}`).
            self._stop(self._index)
        if len(self._stack) == 1:
            self._breaks.append(self._index)
        self._index += 1
        pending, self._pending = self._pending, []
        limit = self._backticks[-1].end if self._backticks else len(self._text)
        for position, operator in enumerate(pending):
            if position > 0 and self._text.startswith(_NEWLINE, self._index):
                # The next body starts on the line after the previous closer.
                self._index += 1
            heredoc = self._read_body(
                operator, inside_substitution=frame.context == _SUBSTITUTION, limit=limit
            )
            if heredoc is None:
                return True
            self._heredocs.append(heredoc)
            if not heredoc.terminated:
                # The rest of the text is this body; later operators get none.
                self._pending = pending[position + 1 :]
                self._index = len(self._text)
                return False
        return True

    def _read_body(
        self, operator: HeredocOperator, *, inside_substitution: bool, limit: int
    ) -> Heredoc | None:
        """Read one body from the cursor; None when the scan had to stop."""
        text = self._text
        body_start = cursor = self._index
        while cursor < limit:
            logical, line_end, joined = self._body_line(
                operator, cursor, limit, inside_substitution
            )
            candidate = logical.lstrip(_TAB) if operator.strip_tabs else logical
            if candidate == operator.delimiter:
                self._index = line_end
                return Heredoc(operator, body_start, cursor, line_end, terminated=True)
            if inside_substitution and candidate.startswith(
                operator.delimiter + _SUBSTITUTION_CLOSE
            ):
                if joined:
                    self._stop(operator.start)
                    self._index = line_end
                    return None
                closer_end = cursor + (len(logical) - len(candidate)) + len(operator.delimiter)
                self._index = closer_end
                return Heredoc(operator, body_start, cursor, closer_end, terminated=True)
            cursor = line_end + 1
        if limit < len(text):
            # A body still open where its backtick substitution ends.
            self._stop(operator.start)
            self._index = limit
            return None
        end = len(text)
        return Heredoc(operator, body_start, end, end, terminated=False)

    def _body_line(
        self, operator: HeredocOperator, cursor: int, limit: int, inside_substitution: bool
    ) -> tuple[str, int, bool]:
        """``(line bash compares, offset of its end, whether it joined lines)``.

        An unquoted body joins a line ending in an odd run of backslashes to
        the next, as bash does. A quoted body joins nothing, but each of its
        backslash-newlines is recorded for normalising unless removing it
        would change the closer. A line is cut at ``limit``.
        """
        text = self._text
        line_end = _line_end(text, cursor, limit)
        line = text[cursor:line_end]
        if operator.quoted:
            self._quoted_body_continuation(operator, cursor, line_end, limit, inside_substitution)
            return line, line_end, False
        parts = [line]
        joined = False
        while _odd_trailing_backslashes(parts[-1]) and line_end < limit:
            self._continuations.add(line_end - 1)
            parts[-1] = parts[-1][:-1]
            next_start = line_end + 1
            next_end = _line_end(text, next_start, limit)
            parts.append(text[next_start:next_end])
            line_end = next_end
            joined = True
        return "".join(parts), line_end, joined

    def _quoted_body_continuation(
        self,
        operator: HeredocOperator,
        cursor: int,
        line_end: int,
        limit: int,
        inside_substitution: bool,
    ) -> None:
        """Record the backslash-newline ending this quoted-body line, unless
        removing it would change which line closes the body."""
        text = self._text
        if not text.startswith(_CONTINUATION, line_end - 1) or line_end >= limit:
            return
        next_end = _line_end(text, line_end + 1, limit)
        # The normalised line this one belongs to: back over the lines
        # already joined into it.
        start = cursor
        while start >= 2 and (start - 2) in self._continuations:
            start = text.rfind(_NEWLINE, 0, start - 1) + 1
        joined = (text[start : line_end - 1] + text[line_end + 1 : next_end]).replace(
            _CONTINUATION, ""
        )
        next_line = text[line_end + 1 : next_end]

        def closes(line: str) -> bool:
            candidate = line.lstrip(_TAB) if operator.strip_tabs else line
            if candidate == operator.delimiter:
                return True
            return inside_substitution and candidate.startswith(
                operator.delimiter + _SUBSTITUTION_CLOSE
            )

        if not (closes(next_line) or closes(joined)):
            self._continuations.add(line_end - 1)

    def _redirection(self, frame: _Frame) -> bool:
        text, start = self._text, self._index
        cursor = start
        run = 0
        while cursor < len(text):
            if text[cursor] == "<":
                run += 1
                cursor += 1
            elif text.startswith(_CONTINUATION, cursor):
                self._continuations.add(cursor)
                cursor += len(_CONTINUATION)
            else:
                break
        self._index = cursor
        if run != len(_HEREDOC) or self._stopped_at is not None:
            return True
        strip_tabs = text.startswith(_STRIP_TABS, cursor)
        if strip_tabs:
            cursor += len(_STRIP_TABS)
        while cursor < len(text):
            if text[cursor] in _BLANKS:
                cursor += 1
            elif text.startswith(_CONTINUATION, cursor):
                self._continuations.add(cursor)
                cursor += len(_CONTINUATION)
            else:
                break
        # Inside backticks the closing backtick ends the word: bash has already
        # cut the substitution's text out before it reads the heredoc.
        terminators = _METACHARACTERS + ("`" if frame.context == _BACKTICK else "")
        word = self._read_word(cursor, terminators)
        if word is None:
            # The word runs into an unterminated quote, or holds something
            # whose extent the scanner does not model: nothing later can be
            # placed. The scan resumes after the `<<`.
            self._stop(start)
            return True
        delimiter, quoted, word_end = word
        if word_end == cursor:
            return True
        operator = HeredocOperator(start, word_end, delimiter, quoted, strip_tabs)
        self._pending.append(operator)
        self.operators.append(operator)
        self._index = word_end
        return True

    def _read_word(self, start: int, terminators: str) -> tuple[str, bool, int] | None:
        """``(delimiter, quoted, end)`` for the word at ``start``; None if
        left open or holding a ``${ }`` or ``$[ ]``."""
        text = self._text
        parts: list[str] = []
        quoted = False
        index = start
        while index < len(text) and text[index] not in terminators:
            char = text[index]
            if text.startswith(_CONTINUATION, index):
                self._continuations.add(index)
                index += len(_CONTINUATION)
            elif char == _BACKSLASH:
                if index + 1 >= len(text):
                    return None
                parts.append(text[index + 1])
                quoted = True
                index += 2
            elif text.startswith(_PID, index):
                parts.append(_PID)
                index += len(_PID)
            elif text.startswith(_PARAMETER_OPEN, index) or text.startswith(_BRACKET_OPEN, index):
                return None
            elif text.startswith(_ANSI_C_OPEN, index):
                ansi_c = ansi_c_string(text, index + len(_ANSI_C_OPEN))
                if ansi_c is None:
                    return None
                parts.append(ansi_c[0])
                quoted = True
                index = ansi_c[1]
            elif text.startswith(_LOCALE_OPEN, index) or char == '"':
                opener = len(_LOCALE_OPEN) if char == "$" else 1
                closing, inner, continuations = _double_quoted_span(text, index + opener)
                if closing < 0:
                    return None
                self._continuations.update(continuations)
                parts.append(inner)
                quoted = True
                index = closing + 1
            elif text.startswith(_SUBSTITUTION_OPEN, index) or char == "`":
                span_end = _verbatim_span_end(text, index)
                if span_end < 0 or _CONTINUATION in text[index:span_end]:
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
            else:
                parts.append(char)
                index += 1
        return "".join(parts), quoted, index


def _line_end(text: str, start: int, limit: int) -> int:
    """End of the line at ``start``; ``limit`` if it gets there first."""
    end = text.find(_NEWLINE, start, limit)
    return limit if end < 0 else end


def _odd_trailing_backslashes(line: str) -> bool:
    return (len(line) - len(line.rstrip(_BACKSLASH))) % 2 == 1


def _verbatim_span_end(text: str, start: int) -> int:
    """Index past the ``$( )``, ``$(( ))`` or backtick span at ``start``, or -1.

    Quotes inside a ``$( )`` span are skipped whole, so a ``)`` or a blank in
    them does not end it. A backtick span ends at the first unescaped
    backtick, as bash ends it, quotes or not.
    """
    if text[start] == "`":
        index = start + 1
        while index < len(text):
            if text[index] == _BACKSLASH:
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
        if char == _BACKSLASH or text.startswith(_PID, index):
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
            closing, _inner, _continuations = _double_quoted_span(text, index + 1)
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


def _double_quoted_span(text: str, start: int) -> tuple[int, str, list[int]]:
    """Index of the closing ``"`` (or -1), the text inside with escapes
    removed, and the backslash-newlines bash removed from it."""
    parts: list[str] = []
    continuations: list[int] = []
    index = start
    while index < len(text):
        char = text[index]
        if char == '"':
            return index, "".join(parts), continuations
        if (
            char == _BACKSLASH
            and index + 1 < len(text)
            and text[index + 1] in _DOUBLE_QUOTE_ESCAPABLE
        ):
            if text[index + 1] == _NEWLINE:
                continuations.append(index)
            else:
                parts.append(text[index + 1])
            index += 2
            continue
        parts.append(char)
        index += 1
    return -1, "", []
