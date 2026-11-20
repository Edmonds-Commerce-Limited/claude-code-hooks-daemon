"""Scratch paths a tracked file names: the reference set (Plan 00627 Task 2.4).

DESIGN.md section 3.4. The set is built once per sweep with two ``git grep``
runs in the project: one over the revisions that can still reach the default
branch (HEAD, the local default tip, and every local branch not merged into it;
every local branch when there is no local default), and one over the working
tree's tracked files, so an uncommitted edit counts too. A match must be the
root's path followed by a path character: a bare word is never a reference.

Fail closed. Any git failure, timeout or output that does not parse, an empty
revision list, or a root or entry name the search cannot match, makes the
answer UNKNOWN, and an unknown answer is STUCK in the verdict, never "nothing
references it". Only ``rc 0`` with records, or ``rc 1`` with empty output, is
a known answer.

The path character class is ``[A-Za-z0-9._+@~/-]``. It adds ``_``, ``+``,
``@`` and ``~`` to DESIGN.md's class, so ``probe_run`` is found whole.
"""

from __future__ import annotations

import posixpath
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final

from claude_code_hooks_daemon.core.scratch_repos import ProjectGit

#: One character a referenced path may hold.
PATH_CLASS: Final[str] = "[A-Za-z0-9._+@~/-]"
#: Characters stripped from a match's end to form extra candidates (over-protects only).
_TRAILING: Final[str] = "._+@~/-"
#: One ``git grep`` may run this long; a timeout is UNKNOWN.
REFERENCE_GREP_TIMEOUT: Final[float] = 120.0

#: Said for an entry whose name holds a character the search cannot match.
UNSEARCHABLE_NAME: Final[str] = (
    "the entry name holds a character a reference search cannot match, "
    "so whether a tracked file names it is unknown"
)

_NAME: Final[re.Pattern[str]] = re.compile(f"{PATH_CLASS}+")
_SHA: Final[re.Pattern[str]] = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
_REV_RECORD: Final[re.Pattern[str]] = re.compile(
    f"([0-9a-f]{{40}}|[0-9a-f]{{64}}):([^\\0]*)\\0([0-9]+)\\0({PATH_CLASS}+)\\n"
)
_TREE_RECORD: Final[re.Pattern[str]] = re.compile(f"([^\\0]*)\\0([0-9]+)\\0({PATH_CLASS}+)\\n")
_HEADS: Final[str] = "refs/heads/"
_WORKING_TREE: Final[str] = "working tree"

#: Flags before ``grep``, so the project's config cannot change the output format.
_GREP_CONFIG: Final[tuple[str, ...]] = (
    "-c",
    "grep.column=false",
    "-c",
    "grep.fullName=false",
    "-c",
    "grep.fallbackToNoIndex=false",
    "-c",
    "submodule.recurse=false",
    "-c",
    "core.quotePath=false",
)
_GREP_FLAGS: Final[tuple[str, ...]] = ("-a", "-z", "-o", "-n", "--no-color", "-E")


@dataclass(frozen=True)
class References:
    """What the reference set says about one entry."""

    #: ``<label>:<path>:<line>`` of each tracked line naming the entry.
    sites: tuple[str, ...]
    #: Why the answer is unknown; "" when it is known.
    unknown: str = ""


@dataclass(frozen=True)
class ReferenceSet:
    """Every entry a tracked file names, by entry name; or why that is unknown."""

    sites: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    unknown: str = ""

    def for_entry(self, name: str) -> References:
        """The entry's references; unknown when the set is, or the name is unsearchable."""
        if self.unknown:
            return References((), self.unknown)
        if not _NAME.fullmatch(name):
            return References((), UNSEARCHABLE_NAME)
        return References(self.sites.get(name, ()))


class _Unknown(Exception):
    """The reference set cannot be known; the message says why."""


def _pattern(relative_root: str) -> str:
    escaped = relative_root.replace(".", "[.]").replace("+", "[+]")
    return f"{escaped}/{PATH_CLASS}+"


def _branch_listing(project: ProjectGit, *extra: str) -> list[tuple[str, str]]:
    result = project.runner(
        project.root, "for-each-ref", "--format=%(objectname) %(refname)", *extra, _HEADS
    )
    if result.returncode != 0:
        raise _Unknown(f"the project's branches could not be listed ({result.returncode})")
    pairs: list[tuple[str, str]] = []
    for line in result.stdout.splitlines():
        sha, _, ref = line.partition(" ")
        if not _SHA.fullmatch(sha) or not ref.startswith(_HEADS):
            raise _Unknown("the project's branch listing could not be parsed")
        pairs.append((sha, ref.removeprefix(_HEADS)))
    return pairs


def _revisions(project: ProjectGit) -> dict[str, str]:
    """The shas to search, each with its label, HEAD first."""
    head = project.runner(project.root, "rev-parse", "--verify", "--quiet", "HEAD^{commit}")
    head_sha = head.stdout.strip()
    if head.returncode != 0 or not _SHA.fullmatch(head_sha):
        raise _Unknown(f"the project's HEAD could not be resolved ({head.returncode})")
    branches = _branch_listing(project)
    if not branches:
        raise _Unknown("the project has no local branch")
    revs: dict[str, str] = {head_sha: "HEAD"}
    default = project.default_branch
    default_tip = next((sha for sha, name in branches if name == default), None)
    if default_tip is not None:
        wanted = [(default_tip, str(default))]
        wanted.extend(_branch_listing(project, f"--no-merged={_HEADS}{default}"))
    else:
        wanted = branches
    for sha, name in wanted:
        revs.setdefault(sha, name)
    return revs


def _grep(project: ProjectGit, pattern: str, revs: Sequence[str]) -> str:
    """Run one search; ``revs`` empty means the working tree, by the caller's choice."""
    result = project.runner(
        project.root,
        *_GREP_CONFIG,
        "grep",
        *_GREP_FLAGS,
        "-e",
        pattern,
        *revs,
        "--",
        timeout=REFERENCE_GREP_TIMEOUT,
    )
    if result.returncode == 1 and not result.stdout:
        return ""
    if result.returncode != 0 or not result.stdout:
        raise _Unknown(f"git grep failed ({result.returncode}): {result.stderr.strip()[:200]}")
    return result.stdout


def _records(output: str, record: re.Pattern[str]) -> list[tuple[str | None, str, str, str]]:
    """``(sha or None, path, line, match)`` per record; the whole output must parse."""
    found: list[tuple[str | None, str, str, str]] = []
    position = 0
    while position < len(output):
        matched = record.match(output, position)
        if matched is None:
            raise _Unknown("git grep's output could not be parsed")
        groups = matched.groups()
        if len(groups) == 4:
            found.append((groups[0], groups[1], groups[2], groups[3]))
        else:
            found.append((None, groups[0], groups[1], groups[2]))
        position = matched.end()
    return found


def _entries_named(match: str, relative_root: str) -> set[str]:
    """Every entry name a matched path could mean; stripping only adds candidates."""
    prefix = f"{relative_root}/"
    if not match.startswith(prefix):
        raise _Unknown("git grep returned a match outside the root")
    rest = match[len(prefix) :]
    names: set[str] = set()
    for form in {rest, rest.rstrip("./"), rest.rstrip(_TRAILING)}:
        candidates = [form]
        resolved = posixpath.normpath(f"{relative_root}/{form}")
        if resolved.startswith(prefix):
            candidates.append(resolved[len(prefix) :])
        for candidate in candidates:
            first = candidate.split("/", 1)[0]
            if first not in ("", ".", ".."):
                names.add(first)
    return names


def build_references(project: ProjectGit | None, relative_root: str | None) -> ReferenceSet:
    """The reference set for the root at ``relative_root`` (from the project root)."""
    if project is None:
        return ReferenceSet(unknown="the project's git was not read")
    if relative_root is None:
        return ReferenceSet(unknown="the scratch root is outside the project")
    if not _NAME.fullmatch(relative_root):
        return ReferenceSet(
            unknown="the scratch root's path holds a character the search cannot match"
        )
    try:
        revs = _revisions(project)
        if not revs:
            raise _Unknown("no revision to search")
        pattern = _pattern(relative_root)
        found = _records(_grep(project, pattern, list(revs)), _REV_RECORD)
        found.extend(_records(_grep(project, pattern, []), _TREE_RECORD))
    except _Unknown as unknown:
        return ReferenceSet(unknown=f"references from tracked files: {unknown}")
    sites: dict[str, list[str]] = {}
    for sha, path, line, match in found:
        if sha is not None and sha not in revs:
            return ReferenceSet(
                unknown="references from tracked files: git grep named an unasked revision"
            )
        label = _WORKING_TREE if sha is None else revs[sha]
        site = f"{label}:{path}:{line}"
        try:
            names = _entries_named(match, relative_root)
        except _Unknown as unknown:
            return ReferenceSet(unknown=f"references from tracked files: {unknown}")
        for name in names:
            listed = sites.setdefault(name, [])
            # The working tree repeats every committed line HEAD already showed.
            if site not in listed and not (sha is None and f"HEAD:{path}:{line}" in listed):
                listed.append(site)
    return ReferenceSet({name: tuple(listed) for name, listed in sites.items()})


__all__ = [
    "PATH_CLASS",
    "REFERENCE_GREP_TIMEOUT",
    "UNSEARCHABLE_NAME",
    "ReferenceSet",
    "References",
    "build_references",
]
