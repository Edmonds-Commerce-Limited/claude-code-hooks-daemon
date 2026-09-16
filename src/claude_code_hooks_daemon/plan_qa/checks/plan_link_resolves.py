"""Check ``plan-link-resolves`` (SWEEP only, advise; Plan 00419 N2).

A live ``PLAN.md`` should state PRESENT truth, so a link it makes to a sibling
that has since been archived is worth repairing — the plan is editable, and a
human clicking the link on GitHub gets a 404 until someone does.

**Why this exists at all.** No plan-QA check resolved links, so
``plan-qa --sweep`` reported ``0 findings`` over eight dead links on the day
00413 was archived — twice. A sweep that says "clean" while a tree is not is
worse than no sweep, because it is believed.

**Why SWEEP only, and why never BLOCK.** Docs QA's ``pointer-resolves``
already blocks a link that is NEW in an edit or a commit; a second blocking
gate on the same fact is the double-gate shape the same ledger's N3 is about.
And a link that went dead because somebody else archived the target was not
introduced by the edit under judgement, so there is nothing for a gate to
refuse.

**Archived plans and journals are exempt**, and that is the rule this whole
remedy rests on rather than an omission: an archived plan is a RECORD ("truth
is enforced on LIVE plans, never on the historical record"), and a ``JOURNAL/``
day-file is append-only, so repointing an earlier entry is forbidden by
``journal-append-only`` — both directions observed as real handler output on
Plan 00408's day-file. ``tree_targets`` yields only ``PLAN.md``, so journals
never reach this check in the first place; the archive test is explicit.
"""

from typing import Final

from claude_code_hooks_daemon.plan_links import PlanLinkResolver, PlanTreeLayout
from claude_code_hooks_daemon.plan_qa.checks.common import DocumentTarget, tree_targets
from claude_code_hooks_daemon.plan_qa.types import (
    CheckContext,
    CheckSpec,
    Finding,
    Level,
    Stage,
)
from claude_code_hooks_daemon.utils.authored_paths import contained_authored_path
from claude_code_hooks_daemon.utils.markdown_links import extract_link_targets

CHECK_ID: Final[str] = "plan-link-resolves"

_EXTERNAL_SCHEME_PREFIXES: Final[tuple[str, ...]] = ("#", "mailto:")
_PLACEHOLDER_TOKENS: Final[tuple[str, ...]] = ("NNNNN", "X.Y.Z", "{", "*", "<")
_SCHEME_SEPARATOR: Final[str] = "://"
_MAX_REPORTED_LINKS: Final[int] = 10


def _is_skippable(target: str) -> bool:
    """Whether ``target`` is a shape this check never resolves.

    Mirrors ``docs_qa.checks.pointer_resolves._is_skippable``: an external
    URL, a ``mailto:``, a pure fragment and a template placeholder all name
    something that is not a repository file, so resolving them could only ever
    produce false positives. ``_TEMPLATE_.md``'s ``NNNNN`` is the placeholder
    that matters most here — it sits in the plan tree by design.
    """
    if not target or target.startswith(_EXTERNAL_SCHEME_PREFIXES):
        return True
    if _SCHEME_SEPARATOR in target:
        return True
    return any(token in target for token in _PLACEHOLDER_TOKENS)


def _layout(context: CheckContext) -> PlanTreeLayout:
    """The plan tree's shape, from the context's own policy mirror.

    ``completed_dir``/``cancelled_dir`` are already on the context, so this
    check introduces no config key — it only reads what the surface was told.
    """
    archives = tuple(
        dict.fromkeys(name for name in (context.completed_dir, context.cancelled_dir) if name)
    )
    return PlanTreeLayout(
        plan_dir=context.plan_dir_rel,
        archive_dirs=archives,
        journal_dir=context.journal_dir_name,
    )


def _resolves_literally(context: CheckContext, doc_dir_rel: str, target: str) -> bool:
    """Whether ``target`` exists at the path it literally names.

    Contained, not merely joined: the target is AUTHORED, and a plain
    existence answer over an escaping path is an oracle about the host
    filesystem rather than about this repository.
    """
    file_target = target.split("#", 1)[0]
    if not file_target:
        return True
    source_dir = contained_authored_path(context.project_root, doc_dir_rel)
    if source_dir is None:
        return False
    resolved = contained_authored_path(source_dir, file_target, within=context.project_root)
    return resolved is not None and resolved.exists()


def _run_sweep(context: CheckContext) -> list[Finding]:
    layout = _layout(context)
    resolver = PlanLinkResolver(context.project_root, layout)
    findings: list[Finding] = []
    for target in tree_targets(context):
        if target.in_archive:
            continue
        findings.extend(_document_findings(context, resolver, target))
    return findings


def _document_findings(
    context: CheckContext, resolver: PlanLinkResolver, target: DocumentTarget
) -> list[Finding]:
    doc_dir_rel = target.rel_path.rsplit("/", 1)[0]
    source_dir = context.project_root / doc_dir_rel
    moved: list[str] = []
    repoints: list[str] = []
    dead: list[str] = []
    for link in extract_link_targets(target.text):
        if _is_skippable(link) or _resolves_literally(context, doc_dir_rel, link):
            continue
        relocated = resolver.resolve(source_dir, link)
        if relocated is None:
            if link not in dead:
                dead.append(link)
            continue
        if link in moved:
            continue
        moved.append(link)
        repoints.append(f"`{link}` -> `{resolver.suggested_link(source_dir, relocated)}`")

    findings: list[Finding] = []
    if moved:
        reported = ", ".join(moved[:_MAX_REPORTED_LINKS])
        findings.append(
            Finding(
                check_id=CHECK_ID,
                level=Level.ADVISE,
                message=f"PLAN.md links to plan(s) that have been archived: {reported}",
                remediation=(
                    "Repoint: "
                    + "; ".join(repoints[:_MAX_REPORTED_LINKS])
                    + ". The plan was archived, not deleted — a live plan should state "
                    "present truth."
                ),
                path=target.rel_path,
            )
        )
    if dead:
        reported = ", ".join(dead[:_MAX_REPORTED_LINKS])
        findings.append(
            Finding(
                check_id=CHECK_ID,
                level=Level.ADVISE,
                message=f"PLAN.md link target(s) do not exist: {reported}",
                remediation=(
                    "Fix or remove each link (create the target, correct the path, or "
                    "delete the dead link)."
                ),
                path=target.rel_path,
            )
        )
    return findings


CHECKS: Final[tuple[CheckSpec, ...]] = (
    CheckSpec(
        check_id=CHECK_ID,
        stage=Stage.SWEEP,
        level=Level.ADVISE,
        sins=("E5",),
        run=_run_sweep,
    ),
)
