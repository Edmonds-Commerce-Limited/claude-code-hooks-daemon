"""Resolve a plan link by NUMBER, wherever the plan now lives (Plan 00419 N2).

Archiving a plan moves ``<plan dir>/NNNNN-x/`` to
``<plan dir>/Completed/NNNNN-x/`` — one level deeper — so every
``](../00NNN-y/PLAN.md)`` that plan contains stops resolving the moment it is
archived. The pointers that break are the load-bearing ones: a link to the plan
that graduated out of this one is the reason a reader opens an archived ledger
at all.

Repointing the links at archival time is not available as a remedy. A
``JOURNAL/`` day-file is append-only, so rewriting an earlier entry to chase a
folder that moved is forbidden by ``journal-append-only`` — observed as real
handler output, both directions, on Plan 00408's day-file. And the project has
already ruled that an archived plan is a RECORD: "truth is enforced on LIVE
plans, never on the historical record".

What is left is to teach the tooling what ``bin/hooks-daemon find-plan``
already tells humans: a link names a plan NUMBER, and the plan is wherever it
now lives. Resolution here is applied only when the LITERAL path fails, so a
link to a plan that never existed still reports dead.

Every name this needs already has a config home —
``plan_workflow.directory``, ``plan_workflow.qa.completed_dir`` /
``cancelled_dir`` and ``plan_workflow.qa.journal.dir_name`` — so the resolver
introduces no new key. It reads the FILESYSTEM rather than ``README.md``'s
index, for the reason :mod:`plan_finder` states: a plan whose index row is
missing must not become invisible to a resolver that claims to search
everything.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Protocol

from claude_code_hooks_daemon.utils.authored_paths import contained_authored_path

#: Mirrors ``PlanWorkflowConfig.directory`` and the two archive fields'
#: pydantic defaults. Stated here, as ``docs_qa.policy`` states
#: ``DEFAULT_AGENT_TREE``, so a caller with no config to hand still gets the
#: shipped shape rather than nothing.
DEFAULT_PLAN_DIR: Final[str] = "CLAUDE/Plan"
DEFAULT_ARCHIVE_DIRS: Final[tuple[str, ...]] = ("Completed", "Cancelled")
DEFAULT_JOURNAL_DIR: Final[str] = "JOURNAL"

_PLAN_DOC_FILENAME: Final[str] = "PLAN.md"

# A plan folder is ``NNNNN-name``. Four or five digits (matching
# :mod:`plan_finder`) rather than one-to-five: a looser pattern reads
# ``2026-09-16-retro.md`` as plan 2026.
_PLAN_FOLDER_RE: Final[re.Pattern[str]] = re.compile(r"^(\d{4,5})-")


@dataclass(frozen=True)
class PlanTreeLayout:
    """Where plan folders live: the active root, and every archive directory.

    Plain values, so the consuming packages stay config-decoupled the way
    ``plan_qa.context`` and ``docs_qa.policy`` already are.
    """

    plan_dir: str = DEFAULT_PLAN_DIR
    archive_dirs: tuple[str, ...] = DEFAULT_ARCHIVE_DIRS
    journal_dir: str = DEFAULT_JOURNAL_DIR

    def contains(self, rel_path: str) -> bool:
        """Whether ``rel_path`` (repo-relative, forward-slashed) is in the tree."""
        prefix = self.plan_dir.strip("/") + "/"
        return rel_path.startswith(prefix)

    def is_archived(self, rel_path: str) -> bool:
        """Whether ``rel_path`` sits under one of the archive directories.

        An archived plan is a RECORD. Nothing about it is rewritten to match
        today's tree, so a finding against one is a finding nobody may act on.
        """
        if not self.contains(rel_path):
            return False
        remainder = rel_path[len(self.plan_dir.strip("/")) + 1 :]
        return any(remainder.startswith(name + "/") for name in self.archive_dirs)

    def is_journal(self, rel_path: str) -> bool:
        """Whether ``rel_path`` is journal territory inside the plan tree.

        A journal is append-only, so an earlier entry cannot be repointed.
        Scoped to the plan tree on purpose: a directory merely NAMED
        ``JOURNAL`` elsewhere in the repository carries no such contract.
        """
        if not self.contains(rel_path):
            return False
        return f"/{self.journal_dir}/" in rel_path

    def is_plan_document(self, rel_path: str) -> bool:
        """Whether ``rel_path`` is a ``PLAN.md`` inside the plan tree."""
        return (
            self.contains(rel_path)
            and not self.is_journal(rel_path)
            and rel_path.rsplit("/", 1)[-1] == _PLAN_DOC_FILENAME
        )


class PlanWorkflowShape(Protocol):
    """Structural view of ``PlanWorkflowConfig``.

    A Protocol for the same reason ``docs_qa.policy`` uses them: this module
    must not import the pydantic models, so the real config, a test stand-in
    or plain values loaded elsewhere all satisfy it.
    """

    @property
    def directory(self) -> str: ...

    @property
    def qa(self) -> PlanWorkflowQaShape: ...


class PlanWorkflowQaShape(Protocol):
    """Structural view of ``PlanWorkflowQaConfig``."""

    @property
    def completed_dir(self) -> str: ...

    @property
    def cancelled_dir(self) -> str | None: ...

    @property
    def journal(self) -> PlanWorkflowJournalShape: ...


class PlanWorkflowJournalShape(Protocol):
    """Structural view of ``PlanWorkflowQaJournalConfig``."""

    @property
    def dir_name(self) -> str: ...


def plan_tree_layout(plan_workflow: PlanWorkflowShape) -> PlanTreeLayout:
    """Build a :class:`PlanTreeLayout` from the ``plan_workflow`` config block.

    Archive names are deduped in declaration order, matching
    ``ProjectLayout.plan_archive_dirs``: a project that sets ``cancelled_dir``
    to ``None`` (or to the same name as ``completed_dir``) has ONE archive, and
    searching it twice would be harmless but dishonest about the tree's shape.
    """
    qa = plan_workflow.qa
    archives = tuple(dict.fromkeys(name for name in (qa.completed_dir, qa.cancelled_dir) if name))
    return PlanTreeLayout(
        plan_dir=plan_workflow.directory,
        archive_dirs=archives,
        journal_dir=qa.journal.dir_name,
    )


@dataclass(frozen=True)
class RelocatedPlanLink:
    """A link target that resolves through the plan tree rather than literally."""

    plan_number: int
    path: Path
    rel_path: str


def split_plan_reference(target: str) -> tuple[int, str] | None:
    """Split a link target into ``(plan number, remainder)``, or ``None``.

    The RIGHTMOST plan-folder-shaped component wins, so
    ``../Completed/00413-x/PLAN.md`` names 00413 rather than whatever precedes
    it, and the remainder is everything below the folder
    (``JOURNAL/00414-Journal-26-09-16.md`` for a nested target, ``""`` for a
    link to the folder itself).

    The FINAL component is only accepted when it has no extension. A journal
    day-file is named ``00413-Journal-26-09-15.md``, which is folder-shaped and
    is a FILE — reading it as a plan reference would invent a plan link out of
    a filename.
    """
    parts = target.split("/")
    for index in range(len(parts) - 1, -1, -1):
        component = parts[index]
        if index == len(parts) - 1 and "." in component:
            continue
        match = _PLAN_FOLDER_RE.match(component)
        if match is not None:
            return int(match.group(1)), "/".join(parts[index + 1 :])
    return None


class PlanLinkResolver:
    """Answers "where does plan NNNNN's file live now?" over one plan tree.

    The folder index is built ONCE, lazily, on the first target that needs it:
    a sweep asks this question for every unresolved link in the corpus, and an
    EDIT-stage check must not pay for a directory listing when every link in
    the file resolves literally.
    """

    def __init__(self, project_root: Path, layout: PlanTreeLayout) -> None:
        self._project_root = project_root
        self._layout = layout
        self._folders: dict[int, Path] | None = None

    def resolve(self, source_dir: Path, target: str) -> RelocatedPlanLink | None:
        """The plan file ``target`` names, or ``None`` if it names none.

        ``source_dir`` is the directory of the document the link was written
        in; it is not consulted for resolution (the plan NUMBER is the whole
        key) but keeps the call site honest about what a link is relative to,
        and :meth:`suggested_link` needs it.

        ``None`` covers three genuinely different cases that all mean "this
        check should say nothing": the target names no plan, the plan number
        exists nowhere in the tree, or the named file is absent from the
        folder that was found. A link to a plan that never existed must still
        report dead, which is why the third case is not waved through.
        """
        del source_dir  # resolution is by plan number alone
        reference = split_plan_reference(target)
        if reference is None:
            return None
        number, remainder = reference
        folder = self._folder_for(number)
        if folder is None:
            return None
        # The remainder is AUTHORED text out of a markdown link, so it is
        # contained rather than merely joined: `../00413-x/../../../etc/passwd`
        # normalises clean out of the repository, and a plain existence answer
        # over that reports whether the HOST path is there.
        resolved = (
            contained_authored_path(folder, remainder, within=self._project_root)
            if remainder
            else folder
        )
        if resolved is None or not resolved.exists():
            return None
        return RelocatedPlanLink(
            plan_number=number,
            path=resolved,
            rel_path=str(resolved.relative_to(self._project_root)),
        )

    def suggested_link(self, source_dir: Path, relocated: RelocatedPlanLink) -> str:
        """The relative target an author should write from ``source_dir``.

        A remediation that named only the repo-relative path would leave the
        reader to compute the ``../`` hops themselves, which is the step the
        original link got wrong.
        """
        return os.path.relpath(relocated.path, start=source_dir).replace(os.sep, "/")

    def _folder_for(self, number: int) -> Path | None:
        if self._folders is None:
            self._folders = self._index_folders()
        return self._folders.get(number)

    def _index_folders(self) -> dict[int, Path]:
        """Plan folders by number: the active root first, then each archive.

        First match wins. Two folders sharing a number is
        ``no-new-collisions``' finding, not this resolver's — but it must
        still answer, and the LIVE plan is the better answer to "where is
        plan N".
        """
        folders: dict[int, Path] = {}
        plan_dir = self._project_root / self._layout.plan_dir
        roots = [plan_dir, *(plan_dir / name for name in self._layout.archive_dirs)]
        for root in roots:
            if not root.is_dir():
                continue
            for entry in sorted(root.iterdir()):
                if not entry.is_dir():
                    continue
                match = _PLAN_FOLDER_RE.match(entry.name)
                if match is not None:
                    folders.setdefault(int(match.group(1)), entry)
        return folders
