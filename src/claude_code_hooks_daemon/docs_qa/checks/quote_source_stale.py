"""Check ``quote-source-stale`` (EDIT only, advise-only; R4b, DESIGN §2.4).

Editing a SOURCE file that other documents quote from should tell the
author which quoting files now need re-checking — without blocking the
edit itself (advise-only, never block: the source author is not
responsible for fixing every quoter in the same commit, and SWEEP
re-verifies every quote fully anyway, which is why this check has no SWEEP
half of its own).

**Only anchors with a KNOWN quoter are considered** — this check does not
enumerate every heading in the edited file, it consults the corpus's
REVERSE index (:meth:`docs_qa.corpus.DocCorpus.quoters_of`) for exactly the
``(this_file, anchor)`` pairs some OTHER document already quotes, then
diffs each such anchor's section-span (normalised) between the would-be
and on-disk content. This is where the corpus genuinely accelerates a
lookup no single-file read could answer — unlike ``quote-drift``'s primary
path, this check is USELESS without one: a cold corpus (no reverse index
data) means "no known quoters", so it degrades to silence, never to a
false positive or a crash.
"""

from typing import Final

from claude_code_hooks_daemon.docs_qa.quotes import normalise_markdown, resolve_anchor_span
from claude_code_hooks_daemon.docs_qa.types import (
    CheckContext,
    CheckSpec,
    CheckStage,
    Finding,
    Severity,
)

CHECK_ID: Final[str] = "quote-source-stale"


def _finding(rel_path: str, anchor: str, quoters: tuple[str, ...]) -> Finding:
    quoter_list = ", ".join(f"`{quoter}`" for quoter in quoters)
    return Finding(
        check_id=CHECK_ID,
        severity=Severity.ADVISE,
        message=(
            f"`{rel_path}#{anchor}` changed, and {quoter_list} "
            "quote{} it.".format("s" if len(quoters) == 1 else "")
        ),
        remediation=(
            f"Re-check the ssot-quote block(s) in {quoter_list} against the "
            f"updated `{rel_path}#{anchor}` (or run the docs-qa sweep, which "
            "re-verifies every quote automatically)."
        ),
        path=rel_path,
    )


def _run_edit(context: CheckContext) -> list[Finding]:
    if context.file_path is None or context.file_content is None:
        return []
    if context.file_content_before is None:
        return []  # a brand-new file has no prior quoters to have gone stale
    if context.corpus is None:
        return []  # cold-safe: no reverse-index data means "no known quoters"

    rel_path = str(context.file_path.relative_to(context.project_root))
    quoted_anchors = sorted(
        {
            ref.anchor
            for record in context.corpus.documents.values()
            for ref in record.quotes
            if ref.source_path == rel_path
        }
    )

    findings: list[Finding] = []
    for anchor in quoted_anchors:
        # quoted_anchors is derived from the SAME corpus data quoters_of
        # consults (both filter record.quotes by source_path==rel_path), so
        # this can never be empty here -- no defensive check needed.
        quoters = context.corpus.quoters_of(rel_path, anchor)
        old_span = resolve_anchor_span(context.file_content_before, anchor)
        new_span = resolve_anchor_span(context.file_content, anchor)
        old_norm = normalise_markdown(old_span) if old_span is not None else None
        new_norm = normalise_markdown(new_span) if new_span is not None else None
        if old_norm == new_norm:
            continue
        findings.append(_finding(rel_path, anchor, quoters))
    return findings


CHECKS: Final[tuple[CheckSpec, ...]] = (
    CheckSpec(check_id=CHECK_ID, stage=CheckStage.EDIT, run=_run_edit),
)
