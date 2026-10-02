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

from claude_code_hooks_daemon.utils.shell_segmentation import (
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

#: Shells that run the string given to `-c`.
_SHELLS: frozenset[str] = frozenset({"bash", "sh", "zsh", "dash", "ksh"})

#: `rg --pre CMD` runs CMD on every file, so an `rg` carrying it is not data.
_RG_PREPROCESSOR = "--pre"

#: Redirect operators whose `&` is part of the operator, not a separator:
#: `2>&1`, `>&2`, `<&3`, `&>f`, `&>>f`.
_REDIRECT_AMPERSAND = re.compile(r"[<>]&|(?<!&)&>>?")

#: A redirect to a file, as one word: `>`, `>>`, `2>`, or with the path attached.
_REDIRECT_TARGET = re.compile(r"[0-9]*>>?(?P<path>[^&>].*)?")

#: Commands that run a file's text in the current shell.
_SOURCE_HEADS: frozenset[str] = frozenset({"source", "."})

#: What replaces the arguments of a data segment.
_DATA_PLACEHOLDER = "_"

#: Characters that make an argument something bash computes rather than reads.
_EXPANSION_MARKERS: tuple[str, ...] = ("$", "`", "<(", ">(")

#: `gh` subcommands whose title/body/notes values are human prose.
_GH_PROSE_SUBCOMMANDS: frozenset[str] = frozenset({"pr", "issue", "release"})
_GH_PROSE_FLAGS: frozenset[str] = frozenset({"--title", "--body", "--notes", "-t", "-b", "-n"})

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
    return split_unquoted_spans(masked, SEGMENT_SEPARATORS)


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
    if head in _SHELLS or head in _SOURCE_HEADS:
        operands = [word for word in words[1:] if word is None or not word.startswith("-")]
        candidate = operands[0] if operands else None
    else:
        candidate = words[0]
    if candidate is None:
        return None
    candidate = _normalise_path(candidate)
    return candidate if candidate in written else None


def _runs_written_script(command: str) -> bool:
    """Whether a segment runs a path an EARLIER segment of ``command`` wrote.

    `echo 'git stash' > s.sh && bash s.sh` runs the text of the echo, so that
    text is a command however a data head would otherwise be read. Paths are
    compared textually, so a path the shell computes is not matched; the caller
    then judges the whole command exactly as written.
    """
    written: set[str] = set()
    for start, end in _segment_spans(command):
        words = [
            resolve_shell_word(command[a + start : b + start])
            for a, b in shell_word_spans(command[start:end])
        ]
        if _executed_path(words, written) is not None:
            return True
        written |= _written_paths(words)
    return False


def command_position_view(command: str, _depth: int = 0) -> str:
    """``command`` with every span that cannot run replaced by a placeholder."""
    if _runs_written_script(command):
        return command
    stripped = strip_inert_spans(command)
    spans = _segment_spans(stripped)
    segments = [stripped[start:end] for start, end in spans]
    pieces: list[str] = []
    previous_end = 0
    for index, (start, end) in enumerate(spans):
        pieces.append(stripped[previous_end:start])
        may_run_output = _pipeline_may_run_output(stripped, spans, segments, index)
        pieces.append(_narrow(segments[index], may_run_output, _depth))
        previous_end = end
    pieces.append(stripped[previous_end:])
    return "".join(pieces)


def command_position_segments(command: str) -> list[str]:
    """The command-position view, split into its command segments.

    Split AFTER narrowing so a body read out of `bash -c '...'` is judged
    segment by segment too: `bash -c 'git stash list; git stash'` is two
    commands.
    """
    view = command_position_view(command)
    return [view[start:end] for start, end in _segment_spans(view)]


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


def _narrow(segment: str, may_run_output: bool, depth: int) -> str:
    head = _head(segment)
    if head is None:
        return segment
    if head in DATA_HEADS:
        if (
            may_run_output
            or any(marker in segment for marker in _EXPANSION_MARKERS)
            or (head == "rg" and _has_rg_preprocessor(segment))
        ):
            return segment
        return f" {head} {_DATA_PLACEHOLDER} "
    if head in _SHELLS and depth < _MAX_NESTING:
        return _narrow_shell_body(segment, depth)
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


def _narrow_shell_body(segment: str, depth: int) -> str:
    """Replace a literal `-c` body with its own command-position view."""
    spans = shell_word_spans(segment)
    words = [segment[start:end] for start, end in spans]
    shell_at = next(
        (
            i
            for i, word in enumerate(words)
            if (resolve_shell_word(word) or "").rsplit("/", 1)[-1] in _SHELLS
        ),
        None,
    )
    if shell_at is None:
        return segment
    for offset in range(shell_at + 1, len(words) - 1):
        option = resolve_shell_word(words[offset])
        if option is None or not option.startswith("-"):
            return segment
        if not option.startswith("--") and "c" in option[1:]:
            body = resolve_shell_word(words[offset + 1])
            if body is None:
                return segment
            start, end = spans[offset + 1]
            return segment[:start] + command_position_view(body, depth + 1) + segment[end:]
    return segment


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
