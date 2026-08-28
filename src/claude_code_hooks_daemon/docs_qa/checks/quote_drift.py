"""Check ``quote-drift`` (EDIT + SWEEP; R4b, DESIGN §2.4 hardened spec).

Every ``ssot-quote`` block in the QUOTING file is verified against its
declared source: the source file must exist, the anchor must resolve, and
the quote body (normalised) must verify as a contiguous substring of the
normalised source span, at least
:data:`docs_qa.quotes.MIN_QUOTE_LENGTH_CHARS` long. A source file that is
missing, or an anchor that does not resolve, is ALSO quote-drift — with a
distinct message naming which half failed, so the remedy is actionable
rather than a generic "drifted".

**EDIT half** (block-eligible on the quoting edit, per the design table —
unlike ``pointer-resolves`` this is NOT gated to "new quotes only": ANY
quote-drift finding in the file being edited is block-eligible, because a
quoting file with a drifted quote is wrong regardless of whether THIS edit
introduced the drift). The primary verification path reads the SOURCE FILE
directly from disk — no corpus needed at all; the cold-index rule has
nothing to degrade here, because this check's primary case never consults
one.

**SWEEP half** (always ADVISE — a sweep has no before/after to judge
worse-only). Iterates the corpus's indexed documents, skipping any with no
quote references cheaply (the ``quotes`` field is exactly the corpus's
purpose here); for a document that DOES quote something, its content is
re-read fresh from disk (the corpus stores references, never bodies) and
every block re-verified, mirroring the EDIT-stage logic.
"""

import logging
from fnmatch import fnmatch
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.docs_qa.quotes import (
    MIN_QUOTE_LENGTH_CHARS,
    QuoteBlock,
    parse_quote_blocks,
    resolve_anchor_span,
    verify_quote,
)
from claude_code_hooks_daemon.docs_qa.types import (
    CheckContext,
    CheckSpec,
    CheckStage,
    Finding,
    Severity,
)

logger = logging.getLogger(__name__)

CHECK_ID: Final[str] = "quote-drift"

_REMEDY_TAIL: Final[str] = (
    "A quote must come from a SINGLE section — verbatim text spanning two "
    "sections cannot verify against either section's span alone; split it "
    "into two ssot-quote blocks against two anchors instead."
)


def _matches_allowlist(rel_path: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch(rel_path, pattern) for pattern in patterns)


def _finding(rel_path: str, message: str, remediation: str, severity: Severity) -> Finding:
    return Finding(
        check_id=CHECK_ID,
        severity=severity,
        message=message,
        remediation=remediation,
        path=rel_path,
    )


def _verify_block(
    project_root: Path, rel_path: str, block: QuoteBlock, severity: Severity
) -> Finding | None:
    """One quote block's finding, or ``None`` if it verifies clean."""
    source_abs = project_root / block.source_path
    if not source_abs.is_file():
        return _finding(
            rel_path,
            f"`{rel_path}` quotes `{block.source_path}#{block.anchor}`, but the "
            "source file is missing.",
            f"Restore `{block.source_path}`, or update the ssot-quote marker to "
            f"point at its new location. {_REMEDY_TAIL}",
            severity,
        )
    try:
        source_text = source_abs.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        # An unreadable or undecodable source file must not abort the whole
        # sweep/edit check (Plan 00287 N5) -- report it the same way a
        # missing source file is reported.
        return _finding(
            rel_path,
            f"`{rel_path}` quotes `{block.source_path}#{block.anchor}`, but the "
            "source file could not be read.",
            f"Fix `{block.source_path}`'s permissions/encoding, or update the "
            f"ssot-quote marker to point at its new location. {_REMEDY_TAIL}",
            severity,
        )
    span = resolve_anchor_span(source_text, block.anchor)
    if span is None:
        return _finding(
            rel_path,
            f"`{rel_path}` quotes `{block.source_path}#{block.anchor}`, but that "
            "anchor was not found in the source file.",
            f"Add an `<!-- ssot-anchor: {block.anchor} -->` marker at the intended "
            f"section in `{block.source_path}`, or update the ssot-quote marker to "
            f"the section's current heading. {_REMEDY_TAIL}",
            severity,
        )
    if len(block.body.strip()) < MIN_QUOTE_LENGTH_CHARS:
        return _finding(
            rel_path,
            f"`{rel_path}` quotes `{block.source_path}#{block.anchor}`, but the "
            f"quote body is too short to verify (minimum "
            f"{MIN_QUOTE_LENGTH_CHARS} normalised characters).",
            "Quote a longer, self-contained excerpt — a one-line quote is a "
            f"substring of almost anything and protects nothing. {_REMEDY_TAIL}",
            severity,
        )
    if verify_quote(block.body, span):
        return None
    return _finding(
        rel_path,
        f"`{rel_path}` quote of `{block.source_path}#{block.anchor}` has drifted "
        "from its source.",
        f"Update the quoted excerpt in `{rel_path}` to match the current text of "
        f"`{block.source_path}#{block.anchor}`. {_REMEDY_TAIL}",
        severity,
    )


def _run_edit(context: CheckContext) -> list[Finding]:
    if context.file_path is None or context.file_content is None:
        return []
    rel_path = str(context.file_path.relative_to(context.project_root))
    grandfathered = _matches_allowlist(rel_path, context.policy.qa.grandfather_allowlist)
    severity = Severity.ADVISE if grandfathered else Severity.BLOCK

    findings: list[Finding] = []
    for block in parse_quote_blocks(context.file_content):
        finding = _verify_block(context.project_root, rel_path, block, severity)
        if finding is not None:
            findings.append(finding)
    return findings


def _run_sweep(context: CheckContext) -> list[Finding]:
    if context.corpus is None:
        return []

    findings: list[Finding] = []
    for rel_path, record in sorted(context.corpus.documents.items()):
        if not record.quotes:
            continue
        abs_path = context.project_root / rel_path
        if not abs_path.is_file():
            continue
        try:
            content = abs_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            # An unreadable or undecodable file must not abort the whole
            # SessionStart sweep (Plan 00287 N5) -- skip it, matching the
            # corpus's own UnicodeDecodeError handling.
            logger.debug("quote-drift: skipping unreadable %s: %s", rel_path, exc)
            continue
        for block in parse_quote_blocks(content):
            finding = _verify_block(context.project_root, rel_path, block, Severity.ADVISE)
            if finding is not None:
                findings.append(finding)
    return findings


def _run_staged(context: CheckContext) -> list[Finding]:
    """STAGED half: every staged quoting doc, block-eligible like EDIT.

    Mirrors the design table exactly: block-eligibility is "on the
    QUOTING edit", not gated to new-only, so every staged quoting file's
    findings are treated the same way EDIT treats a single file.
    """
    if context.staged_documents is None:
        return []

    findings: list[Finding] = []
    for rel_path, content in sorted(context.staged_documents.items()):
        grandfathered = _matches_allowlist(rel_path, context.policy.qa.grandfather_allowlist)
        severity = Severity.ADVISE if grandfathered else Severity.BLOCK
        for block in parse_quote_blocks(content):
            finding = _verify_block(context.project_root, rel_path, block, severity)
            if finding is not None:
                findings.append(finding)
    return findings


CHECKS: Final[tuple[CheckSpec, CheckSpec, CheckSpec]] = (
    CheckSpec(check_id=CHECK_ID, stage=CheckStage.EDIT, run=_run_edit),
    CheckSpec(check_id=CHECK_ID, stage=CheckStage.STAGED, run=_run_staged),
    CheckSpec(check_id=CHECK_ID, stage=CheckStage.SWEEP, run=_run_sweep),
)
