"""Check ``duplicate-block`` (EDIT + SWEEP; DESIGN §duplicate-block row).

A structured block (R4 classes: fenced code, table, or list-run of 3+
items — :mod:`docs_qa.structured_blocks`) whose NORMALISED hash also
appears in a DIFFERENT document is a finding. The finding is reported on
the file being CHECKED (the edited/swept file), naming its duplicate
partner(s) by path.

**ADVISORY ONLY, HARD-CODED — never block-eligible.** Per
DESIGN-enforcement.md's duplicate-block row ("never at first (00208/00214:
hand-triaged whole-repo run before any promotion)"), this check has NO
:data:`~docs_qa.types.Severity.BLOCK` code path at all — not even behind a
``block`` mode override, since the structural block-eligibility rule
(DESIGN §2.2) means a mode override can only escalate a finding this check
itself marked BLOCK, and this check marks nothing BLOCK. Promoting any part
of it to block-eligible requires a FRESH hand-triaged whole-repo run
recorded in
``CLAUDE/Plan/00284-documentation-ssot-enforcement/TRIAGE-duplicate-block.md``
(or a successor triage doc) — do not add a BLOCK path here without one.

**Cold-index rule**: the EDIT half needs a cross-document comparison, which
needs a corpus; a cold or absent corpus means "no comparison possible", not
"assume clean" — it degrades to silence, never a guess (mirrors
``quote-source-stale``'s EDIT-stage treatment of the same situation).

**Grandfathering**: unlike a block-eligible check, there is no severity for
``grandfather_allowlist`` to downgrade here (everything is already ADVISE).
Respecting it therefore means fully suppressing a finding whose REPORTED
file matches the allowlist — the only way the option has any effect on an
always-advisory check.

**Self-comparison**: a document's own block hashes are never compared
against themselves — set-based membership per document, and the corpus's
OWN (possibly stale) record for the file being edited is explicitly
excluded by path so a file can never be reported as its own duplicate
partner.
"""

from fnmatch import fnmatch
from typing import Final

from claude_code_hooks_daemon.docs_qa.corpus import DocCorpus
from claude_code_hooks_daemon.docs_qa.structured_blocks import extract_structured_block_hashes
from claude_code_hooks_daemon.docs_qa.types import (
    CheckContext,
    CheckSpec,
    CheckStage,
    Finding,
    Severity,
)

CHECK_ID: Final[str] = "duplicate-block"


def _matches_allowlist(rel_path: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch(rel_path, pattern) for pattern in patterns)


def _finding(rel_path: str, partners: tuple[str, ...]) -> Finding:
    partner_list = ", ".join(f"`{partner}`" for partner in partners)
    return Finding(
        check_id=CHECK_ID,
        severity=Severity.ADVISE,
        message=(
            f"`{rel_path}` contains a structured block (fenced code, table, or "
            f"list run) identical, after normalisation, to one in: {partner_list}."
        ),
        remediation=(
            "Extract the content into one canonical location and have the "
            "other file(s) link to it (R1), or — if this is deliberate "
            "verbatim repetition — wrap it in "
            "`<!-- ssot-quote: file.md#anchor -->` markers (R4b) so it becomes "
            "tracked, drift-checked quotation instead of an untracked copy."
        ),
        path=rel_path,
    )


def _hash_index(corpus: DocCorpus) -> dict[str, tuple[str, ...]]:
    """``block_hash -> sorted rel_paths``, restricted to hashes shared by 2+ docs."""
    index: dict[str, list[str]] = {}
    for rel_path, record in corpus.documents.items():
        for block_hash in set(record.block_hashes):
            index.setdefault(block_hash, []).append(rel_path)
    return {
        block_hash: tuple(sorted(paths)) for block_hash, paths in index.items() if len(paths) >= 2
    }


def _run_edit(context: CheckContext) -> list[Finding]:
    if context.file_path is None or context.file_content is None:
        return []
    if context.corpus is None or context.corpus.cold:
        return []  # cold-index rule: no cross-doc comparison possible

    rel_path = str(context.file_path.relative_to(context.project_root))
    if _matches_allowlist(rel_path, context.policy.qa.grandfather_allowlist):
        return []

    index = _hash_index(context.corpus)
    own_hashes = set(extract_structured_block_hashes(context.file_content))
    if not own_hashes:
        return []

    partners: set[str] = set()
    for block_hash in own_hashes:
        for candidate in index.get(block_hash, ()):
            if candidate != rel_path:
                partners.add(candidate)
    if not partners:
        return []
    return [_finding(rel_path, tuple(sorted(partners)))]


def _run_sweep(context: CheckContext) -> list[Finding]:
    if context.corpus is None:
        return []

    findings: list[Finding] = []
    for block_hash, paths in sorted(_hash_index(context.corpus).items()):
        # One finding per shared block: the alphabetically-first path
        # reports, naming every other path as a partner -- never a mirrored
        # second finding for the same hash from a partner's perspective.
        reporter, *partners = paths
        if _matches_allowlist(reporter, context.policy.qa.grandfather_allowlist):
            continue
        findings.append(_finding(reporter, tuple(partners)))
    return findings


CHECKS: Final[tuple[CheckSpec, CheckSpec]] = (
    CheckSpec(check_id=CHECK_ID, stage=CheckStage.EDIT, run=_run_edit),
    CheckSpec(check_id=CHECK_ID, stage=CheckStage.SWEEP, run=_run_sweep),
)
