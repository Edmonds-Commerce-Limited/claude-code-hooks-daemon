"""Tests for unresolved review attempts (Plan 00620 review fix 3, F-BYPS F2).

A review that ends with no verdict (an unparseable reply, a damaged transcript, a
killed reviewer, a withdrawn verdict, or a review still running) used to leave no
trace, so the requester could simply ask again for the same tip: opinion shopping.
Each unresolved attempt on the same WORK now adds one required reviewer, and
``MAX_UNRESOLVED_REVIEWS`` of them close the route until a human decides.

The count is DERIVED from the store (a dispatch with no verdict of its own) and
unioned with the ``failures/`` trace records, so a reviewer that never stopped
counts too. Every read fails closed.
"""

from __future__ import annotations

import inspect
import json
from dataclasses import replace
from pathlib import Path

import pytest

from claude_code_hooks_daemon.config.models import BranchRejectConfig
from claude_code_hooks_daemon.core import branch_reject
from claude_code_hooks_daemon.core.branch_reject import (
    MAX_UNRESOLVED_REVIEWS,
    DispatchRecord,
    FailureRecord,
    RejectError,
    RejectRefusedError,
    RejectRequest,
    RejectRoute,
    RejectStore,
    admit_request,
    compute_inventory,
    issue_requests,
    new_id,
    read_ledger,
    unresolved_attempts,
)
from claude_code_hooks_daemon.daemon.branch_safety import delete_branches
from tests.unit.core.test_branch_reject import (
    NOW,
    _git,
    _issue,
    _main_sha,
    _reviewer,
    _tip,
    config,
    repo,
    store,
)

__all__ = ["config", "repo", "store"]


def _route(repo: Path, store: RejectStore, config: BranchRejectConfig) -> RejectRoute:
    return RejectRoute(
        store=store,
        ledger_path=repo / config.ledger_path,
        config=config,
        now=NOW,
        default_ref="main",
    )


def _request(repo: Path, store: RejectStore, *, branch: str = "feat") -> RejectRequest:
    request = RejectRequest(
        nonce=new_id(),
        branch=branch,
        tip=_tip(repo, branch),
        default_sha=_main_sha(repo),
        inventory=compute_inventory(repo, branch, "main"),
        reviewers_required=1,
        prompt_sha256="b" * 64,
        created_at=NOW - 120,
    )
    store.write_request(request)
    return request


def _dispatched(repo: Path, store: RejectStore, *, branch: str = "feat") -> RejectRequest:
    """A request whose reviewer was dispatched and never produced a verdict."""
    request = _request(repo, store, branch=branch)
    store.write_dispatch(
        DispatchRecord(
            nonce=request.nonce, session_id="s1", tool_use_id="toolu_y", agent_id="killed"
        )
    )
    return request


def _failure(request: RejectRequest, reason: str = "unparseable-reply") -> FailureRecord:
    return FailureRecord(
        nonce=request.nonce,
        reason=reason,
        branch=request.branch,
        tip=request.tip,
        recorded_at=NOW - 60,
    )


def _count(repo: Path, store: RejectStore, branch: str = "feat") -> int:
    inventory = compute_inventory(repo, branch, "main")
    return unresolved_attempts(store, branch, _tip(repo, branch), inventory)


def _delete(repo: Path, route: RejectRoute) -> bool:
    report = delete_branches(repo, ["feat"], protected_ref="main", reject_route=route)
    return report.deleted == ("feat",)


class TestTheConstant:
    def test_two_unresolved_reviews_close_the_route(self) -> None:
        assert MAX_UNRESOLVED_REVIEWS == 2


class TestFailureRecords:
    def test_a_failure_round_trips(self, repo: Path, store: RejectStore) -> None:
        record = _failure(_request(repo, store))
        store.write_failure(record)
        assert store.failures() == [record]

    def test_a_second_failure_for_one_nonce_keeps_the_first(
        self, repo: Path, store: RejectStore
    ) -> None:
        request = _request(repo, store)
        store.write_failure(_failure(request, "reply-mismatch"))
        store.write_failure(_failure(request, "unparseable-reply"))
        assert [f.reason for f in store.failures()] == ["reply-mismatch"]

    def test_a_failure_not_named_by_its_nonce_raises(self, repo: Path, store: RejectStore) -> None:
        record = _failure(_request(repo, store))
        directory = store.root / "failures"
        directory.mkdir(parents=True)
        (directory / f"{new_id()}.json").write_text(
            json.dumps(record.to_dict(), sort_keys=True), encoding="utf-8"
        )
        with pytest.raises(RejectError, match="not named by its nonce"):
            store.failures()

    def test_a_damaged_failure_raises(self, store: RejectStore) -> None:
        directory = store.root / "failures"
        directory.mkdir(parents=True)
        (directory / f"{new_id()}.json").write_text("{half", encoding="utf-8")
        with pytest.raises(RejectError):
            store.failures()


class TestDispatchListing:
    def test_dispatches_are_listed(self, repo: Path, store: RejectStore) -> None:
        request = _dispatched(repo, store)
        assert [d.nonce for d in store.dispatches()] == [request.nonce]

    def test_a_dispatch_not_named_by_its_nonce_raises(self, repo: Path, store: RejectStore) -> None:
        request = _dispatched(repo, store)
        original = store.root / "dispatches" / f"{request.nonce}.json"
        original.rename(original.with_name(f"{new_id()}.json"))
        with pytest.raises(RejectError, match="not named by its nonce"):
            store.dispatches()

    def test_a_damaged_dispatch_raises(self, repo: Path, store: RejectStore) -> None:
        request = _dispatched(repo, store)
        (store.root / "dispatches" / f"{request.nonce}.json").write_text("[", encoding="utf-8")
        with pytest.raises(RejectError):
            store.dispatches()


class TestUnresolvedAttempts:
    def test_nothing_on_file_is_zero(self, repo: Path, store: RejectStore) -> None:
        assert _count(repo, store) == 0

    def test_a_request_never_dispatched_does_not_count(
        self, repo: Path, store: RejectStore
    ) -> None:
        _request(repo, store)
        assert _count(repo, store) == 0

    def test_a_dispatch_with_its_verdict_does_not_count(
        self, repo: Path, store: RejectStore
    ) -> None:
        _issue(repo, store)
        assert _count(repo, store) == 0

    def test_a_dispatch_with_no_stop_counts(self, repo: Path, store: RejectStore) -> None:
        """A killed reviewer, or one still running: no stop, no verdict."""
        _dispatched(repo, store)
        assert _count(repo, store) == 1

    def test_a_withdrawn_verdict_counts(self, repo: Path, store: RejectStore) -> None:
        verdict = _issue(repo, store)
        store.withdraw_verdict(verdict.verdict_id)
        assert _count(repo, store) == 1

    def test_a_failure_and_its_dispatch_count_once(self, repo: Path, store: RejectStore) -> None:
        store.write_failure(_failure(_dispatched(repo, store)))
        assert _count(repo, store) == 1

    def test_a_failure_counts_even_beside_a_verdict_file(
        self, repo: Path, store: RejectStore
    ) -> None:
        verdict = _issue(repo, store)
        request = store.read_request(verdict.nonce)
        assert request is not None
        store.write_failure(_failure(request))
        assert _count(repo, store) == 1

    def test_a_verdict_that_is_not_the_requests_own_does_not_resolve_it(
        self, repo: Path, store: RejectStore
    ) -> None:
        verdict = _issue(repo, store)
        store.write_verdict(replace(verdict, branch="elsewhere"))
        assert _count(repo, store) == 1

    def test_unrelated_work_does_not_count(self, repo: Path, store: RejectStore) -> None:
        _git(repo, "switch", "-q", "-c", "other")
        (repo / "other.py").write_text("z = 3\n", encoding="utf-8")
        _git(repo, "add", "other.py")
        _git(repo, "commit", "-q", "-m", "other work")
        _git(repo, "switch", "-q", "main")
        _dispatched(repo, store, branch="other")
        assert _count(repo, store) == 0

    def test_an_empty_commit_and_a_rename_do_not_reset_the_count(
        self, repo: Path, store: RejectStore
    ) -> None:
        old_tip = _tip(repo)
        _dispatched(repo, store)
        _git(repo, "branch", "-m", "feat", "renamed")
        _git(repo, "switch", "-q", "renamed")
        _git(repo, "commit", "-q", "--allow-empty", "-m", "nothing")
        _git(repo, "switch", "-q", "main")
        assert _tip(repo, "renamed") != old_tip
        assert _count(repo, store, "renamed") == 1

    def test_a_dispatch_whose_request_is_missing_raises(
        self, repo: Path, store: RejectStore
    ) -> None:
        request = _dispatched(repo, store)
        (store.root / "requests" / f"{request.nonce}.json").unlink()
        with pytest.raises(RejectError, match="no request"):
            _count(repo, store)

    def test_a_failure_whose_request_is_missing_raises(
        self, repo: Path, store: RejectStore
    ) -> None:
        request = _request(repo, store)
        store.write_failure(_failure(request))
        (store.root / "requests" / f"{request.nonce}.json").unlink()
        with pytest.raises(RejectError, match="no request"):
            _count(repo, store)

    def test_a_damaged_verdict_raises(self, repo: Path, store: RejectStore) -> None:
        verdict = _issue(repo, store)
        (store.root / "verdicts" / f"{verdict.verdict_id}.json").write_text("{", encoding="utf-8")
        with pytest.raises(RejectError):
            _count(repo, store)


class TestAdmissionRaisesTheBar:
    def test_one_unresolved_attempt_adds_a_reviewer(
        self, repo: Path, config: BranchRejectConfig
    ) -> None:
        inventory = compute_inventory(repo, "feat", "main")
        tip = _tip(repo)
        assert admit_request("feat", tip, inventory, [], 0, config, unresolved_attempts=1) == 2
        assert admit_request("feat", tip, inventory, [], 3, config, unresolved_attempts=1) == 3

    def test_two_unresolved_attempts_close_the_route(
        self, repo: Path, config: BranchRejectConfig
    ) -> None:
        inventory = compute_inventory(repo, "feat", "main")
        with pytest.raises(RejectRefusedError, match="a human must decide"):
            admit_request(
                "feat",
                _tip(repo),
                inventory,
                [],
                0,
                config,
                unresolved_attempts=MAX_UNRESOLVED_REVIEWS,
            )

    def test_the_count_is_required_and_keyword_only(self) -> None:
        parameter = inspect.signature(admit_request).parameters["unresolved_attempts"]
        assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
        assert parameter.default is inspect.Parameter.empty


class TestIssueRequests:
    def test_an_unparseable_reply_raises_the_bar_then_a_second_refuses(
        self, repo: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        route = _route(repo, store, config)
        (first,) = issue_requests(repo, "feat", route)
        store.write_dispatch(
            DispatchRecord(
                nonce=first.request.nonce, session_id="s1", tool_use_id="t1", agent_id="a1"
            )
        )
        store.write_failure(_failure(first.request))
        second = issue_requests(repo, "feat", route)
        assert len(second) == 2
        assert {item.request.reviewers_required for item in second} == {2}
        store.write_dispatch(
            DispatchRecord(
                nonce=second[0].request.nonce, session_id="s1", tool_use_id="t2", agent_id="a2"
            )
        )
        with pytest.raises(RejectRefusedError, match="a human must decide"):
            issue_requests(repo, "feat", route)

    def test_a_dispatch_with_no_stop_raises_the_bar(
        self, repo: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        _dispatched(repo, store)
        route = _route(repo, store, config)
        assert len(issue_requests(repo, "feat", route)) == 2


class TestApproval:
    def test_an_older_no_value_verdict_cannot_meet_the_raised_count(
        self, repo: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        _issue(repo, store, reviewer=_reviewer("first"))
        _dispatched(repo, store)
        route = _route(repo, store, config)
        assert not _delete(repo, route)
        assert read_ledger(route.ledger_path) == []

    def test_a_second_distinct_reviewer_meets_the_raised_count(
        self, repo: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        _issue(repo, store, reviewer=_reviewer("first"))
        _dispatched(repo, store)
        _issue(repo, store, reviewer=_reviewer("second"))
        assert _delete(repo, _route(repo, store, config))

    def test_two_unresolved_attempts_refuse_whatever_verdicts_exist(
        self, repo: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        for agent in ("r1", "r2", "r3", "r4"):
            _issue(repo, store, reviewer=_reviewer(agent))
        _dispatched(repo, store)
        _dispatched(repo, store)
        route = _route(repo, store, config)
        with pytest.raises(RejectRefusedError, match="a human must decide"):
            branch_reject.approve_removal(
                repo, "feat", _tip(repo), route, default_ref="main", write=False
            )
        assert not _delete(repo, route)
