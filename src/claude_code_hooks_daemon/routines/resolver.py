"""Resolving a routine and the procedure a run executes (Plan 00412 Task 2.3).

The CLI verb that uses this is deliberately thin. Everything here can be wrong
in a way worth testing, and ``daemon/cli.py`` is already ~9,000 lines — the
last collector that grew inside it had to be extracted so that a directive and
a command could not disagree about what they were describing.

Two refusals, both deliberate, both about the same failure:

- an id matching nothing raises rather than returning nothing. The caller named
  something specific, and an empty result reads downstream as a routine that
  exists and has never run — quieter, and wronger;
- a ROUTINE.md with no usable ``## Procedure`` raises rather than yielding "".
  Handing an agent an empty procedure is how a run gets RECORDED for work
  nobody did, and the record is the only thing that proves a run happened.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

#: Routine tree, beside ``CLAUDE/Plan`` — which is the point of the naming.
_ROUTINES_SUBDIR: Final[tuple[str, str]] = ("CLAUDE", "Routine")

#: The definition document inside a routine folder.
ROUTINE_DOC: Final[str] = "ROUTINE.md"

#: ``NNNNN-name``. A letter after the hyphen keeps date folders out.
_ROUTINE_FOLDER: Final[re.Pattern[str]] = re.compile(r"^(\d{1,5})-[a-zA-Z]")

#: The heading whose body a run executes.
_PROCEDURE_HEADING: Final[str] = "## Procedure"

#: A scaffolded-but-unfilled procedure is only an HTML comment. Running that
#: would record coverage for an interval nobody reviewed.
_COMMENT_ONLY: Final[re.Pattern[str]] = re.compile(r"^<!--.*?-->$", re.DOTALL)


class RoutineNotFoundError(LookupError):
    """No routine in this project answers to the given id."""


class ProcedureMissingError(ValueError):
    """The routine has no procedure a run could execute."""


def routines_dir(project_root: Path) -> Path:
    """The routine tree for ``project_root``.

    Args:
        project_root: Repository root.

    Returns:
        The path, which may not exist.
    """
    return project_root.joinpath(*_ROUTINES_SUBDIR)


def list_routines(project_root: Path) -> list[Path]:
    """Every live routine folder, lowest number first.

    Archived routines (one level down, e.g. ``Completed/``) are excluded: this
    is the index a human reads before naming one, and a retired routine is not
    a candidate to run.

    Args:
        project_root: Repository root.

    Returns:
        The folders, or an empty list when the project declares none — which
        is not an error, because nothing was named.
    """
    tree = routines_dir(project_root)
    if not tree.is_dir():
        return []
    return sorted(
        (child for child in tree.iterdir() if _is_routine_folder(child)),
        key=lambda path: path.name,
    )


def find_routine(project_root: Path, identifier: str) -> Path:
    """The routine folder ``identifier`` names.

    Accepts a padded number (``00001``), an unpadded one (``1``) or the whole
    folder name. A live routine wins over an archived folder carrying the same
    number; an archived one is still addressable when nothing live matches,
    because archiving is history rather than deletion.

    Args:
        project_root: Repository root.
        identifier: Number or folder name.

    Returns:
        The routine folder.

    Raises:
        RoutineNotFoundError: Nothing in the tree answers to ``identifier``.
    """
    for candidate in (*list_routines(project_root), *_archived_routines(project_root)):
        if _matches(candidate, identifier):
            return candidate
    raise RoutineNotFoundError(
        f"no routine matching '{identifier}' under {routines_dir(project_root)} — "
        "run `hooks-daemon run-routine --list` to see what this project declares"
    )


def read_procedure(routine: Path) -> str:
    """The body of the routine's ``## Procedure`` section.

    Args:
        routine: A routine folder.

    Returns:
        The procedure text, stripped, without its heading.

    Raises:
        ProcedureMissingError: There is no ROUTINE.md, no procedure heading,
            or the section still holds only its scaffolded placeholder.
    """
    document = routine / ROUTINE_DOC
    if not document.is_file():
        raise ProcedureMissingError(
            f"{routine.name} has no {ROUTINE_DOC} — a folder without one is not a routine"
        )

    body = _section(document.read_text(encoding="utf-8"), _PROCEDURE_HEADING)
    if body is None:
        raise ProcedureMissingError(
            f"{routine.name}/{ROUTINE_DOC} has no '{_PROCEDURE_HEADING}' section — "
            "a run with no procedure records coverage for work nobody did"
        )
    if not body or _COMMENT_ONLY.match(body):
        raise ProcedureMissingError(
            f"{routine.name}/{ROUTINE_DOC} still holds the scaffolded "
            f"'{_PROCEDURE_HEADING}' placeholder — fill it in before running"
        )
    return body


def _is_routine_folder(path: Path) -> bool:
    """Whether ``path`` is a numbered routine folder.

    A dotfile is excluded outright, which is what keeps the scaffolder's
    ``.mkroutine.lock`` from being offered as a routine.
    """
    return (
        path.is_dir()
        and not path.name.startswith(".")
        and _ROUTINE_FOLDER.match(path.name) is not None
    )


def _archived_routines(project_root: Path) -> list[Path]:
    """Routine folders one level down, e.g. under ``Completed/``."""
    tree = routines_dir(project_root)
    if not tree.is_dir():
        return []
    archived: list[Path] = []
    for parent in tree.iterdir():
        if not parent.is_dir() or _is_routine_folder(parent) or parent.name.startswith("."):
            continue
        archived.extend(child for child in parent.iterdir() if _is_routine_folder(child))
    return sorted(archived, key=lambda path: path.name)


def _matches(routine: Path, identifier: str) -> bool:
    """Whether ``routine`` answers to ``identifier``."""
    if routine.name == identifier:
        return True
    match = _ROUTINE_FOLDER.match(routine.name)
    if match is None:
        return False
    if not identifier.isdigit():
        return False
    return int(match.group(1)) == int(identifier)


def _section(document: str, heading: str) -> str | None:
    """The body under ``heading``, up to the next heading of any level.

    Args:
        document: Whole markdown document.
        heading: Exact heading line to find.

    Returns:
        The stripped body, or None when the heading is absent. An empty string
        means the heading is present with nothing under it, which the caller
        treats differently from absence.
    """
    lines = document.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == heading)
    except StopIteration:
        return None

    body: list[str] = []
    for line in lines[start + 1 :]:
        if line.startswith("#"):
            break
        body.append(line)
    return "\n".join(body).strip()
