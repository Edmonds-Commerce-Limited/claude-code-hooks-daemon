"""The text of a Bash command that sits in COMMAND position (ledger N241).

`git_stash` and `destructive_git` ask "does this command run a stash / a hard
reset?". Scanning the raw string answers a different question, "does the text
contain those words?", and denies `git commit -m 'document the git stash
guard'`, `grep -n 'git stash' notes.md` and `echo 'do not run git reset
--hard'`.

Governing ruling: CLAUDE/ARCHITECTURE.md, "Threat model: the agent is careless,
not hostile". Ordinary commands, including a literal `bash -c '...'` body, are
in scope; a shape whose operative text is not visible (a variable, `eval` of a
variable) is not. A false positive on ordinary work is fixed by NARROWING the
matcher, so this module removes only text that cannot run:

* a `-m`/`-F` message value and a quoted-heredoc body fed to a data sink
  (:func:`strip_inert_spans`);
* the arguments of a command that only prints or searches them
  (:data:`DATA_HEADS`), unless an expansion in them could run something or the
  pipeline carries the output to any stage that is not a known inert sink;
* a `gh pr|issue|release` title, body or notes value;
* and, inside a literal `bash -c '<body>'`, the same rules applied to the body.

A command that writes a file and then runs that same path (`echo '...' > s.sh
&& bash s.sh`, a heredoc written then sourced) is left untouched whole: the
text written IS the script.

Everything else is left exactly as written, so a segment this module cannot
read is judged as before: a false positive, never a bypass.
"""

from __future__ import annotations

import re
from itertools import pairwise

from claude_code_hooks_daemon.utils.command_evasion import (
    GitGrepRole,
    git_grep_word_roles,
    git_subcommand_index,
    strip_reserved_word_prefix,
)
from claude_code_hooks_daemon.utils.shell_segmentation import (
    DATA_SINKS,
    is_inert_pipeline_stage,
    resolve_shell_word,
    segment_command_chain,
    shell_word_spans,
    split_unquoted_spans,
    strip_inert_spans,
)

#: Separators that end one command and start the next. Longest first, so `&&`
#: and `||` match whole. A lone `&` and a newline end a command too, and
#: leaving either out would let `echo hi & git stash` read as one data segment.
SEGMENT_SEPARATORS: tuple[str, ...] = ("&&", "||", "|", "&", ";", "\n")

#: Commands that print or search their arguments and never run them. An
#: ALLOWLIST: a missing entry costs a false positive, a wrong entry costs a guard.
DATA_HEADS: frozenset[str] = frozenset({"echo", "printf", "grep", "egrep", "fgrep", "rg"})

#: The subset of :data:`DATA_HEADS` that only SEARCHES its arguments. A guard that
#: keeps judging a wrapped or rebound `echo`/`printf` can still opt into blanking
#: just these, via the ``data_heads`` argument of :func:`command_position_view`.
SEARCH_HEADS: frozenset[str] = frozenset({"grep", "egrep", "fgrep", "rg"})

#: Shells that run the string given to `-c`.
SHELL_NAMES: frozenset[str] = frozenset({"bash", "sh", "zsh", "dash", "ksh"})

#: `rg --pre CMD` runs CMD on every file, so an `rg` carrying it is not data.
_RG_PREPROCESSOR = "--pre"

#: Redirect operators whose `&` is part of the operator, not a separator:
#: `2>&1`, `>&2`, `<&3`, `&>f`, `&>>f`.
_REDIRECT_AMPERSAND = re.compile(r"[<>]&|(?<!&)&>>?")

#: A redirect to a file, as one word: `>`, `>>`, `2>`, or with the path attached.
_REDIRECT_TARGET = re.compile(r"[0-9]*>>?(?P<path>[^&>].*)?")

#: An unquoted word with no shell syntax: no expansion, glob, escape, comment,
#: group or redirect character.
_PLAIN_WORD = re.compile(r"[A-Za-z0-9_./:@=+,%-]+")

#: Characters that stay live inside double quotes, or that bash treats specially there.
_DOUBLE_QUOTE_ACTIVE: tuple[str, ...] = ('"', "$", "`", "\\", "!", "\n")

#: Commands that run a file's text in the current shell.
SOURCE_HEADS: frozenset[str] = frozenset({"source", "."})

#: What replaces the arguments of a data segment.
_DATA_PLACEHOLDER = "_"

#: Characters that make an argument something bash computes rather than reads.
_EXPANSION_MARKERS: tuple[str, ...] = ("$", "`", "<(", ">(")

#: `gh` subcommands whose title/body/notes values are human prose.
_GH_PROSE_SUBCOMMANDS: frozenset[str] = frozenset({"pr", "issue", "release"})
_GH_PROSE_FLAGS: frozenset[str] = frozenset({"--title", "--body", "--notes", "-t", "-b", "-n"})

#: Commands that run what follows as root; a shell they run elevates its whole `-c` body.
_ELEVATORS: frozenset[str] = frozenset({"sudo", "doas"})
_ELEVATOR_PREFIX = "sudo "

#: How deep a `bash -c` body is read inside another.
_MAX_NESTING = 3

_PIPE = "|"


def _segment_spans(text: str) -> list[tuple[int, int]]:
    """Offsets of the command segments of ``text``.

    A redirect's `&` is masked for the split only (same length, so the offsets
    still index ``text``): `echo x 2>&1 | bash` is ONE pipeline, not two
    commands joined by a background operator.
    """
    masked = _REDIRECT_AMPERSAND.sub(lambda match: match.group().replace("&", "_"), text)
    return split_unquoted_spans(masked, SEGMENT_SEPARATORS, comments_end_at_newline=True)


def segment_spans(text: str) -> list[tuple[int, int]]:
    """Offsets of the command segments of ``text``, for a caller that needs the
    positions rather than the redacted view (the message text stays in
    ``text``, so it can still be read)."""
    return _segment_spans(text)


def _normalise_path(path: str) -> str:
    """``path`` without leading `./`, so `./s.sh` and `s.sh` compare equal."""
    while path.startswith("./"):
        path = path[2:]
    return path


def _written_paths(words: list[str | None]) -> set[str]:
    """Paths one segment writes: `> p`, `>> p`, `>p` and the operands of `tee`."""
    paths: set[str] = set()
    for index, word in enumerate(words):
        if word is None:
            continue
        match = _REDIRECT_TARGET.fullmatch(word)
        if match is None:
            continue
        target = match.group("path") or (words[index + 1] if index + 1 < len(words) else None)
        if target:
            paths.add(_normalise_path(target))
    if words and words[0] is not None and words[0].rsplit("/", 1)[-1] == "tee":
        paths.update(
            _normalise_path(word) for word in words[1:] if word and not word.startswith("-")
        )
    return paths


def _executed_path(words: list[str | None], written: set[str]) -> str | None:
    """The path one segment runs as a script, if it names a written one."""
    if not words or words[0] is None:
        return None
    head = words[0].rsplit("/", 1)[-1]
    if head in SHELL_NAMES or head in SOURCE_HEADS:
        operands = [word for word in words[1:] if word is None or not word.startswith("-")]
        candidate = operands[0] if operands else None
    else:
        candidate = words[0]
    if candidate is None:
        return None
    candidate = _normalise_path(candidate)
    return candidate if candidate in written else None


#: A redirect operator inside one unquoted word: `sh<s.sh`, `x>s.sh`, `0<s.sh`.
#: A leading file-descriptor number belongs to the operator only at the word's start.
_ATTACHED_REDIRECT = re.compile(r"((?:(?<!\S)[0-9]+)?(?:<<<|<<|<&|&>>|&>|>>|>&|<|>))")

#: Characters that make a word quoted, escaped or computed, so it is not split.
_UNSPLITTABLE_WORD_CHARS: tuple[str, ...] = ("'", '"', "\\", "$", "`", "(")

#: A redirect of stdin from a file: `<`, `0<`, or either with the path attached.
_STDIN_REDIRECT = re.compile(r"0?<(?P<path>[^<&(].*)?")

#: Any redirect operator word, with or without its path attached.
_ANY_REDIRECT = re.compile(r"[0-9]*(?:<<<|<<|<&|>>|>&|&>>|&>|<|>)(?P<path>.*)")

#: Wrappers that run the command after them in the same process, and the
#: options of each that take the next word as their value.
_PASS_THROUGH_WRAPPERS: dict[str, frozenset[str]] = {
    "exec": frozenset({"-a"}),
    "env": frozenset({"-u", "-C", "-S", "--unset", "--chdir", "--split-string"}),
    "command": frozenset(),
    "builtin": frozenset(),
}

#: Commands that copy or move their source operands onto the last operand.
_COPY_HEADS: frozenset[str] = frozenset({"cp", "mv"})

#: Shell options that take the next word as their value.
_SHELL_OPTIONS_WITH_VALUE: frozenset[str] = frozenset({"-o", "+o", "-O", "+O"})

#: Script operands that still mean "read the program from stdin".
_STDIN_OPERANDS: frozenset[str] = frozenset({"/dev/stdin", "-"})

#: Prefixes that run the builtin after them unchanged: `builtin printf`, `command printf`.
_BUILTIN_PREFIXES: frozenset[str | None] = frozenset({"builtin", "command"})

#: An expansion of a named variable, capturing the name.
_VARIABLE_REFERENCE = re.compile(r"\$\{?[!#]?([A-Za-z_][A-Za-z0-9_]*)")

#: A variable assignment word ahead of a command: `A=1 sh`.
_ASSIGNMENT_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=.*")


def _split_attached_redirects(raw: str) -> list[str]:
    """``raw`` cut at each redirect operator, when it is a plain unquoted word."""
    if any(char in raw for char in _UNSPLITTABLE_WORD_CHARS) or not ("<" in raw or ">" in raw):
        return [raw]
    return [piece for piece in _ATTACHED_REDIRECT.split(raw) if piece]


def _segment_words(segment: str) -> list[str | None]:
    """The resolved words of one segment, each attached redirect split off."""
    words: list[str | None] = []
    for start, end in shell_word_spans(segment):
        for piece in _split_attached_redirects(segment[start:end]):
            words.append(resolve_shell_word(piece))
    return words


def _command_words(words: list[str | None]) -> list[str | None]:
    """``words`` without redirects, leading assignments and pass-through wrappers.

    `< s.sh exec env A=1 sh -e` is the shell `sh -e`.
    """
    plain: list[str | None] = []
    index = 0
    while index < len(words):
        word = words[index]
        match = None if word is None else _ANY_REDIRECT.fullmatch(word)
        if match is not None:
            index += 1 if match.group("path") else 2
            continue
        plain.append(word)
        index += 1
    while plain and plain[0] is not None and _ASSIGNMENT_WORD.fullmatch(plain[0]):
        plain = plain[1:]
    while plain and plain[0] is not None and plain[0] in _PASS_THROUGH_WRAPPERS:
        valued = _PASS_THROUGH_WRAPPERS[plain[0]]
        index = 1
        while index < len(plain):
            word = plain[index]
            if word is None:
                return plain[index:]
            if word in valued:
                index += 2
            elif word.startswith("-") or (plain[0] == "env" and _ASSIGNMENT_WORD.fullmatch(word)):
                index += 1
            else:
                break
        plain = plain[index:]
    return plain


def _stdin_paths(words: list[str | None]) -> set[str]:
    """Paths one segment feeds on stdin: `< p`, `0< p`, `<p`, and the operands of `cat`."""
    paths: set[str] = set()
    for index, word in enumerate(words):
        match = None if word is None else _STDIN_REDIRECT.fullmatch(word)
        if match is None:
            continue
        target = match.group("path") or (words[index + 1] if index + 1 < len(words) else None)
        if target:
            paths.add(_normalise_path(target))
    command = _command_words(words)
    if command and command[0] is not None and command[0].rsplit("/", 1)[-1] == "cat":
        paths.update(
            _normalise_path(word) for word in command[1:] if word and not word.startswith("-")
        )
    return paths


def _reads_shell_input(command: list[str | None]) -> bool:
    """Whether a command (:func:`_command_words`) is a shell that RUNS its stdin.

    Not when it runs a `-c` string or a script operand other than `/dev/stdin`
    or `-` (`bash build.sh < s.sh` runs build.sh), nor under `-n`, which only
    checks the syntax. Under `-s` every operand is a positional argument. A
    word that cannot be read is taken as a script operand.
    """
    if not command or command[0] is None or command[0].rsplit("/", 1)[-1] not in SHELL_NAMES:
        return False
    index = 1
    while index < len(command):
        word = command[index]
        if word is None:
            return False
        if word == "--":
            index += 1
            break
        if word in _SHELL_OPTIONS_WITH_VALUE:
            index += 2
            continue
        if not word.startswith(("-", "+")) or word == "-":
            break
        if not word.startswith("--"):
            if is_shell_command_option(word) or "n" in word[1:]:
                return False
            if "s" in word[1:]:
                return True
        index += 1
    return index >= len(command) or command[index] in _STDIN_OPERANDS


def _copied_paths(command: list[str | None], written: set[str]) -> set[str]:
    """The destination of a `cp`/`mv` whose source is a written path."""
    if not command or command[0] is None or command[0].rsplit("/", 1)[-1] not in _COPY_HEADS:
        return set()
    operands = [word for word in command[1:] if word is None or not word.startswith("-")]
    if len(operands) < 2 or operands[-1] is None:
        return set()
    sources = {_normalise_path(word) for word in operands[:-1] if word is not None}
    return {_normalise_path(operands[-1])} if sources & written else set()


def _runs_written_script(command: str) -> bool:
    """Whether a segment runs a path an EARLIER segment of ``command`` wrote.

    `echo 'git stash' > s.sh && bash s.sh` runs the text of the echo, so that
    text is a command however a data head would otherwise be read. So does a
    shell fed the file on stdin: `sh < s.sh`, or `cat s.sh | sh` (along the
    `|` stages only; a `;`, `&&` or `||` feeds nothing). A
    `cp`/`mv` of a written path writes its destination. Paths are compared
    textually, so a path the shell computes is not matched; the caller then
    judges the whole command exactly as written.
    """
    written: set[str] = set()
    feeds_next = False
    previous_end: int | None = None
    for start, end in _segment_spans(command):
        fed = feeds_next and previous_end is not None and command[previous_end:start] == _PIPE
        words = _segment_words(command[start:end])
        plain = _command_words(words)
        if _executed_path(plain, written) is not None:
            return True
        stdin = _stdin_paths(words)
        if _reads_shell_input(plain) and (fed or stdin & written):
            return True
        feeds_next = fed or bool(stdin & written)
        written |= _written_paths(words) | _copied_paths(plain, written)
        previous_end = end
    return False


def command_position_view(
    command: str,
    _depth: int = 0,
    _keep_text: bool = False,
    data_heads: frozenset[str] = DATA_HEADS,
) -> str:
    """``command`` with every span that cannot run replaced by a placeholder.

    ``data_heads`` names the heads whose arguments are blanked; an opt-in
    narrower set (:data:`SEARCH_HEADS`) leaves the others judged as written.

    ``_keep_text`` is set for a `-c` body whose own output a pipeline may run:
    the git/awk search literals in it are then left as written.
    """
    if _runs_written_script(command):
        return command
    stripped = strip_inert_spans(command)
    spans = _segment_spans(stripped)
    segments = [stripped[start:end] for start, end in spans]
    expanded = _expanded_names(command)
    pieces: list[str] = []
    previous_end = 0
    for index, (start, end) in enumerate(spans):
        pieces.append(stripped[previous_end:start])
        may_run_output = _pipeline_may_run_output(stripped, spans, segments, index)
        pieces.append(
            _narrow(segments[index], may_run_output, _depth, _keep_text, data_heads, expanded)
        )
        previous_end = end
    pieces.append(stripped[previous_end:])
    return "".join(pieces)


def is_plain_data_command(command: str) -> bool:
    """Whether ``command`` is ONE bare `echo`/`printf`/`grep`/`rg` over plain words.

    The words are quoted literals or plain unquoted ones, and the only
    redirect is a `>`/`>>` to a plain file path. Nothing in such a command can
    run its text: no second segment, no expansion, no pipe, no `-v` assignment,
    no `--pre`. It is stricter than the data-head blanking of
    :func:`command_position_view` on purpose, for the guards that deliberately
    keep judging every shape this function does not vouch for (an alias, a
    wrapper before the head, an fd redirect, a glob).
    """
    spans = _segment_spans(command)
    if len(spans) != 1 or command[: spans[0][0]].strip() or command[spans[0][1] :].strip():
        return False
    start, end = spans[0]
    segment = command[start:end]
    word_spans = shell_word_spans(segment)
    # The word reader stops at syntax it cannot place (`$(`, an open quote), so
    # text between or after the words it did return means it did not see it all.
    gaps = [segment[: word_spans[0][0]] if word_spans else segment]
    gaps += [segment[a[1] : b[0]] for a, b in pairwise(word_spans)]
    gaps.append(segment[word_spans[-1][1] :] if word_spans else "")
    if any(gap.strip(" \t") for gap in gaps):
        return False
    raw = [segment[a:b] for a, b in word_spans]
    if not raw or raw[0] not in DATA_HEADS or (raw[0] == "rg" and _has_rg_preprocessor(segment)):
        return False
    is_printf = raw[0] == "printf"
    index = 1
    while index < len(raw):
        word = raw[index]
        index += 1
        redirect = _REDIRECT_TARGET.fullmatch(word)
        if redirect is not None:
            target = redirect.group("path")
            if target is None:
                if index >= len(raw):
                    return False
                target, index = raw[index], index + 1
            if not _PLAIN_WORD.fullmatch(target):
                return False
        elif not _is_plain_data_word(word, is_printf):
            return False
    return True


def _is_plain_data_word(word: str, is_printf: bool) -> bool:
    """A quoted literal that cannot expand, or an unquoted word with no shell syntax."""
    if len(word) >= 2 and word[0] == word[-1] == "'":
        body = word[1:-1]
        return "'" not in body and "\n" not in body
    if len(word) >= 2 and word[0] == word[-1] == '"':
        body = word[1:-1]
        return not any(char in body for char in _DOUBLE_QUOTE_ACTIVE)
    if is_printf and word.startswith("-"):
        return False
    return _PLAIN_WORD.fullmatch(word) is not None


def command_position_segments(command: str) -> list[str]:
    """The command-position view, split into its command segments.

    Split AFTER narrowing so a body read out of `bash -c '...'` is judged
    segment by segment too: `bash -c 'git stash list; git stash'` is two
    commands.
    """
    view = command_position_view(command)
    return [view[start:end] for start, end in _segment_spans(view)]


def without_comment(segment: str) -> str:
    """``segment`` up to the first word that starts a shell comment.

    The segment splitter keeps comment text as a command on purpose (the
    conservative reading), so a guard that matches ONE command's own words
    cuts the comment off first: `true # sudo pip install x` runs `true`.

    Only the guards that call this (pip_break_system, sudo_pip and the gh view
    comment guards) cut comments; git_stash and destructive_git still judge
    comment text as commands.
    """
    for start, _end in shell_word_spans(segment):
        if segment[start] == "#":
            return segment[:start]
    return segment


def command_position_code_segments(command: str) -> list[str]:
    """:func:`command_position_segments` with each segment's trailing comment removed.

    git_stash and destructive_git still judge comment text (they use
    :func:`command_position_segments`); only the guards that opt in cut it.
    """
    return [without_comment(segment) for segment in command_position_segments(command)]


def command_position_code_segments_with_separators(command: str) -> list[tuple[str, str]]:
    """:func:`command_position_code_segments` paired with the operator before each.

    Each item is ``(separator, segment)``: the separator text that split this
    segment from the one before (``;``, ``&&``, ``|``, ``|&``...), empty for
    the first. A blank segment is dropped and its separator merged into the
    next one, so `a |& b` reads as ``("", "a")`` then ``("|&", "b")``.
    """
    view = command_position_view(command)
    result: list[tuple[str, str]] = []
    previous_end = 0
    pending = ""
    for start, end in _segment_spans(view):
        pending += view[previous_end:start].strip(" \t")
        previous_end = end
        segment = without_comment(view[start:end])
        if not segment.strip():
            continue
        result.append((pending, segment))
        pending = ""
    return result


#: Commands whose quoted multi-word arguments are search patterns, programs or
#: format strings handed to THAT command, never a second command line:
#: `git log --grep='git reset --hard'`, `awk '/git stash/ {print}'`.
_TEXT_ARGUMENT_HEADS: frozenset[str] = frozenset({"git", "awk", "gawk", "mawk"})

_QUOTES = ("'", '"')


#: Read-only git subcommands: they print, never run, what they are given.
#: `submodule foreach`, `rebase --exec` and `bisect run` take a command line
#: and are NOT here, so their quoted argument stays a command.
_READ_ONLY_GIT_SUBCOMMANDS: frozenset[str] = frozenset(
    {"log", "show", "diff", "grep", "shortlog", "blame", "rev-list", "whatchanged"}
)

#: Options of those subcommands whose value is a search or format string.
_GIT_TEXT_OPTIONS: frozenset[str] = frozenset({"--grep", "-S", "-G", "-e"})
_GIT_TEXT_OPTION_PREFIXES: tuple[str, ...] = ("--grep=", "--format=", "--pretty=", "-S", "-G", "-e")
_GIT_GREP = "grep"
#: The roles (see ``git_grep_word_roles``) whose quoted literal is data to
#: `git grep`: the pattern, and the revisions and pathspecs beside it.
_GIT_GREP_DATA_ROLES: frozenset[GitGrepRole | None] = frozenset(
    {GitGrepRole.PATTERN, GitGrepRole.OPERAND}
)
#: Text a git command or awk may RUN: a `!` alias body, an awk `system` call or pipe.
_GIT_RUNNABLE_MARKERS: tuple[str, ...] = ("!",)
_AWK_RUNNABLE_MARKERS: tuple[str, ...] = ("system", "|")
_AWK_OUTPUT_REDIRECT: str = ">"


def _blank_literal(
    word: str, runnable: tuple[str, ...], at_start: bool, single_quote_is_literal: bool = False
) -> str:
    """``word`` with its one quoted literal replaced by a placeholder.

    Kept as written when the literal holds no blank (`"stash"` is a token the
    guards read), has an expansion or escape, is not a single quoted span, or
    holds text in ``runnable``. ``at_start`` says the literal opens the word;
    otherwise it follows an attached option such as `--grep=`.

    ``single_quote_is_literal`` reads `$`, a backtick and `<(` inside SINGLE
    quotes as the plain characters bash makes them (an awk program's `$1`),
    instead of as a possible expansion. Off by default: the callers that have
    not opted in keep the conservative reading.
    """
    quote_at = 0 if at_start else min((word.find(q) for q in _QUOTES if q in word), default=-1)
    if quote_at < 0 or resolve_shell_word(word[quote_at:]) is None:
        return word
    literal = word[quote_at:]
    quote = literal[0]
    body = literal[1:-1]
    if (
        quote not in _QUOTES
        or literal[-1] != quote
        or literal.count(quote) != 2
        or not any(blank in body for blank in " \t")
        or (
            any(marker in body for marker in _EXPANSION_MARKERS)
            and not (single_quote_is_literal and quote == "'")
        )
        or (quote == '"' and any(active in body for active in _DOUBLE_QUOTE_ACTIVE))
        or any(marker in body for marker in runnable)
    ):
        return word
    return word[:quote_at] + quote + _DATA_PLACEHOLDER + quote


def _blank_git_text(segment: str, words: list[tuple[int, int]]) -> list[str]:
    """Each word of a read-only git segment, with search/format literals blanked."""
    raw = [segment[start:end] for start, end in words]
    git_at = next((i for i, word in enumerate(raw) if word.rsplit("/", 1)[-1] == "git"), None)
    subcommand = None if git_at is None else git_subcommand_index(raw, git_at)
    if subcommand is None or raw[subcommand] not in _READ_ONLY_GIT_SUBCOMMANDS:
        return raw
    roles = git_grep_word_roles(raw, subcommand) if raw[subcommand] == _GIT_GREP else {}
    out = list(raw)
    for index in range(subcommand + 1, len(raw)):
        word = raw[index]
        after_option = raw[index - 1] in _GIT_TEXT_OPTIONS and index - 1 > subcommand
        is_grep_data = roles.get(index) in _GIT_GREP_DATA_ROLES and not word.startswith("-")
        if after_option or is_grep_data:
            out[index] = _blank_literal(word, _GIT_RUNNABLE_MARKERS, True)
        elif word.startswith(_GIT_TEXT_OPTION_PREFIXES):
            out[index] = _blank_literal(word, _GIT_RUNNABLE_MARKERS, False)
    return out


def blank_quoted_text_arguments(segment: str, awk_dollar_is_data: bool = False) -> str:
    """``segment`` with the quoted text arguments of `git`/`awk` blanked.

    ``awk_dollar_is_data`` lets a single-quoted awk program holding `$1` be
    blanked too: awk reads that `$` as a field, never the shell. The program's
    own `system` and `|` still keep it as written.

    A guard asks "is this a destructive git command?". The value of `--grep`,
    `-S`, `-G`, `-e`, `--format` or `--pretty` on a read-only git subcommand,
    a `git grep` pattern, and an `awk` program are data for that command. A
    quoted argument of any other git command stays: `submodule foreach`,
    `rebase --exec` and `bisect run` run it. Everything the reader cannot
    place, and everything that could run, is left as written.
    """
    head = _head(segment)
    if head not in _TEXT_ARGUMENT_HEADS:
        return segment
    words = shell_word_spans(segment)
    if head == "git":
        replaced = _blank_git_text(segment, words)
    else:
        # An awk `print > "s.sh"` can write a script a later `sh s.sh` runs, so under
        # the opt-in the program's own output redirect keeps it as written.
        runnable = _AWK_RUNNABLE_MARKERS + (_AWK_OUTPUT_REDIRECT,) * awk_dollar_is_data
        replaced = [
            _blank_literal(segment[start:end], runnable, True, awk_dollar_is_data)
            for start, end in words
        ]
    pieces: list[str] = []
    previous_end = 0
    for (start, end), word in zip(words, replaced, strict=True):
        pieces.append(segment[previous_end:start])
        pieces.append(word)
        previous_end = end
    pieces.append(segment[previous_end:])
    return "".join(pieces)


def command_position_argument_segments(command: str, awk_dollar_is_data: bool = False) -> list[str]:
    """:func:`command_position_segments` with quoted text arguments blanked.

    A segment whose output a pipeline hands to anything but a known inert sink
    is left as written: `git log --format='git reset --hard' | sh` runs it.
    ``awk_dollar_is_data`` is passed on to :func:`blank_quoted_text_arguments`,
    except for a command that runs a script an earlier segment wrote
    (:func:`_runs_written_script`): the text written IS the script.
    """
    awk_dollar_is_data = awk_dollar_is_data and not _runs_written_script(command)
    view = command_position_view(command)
    spans = _segment_spans(view)
    segments = [view[start:end] for start, end in spans]
    return [
        (
            segment
            if _pipeline_may_run_output(view, spans, segments, index)
            else blank_quoted_text_arguments(segment, awk_dollar_is_data)
        )
        for index, segment in enumerate(segments)
    ]


#: Heads whose substitution body, or whose argument, is only ever PRINTED.
_PRINTING_HEADS: frozenset[str] = frozenset({"echo", "printf"})

#: What a blanked print-only substitution is replaced with.
_PRINTED_PLACEHOLDER = "_"

#: Text that makes a substitution body more than a literal print, wherever it sits.
_BODY_ACTIVE_CHARS: tuple[str, ...] = ("$", "`", "\n")

#: Shell operators; in a substitution body they are tolerated only inside quotes.
_BODY_OPERATORS: str = "(){};&|<>"

#: A whole segment assigning a masked capture: `m=____` or `m="____"`.
_CAPTURED_ASSIGNMENT = re.compile(
    r"\s*(?P<name>[A-Za-z_][A-Za-z0-9_]*)=(?P<q>\"?)(?P<value>_+)(?P=q)\s*"
)

#: A printed word that expands one variable: `$m`, `"$m"`, `${m}`, `"${m}"`.
_PRINTED_REFERENCE = re.compile(
    r"(?P<q>\"?)\$(?:(?P<bare>[A-Za-z_][A-Za-z0-9_]*)|\{(?P<braced>[A-Za-z_][A-Za-z0-9_]*)\})(?P=q)"
)

#: Characters that make a word more than literal text (a quote is checked separately).
_UNLITERAL_WORD_CHARS: str = "$`\\"

#: Characters that make the unquoted part of a word an operator, glob or comment.
_UNQUOTED_ACTIVE_CHARS: str = "<>&(){}*?[]!#~"

#: Data sinks with an option that writes a file or runs git; never a print-only stage.
_UNSAFE_PRINTED_SINKS: frozenset[str] = frozenset({"git", "sort"})

#: An option-only word of a formatter stage: `-w`, `-c5`, `40`.
_FORMATTER_OPTION = re.compile(r"-[A-Za-z]+[0-9]*|[0-9]+")


def _outside_quotes(text: str) -> str:
    """``text`` without its single- and double-quoted spans."""
    kept: list[str] = []
    quote = ""
    for char in text:
        if quote:
            quote = "" if char == quote else quote
        elif char in "'\"":
            quote = char
        else:
            kept.append(char)
    return "".join(kept)


def _printf_options(words: list[str | None]) -> list[str | None] | None:
    """The words after `printf` (behind any `builtin`/`command`), or None if not a printf."""
    index = 0
    while index < len(words) and words[index] in _BUILTIN_PREFIXES:
        index += 1
    if index >= len(words) or words[index] != "printf":
        return None
    return words[index + 1 :]


def _assigns_variable(words: list[str | None]) -> bool:
    """Whether a `printf` stores its output in a variable (`printf -v name ...`,
    `printf -vname ...`) instead of printing it, so the text can be run later
    through that variable."""
    options = _printf_options(words) or []
    return bool(options) and (options[0] or "").startswith("-v")


def _assigned_name(words: list[str | None]) -> str | None:
    """The variable a `printf -v` (:func:`_assigns_variable`) assigns, or None
    when it cannot be read."""
    options = _printf_options(words) or [None]
    flag = options[0] or ""
    if flag != "-v":
        return flag[2:] or None
    return options[1] if len(options) > 1 else None


def _expanded_names(command: str) -> frozenset[str]:
    """Every variable name ``command`` expands (`$n`, `${n}`, `${!n}`, `${#n}`)
    outside a print-only segment whose output nothing may run."""
    spans = _segment_spans(command)
    segments = [command[start:end] for start, end in spans]
    names: set[str] = set()
    for index, segment in enumerate(segments):
        found = set(_VARIABLE_REFERENCE.findall(segment))
        printed = _is_print_only_segment(segment, False, found) and not (
            _pipeline_may_run_output(command, spans, segments, index)
        )
        if not printed:
            names |= found
    return frozenset(names)


def _assigns_expanded_variable(words: list[str | None], expanded: frozenset[str]) -> bool:
    """Whether a `printf -v` assigns a variable the command may later expand.

    `printf -v x '...'` whose `x` is never expanded leaves its text unused, so it
    is data; a name that cannot be read is assumed expanded.
    """
    if not _assigns_variable(words):
        return False
    name = _assigned_name(words)
    return name is None or name in expanded


def _printing_body(body: str) -> bool:
    """Whether ``body`` is ONE `printf`/`echo` of literal words and nothing else."""
    if any(marker in body for marker in _BODY_ACTIVE_CHARS):
        return False
    # A backslash is literal inside single quotes; beside a double quote it may escape one.
    if "\\" in body and ('"' in body or "\\" in _outside_quotes(body)):
        return False
    spans = shell_word_spans(body)
    if not spans:
        return False
    words = [resolve_shell_word(body[start:end]) for start, end in spans]
    if words[0] not in _PRINTING_HEADS or any(word is None for word in words):
        return False
    if _assigns_variable(words):
        return False
    return not any(char in _outside_quotes(body) for char in _BODY_OPERATORS)


def _printing_substitutions(command: str) -> list[tuple[int, int]]:
    """Offsets of every `$( ... )` in ``command`` whose body only prints literal text.

    A quote-aware scan: a `$(` inside single quotes is text; a body holding a
    nested substitution, a group or an unterminated quote is not a candidate.
    """
    found: list[tuple[int, int]] = []
    index = 0
    quote = ""
    while index < len(command):
        char = command[index]
        if char == "\\" and quote != "'":
            index += 2
            continue
        if quote == "'":
            quote = "" if char == "'" else quote
        elif command.startswith("$(", index) and not command.startswith("$((", index):
            end = _substitution_end(command, index + 2)
            if end is not None and _printing_body(command[index + 2 : end - 1]):
                found.append((index, end))
                index = end
                continue
        elif quote:
            quote = "" if char == quote else quote
        elif char in "'\"":
            quote = char
        index += 1
    return found


def _substitution_end(command: str, start: int) -> int | None:
    """Offset just past the `)` closing a substitution whose body begins at ``start``."""
    index = start
    quote = ""
    while index < len(command):
        char = command[index]
        if char == "\\" and quote != "'":
            index += 2
            continue
        if quote:
            if char == quote:
                quote = ""
        elif char in "'\"":
            quote = char
        elif char == ")":
            return index + 1
        elif char == "(" or command.startswith("$(", index):
            return None
        index += 1
    return None


def _is_literal_word(raw: str) -> bool:
    """Whether ``raw`` is plain text: no expansion, escape, operator, glob or comment."""
    return (
        not any(char in raw for char in _UNLITERAL_WORD_CHARS)
        and not any(char in _outside_quotes(raw) for char in _UNQUOTED_ACTIVE_CHARS)
        and resolve_shell_word(raw) is not None
    )


def _is_printed_word(raw: str, assigned: set[str]) -> bool:
    """Whether ``raw`` is literal text or the plain expansion of a captured variable."""
    reference = _PRINTED_REFERENCE.fullmatch(raw)
    if reference is not None:
        return (reference.group("bare") or reference.group("braced")) in assigned
    return _is_literal_word(raw)


def _is_print_only_segment(segment: str, piped: bool, assigned: set[str]) -> bool:
    """Whether ``segment`` is an `echo`/`printf` (not `printf -v`) of printed words,
    or, when ``piped``, a data sink given options only: no redirect, no file operand."""
    spans = shell_word_spans(segment)
    # Text no word span covers (a substitution, a backtick) is not printed text.
    uncovered = segment
    for start, end in spans:
        uncovered = uncovered[:start] + " " * (end - start) + uncovered[end:]
    if uncovered.strip():
        return False
    raws = [segment[start:end] for start, end in spans]
    if not raws:
        return True
    if raws[0] in _PRINTING_HEADS:
        option = resolve_shell_word(raws[1]) if len(raws) > 1 else ""
        assigns = raws[0] == "printf" and (option is None or option.startswith("-v"))
        return not assigns and all(_is_printed_word(raw, assigned) for raw in raws[1:])
    return (
        piped
        and raws[0] in DATA_SINKS - _UNSAFE_PRINTED_SINKS
        and all(_FORMATTER_OPTION.fullmatch(raw) for raw in raws[1:])
    )


def _whole_command_prints_only(masked: str, candidates: list[tuple[int, int]]) -> bool:
    """Whether every segment of ``masked`` (its print-only substitutions masked)
    only assigns a capture, prints, or reformats a pipe.

    An ALLOWLIST that fails closed: any other command, word or operator means
    the captured text may still be run, so it stays as written.
    """
    values = set(candidates)
    assigned: set[str] = set()
    previous_end: int | None = None
    for start, end in _segment_spans(masked):
        segment = masked[start:end]
        piped = previous_end is not None and masked[previous_end:start] == _PIPE
        previous_end = end
        assignment = _CAPTURED_ASSIGNMENT.fullmatch(segment)
        if assignment is not None:
            value = (start + assignment.start("value"), start + assignment.end("value"))
            if value not in values:
                return False
            assigned.add(assignment.group("name"))
        elif not _is_print_only_segment(segment, piped, assigned):
            return False
    return True


def blank_printed_substitutions(command: str) -> str:
    """``command`` with its print-only substitutions replaced by a placeholder,
    when the WHOLE command provably only prints.

    `msg=$(printf '%s' 'git push origin --delete b'); echo "$msg"` and
    `echo "$(printf ...)"` run no git: every segment only assigns the capture,
    prints literal words or the captured variable, or reformats a pipe
    (:func:`_whole_command_prints_only`). Anything else leaves ``command`` as written.
    """
    candidates = _printing_substitutions(command)
    if not candidates:
        return command
    masked = command
    for start, end in reversed(candidates):
        masked = masked[:start] + "_" * (end - start) + masked[end:]
    if not _whole_command_prints_only(masked, candidates):
        return command
    for start, end in reversed(candidates):
        command = command[:start] + _PRINTED_PLACEHOLDER + command[end:]
    return command


def _head(segment: str) -> str | None:
    chain = segment_command_chain(segment)
    return None if chain is None else chain[-1].rstrip(")").rsplit("/", 1)[-1]


def _pipeline_may_run_output(
    text: str, spans: list[tuple[int, int]], segments: list[str], index: int
) -> bool:
    """Whether the pipeline starting at ``index`` hands its output to anything
    but a known inert sink.

    An ALLOWLIST (:func:`is_inert_pipeline_stage`): a stage that is unreadable,
    unlisted, or reads its input through a process substitution may run what it
    is given, so a missing entry costs a false positive, never a guard.
    """
    for follower in range(index + 1, len(spans)):
        if text[spans[follower - 1][1] : spans[follower][0]] != _PIPE:
            return False
        if not is_inert_pipeline_stage(segments[follower]):
            return True
    return False


def _narrow(
    segment: str,
    may_run_output: bool,
    depth: int,
    keep_text: bool = False,
    data_heads: frozenset[str] = DATA_HEADS,
    expanded: frozenset[str] = frozenset(),
) -> str:
    """``segment`` with the text it cannot run blanked; ``expanded`` names the
    variables the whole command expands (:func:`_assigns_expanded_variable`)."""
    head = _head(segment)
    if head is None:
        return segment
    if head in data_heads:
        if (
            may_run_output
            or any(marker in segment for marker in _EXPANSION_MARKERS)
            or (head == "rg" and _has_rg_preprocessor(segment))
            or _assigns_expanded_variable(
                [resolve_shell_word(segment[a:b]) for a, b in shell_word_spans(segment)],
                expanded,
            )
        ):
            return segment
        return f" {head} {_DATA_PLACEHOLDER} "
    if head in SHELL_NAMES and depth < _MAX_NESTING:
        return _narrow_shell_body(segment, depth, keep_text or may_run_output, data_heads)
    if head in _TEXT_ARGUMENT_HEADS and not (may_run_output or keep_text):
        # A search/format literal of a read-only git command (or an awk
        # program) is data for that command, in every guard and inside a
        # `bash -c` body alike: `git grep -n 'pip install --break-system-packages'`.
        return blank_quoted_text_arguments(segment)
    if head == "gh":
        return _narrow_gh_prose(segment)
    return segment


def _has_rg_preprocessor(segment: str) -> bool:
    """Whether an `rg` segment passes `--pre`, or a word that cannot be read."""
    for start, end in shell_word_spans(segment):
        value = resolve_shell_word(segment[start:end])
        if value is None or value == _RG_PREPROCESSOR or value.startswith(_RG_PREPROCESSOR + "="):
            return True
    return False


def is_shell_command_option(option: str) -> bool:
    """Whether a shell option word takes the next word as the command string.

    A short-option cluster carrying `c` (`-c`, `-ec`, `-lc`); a long option never does.
    """
    return option.startswith("-") and not option.startswith("--") and "c" in option[1:]


def _narrow_shell_body(
    segment: str, depth: int, keep_text: bool, data_heads: frozenset[str] = DATA_HEADS
) -> str:
    """Replace a literal `-c` body with its own command-position view."""
    spans = shell_word_spans(segment)
    words = [segment[start:end] for start, end in spans]
    shell_at = next(
        (
            i
            for i, word in enumerate(words)
            if (resolve_shell_word(word) or "").rsplit("/", 1)[-1] in SHELL_NAMES
        ),
        None,
    )
    if shell_at is None:
        return segment
    for offset in range(shell_at + 1, len(words) - 1):
        option = resolve_shell_word(words[offset])
        if option is None or not option.startswith("-"):
            return segment
        if is_shell_command_option(option):
            body = resolve_shell_word(words[offset + 1])
            if body is None:
                return segment
            start, end = spans[offset + 1]
            body_view = command_position_view(body, depth + 1, keep_text, data_heads)
            if _is_elevated(words[:shell_at]):
                body_view = _elevate_later_segments(body_view)
            return segment[:start] + body_view + segment[end:]
    return segment


def _is_elevated(words_before_shell: list[str]) -> bool:
    """Whether the words ahead of a shell name run it through `sudo` or `doas`."""
    return any(
        (resolve_shell_word(word) or "").rsplit("/", 1)[-1] in _ELEVATORS
        for word in words_before_shell
    )


def _elevate_later_segments(body_view: str) -> str:
    """``body_view`` with each segment after the first headed by `sudo`.

    The splitter cuts a `sudo bash -c 'cd d; pip install x'` body at `;`, which
    leaves the second command without the `sudo` that runs it. The first
    segment already follows `sudo bash -c` in the line, so only later ones need it.
    """
    pieces: list[str] = []
    previous_end = 0
    for index, (start, end) in enumerate(_segment_spans(body_view)):
        pieces.append(body_view[previous_end:start])
        text = body_view[start:end]
        if index == 0 or not text.strip():
            pieces.append(text)
        else:
            # After any keyword (`then`, `do`, `{`...) and `(`: `then sudo pip`.
            lead = len(text) - len(strip_reserved_word_prefix(text))
            lead += len(text[lead:]) - len(text[lead:].lstrip("( \t"))
            pieces.append(f"{text[:lead]}{_ELEVATOR_PREFIX}{text[lead:]}")
        previous_end = end
    pieces.append(body_view[previous_end:])
    return "".join(pieces)


def _narrow_gh_prose(segment: str) -> str:
    """Blank the title/body/notes values of `gh pr|issue|release ...`."""
    spans = shell_word_spans(segment)
    words = [segment[start:end] for start, end in spans]
    resolved = [resolve_shell_word(word) for word in words]
    subcommand = next(
        (value for value in resolved[1:] if value is not None and not value.startswith("-")),
        None,
    )
    if subcommand not in _GH_PROSE_SUBCOMMANDS:
        return segment
    replacements: list[tuple[int, int, str]] = []
    for index, value in enumerate(resolved):
        if value is None:
            continue
        if value in _GH_PROSE_FLAGS:
            if index + 1 < len(words) and resolved[index + 1] is not None:
                start, end = spans[index + 1]
                replacements.append((start, end, _DATA_PLACEHOLDER))
        else:
            flag, equals, _rest = value.partition("=")
            if equals and flag in _GH_PROSE_FLAGS and flag.startswith("--"):
                start, end = spans[index]
                replacements.append((start, end, f"{flag}={_DATA_PLACEHOLDER}"))
    for start, end, text in reversed(replacements):
        segment = segment[:start] + text + segment[end:]
    return segment
