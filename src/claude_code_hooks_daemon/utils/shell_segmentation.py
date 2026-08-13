"""Split a Bash command string into top-level segments.

Handlers that decide *what command is actually being run* need to know where one
command ends and the next begins, and must treat a separator inside a quoted
argument as DATA rather than syntax. Getting that wrong in either direction is a
real defect:

- split too eagerly and a quoted ``;`` cuts the producer in half, so a
  legitimate command is denied because its resolved name is a fragment;
- split too lazily and a separator is missed, so the guarded command inherits
  the leading word of a harmless one and the handler is bypassed.

This module exists because two handlers grew their own scanner and each got the
opposite half of the escape rule, producing the same bypass from opposite causes
(Plan 00200 Task 3.7). One scanner, one set of rules, one place to fix.

Deliberately a scanner, not a shell parser. Callers need boundaries and a
yes/no answer on whether a span can execute — never a full expansion.

Plan 00222 added the second of those, for the same reason the module exists at
all. ``git_message_backtick`` already encoded "bash substitutes inside DOUBLE
quotes"; ``pipe_blocker`` independently assumed the opposite, treating any
message value as inert prose, and so let a real pipe through inside
``git commit -m "$(pytest ... | tail -1)"``. Two handlers, one codebase,
contradicting each other about the shell. ``value_can_substitute`` is where
that fact now lives, once.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

# Bash quoting characters. Inside single quotes NOTHING is special except the
# closing quote -- in particular a backslash is a literal backslash, which is
# the rule a scanner that escapes everywhere gets wrong.
_SINGLE_QUOTE = "'"
_DOUBLE_QUOTE = '"'

# A backslash escapes exactly the next character, everywhere EXCEPT inside
# single quotes. A scanner blind to it flips its quote state on an escaped quote
# and never leaves quoted mode.
_ESCAPE_CHAR = "\\"

# Spans that make bash RUN something and substitute its output. Backticks are
# listed separately because the same character opens and closes them.
_SUBSTITUTION_OPENERS: tuple[str, ...] = ("$(", "<(", ">(")
_BACKTICK = "`"

# ``"$(cat <<'EOF' ... EOF)"`` -- the canonical multi-line message idiom.
#
# It contains ``$(``, so the opener test alone would call it executable. What
# makes it inert is the QUOTED delimiter: bash performs no expansion at all
# inside ``<<'EOF'``, so the body is literal text and the only thing that runs
# is ``cat``. An UNQUOTED ``<<EOF`` does expand and is deliberately unmatched.
#
# Scanning the body instead of recognising the idiom is not a safe fallback:
# newlines are segment separators, so the "command" before a pipe in the body
# resolves to a line of English prose (Plan 00200's false positive, rediscovered
# by Plan 00222's tests before it shipped).
_QUOTED_HEREDOC_PATTERN = re.compile(
    r"^\"\$\(\s*cat\s+<<-?\s*'(?P<delim>\w+)'.*\)\"$",
    re.DOTALL,
)

# The same bash fact as above, for a heredoc fed straight to a command's stdin
# rather than wrapped in an argument value: `git commit -F - <<'EOF' ... EOF`.
# Quoting the delimiter disables every expansion, so bash hands the body over
# verbatim and never parses it as shell syntax.
#
# The delimiter MUST be quoted. A bare `<<EOF` still expands `$(...)` and
# backticks, so its body can genuinely run a command and is deliberately left
# alone.
#
# DOTALL so the body may span newlines; non-greedy so the FIRST matching closing
# delimiter ends the body rather than the last one in the command.
_QUOTED_HEREDOC_BODY_PATTERN = re.compile(
    r"(?P<opener><<-?\s*(?P<quote>['\"])(?P<delim>\w+)(?P=quote))"
    r"\n.*?\n"
    r"(?P<closer>[ \t]*(?P=delim))",
    re.DOTALL,
)

# What a blanked body is replaced with: a single inert token that keeps the
# heredoc's shape (opener, one body line, closer) so a caller splitting on
# newlines still sees a well-formed command.
_INERT_BODY_PLACEHOLDER = "HEREDOC_BODY"


def value_can_substitute(value: str) -> bool:
    """Whether bash will EXECUTE something inside this quoted argument value.

    The question a handler actually needs before deciding that an argument is
    inert data. Quote class alone is the wrong test in both directions:

    * DOUBLE quotes do not stop substitution -- they stop word splitting. So
      ``"$(pytest ...)"`` runs pytest, and treating it as prose hides it.
    * SINGLE quotes stop substitution entirely, so a ``$(`` between them is
      literal text however executable it reads.

    What separates the cases is whether a substitution is present at all, which
    is why a rule phrased on quote class was tried and rejected: it re-breaks
    the deliberate allowance for double-quoted PROSE that merely mentions a
    pipe (Plan 00200).

    Args:
        value: The argument value INCLUDING its surrounding quotes, exactly as
            it appeared in the command. The quotes are the evidence.

    Returns:
        True if bash would run something inside ``value``.
    """
    if value.startswith(_SINGLE_QUOTE) and value.endswith(_SINGLE_QUOTE):
        return False
    if _QUOTED_HEREDOC_PATTERN.match(value):
        return False
    return _BACKTICK in value or any(opener in value for opener in _SUBSTITUTION_OPENERS)


def strip_quoted_heredoc_bodies(command: str) -> str:
    """Blank the body of every heredoc whose DELIMITER IS QUOTED.

    ``<<'EOF'`` and ``<<"EOF"`` disable every expansion, so bash hands the body
    to the receiving command verbatim and never parses it as shell syntax.
    Anything in that body — a pipe, a script name, a command that reads as
    dangerous — is DATA.

    Call this BEFORE splitting a command into segments. Newlines are segment
    separators, so a caller that splits first will chop the body into lines and
    judge each one as a command; the "command" before a pipe then resolves to a
    line of English prose. That is not hypothetical, it is the false positive
    this module's docstring already records for ``value_can_substitute``, and it
    recurred in ``enforce_llm_qa`` for the one heredoc shape that function does
    not cover (Plan 00234 finding H-3): a ``git commit -F - <<'EOF'`` message
    body that merely MENTIONED a guarded script was denied.

    An UNQUOTED ``<<EOF`` is deliberately NOT blanked: bash expands ``$(...)``
    and backticks inside it, so its body really can run something.

    Args:
        command: The raw Bash command string.

    Returns:
        ``command`` with each quoted-delimiter heredoc body replaced by a single
        inert placeholder line. The opener and closing delimiter are preserved,
        so the result still splits into well-formed segments.

    Examples:
        >>> strip_quoted_heredoc_bodies("git commit -F - <<'EOF'\\nrm -rf /\\nEOF")
        "git commit -F - <<'EOF'\\nHEREDOC_BODY\\nEOF"
        >>> strip_quoted_heredoc_bodies("echo hi")
        'echo hi'
    """
    return _QUOTED_HEREDOC_BODY_PATTERN.sub(
        lambda match: (
            f"{match.group('opener')}\n{_INERT_BODY_PLACEHOLDER}\n{match.group('closer')}"
        ),
        command,
    )


def split_unquoted(text: str, separators: Sequence[str]) -> list[str]:
    """Split ``text`` on ``separators`` that appear outside quotes.

    Args:
        text: The raw command string.
        separators: Separator strings to split on. Multi-character separators
            (``&&``, ``||``) are matched whole, so order them longest-first when
            one is a prefix of another.

    Returns:
        The segments, quote characters and escapes preserved verbatim so callers
        can pattern-match them. Always at least one element; separators
        themselves are not included.

    Examples:
        >>> split_unquoted("cd x\\ngrep y", (";", "\\n"))
        ['cd x', 'grep y']
        >>> split_unquoted('grep -E "a;b"', (";",))
        ['grep -E "a;b"']
    """
    segments: list[str] = []
    current: list[str] = []
    in_single = False
    in_double = False
    index = 0

    while index < len(text):
        char = text[index]

        # Rule 1: inside single quotes a backslash is literal, so escape
        # handling is skipped entirely and only the closing quote matters.
        if char == _ESCAPE_CHAR and not in_single:
            current.append(char)
            index += 1
            if index < len(text):
                current.append(text[index])
                index += 1
            continue

        if char == _SINGLE_QUOTE and not in_double:
            in_single = not in_single
        elif char == _DOUBLE_QUOTE and not in_single:
            in_double = not in_double
        elif not in_single and not in_double:
            matched = next((sep for sep in separators if text.startswith(sep, index)), None)
            if matched is not None:
                segments.append("".join(current))
                current = []
                index += len(matched)
                continue

        current.append(char)
        index += 1

    segments.append("".join(current))
    return segments
