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
#
# The opener line may carry MORE than the delimiter. A heredoc opener and an
# output redirect are independent redirections, so `cat > doc.md <<'EOF'` and
# `cat <<'EOF' > doc.md` are the same command and bash cares about neither
# order. Demanding a newline straight after the delimiter recognised only the
# first, and an unrecognised heredoc is not a near miss: the body is scanned as
# shell, so a paragraph of prose gets split on newlines and judged command by
# command. Which of two identical commands got denied depended on word order.
#
# The delimiter charset is wider than `\w+` for the same reason -- `'EOF-1'`
# and `'END.MD'` are ordinary and legal, and an unmatched delimiter exposes the
# whole body. The closer then needs the lookahead: without it `EOF` is closed
# by a body line reading `EOFDATA`, ending the body early and scanning the rest.
_QUOTED_HEREDOC_BODY_PATTERN = re.compile(
    r"(?P<opener><<-?\s*(?P<quote>['\"])(?P<delim>[\w.\-]+)(?P=quote))"
    r"(?P<opener_tail>[^\n]*)\n.*?\n"
    r"(?P<closer>[ \t]*(?P=delim)(?![\w.\-]))",
    re.DOTALL,
)

# What a blanked body is replaced with: a single inert token that keeps the
# heredoc's shape (opener, one body line, closer) so a caller splitting on
# newlines still sees a well-formed command.
_INERT_BODY_PLACEHOLDER = "HEREDOC_BODY"

# Separators that end one command and start the next, used to find which
# command a heredoc opener actually belongs to. Longest-first: `||` must be
# matched whole before the single `|` can claim its first character.
_RECEIVER_SEPARATORS: tuple[str, ...] = ("&&", "||", ";", "|", "&")

#: Grouping and escaping characters bash strips off the front of a command
#: word while deciding what command it names. `(` and `{` open a subshell or
#: brace group, `` ` `` and `$` open a substitution, `\` escapes the next
#: character -- in none of these does the punctuation belong to the command's
#: name.
_WORD_GROUPING_PREFIXES = "(){}`\\$"

#: Words that PREFIX a command without being it, so the command word sits
#: further along: `sudo -E tee f` names tee. Only consulted by
#: `quoted_heredoc_command_words`, whose caller matches against an allowlist
#: of SAFE names -- skipping sudo cannot hide anything there, because what it
#: reveals (`sudo -E bash` -> `bash`) is not on such a list either.
#: `quoted_heredoc_receivers` must NOT use this: its caller matches against
#: DANGEROUS names, where reporting only `sudo` would hide the interpreter.
_COMMAND_WORD_PREFIXES: frozenset[str] = frozenset({"sudo"})


#: Matches a `-m`/`--message`/`-F`/`--file` flag immediately followed by its
#: VALUE, so the value can be excluded from a command scan. Three value shapes,
#: tried in order (DOTALL so `.` spans newlines, needed for the heredoc
#: alternative's body):
#:   1. The canonical heredoc-embedded message idiom: -m "$(cat <<'EOF' … EOF)"
#:      (leading whitespace before the closing delimiter is tolerated — messages
#:      are often re-indented).
#:   2. A single- or double-quoted string (may span literal newlines).
#:   3. A bare word (e.g. `-F commit-msg.txt`) as a fallback.
_MESSAGE_BODY_PATTERN = re.compile(
    r"(?P<flag>(?<![\w-])(?:-m|--message|-F|--file))"
    r"(?P<sep>=|\s+)"
    r"(?P<value>"
    r"\"\$\(cat\s+<<-?\s*'?(?P<delim>\w+)'?\s*\n.*?\n[ \t]*(?P=delim)[ \t]*\n?\s*\)\""
    r"|'(?:[^'\\]|\\.)*'"
    r'|"(?:[^"\\]|\\.)*"'
    r"|\S+"
    r")",
    re.DOTALL,
)

#: What an inert message value is replaced with.
_MESSAGE_BODY_PLACEHOLDER = "<REDACTED>"

#: Commands whose `-m`/`--message`/`-F`/`--file` argument is human-authored
#: PROSE rather than an operand (Plan 00222). Scoping is required because the
#: same spelling means something else elsewhere: `python -m <module>` names a
#: MODULE, and blanking it reported the producer of `python -m pytest … | tail`
#: as the redaction placeholder — a remediation the caller cannot run.
_MESSAGE_TAKING_COMMANDS: tuple[str, ...] = ("git", "hg", "svn", "jj")

#: Separators that end one command and start the next, for attributing a flag
#: to the command word that owns it.
_CHAIN_SEPARATORS: tuple[str, ...] = ("&&", "||", ";", "\n")

#: Path separator, for reducing `/usr/bin/git` to `git` before comparison.
_PATH_SEPARATOR = "/"

#: Where a top-level scan starts when no earlier separator is found.
_SEGMENT_START = 0


def _segment_binary(command: str, index: int) -> str:
    """Basename of the command word that owns the flag at ``index``.

    Bounded by chain separators so a `git commit` earlier in the line cannot
    lend its message-taking status to a later `python -m` in the same command.
    """
    start = _SEGMENT_START
    for separator in _CHAIN_SEPARATORS:
        found = command.rfind(separator, _SEGMENT_START, index)
        if found != -1:
            start = max(start, found + len(separator))
    words = command[start:index].split()
    if not words:
        return ""
    return words[0].rpartition(_PATH_SEPARATOR)[2]


def _command_word(word: str) -> str:
    """The command name bash would resolve ``word`` to.

    Quoting is a property of the SHELL SYNTAX, not of the command being named:
    ``"bash"``, ``'bash'``, ``ba"sh"``, ``\\bash`` and ``(bash`` all invoke
    bash. A caller comparing a receiver against a list of interpreter names has
    to compare what bash resolves, or the list is defeated by punctuation that
    changes nothing about what runs.

    Reducing only the basename -- the previous behaviour -- made this helper
    UNDER-report, which grants an exemption. That inverts the safe direction
    its own contract promises: over-reporting withholds an exemption, and
    withholding is the cheap error.
    """
    unquoted = word.replace('"', "").replace("'", "")
    return unquoted.lstrip(_WORD_GROUPING_PREFIXES).rsplit("/", 1)[-1]


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


def strip_message_bodies(command: str) -> str:
    """Blank every ``-m``/``--message``/``-F``/``--file`` VALUE bash cannot run.

    These flags carry human-authored prose — a commit/tag message, or a path to
    one — never shell syntax to execute. A guarded construct sitting in that
    prose is DATA, and a handler that scans the raw string reads it as a
    command: the field report for Plan 00377 N7 is a commit message describing
    a ``--force`` flag, denied as though it were a force push.

    Two conditions gate the blanking, both from Plan 00222, each added after the
    unconditional form was measured to be wrong in the opposite direction:

    * the owning command must actually TAKE a message, so ``python -m
      <module>`` keeps naming a module rather than a redaction placeholder, and
    * the value must not be able to execute — bash substitutes inside double
      quotes, so blanking ``"$(...)"`` would CONCEAL a live command.

    A value failing either test is returned untouched and scanned normally.

    Args:
        command: The raw Bash command string.

    Returns:
        ``command`` with each inert message value replaced by a placeholder.
        Everything else, including a real command beside the message, is
        untouched.
    """

    def _blank_if_inert(match: re.Match[str]) -> str:
        if _segment_binary(command, match.start()) not in _MESSAGE_TAKING_COMMANDS:
            return match.group(0)
        if value_can_substitute(match.group("value")):
            return match.group(0)
        return f"{match.group('flag')}{match.group('sep')}{_MESSAGE_BODY_PLACEHOLDER}"

    return _MESSAGE_BODY_PATTERN.sub(_blank_if_inert, command)


def strip_inert_spans(command: str) -> str:
    """Blank every span bash will hand over as data rather than execute.

    The composition of :func:`strip_message_bodies` and
    :func:`strip_quoted_heredoc_bodies` — the scan target a handler should
    judge when it is asking "what command is being run?".

    Both halves are required, and that is measured rather than assumed: for
    Plan 00377 N7, blanking only the heredoc cleared the reported command while
    leaving an ordinary one-line ``git commit -m 'document --amend'`` still
    denied, because the single-line patterns match inside the message value.

    Args:
        command: The raw Bash command string.

    Returns:
        ``command`` with inert message values and quoted-heredoc bodies blanked.
    """
    return strip_quoted_heredoc_bodies(strip_message_bodies(command))


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
    # ``opener_tail`` is kept, not dropped: it holds whatever else the opener
    # line carried, and that is usually a REDIRECT (`cat <<'EOF' > doc.md`).
    # Erasing it would hide the destination from every caller that judges the
    # blanked command -- blanking a body must remove no evidence but the body.
    return _QUOTED_HEREDOC_BODY_PATTERN.sub(
        lambda match: (
            f"{match.group('opener')}{match.group('opener_tail')}"
            f"\n{_INERT_BODY_PLACEHOLDER}\n{match.group('closer')}"
        ),
        command,
    )


def quoted_heredoc_receivers(command: str) -> list[str]:
    """Return the command words each quoted-delimiter heredoc is fed to.

    ``strip_quoted_heredoc_bodies`` blanks a body because bash never PARSES
    it. That is the whole truth when the receiver treats the bytes as data —
    ``git commit -F -``, ``cat > file`` — but NOT when the receiver is an
    interpreter: ``bash <<'EOF'`` executes the body regardless of the quoting,
    which only governs what the OUTER shell expands on the way in. A caller
    blanking bodies for a safety decision would otherwise hand out a clean
    bypass, so it needs to know who is on the receiving end.

    The interpreter policy deliberately stays with the caller; different
    handlers guard different interpreter sets, and this module judges nothing.

    Every word of the receiving command is returned, not just the first,
    because ``sudo -E bash <<'EOF'`` genuinely feeds bash and reporting only
    ``sudo`` would hide it. Words are reduced to their basename so ``/bin/sh``
    and ``sh`` compare equal. The consequence is intentional over-reporting: a
    redirect target that happens to be named like an interpreter is reported
    too. For a caller deciding whether to WITHHOLD an exemption that is the
    safe direction — it withholds one, it never grants one.

    An UNQUOTED ``<<EOF`` is not reported: it is not blanked either, so there
    is no exemption to guard.

    Args:
        command: The raw Bash command string.

    Returns:
        Basenames of the words making up each quoted heredoc's receiving
        command, in the order the heredocs appear. Empty if there are none.

    Examples:
        >>> quoted_heredoc_receivers("git commit -F - <<'MSG'\\nbody\\nMSG")
        ['git']
        >>> quoted_heredoc_receivers("/bin/sh <<'EOF'\\nbody\\nEOF")
        ['sh']
    """
    receivers: list[str] = []
    for segment in _heredoc_receiving_segments(command):
        receivers.extend(
            _command_word(word) for word in segment.split() if word and not word.startswith("-")
        )
    return receivers


def _heredoc_receiving_segments(command: str) -> list[str]:
    """Return the command segment feeding each quoted heredoc, in order.

    The receiving command is what sits between the previous separator and the
    ``<<`` opener -- a pipe stage or an ``&&`` branch, not the whole line, so
    ``echo x | bash <<'EOF'`` resolves to bash rather than echo.
    """
    segments: list[str] = []
    for match in _QUOTED_HEREDOC_BODY_PATTERN.finditer(command):
        preceding = command[: match.start("opener")]
        last_line = preceding.rsplit("\n", 1)[-1]
        segments.append(split_unquoted(last_line, _RECEIVER_SEPARATORS)[-1])
    return segments


def quoted_heredoc_command_words(command: str) -> list[str]:
    """Return the single command word feeding each quoted heredoc.

    The allowlist counterpart to ``quoted_heredoc_receivers``. That function
    reports EVERY word so a caller matching against a list of DANGEROUS names
    cannot be fooled by ``sudo -E bash`` hiding the interpreter behind sudo.
    A caller matching against a list of SAFE names needs the opposite shape:
    the one word that names the command, because an argument is not the
    receiver and must not be asked to satisfy the allowlist. ``git commit -F -``
    would otherwise fail on ``commit`` and ``jq -r .`` on ``.``.

    ``sudo`` is skipped so ``sudo -E tee f`` resolves to ``tee``. That cannot
    hide anything from an allowlist caller: ``sudo -E bash`` resolves to
    ``bash``, which no list of data sinks contains, so the exemption is
    withheld either way.

    A word built by EXPANSION (``$SHELL``, ``b$'ash'``) is reported as-is --
    resolving it would mean running the command the caller exists to judge.
    For an allowlist caller that needs no special handling: an unresolvable
    word simply fails to match, which is the safe direction. This is why the
    unbounded expansion family needs no normalisation here.

    Args:
        command: The raw Bash command string.

    Returns:
        One command-word basename per quoted heredoc, in the order the
        heredocs appear. Empty if there are none.

    Examples:
        >>> quoted_heredoc_command_words("git commit -F - <<'MSG'\\nbody\\nMSG")
        ['git']
        >>> quoted_heredoc_command_words("sudo -E bash <<'EOF'\\nbody\\nEOF")
        ['bash']
    """
    command_words: list[str] = []
    for segment in _heredoc_receiving_segments(command):
        for word in segment.split():
            if not word or word.startswith("-"):
                continue
            resolved = _command_word(word)
            # An EMPTY resolution means the word was pure grouping punctuation
            # (`{`, `(`), which `_WORD_GROUPING_PREFIXES` strips entirely. It
            # names no command, so accepting it as the command word matched ''
            # against the caller's allowlist, failed, and denied an ordinary
            # `{ cat <<'DOC' ... } > doc.md`. Skipping it looks at the next
            # word instead, which is the actual receiver -- so `( bash <<'X'`
            # still resolves to `bash` and still withholds the exemption.
            if not resolved or resolved in _COMMAND_WORD_PREFIXES:
                continue
            command_words.append(resolved)
            break
    return command_words


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
