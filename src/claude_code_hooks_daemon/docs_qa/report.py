"""Renderers turning docs QA findings into surface-appropriate text.

Mirrors :mod:`claude_code_hooks_daemon.plan_qa.report`:

- :func:`format_block_reason` — a PreToolUse deny reason (future EDIT
  handler)
- :func:`format_advisory` — compact advisory context (future SWEEP/commit
  gate)
- :func:`format_cli_report` — the ``docs-qa`` CLI report with severity
  counts
"""

from typing import Final

from claude_code_hooks_daemon.docs_qa.types import Finding, Severity

_HEADER_BLOCK = "Docs QA violation(s) — fix before retrying:"
_HEADER_ADVISORY = "Docs QA drift report:"

# An advisory surface (SWEEP, warn-mode commit gate) is unbounded context
# injected into every matching session — a project with several oversized
# module docs (module-doc-budget) or a large corpus of stale links could
# otherwise dump dozens of bullets into context every time. format_advisory
# stays compact by showing only the first N findings and naming the CLI for
# the rest; format_block_reason and format_cli_report are unaffected — a
# deny reason must show every violation the agent needs to fix, and the CLI
# report is read on demand, not injected automatically.
MAX_ADVISORY_FINDINGS_SHOWN: Final[int] = 8

# A clean report must describe exactly what was examined. A ``--lint`` of
# one file must not read as "the whole corpus is clean" (same discipline as
# plan_qa's CLEAN_SCOPE_TREE).
CLEAN_SCOPE_CORPUS: Final[str] = "documentation corpus is clean"


def _format_finding(finding: Finding) -> str:
    """One finding as a compact multi-line bullet."""
    location = f" [{finding.path}]" if finding.path else ""
    return (
        f"- [{finding.severity.value}] {finding.check_id}{location}: "
        f"{finding.message}\n  Fix: {finding.remediation}"
    )


def format_block_reason(findings: list[Finding]) -> str:
    """Deny-reason text for a blocking surface."""
    lines = [_HEADER_BLOCK]
    lines.extend(_format_finding(finding) for finding in findings)
    return "\n".join(lines)


def _select_capped_findings(findings: list[Finding], cap: int) -> list[Finding]:
    """The findings shown by a capped advisory, guaranteeing every distinct
    check gets at least one slot before the remainder fills up.

    Findings accumulate in check-registration order, so a naive ``[:cap]``
    slice starves every check after whichever one produced the most
    findings first (e.g. 76 ``at-import-census`` findings fill all 8 slots
    before ``duplicate-block`` -- registered later -- ever shows one).

    Two phases: (1) round-robin one finding per distinct check, ordered
    BLOCK-severity checks before ADVISE (stable, so ties keep their
    original registration order); (2) fill any remaining capacity from the
    leftover findings in their original order. The result is re-sorted back
    to original order for presentation.
    """
    if len(findings) <= cap:
        return list(findings)

    indices_by_check: dict[str, list[int]] = {}
    for index, finding in enumerate(findings):
        indices_by_check.setdefault(finding.check_id, []).append(index)

    check_ids_by_severity = sorted(
        indices_by_check,
        key=lambda check_id: (
            0 if findings[indices_by_check[check_id][0]].severity == Severity.BLOCK else 1
        ),
    )

    selected: set[int] = set()
    for check_id in check_ids_by_severity:
        if len(selected) >= cap:
            break
        selected.add(indices_by_check[check_id][0])

    for index in range(len(findings)):
        if len(selected) >= cap:
            break
        selected.add(index)

    return [findings[index] for index in sorted(selected)]


def format_advisory(findings: list[Finding]) -> str:
    """Advisory-context text for non-blocking surfaces.

    Capped at :data:`MAX_ADVISORY_FINDINGS_SHOWN` bullets so a large corpus
    of drift never bloats a session's injected context; the CLI shows every
    finding on demand. Every distinct check with findings gets at least one
    slot before the cap fills with the remainder (see
    :func:`_select_capped_findings`).
    """
    lines = [_HEADER_ADVISORY]
    shown = _select_capped_findings(findings, MAX_ADVISORY_FINDINGS_SHOWN)
    lines.extend(_format_finding(finding) for finding in shown)
    omitted = len(findings) - len(shown)
    if omitted > 0:
        plural = "s" if omitted != 1 else ""
        lines.append(
            f"...and {omitted} more finding{plural} — run `docs-qa --sweep` "
            "(or `--check-staged`) for the full report."
        )
    return "\n".join(lines)


def format_cli_report(findings: list[Finding], clean_scope: str = CLEAN_SCOPE_CORPUS) -> str:
    """CLI report: severity counts plus every finding.

    ``clean_scope`` names what a zero-finding run actually examined. It
    defaults to the whole corpus because that is what ``--sweep`` covers;
    ``--lint`` passes the single file it read.
    """
    if not findings:
        return f"Docs QA: 0 findings — {clean_scope}."
    blocks = sum(1 for finding in findings if finding.severity == Severity.BLOCK)
    advisories = sum(1 for finding in findings if finding.severity == Severity.ADVISE)
    plural = "s" if len(findings) != 1 else ""
    lines = [f"Docs QA: {len(findings)} finding{plural} ({blocks} block, {advisories} advise)"]
    lines.extend(_format_finding(finding) for finding in findings)
    return "\n".join(lines)
