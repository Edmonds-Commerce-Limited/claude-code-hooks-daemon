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
"""

import re
from collections.abc import Sequence
from fnmatch import fnmatch
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.docs_qa.corpus import extract_link_targets, is_in_scope
from claude_code_hooks_daemon.docs_qa.types import (
    CheckContext,
    CheckSpec,
    CheckStage,
    Finding,
    Severity,
)

CHECK_ID: Final[str] = "pointer-resolves"

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
    """
    file_target = _strip_fragment(target)
    if not file_target:
        return True
    if file_target.startswith("/"):
        if Path(file_target).exists():
            return True
        return (project_root / file_target.lstrip("/")).exists()
    if file_path is not None and (file_path.parent / file_target).exists():
        return True
    return (project_root / file_target).exists()


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

    findings: list[Finding] = []
    for target in extract_link_targets(context.file_content):
        if _is_skippable(target):
            continue
        if _resolves(context.project_root, context.file_path, target):
            continue
        is_new = target not in old_targets
        severity = Severity.BLOCK if (is_new and not grandfathered) else Severity.ADVISE
        findings.append(_finding(rel_path, target, severity))
    return findings


def _run_sweep(context: CheckContext) -> list[Finding]:
    if context.corpus is None:
        return []

    findings: list[Finding] = []
    for rel_path, record in sorted(context.corpus.documents.items()):
        file_path = context.project_root / rel_path
        for target in record.links:
            if _is_skippable(target):
                continue
            if _resolves(context.project_root, file_path, target):
                continue
            findings.append(_finding(rel_path, target, Severity.ADVISE))
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

    findings: list[Finding] = []
    for rel_path, content in sorted(context.staged_documents.items()):
        grandfathered = _matches_allowlist(rel_path, context.policy.qa.grandfather_allowlist)
        head_content = context.gitfacts.head_file_text(rel_path)
        old_targets = set(extract_link_targets(head_content)) if head_content else set()
        file_path = context.project_root / rel_path
        for target in extract_link_targets(content):
            if _is_skippable(target):
                continue
            if _resolves(context.project_root, file_path, target):
                continue
            is_new = target not in old_targets
            severity = Severity.BLOCK if (is_new and not grandfathered) else Severity.ADVISE
            findings.append(_finding(rel_path, target, severity))
    return findings


CHECKS: Final[tuple[CheckSpec, CheckSpec, CheckSpec]] = (
    CheckSpec(check_id=CHECK_ID, stage=CheckStage.EDIT, run=_run_edit),
    CheckSpec(check_id=CHECK_ID, stage=CheckStage.STAGED, run=_run_staged),
    CheckSpec(check_id=CHECK_ID, stage=CheckStage.SWEEP, run=_run_sweep),
)
