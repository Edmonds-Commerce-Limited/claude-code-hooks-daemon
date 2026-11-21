"""Filing proposals for the scratch sweep (Plan 00627 Task 2.5, DESIGN.md section 6).

A proposal is a suggestion printed beside an UNCERTAIN, REFERENCED or PROTECTED
row. It never feeds the verdict and it never moves anything: a filed file needs
a name, a commit and the content guards, which do not see a ``mv``.

The hint is chosen from the entry's name, kind and size alone; no file is
opened. A command is printed only for a single regular file going to a plan
folder, and it is ``mv -n --``: it cannot overwrite, and it is never run here.
No delete command is ever produced.
"""

from __future__ import annotations

import enum
import os
import re
import shlex
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.core.scratch_verdict import Verdict
from claude_code_hooks_daemon.core.scratch_walk import NodeKind
from claude_code_hooks_daemon.plan_finder import find_plans

HINT_REPOSITORY: Final[str] = "commit and push to a branch on the remote; then P4 covers it"
HINT_TRACKED: Final[str] = "holds a file the project tracks: a human decides"
HINT_TOO_LARGE: Final[str] = "Too large to track: file a summary and let the rest expire"
HINT_SCRIPT: Final[str] = "scripts/ (tooling) or tests/ (a harness, test first)"
HINT_RELEASE: Final[str] = "CLAUDE/UPGRADES/UNRELEASED/"
HINT_NO_HOME: Final[str] = "No tracked home: ask the coordinator for a plan folder"

#: The verdicts that get a proposal: the rest are in use, unknown, or due to go.
_PROPOSED: Final[frozenset[Verdict]] = frozenset(
    {Verdict.UNCERTAIN, Verdict.REFERENCED, Verdict.PROTECTED}
)
_PLAN_PREFIX: Final[re.Pattern[str]] = re.compile(r"^(\d{3,5})(?=[-_.]|$)")
_SCRIPT_SUFFIXES: Final[frozenset[str]] = frozenset({".py", ".sh", ".bash"})
_RELEASE_WORDS: Final[tuple[str, ...]] = ("release", "upgrade")
_ARCHIVE_SEGMENT: Final[str] = "Completed"
_REPORTS: Final[str] = "subagent-reports"


class Protection(enum.Enum):
    """Why a PROTECTED entry is protected, in the order ``judge`` decides it."""

    NONE = "none"
    REPOSITORY = "repository"
    TRACKED = "tracked"


@dataclass(frozen=True)
class FilingProposal:
    """Where an entry could be filed, and the move command (empty: none printed)."""

    destination: str
    command: str


@dataclass(frozen=True)
class PlanIndex:
    """Plan folders (project-relative) by number; a number with two same-tier folders is ambiguous."""

    folders: Mapping[int, str]
    ambiguous_numbers: frozenset[int] = field(default_factory=frozenset)

    def folder(self, number: int) -> str | None:
        return self.folders.get(number)

    def ambiguous(self, number: int) -> bool:
        return number in self.ambiguous_numbers


def build_plan_index(project_root: Path, plan_dir: str | None) -> PlanIndex:
    """Every plan by number, an active plan preferred over an archived one.

    ``find_plans`` walks the whole tree, so ``Completed/`` is covered. A plan
    is archived when a path segment is ``Completed``. None: no plan directory.
    """
    if plan_dir is None:
        return PlanIndex({})
    tiers: dict[int, dict[bool, list[str]]] = {}
    for match in find_plans(project_root, plan_dir, ""):
        archived = _ARCHIVE_SEGMENT in Path(match.path).parts
        tiers.setdefault(match.number, {}).setdefault(archived, []).append(match.path)
    folders: dict[int, str] = {}
    ambiguous: set[int] = set()
    for number, by_tier in tiers.items():
        paths = by_tier.get(False) or by_tier[True]
        folders[number] = paths[0]
        if len(paths) > 1:
            ambiguous.add(number)
    return PlanIndex(folders, frozenset(ambiguous))


def move_command(relative_root: str, name: str, destination_dir: str) -> str:
    """``mv -n -- <src> <dest>/``, both sides quoted; empty when it would be unsafe.

    The trailing ``/`` is inside the quoted destination, so a missing folder
    makes ``mv`` fail rather than rename the file to the folder's name.
    """
    source = f"{relative_root}/{name}"
    target = f"{destination_dir}/"
    if not name or name.startswith("-") or not (source + target).isprintable():
        return ""
    return f"mv -n -- {shlex.quote(source)} {shlex.quote(target)}"


def propose(
    name: str,
    *,
    kind: NodeKind,
    size: int,
    verdict: Verdict,
    protection: Protection,
    plans: PlanIndex,
    project_root: Path,
    relative_root: str | None,
    max_bytes: int,
) -> FilingProposal | None:
    """The proposal for one entry, or None for a verdict that gets none."""
    if verdict not in _PROPOSED:
        return None
    if protection is Protection.REPOSITORY:
        return FilingProposal(HINT_REPOSITORY, "")
    if protection is Protection.TRACKED:
        return FilingProposal(HINT_TRACKED, "")
    if size > max_bytes:
        return FilingProposal(HINT_TOO_LARGE, "")
    plan = _plan_proposal(name, kind, plans, project_root, relative_root)
    if plan is not None:
        return plan
    lowered = name.lower()
    if Path(lowered).suffix in _SCRIPT_SUFFIXES:
        return FilingProposal(HINT_SCRIPT, "")
    if any(word in lowered for word in _RELEASE_WORDS):
        return FilingProposal(HINT_RELEASE, "")
    return FilingProposal(HINT_NO_HOME, "")


def _plan_proposal(
    name: str,
    kind: NodeKind,
    plans: PlanIndex,
    project_root: Path,
    relative_root: str | None,
) -> FilingProposal | None:
    prefix = _PLAN_PREFIX.match(name)
    if prefix is None:
        return None
    number = int(prefix.group(1))
    folder = plans.folder(number)
    if folder is None:
        return None
    reports = f"{folder}/{_REPORTS}"
    destination = f"{reports}/"
    single_file = kind is NodeKind.FILE and not plans.ambiguous(number)
    if not single_file or relative_root is None:
        return FilingProposal(destination, "")
    if os.path.lexists(project_root / reports / name):
        return FilingProposal(destination, "")
    return FilingProposal(destination, move_command(relative_root, name, reports))


__all__ = [
    "HINT_NO_HOME",
    "HINT_RELEASE",
    "HINT_REPOSITORY",
    "HINT_SCRIPT",
    "HINT_TOO_LARGE",
    "HINT_TRACKED",
    "FilingProposal",
    "PlanIndex",
    "Protection",
    "build_plan_index",
    "move_command",
    "propose",
]
