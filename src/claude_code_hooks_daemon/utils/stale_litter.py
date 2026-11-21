"""Report-only detection of litter an always-on checkout accumulates.

Plan 00470 Task 4.1 follow-up. REPORT-FIRST, like
:mod:`claude_code_hooks_daemon.utils.stale_checkouts`: this module reads git,
deletes nothing, and prints the command a human or agent MAY choose to run.
Nothing here runs it. Scratch is not reported here: the scratch sweep
(Plan 00627) judges it, and the idle advisory reads that sweep's inventory.

* ``refs/integration/changed-green/<branch>`` refs whose branch no longer
  exists anywhere. The QA ``changed`` tier writes one when a branch goes green
  and never prunes it, and each one pins its commit against ``git gc``. A ref is
  reported only when NO local branch and NO remote-tracking branch carries the
  name, so a branch that still exists keeps its record.
"""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.utils.git_repo import HEADS_PREFIX
from claude_code_hooks_daemon.utils.stale_checkouts import ScanDeadline

#: Refs the report names; the rest are counted. The one command covers all of them.
MAX_LISTED_REFS: Final[int] = 5

#: Budget for the git calls of the gone-branch ref scan.
REF_SCAN_BUDGET_SECONDS: Final[float] = 5.0

#: The QA ``changed`` tier's per-branch record. The script that writes it
#: (``scripts/qa/llm_qa.py``) cannot be imported from here: keep the spellings in step.
CHANGED_GREEN_PREFIX: Final[str] = "refs/integration/changed-green/"

_REMOTES_PREFIX: Final[str] = "refs/remotes/"


def _remote_branch_names(refname: str, remotes: tuple[str, ...]) -> set[str]:
    """The branch name(s) a ``refs/remotes/...`` ref can stand for.

    The remote is matched against the configured remote names (longest first),
    because a remote name may itself contain a slash. A ref under no configured
    remote has no known split, so every tail after a slash counts as live: a
    branch is never reported gone on a guess.
    """
    rest = refname.removeprefix(_REMOTES_PREFIX)
    for remote in sorted(remotes, key=len, reverse=True):
        if rest.startswith(f"{remote}/"):
            return {rest.removeprefix(f"{remote}/")}
    return {rest[index + 1 :] for index, char in enumerate(rest) if char == "/"}


def _gone_branch_refs(repo_root: Path, deadline: ScanDeadline) -> tuple[str, ...] | None:
    """Changed-green refs whose branch exists nowhere, or None when git cannot say."""
    remote_listing = deadline.run(repo_root, "remote")
    if remote_listing.returncode != 0:
        return None
    remotes = tuple(remote_listing.stdout.splitlines())
    listing = deadline.run(
        repo_root,
        "for-each-ref",
        "--format=%(refname)",
        HEADS_PREFIX,
        _REMOTES_PREFIX,
        CHANGED_GREEN_PREFIX,
    )
    if listing.returncode != 0:
        return None
    recorded: list[str] = []
    live: set[str] = set()
    for refname in listing.stdout.splitlines():
        if refname.startswith(CHANGED_GREEN_PREFIX):
            recorded.append(refname)
        elif refname.startswith(HEADS_PREFIX):
            live.add(refname.removeprefix(HEADS_PREFIX))
        elif refname.startswith(_REMOTES_PREFIX):
            live |= _remote_branch_names(refname, remotes)
    return tuple(ref for ref in recorded if ref.removeprefix(CHANGED_GREEN_PREFIX) not in live)


def collect_gone_branch_ref_report(
    repo_root: Path,
    *,
    budget_seconds: float = REF_SCAN_BUDGET_SECONDS,
    deadline: ScanDeadline | None = None,
) -> str | None:
    """The report on changed-green refs of branches that no longer exist, or None.

    Quiet when git cannot answer, no ref is recorded, or every recorded branch
    still exists locally or on a remote. At most ``MAX_LISTED_REFS`` refs are
    named; the single command covers every one, so the report stays short however
    many refs have piled up. ``deadline`` is a budget shared with other scans.
    """
    shared = deadline or ScanDeadline(budget_seconds)
    gone = _gone_branch_refs(repo_root, shared)
    if not gone and not shared.exhausted:
        return None
    lines = [
        "CHANGED-GREEN REFS OF GONE BRANCHES (report only; this advisory never runs "
        "the command below - inspect, then choose):"
    ]
    if shared.exhausted:
        lines.append("SCAN INCOMPLETE: the time budget ran out before git answered.")
    if gone:
        noun = "ref" if len(gone) == 1 else "refs"
        lines.append(
            f"{len(gone)} changed-green {noun} whose branch no longer exists locally or on a remote:"
        )
        lines.extend(f"  - {ref}" for ref in gone[:MAX_LISTED_REFS])
        if len(gone) > MAX_LISTED_REFS:
            lines.append(f"  ... and {len(gone) - MAX_LISTED_REFS} more")
        quoted = " ".join(shlex.quote(ref) for ref in gone)
        lines.append(f"      printf 'delete %s\\n' {quoted} | git update-ref --stdin")
    return "\n".join(lines)
