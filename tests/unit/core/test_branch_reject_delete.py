"""Tests for the delete path of the no-value route (Plan 00620, DESIGN.md section 10).

The refusal classes were committed RED in slice 1, as the plan's security rules
require, to pin the slice 2 contract before any code loosened the guard.

The refusal tests are the point. Each names one way an agent could try to get an
``unproven`` branch deleted (a forged, reused, stale, wrong-tip or self-written
verdict, a verdict with no verified bundle, a bundle with no verdict) and asserts the
branch survives. Only the last class shows the route working at all.
"""

from __future__ import annotations

import shlex
from dataclasses import replace
from pathlib import Path

import pytest

from claude_code_hooks_daemon.config.models import BranchRejectConfig
from claude_code_hooks_daemon.core.branch_reject import (
    TIER_REJECTED_BUNDLED,
    LedgerLine,
    LedgerRefusal,
    RejectRoute,
    RejectStore,
    Verdict,
    append_ledger,
    bundle_path_for,
    read_ledger,
    read_ledger_entries,
    write_bundle,
)
from claude_code_hooks_daemon.daemon.branch_safety import DeletionReport, delete_branches
from tests.unit.core.test_branch_reject import (
    HOUR,
    NOW,
    _git,
    _issue,
    _ledger_line,
    _main_sha,
    _reviewer,
    _tip,
    config,
    repo,
    store,
)

__all__ = ["config", "repo", "store"]


def _route(repo: Path, store: RejectStore, config: BranchRejectConfig) -> RejectRoute:
    return RejectRoute(store=store, ledger_path=repo / config.ledger_path, config=config, now=NOW)


def _delete(repo: Path, route: RejectRoute) -> DeletionReport:
    return delete_branches(repo, ["feat"], protected_ref="main", reject_route=route)


def _branch_exists(repo: Path) -> bool:
    return bool(_git(repo, "for-each-ref", "refs/heads/feat").strip())


def _assert_refused(repo: Path, report: DeletionReport, route: RejectRoute) -> None:
    assert report.refused is True
    assert report.deleted == ()
    assert _branch_exists(repo)
    assert read_ledger(route.ledger_path) == []


class TestRefusals:
    def test_no_verdict_refuses(
        self, repo: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        route = _route(repo, store, config)
        _assert_refused(repo, _delete(repo, route), route)

    def test_a_bundle_alone_unlocks_nothing(
        self, repo: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        write_bundle(repo, "feat", _tip(repo), _main_sha(repo), config)
        route = _route(repo, store, config)
        _assert_refused(repo, _delete(repo, route), route)

    def test_a_forged_verdict_with_no_request_or_dispatch_refuses(
        self, repo: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        verdict = _issue(repo, store)
        (store.root / "requests" / f"{verdict.nonce}.json").unlink()
        (store.root / "dispatches" / f"{verdict.nonce}.json").unlink()
        route = _route(repo, store, config)
        _assert_refused(repo, _delete(repo, route), route)

    def test_a_reused_verdict_refuses(
        self, repo: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        tip = _tip(repo)
        _issue(repo, store)
        route = _route(repo, store, config)
        first = _delete(repo, route)
        assert first.deleted == ("feat",)
        _git(repo, "branch", "feat", tip)
        second = _delete(repo, route)
        assert second.refused is True
        assert _branch_exists(repo)
        assert len(read_ledger(route.ledger_path)) == 1

    def test_a_stale_verdict_refuses(
        self, repo: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        _issue(repo, store, issued_at=NOW - 25 * HOUR)
        route = _route(repo, store, config)
        _assert_refused(repo, _delete(repo, route), route)

    def test_a_wrong_tip_verdict_refuses(
        self, repo: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        _issue(repo, store)
        _git(repo, "switch", "-q", "feat")
        (repo / "src" / "more.py").write_text("y\n", encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "more")
        _git(repo, "switch", "-q", "main")
        route = _route(repo, store, config)
        _assert_refused(repo, _delete(repo, route), route)

    @pytest.mark.parametrize("agent_id", ["creator", "toucher"])
    def test_a_self_written_verdict_refuses(
        self, repo: Path, store: RejectStore, config: BranchRejectConfig, agent_id: str
    ) -> None:
        _issue(repo, store, reviewer=_reviewer(agent_id=agent_id))
        route = _route(repo, store, config)
        _assert_refused(repo, _delete(repo, route), route)

    def test_a_valid_verdict_with_no_verified_bundle_refuses(
        self, repo: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        _issue(repo, store)
        path = bundle_path_for(repo, config, "feat", _tip(repo))
        path.parent.mkdir(parents=True)
        path.write_bytes(b"not a bundle")
        route = _route(repo, store, config)
        _assert_refused(repo, _delete(repo, route), route)

    def test_a_keep_verdict_refuses(
        self, repo: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        _issue(repo, store, decision="keep")
        route = _route(repo, store, config)
        _assert_refused(repo, _delete(repo, route), route)

    def test_without_a_route_unproven_is_refused_as_today(
        self, repo: Path, store: RejectStore
    ) -> None:
        _issue(repo, store)
        report = delete_branches(repo, ["feat"], protected_ref="main")
        assert report.refused is True
        assert _branch_exists(repo)


class TestTheRoute:
    def test_a_valid_verdict_and_bundle_delete_and_record(
        self, repo: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        tip = _tip(repo)
        verdict: Verdict = _issue(repo, store)
        route = _route(repo, store, config)
        report = _delete(repo, route)
        assert report.deleted == ("feat",)
        assert not _branch_exists(repo)
        assert report.classifications[0].tier == TIER_REJECTED_BUNDLED
        bundle = bundle_path_for(repo, config, "feat", tip)
        assert any(c.startswith("git fetch ") and str(bundle) in c for c in report.restore_commands)
        assert f"git branch feat {tip}" in report.restore_commands
        (line,) = read_ledger(route.ledger_path)
        assert line.verdict_ids == (verdict.verdict_id,)
        assert line.tip == tip
        assert line.bundle_path == str(bundle)
        assert line.default_sha == _main_sha(repo)
        assert line.restore_commands == tuple(report.restore_commands)

    def test_the_restore_lines_bring_the_branch_back(
        self, repo: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        tip = _tip(repo)
        _issue(repo, store)
        report = _delete(repo, _route(repo, store, config))
        fetch = next(c for c in report.restore_commands if c.startswith("git fetch "))
        _git(repo, *shlex.split(fetch)[1:])
        assert _tip(repo) == tip


class TestRouteStrictness:
    def test_a_dry_run_writes_nothing(
        self, repo: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        _issue(repo, store)
        route = _route(repo, store, config)
        report = delete_branches(
            repo, ["feat"], protected_ref="main", reject_route=route, dry_run=True
        )
        assert report.refused is False
        assert report.deleted == ()
        assert report.classifications[0].tier == TIER_REJECTED_BUNDLED
        assert _branch_exists(repo)
        assert not bundle_path_for(repo, config, "feat", _tip(repo)).exists()
        assert read_ledger_entries(route.ledger_path) == []

    def test_a_refused_classification_is_not_unlocked(
        self, repo: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        _issue(repo, store)
        route = _route(repo, store, config)
        report = delete_branches(
            repo, ["feat"], protected_ref="main", protected_names=("feat",), reject_route=route
        )
        _assert_refused(repo, report, route)

    def test_a_keep_beside_a_valid_no_value_refuses(
        self, repo: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        _issue(repo, store)
        _issue(repo, store, reviewer=_reviewer(agent_id="reviewer2"), decision="keep")
        route = _route(repo, store, config)
        _assert_refused(repo, _delete(repo, route), route)

    def test_the_rate_is_recomputed_at_delete_time(
        self, repo: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        route = _route(repo, store, config)
        for _ in range(config.two_reviewer_after):
            append_ledger(route.ledger_path, _ledger_line(branch="old", removed_at=NOW - HOUR))
        _issue(repo, store)
        report = _delete(repo, route)
        assert report.refused is True
        assert _branch_exists(repo)
        assert any("distinct" in b for b in report.blockers)

    def test_two_distinct_reviewers_meet_the_raised_rate(
        self, repo: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        route = _route(repo, store, config)
        for _ in range(config.two_reviewer_after):
            append_ledger(route.ledger_path, _ledger_line(branch="old", removed_at=NOW - HOUR))
        _issue(repo, store)
        _issue(repo, store, reviewer=_reviewer(agent_id="reviewer2"))
        assert _delete(repo, route).deleted == ("feat",)

    def test_a_damaged_ledger_refuses_without_a_traceback(
        self, repo: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        _issue(repo, store)
        route = _route(repo, store, config)
        route.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        route.ledger_path.write_text("not json\n", encoding="utf-8")
        report = _delete(repo, route)
        assert report.refused is True
        assert _branch_exists(repo)
        assert any("ledger" in b for b in report.blockers)

    def test_one_unapproved_branch_removes_none_of_the_batch(
        self, repo: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        _git(repo, "branch", "other", "feat")
        _git(repo, "switch", "-q", "other")
        (repo / "src" / "other.py").write_text("o\n", encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "other")
        _git(repo, "switch", "-q", "main")
        _issue(repo, store)
        route = _route(repo, store, config)
        report = delete_branches(repo, ["feat", "other"], protected_ref="main", reject_route=route)
        assert report.refused is True
        assert report.deleted == ()
        assert _branch_exists(repo)
        assert read_ledger_entries(route.ledger_path) == []

    def test_a_git_refusal_after_the_append_is_recorded(
        self, repo: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        """The line goes in before git is asked; a refusal leaves a second line saying so."""
        _issue(repo, store)
        route = _route(repo, store, config)
        lock = repo / ".git" / "refs" / "heads" / "feat.lock"
        lock.write_text("held\n", encoding="utf-8")
        report = _delete(repo, route)
        lock.unlink()
        assert report.refused is True
        assert report.deleted == ()
        assert _branch_exists(repo)
        entries = read_ledger_entries(route.ledger_path)
        assert [type(e) for e in entries] == [LedgerLine, LedgerRefusal]
        assert read_ledger(route.ledger_path) == []
        assert any("git refused" in b for b in report.blockers)

    def test_a_refused_attempt_cannot_be_retried_on_the_same_verdict(
        self, repo: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        _issue(repo, store)
        route = _route(repo, store, config)
        lock = repo / ".git" / "refs" / "heads" / "feat.lock"
        lock.write_text("held\n", encoding="utf-8")
        _delete(repo, route)
        lock.unlink()
        again = _delete(repo, route)
        assert again.refused is True
        assert _branch_exists(repo)
        assert any("already used" in b for b in again.blockers)

    def test_the_route_judges_against_its_own_default_ref(
        self, repo: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        """An integration line proves merges; the route still measures against the default."""
        _git(repo, "switch", "-q", "-c", "line")
        (repo / "line.txt").write_text("l\n", encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "line")
        _git(repo, "switch", "-q", "main")
        _issue(repo, store)
        route = replace(_route(repo, store, config), default_ref="main")
        report = delete_branches(
            repo, ["feat"], protected_ref="line", targets=("line",), reject_route=route
        )
        assert report.deleted == ("feat",)
        (line,) = read_ledger(route.ledger_path)
        assert line.default_sha == _main_sha(repo)
