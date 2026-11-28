"""The no-value route for a REMOTE branch whose pull request closed unmerged (N763).

Every fixture is a throwaway clone of a local bare ``origin`` under ``tmp_path``, and
``gh`` is a fake runner returning canned JSON, so nothing here reaches a real remote.
"""

from __future__ import annotations

import json
import shlex
import subprocess
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

import pytest

from claude_code_hooks_daemon.config.models import BranchesConfig
from claude_code_hooks_daemon.core import branch_reject_remote as remote_route
from claude_code_hooks_daemon.core.branch_reject import (
    DECISION_NO_VALUE,
    DispatchRecord,
    LedgerLine,
    LedgerRefusal,
    RejectError,
    RejectRefusedError,
    RejectRequest,
    RejectRoute,
    RejectStore,
    RemovalApproval,
    Verdict,
    compute_inventory,
    new_id,
    read_ledger,
    read_ledger_entries,
    record_removal,
    unresolved_attempts,
)
from claude_code_hooks_daemon.utils.github_issue_validity import GhError
from tests.support.git_fixtures import git_setup_timeout, run_git
from tests.unit.core.test_branch_reject import HOUR, NOW, _items, _reviewer
from tests.unit.core.test_branch_reject import _git as _git_out

REMOTE = "origin"
PR = 17
GH_URL = "https://github.com/acme/widgets.git"
SLUG = "github.com/acme/widgets"


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
    # The remote's CONFIGURED url names a GitHub repository (what gh is pointed at);
    # insteadOf sends every git transfer to the local bare repository instead.
    run_git(work, "remote", "add", REMOTE, GH_URL)
    run_git(work, "config", f"url.{origin}.insteadOf", GH_URL)
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


def _pr(
    state: str = "CLOSED", *, oid: str, name: str = "novel", **extra: object
) -> dict[str, object]:
    return {
        "number": PR,
        "state": state,
        "headRefName": name,
        "headRefOid": oid,
        "isCrossRepository": False,
        **extra,
    }


class FakeGh:
    """Answers ``gh pr list --head`` with ``payload`` and ``--base`` with ``based``.

    Each is JSON-encoded unless already a str, and raised when an exception.
    """

    def __init__(self, payload: object, based: object = ()) -> None:
        self.payload = payload
        self.based: object = list(based) if isinstance(based, tuple) else based
        self.calls: list[list[str]] = []

    def __call__(self, args: Sequence[str]) -> str:
        self.calls.append(list(args))
        answer = self.based if "--base" in args else self.payload
        if isinstance(answer, Exception):
            raise answer
        return answer if isinstance(answer, str) else json.dumps(answer)


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
        gh = FakeGh([_pr(oid="a" * 40)])
        assert remote_route.closed_pr(gh, SLUG, "novel", "a" * 40) == PR

    def test_the_query_names_the_repository_the_head_and_every_state(self) -> None:
        gh = FakeGh([_pr(oid="a" * 40)])
        remote_route.closed_pr(gh, SLUG, "novel", "a" * 40)
        (call,) = gh.calls
        assert call[:2] == ["pr", "list"]
        assert call[call.index("-R") + 1] == SLUG
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
            remote_route.closed_pr(FakeGh(payload), SLUG, "novel", "a" * 40)

    def test_a_full_page_is_unreadable(self) -> None:
        page = [_pr(oid="a" * 40, number=n) for n in range(remote_route.PR_PAGE_LIMIT)]
        with pytest.raises(RejectRefusedError, match="could not be read"):
            remote_route.closed_pr(FakeGh(page), SLUG, "novel", "a" * 40)


class TestOpenBasePrs:
    """BLOCKER 1 of the N763 review: deleting a branch an open PR is BASED on closes it."""

    def test_no_open_pr_based_on_the_branch_passes(self) -> None:
        gh = FakeGh([], based=[])
        remote_route.refuse_open_base_prs(gh, SLUG, "novel")
        (call,) = gh.calls
        assert call[call.index("-R") + 1] == SLUG
        assert call[call.index("--base") + 1] == "novel"
        assert call[call.index("--state") + 1] == "open"

    @pytest.mark.parametrize(
        ("based", "needle"),
        [
            ([{"number": 99}], "#99"),
            ([{"number": 99}, {"number": 100}], "#99"),
            ("not json", "could not be read"),
            ({"number": 99}, "could not be read"),
            ([{"number": "99"}], "could not be read"),
            (GhError("offline"), "could not be read"),
        ],
    )
    def test_an_open_or_unreadable_based_pr_is_refused(self, based: object, needle: str) -> None:
        with pytest.raises(RejectRefusedError, match=needle):
            remote_route.refuse_open_base_prs(FakeGh([], based=based), SLUG, "novel")


class TestRepositorySlug:
    @pytest.mark.parametrize(
        ("url", "slug"),
        [
            ("https://github.com/acme/widgets.git", "github.com/acme/widgets"),
            ("https://github.com/acme/widgets", "github.com/acme/widgets"),
            ("https://token@github.com/acme/widgets.git", "github.com/acme/widgets"),
            ("git@github.com:acme/widgets.git", "github.com/acme/widgets"),
            ("ssh://git@github.com/acme/widgets.git", "github.com/acme/widgets"),
            ("ssh://git@ghe.example.com/acme/my.repo.git", "ghe.example.com/acme/my.repo"),
            ("https://github.com:443/acme/widgets.git", "github.com/acme/widgets"),
            ("ssh://git@github.com:22/acme/widgets.git", "github.com/acme/widgets"),
        ],
    )
    def test_a_github_style_url_names_its_repository(self, url: str, slug: str) -> None:
        assert remote_route.repository_slug(url) == slug

    @pytest.mark.parametrize(
        "url",
        [
            "/tmp/origin.git",
            "file:///tmp/origin.git",
            "https://github.com/acme",
            "https://github.com/acme/widgets/extra",
            "https://github.com/-acme/widgets",
            "https://github.com/acme/..",
            "git@github.com:acme/.git",
            "",
        ],
    )
    def test_anything_else_is_refused(self, url: str) -> None:
        with pytest.raises(RejectRefusedError, match="repository"):
            remote_route.repository_slug(url)

    @pytest.mark.parametrize(
        "url",
        [
            "https://ghe.corp:8443/a/w",
            "ssh://git@ghe.example.com:2222/acme/widgets.git",
            "http://ghe.corp:8080/a/w.git",
            "git://ghe.corp:9999/a/w.git",
            "https://ghe.corp:22/a/w",
        ],
    )
    def test_a_non_default_port_is_refused(self, url: str) -> None:
        """``gh -R`` takes no port, so dropping it would name another server's repo."""
        with pytest.raises(RejectRefusedError, match="repository"):
            remote_route.repository_slug(url)

    def test_the_route_reads_the_configured_remote_url(
        self, work: Path, branches: BranchesConfig
    ) -> None:
        gh = _closed(work)
        remote_route.check_subject(work, branches, "main", "novel", gh)
        assert gh.calls and all(call[call.index("-R") + 1] == SLUG for call in gh.calls)

    def test_a_remote_with_two_configured_urls_is_refused(
        self, work: Path, branches: BranchesConfig
    ) -> None:
        _git(work, "config", "--add", f"remote.{REMOTE}.url", "https://github.com/other/fork.git")
        with pytest.raises(RejectRefusedError, match="exactly one configured URL"):
            remote_route.check_subject(work, branches, "main", "novel", _closed(work))

    def test_a_remote_whose_url_names_no_repository_is_refused(
        self, origin_and_clone: tuple[Path, Path], branches: BranchesConfig
    ) -> None:
        origin, work = origin_and_clone
        _git(work, "remote", "set-url", REMOTE, str(origin))
        with pytest.raises(RejectRefusedError, match="repository"):
            remote_route.check_subject(work, branches, "main", "novel", _closed(work))


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

    def test_a_branch_checked_out_in_the_main_checkout_is_refused(
        self, work: Path, branches: BranchesConfig
    ) -> None:
        _git(work, "checkout", "-q", "-b", "novel", f"{REMOTE}/novel")
        with pytest.raises(RejectRefusedError, match="checked out"):
            remote_route.check_subject(work, branches, "main", "novel", _closed(work))

    @pytest.mark.parametrize(
        ("branches", "needle"),
        [
            (BranchesConfig(default="main", protected_names=["novel"]), "protected name"),
            (BranchesConfig(default="main", protected_names=["nov*"]), "protected name"),
            (BranchesConfig(default="main", exempt=["novel"]), "exempt"),
            (BranchesConfig(default="main", exempt=["n*l"]), "exempt"),
        ],
    )
    def test_a_protected_or_exempt_name_is_refused(
        self, work: Path, branches: BranchesConfig, needle: str
    ) -> None:
        with pytest.raises(RejectRefusedError, match=needle):
            remote_route.check_subject(work, branches, "main", "novel", _closed(work))

    @pytest.mark.parametrize("name", ["master", "develop", "trunk"])
    def test_the_default_protected_names_are_refused(
        self, origin_and_clone: tuple[Path, Path], branches: BranchesConfig, name: str
    ) -> None:
        _origin, work = origin_and_clone
        _git(work, "push", "-q", REMOTE, f"{REMOTE}/novel:refs/heads/{name}")
        _git(work, "fetch", "-q", REMOTE)
        gh = FakeGh([_pr(oid=_tip(work, name), name=name)])
        with pytest.raises(RejectRefusedError, match="protected name"):
            remote_route.check_subject(work, branches, "main", name, gh)

    def test_the_default_branch_is_refused_by_name(
        self, work: Path, branches: BranchesConfig
    ) -> None:
        gh = FakeGh([_pr(oid=_tip(work, "main"), name="main")])
        with pytest.raises(RejectRefusedError, match="is the default branch"):
            remote_route.check_subject(work, branches, "main", "main", gh)

    @pytest.mark.parametrize("name", ["refs/tags/novel", "nov el", "nov*", "-novel"])
    def test_a_tag_or_non_literal_name_is_refused(
        self, work: Path, branches: BranchesConfig, name: str
    ) -> None:
        with pytest.raises(RejectRefusedError, match="literal"):
            remote_route.check_subject(work, branches, "main", name, _closed(work))

    def test_an_open_pr_based_on_the_branch_is_refused(
        self, work: Path, branches: BranchesConfig
    ) -> None:
        gh = FakeGh([_pr(oid=_tip(work))], based=[{"number": 99}])
        with pytest.raises(RejectRefusedError, match="#99"):
            remote_route.check_subject(work, branches, "main", "novel", gh)

    def test_unreadable_based_prs_are_refused(self, work: Path, branches: BranchesConfig) -> None:
        gh = FakeGh([_pr(oid=_tip(work))], based=GhError("offline"))
        with pytest.raises(RejectRefusedError, match="could not be read"):
            remote_route.check_subject(work, branches, "main", "novel", gh)

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
            remote_route.check_subject(work, BranchesConfig(), "trunk", "novel", _closed(work))


def _unresolved_local_review(work: Path, route: RejectRoute) -> None:
    """A LOCAL-scope review of the same work, dispatched and never answered."""
    nonce = new_id()
    inventory = compute_inventory(work, "novel", f"refs/remotes/{REMOTE}/main", remote=REMOTE)
    route.store.write_request(
        RejectRequest(
            nonce=nonce,
            branch="novel",
            tip=_tip(work),
            default_sha=_tip(work, "main"),
            inventory=inventory,
            reviewers_required=1,
            prompt_sha256="b" * 64,
            created_at=NOW - 2 * HOUR,
        )
    )
    route.store.write_dispatch(
        DispatchRecord(nonce=nonce, session_id="s9", tool_use_id="toolu_y", agent_id="local9")
    )


class TestUnresolvedAttemptsByScope:
    def test_a_local_attempt_does_not_count_against_the_remote_scope(
        self, work: Path, route: RejectRoute
    ) -> None:
        _unresolved_local_review(work, route)
        inventory = compute_inventory(work, "novel", f"refs/remotes/{REMOTE}/main", remote=REMOTE)
        tip = _tip(work)
        assert unresolved_attempts(route.store, "novel", tip, inventory) == 1
        assert unresolved_attempts(route.store, "novel", tip, inventory, remote=REMOTE) == 0

    def test_a_local_attempt_raises_no_remote_reviewer_count(
        self, work: Path, branches: BranchesConfig, route: RejectRoute
    ) -> None:
        _unresolved_local_review(work, route)
        _subject, issued = remote_route.issue_remote_requests(
            work, branches, "main", "novel", route, _closed(work)
        )
        assert [item.request.reviewers_required for item in issued] == [1]

    def test_a_local_attempt_after_the_verdict_does_not_block_the_remote_delete(
        self, work: Path, branches: BranchesConfig, route: RejectRoute
    ) -> None:
        _issue(work, branches, route, _closed(work))
        _unresolved_local_review(work, route)
        remote_route.delete_rejected_remote(work, branches, "main", "novel", route, _closed(work))
        assert "refs/heads/novel" not in _heads(work)


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

    def test_an_open_pr_based_on_the_branch_stores_nothing(
        self, work: Path, branches: BranchesConfig, route: RejectRoute
    ) -> None:
        stacked = FakeGh([_pr(oid=_tip(work))], based=[{"number": 99}])
        with pytest.raises(RejectRefusedError, match="#99"):
            remote_route.issue_remote_requests(work, branches, "main", "novel", route, stacked)
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

    def test_the_printed_restore_lines_restore_into_a_clone_without_the_objects(
        self,
        origin_and_clone: tuple[Path, Path],
        branches: BranchesConfig,
        route: RejectRoute,
        tmp_path: Path,
    ) -> None:
        """The bundle alone carries the work: a fresh ``--no-local`` clone lacks the tip."""
        origin, work = origin_and_clone
        tip = _tip(work)
        _issue(work, branches, route, _closed(work))
        removal = remote_route.delete_rejected_remote(
            work, branches, "main", "novel", route, _closed(work)
        )
        fresh = tmp_path / "fresh"
        run_git(tmp_path, "clone", "-q", "--no-local", str(origin), str(fresh))
        missing = subprocess.run(
            ["git", "-C", str(fresh), "cat-file", "-e", f"{tip}^{{commit}}"],
            capture_output=True,
            check=False,
            timeout=git_setup_timeout(),
        )
        assert missing.returncode != 0, "the fresh clone must not already hold the removed tip"
        for command in removal.restore:
            argv = shlex.split(command)
            assert argv[0] == "git"
            _git(fresh, *argv[1:])
        assert f"{tip}\trefs/heads/novel" in _git(fresh, "ls-remote", "--heads", REMOTE)
        assert f"{tip}\trefs/heads/novel" in _heads(work)

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
        self,
        origin_and_clone: tuple[Path, Path],
        branches: BranchesConfig,
        route: RejectRoute,
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

    def test_an_open_pr_based_on_the_branch_at_delete_time_is_refused(
        self, work: Path, branches: BranchesConfig, route: RejectRoute
    ) -> None:
        _issue(work, branches, route, _closed(work))
        stacked = FakeGh([_pr(oid=_tip(work))], based=[{"number": 99}])
        with pytest.raises(RejectRefusedError, match="#99"):
            remote_route.delete_rejected_remote(work, branches, "main", "novel", route, stacked)
        assert "refs/heads/novel" in _heads(work)
        assert read_ledger_entries(route.ledger_path) == []

    def test_a_tip_pushed_between_the_checks_and_the_push_survives(
        self,
        origin_and_clone: tuple[Path, Path],
        branches: BranchesConfig,
        route: RejectRoute,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The lease is the only guard after the checks: a racing push must win."""
        origin, work = origin_and_clone
        judged = _tip(work)
        _issue(work, branches, route, _closed(work))
        other = tmp_path / "racer"
        run_git(tmp_path, "clone", "-q", str(origin), str(other))
        run_git(other, "config", "user.email", "t@example.invalid")
        run_git(other, "config", "user.name", "Tester")
        run_git(other, "checkout", "-q", "novel")
        run_git(other, "commit", "-q", "--allow-empty", "-m", "raced in")
        raced = _git(other, "rev-parse", "HEAD").strip()
        real = record_removal

        def push_then_record(
            repo: Path, approval: RemovalApproval, scoped: RejectRoute
        ) -> LedgerLine:
            run_git(other, "push", "-q", "origin", "novel")
            return real(repo, approval, scoped)

        monkeypatch.setattr(remote_route, "record_removal", push_then_record)
        with pytest.raises(RejectRefusedError, match="ledger records the refusal"):
            remote_route.delete_rejected_remote(
                work, branches, "main", "novel", route, _closed(work)
            )
        assert f"{raced}\trefs/heads/novel" in _heads(work)
        line, refusal = read_ledger_entries(route.ledger_path)
        assert isinstance(line, LedgerLine) and line.tip == judged
        assert isinstance(refusal, LedgerRefusal) and refusal.remote == REMOTE

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
