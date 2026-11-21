"""The adversarial pass over the no-value route (Plan 00620 Task 2.4).

Each test is one way an agent with write access to the daemon's state could try to
get an ``unproven`` branch deleted, or to make the recovery look sound when it is not.
A refusal asserts no side effect: the branch still resolves at its tip and the ledger
gained no removal line.

A test whose name starts ``test_accepted_residue_`` pins a gap the plan accepts
(RULINGS.md Q1) rather than a refusal: it documents what the guard does NOT catch,
so a change in that behaviour is seen.
"""

from __future__ import annotations

import json
import shlex
import subprocess
from dataclasses import replace
from pathlib import Path

from claude_code_hooks_daemon.config.models import BranchRejectConfig
from claude_code_hooks_daemon.core.branch_reject import (
    DispatchRecord,
    KeepRecord,
    RejectRoute,
    RejectStore,
    Verdict,
    bundle_path_for,
    main_checkout,
    new_id,
    read_ledger,
)
from claude_code_hooks_daemon.daemon.branch_safety import DeletionReport, delete_branches
from tests.unit.core.test_branch_reject import (
    _ENV,
    NOW,
    _git,
    _issue,
    _reviewer,
    _tip,
    config,
    repo,
    store,
)
from tests.unit.core.test_branch_reject_delete import _assert_refused, _branch_exists, _route

__all__ = ["config", "repo", "store"]


def _delete(repo: Path, route: RejectRoute, branch: str = "feat") -> DeletionReport:
    return delete_branches(repo, [branch], protected_ref="main", reject_route=route)


def _verdict_path(store: RejectStore, verdict: Verdict) -> Path:
    return store.root / "verdicts" / f"{verdict.verdict_id}.json"


def _rewrite(store: RejectStore, verdict: Verdict, **changes: object) -> None:
    """Edit the verdict file in place, as a same-user agent could."""
    path = _verdict_path(store, verdict)
    data = json.loads(path.read_text(encoding="utf-8"))
    data.update(changes)
    path.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")


def _assert_untouched(repo: Path, report: DeletionReport, route: RejectRoute, tip: str) -> None:
    _assert_refused(repo, report, route)
    assert _tip(repo) == tip


class TestTamperedVerdictFiles:
    def test_a_truncated_verdict_file_refuses(
        self, repo: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        tip = _tip(repo)
        path = _verdict_path(store, _issue(repo, store))
        text = path.read_text(encoding="utf-8")
        path.write_text(text[: len(text) // 2], encoding="utf-8")
        route = _route(repo, store, config)
        _assert_untouched(repo, _delete(repo, route), route, tip)

    def test_an_empty_verdict_file_refuses(
        self, repo: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        tip = _tip(repo)
        _verdict_path(store, _issue(repo, store)).write_bytes(b"")
        route = _route(repo, store, config)
        _assert_untouched(repo, _delete(repo, route), route, tip)

    def test_a_verdict_file_that_is_not_utf8_refuses(
        self, repo: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        tip = _tip(repo)
        _verdict_path(store, _issue(repo, store)).write_bytes(b"\xff\xfe{")
        route = _route(repo, store, config)
        _assert_untouched(repo, _delete(repo, route), route, tip)

    def test_a_verdict_edited_to_another_tip_refuses(
        self, repo: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        tip = _tip(repo)
        _rewrite(store, _issue(repo, store), tip="9" * 40)
        route = _route(repo, store, config)
        _assert_untouched(repo, _delete(repo, route), route, tip)

    def test_a_verdict_edited_to_another_reviewer_agent_refuses(
        self, repo: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        """The dispatch record still binds the nonce to the original agent."""
        tip = _tip(repo)
        verdict = _issue(repo, store)
        reviewer = {**verdict.reviewer.to_dict(), "agent_id": "someone-else"}
        _rewrite(store, verdict, reviewer=reviewer)
        route = _route(repo, store, config)
        _assert_untouched(repo, _delete(repo, route), route, tip)

    def test_a_verdict_edited_to_drop_an_item_refuses(
        self, repo: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        tip = _tip(repo)
        verdict = _issue(repo, store)
        items = [item.to_dict() for item in verdict.items[1:]]
        _rewrite(store, verdict, items=items)
        route = _route(repo, store, config)
        _assert_untouched(repo, _delete(repo, route), route, tip)

    def test_a_keep_flipped_to_no_value_still_refuses_on_its_keep_record(
        self, repo: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        """The recorder files a keep record beside a keep verdict; that record is final."""
        tip = _tip(repo)
        verdict = _issue(repo, store, decision="keep")
        store.write_keep(
            KeepRecord(
                verdict_id=verdict.verdict_id,
                branch="feat",
                tip=tip,
                commits=verdict.inventory.commits,
                reasons=("still needed",),
                recorded_at=NOW - 60,
            )
        )
        items = [{**item.to_dict(), "decision": "no-value"} for item in verdict.items]
        _rewrite(store, verdict, items=items, overall="no-value")
        route = _route(repo, store, config)
        _assert_untouched(repo, _delete(repo, route), route, tip)

    def test_accepted_residue_a_keep_flipped_with_its_keep_record_removed_is_not_caught(
        self, repo: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        """RULINGS Q1: editing the verdict AND deleting the keep is forging the state.

        The guard does not re-read the reviewer's transcript at delete time, so the
        edited judgement is not detected. What bounds it is the bundle: the branch is
        restorable, and the ledger line names the removal.
        """
        verdict = _issue(repo, store, decision="keep")
        items = [{**item.to_dict(), "decision": "no-value"} for item in verdict.items]
        _rewrite(store, verdict, items=items, overall="no-value")
        route = _route(repo, store, config)
        report = _delete(repo, route)
        assert report.deleted == ("feat",)
        assert len(read_ledger(route.ledger_path)) == 1
        assert any(c.startswith("git fetch ") for c in report.restore_commands)


class TestSymlinks:
    def test_a_verdict_dir_symlinked_to_an_empty_dir_refuses(
        self, repo: Path, store: RejectStore, config: BranchRejectConfig, tmp_path: Path
    ) -> None:
        tip = _tip(repo)
        _issue(repo, store)
        verdicts = store.root / "verdicts"
        moved = tmp_path / "elsewhere"
        verdicts.rename(moved)
        empty = tmp_path / "empty"
        empty.mkdir()
        verdicts.symlink_to(empty, target_is_directory=True)
        route = _route(repo, store, config)
        _assert_untouched(repo, _delete(repo, route), route, tip)

    def test_a_used_verdict_reached_through_a_symlinked_dir_still_refuses(
        self, repo: Path, store: RejectStore, config: BranchRejectConfig, tmp_path: Path
    ) -> None:
        """Single use is read from the ledger, not from where the file lives."""
        tip = _tip(repo)
        _issue(repo, store)
        route = _route(repo, store, config)
        assert _delete(repo, route).deleted == ("feat",)
        _git(repo, "branch", "feat", tip)
        verdicts = store.root / "verdicts"
        moved = tmp_path / "elsewhere"
        verdicts.rename(moved)
        verdicts.symlink_to(moved, target_is_directory=True)
        again = _delete(repo, route)
        assert again.refused is True
        assert _tip(repo) == tip
        assert len(read_ledger(route.ledger_path)) == 1

    def test_a_verdict_file_symlinked_to_another_verdict_refuses(
        self, repo: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        """The link's name is not the id the target holds."""
        tip = _tip(repo)
        verdict = _issue(repo, store)
        target = _verdict_path(store, verdict)
        (store.root / "verdicts" / f"{new_id()}.json").symlink_to(target)
        route = _route(repo, store, config)
        _assert_untouched(repo, _delete(repo, route), route, tip)

    def test_a_planted_symlink_at_the_bundle_path_refuses(
        self, repo: Path, store: RejectStore, config: BranchRejectConfig, tmp_path: Path
    ) -> None:
        """A planted bundle has no sidecar the guard wrote, whatever it points at."""
        tip = _tip(repo)
        _issue(repo, store)
        planted = tmp_path / "planted.bundle"
        _git(repo, "bundle", "create", str(planted), "refs/heads/feat", "^main")
        path = bundle_path_for(repo, config, "feat", tip)
        path.parent.mkdir(parents=True)
        path.symlink_to(planted)
        route = _route(repo, store, config)
        _assert_untouched(repo, _delete(repo, route), route, tip)


class TestBoundToItsRequest:
    def test_a_verdict_for_another_branch_at_the_same_tip_refuses(
        self, repo: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        tip = _tip(repo)
        _git(repo, "branch", "twin", "feat")
        _issue(repo, store, branch="twin")
        route = _route(repo, store, config)
        _assert_untouched(repo, _delete(repo, route), route, tip)
        assert _tip(repo, "twin") == tip

    def test_a_verdict_relabelled_to_another_branch_refuses(
        self, repo: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        """The twin's verdict edited to name ``feat``: its request still names ``twin``."""
        tip = _tip(repo)
        _git(repo, "branch", "twin", "feat")
        _rewrite(store, _issue(repo, store, branch="twin"), branch="feat")
        route = _route(repo, store, config)
        _assert_untouched(repo, _delete(repo, route), route, tip)

    def test_a_verdict_signed_for_another_request_refuses(
        self, repo: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        """A valid feat verdict re-pointed at the twin's request and dispatch."""
        tip = _tip(repo)
        _git(repo, "branch", "twin", "feat")
        twin = _issue(repo, store, branch="twin")
        feat = _issue(repo, store)
        store.withdraw_verdict(feat.verdict_id)
        store.withdraw_verdict(twin.verdict_id)
        store.write_verdict(replace(feat, verdict_id=twin.nonce, nonce=twin.nonce))
        route = _route(repo, store, config)
        _assert_untouched(repo, _delete(repo, route), route, tip)

    def test_a_hand_written_request_with_no_dispatch_refuses(
        self, repo: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        tip = _tip(repo)
        verdict = _issue(repo, store)
        (store.root / "dispatches" / f"{verdict.nonce}.json").unlink()
        route = _route(repo, store, config)
        _assert_untouched(repo, _delete(repo, route), route, tip)

    def test_a_dispatch_hand_written_for_a_fresh_nonce_with_no_request_refuses(
        self, repo: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        tip = _tip(repo)
        verdict = _issue(repo, store)
        (store.root / "requests" / f"{verdict.nonce}.json").unlink()
        store.write_dispatch(
            DispatchRecord(
                nonce=verdict.nonce, session_id="s1", tool_use_id="toolu_y", agent_id="reviewer1"
            )
        )
        route = _route(repo, store, config)
        _assert_untouched(repo, _delete(repo, route), route, tip)

    def test_a_verdict_for_a_branch_that_has_since_moved_refuses(
        self, repo: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        """Moved BACK to an older commit, not forward: the verdict's tip is gone too."""
        _issue(repo, store)
        _git(repo, "branch", "-f", "feat", "main")
        _git(repo, "switch", "-q", "feat")
        (repo / "other.py").write_text("z\n", encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "other")
        _git(repo, "switch", "-q", "main")
        tip = _tip(repo)
        route = _route(repo, store, config)
        _assert_untouched(repo, _delete(repo, route), route, tip)


class TestSlugCollision:
    """``a/b`` and ``a-b`` at one tip share ``a-b-<tip12>.bundle``.

    The second removal finds the first one's bundle at its path. That bundle lists
    ``refs/heads/a/b``, never ``refs/heads/a-b``, so it is refused rather than reused:
    the collision costs a refusal (fail closed), never a bundle that restores the
    wrong branch.
    """

    def test_the_second_branch_is_refused_not_given_the_first_ones_bundle(
        self, repo: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        _git(repo, "branch", "a/b", "feat")
        _git(repo, "branch", "a-b", "feat")
        tip = _tip(repo, "a-b")
        assert bundle_path_for(repo, config, "a/b", tip) == bundle_path_for(
            repo, config, "a-b", tip
        )
        _issue(repo, store, branch="a/b")
        _issue(repo, store, branch="a-b")
        route = _route(repo, store, config)
        assert _delete(repo, route, "a/b").deleted == ("a/b",)
        second = _delete(repo, route, "a-b")
        assert second.refused is True
        assert _tip(repo, "a-b") == tip
        assert [line.branch for line in read_ledger(route.ledger_path)] == ["a/b"]


class TestRestoreWhenTheBundleIsGone:
    """RULINGS section 1: the guard proves the bundle at the delete, not afterwards."""

    def _removed(
        self, repo: Path, store: RejectStore, config: BranchRejectConfig
    ) -> tuple[str, DeletionReport]:
        tip = _tip(repo)
        _issue(repo, store)
        report = _delete(repo, _route(repo, store, config))
        assert report.deleted == ("feat",)
        return tip, report

    def _run(self, repo: Path, command: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            shlex.split(command),
            cwd=repo,
            capture_output=True,
            text=True,
            env={**_ENV, "HOME": str(repo)},
            check=False,
        )

    def _fetch(self, report: DeletionReport) -> str:
        return next(c for c in report.restore_commands if c.startswith("git fetch "))

    def test_a_missing_bundle_fails_the_fetch_line_loudly(
        self, repo: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        tip, report = self._removed(repo, store, config)
        bundle_path_for(repo, config, "feat", tip).unlink()
        assert self._run(repo, self._fetch(report)).returncode != 0
        assert not _branch_exists(repo)

    def test_a_bundle_with_a_corrupted_header_fails_the_fetch_line_loudly(
        self, repo: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        tip, report = self._removed(repo, store, config)
        path = bundle_path_for(repo, config, "feat", tip)
        path.write_bytes(b"not a bundle\n" + path.read_bytes())
        assert self._run(repo, self._fetch(report)).returncode != 0
        assert not _branch_exists(repo)

    def test_a_truncated_pack_restores_only_the_recorded_tip_from_local_objects(
        self, repo: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        """While this clone still holds the commit, git needs nothing from the pack.

        The fetch then succeeds and the branch is back at the recorded tip, never at
        another commit. In a clone that has pruned the objects the same file fails.
        """
        tip, report = self._removed(repo, store, config)
        path = bundle_path_for(repo, config, "feat", tip)
        data = path.read_bytes()
        path.write_bytes(data[: len(data) // 2])
        result = self._run(repo, self._fetch(report))
        if result.returncode == 0:
            assert _tip(repo) == tip
        else:
            assert not _branch_exists(repo)

    def test_the_branch_line_restores_while_git_still_holds_the_commit(
        self, repo: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        tip, report = self._removed(repo, store, config)
        bundle_path_for(repo, config, "feat", tip).unlink()
        assert self._run(repo, f"git branch feat {tip}").returncode == 0
        assert f"git branch feat {tip}" in report.restore_commands
        assert _tip(repo) == tip


def _checkout_route(checkout: Path, config: BranchRejectConfig) -> RejectRoute:
    """The route as ``delete-branch`` builds it in ``checkout``: its own ledger, shared state."""
    shared = RejectStore(main_checkout(checkout) / config.state_dir)
    return RejectRoute(
        store=shared, ledger_path=checkout / config.ledger_path, config=config, now=NOW
    )


class TestSingleUseAcrossCheckouts:
    """RULINGS Q8: single use and the rate hold across every checkout of the repository.

    The tracked ledger is per checkout; the consumed markers and the removal count live
    in the shared main-checkout state directory, which every worktree resolves alike.
    """

    def test_a_second_worktree_cannot_reuse_a_used_verdict(
        self, repo: Path, store: RejectStore, config: BranchRejectConfig, tmp_path: Path
    ) -> None:
        tip = _tip(repo)
        _issue(repo, store)
        assert _delete(repo, _checkout_route(repo, config)).deleted == ("feat",)
        _git(repo, "branch", "feat", tip)
        linked = tmp_path / "linked"
        _git(repo, "worktree", "add", "-q", "--detach", str(linked), "main")
        other = _checkout_route(linked, config)
        report = delete_branches(linked, ["feat"], protected_ref="main", reject_route=other)
        assert report.refused is True
        assert report.deleted == ()
        assert _tip(repo) == tip
        assert any("already used" in b for b in report.blockers)
        assert read_ledger(other.ledger_path) == []

    def test_a_checkout_switched_to_an_older_commit_cannot_reuse_a_used_verdict(
        self, repo: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        """The committed ledger line is gone from the work tree; the shared marker is not."""
        tip = _tip(repo)
        _issue(repo, store)
        route = _checkout_route(repo, config)
        assert _delete(repo, route).deleted == ("feat",)
        _git(repo, "add", config.ledger_path)
        _git(repo, "commit", "-q", "-m", "ledger")
        _git(repo, "switch", "-q", "--detach", "HEAD~1")
        assert not route.ledger_path.exists()
        _git(repo, "branch", "feat", tip)
        report = _delete(repo, route)
        assert report.refused is True
        assert _tip(repo) == tip
        assert any("already used" in b for b in report.blockers)

    def test_the_rate_cap_counts_removals_made_in_other_worktrees(
        self, repo: Path, store: RejectStore, tmp_path: Path
    ) -> None:
        config = BranchRejectConfig(two_reviewer_after=1, refuse_after=1)
        _git(repo, "branch", "twin", "feat")
        _issue(repo, store)
        assert _delete(repo, _checkout_route(repo, config)).deleted == ("feat",)
        _issue(repo, store, branch="twin", reviewer=_reviewer(agent_id="reviewer2"))
        linked = tmp_path / "linked"
        _git(repo, "worktree", "add", "-q", "--detach", str(linked), "main")
        other = _checkout_route(linked, config)
        tip = _tip(repo, "twin")
        report = delete_branches(linked, ["twin"], protected_ref="main", reject_route=other)
        assert report.refused is True
        assert _tip(repo, "twin") == tip
        assert any("removal rate" in b for b in report.blockers)

    def test_a_git_refused_removal_does_not_count_toward_the_shared_rate(
        self, repo: Path, store: RejectStore
    ) -> None:
        config = BranchRejectConfig(two_reviewer_after=1, refuse_after=1)
        _issue(repo, store)
        route = _checkout_route(repo, config)
        lock = repo / ".git" / "refs" / "heads" / "feat.lock"
        lock.write_text("held\n", encoding="utf-8")
        assert _delete(repo, route).refused is True
        lock.unlink()
        _issue(repo, store, reviewer=_reviewer(agent_id="reviewer2"))
        assert _delete(repo, route).deleted == ("feat",)

    def test_a_file_in_place_of_the_consumed_directory_refuses(
        self, repo: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        """A store kind that is not a directory is unreadable, never "nothing consumed"."""
        tip = _tip(repo)
        _issue(repo, store)
        store.root.mkdir(parents=True, exist_ok=True)
        (store.root / "consumed").write_text("", encoding="utf-8")
        route = _checkout_route(repo, config)
        _assert_untouched(repo, _delete(repo, route), route, tip)
