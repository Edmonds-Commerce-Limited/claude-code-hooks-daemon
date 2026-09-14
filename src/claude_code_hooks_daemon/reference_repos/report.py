"""One renderer for every surface that describes a governed repository.

Three consumers say these things — the SessionStart sweep, the PreToolUse
backstop and the CLI — and if each wrote its own wording they would drift.
Drift here is worse than untidy: an agent blocked by one sentence and then
handed a differently-worded answer by the CLI cannot tell whether it is looking
at the same problem or a second one.

Two rendering decisions carry real weight:

``only repos needing attention are listed``
    A report that recites every healthy repo is one a reader learns to skip,
    and the uncheckable canary would head the list forever. An all-clear is a
    single line; a project governing nothing says nothing at all.

``NOT VERIFIED is not the same sentence as STALE``
    "This is out of date" and "nobody has checked" demand different responses.
    Collapsing them would either cry wolf about repos that are fine or give
    false comfort about repos nobody looked at.

The remediation command is load-bearing twice: it is the instruction a reader
follows, and Phase 4 must EXEMPT it from interception — a handler that blocks
the command it just told you to run makes itself impossible to satisfy.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.reference_repos.model import RepoState

_ICON: Final[str] = "📚"

#: The distinct opening for "nobody has checked", kept as a constant so the
#: enforcing handler and the CLI cannot paraphrase it differently.
NOT_VERIFIED_HEADLINE: Final[str] = "reference repo freshness NOT VERIFIED"

_NOT_VERIFIED_DETAIL: Final[str] = (
    "no in-date reading exists (the cache is missing, expired or unusable), so these "
    "repos may be out of date. Run `hooks-daemon reference-repos` to refresh and see."
)


def display_path(path: Path, project_root: Path | None) -> str:
    """Show a governed repo the way a reader recognises it.

    Project-relative when it lives inside the project, absolute otherwise. The
    absolute case is not reachable through ``reference_repos.roots`` — that
    validator rejects a root escaping the repository — but it IS reachable
    through the CLI, which renders whatever readings it is handed, and through
    a cache written before a root was narrowed.

    Public because the PreToolUse gate names repos in its deny message too, and
    a second copy of this rule is exactly the drift this module exists to
    prevent: a repo called one thing when blocked and another thing when
    reported reads as two separate problems.
    """
    if project_root is not None and path.is_relative_to(project_root):
        return str(path.relative_to(project_root))
    return str(path)


def repo_line(state: RepoState, *, project_root: Path | None = None) -> str:
    """Render one repository's status as a single line."""
    name = display_path(state.path, project_root)

    if not state.checkable:
        return f"{name} — {state.reason}"

    problems: list[str] = []
    if state.fetch_failed:
        # Stated FIRST, because it qualifies everything after it: the counts
        # below were computed from refs already on disk, not from the remote.
        problems.append(
            "last fetch failed (offline, or the remote is unreachable), so this reading "
            "is from the refs already on disk"
        )
    if state.is_behind:
        upstream = state.upstream or "its upstream"
        problems.append(f"{state.behind} commit(s) behind {upstream}")
    if not state.is_on_default_branch:
        problems.append(
            f"on branch '{state.branch}', not the default branch '{state.default_branch}'"
        )
    if state.dirty:
        problems.append("uncommitted local changes")

    if not problems:
        return f"{name} — up to date"
    return f"{name} — {'; '.join(problems)}"


def remediation_command(state: RepoState) -> str | None:
    """The one command that fixes this repo, or ``None`` when there is none.

    Returns a single command rather than a sequence because a reader given three
    options runs none of them. Ordered by what must happen FIRST:

    - A dirty repo gets NO command. Every mechanical remedy here would move a
      tree carrying uncommitted work, which is the outcome the plan forbids
      outright — the human decides what happens to their changes.
    - Being on the wrong branch outranks being behind: pulling a feature branch
      to catch it up does not get the reader to the source they meant to read.
    """
    if not state.checkable or state.dirty:
        return None
    if not state.is_on_default_branch and state.default_branch:
        return f"git -C {state.path} checkout {state.default_branch}"
    if state.is_behind:
        # --ff-only, never a plain pull: the remedy must not invent a merge
        # commit in a repository the reader only meant to read.
        return f"git -C {state.path} pull --ff-only"
    return None


def report_lines(
    states: Iterable[RepoState] | None,
    *,
    project_root: Path | None = None,
    max_listed: int | None = None,
) -> list[str]:
    """Render the whole report, for any surface.

    Args:
        states: The readings, or ``None`` meaning nothing is known. ``None`` and
            an empty iterable are different answers and render differently.
        project_root: Used to shorten paths that live inside the project.
        max_listed: Cap on how many repos are listed individually, or ``None``
            for all of them. SessionStart passes a cap because it is one
            advisory among several and a long list pushes the others out of
            view; the CLI leaves it unbounded, because a report you ASKED for
            should show everything. The total is stated either way — a
            truncated list that hid the real count would understate the problem.

    Returns:
        Lines to print. Empty when the project governs no repositories — a
        project that has not adopted the convention should hear nothing.
    """
    if states is None:
        return [f"{_ICON}  {NOT_VERIFIED_HEADLINE}: {_NOT_VERIFIED_DETAIL}"]

    readings = list(states)
    if not readings:
        return []

    attention = [state for state in readings if state.needs_attention]
    verified = [state for state in readings if state.verified]
    unverified = len(readings) - len(verified)

    if not attention:
        # Counting an UNVERIFIED repo as "up to date" would be a false
        # all-clear: nobody confirmed it, and unknown is not the same answer as
        # fine. Two different repos land here — one with no remote to check
        # against, and one whose remote could not be reached — and both are
        # stated as a bounded count rather than a list, so a permanently
        # unreachable clone cannot head the report forever.
        if not verified:
            return [f"{_ICON}  reference repos: {len(readings)} governed, none verifiable"]
        suffix = f" ({unverified} could not be checked against their remotes)" if unverified else ""
        return [f"{_ICON}  reference repos: all {len(verified)} up to date{suffix}"]

    lines = [
        f"{_ICON}  reference repos: {len(attention)} of {len(readings)} need attention "
        "BEFORE you rely on what they contain"
    ]
    listed = attention if max_listed is None else attention[:max_listed]
    for state in listed:
        lines.append(f"  - {repo_line(state, project_root=project_root)}")
        command = remediation_command(state)
        if command is not None:
            lines.append(f"      fix: {command}")

    withheld = len(attention) - len(listed)
    if withheld > 0:
        lines.append(f"  … and {withheld} more (run `hooks-daemon reference-repos` for all)")
    if unverified:
        lines.append(
            f"  ({unverified} could not be checked against their remotes — "
            "`hooks-daemon reference-repos --all` says why)"
        )
    return lines
