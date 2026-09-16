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
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.utils.path_predicates import path_is_file

_LOGGER = logging.getLogger(__name__)

#: `git commit -F <file>` / `--file=<file>`, and `--body-file <file>`. The
#: value may be bare, single- or double-quoted.
MESSAGE_FILE_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?:-F|--file|--body-file)(?:\s+|=)(?:\"([^\"]+)\"|'([^']+)'|(\S+))"
)

#: `-` is stdin: a heredoc or a pipe, with no path to open. Its body sits in
#: the command text, which every caller scans anyway.
STDIN_MESSAGE_FILE: Final[str] = "-"

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
            _LOGGER.debug("Skipping unreadable message file %s: %s", path, failure)
            continue
        found.append(
            MessageFile(path=path, text=raw_bytes.decode(_ENCODING, errors=_DECODE_ERRORS))
        )
    return found
