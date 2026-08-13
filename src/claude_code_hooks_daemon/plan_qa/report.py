"""Renderers turning plan QA findings into surface-appropriate text.

Three consumers, three shapes (Plan 00144):

- :func:`format_block_reason` — a PreToolUse deny reason: what is wrong and
  the EXACT remediation, so the agent self-corrects on the next tool call
- :func:`format_advisory` — compact advisory context for non-blocking
  surfaces (SessionStart sweep, commit gate in warn mode)
- :func:`format_cli_report` — the ``plan-qa`` CLI report with level counts
"""

from typing import Final

from claude_code_hooks_daemon.plan_qa.types import Finding, Level

_HEADER_BLOCK = "Plan QA violation(s) — fix before retrying:"
_HEADER_ADVISORY = "Plan QA drift report:"

# A clean report must describe exactly what was examined (Plan 00230). The
# tree-wide wording was previously printed for a single-file lint too, so a
# `--lint` of one document announced that every OTHER plan on disk was clean
# as well — a claim the run had made no attempt to check.
CLEAN_SCOPE_TREE: Final[str] = "plan tree is clean"


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


def format_cli_report(findings: list[Finding], clean_scope: str = CLEAN_SCOPE_TREE) -> str:
    """CLI report: level counts plus every finding.

    ``clean_scope`` names what a zero-finding run actually examined. It
    defaults to the whole tree because that is what ``--sweep`` and
    ``--check-staged`` cover; ``--lint`` passes the single file it read, so a
    clean result can never be mistaken for a clean tree.
    """
    if not findings:
        return f"Plan QA: 0 findings — {clean_scope}."
    blocks = sum(1 for finding in findings if finding.level == Level.BLOCK)
    advisories = sum(1 for finding in findings if finding.level == Level.ADVISE)
    plural = "s" if len(findings) != 1 else ""
    lines = [f"Plan QA: {len(findings)} finding{plural} ({blocks} block, {advisories} advise)"]
    lines.extend(_format_finding(finding) for finding in findings)
    return "\n".join(lines)
