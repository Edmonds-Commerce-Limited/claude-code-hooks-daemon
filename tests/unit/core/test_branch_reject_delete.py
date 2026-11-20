"""Tests for the delete path of the no-value route (Plan 00620, DESIGN.md section 10).

The refusal classes were committed RED in slice 1, as the plan's security rules
require, to pin the slice 2 contract before any code loosened the guard.

The refusal tests are the point. Each names one way an agent could try to get an
``unproven`` branch deleted (a forged, reused, stale, wrong-tip or self-written
verdict, a verdict with no verified bundle, a bundle with no verdict) and asserts the
branch survives. Only the last class shows the route working at all.
"""

from __future__ import annotations

import json
import shlex
import subprocess
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.config.models import BranchRejectConfig
from claude_code_hooks_daemon.core import branch_reject
from claude_code_hooks_daemon.core.branch_reject import (
    TIER_REJECTED_BUNDLED,
    LedgerLine,
    LedgerRefusal,
    RejectError,
    RejectRoute,
    RejectStore,
    RemovalApproval,
    Verdict,
    append_ledger,
    bundle_path_for,
    new_id,
    read_ledger,
    read_ledger_entries,
    write_bundle,
)
from claude_code_hooks_daemon.daemon import branch_safety
from claude_code_hooks_daemon.daemon.branch_safety import DeletionReport, delete_branches
from tests.unit.core.test_branch_reject import (
    HOUR,
    NOW,
    _commit,
    _git,
    _issue,
    _ledger_line,
    _main_sha,
    _problems,
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


def _second_branch(repo: Path, name: str = "other") -> None:
    _git(repo, "branch", name, "main")
    _git(repo, "switch", "-q", name)
    (repo / "src").mkdir(exist_ok=True)
    (repo / "src" / f"{name}.py").write_text("o\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", name)
    _git(repo, "switch", "-q", "main")


class TestBatchAndFailures:
    def test_a_batch_counts_its_own_approvals_against_the_rate(
        self, repo: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        """Nothing is appended until phase two, so the batch itself must be counted."""
        _second_branch(repo)
        route = _route(repo, store, config)
        for _ in range(config.two_reviewer_after - 1):
            append_ledger(route.ledger_path, _ledger_line(branch="old", removed_at=NOW - HOUR))
        before = len(read_ledger_entries(route.ledger_path))
        _issue(repo, store)
        _issue(repo, store, branch="other")
        report = delete_branches(repo, ["feat", "other"], protected_ref="main", reject_route=route)
        assert report.refused is True
        assert report.deleted == ()
        assert _branch_exists(repo)
        assert len(read_ledger_entries(route.ledger_path)) == before

    def test_a_failed_refusal_append_says_the_ledger_is_wrong(
        self,
        repo: Path,
        store: RejectStore,
        config: BranchRejectConfig,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _issue(repo, store)
        route = _route(repo, store, config)

        def _fail(*_args: object) -> None:
            raise RejectError("disk full")

        monkeypatch.setattr(branch_reject, "append_refusal", _fail)
        lock = repo / ".git" / "refs" / "heads" / "feat.lock"
        lock.write_text("held\n", encoding="utf-8")
        report = _delete(repo, route)
        lock.unlink()
        assert report.refused is True
        assert _branch_exists(repo)
        assert any("wrongly records" in b for b in report.blockers)

    def test_a_bundle_changed_after_approval_refuses_before_the_append(
        self,
        repo: Path,
        store: RejectStore,
        config: BranchRejectConfig,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _issue(repo, store)
        route = _route(repo, store, config)
        real = branch_reject.record_removal

        def _tamper(repo_: Path, approval: RemovalApproval, route_: RejectRoute) -> LedgerLine:
            assert approval.bundle is not None
            approval.bundle.path.write_bytes(b"replaced")
            return real(repo_, approval, route_)

        monkeypatch.setattr(branch_reject, "record_removal", _tamper)
        report = _delete(repo, route)
        assert report.refused is True
        assert _branch_exists(repo)
        assert read_ledger_entries(route.ledger_path) == []
        assert any("no longer verifies" in b for b in report.blockers)


def _during_record(monkeypatch: pytest.MonkeyPatch, action: Callable[[], object]) -> None:
    """Run ``action`` inside the window between the ledger append and git's delete."""
    real = branch_reject.record_removal

    def _then_act(repo_: Path, approval: RemovalApproval, route_: RejectRoute) -> LedgerLine:
        line = real(repo_, approval, route_)
        action()
        return line

    monkeypatch.setattr(branch_reject, "record_removal", _then_act)


def _config_keys(repo: Path, branch: str = "feat") -> list[str]:
    listing = _git(repo, "config", "--local", "--name-only", "--list")
    return [key for key in listing.splitlines() if key.startswith(f"branch.{branch}.")]


def _assert_cancelled(repo: Path, report: DeletionReport, route: RejectRoute) -> None:
    assert report.refused is True
    assert report.deleted == ()
    entries = read_ledger_entries(route.ledger_path)
    assert [type(e) for e in entries] == [LedgerLine, LedgerRefusal]
    assert read_ledger(route.ledger_path) == []


class TestCompareAndDelete:
    """git deletes the branch only while it still points at the tip the verdict covered.

    The proof and the verdicts are about one sha. A branch moved after the tip re-check
    (``git branch -f``, ``git fetch . y:x``) holds commits no reviewer saw and no bundle
    carries, so the delete is a compare-and-delete and git refuses a moved ref.
    """

    def test_a_branch_moved_after_the_proof_survives(
        self,
        repo: Path,
        store: RejectStore,
        config: BranchRejectConfig,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _issue(repo, store)
        route = _route(repo, store, config)
        _git(repo, "switch", "-q", "-c", "elsewhere", "main")
        moved_to = _commit(repo, "late.py", "late\n", "late work")
        _git(repo, "switch", "-q", "main")
        _during_record(monkeypatch, lambda: _git(repo, "branch", "-f", "feat", moved_to))
        report = _delete(repo, route)
        assert _tip(repo) == moved_to
        _assert_cancelled(repo, report, route)
        assert any("git refused" in b for b in report.blockers)
        assert _config_keys(repo), "a refused delete must leave branch.feat.* in place"

    def test_a_worktree_added_after_the_proof_refuses(
        self,
        repo: Path,
        store: RejectStore,
        config: BranchRejectConfig,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A compare-and-delete skips git's worktree check, so the guard makes it itself."""
        _issue(repo, store)
        route = _route(repo, store, config)
        tip = _tip(repo)
        peer = repo.parent / "peer"
        _during_record(monkeypatch, lambda: _git(repo, "worktree", "add", "-q", str(peer), "feat"))
        report = _delete(repo, route)
        assert _tip(repo) == tip
        _assert_cancelled(repo, report, route)
        assert any("worktree" in b for b in report.blockers)

    def test_a_branch_turned_into_a_symref_after_the_proof_refuses(
        self,
        repo: Path,
        store: RejectStore,
        config: BranchRejectConfig,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A dereferencing delete would remove the TARGET, a branch nobody judged."""
        _issue(repo, store)
        route = _route(repo, store, config)
        tip = _tip(repo)
        _git(repo, "branch", "target", tip)

        def _alias() -> None:
            _git(repo, "update-ref", "-d", "refs/heads/feat")
            _git(repo, "symbolic-ref", "refs/heads/feat", "refs/heads/target")

        _during_record(monkeypatch, _alias)
        report = _delete(repo, route)
        assert _tip(repo, "target") == tip
        assert _branch_exists(repo)
        _assert_cancelled(repo, report, route)

    def test_a_removal_takes_the_branch_config_and_reflog_with_it(
        self, repo: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        """What ``git branch -D`` removes, the compare-and-delete removes too."""
        _issue(repo, store)
        assert _config_keys(repo)
        report = _delete(repo, _route(repo, store, config))
        assert report.deleted == ("feat",)
        assert report.refused is False
        assert _config_keys(repo) == []
        assert not (repo / ".git" / "logs" / "refs" / "heads" / "feat").exists()

    def test_a_branch_with_no_config_section_is_removed(
        self, repo: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        _issue(repo, store)
        _git(repo, "config", "--remove-section", "branch.feat")
        report = _delete(repo, _route(repo, store, config))
        assert report.deleted == ("feat",)
        assert report.refused is False

    def test_a_failed_config_cleanup_never_cancels_a_real_removal(
        self,
        repo: Path,
        store: RejectStore,
        config: BranchRejectConfig,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The ref is gone once git said so; cancelling it would undercount the rate."""
        _issue(repo, store)
        route = _route(repo, store, config)
        real = branch_safety._git

        def _config_fails(
            repo_: Path, *args: str, **kwargs: Any
        ) -> subprocess.CompletedProcess[str]:
            if args[:2] == ("config", "--remove-section"):
                return subprocess.CompletedProcess(list(args), 5, "", "could not lock config")
            return real(repo_, *args, **kwargs)

        monkeypatch.setattr(branch_safety, "_git", _config_fails)
        report = _delete(repo, route)
        assert report.deleted == ("feat",)
        assert not _branch_exists(repo)
        assert [type(e) for e in read_ledger_entries(route.ledger_path)] == [LedgerLine]


class TestRecordRemoval:
    def _approval(
        self, repo: Path, store: RejectStore, route: RejectRoute, *, write: bool = True
    ) -> RemovalApproval:
        return branch_reject.approve_removal(
            repo, "feat", _tip(repo), route, default_ref="main", write=write
        )

    def test_a_dry_run_approval_records_nothing(
        self, repo: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        _issue(repo, store)
        route = _route(repo, store, config)
        approval = self._approval(repo, store, route, write=False)
        with pytest.raises(RejectError, match="dry-run"):
            branch_reject.record_removal(repo, approval, route)

    def test_a_concurrent_consume_refuses(
        self, repo: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        _issue(repo, store)
        route = _route(repo, store, config)
        approval = self._approval(repo, store, route)
        branch_reject.record_removal(repo, approval, route)
        with pytest.raises(RejectError, match="concurrent"):
            branch_reject.record_removal(repo, approval, route)
        assert len(read_ledger_entries(route.ledger_path)) == 1

    def test_a_concurrent_use_of_the_same_reviewer_agent_refuses(
        self, repo: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        verdict = _issue(repo, store)
        route = _route(repo, store, config)
        approval = self._approval(repo, store, route)
        line = replace(_ledger_line(branch="old"), reviewer_agent_ids=(verdict.reviewer.agent_id,))
        append_ledger(route.ledger_path, line)
        with pytest.raises(RejectError, match="concurrent"):
            branch_reject.record_removal(repo, approval, route)
        assert len(read_ledger_entries(route.ledger_path)) == 1


def _copy_under_new_id(store: RejectStore, verdict: Verdict) -> Verdict:
    """What an agent with write access to the store could do: re-file a verdict."""
    copy = replace(verdict, verdict_id=new_id())
    (store.root / "verdicts" / f"{copy.verdict_id}.json").write_text(
        json.dumps(copy.to_dict(), sort_keys=True), encoding="utf-8"
    )
    return copy


class TestVerdictIdentity:
    """Single use is keyed on the verdict id, so the id must be bound to the nonce.

    The recorder writes ``verdict_id = nonce`` and one nonce binds one reviewer stop;
    a verdict filed under any other id, or a file whose name is not its id, is a copy
    nobody's stop produced, and it must never count.
    """

    def test_a_used_verdict_copied_under_a_new_id_refuses(
        self, repo: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        tip = _tip(repo)
        verdict = _issue(repo, store)
        route = _route(repo, store, config)
        assert _delete(repo, route).deleted == ("feat",)
        _git(repo, "branch", "feat", tip)
        _copy_under_new_id(store, verdict)
        again = _delete(repo, route)
        assert again.refused is True
        assert _branch_exists(repo)
        assert len(read_ledger(route.ledger_path)) == 1

    def test_a_git_refused_verdict_copied_under_a_new_id_refuses(
        self, repo: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        verdict = _issue(repo, store)
        route = _route(repo, store, config)
        lock = repo / ".git" / "refs" / "heads" / "feat.lock"
        lock.write_text("held\n", encoding="utf-8")
        _delete(repo, route)
        lock.unlink()
        _copy_under_new_id(store, verdict)
        again = _delete(repo, route)
        assert again.refused is True
        assert _branch_exists(repo)
        assert read_ledger(route.ledger_path) == []

    def test_a_verdict_whose_id_is_not_its_nonce_refuses(
        self, repo: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        verdict = _issue(repo, store)
        store.withdraw_verdict(verdict.verdict_id)
        _copy_under_new_id(store, verdict)
        route = _route(repo, store, config)
        _assert_refused(repo, _delete(repo, route), route)

    def test_a_verdict_problem_names_the_id_nonce_mismatch(
        self, repo: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        verdict = replace(_issue(repo, store), verdict_id=new_id())
        found = _problems(repo, store, verdict, config)
        assert any("is not its nonce" in p for p in found)

    def test_a_verdict_filed_under_another_name_refuses(
        self, repo: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        """The content is untouched (id == nonce), only the file name differs."""
        verdict = _issue(repo, store)
        original = store.root / "verdicts" / f"{verdict.verdict_id}.json"
        original.rename(original.with_name(f"{new_id()}.json"))
        route = _route(repo, store, config)
        _assert_refused(repo, _delete(repo, route), route)

    def test_a_used_nonce_refuses_whatever_id_it_is_filed_under(
        self, repo: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        """Defence in depth: the ledger's consumed set is checked against the nonce too."""
        verdict = replace(_issue(repo, store), verdict_id=new_id())
        found = _problems(repo, store, verdict, config, consumed=frozenset({verdict.nonce}))
        assert any("already used" in p for p in found)

    def test_a_used_chain_replayed_under_a_fresh_nonce_refuses(
        self, repo: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        """Request, dispatch and verdict all copied under a new nonce, nothing else edited.

        Each id check passes (id == nonce == file name), so single use must also be
        keyed on the reviewer agent: one agent reviews one nonce, and the ledger names it.
        Writing a NEW agent id into the copies is forging, the residue RULINGS Q1 accepts.
        """
        tip = _tip(repo)
        verdict = _issue(repo, store)
        route = _route(repo, store, config)
        assert _delete(repo, route).deleted == ("feat",)
        _git(repo, "branch", "feat", tip)
        fresh = new_id()
        request = store.read_request(verdict.nonce)
        dispatch = store.read_dispatch(verdict.nonce)
        assert request is not None and dispatch is not None
        store.write_request(replace(request, nonce=fresh))
        store.write_dispatch(replace(dispatch, nonce=fresh))
        store.write_verdict(replace(verdict, verdict_id=fresh, nonce=fresh))
        again = _delete(repo, route)
        assert again.refused is True
        assert _branch_exists(repo)
        assert len(read_ledger(route.ledger_path)) == 1
        assert any("reviewer agent" in b and "already" in b for b in again.blockers)
