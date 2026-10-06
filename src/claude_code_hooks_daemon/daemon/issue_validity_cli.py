"""The ``issue-validity`` command: deterministic issue lookup, claim and listing.

Plan 00490. ``bin/hooks-daemon issue-validity N [--claim] [--json]`` reports
whether issue N may be worked on, and with ``--claim`` performs the one repair
that is safe to do by code (claiming an unassigned issue). ``issue-validity
--list-eligible`` prints the open issues whose author is approved.

Exit codes::

    0  valid (all checks ok or not applicable); also: the listing succeeded
    1  blocked (assigned only to others, or the author is not approved)
    2  fixable and not fixed (unassigned, no ``--claim``, or the claim failed)
    3  unknown (a fact could not be read); the listing failed
    4  usage or configuration error

**This command is the strict caller.** An ``unknown`` result is not eligible:
it exits non-zero, because the issue-sdlc runbook's author gate must never fail
open. (The PreToolUse handler is the lenient caller and only advises.)

**Nothing is written to an ineligible issue.** ``--claim`` acts only when the
overall verdict is *fixable*, which excludes any blocked or unknown issue.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final, TextIO

from claude_code_hooks_daemon.config.models import handler_options
from claude_code_hooks_daemon.constants import HandlerID
from claude_code_hooks_daemon.daemon.validation import load_config_safe
from claude_code_hooks_daemon.utils.github_issue_validity import (
    CLAIM_FIX_NAME,
    AssigneeCheck,
    AuthorWhitelistCheck,
    GhError,
    IssueValidityService,
    ValidityCheck,
    ValidityReport,
    Verdict,
    approved_authors_from_options,
)

EXIT_OK: Final[int] = 0
EXIT_BLOCKED: Final[int] = 1
EXIT_FIXABLE: Final[int] = 2
EXIT_UNKNOWN: Final[int] = 3
EXIT_USAGE: Final[int] = 4

_VERDICT_EXIT: Final[dict[Verdict, int]] = {
    Verdict.VALID: EXIT_OK,
    Verdict.BLOCKED: EXIT_BLOCKED,
    Verdict.FIXABLE: EXIT_FIXABLE,
    Verdict.UNKNOWN: EXIT_UNKNOWN,
}

_CLAIM_COMMAND: Final[str] = "bin/hooks-daemon issue-validity {number} --claim"


def load_approved_authors(project_root: Path) -> tuple[str, ...] | None:
    """The approved-author list from the project's config; None when absent.

    The list lives in the options of ``github_issue_assignment_guard`` whether
    or not that handler is enabled, so the CLI, the handler and the runbook all
    read one key.

    Raises:
        ValueError: The option is present but malformed.
    """
    config = load_config_safe(project_root) or {}
    block = (
        (config.get("handlers") or {})
        .get("pre_tool_use", {})
        .get(HandlerID.GITHUB_ISSUE_ASSIGNMENT_GUARD.config_key)
    )
    return approved_authors_from_options(handler_options(block))


def _describe(report: ValidityReport) -> list[str]:
    lines = [f"issue #{report.number}: {report.verdict.value}"]
    for result in report.results:
        lines.append(f"  [{result.status.value}] {result.check}: {result.message}")
    if report.verdict is Verdict.FIXABLE:
        lines.append(f"  to claim it: {_CLAIM_COMMAND.format(number=report.number)}")
    return lines


def _emit(report: ValidityReport, as_json: bool, stdout: TextIO) -> None:
    if as_json:
        stdout.write(json.dumps(report.to_dict(), indent=2) + "\n")
    else:
        stdout.write("\n".join(_describe(report)) + "\n")


def _check_one(
    number: int,
    claim: bool,
    as_json: bool,
    approved: Sequence[str] | None,
    service: IssueValidityService,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    checks: list[ValidityCheck] = [AuthorWhitelistCheck(approved), AssigneeCheck()]
    report = service.check_issue(number, checks)
    claimed = False
    if claim and report.verdict is Verdict.FIXABLE:
        try:
            for fix in report.fixes:
                if fix.name == CLAIM_FIX_NAME:
                    claimed = service.claim(fix)
                    if not claimed:
                        stderr.write(
                            f"claim failed for #{number}: another account was assigned at the "
                            "same time; this claim backed off and the issue is not workable\n"
                        )
        except GhError as exc:
            stderr.write(f"claim failed for #{number}: {exc}\n")
        else:
            report = service.check_issue(number, checks)
    if claimed and report.verdict is Verdict.VALID and not as_json:
        stdout.write(f"claimed issue #{number}\n")
    _emit(report, as_json, stdout)
    return _VERDICT_EXIT[report.verdict]


def _list_eligible(
    as_json: bool,
    approved: Sequence[str] | None,
    service: IssueValidityService,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    author_check = AuthorWhitelistCheck(approved)
    try:
        reports = service.check_open_issues([author_check])
    except GhError as exc:
        stderr.write(f"could not list open issues: {exc}\n")
        return EXIT_UNKNOWN
    eligible = [r.number for r in reports if r.verdict is Verdict.VALID]
    skipped = len(reports) - len(eligible)
    if as_json:
        payload: dict[str, Any] = {"eligible": eligible, "skipped": skipped}
        stdout.write(json.dumps(payload) + "\n")
    else:
        stdout.write(f"eligible issues ({len(eligible)}), skipped {skipped}:\n")
        for number in eligible:
            stdout.write(f"#{number}\n")
    return EXIT_OK


def run_issue_validity(
    *,
    number: int | None,
    claim: bool,
    as_json: bool,
    list_eligible: bool,
    approved: Sequence[str] | None,
    service: IssueValidityService,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    """Run the command; returns the process exit code.

    Refuses (``EXIT_USAGE``, no ``gh`` call) when no author list is configured:
    this is the strict caller, and an unconfigured list would make every issue
    eligible. The PreToolUse handler keeps "no list = author check n/a".
    """
    if not AuthorWhitelistCheck(approved).is_configured:
        stderr.write(
            "refusing to judge issues: no approved_issue_authors configured. Set it under "
            "handlers.pre_tool_use.github_issue_assignment_guard.options in "
            ".claude/hooks-daemon.yaml; an unconfigured list would make every issue eligible.\n"
        )
        return EXIT_USAGE
    if list_eligible:
        return _list_eligible(as_json, approved, service, stdout, stderr)
    if number is None:
        stderr.write("an issue number is required (or use --list-eligible)\n")
        return EXIT_USAGE
    return _check_one(number, claim, as_json, approved, service, stdout, stderr)
