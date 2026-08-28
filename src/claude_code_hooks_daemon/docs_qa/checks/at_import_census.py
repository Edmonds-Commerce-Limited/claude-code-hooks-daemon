"""Check ``at-import-census`` (EDIT + SWEEP; R6, DESIGN critique FP note).

R6 — "No @-imports outside the deliberate resident set in root CLAUDE.md":
``@``-imports re-inline eagerly and defeat progressive disclosure, so any
``@path.md`` token outside the configured ``resident_at_imports`` allowlist
(``fnmatch`` patterns, default ``["CLAUDE.md"]``) is a finding.

The design critique's false-positive note: docs legitimately QUOTE an
``@``-import string when describing the rule itself (e.g. this very
module's docstring). Backtick-quoted occurrences and anything inside a
fenced code block are skipped for that reason — a per-line backtick-span
strip runs BEFORE the import regex, on top of the existing fence-aware
line filter.

Block eligibility mirrors ``pointer-resolves`` exactly: NEW imports only
at EDIT (an import already present before the edit is not this edit's
fault); SWEEP is always ADVISE (no before/after to judge).
"""

import re
from fnmatch import fnmatch
from typing import Final

from claude_code_hooks_daemon.docs_qa.types import (
    CheckContext,
    CheckSpec,
    CheckStage,
    Finding,
    Severity,
)
from claude_code_hooks_daemon.plan_qa.model import lines_outside_fences

CHECK_ID: Final[str] = "at-import-census"

_BACKTICK_SPAN_RE: Final[re.Pattern[str]] = re.compile(r"`[^`]*`")
_AT_IMPORT_RE: Final[re.Pattern[str]] = re.compile(r"@(\S+\.md)")
_TRAILING_PUNCTUATION: Final[str] = ".,;:)"


def _strip_backtick_spans(line: str) -> str:
    return _BACKTICK_SPAN_RE.sub("", line)


def extract_at_imports(text: str) -> list[str]:
    """Every ``@path.md`` import target, outside fences and backtick spans."""
    targets: list[str] = []
    for line in lines_outside_fences(text):
        stripped = _strip_backtick_spans(line)
        for match in _AT_IMPORT_RE.finditer(stripped):
            targets.append(match.group(1).rstrip(_TRAILING_PUNCTUATION))
    return targets


def _is_resident(target: str, resident_at_imports: tuple[str, ...]) -> bool:
    return any(fnmatch(target, pattern) for pattern in resident_at_imports)


def _finding(rel_path: str, target: str, severity: Severity) -> Finding:
    return Finding(
        check_id=CHECK_ID,
        severity=severity,
        message=f"`@{target}` is an @-import outside the resident allowlist.",
        remediation=(
            f"Replace the `@{target}` import in `{rel_path}` with a plain markdown "
            "link — @-imports re-inline eagerly and defeat progressive disclosure "
            "(R6). Extend `documentation.qa.resident_at_imports` only for a "
            "deliberately always-loaded file."
        ),
        path=rel_path,
    )


def _run_edit(context: CheckContext) -> list[Finding]:
    if context.file_path is None or context.file_content is None:
        return []
    rel_path = str(context.file_path.relative_to(context.project_root))
    resident = context.policy.qa.resident_at_imports
    old_targets = (
        set(extract_at_imports(context.file_content_before))
        if context.file_content_before is not None
        else set()
    )

    findings: list[Finding] = []
    for target in extract_at_imports(context.file_content):
        if _is_resident(target, resident):
            continue
        is_new = target not in old_targets
        severity = Severity.BLOCK if is_new else Severity.ADVISE
        findings.append(_finding(rel_path, target, severity))
    return findings


def _run_sweep(context: CheckContext) -> list[Finding]:
    if context.corpus is None:
        return []

    findings: list[Finding] = []
    resident = context.policy.qa.resident_at_imports
    for rel_path in sorted(context.corpus.documents):
        abs_path = context.project_root / rel_path
        if not abs_path.is_file():
            continue
        content = abs_path.read_text(encoding="utf-8")
        for target in extract_at_imports(content):
            if _is_resident(target, resident):
                continue
            findings.append(_finding(rel_path, target, Severity.ADVISE))
    return findings


CHECKS: Final[tuple[CheckSpec, CheckSpec]] = (
    CheckSpec(check_id=CHECK_ID, stage=CheckStage.EDIT, run=_run_edit),
    CheckSpec(check_id=CHECK_ID, stage=CheckStage.SWEEP, run=_run_sweep),
)
