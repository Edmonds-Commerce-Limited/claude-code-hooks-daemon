"""RED tests for the delete path of the no-value route (Plan 00620, DESIGN.md section 10).

Committed RED in slice 1, as the plan's security rules require: they pin the slice 2
contract before any code loosens the guard. ``delete_branches`` takes no
``reject_route`` yet, so every test here fails until slice 2 wires it.

The refusal tests are the point. Each names one way an agent could try to get an
``unproven`` branch deleted (a forged, reused, stale, wrong-tip or self-written
verdict, a verdict with no verified bundle, a bundle with no verdict) and asserts the
branch survives. Only the last class shows the route working at all.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from claude_code_hooks_daemon.config.models import BranchRejectConfig
from claude_code_hooks_daemon.core.branch_reject import (
    TIER_REJECTED_BUNDLED,
    RejectRoute,
    RejectStore,
    Verdict,
    bundle_path_for,
    read_ledger,
    write_bundle,
)
from claude_code_hooks_daemon.daemon.branch_safety import DeletionReport, delete_branches
from tests.unit.core.test_branch_reject import (
    HOUR,
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
