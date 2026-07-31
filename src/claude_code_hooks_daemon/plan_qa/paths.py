"""Single source of truth for classifying files under the plan directory.

Plan 00190. Plan documents and journal day-files obey *opposite* contracts:
a plan document is lean, curated and rewritten in place; a journal is
append-only and unbounded. Applying either rule-set to the other file type is
a defect in both directions — a size limit on a journal, or an append-only
rule on a plan.

Before this module, two independent predicates decided scope, and a file at
``JOURNAL/PLAN.md`` satisfied BOTH. :func:`classify` removes that class of
defect by construction: it returns exactly one :class:`PlanFileKind`, and it
tests journal containment BEFORE the ``PLAN.md`` filename, so journal
territory can never be read as plan material.

**Classification is deliberately config-INDEPENDENT** (Decision 5). It reads
only *layout* (where the plan and journal directories are), never *policy*
(whether journalling is enabled). A policy-dependent predicate would silently
re-apply plan rules to every journal file the moment journalling was switched
off. Policy gating belongs in the checks, on top of the answer given here.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.plan_qa.model import (
    PLAN_DOC_FILENAME,
    parse_journal_dayfile_name,
)
from claude_code_hooks_daemon.plan_qa.types import DEFAULT_JOURNAL_DIR_NAME, CheckContext

_MARKDOWN_SUFFIX: Final[str] = ".md"
_PLAN_INDEX_FILENAME: Final[str] = "README.md"

# A plan folder is ``NNNNN-name``; the number is 1-5 digits followed by a
# hyphen and a letter (mirrors the long-standing folder grammar).
_PLAN_FOLDER_NUMBER_RE: Final[re.Pattern[str]] = re.compile(r"^(\d{1,5})-[a-zA-Z]")


class PlanFileKind(Enum):
    """What kind of file an edit targets, for scope purposes.

    Exactly one kind applies to any path. ``OUTSIDE`` is the documented
    no-match: not under the plan directory, or not a markdown file.
    """

    PLAN_DOCUMENT = "plan_document"
    PLAN_INDEX = "plan_index"
    JOURNAL_DAYFILE = "journal_dayfile"
    JOURNAL_OTHER = "journal_other"
    SUPPORTING_DOC = "supporting_doc"
    OUTSIDE = "outside"


# Kinds whose content is journal territory: append-only, unbounded by design,
# and exempt from every plan-document rule (size, curation, task grammar).
_JOURNAL_KINDS: Final[frozenset[PlanFileKind]] = frozenset(
    {PlanFileKind.JOURNAL_DAYFILE, PlanFileKind.JOURNAL_OTHER}
)


@dataclass(frozen=True)
class PlanFile:
    """A path resolved against the plan directory layout."""

    kind: PlanFileKind
    path: Path
    rel_path: str
    plan_folder: str | None
    plan_number: int | None
    in_archive: bool

    @property
    def is_journal(self) -> bool:
        """Whether this file is journal territory.

        Journals are append-only and grow without limit by design, so this
        is the predicate every size and curation rule must consult to exempt
        itself.
        """
        return self.kind in _JOURNAL_KINDS

    @property
    def is_plan_document(self) -> bool:
        """Whether plan-document rules (status, task grammar, size) apply."""
        return self.kind is PlanFileKind.PLAN_DOCUMENT


def _journal_dir_index(directories: Sequence[str], journal_dir_name: str) -> int | None:
    """Index of the first journal directory in ``directories``, else ``None``.

    The one place the "is this journal territory?" question is answered.
    :func:`classify` and :func:`is_journal_file` both route through here so
    they cannot drift apart.
    """
    return next(
        (index for index, name in enumerate(directories) if name == journal_dir_name),
        None,
    )


def is_journal_file(path: Path, journal_dir_name: str = DEFAULT_JOURNAL_DIR_NAME) -> bool:
    """Whether ``path`` is journal territory, by LOCATION or by day-file NAME.

    A path-only, config-independent predicate for handlers that hold a file
    path but no :class:`CheckContext`. Both signals are legitimate:

    - **Location** — anything inside a journal directory, at any depth. This
      is the signal handlers previously lacked, so a file in ``JOURNAL/``
      with a non-conforming name still received plan-document rules.
    - **Name** — the distinctive ``NNNNN-Journal-YY-MM-DD.md`` grammar, which
      still identifies a day-file that has been misplaced.
    """
    return (
        _journal_dir_index(path.parts[:-1], journal_dir_name) is not None
        or parse_journal_dayfile_name(path.name) is not None
    )


def _archive_dir_names(context: CheckContext) -> frozenset[str]:
    names = {context.completed_dir}
    if context.cancelled_dir is not None:
        names.add(context.cancelled_dir)
    return frozenset(names)


def _plan_number_from_folder(folder_name: str) -> int | None:
    match = _PLAN_FOLDER_NUMBER_RE.match(folder_name)
    return int(match.group(1)) if match else None


def _outside(path: Path, context: CheckContext) -> PlanFile:
    try:
        rel_path = str(path.relative_to(context.project_root))
    except ValueError:
        # Outside the project entirely — keep the absolute path for messages.
        rel_path = str(path)
    return PlanFile(
        kind=PlanFileKind.OUTSIDE,
        path=path,
        rel_path=rel_path,
        plan_folder=None,
        plan_number=None,
        in_archive=False,
    )


def classify(path: Path, context: CheckContext) -> PlanFile:
    """Classify ``path`` against the plan directory layout.

    The ordering of the tests below is load-bearing:

    1. Non-markdown and non-plan-directory paths short-circuit to ``OUTSIDE``.
    2. **Journal containment is tested next** — before the ``PLAN.md``
       filename — so nothing under a journal directory can ever be read as a
       plan document.
    3. Only then are plan documents, the plan index and supporting docs
       distinguished.
    """
    if not path.is_relative_to(context.plan_dir):
        return _outside(path, context)
    if path.suffix != _MARKDOWN_SUFFIX:
        return _outside(path, context)

    relative = path.relative_to(context.plan_dir)
    parts = relative.parts
    archive_dirs = _archive_dir_names(context)
    in_archive = len(parts) > 0 and parts[0] in archive_dirs

    # Directory components between the plan dir and the file itself.
    directories = parts[:-1]
    if in_archive:
        directories = directories[1:]

    # (2) Journal containment FIRST. Any ancestor named after the journal
    # directory makes this journal territory, however deeply nested.
    journal_depth = _journal_dir_index(directories, context.journal_dir_name)
    plan_folder = directories[0] if directories else None
    if journal_depth is not None:
        # The plan folder is whatever directory encloses the journal dir.
        plan_folder = directories[journal_depth - 1] if journal_depth > 0 else None
        is_dayfile = (
            path.parent.name == context.journal_dir_name
            and parse_journal_dayfile_name(path.name) is not None
        )
        return PlanFile(
            kind=PlanFileKind.JOURNAL_DAYFILE if is_dayfile else PlanFileKind.JOURNAL_OTHER,
            path=path,
            rel_path=str(path.relative_to(context.project_root)),
            plan_folder=plan_folder,
            plan_number=_plan_number_from_folder(plan_folder) if plan_folder else None,
            in_archive=in_archive,
        )

    rel_path = str(path.relative_to(context.project_root))
    plan_number = _plan_number_from_folder(plan_folder) if plan_folder else None

    # (3) The index lives at the plan-directory root; inside a plan folder a
    # README is just another supporting doc.
    if not directories:
        kind = (
            PlanFileKind.PLAN_INDEX if path.name == _PLAN_INDEX_FILENAME else PlanFileKind.OUTSIDE
        )
        if kind is PlanFileKind.OUTSIDE:
            return _outside(path, context)
        return PlanFile(
            kind=kind,
            path=path,
            rel_path=rel_path,
            plan_folder=None,
            plan_number=None,
            in_archive=in_archive,
        )

    kind = (
        PlanFileKind.PLAN_DOCUMENT
        if path.name == PLAN_DOC_FILENAME
        else PlanFileKind.SUPPORTING_DOC
    )
    return PlanFile(
        kind=kind,
        path=path,
        rel_path=rel_path,
        plan_folder=plan_folder,
        plan_number=plan_number,
        in_archive=in_archive,
    )
