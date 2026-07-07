"""Renderers turning plan QA findings into surface-appropriate text.

Three consumers, three shapes (Plan 00144):

- :func:`format_block_reason` — a PreToolUse deny reason: what is wrong and
  the EXACT remediation, so the agent self-corrects on the next tool call
- :func:`format_advisory` — compact advisory context for non-blocking
  surfaces (SessionStart sweep, commit gate in warn mode)
- :func:`format_cli_report` — the ``plan-qa`` CLI report with level counts
"""

from claude_code_hooks_daemon.plan_qa.types import Finding, Level

_HEADER_BLOCK = "Plan QA violation(s) — fix before retrying:"
_HEADER_ADVISORY = "Plan QA drift report:"
_CLEAN_REPORT = "Plan QA: 0 findings — plan tree is clean."


def _format_finding(finding: Finding) -> str:
    """One finding as a compact multi-line bullet."""
    location = f" [{finding.path}]" if finding.path else ""
    return (
        f"- [{finding.level.value}] {finding.check_id}{location}: "
        f"{finding.message}\n  Fix: {finding.remediation}"
    )


def format_block_reason(findings: list[Finding]) -> str:
    """Deny-reason text for a blocking surface."""
    lines = [_HEADER_BLOCK]
    lines.extend(_format_finding(finding) for finding in findings)
    return "\n".join(lines)


def format_advisory(findings: list[Finding]) -> str:
    """Advisory-context text for non-blocking surfaces."""
    lines = [_HEADER_ADVISORY]
    lines.extend(_format_finding(finding) for finding in findings)
    return "\n".join(lines)


def format_cli_report(findings: list[Finding]) -> str:
    """CLI report: level counts plus every finding."""
    if not findings:
        return _CLEAN_REPORT
    blocks = sum(1 for finding in findings if finding.level == Level.BLOCK)
    advisories = sum(1 for finding in findings if finding.level == Level.ADVISE)
    plural = "s" if len(findings) != 1 else ""
    lines = [f"Plan QA: {len(findings)} finding{plural} ({blocks} block, {advisories} advise)"]
    lines.extend(_format_finding(finding) for finding in findings)
    return "\n".join(lines)
