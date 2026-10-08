"""Deterministic GitHub issue validity checking (Plan 00490).

Whether an issue may be worked on is a question code can answer, so no agent
turn is spent on it. :func:`check_issue` fetches the issue's facts with ONE
``gh issue view`` call, runs a list of pluggable :class:`ValidityCheck` objects
over them and returns a :class:`ValidityReport` carrying a verdict and the
per-check results.

Two checks ship:

- :class:`AssigneeCheck` - the issue must be assigned to the signed-in account.
  Unassigned is *fixable* (the fix is the claim ``gh issue edit N
  --add-assignee @me``); assigned only to others is *blocking*.
- :class:`AuthorWhitelistCheck` - the issue's author must be on a configured
  list of approved GitHub logins (case-insensitive). No list configured means
  the check is not applicable, never a lockout.

A further check (issue open/closed, a label rule) is one new class with a
``name``, a ``needs_identity`` flag and an ``evaluate`` method.

**Strictness belongs to the caller, not to this module.** The report says
``UNKNOWN`` when a fact could not be read. The PreToolUse handler treats that as
an advisory (it never denies on failure); the CLI used for issue selection
treats it as not eligible. Neither decision is made here.

**Only a settled state stays cached.** A report that is fixable or blocked
drops its cached facts, so the retry after a claim sees the new assignee at
once. Failures are remembered briefly so an offline machine does not pay a
timeout on every edit.

GitHub content is untrusted data: every login read from GitHub is validated
against GitHub's own login grammar before it can reach a message. An
unreadable login is replaced by :data:`UNRECOGNISED_LOGIN` rather than dropped,
because dropping an assignee could turn "assigned to someone else" into
"unassigned", which is claimable.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess  # nosec B404 - trusted system tool (gh), list form, no shell
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Final, Protocol

from pydantic import BaseModel, ValidationError

from claude_code_hooks_daemon.constants import Timeout

_LOGGER = logging.getLogger(__name__)

#: Shown in place of a login that does not match GitHub's login grammar.
UNRECOGNISED_LOGIN: Final[str] = "<unrecognised login>"

#: Option key (under the handler's options) holding the approved-author list.
APPROVED_AUTHORS_OPTION: Final[str] = "approved_issue_authors"

#: How long a settled (valid or not applicable) issue's facts stay cached.
FACTS_TTL_SECONDS: Final[float] = 300.0

#: How long a failed lookup is remembered before gh is asked again.
FAILURE_TTL_SECONDS: Final[float] = 60.0

#: The claim fix's name, and the placeholder GitHub resolves to the signed-in login.
CLAIM_FIX_NAME: Final[str] = "claim"
SELF_ASSIGNEE: Final[str] = "@me"

_VIEW_FIELDS: Final[str] = "assignees,state,author,labels"
_LIST_FIELDS: Final[str] = "number,assignees,state,author,labels"
#: The most open issues one listing asks ``gh`` for (``gh`` pages through them). A
#: listing that comes back this full may have stopped short, so it is refused.
LIST_LIMIT: Final[int] = 1000

# GitHub logins: alphanumerics and single hyphens, never at the ends, at most 39
# characters; apps carry a "[bot]" suffix.
_LOGIN_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?(?:\[bot\])?$"
)


class GhError(Exception):
    """A ``gh`` call, or its answer, could not be used."""


GhRunner = Callable[[Sequence[str]], str]


def make_gh_runner(*, timeout: float = Timeout.GH_LOOKUP, cwd: Path | None = None) -> GhRunner:
    """The real runner: ``gh <args>`` with a timeout, returning stdout.

    Raises:
        GhError: From the returned runner, when gh is missing, times out or
            exits non-zero. The message carries gh's own first stderr line.
    """

    def run(args: Sequence[str]) -> str:
        try:
            completed = subprocess.run(  # nosec B603 B607 - gh, list form, no shell
                ["gh", *args],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=cwd,
                check=False,
            )
        except FileNotFoundError as exc:
            raise GhError("gh is not installed") from exc
        except subprocess.TimeoutExpired as exc:
            raise GhError(f"gh timed out after {timeout:g}s") from exc
        except OSError as exc:
            raise GhError(f"gh could not be run: {exc}") from exc
        if completed.returncode != 0:
            first_line = (completed.stderr.strip().splitlines() or ["no error text"])[0]
            raise GhError(f"gh exited {completed.returncode}: {first_line[:200]}")
        return completed.stdout

    return run


class CheckStatus(StrEnum):
    """One check's outcome."""

    OK = "ok"
    FIXABLE = "fixable"
    BLOCKING = "blocking"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "n/a"


class Verdict(StrEnum):
    """The overall outcome. Precedence: BLOCKED, FIXABLE, UNKNOWN, VALID."""

    VALID = "valid"
    FIXABLE = "fixable"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class FixAction:
    """A deterministic repair for a fixable result."""

    name: str
    issue: int
    description: str
    gh_args: tuple[str, ...]

    @property
    def command(self) -> str:
        """The gh command line, for a message."""
        return "gh " + " ".join(self.gh_args)


@dataclass(frozen=True, slots=True)
class CheckResult:
    """What one check concluded about one issue."""

    check: str
    status: CheckStatus
    message: str
    fix: FixAction | None = None


@dataclass(frozen=True, slots=True)
class IssueFacts:
    """The facts every check reads, fetched together."""

    number: int
    assignees: tuple[str, ...]
    author: str | None
    state: str
    labels: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ValidityReport:
    """All results for one issue, plus whether gh was asked in this call."""

    number: int
    results: tuple[CheckResult, ...]
    fresh: bool = field(default=True, compare=False)

    @property
    def verdict(self) -> Verdict:
        """The overall verdict, from the per-check statuses."""
        statuses = {result.status for result in self.results}
        if CheckStatus.BLOCKING in statuses:
            return Verdict.BLOCKED
        if CheckStatus.FIXABLE in statuses:
            return Verdict.FIXABLE
        if CheckStatus.UNKNOWN in statuses:
            return Verdict.UNKNOWN
        return Verdict.VALID

    @property
    def fixes(self) -> tuple[FixAction, ...]:
        """The fixes offered by fixable results."""
        return tuple(r.fix for r in self.results if r.fix is not None)

    def messages(self, *statuses: CheckStatus) -> list[str]:
        """``"<check>: <message>"`` for each result whose status is listed."""
        return [f"{r.check}: {r.message}" for r in self.results if r.status in statuses]

    def to_dict(self) -> dict[str, Any]:
        """A JSON-ready form."""
        return {
            "issue": self.number,
            "verdict": self.verdict.value,
            "checks": [
                {
                    "check": r.check,
                    "status": r.status.value,
                    "message": r.message,
                    "fix": (
                        {"name": r.fix.name, "command": r.fix.command}
                        if r.fix is not None
                        else None
                    ),
                }
                for r in self.results
            ],
        }


class ValidityCheck(Protocol):
    """A pluggable check. ``evaluate`` is pure: it reads only its arguments."""

    name: str
    #: True when ``evaluate`` needs the signed-in login (one ``gh api user`` call).
    needs_identity: bool

    def evaluate(self, facts: IssueFacts, identity: str | None) -> CheckResult:
        """Judge ``facts``. ``identity`` is None when it could not be resolved."""
        ...


class AssigneeCheck:
    """The issue must be assigned to the signed-in account."""

    name = "assignee"
    needs_identity = True

    def evaluate(self, facts: IssueFacts, identity: str | None) -> CheckResult:
        """Only self: ok. Nobody: fixable by claiming. Several or others only: blocking."""
        if identity is None:
            return CheckResult(
                self.name, CheckStatus.UNKNOWN, "the signed-in GitHub account is unknown"
            )
        if len(facts.assignees) > 1:
            return CheckResult(
                self.name,
                CheckStatus.BLOCKING,
                f"issue #{facts.number} has {len(facts.assignees)} assignees "
                f"({', '.join(facts.assignees)}); who may work on it is ambiguous. "
                "A human must leave exactly one assignee.",
            )
        if any(a.casefold() == identity.casefold() for a in facts.assignees):
            return CheckResult(self.name, CheckStatus.OK, f"assigned to {identity}")
        if not facts.assignees:
            return CheckResult(
                self.name,
                CheckStatus.FIXABLE,
                f"issue #{facts.number} is unassigned",
                FixAction(
                    name=CLAIM_FIX_NAME,
                    issue=facts.number,
                    description=f"assign #{facts.number} to {identity}",
                    gh_args=("issue", "edit", str(facts.number), "--add-assignee", SELF_ASSIGNEE),
                ),
            )
        return CheckResult(
            self.name,
            CheckStatus.BLOCKING,
            f"issue #{facts.number} is assigned to {', '.join(facts.assignees)}, not {identity}",
        )


class AuthorWhitelistCheck:
    """The issue's author must be on the approved list (case-insensitive)."""

    name = "author"
    needs_identity = False

    def __init__(self, approved: Iterable[str] | None) -> None:
        self._approved = frozenset(login.casefold() for login in approved or ())

    @property
    def is_configured(self) -> bool:
        """True when a non-empty list is configured."""
        return bool(self._approved)

    def evaluate(self, facts: IssueFacts, identity: str | None) -> CheckResult:
        """Not applicable without a list; otherwise ok only for a listed author."""
        if not self._approved:
            return CheckResult(
                self.name, CheckStatus.NOT_APPLICABLE, "no approved issue authors configured"
            )
        if facts.author is not None and facts.author.casefold() in self._approved:
            return CheckResult(self.name, CheckStatus.OK, f"author {facts.author} is approved")
        return CheckResult(
            self.name,
            CheckStatus.BLOCKING,
            f"issue #{facts.number} was not opened by an approved author "
            f"(author: {facts.author or 'none recorded'})",
        )


def approved_authors_problem(options: Mapping[str, Any]) -> str | None:
    """What is wrong with the approved-author option, or None when it is fine."""
    value = options.get(APPROVED_AUTHORS_OPTION)
    if value is None or (isinstance(value, list) and all(isinstance(i, str) for i in value)):
        return None
    return f"{APPROVED_AUTHORS_OPTION} must be a list of GitHub logins"


def approved_authors_from_options(options: Mapping[str, Any]) -> tuple[str, ...] | None:
    """The approved-author list from handler options; None when absent.

    Raises:
        ValueError: The option is present but is not a list of strings.
    """
    problem = approved_authors_problem(options)
    if problem is not None:
        raise ValueError(problem)
    value = options.get(APPROVED_AUTHORS_OPTION)
    return None if value is None else tuple(value)


class _Login(BaseModel):
    login: str


class _Label(BaseModel):
    name: str


class _IssuePayload(BaseModel):
    assignees: list[_Login]
    state: str = ""
    author: _Login | None = None
    labels: list[_Label] = []


def _safe_login(login: str) -> str:
    return login if _LOGIN_PATTERN.match(login) else UNRECOGNISED_LOGIN


def _facts_from_mapping(number: int, mapping: Mapping[str, Any]) -> IssueFacts:
    try:
        payload = _IssuePayload.model_validate(mapping)
    except ValidationError as exc:
        raise GhError(
            f"unexpected gh issue payload for #{number}: {exc.error_count()} errors"
        ) from exc
    return IssueFacts(
        number=number,
        assignees=tuple(_safe_login(a.login) for a in payload.assignees),
        author=_safe_login(payload.author.login) if payload.author is not None else None,
        state=payload.state,
        labels=tuple(label.name for label in payload.labels),
    )


def _loads(text: str) -> object:
    try:
        parsed: object = json.loads(text)
    except json.JSONDecodeError as exc:
        raise GhError("gh did not return JSON") from exc
    return parsed


def facts_from_payload(number: int, text: str) -> IssueFacts:
    """Parse ``gh issue view --json`` output.

    Raises:
        GhError: The text is not JSON, or lacks the fields the checks read.
    """
    data = _loads(text)
    if not isinstance(data, dict):
        raise GhError("gh returned an unexpected payload")
    return _facts_from_mapping(number, data)


@dataclass(slots=True)
class _Entry:
    expires: float
    facts: IssueFacts | None
    error: str | None


class IssueValidityService:
    """Runs checks over issues through one injectable ``gh`` runner, with caches."""

    def __init__(
        self,
        runner: GhRunner,
        clock: Callable[[], float] = time.monotonic,
        facts_ttl: float = FACTS_TTL_SECONDS,
        failure_ttl: float = FAILURE_TTL_SECONDS,
    ) -> None:
        self._runner = runner
        self._clock = clock
        self._facts_ttl = facts_ttl
        self._failure_ttl = failure_ttl
        self._facts: dict[int, _Entry] = {}
        self._identity_failed_until = 0.0
        self._identity_login: str | None = None
        self._asked = False

    def identity(self) -> str | None:
        """The signed-in login: cached for the process, a failure briefly."""
        if self._identity_login is not None:
            return self._identity_login
        now = self._clock()
        if self._identity_failed_until > now:
            return None
        self._asked = True
        login: str | None = None
        try:
            candidate = self._runner(["api", "user", "--jq", ".login"]).strip()
        except GhError as exc:
            _LOGGER.info("gh could not resolve the signed-in login: %s", exc)
            self._identity_failed_until = now + self._failure_ttl
        else:
            if _LOGIN_PATTERN.match(candidate):
                login = candidate
                self._identity_login = login
            else:
                _LOGGER.info("gh returned an unreadable login; ignoring it")
                self._identity_failed_until = now + self._failure_ttl
        return login

    def _facts_for(self, number: int) -> tuple[IssueFacts | None, str | None]:
        now = self._clock()
        entry = self._facts.get(number)
        if entry is not None and entry.expires > now:
            return entry.facts, entry.error
        self._asked = True
        try:
            facts = facts_from_payload(
                number, self._runner(["issue", "view", str(number), "--json", _VIEW_FIELDS])
            )
        except GhError as exc:
            self._facts[number] = _Entry(now + self._failure_ttl, None, str(exc))
            return None, str(exc)
        self._facts[number] = _Entry(now + self._facts_ttl, facts, None)
        return facts, None

    def forget(self, number: int) -> None:
        """Drop an issue's cached facts."""
        self._facts.pop(number, None)

    def _report(
        self,
        number: int,
        facts: IssueFacts | None,
        error: str | None,
        checks: Sequence[ValidityCheck],
    ) -> ValidityReport:
        if facts is None:
            message = f"could not read issue #{number}: {error}"
            results = tuple(CheckResult(c.name, CheckStatus.UNKNOWN, message) for c in checks)
            return ValidityReport(number, results, fresh=self._asked)
        identity = self.identity() if any(c.needs_identity for c in checks) else None
        results = tuple(c.evaluate(facts, identity) for c in checks)
        return ValidityReport(number, results, fresh=self._asked)

    def check_issue(self, number: int, checks: Sequence[ValidityCheck]) -> ValidityReport:
        """Run ``checks`` over issue ``number``."""
        self._asked = False
        facts, error = self._facts_for(number)
        report = self._report(number, facts, error, checks)
        if report.verdict in (Verdict.FIXABLE, Verdict.BLOCKED):
            self.forget(number)
        return report

    def check_open_issues(self, checks: Sequence[ValidityCheck]) -> list[ValidityReport]:
        """Run ``checks`` over every open issue, from one ``gh issue list`` call.

        Raises:
            GhError: The listing failed, or filled ``LIST_LIMIT`` and so may have
                left issues out. There is no partial answer.
        """
        self._asked = True
        data = _loads(
            self._runner(
                [
                    "issue",
                    "list",
                    "--state",
                    "open",
                    "--limit",
                    str(LIST_LIMIT),
                    "--json",
                    _LIST_FIELDS,
                ]
            )
        )
        if not isinstance(data, list):
            raise GhError("gh returned an unexpected listing")
        if len(data) >= LIST_LIMIT:
            raise GhError(
                f"the listing reached the limit of {LIST_LIMIT} open issues, so it may be "
                "incomplete; check the issues you care about by number instead"
            )
        reports: list[ValidityReport] = []
        for item in data:
            if not isinstance(item, dict) or not isinstance(item.get("number"), int):
                raise GhError("gh returned a listing entry without an issue number")
            facts = _facts_from_mapping(item["number"], item)
            reports.append(self._report(facts.number, facts, None, checks))
        return reports

    def apply_fix(self, fix: FixAction) -> None:
        """Run a fix and drop the issue's cached facts.

        Raises:
            GhError: The fix command failed.
        """
        self._runner(fix.gh_args)
        self.forget(fix.issue)

    def claim(self, fix: FixAction) -> bool:
        """Switch the issue to the signed-in account; True only if it is the sole assignee.

        The edit is applied, the issue re-read, and the claim succeeds only when
        the assignees are exactly the signed-in account. Otherwise another
        claimant won the race: this claim backs off by removing itself, so an
        issue is never left with two assignees, and False is returned.

        Raises:
            GhError: A gh command failed.
        """
        self.apply_fix(fix)
        identity = self.identity()
        facts, error = self._facts_for(fix.issue)
        if error is not None or facts is None:
            raise GhError(f"could not re-read issue #{fix.issue} after claiming: {error}")
        if identity is not None and [a.casefold() for a in facts.assignees] == [
            identity.casefold()
        ]:
            return True
        if any(a.casefold() == (identity or "").casefold() for a in facts.assignees):
            self._runner(["issue", "edit", str(fix.issue), "--remove-assignee", SELF_ASSIGNEE])
        self.forget(fix.issue)
        return False


_DEFAULT_SERVICE: IssueValidityService | None = None


def default_service() -> IssueValidityService:
    """The process-wide service, built on first use with the real runner."""
    global _DEFAULT_SERVICE
    if _DEFAULT_SERVICE is None:
        _DEFAULT_SERVICE = IssueValidityService(make_gh_runner())
    return _DEFAULT_SERVICE


def check_issue(
    number: int,
    checks: Sequence[ValidityCheck],
    *,
    service: IssueValidityService | None = None,
) -> ValidityReport:
    """Check issue ``number`` against ``checks`` and report."""
    return (service or default_service()).check_issue(number, checks)
