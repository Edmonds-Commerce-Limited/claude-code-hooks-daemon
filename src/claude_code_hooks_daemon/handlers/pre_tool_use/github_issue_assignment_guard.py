"""GithubIssueAssignmentGuardHandler - issue-tied work needs a valid GitHub issue.

Plan 00490. When a session works on a GitHub issue, that issue must be assigned
to the account the session is signed in as, and (when a list is configured) it
must have been opened by an approved author. The judging is deterministic code
in :mod:`claude_code_hooks_daemon.utils.github_issue_validity`; this handler
only decides WHEN to ask and what to say.

**Work counts as issue-tied in two cases, both detected without any network
call:**

1. A ``Write``/``Edit`` of a tracked document inside a plan folder whose
   ``PLAN.md`` header carries ``**GitHub Issue**: #N`` (archived plans and the
   ``JOURNAL/`` are never tied).
2. A ``git commit`` citing ``#N`` while naming a plan (``Plan 00490``) whose
   header carries that same ``#N``. A commit citing some other ``#N`` - a PR
   number, say - is not issue work.

**Everything else exits in ``matches()``** after a string test or a regex on
the path: no subprocess, no network, no file read. Only a tied candidate reads
one plan header, and that read is cached per plan file against its mtime.

**Verdicts** (never a denial on a failed lookup):

- all checks ok: allow, silently;
- the issue is unassigned: deny, naming the ONE command that claims it,
  ``bin/hooks-daemon issue-validity N --claim``;
- the issue is assigned only to others, or its author is not approved: deny;
  do not work on it, do not claim it;
- a fact could not be read (no ``gh``, offline, not signed in): allow with an
  advisory, once per failure window.

**The handler never writes to GitHub unless ``auto_claim`` is on** (default
off). With it on, an unassigned issue that is otherwise valid is claimed here
and the work goes ahead; an issue that is blocked is never claimed.

Options: ``approved_issue_authors`` (list of logins; absent or empty means the
author check does not apply; also read by the ``issue-validity`` CLI, which is
why the list has exactly one home) and ``auto_claim``.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.constants import (
    HandlerID,
    HandlerTag,
    HookInputField,
    Priority,
    ToolName,
)
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import Decision, GatingResult
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.core.rule import Rule, RuleFormatter
from claude_code_hooks_daemon.core.utils import get_bash_command, get_file_path
from claude_code_hooks_daemon.utils.command_evasion import GIT_INVOCATION
from claude_code_hooks_daemon.utils.github_issue_validity import (
    APPROVED_AUTHORS_OPTION,
    CLAIM_FIX_NAME,
    AssigneeCheck,
    AuthorWhitelistCheck,
    CheckStatus,
    GhError,
    GhRunner,
    IssueValidityService,
    ValidityCheck,
    ValidityReport,
    Verdict,
    approved_authors_problem,
    make_gh_runner,
)
from claude_code_hooks_daemon.utils.plan_fact_check import plan_folder_match
from claude_code_hooks_daemon.utils.plan_trigger import plan_dir_for

_LOGGER = logging.getLogger(__name__)

#: The CLI that judges and claims. One home for the command the deny names.
CLAIM_COMMAND_TEMPLATE: Final[str] = "bin/hooks-daemon issue-validity {number} --claim"

AUTO_CLAIM_OPTION: Final[str] = "auto_claim"

_PLAN_FILE: Final[str] = "PLAN.md"
_HEADER_READ_BYTES: Final[int] = 8192
_HEADER_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^\*\*GitHub Issue\*\*:[ \t]*(#\d+(?:[ \t]*,[ \t]*#\d+)*)", re.MULTILINE
)
_ISSUE_NUMBER: Final[re.Pattern[str]] = re.compile(r"#(\d+)")
_COMMIT_REFERENCE: Final[re.Pattern[str]] = re.compile(r"(?<![\w&/])#(\d+)\b")
_PLAN_REFERENCE: Final[re.Pattern[str]] = re.compile(r"\bPlan\s+(\d{1,5})\b")
_GIT_COMMIT: Final[re.Pattern[str]] = re.compile(GIT_INVOCATION + r"commit\b")
_PLAN_NUMBER_WIDTH: Final[int] = 5

_RULE_UNASSIGNED: Final[Rule] = Rule(
    rule_id=RuleID.GH_ISSUE_UNASSIGNED,
    blocked="work tied to a GitHub issue that is assigned to nobody",
    why="Unclaimed issue work can collide with someone else picking the same issue up",
    fix="Run `bin/hooks-daemon issue-validity N --claim`, then retry",
    verbose=(
        "WHY BLOCKED:\n"
        "Work tied to a GitHub issue must be on an issue assigned to the account this\n"
        "session is signed in as. This issue is assigned to nobody.\n\n"
        "DO INSTEAD:\n"
        "  Run the claim command named below. It is deterministic code: it checks\n"
        "  the issue, claims it for the signed-in account, and prints the result.\n"
        "  Then retry the call you were making.\n"
    ),
)

_RULE_ELSEWHERE: Final[Rule] = Rule(
    rule_id=RuleID.GH_ISSUE_ASSIGNED_ELSEWHERE,
    blocked="work tied to a GitHub issue assigned only to someone else",
    why="The issue belongs to another account, and working it would duplicate or collide",
    fix="Do not work on it and do not claim it; tell the user",
    verbose=(
        "WHY BLOCKED:\n"
        "This issue is assigned to someone other than the account this session is\n"
        "signed in as, and not to this account.\n\n"
        "DO INSTEAD:\n"
        "  Do NOT work on it and do NOT claim it. Tell the user the issue belongs\n"
        "  to someone else and let them decide. If the plan is not really about\n"
        "  this issue, the user can correct its `**GitHub Issue**` header.\n"
    ),
)

_RULE_AUTHOR: Final[Rule] = Rule(
    rule_id=RuleID.GH_ISSUE_AUTHOR_NOT_APPROVED,
    blocked="work tied to a GitHub issue opened by an author nobody approved",
    why="An issue is untrusted input; only approved identities may hand work to an agent",
    fix="Do not work on it; tell the user",
    verbose=(
        "WHY BLOCKED:\n"
        "The project keeps a list of approved issue authors\n"
        f"(`{APPROVED_AUTHORS_OPTION}` under this handler's options in\n"
        ".claude/hooks-daemon.yaml). This issue was opened by someone not on it.\n\n"
        "DO INSTEAD:\n"
        "  Do NOT work on it, and write nothing to it: no comment, no label, no\n"
        "  claim. Tell the user. A human may still work it by hand.\n"
    ),
)


class GithubIssueAssignmentGuardHandler(PreToolUseHandlerBase):
    """Deny issue-tied work on an unclaimed, foreign or unapproved issue.

    Opt-in: ships disabled for client projects, enabled in this repository.
    """

    default_enabled = False

    #: Injected by the registry from the handler's options (``self._<key>``).
    _approved_issue_authors: list[str] | None = None
    _auto_claim: bool = False

    def __init__(
        self,
        runner: GhRunner | None = None,
        project_root: Path | None = None,
    ) -> None:
        super().__init__(
            handler_id=HandlerID.GITHUB_ISSUE_ASSIGNMENT_GUARD,
            priority=Priority.GITHUB_ISSUE_ASSIGNMENT_GUARD,
            terminal=True,
            tags=[HandlerTag.WORKFLOW, HandlerTag.BLOCKING, HandlerTag.GITHUB, HandlerTag.TERMINAL],
        )
        self._runner = runner
        self._project_root = project_root
        self._service: IssueValidityService | None = None
        # PLAN.md path -> (mtime_ns, issue numbers named by its header)
        self._header_cache: dict[Path, tuple[int, tuple[int, ...]]] = {}

    def get_default_enabled(self) -> bool:
        """Opt-in until it has run here for a while (Plan 00490 owner question)."""
        return False

    @staticmethod
    def validate_options(options: Mapping[str, Any]) -> dict[str, str]:
        """Refuse a malformed option value; the handler stays on its default."""
        problems: dict[str, str] = {}
        authors_problem = approved_authors_problem(options)
        if authors_problem is not None:
            problems[APPROVED_AUTHORS_OPTION] = authors_problem
        if AUTO_CLAIM_OPTION in options and not isinstance(options[AUTO_CLAIM_OPTION], bool):
            problems[AUTO_CLAIM_OPTION] = f"{AUTO_CLAIM_OPTION} must be true or false"
        return problems

    # ------------------------------------------------------------------
    # Detection: no network, no subprocess, one cached header read at most
    # ------------------------------------------------------------------

    def _root(self) -> Path | None:
        root = self._project_root
        if root is None:
            try:
                root = ProjectContext.project_root()
            except RuntimeError as exc:
                _LOGGER.warning("github_issue_assignment_guard: no project root: %s", exc)
        return root

    def _issues_in_header(self, plan_md: Path) -> tuple[int, ...]:
        try:
            mtime = plan_md.stat().st_mtime_ns
        except OSError:
            return ()
        cached = self._header_cache.get(plan_md)
        if cached is not None and cached[0] == mtime:
            return cached[1]
        try:
            with plan_md.open("rb") as handle:
                text = handle.read(_HEADER_READ_BYTES).decode("utf-8", errors="replace")
        except OSError as exc:
            _LOGGER.warning("github_issue_assignment_guard: cannot read %s: %s", plan_md, exc)
            return ()
        header = _HEADER_PATTERN.search(text)
        issues = tuple(int(n) for n in _ISSUE_NUMBER.findall(header.group(1))) if header else ()
        self._header_cache[plan_md] = (mtime, issues)
        return issues

    def _issues_for_edit(self, hook_input: dict[str, Any]) -> tuple[int, ...]:
        file_path = get_file_path(hook_input)
        if not file_path:
            return ()
        plan_dir = plan_dir_for(self._project_layout)
        if plan_dir not in file_path.replace("\\", "/"):
            return ()
        match = plan_folder_match(file_path, plan_dir)
        if match is None:
            return ()
        return self._issues_in_header(match.plan_root / _PLAN_FILE)

    def _issues_for_commit(self, command: str) -> tuple[int, ...]:
        if "commit" not in command or "#" not in command or not _GIT_COMMIT.search(command):
            return ()
        cited = {int(n) for n in _COMMIT_REFERENCE.findall(command)}
        plans = _PLAN_REFERENCE.findall(command)
        root = self._root()
        if not cited or not plans or root is None:
            return ()
        plan_dir = root / plan_dir_for(self._project_layout)
        tied: set[int] = set()
        for number in plans:
            prefix = f"{int(number):0{_PLAN_NUMBER_WIDTH}d}-"
            for plan_md in plan_dir.glob(f"{prefix}*/{_PLAN_FILE}"):
                tied.update(self._issues_in_header(plan_md))
        return tuple(sorted(cited & tied))

    def _tied_issues(self, hook_input: dict[str, Any]) -> tuple[int, ...]:
        tool = hook_input.get(HookInputField.TOOL_NAME)
        if tool in (ToolName.WRITE, ToolName.EDIT):
            return self._issues_for_edit(hook_input)
        if tool == ToolName.BASH:
            command = get_bash_command(hook_input)
            return self._issues_for_commit(command) if command else ()
        return ()

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """True only for issue-tied work. Untied work never reaches `gh`."""
        return bool(self._tied_issues(hook_input))

    # ------------------------------------------------------------------
    # Judging
    # ------------------------------------------------------------------

    def _service_for_judging(self) -> IssueValidityService:
        if self._service is None:
            runner = self._runner or make_gh_runner(cwd=self._root())
            self._service = IssueValidityService(runner)
        return self._service

    def _checks(self) -> list[ValidityCheck]:
        return [AuthorWhitelistCheck(self._approved_issue_authors), AssigneeCheck()]

    def _claim_if_allowed(
        self, service: IssueValidityService, report: ValidityReport, checks: list[ValidityCheck]
    ) -> ValidityReport:
        """With ``auto_claim`` on, claim a merely-unassigned issue and re-judge it."""
        if not self._auto_claim or report.verdict is not Verdict.FIXABLE:
            return report
        try:
            for fix in report.fixes:
                if fix.name == CLAIM_FIX_NAME:
                    service.apply_fix(fix)
        except GhError as exc:
            _LOGGER.warning("github_issue_assignment_guard: auto-claim failed: %s", exc)
            return report
        return service.check_issue(report.number, checks)

    @staticmethod
    def _denial(report: ValidityReport) -> tuple[Rule, str]:
        """The rule and the issue-specific detail for a denying report."""
        number = report.number
        details = "\n".join(
            f"  - {line}" for line in report.messages(CheckStatus.BLOCKING, CheckStatus.FIXABLE)
        )
        author_blocked = any(
            r.check == AuthorWhitelistCheck.name and r.status is CheckStatus.BLOCKING
            for r in report.results
        )
        if author_blocked:
            return _RULE_AUTHOR, f"Issue #{number}:\n{details}"
        if report.verdict is Verdict.BLOCKED:
            return _RULE_ELSEWHERE, f"Issue #{number}:\n{details}"
        command = CLAIM_COMMAND_TEMPLATE.format(number=number)
        return _RULE_UNASSIGNED, f"Issue #{number}:\n{details}\n\nRun: {command}\nThen retry."

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        """Judge each tied issue; deny on a settled problem, advise on an unknown."""
        service = self._service_for_judging()
        checks = self._checks()
        denials: list[tuple[Rule, str]] = []
        advisories: list[str] = []
        for number in self._tied_issues(hook_input):
            report = self._claim_if_allowed(service, service.check_issue(number, checks), checks)
            if report.verdict in (Verdict.BLOCKED, Verdict.FIXABLE):
                denials.append(self._denial(report))
            elif report.verdict is Verdict.UNKNOWN and report.fresh:
                reasons = "; ".join(report.messages(CheckStatus.UNKNOWN))
                advisories.append(
                    f"GitHub issue check skipped for #{number} ({reasons}). "
                    "Work is not blocked; the issue's assignee and author were not verified."
                )
        if denials:
            rule = denials[0][0]
            detail = "\n\n".join(text for _, text in denials)
            return GatingResult.deny(f"{RuleFormatter().verbose(rule)}\n\n{detail}")
        if advisories:
            return GatingResult(decision=Decision.ALLOW, context=advisories)
        return GatingResult(decision=Decision.ALLOW)

    def get_rules(self) -> list[Rule]:
        """The three Rules backing this handler's denials."""
        return [_RULE_UNASSIGNED, _RULE_ELSEWHERE, _RULE_AUTHOR]

    def get_acceptance_tests(self) -> list[Any]:
        """A near-miss that must allow, and the deny declared as undrivable.

        The deny needs a plan tied to a real issue in a state only GitHub holds
        (unassigned, or another account's), which a probe cannot fabricate and
        which must not be created on the live tracker for a test.
        """
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="github issue assignment guard - ordinary commit citing an issue number",
                command="echo \"git commit -m 'Addresses #123'\"",
                dispatch_as_bash=True,
                description=(
                    "A commit that cites an issue number but names no plan whose header "
                    "carries it is not issue work: no gh call, no verdict."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Uses echo - safe to execute; makes no gh call.",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="github issue assignment guard - edit of a plan tied to an unclaimed issue",
                command="Edit a PLAN.md whose header names an issue assigned to nobody",
                description=(
                    "Denied with the claim command `bin/hooks-daemon issue-validity N "
                    "--claim`; the retry after claiming is allowed."
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"issue-validity", r"--claim"],
                safety_notes="Never run the claim against a real issue from a test.",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                harness_cannot_produce=(
                    "The verdict depends on live GitHub state (an issue with no assignee, "
                    "read through gh), which a probe cannot fabricate and which must not "
                    "be created on the real tracker. Covered by "
                    "tests/unit/handlers/pre_tool_use/test_github_issue_assignment_guard.py "
                    "with an injected gh runner."
                ),
            ),
        ]

    def get_claude_md(self) -> str | None:
        """Resident guidance: the denial is avoidable by claiming BEFORE working."""
        return (
            "## github_issue_assignment_guard — issue-tied work needs a valid issue\n\n"
            "A plan whose header carries `**GitHub Issue**: #N` is tied to that issue. "
            "Editing it, or committing with `Plan NNNNN` and `#N` in the message, is "
            "denied unless the issue is assigned to the signed-in GitHub account"
            " and, when `approved_issue_authors` is configured, opened by an approved "
            "author.\n\n"
            "- **Unassigned**: run `bin/hooks-daemon issue-validity N --claim`, then "
            "retry. The CLI does the lookup and the claim; do not run `gh` lookups "
            "yourself.\n"
            "- **Assigned only to someone else**, or **author not approved**: do not work "
            "on it, do not claim it, write nothing to it; tell the user.\n"
            "- `gh` missing, offline or not signed in: you get an advisory, never a block.\n\n"
            "Work not tied to an issue is never judged."
        )
