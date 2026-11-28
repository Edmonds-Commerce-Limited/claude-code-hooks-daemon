"""The no-value route for a REMOTE branch whose pull request closed unmerged (N763).

Every fixture is a throwaway clone of a local bare ``origin`` under ``tmp_path``, and
``gh`` is a fake runner returning canned JSON, so nothing here reaches a real remote.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

import pytest

from claude_code_hooks_daemon.config.models import BranchesConfig
from claude_code_hooks_daemon.core import branch_reject_remote as remote_route
from claude_code_hooks_daemon.core.branch_reject import (
    DECISION_NO_VALUE,
    DispatchRecord,
    RejectError,
    RejectRefusedError,
    RejectRoute,
    RejectStore,
    Verdict,
    compute_inventory,
    read_ledger,
)
from claude_code_hooks_daemon.utils.github_issue_validity import GhError
from tests.support.git_fixtures import run_git
from tests.unit.core.test_branch_reject import HOUR, NOW, _items, _reviewer
from tests.unit.core.test_branch_reject import _git as _git_out

REMOTE = "origin"
PR = 17


def _git(repo: Path, *args: str) -> str:
    """Stdout of git in ``repo``; raises on failure."""
    return _git_out(repo, *args)


@pytest.fixture
def origin_and_clone(tmp_path: Path) -> tuple[Path, Path]:
    """``origin`` holds ``main`` and ``novel`` (one unique file); the clone has no local ``novel``."""
    origin = tmp_path / "origin.git"
    work = tmp_path / "work"
    run_git(tmp_path, "init", "--bare", "--initial-branch=main", str(origin))
    run_git(tmp_path, "init", "--initial-branch=main", str(work))
    run_git(work, "config", "user.email", "t@example.invalid")
    run_git(work, "config", "user.name", "Tester")
    run_git(work, "config", "commit.gpgsign", "false")
    run_git(work, "remote", "add", REMOTE, str(origin))
    (work / "README.md").write_text("base\n", encoding="utf-8")
    run_git(work, "add", "README.md")
    run_git(work, "commit", "-m", "base")
    run_git(work, "push", "-u", REMOTE, "main")
    run_git(work, "remote", "set-head", REMOTE, "main")
    run_git(work, "checkout", "-q", "-b", "novel", "main")
    (work / "src").mkdir()
    (work / "src" / "novel.py").write_text("x = 1\n", encoding="utf-8")
    run_git(work, "add", "src/novel.py")
    run_git(work, "commit", "-m", "novel work")
    run_git(work, "push", "-u", REMOTE, "novel")
    run_git(work, "checkout", "-q", "main")
    run_git(work, "branch", "-D", "novel")
    run_git(work, "fetch", REMOTE)
    return origin, work


@pytest.fixture
def work(origin_and_clone: tuple[Path, Path]) -> Path:
    return origin_and_clone[1]


@pytest.fixture
def branches() -> BranchesConfig:
    return BranchesConfig(default="main")


@pytest.fixture
def route(work: Path, branches: BranchesConfig) -> RejectRoute:
    return RejectRoute(
        store=RejectStore(work / branches.reject.state_dir),
        ledger_path=work / branches.reject.ledger_path,
        config=branches.reject,
        now=NOW,
        default_ref="main",
    )


def _tip(work: Path, name: str = "novel") -> str:
    return _git(work, "rev-parse", f"refs/remotes/{REMOTE}/{name}").strip()


def _heads(work: Path) -> str:
    return _git(work, "ls-remote", "--heads", REMOTE)


def _pr(state: str = "CLOSED", *, oid: str, name: str = "novel", **extra: object) -> dict[str, object]:
    return {
        "number": PR,
        "state": state,
        "headRefName": name,
        "headRefOid": oid,
        "isCrossRepository": False,
        **extra,
    }


class FakeGh:
    """Answers ``gh pr list`` with ``payload`` (JSON-encoded unless already a str)."""

    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.calls: list[list[str]] = []

    def __call__(self, args: Sequence[str]) -> str:
        self.calls.append(list(args))
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload if isinstance(self.payload, str) else json.dumps(self.payload)


def _closed(work: Path) -> FakeGh:
    return FakeGh([_pr(oid=_tip(work))])


def _issue(
    work: Path, branches: BranchesConfig, route: RejectRoute, gh: FakeGh, *, at: float = NOW - HOUR
) -> Verdict:
    """Request a remote review, bind its dispatch and record a no-value verdict."""
    _subject, issued = remote_route.issue_remote_requests(
        work, branches, "main", "novel", route, gh
    )
    (item,) = issued
    request = item.request
    reviewer = _reviewer()
    route.store.write_dispatch(
        DispatchRecord(
            nonce=request.nonce,
            session_id=reviewer.session_id,
            tool_use_id="toolu_x",
            agent_id=reviewer.agent_id,
        )
    )
    verdict = Verdict(
        verdict_id=request.nonce,
        nonce=request.nonce,
        branch=request.branch,
        tip=request.tip,
        default_sha=request.default_sha,
        inventory=request.inventory,
        items=_items(request.inventory, DECISION_NO_VALUE),
        overall=DECISION_NO_VALUE,
        issued_at=at,
        reviewer=reviewer,
        remote=request.remote,
    )
    route.store.write_verdict(verdict)
    return verdict


class TestClosedPr:
    def test_a_closed_unmerged_pr_at_the_tip_is_accepted(self) -> None:
        assert remote_route.closed_pr(FakeGh([_pr(oid="a" * 40)]), "novel", "a" * 40) == PR

    def test_the_query_names_the_head_and_every_state(self) -> None:
        gh = FakeGh([_pr(oid="a" * 40)])
        remote_route.closed_pr(gh, "novel", "a" * 40)
        (call,) = gh.calls
        assert call[:2] == ["pr", "list"]
        assert call[call.index("--head") + 1] == "novel"
        assert call[call.index("--state") + 1] == "all"

    @pytest.mark.parametrize(
        ("payload", "needle"),
        [
            ([_pr("OPEN", oid="a" * 40)], "open"),
            ([_pr("MERGED", oid="a" * 40)], "merged"),
            ([_pr(oid="a" * 40), _pr("OPEN", oid="b" * 40, number=18)], "open"),
            ([_pr("WEIRD", oid="a" * 40)], "state"),
            ([], "no pull request"),
            ([_pr(oid="b" * 40)], "head commit"),
            ([_pr(oid="a" * 40, name="other")], "no pull request"),
            ([_pr(oid="a" * 40, isCrossRepository=True)], "no pull request"),
            ({"not": "a list"}, "could not be read"),
            ("not json", "could not be read"),
            ([["not", "an object"]], "could not be read"),
            ([_pr(oid="a" * 40, number="17")], "could not be read"),
            (GhError("gh: not logged in"), "could not be read"),
        ],
    )
    def test_anything_but_a_closed_pr_at_the_tip_is_refused(
        self, payload: object, needle: str
    ) -> None:
        with pytest.raises(RejectRefusedError, match=needle):
            remote_route.closed_pr(FakeGh(payload), "novel", "a" * 40)

    def test_a_full_page_is_unreadable(self) -> None:
        page = [_pr(oid="a" * 40, number=n) for n in range(remote_route.PR_PAGE_LIMIT)]
        with pytest.raises(RejectRefusedError, match="could not be read"):
            remote_route.closed_pr(FakeGh(page), "novel", "a" * 40)


class TestSubject:
    def test_a_remote_only_closed_branch_is_accepted(
        self, work: Path, branches: BranchesConfig
    ) -> None:
        subject = remote_route.check_subject(work, branches, "main", "novel", _closed(work))
        assert subject.tip == _tip(work)
        assert subject.pr_number == PR
        assert subject.default_ref == f"refs/remotes/{REMOTE}/main"

    def test_a_remote_held_branch_is_accepted(self, work: Path, branches: BranchesConfig) -> None:
        _git(work, "branch", "novel", f"{REMOTE}/novel")
        subject = remote_route.check_subject(work, branches, "main", "novel", _closed(work))
        assert subject.tip == _tip(work)

    def test_a_nonexistent_branch_is_refused(self, work: Path, branches: BranchesConfig) -> None:
        with pytest.raises(RejectRefusedError, match="does not exist"):
            remote_route.check_subject(work, branches, "main", "absent", _closed(work))

    def test_the_default_branch_is_refused(self, work: Path, branches: BranchesConfig) -> None:
        with pytest.raises(RejectRefusedError, match="default"):
            remote_route.check_subject(work, branches, "main", "main", _closed(work))

    def test_a_merged_branch_keeps_the_existing_route(
        self, work: Path, branches: BranchesConfig
    ) -> None:
        _git(work, "merge", "-q", "--no-ff", "-m", "merge", f"{REMOTE}/novel")
        _git(work, "push", "-q", REMOTE, "main")
        with pytest.raises(RejectRefusedError, match="delete-branch --remote-only"):
            remote_route.check_subject(work, branches, "main", "novel", _closed(work))

    def test_a_branch_checked_out_in_a_worktree_is_refused(
        self, work: Path, branches: BranchesConfig, tmp_path: Path
    ) -> None:
        _git(work, "worktree", "add", "-q", str(tmp_path / "wt"), "-b", "novel", f"{REMOTE}/novel")
        with pytest.raises(RejectRefusedError, match="checked out"):
            remote_route.check_subject(work, branches, "main", "novel", _closed(work))

    def test_a_stale_tracking_ref_is_refused(
        self, origin_and_clone: tuple[Path, Path], branches: BranchesConfig, tmp_path: Path
    ) -> None:
        origin, work = origin_and_clone
        tip = _tip(work)
        other = tmp_path / "other"
        run_git(tmp_path, "clone", "-q", str(origin), str(other))
        run_git(other, "config", "user.email", "t@example.invalid")
        run_git(other, "config", "user.name", "Tester")
        run_git(other, "checkout", "-q", "novel")
        run_git(other, "commit", "-q", "--allow-empty", "-m", "pushed after close")
        run_git(other, "push", "-q", "origin", "novel")
        with pytest.raises(RejectRefusedError, match="fetch"):
            remote_route.check_subject(work, branches, "main", "novel", FakeGh([_pr(oid=tip)]))

    def test_an_unknown_remote_default_is_refused(
        self, work: Path, branches: BranchesConfig
    ) -> None:
        with pytest.raises(RejectRefusedError, match="default"):
            remote_route.check_subject(
                work, BranchesConfig(), "trunk", "novel", _closed(work)
            )


class TestRequest:
    def test_a_request_is_stored_with_the_remote_scope_and_prompt(
        self, work: Path, branches: BranchesConfig, route: RejectRoute
    ) -> None:
        subject, issued = remote_route.issue_remote_requests(
            work, branches, "main", "novel", route, _closed(work)
        )
        (item,) = issued
        assert item.request.remote == REMOTE
        assert item.request.tip == subject.tip
        assert f"pull request #{PR} was closed" in item.prompt
        assert route.store.read_request(item.request.nonce) == item.request

    def test_an_open_pr_stores_nothing(
        self, work: Path, branches: BranchesConfig, route: RejectRoute
    ) -> None:
        with pytest.raises(RejectRefusedError):
            remote_route.issue_remote_requests(
                work, branches, "main", "novel", route, FakeGh([_pr("OPEN", oid=_tip(work))])
            )
        assert not (route.store.root / "requests").exists()


class TestDelete:
    def test_a_no_value_verdict_removes_the_remote_branch_with_a_bundle(
        self, work: Path, branches: BranchesConfig, route: RejectRoute
    ) -> None:
        tip = _tip(work)
        _issue(work, branches, route, _closed(work))
        removal = remote_route.delete_rejected_remote(
            work, branches, "main", "novel", route, _closed(work)
        )
        assert "refs/heads/novel" not in _heads(work)
        assert removal.tip == tip
        assert removal.bundle.is_file()
        assert removal.restore[1] == f"git push {REMOTE} {tip}:refs/heads/novel"
        (line,) = read_ledger(route.ledger_path)
        assert (line.branch, line.remote, line.tip) == ("novel", REMOTE, tip)

    def test_the_bundle_restores_the_branch(
        self, work: Path, branches: BranchesConfig, route: RejectRoute
    ) -> None:
        tip = _tip(work)
        _issue(work, branches, route, _closed(work))
        removal = remote_route.delete_rejected_remote(
            work, branches, "main", "novel", route, _closed(work)
        )
        fetch = ["fetch", str(removal.bundle), f"refs/remotes/{REMOTE}/novel:refs/remotes/{REMOTE}/novel"]
        _git(work, *fetch)
        _git(work, "push", "-q", REMOTE, f"{tip}:refs/heads/novel")
        assert tip in _heads(work)

    def test_no_verdict_is_refused(
        self, work: Path, branches: BranchesConfig, route: RejectRoute
    ) -> None:
        with pytest.raises(RejectRefusedError, match="no reviewer verdict"):
            remote_route.delete_rejected_remote(
                work, branches, "main", "novel", route, _closed(work)
            )
        assert "refs/heads/novel" in _heads(work)

    def test_a_local_scope_verdict_never_unlocks_the_remote_delete(
        self, work: Path, branches: BranchesConfig, route: RejectRoute
    ) -> None:
        verdict = _issue(work, branches, route, _closed(work))
        request = route.store.read_request(verdict.nonce)
        assert request is not None
        route.store.write_request(replace(request, remote=""))
        route.store.write_verdict(replace(verdict, remote=""))
        with pytest.raises(RejectRefusedError, match="no reviewer verdict"):
            remote_route.delete_rejected_remote(
                work, branches, "main", "novel", route, _closed(work)
            )
        assert "refs/heads/novel" in _heads(work)

    def test_a_verdict_for_another_branch_is_refused(
        self, work: Path, branches: BranchesConfig, route: RejectRoute
    ) -> None:
        verdict = _issue(work, branches, route, _closed(work))
        route.store.write_verdict(replace(verdict, branch="other"))
        with pytest.raises(RejectRefusedError, match="no reviewer verdict"):
            remote_route.delete_rejected_remote(
                work, branches, "main", "novel", route, _closed(work)
            )

    def test_an_expired_verdict_is_refused(
        self, work: Path, branches: BranchesConfig, route: RejectRoute
    ) -> None:
        lifetime = branches.reject.verdict_lifetime_hours * HOUR
        _issue(work, branches, route, _closed(work), at=NOW - lifetime - HOUR)
        with pytest.raises(RejectRefusedError, match="expired"):
            remote_route.delete_rejected_remote(
                work, branches, "main", "novel", route, _closed(work)
            )
        assert "refs/heads/novel" in _heads(work)

    def test_a_tip_moved_after_the_verdict_is_refused(
        self, origin_and_clone: tuple[Path, Path], branches: BranchesConfig, route: RejectRoute,
        tmp_path: Path,
    ) -> None:
        origin, work = origin_and_clone
        _issue(work, branches, route, _closed(work))
        other = tmp_path / "other"
        run_git(tmp_path, "clone", "-q", str(origin), str(other))
        run_git(other, "config", "user.email", "t@example.invalid")
        run_git(other, "config", "user.name", "Tester")
        run_git(other, "checkout", "-q", "novel")
        run_git(other, "commit", "-q", "--allow-empty", "-m", "more")
        run_git(other, "push", "-q", "origin", "novel")
        run_git(work, "fetch", "-q", REMOTE)
        moved = FakeGh([_pr(oid=_tip(work))])
        with pytest.raises(RejectRefusedError, match="tip"):
            remote_route.delete_rejected_remote(work, branches, "main", "novel", route, moved)
        assert _tip(work) in _heads(work)

    def test_a_pr_reopened_after_the_verdict_is_refused(
        self, work: Path, branches: BranchesConfig, route: RejectRoute
    ) -> None:
        _issue(work, branches, route, _closed(work))
        reopened = FakeGh([_pr("OPEN", oid=_tip(work))])
        with pytest.raises(RejectRefusedError, match="open"):
            remote_route.delete_rejected_remote(work, branches, "main", "novel", route, reopened)
        assert "refs/heads/novel" in _heads(work)

    def test_unreadable_pr_state_at_delete_time_is_refused(
        self, work: Path, branches: BranchesConfig, route: RejectRoute
    ) -> None:
        _issue(work, branches, route, _closed(work))
        with pytest.raises(RejectRefusedError, match="could not be read"):
            remote_route.delete_rejected_remote(
                work, branches, "main", "novel", route, FakeGh(GhError("offline"))
            )
        assert "refs/heads/novel" in _heads(work)

    def test_a_used_verdict_is_refused_the_second_time(
        self, work: Path, branches: BranchesConfig, route: RejectRoute
    ) -> None:
        tip = _tip(work)
        _issue(work, branches, route, _closed(work))
        remote_route.delete_rejected_remote(work, branches, "main", "novel", route, _closed(work))
        _git(work, "push", "-q", REMOTE, f"{tip}:refs/heads/novel")
        _git(work, "fetch", "-q", REMOTE)
        with pytest.raises((RejectRefusedError, RejectError)):
            remote_route.delete_rejected_remote(
                work, branches, "main", "novel", route, _closed(work)
            )
        assert "refs/heads/novel" in _heads(work)


def test_the_inventory_matches_the_local_route(work: Path) -> None:
    _git(work, "branch", "novel", f"{REMOTE}/novel")
    assert compute_inventory(work, "novel", "main") == compute_inventory(
        work, "novel", f"refs/remotes/{REMOTE}/main", remote=REMOTE
    )
