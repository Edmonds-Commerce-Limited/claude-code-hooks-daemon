"""Message and body FILES named on a command line, read once for every caller.

`git commit -F <file>`, `git commit --file=<file>` and
`gh issue create --body-file <file>` all put the text somewhere other than the
command line. A guard that reads only the command therefore judges
`git commit -m "<term>"` and misses `git commit -F msg.txt` carrying the same
term — which is how Plan 00412's D-PUB-2 was found: two handlers had
near-identical private copies of this reader, and the second was wired into one
of its two branches.

Skipping is deliberate in every case below. A missing or unreadable file makes
`git` itself fail, and that failure belongs to git rather than to a guard; an
oversized file is not a message a human wrote. Reporting those as violations
would make the guard fire on commands that were already going to fail.

**Scope this to commands that genuinely take a message or body file.** `-F`
means a FIELD to `gh api`, so reading every `-F` on every command would start
treating `-F key=value` as a filename.
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.constants import HookInputField, ToolName
from claude_code_hooks_daemon.core.utils import scan_bash_write_targets, split_heredocs
from claude_code_hooks_daemon.utils.command_evasion import normalise_line_continuations
from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue
from claude_code_hooks_daemon.utils.path_predicates import path_is_file
from claude_code_hooks_daemon.utils.shell_segmentation import (
    mask_quoted,
    split_unquoted,
    split_unquoted_spans,
)

_LOGGER = logging.getLogger(__name__)

#: `git commit -F <file>` / `--file=<file>`, and `--body-file <file>`. The
#: value may be bare, single- or double-quoted.
MESSAGE_FILE_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?:-F|--file|--body-file)(?:\s+|=)(?:\"([^\"]+)\"|'([^']+)'|(\S+))"
)

#: `-` is stdin: a heredoc or a pipe, with no path to open. Its body sits in
#: the command text, which every caller scans anyway.
STDIN_MESSAGE_FILE: Final[str] = "-"

#: Where one shell command ends and the next begins. Longest first so `||` is
#: not read as two pipes.
COMMAND_SEPARATORS: Final[tuple[str, ...]] = ("||", "&&", "|", ";", "\n")

#: Where one top-level statement ends: a pipeline is NOT split here.
STATEMENT_SEPARATORS: Final[tuple[str, ...]] = ("||", "&&", ";", "\n")

#: A group opener is `(` or a `{` standing alone as a word; a closer is `)` or
#: a `}` standing alone. Parameter braces (`${x}`) are not groups.
_GROUP_OPEN: Final[re.Pattern[str]] = re.compile(r"\(|(?<![\w$])\{(?=\s)")
_GROUP_CLOSE: Final[re.Pattern[str]] = re.compile(r"\)|(?:(?<=\s)|^)\}(?![\w}])")

#: Where a reserved word can begin a command: at the start, after a separator
#: or opener, or after `then` / `do` / `else` / `elif`.
_COMMAND_START: Final[str] = (
    r"(?:^|(?<=[;&|\n(){])|(?<=\bthen)|(?<=\bdo)|(?<=\belse)|(?<=\belif))\s*"
)

#: Compound commands carry the redirect that applies to the whole of them on
#: their closing word: `if ...; fi > m.txt`, `for ...; done > m.txt`.
_COMPOUND_OPEN: Final[re.Pattern[str]] = re.compile(
    _COMMAND_START + r"(?P<word>if|for|while|until|case|select)\b"
)
_COMPOUND_CLOSE: Final[re.Pattern[str]] = re.compile(_COMMAND_START + r"(?P<word>fi|done|esac)\b")

#: A `case` pattern list ends in a `)` that closes nothing.
_CASE_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?:\bin|;;&?|;&)\s*(?!esac\b)\(?\s*[^\s()]+(?:\s*\|\s*[^\s()]+)*\s*\)"
)

_CASE_WORD: Final[str] = "case"
_OPENS: Final[int] = 1
_CLOSES: Final[int] = -1

#: Both former copies used this bound, so it is preserved rather than chosen.
MAX_MESSAGE_FILE_BYTES: Final[int] = 65_536

_ENCODING: Final[str] = "utf-8"
_DECODE_ERRORS: Final[str] = "replace"


@dataclass(frozen=True)
class MessageFile:
    """One readable message file, and what it contains.

    The path travels with the text because a caller may need to NAME the file
    without quoting it: `sensitive_content` reports which file carried a term
    and never the line that did.
    """

    path: Path
    text: str


def _resolve_message_path(raw: str, cwd: str | None) -> str:
    """``raw`` as an absolute, normalised path when ``cwd`` allows it."""
    path = Path(raw)
    if not path.is_absolute() and cwd:
        path = Path(cwd) / path
    return os.path.normpath(str(path))


def _named_message_files(recordings: Sequence[str], cwd: str | None) -> set[str]:
    """Normalised paths of every message/body file ``recordings`` name."""
    named: set[str] = set()
    for recording in recordings:
        for match in MESSAGE_FILE_PATTERN.finditer(recording):
            raw = next(group for group in match.groups() if group)
            if raw != STDIN_MESSAGE_FILE:
                named.add(_resolve_message_path(raw, cwd))
    return named


def _writes_any(segment: str, named: set[str], cwd: str | None) -> bool:
    """True when ``segment`` writes one of the ``named`` paths.

    With no ``cwd`` a relative path cannot be resolved, so the file NAME
    decides: matching too much only offers one more segment to the caller.
    """
    hook_input: dict[str, Any] = {
        HookInputField.TOOL_NAME: ToolName.BASH,
        HookInputField.TOOL_INPUT: {"command": segment},
    }
    if cwd:
        hook_input[HookInputField.CWD] = cwd
    written = {os.path.normpath(target) for target in scan_bash_write_targets(hook_input).paths}
    if written & named:
        return True
    if cwd:
        return False
    names = {Path(target).name for target in written}
    return any(Path(path).name in names for path in named)


def _reads_stdin_message(text: str) -> bool:
    """True when ``text`` names stdin (``-F -``, ``--file=-``, ``--body-file -``) as its message."""
    return any(
        next(group for group in match.groups() if group) == STDIN_MESSAGE_FILE
        for match in MESSAGE_FILE_PATTERN.finditer(text)
    )


def _group_tokens(masked: str) -> list[tuple[int, int, int]]:
    """``(start, end, delta)`` of every group opener (+1) and closer (-1) in ``masked``.

    Groups are ``{ }``, ``( )`` and the compound commands ``if``/``fi``,
    ``for``/``while``/``until``/``select`` ... ``done`` and ``case``/``esac``;
    ``masked`` has its quoted text blanked.
    """
    opens = [(m.start("word"), m.end("word")) for m in _COMPOUND_OPEN.finditer(masked)]
    if any(masked[start:end] == _CASE_WORD for start, end in opens):
        masked = _CASE_PATTERN.sub(lambda m: m.group().replace("(", " ").replace(")", " "), masked)
    tokens = [(m.start(), m.end(), _OPENS) for m in _GROUP_OPEN.finditer(masked)]
    tokens += [(m.start(), m.end(), _CLOSES) for m in _GROUP_CLOSE.finditer(masked)]
    tokens += [(start, end, _OPENS) for start, end in opens]
    tokens += [(m.start("word"), m.end("word"), _CLOSES) for m in _COMPOUND_CLOSE.finditer(masked)]
    return sorted(tokens)


def _statements(without_bodies: str) -> list[str]:
    """Top-level statements of ``without_bodies``: split on ``&&``/``||``/``;``/newline.

    A pipeline stays whole (``|`` does not split), and a ``{ }`` / ``( )``
    group or ``if``/``for``/``while``/``until``/``case`` compound stays whole,
    so the stage that PRODUCES a text travels with the one that writes it. An
    unbalanced group runs to the end of the command, which keeps more text
    rather than less.
    """
    tokens = _group_tokens(mask_quoted(without_bodies, keep_double=False))
    statements: list[str] = []
    open_from: int | None = None
    depth = 0
    for start, end in split_unquoted_spans(without_bodies, STATEMENT_SEPARATORS):
        if open_from is None:
            open_from = start
        depth += sum(delta for position, _, delta in tokens if start <= position < end)
        if depth <= 0:
            statements.append(without_bodies[open_from:end])
            open_from = None
            depth = 0
    if open_from is not None:
        statements.append(without_bodies[open_from:])
    return [statement for statement in statements if statement.strip()]


def _unwrap(statement: str) -> tuple[str, str] | None:
    """``(inside, after)`` when ``statement`` opens with a group that closes before its end.

    ``after`` is whatever follows the group's closer: a redirect or a pipe
    that applies to the group as a whole. ``None`` when the statement does
    not begin with a group, or the group never closes.
    """
    text = statement.strip()
    tokens = _group_tokens(mask_quoted(text, keep_double=False))
    if not tokens or tokens[0][0] != 0 or tokens[0][2] != _OPENS:
        return None
    depth = 0
    for start, end, delta in tokens:
        depth += delta
        if depth == 0:
            return text[tokens[0][1] : start], text[end:]
    return None


def _leaves(statement: str, applies_outside: Callable[[str], bool]) -> list[str]:
    """``statement``, or the statements INSIDE it when its group is not what is recorded.

    A group stays whole only when what follows it (``applies_outside``) is the
    write or recording: ``{ echo T; } > m.txt``. When the write sits inside
    (``( cd /tmp/x && echo msg > m.txt )``) the group's other statements are not
    message text, so they are judged one by one, as they would be outside it.
    """
    unwrapped = _unwrap(statement)
    if unwrapped is None or applies_outside(unwrapped[1]):
        return [statement]
    leaves: list[str] = []
    for inner in _statements(unwrapped[0]):
        leaves.extend(_leaves(inner, applies_outside))
    return leaves


def _stdin_producers(statement: str, recordings: Sequence[str]) -> list[str]:
    """Pipeline stages that feed a recording stage reading its message from stdin."""
    stages = split_unquoted(statement, ("|",))
    producers: list[str] = []
    for position, stage in enumerate(stages[1:], start=1):
        recorded = any(recording.strip() and recording.strip() in stage for recording in recordings)
        if recorded and _reads_stdin_message(stage):
            producers.append("|".join(stages[:position]).strip())
    return producers


def message_file_writers(command: str, recordings: Sequence[str], cwd: str | None) -> list[str]:
    """Text of ``command`` that PRODUCES a message ``recordings`` take from elsewhere.

    ``git commit -F m.txt`` reads a file an earlier part of the same command
    may create (``cat > m.txt <<'EOF'``, ``echo ... > m.txt``). That file is not
    on disk at PreToolUse time, so :func:`read_message_files` skips it and the
    text it will hold is visible only in the command that creates it. A caller
    that judges message text per recording command (rather than the whole
    line) must judge these as well, or the text reaches history unexamined.

    Three shapes are returned:

    * the whole statement (pipeline or ``{ }`` / ``( )`` group included) that
      writes a named file, so ``echo <text> | tee m.txt`` and
      ``{ echo <text>; } > m.txt`` are judged on ``<text>``, not just on the
      ``tee`` or the closing redirect;
    * that statement's heredoc bodies;
    * the pipeline stages feeding a recording command that reads stdin
      (``echo <text> | git commit -F -``).

    A statement that writes no named file is not message text, so an unrelated
    one (``cd /tmp/<term>``) is still not returned. A producer whose text is
    not on the command line (``cat other.txt | git commit -F -``) is unknowable
    here and is left to the file reader, as an unreadable file already is.
    """
    named = _named_message_files(recordings, cwd)
    stdin = any(_reads_stdin_message(recording) for recording in recordings)
    if not named and not stdin:
        return []
    without_bodies, heredocs = split_heredocs(normalise_line_continuations(command))
    writers: list[str] = []
    recorded = [recording.strip() for recording in recordings if recording.strip()]

    def applies_outside(after: str) -> bool:
        writes = bool(named) and _writes_any(after, named, cwd)
        return writes or (stdin and any(recording in after for recording in recorded))

    for top_level in _statements(without_bodies):
        for statement in _leaves(top_level, applies_outside):
            if named and _writes_any(statement, named, cwd):
                writers.append(statement.strip())
            if stdin:
                writers.extend(_stdin_producers(statement, recordings))
    for heredoc in heredocs:
        opener = heredoc.opener_line.strip()
        if any(opener in found or found in opener for found in writers):
            writers.append(heredoc.body)
    return writers


def read_message_files(command: str, cwd: str | None) -> list[MessageFile]:
    """Every readable message/body file named in ``command``.

    A relative path with no ``cwd`` is left unresolved and therefore skipped.
    Joining it against the process's own working directory would name a file
    the command never meant, which is a fabricated path rather than a resolved
    one.
    """
    found: list[MessageFile] = []
    for match in MESSAGE_FILE_PATTERN.finditer(command):
        raw = next(group for group in match.groups() if group)
        if raw == STDIN_MESSAGE_FILE:
            continue
        path = Path(raw)
        if not path.is_absolute():
            if not cwd:
                continue
            path = Path(cwd) / path
        # `os.access` never raises, so it would have caught an unreadable file
        # on its own -- but only by correcting a guess `is_file()` had already
        # crashed on. Stating the answer here keeps the skip attributable to
        # this line rather than to the next one.
        if not path_is_file(path, unreadable_means=False) or not os.access(path, os.R_OK):
            continue
        try:
            if path.stat().st_size > MAX_MESSAGE_FILE_BYTES:
                continue
            raw_bytes = path.read_bytes()
        except OSError as failure:
            # Statting a file is NOT reading it, and the gap raises. A file
            # whose own mode denies read stats perfectly well, and so does one
            # unlinked between the check above and this line. Letting that
            # escape takes the calling guard down with it -- which is a guard
            # that silently stops applying, or one that denies legitimate work.
            log_and_continue(
                _LOGGER,
                failure,
                reason=f"an unreadable message file {path} is skipped so the calling guard still judges the files it can read, instead of failing outright",
                level=logging.DEBUG,
            )
            continue
        found.append(
            MessageFile(path=path, text=raw_bytes.decode(_ENCODING, errors=_DECODE_ERRORS))
        )
    return found
