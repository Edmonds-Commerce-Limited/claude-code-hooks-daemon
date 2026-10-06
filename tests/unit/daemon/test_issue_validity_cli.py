"""The ``issue-validity`` CLI (Plan 00490): deterministic lookup, claim and listing.

Driven through an injected ``gh`` runner. No test claims a real issue.
"""

from __future__ import annotations

import io
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.daemon.issue_validity_cli import (
    EXIT_BLOCKED,
    EXIT_FIXABLE,
    EXIT_OK,
    EXIT_UNKNOWN,
    EXIT_USAGE,
    load_approved_authors,
    run_issue_validity,
)
from claude_code_hooks_daemon.utils.github_issue_validity import (
    GhError,
    IssueValidityService,
)

ME = "lts-bob"


class FakeGh:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.identity: str | Exception = ME
        self.issues: dict[int, dict[str, Any] | Exception] = {}
        self.listing: list[dict[str, Any]] | Exception = []
        self.edit_error: Exception | None = None
        self.race_winner: str | None = None

    def __call__(self, args: Sequence[str]) -> str:
        argv = tuple(args)
        self.calls.append(argv)
        if argv[:2] == ("api", "user"):
            if isinstance(self.identity, Exception):
                raise self.identity
            return self.identity
        if argv[:2] == ("issue", "view"):
            answer = self.issues[int(argv[2])]
            if isinstance(answer, Exception):
                raise answer
            return json.dumps(answer)
        if argv[:2] == ("issue", "list"):
            if isinstance(self.listing, Exception):
                raise self.listing
            return json.dumps(self.listing)
        if argv[:2] == ("issue", "edit"):
            if self.edit_error is not None:
                raise self.edit_error
            current = self.issues[int(argv[2])]
            assert isinstance(current, dict)
            if "--remove-assignee" in argv:
                current["assignees"] = [a for a in current["assignees"] if a["login"] != ME]
            else:
                winner = [{"login": self.race_winner}] if self.race_winner else []
                current["assignees"] = [*winner, {"login": ME}]
            return ""
        raise AssertionError(argv)


def _issue(number: int, assignees: Sequence[str] = (), author: str = "lts-bob") -> dict[str, Any]:
    return {
        "number": number,
        "assignees": [{"login": a} for a in assignees],
        "author": {"login": author},
        "state": "OPEN",
        "labels": [],
    }


@pytest.fixture
def gh() -> FakeGh:
    return FakeGh()


def _run(
    gh: FakeGh,
    *,
    number: int | None = None,
    claim: bool = False,
    as_json: bool = False,
    list_eligible: bool = False,
    approved: Sequence[str] | None = ("lts-bob", "ltscommerce"),
) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = run_issue_validity(
        number=number,
        claim=claim,
        as_json=as_json,
        list_eligible=list_eligible,
        approved=approved,
        service=IssueValidityService(gh),
        stdout=out,
        stderr=err,
    )
    return code, out.getvalue(), err.getvalue()


class TestSingleIssue:
    def test_a_valid_issue_exits_zero(self, gh: FakeGh) -> None:
        gh.issues[5] = _issue(5, [ME])
        code, out, _ = _run(gh, number=5)
        assert code == EXIT_OK
        assert "valid" in out

    def test_unassigned_without_claim_reports_and_does_not_write(self, gh: FakeGh) -> None:
        gh.issues[5] = _issue(5)
        code, out, _ = _run(gh, number=5)
        assert code == EXIT_FIXABLE
        assert "--claim" in out
        assert not [c for c in gh.calls if c[:2] == ("issue", "edit")]

    def test_claim_assigns_and_exits_zero(self, gh: FakeGh) -> None:
        gh.issues[5] = _issue(5)
        code, out, _ = _run(gh, number=5, claim=True)
        assert code == EXIT_OK
        assert ("issue", "edit", "5", "--add-assignee", "@me") in gh.calls
        assert "claimed" in out.lower()

    def test_claim_does_nothing_to_an_issue_that_is_already_mine(self, gh: FakeGh) -> None:
        gh.issues[5] = _issue(5, [ME])
        code, _, _ = _run(gh, number=5, claim=True)
        assert code == EXIT_OK
        assert not [c for c in gh.calls if c[:2] == ("issue", "edit")]

    def test_claim_never_touches_an_issue_held_by_someone_else(self, gh: FakeGh) -> None:
        gh.issues[5] = _issue(5, ["alice"])
        code, out, _ = _run(gh, number=5, claim=True)
        assert code == EXIT_BLOCKED
        assert "alice" in out
        assert not [c for c in gh.calls if c[:2] == ("issue", "edit")]

    def test_a_claim_lost_to_a_race_backs_off_and_stays_not_workable(self, gh: FakeGh) -> None:
        gh.issues[5] = _issue(5)
        gh.race_winner = "alice"
        code, out, err = _run(gh, number=5, claim=True)
        assert code == EXIT_BLOCKED
        assert "claim failed" in err
        assert "claimed issue" not in out
        assert ("issue", "edit", "5", "--remove-assignee", "@me") in gh.calls
        assert gh.issues[5]["assignees"] == [{"login": "alice"}]

    def test_two_assignees_including_me_is_blocked_and_never_edited(self, gh: FakeGh) -> None:
        gh.issues[5] = _issue(5, ["alice", ME])
        code, out, _ = _run(gh, number=5, claim=True)
        assert code == EXIT_BLOCKED
        assert "exactly one assignee" in out
        assert not [c for c in gh.calls if c[:2] == ("issue", "edit")]

    def test_claim_never_writes_to_an_issue_from_an_unapproved_author(self, gh: FakeGh) -> None:
        gh.issues[5] = _issue(5, author="stranger")
        code, _, _ = _run(gh, number=5, claim=True)
        assert code == EXIT_BLOCKED
        assert not [c for c in gh.calls if c[:2] == ("issue", "edit")]

    def test_a_failed_claim_exits_fixable_and_says_why(self, gh: FakeGh) -> None:
        gh.issues[5] = _issue(5)
        gh.edit_error = GhError("permission denied")
        code, _, err = _run(gh, number=5, claim=True)
        assert code == EXIT_FIXABLE
        assert "permission denied" in err

    def test_an_unreadable_issue_is_unknown_and_never_valid(self, gh: FakeGh) -> None:
        gh.issues[5] = GhError("offline")
        code, out, _ = _run(gh, number=5)
        assert code == EXIT_UNKNOWN
        assert "unknown" in out

    def test_unknown_is_not_eligible_even_for_the_author_check(self, gh: FakeGh) -> None:
        gh.issues[5] = GhError("offline")
        code, _, _ = _run(gh, number=5, claim=True)
        assert code == EXIT_UNKNOWN
        assert not [c for c in gh.calls if c[:2] == ("issue", "edit")]

    @pytest.mark.parametrize("approved", [None, ()])
    @pytest.mark.parametrize("claim", [False, True])
    def test_refuses_to_judge_an_issue_without_a_configured_list(
        self, gh: FakeGh, approved: Sequence[str] | None, claim: bool
    ) -> None:
        """Issue selection must never fail open: no list, no verdict, no gh call."""
        gh.issues[5] = _issue(5, author="anyone")
        code, out, err = _run(gh, number=5, claim=claim, approved=approved)
        assert code == EXIT_USAGE
        assert out == ""
        assert "approved_issue_authors" in err
        assert gh.calls == []

    def test_json_output(self, gh: FakeGh) -> None:
        gh.issues[5] = _issue(5)
        code, out, _ = _run(gh, number=5, as_json=True)
        data = json.loads(out)
        assert code == EXIT_FIXABLE
        assert data["verdict"] == "fixable"
        statuses = {c["check"]: c["status"] for c in data["checks"]}
        assert statuses == {"author": "ok", "assignee": "fixable"}

    def test_a_number_is_required_without_list_eligible(self, gh: FakeGh) -> None:
        code, _, err = _run(gh)
        assert code == EXIT_USAGE
        assert "issue number" in err


class TestListEligible:
    def _listing(self, gh: FakeGh) -> None:
        gh.listing = [
            _issue(1, author="lts-bob"),
            _issue(2, author="Stranger"),
            _issue(3, author="LTSCommerce"),
        ]

    def test_prints_only_issues_by_approved_authors_case_insensitively(self, gh: FakeGh) -> None:
        self._listing(gh)
        code, out, _ = _run(gh, list_eligible=True)
        assert code == EXIT_OK
        assert "#1" in out and "#3" in out
        assert "#2" not in out
        assert "skipped 1" in out

    def test_json(self, gh: FakeGh) -> None:
        self._listing(gh)
        _, out, _ = _run(gh, list_eligible=True, as_json=True)
        data = json.loads(out)
        assert data["eligible"] == [1, 3]
        assert data["skipped"] == 1

    def test_makes_one_listing_call_and_no_identity_call(self, gh: FakeGh) -> None:
        self._listing(gh)
        _run(gh, list_eligible=True)
        assert [c[:2] for c in gh.calls] == [("issue", "list")]

    @pytest.mark.parametrize("approved", [None, ()])
    def test_refuses_to_list_without_a_configured_list(
        self, gh: FakeGh, approved: Sequence[str] | None
    ) -> None:
        """The runbook's gate must never fail open."""
        self._listing(gh)
        code, out, err = _run(gh, list_eligible=True, approved=approved)
        assert code == EXIT_USAGE
        assert out == ""
        assert "approved_issue_authors" in err
        assert gh.calls == []

    def test_a_listing_failure_exits_unknown_and_prints_nothing_eligible(self, gh: FakeGh) -> None:
        gh.listing = GhError("offline")
        code, out, err = _run(gh, list_eligible=True)
        assert code == EXIT_UNKNOWN
        assert "#" not in out
        assert "offline" in err

    def test_a_listing_with_no_eligible_issue_is_still_a_success(self, gh: FakeGh) -> None:
        gh.listing = [_issue(2, author="stranger")]
        code, out, _ = _run(gh, list_eligible=True)
        assert code == EXIT_OK
        assert "skipped 1" in out


class TestLoadApprovedAuthors:
    def _config(self, root: Path, body: str) -> None:
        (root / ".claude").mkdir()
        (root / ".claude" / "hooks-daemon.yaml").write_text(body, encoding="utf-8")

    def test_reads_the_handler_option(self, tmp_path: Path) -> None:
        self._config(
            tmp_path,
            "handlers:\n  pre_tool_use:\n    github_issue_assignment_guard:\n"
            "      enabled: false\n      options:\n        approved_issue_authors: [A, b]\n",
        )
        assert load_approved_authors(tmp_path) == ("A", "b")

    def test_absent_option_is_none(self, tmp_path: Path) -> None:
        self._config(tmp_path, "handlers:\n  pre_tool_use: {}\n")
        assert load_approved_authors(tmp_path) is None

    def test_missing_config_is_none(self, tmp_path: Path) -> None:
        assert load_approved_authors(tmp_path) is None

    def test_a_malformed_option_fails_fast(self, tmp_path: Path) -> None:
        self._config(
            tmp_path,
            "handlers:\n  pre_tool_use:\n    github_issue_assignment_guard:\n"
            "      options:\n        approved_issue_authors: nope\n",
        )
        with pytest.raises(ValueError, match="approved_issue_authors"):
            load_approved_authors(tmp_path)
