"""Check ``header-body-coherence`` (Stage 1 + 2 + 3; sins A3, A1).

A plan whose header claims ``Not Started`` or ``In Progress`` but whose body
already claims completion (every checkbox ticked, or a prose "all done"
marker) is lying to the reader: the header is the source of truth tooling
reads, and it must not contradict the body it summarises.

**The completion branch ADVISES at EDIT and BLOCKS at COMMIT and SWEEP**, and
the asymmetry is the whole design (Plan 00419 N3). Closing a plan needs two
changes to one document — tick the last Success Criterion, and flip the status
header — and the ``Edit`` tool replaces ONE contiguous span, which the header
(line 3) and the criteria (near the end) never share. Blocking the completion
branch at EDIT therefore denied both orderings: ticking first produced an
all-ticked ``In Progress`` document denied here, and flipping first produced a
``Complete`` document with an unticked holding-area criterion denied by the
project's own ``plan_done_requires_holding_area`` handler. The only remaining
single-call move was a whole-file ``Write``, which is exactly what
``R-WRITE-CLOBBER`` exists to discourage on a document this load-bearing.

A gate that no legal sequence of moves can satisfy is a defect, not a policy.
So the all-ticked-under-``In Progress`` state — the MANDATORY intermediate on
the legal close path — is advisory at edit time, and the invariant is enforced
where the state is SETTLED rather than half-written: at the commit gate and in
the sweep, which is where "finished work still marked In Progress" is real rot.
That is a net TIGHTENING, not a relaxation: this check carried no COMMIT
registration, so a plan committed in the violating state reached history
unchallenged and waited for the next session's sweep.

The ``Not Started`` with some boxes ticked branch keeps blocking at EDIT. It is
not part of the sequencing problem — flipping that header is a legal one-call
fix, because no box is being ticked in the same edit.
"""

from enum import StrEnum
from typing import Final

from claude_code_hooks_daemon.plan_qa.checks.common import (
    commit_scoped_level,
    edit_target,
    level_for_plan,
    staged_plan_md_folder,
    tree_targets,
)
from claude_code_hooks_daemon.plan_qa.model import PlanDoc, PlanStatus
from claude_code_hooks_daemon.plan_qa.types import (
    CheckContext,
    CheckSpec,
    Finding,
    Level,
    Stage,
)

CHECK_ID: Final[str] = "header-body-coherence"
_SINS: Final[tuple[str, ...]] = ("A3", "A1")

_NON_TERMINAL_STATUSES: Final[frozenset[PlanStatus]] = frozenset(
    {PlanStatus.NOT_STARTED, PlanStatus.IN_PROGRESS}
)

_NEW_OR_MODIFIED_STATUSES: Final[tuple[str, ...]] = ("A", "M")
_RENAME_STATUS_PREFIX: Final[str] = "R"

_REMEDIATION: Final[str] = (
    "Flip the status header to `**Status**: Complete` (and move the plan to the "
    "archive directory per the plan lifecycle), or untick/remove the completion "
    "claims that contradict the current header."
)

# Plan 00341: a SECOND remediation, not a reworded first one. Telling the
# author of a half-delivered plan to mark it Complete would be actively wrong,
# which is why "started" and "finished" cannot share one message.
_STARTED_REMEDIATION: Final[str] = (
    "Flip the status header to `**Status**: In Progress`, or untick the boxes "
    "that contradict `Not Started`."
)


class _Violation(StrEnum):
    """Which contradiction a document carries.

    Named rather than implied, because the two branches differ in remediation
    AND in which stages may block on them — a boolean could carry neither
    distinction.
    """

    COMPLETION = "completion"
    STARTED = "started"


def _violation(doc: PlanDoc) -> _Violation | None:
    """The contradiction ``doc`` carries, or ``None`` when it is coherent.

    Completion is tested FIRST because both branches match a ``Not Started``
    plan with every box ticked, and "you finished this" is the more useful
    correction than "you started this".
    """
    if doc.status is None or doc.status not in _NON_TERMINAL_STATUSES:
        return None

    if doc.done_marker_count > 0 or doc.tasks.all_checked:
        return _Violation.COMPLETION

    # Plan 00341: a single ticked box falsifies "not started" on its own, with
    # no history needed to see it. The all-checked branch above cannot catch a
    # partially-delivered plan, which is exactly how a status header rots
    # behind shipped work.
    if doc.status is PlanStatus.NOT_STARTED and doc.tasks.checked > 0:
        return _Violation.STARTED

    return None


def _finding(violation: _Violation, doc: PlanDoc, level: Level, rel_path: str) -> Finding:
    if violation is _Violation.COMPLETION:
        status = doc.status.value if doc.status is not None else "unknown"
        message = f"PLAN.md header claims `{status}` but the body claims completion"
        remediation = _REMEDIATION
    else:
        message = (
            "PLAN.md header claims `Not Started` but the body shows work already "
            f"started ({doc.tasks.checked} of {doc.tasks.total_checkboxes} boxes ticked)"
        )
        remediation = _STARTED_REMEDIATION

    return Finding(
        check_id=CHECK_ID,
        level=level,
        message=message,
        remediation=remediation,
        path=rel_path,
    )


def _run_edit(context: CheckContext) -> list[Finding]:
    """Stage 1: the would-be content of a Write/Edit to one PLAN.md."""
    target = edit_target(context)
    if target is None:
        return []

    violation = _violation(target.doc)
    if violation is None:
        return []

    level = level_for_plan(context, target.plan_number)
    if violation is _Violation.COMPLETION:
        # The mandatory intermediate on the legal close path — see the module
        # docstring. Reported so the author is told what to do next, never
        # blocked, because the next legal move is the one that clears it.
        level = Level.ADVISE
    return [_finding(violation, target.doc, level, target.rel_path)]


def _run_commit(context: CheckContext) -> list[Finding]:
    """Stage 2: every PLAN.md this commit stages, judged as it will land.

    Scoped to STAGED plan documents rather than the whole tree, so a commit
    that goes nowhere near an incoherent plan is never blamed for it. For the
    one it does touch, :func:`commit_scoped_level` keeps Plan 00343's rule:
    BLOCK for state this commit introduces, ADVISE for state it inherited.
    """
    gitfacts = context.gitfacts
    if gitfacts is None:
        return []

    findings: list[Finding] = []
    for change in gitfacts.staged_changes():
        is_new_or_renamed = change.status in _NEW_OR_MODIFIED_STATUSES or change.status.startswith(
            _RENAME_STATUS_PREFIX
        )
        if not is_new_or_renamed:
            continue
        if staged_plan_md_folder(change.path, context.plan_dir_rel) is None:
            continue

        staged_text = gitfacts.staged_file_text(change.path)
        if staged_text is None:
            continue
        staged_doc = PlanDoc.parse(staged_text)
        violation = _violation(staged_doc)
        if violation is None:
            continue

        head_text = gitfacts.head_file_text(change.old_path or change.path)
        pre_existing = head_text is not None and _violation(PlanDoc.parse(head_text)) is violation
        level = commit_scoped_level(context, staged_doc.plan_number, pre_existing=pre_existing)
        findings.append(_finding(violation, staged_doc, level, change.path))

    return findings


def _run_sweep(context: CheckContext) -> list[Finding]:
    """Stage 3: every plan document already on disk.

    A sweep has no commit to attribute anything to and nothing half-written in
    front of it, so both branches carry their full level here.
    """
    findings: list[Finding] = []
    for target in tree_targets(context):
        violation = _violation(target.doc)
        if violation is None:
            continue
        level = level_for_plan(context, target.plan_number)
        findings.append(_finding(violation, target.doc, level, target.rel_path))
    return findings


CHECKS: Final[tuple[CheckSpec, CheckSpec, CheckSpec]] = (
    # Nominally BLOCK at every stage: the level here describes the STRONGEST
    # finding a registration can raise, and the edit surface still blocks the
    # `Not Started` branch. Declaring it ADVISE would understate it wherever
    # this catalogue is rendered as documentation.
    CheckSpec(check_id=CHECK_ID, stage=Stage.EDIT, level=Level.BLOCK, sins=_SINS, run=_run_edit),
    CheckSpec(
        check_id=CHECK_ID, stage=Stage.COMMIT, level=Level.BLOCK, sins=_SINS, run=_run_commit
    ),
    CheckSpec(check_id=CHECK_ID, stage=Stage.SWEEP, level=Level.BLOCK, sins=_SINS, run=_run_sweep),
)
