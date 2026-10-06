"""The GitHub issue assignment guard (Plan 00490).

The handler is a thin consumer of ``utils/github_issue_validity``; those
checks are tested in ``tests/unit/utils/test_github_issue_validity.py``. Here:
what counts as issue-tied work, what the handler decides from a report, and
that untied work never reaches ``gh``.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use.github_issue_assignment_guard import (
    GithubIssueAssignmentGuardHandler,
)
from claude_code_hooks_daemon.utils.github_issue_validity import GhError, GhRunner

ME = "lts-bob"

Factory = Callable[..., GithubIssueAssignmentGuardHandler]


class FakeGh:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.identity: str | Exception = ME
        self.assignees: dict[int, list[str] | Exception] = {}
        self.author = "lts-bob"
        self.race_winner: str | None = None

    def __call__(self, args: Sequence[str]) -> str:
        argv = tuple(args)
        self.calls.append(argv)
        if argv[:2] == ("api", "user"):
            if isinstance(self.identity, Exception):
                raise self.identity
            return self.identity
        if argv[:2] == ("issue", "view"):
            answer = self.assignees[int(argv[2])]
            if isinstance(answer, Exception):
                raise answer
            return json.dumps(
                {
                    "assignees": [{"login": a} for a in answer],
                    "author": {"login": self.author},
                    "state": "OPEN",
                    "labels": [],
                }
            )
        if argv[:2] == ("issue", "edit"):
            number = int(argv[2])
            current = self.assignees[number]
            assert isinstance(current, list)
            if "--remove-assignee" in argv:
                self.assignees[number] = [a for a in current if a != ME]
            else:
                winner = [self.race_winner] if self.race_winner else []
                self.assignees[number] = [*winner, ME]
            return ""
        raise AssertionError(f"unexpected gh call {argv}")


class ForbiddenGh:
    """A runner that fails the test if it is ever called."""

    def __call__(self, args: Sequence[str]) -> str:
        raise AssertionError(f"gh must not be called, got {tuple(args)}")


def _write_plan(root: Path, folder: str, header_issue: str | None) -> Path:
    plan = root / "CLAUDE" / "Plan" / folder
    plan.mkdir(parents=True, exist_ok=True)
    lines = ["# Plan: x", "", "**Status**: Not Started"]
    if header_issue is not None:
        lines.append(f"**GitHub Issue**: {header_issue}")
    lines += ["", "## Overview", ""]
    path = plan / "PLAN.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _edit(path: Path | str) -> dict[str, Any]:
    return {
        "tool_name": "Edit",
        "tool_input": {"file_path": str(path), "old_string": "a", "new_string": "b"},
    }


def _bash(command: str) -> dict[str, Any]:
    return {"tool_name": "Bash", "tool_input": {"command": command}}


@pytest.fixture
def gh() -> FakeGh:
    return FakeGh()


@pytest.fixture
def make_handler(tmp_path: Path) -> Factory:
    def build(
        runner: GhRunner,
        approved: list[str] | None = None,
        auto_claim: bool = False,
    ) -> GithubIssueAssignmentGuardHandler:
        handler = GithubIssueAssignmentGuardHandler(runner=runner, project_root=tmp_path)
        if approved is not None:
            handler._approved_issue_authors = approved
        handler._auto_claim = auto_claim
        return handler

    return build


class TestWhatIsIssueTied:
    def test_a_plan_file_whose_header_names_an_issue(
        self, tmp_path: Path, make_handler: Factory
    ) -> None:
        plan = _write_plan(tmp_path, "00001-x", "#5")
        assert make_handler(ForbiddenGh()).matches(_edit(plan)) is True

    def test_any_tracked_document_in_that_plan_folder(
        self, tmp_path: Path, make_handler: Factory
    ) -> None:
        plan = _write_plan(tmp_path, "00001-x", "#5")
        other = plan.parent / "DESIGN.md"
        assert make_handler(ForbiddenGh()).matches(_edit(other)) is True

    def test_a_write_counts_too(self, tmp_path: Path, make_handler: Factory) -> None:
        plan = _write_plan(tmp_path, "00001-x", "#5")
        event = {"tool_name": "Write", "tool_input": {"file_path": str(plan), "content": "x"}}
        assert make_handler(ForbiddenGh()).matches(event) is True

    def test_a_plan_without_the_header_is_untied(
        self, tmp_path: Path, make_handler: Factory
    ) -> None:
        plan = _write_plan(tmp_path, "00001-x", None)
        assert make_handler(ForbiddenGh()).matches(_edit(plan)) is False

    def test_a_header_with_no_issue_number_yet_is_untied(
        self, tmp_path: Path, make_handler: Factory
    ) -> None:
        plan = _write_plan(tmp_path, "00001-x", "(to be opened - relates to closed #15)")
        assert make_handler(ForbiddenGh()).matches(_edit(plan)) is False

    def test_an_archived_plan_is_untied(self, tmp_path: Path, make_handler: Factory) -> None:
        archived = tmp_path / "CLAUDE" / "Plan" / "Completed" / "00001-x" / "PLAN.md"
        archived.parent.mkdir(parents=True)
        archived.write_text("**GitHub Issue**: #5\n", encoding="utf-8")
        assert make_handler(ForbiddenGh()).matches(_edit(archived)) is False

    def test_a_journal_file_is_untied(self, tmp_path: Path, make_handler: Factory) -> None:
        plan = _write_plan(tmp_path, "00001-x", "#5")
        journal = plan.parent / "JOURNAL" / "00001-Journal-26-10-05.md"
        assert make_handler(ForbiddenGh()).matches(_edit(journal)) is False

    def test_a_plan_that_does_not_exist_yet_is_untied(
        self, tmp_path: Path, make_handler: Factory
    ) -> None:
        path = tmp_path / "CLAUDE" / "Plan" / "00009-new" / "PLAN.md"
        assert make_handler(ForbiddenGh()).matches(_edit(path)) is False

    def test_the_header_cache_follows_an_edit_of_the_header(
        self, tmp_path: Path, make_handler: Factory
    ) -> None:
        plan = _write_plan(tmp_path, "00001-x", None)
        handler = make_handler(ForbiddenGh())
        assert handler.matches(_edit(plan)) is False
        _write_plan(tmp_path, "00001-x", "#5")
        os.utime(plan, ns=(10**18, 10**18))
        assert handler.matches(_edit(plan)) is True

    def test_a_commit_citing_the_issue_of_a_named_plan(
        self, tmp_path: Path, make_handler: Factory
    ) -> None:
        _write_plan(tmp_path, "00001-x", "#5")
        handler = make_handler(ForbiddenGh())
        assert handler.matches(_bash('git commit -m "Plan 00001: do it. Addresses #5"')) is True

    def test_a_commit_citing_another_issue_is_untied(
        self, tmp_path: Path, make_handler: Factory
    ) -> None:
        _write_plan(tmp_path, "00001-x", "#5")
        handler = make_handler(ForbiddenGh())
        assert handler.matches(_bash('git commit -m "Plan 00001: do it. Addresses #9"')) is False

    def test_a_commit_citing_an_issue_with_no_plan_is_untied(self, make_handler: Factory) -> None:
        handler = make_handler(ForbiddenGh())
        assert handler.matches(_bash('git commit -m "Addresses #5"')) is False

    def test_a_commit_naming_a_plan_without_the_header_is_untied(
        self, tmp_path: Path, make_handler: Factory
    ) -> None:
        _write_plan(tmp_path, "00001-x", None)
        handler = make_handler(ForbiddenGh())
        assert handler.matches(_bash('git commit -m "Plan 00001: x. Addresses #5"')) is False

    def test_a_heredoc_commit_message_is_read(self, tmp_path: Path, make_handler: Factory) -> None:
        _write_plan(tmp_path, "00001-x", "#5")
        command = "git commit -F - <<'EOF'\nPlan 00001: x\n\nAddresses #5\nEOF"
        assert make_handler(ForbiddenGh()).matches(_bash(command)) is True


NON_ISSUE_CORPUS: list[dict[str, Any]] = [
    _bash("ls -la"),
    _bash("git status"),
    _bash("git log --oneline"),
    _bash("git commit -m 'fix the parser'"),
    _bash("git commit -m 'Merge PR #123 into main'"),
    _bash("git push origin main"),
    _bash("gh pr view 12 --comments"),
    _bash("gh issue view 12 --comments"),
    _bash("echo '#5 is a number'"),
    _bash("pytest tests/ -q"),
    _bash(""),
    {"tool_name": "Read", "tool_input": {"file_path": "/x/CLAUDE/Plan/00001-x/PLAN.md"}},
    {"tool_name": "Grep", "tool_input": {"pattern": "GitHub Issue"}},
    {"tool_name": "Write", "tool_input": {"file_path": "/x/src/app.py", "content": "x = 1"}},
    {
        "tool_name": "Edit",
        "tool_input": {"file_path": "/x/README.md", "old_string": "a", "new_string": "b"},
    },
    {"tool_name": "Write", "tool_input": {}},
    {"tool_name": "Bash", "tool_input": {}},
    {},
]


class TestOrdinaryWorkIsNeverJudged:
    """The regression corpus: allowed, and `gh` is never reached."""

    @pytest.mark.parametrize("event", NON_ISSUE_CORPUS, ids=lambda e: str(e)[:60])
    def test_does_not_match_and_makes_no_gh_call(
        self, event: dict[str, Any], make_handler: Factory
    ) -> None:
        handler = make_handler(ForbiddenGh())
        assert handler.matches(event) is False

    def test_a_tied_plan_elsewhere_does_not_taint_an_untied_edit(
        self, tmp_path: Path, make_handler: Factory
    ) -> None:
        _write_plan(tmp_path, "00001-x", "#5")
        other = tmp_path / "src" / "thing.py"
        assert make_handler(ForbiddenGh()).matches(_edit(other)) is False


class TestVerdicts:
    def _tied(self, tmp_path: Path) -> Path:
        return _write_plan(tmp_path, "00001-x", "#5")

    def test_assigned_to_self_is_a_silent_allow(
        self, tmp_path: Path, gh: FakeGh, make_handler: Factory
    ) -> None:
        gh.assignees[5] = [ME]
        result = make_handler(gh).handle(_edit(self._tied(tmp_path)))
        assert result.decision is Decision.ALLOW
        assert not result.context
        assert not result.reason

    def test_two_assignees_including_self_is_denied_as_ambiguous(
        self, tmp_path: Path, gh: FakeGh, make_handler: Factory
    ) -> None:
        gh.assignees[5] = [ME, "someone-else"]
        result = make_handler(gh).handle(_edit(self._tied(tmp_path)))
        assert result.decision is Decision.DENY
        assert "exactly one assignee" in (result.reason or "")
        assert "--claim`" not in (result.reason or "").split("Issue #5")[-1]

    def test_unassigned_denies_with_the_one_command_to_run(
        self, tmp_path: Path, gh: FakeGh, make_handler: Factory
    ) -> None:
        gh.assignees[5] = []
        result = make_handler(gh).handle(_edit(self._tied(tmp_path)))
        assert result.decision is Decision.DENY
        reason = result.reason or ""
        assert "bin/hooks-daemon issue-validity 5 --claim" in reason
        assert "retry" in reason.lower()
        assert "gh issue edit" not in reason

    def test_assigned_only_to_others_denies_and_forbids_claiming(
        self, tmp_path: Path, gh: FakeGh, make_handler: Factory
    ) -> None:
        gh.assignees[5] = ["alice"]
        result = make_handler(gh).handle(_edit(self._tied(tmp_path)))
        assert result.decision is Decision.DENY
        reason = result.reason or ""
        assert "alice" in reason
        assert "do not" in reason.lower()
        assert "issue-validity 5 --claim" not in reason

    def test_an_unapproved_author_denies_and_offers_no_claim(
        self, tmp_path: Path, gh: FakeGh, make_handler: Factory
    ) -> None:
        gh.assignees[5] = []
        gh.author = "stranger"
        handler = make_handler(gh, approved=["lts-bob"])
        result = handler.handle(_edit(self._tied(tmp_path)))
        assert result.decision is Decision.DENY
        assert "--claim" not in (result.reason or "")
        assert "approved" in (result.reason or "")

    def test_an_approved_author_passes_regardless_of_case(
        self, tmp_path: Path, gh: FakeGh, make_handler: Factory
    ) -> None:
        gh.assignees[5] = [ME]
        gh.author = "LTS-BOB"
        result = make_handler(gh, approved=["lts-bob"]).handle(_edit(self._tied(tmp_path)))
        assert result.decision is Decision.ALLOW

    def test_a_lookup_failure_allows_with_an_advisory(
        self, tmp_path: Path, gh: FakeGh, make_handler: Factory
    ) -> None:
        gh.assignees[5] = GhError("offline")
        result = make_handler(gh).handle(_edit(self._tied(tmp_path)))
        assert result.decision is Decision.ALLOW
        assert result.context
        assert "#5" in " ".join(result.context)

    def test_no_identity_allows_with_an_advisory(
        self, tmp_path: Path, gh: FakeGh, make_handler: Factory
    ) -> None:
        gh.identity = GhError("not logged in")
        gh.assignees[5] = []
        result = make_handler(gh).handle(_edit(self._tied(tmp_path)))
        assert result.decision is Decision.ALLOW
        assert result.context

    def test_a_remembered_failure_does_not_repeat_the_advisory(
        self, tmp_path: Path, gh: FakeGh, make_handler: Factory
    ) -> None:
        gh.assignees[5] = GhError("offline")
        handler = make_handler(gh)
        plan = self._tied(tmp_path)
        assert handler.handle(_edit(plan)).context
        assert not handler.handle(_edit(plan)).context

    def test_many_edits_of_a_valid_plan_cost_one_lookup(
        self, tmp_path: Path, gh: FakeGh, make_handler: Factory
    ) -> None:
        gh.assignees[5] = [ME]
        handler = make_handler(gh)
        plan = self._tied(tmp_path)
        for _ in range(6):
            handler.handle(_edit(plan))
        assert len([c for c in gh.calls if c[:2] == ("issue", "view")]) == 1

    def test_the_retry_after_a_claim_is_allowed(
        self, tmp_path: Path, gh: FakeGh, make_handler: Factory
    ) -> None:
        gh.assignees[5] = []
        handler = make_handler(gh)
        plan = self._tied(tmp_path)
        assert handler.handle(_edit(plan)).decision is Decision.DENY
        gh.assignees[5] = [ME]  # what `issue-validity 5 --claim` does, out of process
        assert handler.handle(_edit(plan)).decision is Decision.ALLOW

    def test_a_commit_is_judged_like_an_edit(
        self, tmp_path: Path, gh: FakeGh, make_handler: Factory
    ) -> None:
        _write_plan(tmp_path, "00001-x", "#5")
        gh.assignees[5] = []
        result = make_handler(gh).handle(_bash('git commit -m "Plan 00001: x. Addresses #5"'))
        assert result.decision is Decision.DENY

    def test_the_handler_never_writes_by_default(
        self, tmp_path: Path, gh: FakeGh, make_handler: Factory
    ) -> None:
        gh.assignees[5] = []
        make_handler(gh).handle(_edit(self._tied(tmp_path)))
        assert not [c for c in gh.calls if c[:2] == ("issue", "edit")]


class TestAutoClaim:
    def test_claims_then_allows(self, tmp_path: Path, gh: FakeGh, make_handler: Factory) -> None:
        plan = _write_plan(tmp_path, "00001-x", "#5")
        gh.assignees[5] = []
        result = make_handler(gh, auto_claim=True).handle(_edit(plan))
        assert result.decision is Decision.ALLOW
        assert ("issue", "edit", "5", "--add-assignee", "@me") in gh.calls

    def test_a_claim_lost_to_a_race_is_denied_and_backs_off(
        self, tmp_path: Path, gh: FakeGh, make_handler: Factory
    ) -> None:
        plan = _write_plan(tmp_path, "00001-x", "#5")
        gh.assignees[5] = []
        gh.race_winner = "alice"
        result = make_handler(gh, auto_claim=True).handle(_edit(plan))
        assert result.decision is Decision.DENY
        assert ("issue", "edit", "5", "--remove-assignee", "@me") in gh.calls
        assert gh.assignees[5] == ["alice"]

    def test_never_claims_for_an_unapproved_author(
        self, tmp_path: Path, gh: FakeGh, make_handler: Factory
    ) -> None:
        plan = _write_plan(tmp_path, "00001-x", "#5")
        gh.assignees[5] = []
        gh.author = "stranger"
        result = make_handler(gh, approved=["lts-bob"], auto_claim=True).handle(_edit(plan))
        assert result.decision is Decision.DENY
        assert not [c for c in gh.calls if c[:2] == ("issue", "edit")]

    def test_never_claims_an_issue_held_by_someone_else(
        self, tmp_path: Path, gh: FakeGh, make_handler: Factory
    ) -> None:
        plan = _write_plan(tmp_path, "00001-x", "#5")
        gh.assignees[5] = ["alice"]
        result = make_handler(gh, auto_claim=True).handle(_edit(plan))
        assert result.decision is Decision.DENY
        assert not [c for c in gh.calls if c[:2] == ("issue", "edit")]

    def test_a_failed_claim_falls_back_to_the_deny(
        self, tmp_path: Path, gh: FakeGh, make_handler: Factory
    ) -> None:
        plan = _write_plan(tmp_path, "00001-x", "#5")
        gh.assignees[5] = []

        def failing(args: Sequence[str]) -> str:
            if tuple(args[:2]) == ("issue", "edit"):
                raise GhError("permission denied")
            return gh(args)

        result = make_handler(failing, auto_claim=True).handle(_edit(plan))
        assert result.decision is Decision.DENY


class TestContract:
    def test_ships_disabled(self) -> None:
        assert GithubIssueAssignmentGuardHandler().get_default_enabled() is False

    def test_a_deny_acceptance_test_declares_why_the_harness_cannot_drive_it(self) -> None:
        tests = GithubIssueAssignmentGuardHandler().get_acceptance_tests()
        assert tests
        denying = [t for t in tests if t.expected_decision is Decision.DENY]
        assert denying
        assert all(t.harness_cannot_produce for t in denying)

    def test_there_is_a_near_miss_acceptance_test_that_allows(self) -> None:
        tests = GithubIssueAssignmentGuardHandler().get_acceptance_tests()
        assert any(t.expected_decision is Decision.ALLOW for t in tests)

    def test_guidance_names_the_command(self) -> None:
        guidance = GithubIssueAssignmentGuardHandler().get_claude_md() or ""
        assert "bin/hooks-daemon issue-validity" in guidance

    def test_one_rule_per_deny_reason(self) -> None:
        ids = {r.rule_id for r in GithubIssueAssignmentGuardHandler().get_rules()}
        assert ids == {
            "R-GH-ISSUE-UNASSIGNED",
            "R-GH-ISSUE-ASSIGNED-ELSEWHERE",
            "R-GH-ISSUE-AUTHOR-NOT-APPROVED",
        }

    def test_options_validation_rejects_a_bad_list(self) -> None:
        problems = GithubIssueAssignmentGuardHandler.validate_options(
            {"approved_issue_authors": "lts-bob"}
        )
        assert "approved_issue_authors" in problems

    def test_options_validation_accepts_a_list(self) -> None:
        problems = GithubIssueAssignmentGuardHandler.validate_options(
            {"approved_issue_authors": ["a"], "auto_claim": False}
        )
        assert problems == {}
