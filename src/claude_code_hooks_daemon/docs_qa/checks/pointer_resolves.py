"""Check ``pointer-resolves`` (EDIT + STAGED + SWEEP; DESIGN §2.1 refinements).

R6 — "Links are plain and resolve": a plain markdown link
``[text](target)`` whose target FILE does not exist is a finding. This
slice implements FILE-existence resolution only; anchor (``#fragment``)
resolution is explicitly deferred (the design's slug-variance caveat), so
a fragment is stripped before checking rather than resolved.

Block eligibility (structural, DESIGN §2.1): a check not marked
block-eligible ignores a ``block`` mode override. This check IS
block-eligible, but ONLY for a link that is NEW in this edit — a link
already present before the edit is reported as ADVISE even when broken,
because the edit did not introduce the problem. SWEEP findings (whole
corpus, no before/after) are always ADVISE for the same reason: a sweep
has no "did this edit make it worse" to judge.

Cold-index rule: this check never denies based on corpus data — the EDIT
half only ever reads the single file's own would-be content (file
existence needs no corpus at all), so it runs identically whether the
corpus is warm, cold, or absent. The SWEEP half consumes the corpus but
never blocks regardless (see above), so the cold-index rule has nothing to
degrade here.

Archive-aware plan links (Plan 00419 N2): when the literal path fails, a
target that names a plan folder is re-resolved by plan NUMBER across the
whole plan tree (:mod:`plan_links`). A link that resolves that way has NOT
gone dead — the plan moved — so it is never reported as missing and never
BLOCK, because the edit under judgement did not move the target. What
remains is a source-sensitive advisory, described at :func:`_relocation`.
"""

import re
from collections.abc import Sequence
from fnmatch import fnmatch
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.docs_qa.corpus import is_in_scope
from claude_code_hooks_daemon.docs_qa.types import (
    CheckContext,
    CheckSpec,
    CheckStage,
    Finding,
    Severity,
)
from claude_code_hooks_daemon.plan_links import PlanLinkResolver, RelocatedPlanLink
from claude_code_hooks_daemon.utils.authored_paths import contained_authored_path
from claude_code_hooks_daemon.utils.markdown_links import extract_link_targets

CHECK_ID: Final[str] = "pointer-resolves"


def _exists_within(base: Path, target: str, root: Path) -> bool:
    """Whether ``target`` resolves from ``base`` AND lands inside ``root``.

    Containment is the half `authored_path_exists` does not do, and the half
    this check needs. A link target is AUTHORED, and a plain existence answer
    over it is an ORACLE: `[x](/etc/passwd)` needs no `..` to escape, because
    pathlib discards the base for an absolute right operand, and whether a
    finding appears then tells the reader whether that host path exists.

    `base` and `root` differ on purpose. A link resolves relative to its own
    DOCUMENT, so `../sibling.md` legitimately leaves the document's directory
    — it is leaving the REPOSITORY that is the hazard.
    """
    resolved = contained_authored_path(base, target, within=root)
    return resolved is not None and resolved.exists()


_EXTERNAL_SCHEME_RE: Final[re.Pattern[str]] = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://")
_MAILTO_PREFIX: Final[str] = "mailto:"
_PLACEHOLDER_TOKENS: Final[tuple[str, ...]] = ("NNNNN", "X.Y.Z", "{", "*", "<")


def _is_skippable(target: str) -> bool:
    """Whether ``target`` is a link shape this check never resolves.

    External URLs, ``mailto:``, pure-fragment links, and placeholder-token
    targets (a plan number, a version, a templated ``{name}``/glob/angle
    placeholder) all name something that is not a real repository file —
    resolving them would only ever produce false positives.
    """
    if not target or target.startswith("#") or target.startswith(_MAILTO_PREFIX):
        return True
    if _EXTERNAL_SCHEME_RE.match(target):
        return True
    return any(token in target for token in _PLACEHOLDER_TOKENS)


def _strip_fragment(target: str) -> str:
    return target.split("#", 1)[0]


def _resolves(project_root: Path, file_path: Path | None, target: str) -> bool:
    """Whether ``target`` (file-existence only; no anchor resolution) resolves.

    A leading ``/`` is ambiguous between two conventions this project's docs
    both use: (a) a fully-qualified absolute filesystem path — an author
    wrote the project's own on-disk path, e.g. ``/workspace/CHANGELOG.md``
    when ``project_root`` genuinely IS ``/workspace`` — and (b)
    repo-root-relative shorthand (GitHub-style ``/CHANGELOG.md`` meaning
    "from the repo root"). The literal path is tried FIRST: naively
    stripping the leading ``/`` and joining under ``project_root`` for case
    (a) DOUBLES the root segment (``/workspace/workspace/...``) and falsely
    reports a real file as missing. Only when the literal path does not
    exist does this fall back to the repo-root-relative join.

    Otherwise relative-to-the-file is tried first, then relative-to-root as
    a fallback (a plain link written without a leading ``/`` commonly means
    "from the repo root" in this project's own docs).

    Every branch goes through :func:`_exists_within`, which does TWO things
    the plain stat did not.

    It resolves ``..`` lexically before touching the filesystem. Stat-ing the
    join walks ``..`` through the filesystem instead, so a link in the FIRST
    document of a new directory read as dead while naming a real file — and
    being new, it was graded BLOCK and denied a write that no retry could make
    succeed.

    It also CONTAINS the result to ``project_root``. Normalising alone left
    this an existence oracle: a target may be absolute, and pathlib discards
    the base for an absolute right operand, so ``[x](/etc/passwd)`` was stat-ed
    as written and the presence or absence of a finding reported whether that
    host path exists. Containment is why the leading-``/`` branch can stay —
    the project's OWN fully-qualified path is inside ``project_root``, and a
    path outside it is not a link any reader of this repository can follow.
    """
    file_target = _strip_fragment(target)
    if not file_target:
        return True
    if file_target.startswith("/"):
        if _exists_within(project_root, file_target, project_root):
            return True
        return _exists_within(project_root, file_target.lstrip("/"), project_root)
    if file_path is not None and _exists_within(file_path.parent, file_target, project_root):
        return True
    return _exists_within(project_root, file_target, project_root)


def _matches_allowlist(rel_path: str, patterns: Sequence[str]) -> bool:
    return any(fnmatch(rel_path, pattern) for pattern in patterns)


def _finding(check_target_path: str, target: str, severity: Severity) -> Finding:
    return Finding(
        check_id=CHECK_ID,
        severity=severity,
        message=f"Link target does not exist: {target}",
        remediation=(
            f"Fix or remove the link to `{target}` in `{check_target_path}` "
            "(create the target, correct the path, or delete the dead link)."
        ),
        path=check_target_path,
    )


def _relocation(
    resolver: PlanLinkResolver,
    context: CheckContext,
    rel_path: str,
    file_path: Path,
    target: str,
    relocated: RelocatedPlanLink,
) -> Finding | None:
    """Advise that a link's plan has MOVED, or ``None`` to say nothing.

    Severity is a property of the SOURCE document, not of the link, and three
    sources are deliberately silent:

    - an ARCHIVED plan — "truth is enforced on LIVE plans, never on the
      historical record"; editing one to match today's tree falsifies it;
    - a ``JOURNAL/`` day-file — append-only, so repointing an earlier entry is
      structurally forbidden, and a finding nobody may act on trains its
      reader to skim the whole check;
    - a live ``PLAN.md`` — plan QA's ``plan-link-resolves`` reports that one,
      with a plan-tree-aware remediation. Reporting it here as well would put
      one fact on two session-start advisories.

    Everything else — a supporting document in a live plan folder, the plan
    index, a doc anywhere else in the repository — is reported here, at ADVISE
    and never BLOCK: the edit under judgement did not move the target.
    """
    plan_tree = context.policy.plan_tree
    if plan_tree.is_archived(rel_path) or plan_tree.is_journal(rel_path):
        return None
    if plan_tree.is_plan_document(rel_path):
        return None
    suggested = resolver.suggested_link(file_path.parent, relocated)
    return Finding(
        check_id=CHECK_ID,
        severity=Severity.ADVISE,
        message=(
            f"Link target has moved: {target} — "
            f"plan {relocated.plan_number:05d} now lives at {relocated.rel_path}"
        ),
        remediation=(
            f"Repoint the link in `{rel_path}` to `{suggested}` "
            f"(`{relocated.rel_path}`); the plan was archived, not deleted."
        ),
        path=rel_path,
    )


def _judge(
    context: CheckContext,
    resolver: PlanLinkResolver,
    rel_path: str,
    file_path: Path,
    target: str,
    *,
    dead_severity: Severity,
) -> Finding | None:
    """The whole per-link decision, shared by all three stages.

    ``dead_severity`` is the only thing that differs between them: a SWEEP has
    no before/after to judge, so it is always ADVISE, while EDIT and STAGED
    may BLOCK a link that is NEW in that edit or commit.
    """
    if _is_skippable(target):
        return None
    if _resolves(context.project_root, file_path, target):
        return None
    relocated = resolver.resolve(file_path.parent, target)
    if relocated is not None:
        return _relocation(resolver, context, rel_path, file_path, target, relocated)
    return _finding(rel_path, target, dead_severity)


def _resolver(context: CheckContext) -> PlanLinkResolver:
    return PlanLinkResolver(context.project_root, context.policy.plan_tree)


def _dead_severity(*, is_new: bool, grandfathered: bool) -> Severity:
    return Severity.BLOCK if (is_new and not grandfathered) else Severity.ADVISE


def _run_edit(context: CheckContext) -> list[Finding]:
    if context.file_path is None or context.file_content is None:
        return []
    if not is_in_scope(context.file_path, context.project_root, context.policy):
        return []

    rel_path = str(context.file_path.relative_to(context.project_root))
    grandfathered = _matches_allowlist(rel_path, context.policy.qa.grandfather_allowlist)
    old_targets = (
        set(extract_link_targets(context.file_content_before))
        if context.file_content_before is not None
        else set()
    )

    resolver = _resolver(context)
    findings: list[Finding] = []
    for target in extract_link_targets(context.file_content):
        finding = _judge(
            context,
            resolver,
            rel_path,
            context.file_path,
            target,
            dead_severity=_dead_severity(
                is_new=target not in old_targets, grandfathered=grandfathered
            ),
        )
        if finding is not None:
            findings.append(finding)
    return findings


def _run_sweep(context: CheckContext) -> list[Finding]:
    if context.corpus is None:
        return []

    resolver = _resolver(context)
    findings: list[Finding] = []
    for rel_path, record in sorted(context.corpus.documents.items()):
        file_path = context.project_root / rel_path
        for target in record.links:
            finding = _judge(
                context, resolver, rel_path, file_path, target, dead_severity=Severity.ADVISE
            )
            if finding is not None:
                findings.append(finding)
    return findings


def _run_staged(context: CheckContext) -> list[Finding]:
    """STAGED half: every staged ``.md`` doc's links, block-eligible for NEW ones.

    "New" is judged against HEAD (via :attr:`CheckContext.gitfacts`), the
    same distinction the EDIT half makes against ``file_content_before`` —
    a link that was already broken before this commit is not this commit's
    fault.
    """
    if context.staged_documents is None or context.gitfacts is None:
        return []

    resolver = _resolver(context)
    findings: list[Finding] = []
    for rel_path, content in sorted(context.staged_documents.items()):
        grandfathered = _matches_allowlist(rel_path, context.policy.qa.grandfather_allowlist)
        head_content = context.gitfacts.head_file_text(rel_path)
        old_targets = set(extract_link_targets(head_content)) if head_content else set()
        file_path = context.project_root / rel_path
        for target in extract_link_targets(content):
            finding = _judge(
                context,
                resolver,
                rel_path,
                file_path,
                target,
                dead_severity=_dead_severity(
                    is_new=target not in old_targets, grandfathered=grandfathered
                ),
            )
            if finding is not None:
                findings.append(finding)
    return findings


CHECKS: Final[tuple[CheckSpec, CheckSpec, CheckSpec]] = (
    CheckSpec(check_id=CHECK_ID, stage=CheckStage.EDIT, run=_run_edit),
    CheckSpec(check_id=CHECK_ID, stage=CheckStage.STAGED, run=_run_staged),
    CheckSpec(check_id=CHECK_ID, stage=CheckStage.SWEEP, run=_run_sweep),
)
