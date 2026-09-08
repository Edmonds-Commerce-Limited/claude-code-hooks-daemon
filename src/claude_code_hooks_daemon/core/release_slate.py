"""Release slate-clean report (Plan 00359).

Every release gate in RELEASING.md looks at the CODE: QA, review, acceptance.
None looks at the state of the WORK around it. So a release could begin on a
HEAD that CI never passed, over plans mid-work, with unlanded branches and live
worktrees, and every gate would pass. This module puts all of that on one
screen and says whether there is anything for a human to decide.

It REPORTS; it does not rank and it does not touch anything. Which in-flight
item matters is scope, and scope is the human's call.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.plan_qa.model import PlanDoc, PlanStatus

# A plan that is In Progress ONLY because it is waiting for this very release
# says so in its status line. Recognising that from its own words is a
# heuristic (Plan 00359 Decision 2): the cost of a miss is a plan shown under
# the wrong heading in a report a human reads, never a release proceeding
# unseen, so the heuristic is acceptable.
_RELEASE_GATED_MARKER: Final[str] = "/release"
_ATTENTION_PRIORITY: Final[str] = "high"
_PLAN_FILENAME: Final[str] = "PLAN.md"
_MAIN_BRANCH: Final[str] = "main"
_CI_SUCCESS: Final[str] = "success"
_CI_COMPLETED: Final[str] = "completed"

RunGit = Callable[..., "subprocess.CompletedProcess[str]"]
CiLookup = Callable[[str], "CiRunState | None"]


@dataclass(frozen=True)
class PlanSummary:
    number: int
    title: str
    status_raw: str


@dataclass(frozen=True)
class BranchAhead:
    name: str
    ahead: int


@dataclass(frozen=True)
class CiRunState:
    """What CI recorded for one sha. ``conclusion`` is None while running."""

    sha: str
    status: str | None
    conclusion: str | None
    problem: str = ""

    @property
    def is_green(self) -> bool:
        """Completed AND successful. In-progress, cancelled and absent are not."""
        return self.status == _CI_COMPLETED and self.conclusion == _CI_SUCCESS

    def describe(self) -> str:
        if self.problem:
            return f"could not determine ({self.problem})"
        if self.status is None:
            return "no CI run found for this sha"
        # `gh run list` reports a still-running run's conclusion as "" rather
        # than null, so "no conclusion yet" has two spellings.
        if not self.conclusion:
            return self.status
        return f"{self.status}, {self.conclusion}"


@dataclass(frozen=True)
class SlateReport:
    head_sha: str
    head_ci: CiRunState
    in_flight_plans: tuple[PlanSummary, ...]
    release_gated_plans: tuple[PlanSummary, ...]
    attention_plans: tuple[PlanSummary, ...]
    branches_ahead: tuple[BranchAhead, ...]
    worktrees: tuple[Path, ...]

    @property
    def is_clean(self) -> bool:
        """Nothing for a human to decide.

        Attention plans do not count: they are surfaced, but whether a
        high-priority unstarted plan should hold a release is scope, not state.
        """
        return (
            self.head_ci.is_green
            and not self.in_flight_plans
            and not self.branches_ahead
            and not self.worktrees
        )

    def render(self) -> str:
        lines = [f"HEAD {self.head_sha[:8]}: CI {self.head_ci.describe()}"]
        lines.append(_section("In flight (mid-work plans)", _plan_lines(self.in_flight_plans)))
        lines.append(
            _section(
                "Waiting for this release (not blockers)",
                _plan_lines(self.release_gated_plans),
            )
        )
        lines.append(_section("High priority, not started", _plan_lines(self.attention_plans)))
        lines.append(
            _section(
                "Branches ahead of main",
                [f"{b.name} (+{b.ahead})" for b in self.branches_ahead],
            )
        )
        lines.append(_section("Live worktrees", [str(p) for p in self.worktrees]))
        lines.append("")
        lines.append("Slate: CLEAN" if self.is_clean else "Slate: NOT CLEAN — a human decides")
        return "\n".join(lines)


def _section(title: str, items: list[str]) -> str:
    if not items:
        return f"\n{title}: none"
    body = "\n".join(f"  - {item}" for item in items)
    return f"\n{title}:\n{body}"


def _plan_lines(plans: tuple[PlanSummary, ...]) -> list[str]:
    return [f"{p.number:05d} {p.title} — {p.status_raw}" for p in plans]


def _git_lines(run_fn: RunGit, repo_root: Path, *args: str) -> list[str]:
    result = run_fn(repo_root, *args)
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if line.strip()]


def _head_sha(run_fn: RunGit, repo_root: Path) -> str:
    lines = _git_lines(run_fn, repo_root, "rev-parse", "HEAD")
    return lines[0].strip() if lines else ""


def _branches_ahead(run_fn: RunGit, repo_root: Path) -> tuple[BranchAhead, ...]:
    names = _git_lines(
        run_fn, repo_root, "for-each-ref", "--format=%(refname:short)", "refs/heads/"
    )
    found: list[BranchAhead] = []
    for name in names:
        name = name.strip()
        if name == _MAIN_BRANCH:
            continue
        count_lines = _git_lines(
            run_fn, repo_root, "rev-list", "--count", f"{_MAIN_BRANCH}..{name}"
        )
        ahead = int(count_lines[0]) if count_lines and count_lines[0].strip().isdigit() else 0
        if ahead > 0:
            found.append(BranchAhead(name=name, ahead=ahead))
    return tuple(found)


def _worktrees(run_fn: RunGit, repo_root: Path) -> tuple[Path, ...]:
    listing = _git_lines(run_fn, repo_root, "worktree", "list", "--porcelain")
    paths: list[Path] = []
    for line in listing:
        if line.startswith("worktree "):
            path = Path(line[len("worktree ") :].strip())
            if path.resolve() != repo_root.resolve():
                paths.append(path)
    return tuple(paths)


def _plan_docs(plan_root: Path, archive_dir_names: frozenset[str]) -> list[tuple[PlanDoc, Path]]:
    docs: list[tuple[PlanDoc, Path]] = []
    if not plan_root.is_dir():
        return docs
    for folder in sorted(plan_root.iterdir()):
        if not folder.is_dir() or folder.name in archive_dir_names:
            continue
        plan_file = folder / _PLAN_FILENAME
        if not plan_file.is_file():
            continue
        docs.append((PlanDoc.parse(plan_file.read_text(encoding="utf-8")), folder))
    return docs


def _summary(doc: PlanDoc, folder: Path) -> PlanSummary:
    return PlanSummary(
        number=doc.plan_number if doc.plan_number is not None else 0,
        title=doc.title or folder.name,
        status_raw=doc.status_raw or "",
    )


def _classify_plans(
    plan_root: Path, archive_dir_names: frozenset[str]
) -> tuple[tuple[PlanSummary, ...], tuple[PlanSummary, ...], tuple[PlanSummary, ...]]:
    in_flight: list[PlanSummary] = []
    release_gated: list[PlanSummary] = []
    attention: list[PlanSummary] = []
    for doc, folder in _plan_docs(plan_root, archive_dir_names):
        if doc.status is PlanStatus.IN_PROGRESS:
            if _RELEASE_GATED_MARKER in (doc.status_raw or ""):
                release_gated.append(_summary(doc, folder))
            else:
                in_flight.append(_summary(doc, folder))
        elif (
            doc.status is PlanStatus.NOT_STARTED
            and (doc.priority or "").strip().lower() == _ATTENTION_PRIORITY
        ):
            attention.append(_summary(doc, folder))
    return tuple(in_flight), tuple(release_gated), tuple(attention)


def _head_ci(ci_lookup: CiLookup, sha: str) -> CiRunState:
    """Never lets a lookup failure read as clean: a problem is reported, and is not green."""
    try:
        state = ci_lookup(sha)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        return CiRunState(sha=sha, status=None, conclusion=None, problem=str(exc))
    if state is None:
        return CiRunState(sha=sha, status=None, conclusion=None)
    return state


def collect_slate(
    *,
    repo_root: Path,
    plan_root: Path,
    archive_dir_names: frozenset[str],
    run_fn: RunGit,
    ci_lookup: CiLookup,
) -> SlateReport:
    """Everything a human would want on one screen before a release begins."""
    head = _head_sha(run_fn, repo_root)
    in_flight, release_gated, attention = _classify_plans(plan_root, archive_dir_names)
    return SlateReport(
        head_sha=head,
        head_ci=_head_ci(ci_lookup, head),
        in_flight_plans=in_flight,
        release_gated_plans=release_gated,
        attention_plans=attention,
        branches_ahead=_branches_ahead(run_fn, repo_root),
        worktrees=_worktrees(run_fn, repo_root),
    )
