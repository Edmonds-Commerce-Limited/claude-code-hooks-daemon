"""Tests for the no-value removal route's pure module (Plan 00620 Task 2.1, DESIGN.md).

Every fixture builds a REAL git repository: the inventory, the bundle and the
citations are statements about git's own objects, and a mock would only assert
that the module called the functions we already believed in.

The module grants nothing by itself. It answers "is this verdict valid", "is
this bundle sound" and "how many reviewers does this request need"; the delete
wiring that acts on the answers is slice 2.
"""

from __future__ import annotations

import json
import shlex
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from claude_code_hooks_daemon.config.models import BranchRejectConfig
from claude_code_hooks_daemon.core.branch_reject import (
    DECISION_KEEP,
    DECISION_NO_VALUE,
    KIND_COMMIT,
    KIND_PATH,
    BundleRecord,
    DispatchRecord,
    Inventory,
    Item,
    KeepRecord,
    LedgerLine,
    RejectError,
    RejectRefusedError,
    RejectRequest,
    RejectStore,
    Reviewer,
    Verdict,
    admit_request,
    append_ledger,
    bundle_path_for,
    bundle_problems,
    compute_inventory,
    consumed_verdict_ids,
    is_keep_by_default,
    main_checkout,
    new_id,
    read_ledger,
    removals_in_window,
    restore_commands,
    reviewers_for_rate,
    sha256_of,
    verdict_problems,
    verdict_set_problems,
    write_bundle,
)

_ENV = {
    "GIT_AUTHOR_NAME": "Test Author",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "Test Author",
    "GIT_COMMITTER_EMAIL": "test@example.com",
    "PATH": "/usr/bin:/bin",
}

NOW = 1_800_000_000.0
HOUR = 3600.0
DAY = 86_400.0
OPUS = "claude-opus-5-5"


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        env={**_ENV, "HOME": str(repo)},
    )
    return result.stdout


def _commit(repo: Path, filename: str, content: str, message: str) -> str:
    path = repo / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    _git(repo, "add", filename)
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD").strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """``main`` with one file; ``feat`` adds one unique file in one commit; HEAD on main."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _commit(root, "README.md", "base\n", "base")
    _git(root, "switch", "-q", "-c", "feat")
    _commit(root, "src/feature.py", "x = 1\n", "add feature")
    _git(root, "switch", "-q", "main")
    _git(root, "config", "branch.feat.hooksDaemonCreator", "s1:creator")
    _git(root, "config", "--add", "branch.feat.hooksDaemonTouchedBy", "s1:toucher")
    return root


@pytest.fixture
def config() -> BranchRejectConfig:
    return BranchRejectConfig()


@pytest.fixture
def store(repo: Path, config: BranchRejectConfig) -> RejectStore:
    return RejectStore(repo / config.state_dir)


def _tip(repo: Path, branch: str = "feat") -> str:
    return _git(repo, "rev-parse", f"refs/heads/{branch}").strip()


def _main_sha(repo: Path) -> str:
    return _git(repo, "rev-parse", "refs/heads/main").strip()


def _reviewer(
    agent_id: str = "reviewer1",
    *,
    models: tuple[str, ...] = (OPUS,),
    downgraded: bool = False,
    fork: bool = False,
    user_turns: int = 1,
    reply_sha256: str = "a" * 64,
) -> Reviewer:
    return Reviewer(
        session_id="s1",
        agent_id=agent_id,
        models=models,
        downgraded=downgraded,
        fork=fork,
        user_turns=user_turns,
        reply_sha256=reply_sha256,
    )


def _items(inventory: Inventory, decision: str = DECISION_NO_VALUE) -> tuple[Item, ...]:
    commits = tuple(
        Item(kind=KIND_COMMIT, ref=sha, decision=decision, reason="scratch", superseded_by=())
        for sha in inventory.commits
    )
    paths = tuple(
        Item(kind=KIND_PATH, ref=path, decision=decision, reason="scratch", superseded_by=())
        for path in inventory.paths
    )
    return commits + paths


def _issue(
    repo: Path,
    store: RejectStore,
    *,
    branch: str = "feat",
    reviewer: Reviewer | None = None,
    decision: str = DECISION_NO_VALUE,
    issued_at: float = NOW - HOUR,
) -> Verdict:
    """A request, its dispatch record and a verdict, as slice 2's writers would leave them."""
    reviewer = reviewer or _reviewer()
    inventory = compute_inventory(repo, branch, "main")
    nonce = new_id()
    request = RejectRequest(
        nonce=nonce,
        branch=branch,
        tip=_tip(repo, branch),
        default_sha=_main_sha(repo),
        inventory=inventory,
        reviewers_required=1,
        prompt_sha256="b" * 64,
        created_at=issued_at - 60,
    )
    store.write_request(request)
    store.write_dispatch(
        DispatchRecord(
            nonce=nonce,
            session_id=reviewer.session_id,
            tool_use_id="toolu_x",
            agent_id=reviewer.agent_id,
        )
    )
    verdict = Verdict(
        verdict_id=new_id(),
        nonce=nonce,
        branch=branch,
        tip=request.tip,
        default_sha=request.default_sha,
        inventory=inventory,
        items=_items(inventory, decision),
        overall=decision,
        issued_at=issued_at,
        reviewer=reviewer,
    )
    store.write_verdict(verdict)
    return verdict


def _problems(
    repo: Path,
    store: RejectStore,
    verdict: Verdict,
    config: BranchRejectConfig,
    *,
    consumed: frozenset[str] = frozenset(),
    now: float = NOW,
) -> list[str]:
    return verdict_problems(
        verdict,
        repo=repo,
        store=store,
        default_ref="main",
        now=now,
        consumed=consumed,
        config=config,
    )


def _ledger_line(branch: str = "feat", removed_at: float = NOW) -> LedgerLine:
    return LedgerLine(
        branch=branch,
        tip="1" * 40,
        default_sha="2" * 40,
        verdict_ids=(new_id(),),
        reviewer_agent_ids=("r1",),
        reviewer_models=(OPUS,),
        reply_sha256s=("a" * 64,),
        bundle_path="/m/x.bundle",
        bundle_sha256="c" * 64,
        restore_commands=("git branch feat " + "1" * 40,),
        removed_at=removed_at,
    )


class TestIds:
    def test_new_id_is_32_lower_hex_and_unique(self) -> None:
        first, second = new_id(), new_id()
        assert len(first) == 32
        assert first == first.lower()
        int(first, 16)
        assert first != second


class TestInventory:
    def test_lists_the_unique_commit_and_content_unique_path(self, repo: Path) -> None:
        inventory = compute_inventory(repo, "feat", "main")
        assert inventory.commits == (_tip(repo),)
        assert inventory.paths == ("src/feature.py",)

    def test_a_cherry_picked_commit_is_not_listed(self, repo: Path) -> None:
        _git(repo, "switch", "-q", "feat")
        _commit(repo, "notes.txt", "n\n", "notes")
        _git(repo, "switch", "-q", "main")
        _git(repo, "cherry-pick", "feat")
        inventory = compute_inventory(repo, "feat", "main")
        assert len(inventory.commits) == 1
        assert inventory.paths == ("src/feature.py",)

    def test_a_merge_commit_is_always_listed(self, repo: Path) -> None:
        _git(repo, "switch", "-q", "-c", "side", "main")
        _commit(repo, "side.txt", "s\n", "side")
        _git(repo, "switch", "-q", "feat")
        _git(repo, "merge", "-q", "--no-ff", "-m", "merge side", "side")
        merge = _tip(repo)
        _git(repo, "switch", "-q", "main")
        _git(repo, "merge", "-q", "--ff-only", "side")
        inventory = compute_inventory(repo, "feat", "main")
        assert merge in inventory.commits

    def test_results_are_sorted(self, repo: Path) -> None:
        _git(repo, "switch", "-q", "feat")
        _commit(repo, "a.py", "a\n", "a")
        _git(repo, "switch", "-q", "main")
        inventory = compute_inventory(repo, "feat", "main")
        assert list(inventory.commits) == sorted(inventory.commits)
        assert inventory.paths == ("a.py", "src/feature.py")

    def test_a_missing_branch_raises(self, repo: Path) -> None:
        with pytest.raises(RejectError):
            compute_inventory(repo, "nope", "main")

    def test_a_missing_default_raises(self, repo: Path) -> None:
        with pytest.raises(RejectError):
            compute_inventory(repo, "feat", "trunk")

    def test_round_trips_through_a_dict(self, repo: Path) -> None:
        inventory = compute_inventory(repo, "feat", "main")
        assert Inventory.from_dict(inventory.to_dict()) == inventory

    def test_a_malformed_dict_raises(self) -> None:
        with pytest.raises(RejectError):
            Inventory.from_dict({"commits": "abc", "paths": []})


class TestKeepByDefault:
    @pytest.mark.parametrize(
        "path",
        [
            "tests/unit/test_x.py",
            "src/test_y.py",
            "pkg/y_test.go",
            "web/a.test.ts",
            "CLAUDE/Plan/00001-x/PLAN.md",
            "CLAUDE/Plan/00001-x/JOURNAL/2026-01-01/x.txt",
            "docs/guide.txt",
            "README.md",
            "notes.rst",
            ".claude/hooks-daemon.yaml",
            "pyproject.toml",
            "package.json",
            "setup.cfg",
            "tox.ini",
        ],
    )
    def test_kept_classes(self, path: str) -> None:
        assert is_keep_by_default(path) is True

    @pytest.mark.parametrize("path", ["src/feature.py", "scripts/run.sh", "lib/x.go"])
    def test_ordinary_code_is_not(self, path: str) -> None:
        assert is_keep_by_default(path) is False


class TestStore:
    def test_round_trips_every_record(self, repo: Path, store: RejectStore) -> None:
        verdict = _issue(repo, store)
        assert store.read_verdict(verdict.verdict_id) == verdict
        request = store.read_request(verdict.nonce)
        assert request is not None
        assert request.tip == verdict.tip
        dispatch = store.read_dispatch(verdict.nonce)
        assert dispatch is not None
        assert dispatch.agent_id == "reviewer1"
        assert store.verdicts_for("feat", verdict.tip) == [verdict]

    def test_absent_records_are_none(self, store: RejectStore) -> None:
        assert store.read_request(new_id()) is None
        assert store.read_dispatch(new_id()) is None
        assert store.read_verdict(new_id()) is None
        assert store.verdicts_for("feat", "0" * 40) == []
        assert store.keeps() == []

    def test_a_malformed_record_raises(self, repo: Path, store: RejectStore) -> None:
        verdict = _issue(repo, store)
        path = store.root / "verdicts" / f"{verdict.verdict_id}.json"
        path.write_text("{not json", encoding="utf-8")
        with pytest.raises(RejectError):
            store.read_verdict(verdict.verdict_id)
        with pytest.raises(RejectError):
            store.verdicts_for("feat", verdict.tip)

    def test_a_record_missing_a_field_raises(self, repo: Path, store: RejectStore) -> None:
        verdict = _issue(repo, store)
        path = store.root / "verdicts" / f"{verdict.verdict_id}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        del data["reviewer"]
        path.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(RejectError):
            store.read_verdict(verdict.verdict_id)

    def test_a_file_name_that_is_not_an_id_is_never_opened(
        self, repo: Path, store: RejectStore
    ) -> None:
        verdict = _issue(repo, store)
        (store.root / "verdicts" / "hand-written.json").write_text("{bad", encoding="utf-8")
        assert store.verdicts_for("feat", verdict.tip) == [verdict]

    @pytest.mark.parametrize("bad", ["../escape", "ABC", "", "a" * 31])
    def test_a_bad_id_is_refused(self, store: RejectStore, bad: str) -> None:
        with pytest.raises(RejectError):
            store.read_request(bad)

    def test_keeps_round_trip(self, store: RejectStore) -> None:
        keep = KeepRecord(
            verdict_id=new_id(),
            branch="feat",
            tip="1" * 40,
            commits=("1" * 40,),
            reasons=("tests are not superseded",),
            recorded_at=NOW,
        )
        store.write_keep(keep)
        assert store.keeps() == [keep]


class TestVerdictValid:
    def test_a_fresh_chained_verdict_has_no_problems(
        self, repo: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        verdict = _issue(repo, store)
        assert _problems(repo, store, verdict, config) == []

    def test_round_trips_through_a_dict(self, repo: Path, store: RejectStore) -> None:
        verdict = _issue(repo, store)
        assert Verdict.from_dict(verdict.to_dict()) == verdict


class TestVerdictChain:
    """A verdict counts only through a request and a dispatch record (DESIGN section 3)."""

    def test_no_request_is_a_problem(
        self, repo: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        verdict = _issue(repo, store)
        (store.root / "requests" / f"{verdict.nonce}.json").unlink()
        assert any("request" in p for p in _problems(repo, store, verdict, config))

    def test_no_dispatch_record_is_a_problem(
        self, repo: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        verdict = _issue(repo, store)
        (store.root / "dispatches" / f"{verdict.nonce}.json").unlink()
        assert any("dispatch" in p for p in _problems(repo, store, verdict, config))

    def test_a_dispatch_bound_to_another_agent_is_a_problem(
        self, repo: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        verdict = _issue(repo, store)
        store.write_dispatch(
            DispatchRecord(nonce=verdict.nonce, session_id="s1", tool_use_id="t", agent_id="other")
        )
        assert any("dispatch" in p for p in _problems(repo, store, verdict, config))

    def test_a_verdict_disagreeing_with_its_request_is_a_problem(
        self, repo: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        verdict = _issue(repo, store)
        forged = replace(verdict, default_sha="0" * 40)
        assert any("request" in p for p in _problems(repo, store, forged, config))


class TestVerdictTipAndInventory:
    def test_a_moved_tip_is_a_problem(
        self, repo: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        verdict = _issue(repo, store)
        _git(repo, "switch", "-q", "feat")
        _commit(repo, "src/more.py", "y\n", "more")
        _git(repo, "switch", "-q", "main")
        assert any("tip" in p for p in _problems(repo, store, verdict, config))

    def test_a_deleted_branch_is_a_problem(
        self, repo: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        verdict = _issue(repo, store)
        _git(repo, "branch", "-D", "feat")
        assert _problems(repo, store, verdict, config)

    def test_an_item_missing_from_the_inventory_is_a_problem(
        self, repo: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        verdict = _issue(repo, store)
        short = replace(verdict, items=verdict.items[:-1])
        assert any("inventory" in p for p in _problems(repo, store, short, config))

    def test_an_extra_item_is_a_problem(
        self, repo: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        verdict = _issue(repo, store)
        extra = Item(KIND_PATH, "src/ghost.py", DECISION_NO_VALUE, "x", ())
        padded = replace(verdict, items=(*verdict.items, extra))
        assert any("inventory" in p for p in _problems(repo, store, padded, config))

    def test_a_duplicate_item_is_a_problem(
        self, repo: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        verdict = _issue(repo, store)
        doubled = replace(verdict, items=(*verdict.items, verdict.items[0]))
        assert any("duplicate" in p for p in _problems(repo, store, doubled, config))

    def test_an_inventory_that_no_longer_matches_git_is_a_problem(
        self, repo: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        verdict = _issue(repo, store)
        stale = Inventory(commits=verdict.inventory.commits, paths=())
        request = store.read_request(verdict.nonce)
        assert request is not None
        store.write_request(replace(request, inventory=stale))
        commit_items = tuple(i for i in verdict.items if i.kind == KIND_COMMIT)
        mismatched = replace(verdict, inventory=stale, items=commit_items)
        assert any("inventory" in p for p in _problems(repo, store, mismatched, config))


class TestVerdictJudgement:
    def test_a_keep_item_under_an_overall_no_value_is_a_problem(
        self, repo: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        verdict = _issue(repo, store)
        first = replace(verdict.items[0], decision=DECISION_KEEP)
        mixed = replace(verdict, items=(first, *verdict.items[1:]))
        assert any("overall" in p for p in _problems(repo, store, mixed, config))

    def test_an_overall_keep_is_reported_as_not_a_removal(
        self, repo: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        verdict = _issue(repo, store, decision=DECISION_KEEP)
        assert any("keep" in p for p in _problems(repo, store, verdict, config))

    def test_an_empty_reason_is_a_problem(
        self, repo: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        verdict = _issue(repo, store)
        blank = replace(verdict.items[0], reason="  ")
        reasonless = replace(verdict, items=(blank, *verdict.items[1:]))
        assert any("reason" in p for p in _problems(repo, store, reasonless, config))

    def test_an_unknown_decision_is_a_problem(
        self, repo: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        verdict = _issue(repo, store)
        odd = replace(verdict.items[0], decision="maybe")
        assert _problems(repo, store, replace(verdict, items=(odd, *verdict.items[1:])), config)


class TestKeepByDefaultCitations:
    @pytest.fixture
    def doc_repo(self, repo: Path) -> Path:
        _git(repo, "switch", "-q", "feat")
        _commit(repo, "docs/guide.md", "draft\n", "doc draft")
        _git(repo, "switch", "-q", "main")
        return repo

    def _cited(self, verdict: Verdict, citation: tuple[str, ...]) -> Verdict:
        items = tuple(
            replace(i, superseded_by=citation) if i.ref == "docs/guide.md" else i
            for i in verdict.items
        )
        return replace(verdict, items=items)

    def test_a_doc_judged_no_value_without_a_citation_is_a_problem(
        self, doc_repo: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        verdict = _issue(doc_repo, store)
        assert any("docs/guide.md" in p for p in _problems(doc_repo, store, verdict, config))

    def test_a_resolving_path_citation_clears_it(
        self, doc_repo: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        verdict = self._cited(_issue(doc_repo, store), ("path:README.md",))
        assert _problems(doc_repo, store, verdict, config) == []

    def test_a_resolving_commit_citation_clears_it(
        self, doc_repo: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        cited = f"commit:{_main_sha(doc_repo)}"
        verdict = self._cited(_issue(doc_repo, store), (cited,))
        assert _problems(doc_repo, store, verdict, config) == []

    @pytest.mark.parametrize(
        "citation", ["path:docs/absent.md", "nonsense", "path:", "commit:zzz", "path:-p"]
    )
    def test_an_unresolved_citation_is_a_problem(
        self, doc_repo: Path, store: RejectStore, config: BranchRejectConfig, citation: str
    ) -> None:
        verdict = self._cited(_issue(doc_repo, store), (citation,))
        assert any("citation" in p for p in _problems(doc_repo, store, verdict, config))

    def test_a_commit_citation_off_the_default_is_a_problem(
        self, doc_repo: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        verdict = self._cited(_issue(doc_repo, store), (f"commit:{_tip(doc_repo)}",))
        assert any("citation" in p for p in _problems(doc_repo, store, verdict, config))


class TestExpiryAndSingleUse:
    def test_an_expired_verdict_is_a_problem(
        self, repo: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        verdict = _issue(repo, store, issued_at=NOW - 25 * HOUR)
        assert any("expired" in p for p in _problems(repo, store, verdict, config))

    def test_a_verdict_from_the_future_is_a_problem(
        self, repo: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        verdict = _issue(repo, store, issued_at=NOW + HOUR)
        assert any("future" in p for p in _problems(repo, store, verdict, config))

    def test_the_lifetime_is_read_from_config(self, repo: Path, store: RejectStore) -> None:
        verdict = _issue(repo, store, issued_at=NOW - 2 * HOUR)
        short = BranchRejectConfig(verdict_lifetime_hours=1)
        assert any("expired" in p for p in _problems(repo, store, verdict, short))

    def test_a_consumed_verdict_is_a_problem(
        self, repo: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        verdict = _issue(repo, store)
        consumed = frozenset({verdict.verdict_id})
        problems = _problems(repo, store, verdict, config, consumed=consumed)
        assert any("already used" in p for p in problems)


class TestReviewer:
    @pytest.mark.parametrize(
        ("reviewer", "word"),
        [
            (_reviewer(models=("claude-sonnet-5-5",)), "Opus"),
            (_reviewer(models=(OPUS, "claude-haiku-4-5")), "Opus"),
            (_reviewer(models=()), "model"),
            (_reviewer(models=("mystery-model",)), "Opus"),
            (_reviewer(downgraded=True), "downgrade"),
            (_reviewer(fork=True), "fork"),
            (_reviewer(user_turns=2), "resumed"),
            (_reviewer(user_turns=0), "resumed"),
            (_reviewer(reply_sha256="short"), "reply"),
        ],
    )
    def test_an_unfit_reviewer_is_a_problem(
        self,
        repo: Path,
        store: RejectStore,
        config: BranchRejectConfig,
        reviewer: Reviewer,
        word: str,
    ) -> None:
        verdict = _issue(repo, store, reviewer=reviewer)
        assert any(word in p for p in _problems(repo, store, verdict, config))

    def test_fable_is_above_opus(
        self, repo: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        verdict = _issue(repo, store, reviewer=_reviewer(models=("claude-fable-5-2",)))
        assert _problems(repo, store, verdict, config) == []

    @pytest.mark.parametrize("agent_id", ["creator", "toucher"])
    def test_a_creator_or_toucher_reviewer_is_a_problem(
        self, repo: Path, store: RejectStore, config: BranchRejectConfig, agent_id: str
    ) -> None:
        verdict = _issue(repo, store, reviewer=_reviewer(agent_id=agent_id))
        assert any("creator or touched" in p for p in _problems(repo, store, verdict, config))


class TestVerdictSet:
    def test_one_verdict_meets_one_required(self, repo: Path, store: RejectStore) -> None:
        assert verdict_set_problems([_issue(repo, store)], required=1) == []

    def test_one_verdict_short_of_two_required(self, repo: Path, store: RejectStore) -> None:
        assert verdict_set_problems([_issue(repo, store)], required=2)

    def test_two_from_the_same_agent_count_once(self, repo: Path, store: RejectStore) -> None:
        first = _issue(repo, store)
        second = _issue(repo, store)
        assert any("distinct" in p for p in verdict_set_problems([first, second], required=2))

    def test_two_distinct_agreeing_reviewers_meet_two(self, repo: Path, store: RejectStore) -> None:
        first = _issue(repo, store)
        second = _issue(repo, store, reviewer=_reviewer(agent_id="reviewer2"))
        assert verdict_set_problems([first, second], required=2) == []

    def test_disagreement_is_keep(self, repo: Path, store: RejectStore) -> None:
        first = _issue(repo, store)
        second = _issue(repo, store, reviewer=_reviewer(agent_id="r2"), decision=DECISION_KEEP)
        assert any("keep" in p for p in verdict_set_problems([first, second], required=2))

    def test_no_verdicts_is_a_problem(self) -> None:
        assert verdict_set_problems([], required=1)


class TestRate:
    @pytest.mark.parametrize(("count", "required"), [(0, 1), (2, 1), (3, 2), (9, 2), (10, None)])
    def test_thresholds(self, config: BranchRejectConfig, count: int, required: int | None) -> None:
        assert reviewers_for_rate(count, config) == required

    def test_only_the_window_counts(self, config: BranchRejectConfig) -> None:
        lines = [
            _ledger_line(removed_at=NOW - 8 * DAY),
            _ledger_line(removed_at=NOW - 6 * DAY),
            _ledger_line(removed_at=NOW - 1),
        ]
        assert removals_in_window(lines, now=NOW, config=config) == 2

    def test_consumed_ids_come_from_every_line(self) -> None:
        first, second = _ledger_line(), _ledger_line()
        assert consumed_verdict_ids([first, second]) == frozenset(
            (*first.verdict_ids, *second.verdict_ids)
        )


class TestAdmission:
    def _keep(self, *, branch: str = "feat", tip: str, commits: tuple[str, ...]) -> KeepRecord:
        return KeepRecord(
            verdict_id=new_id(),
            branch=branch,
            tip=tip,
            commits=commits,
            reasons=("the tests are not superseded",),
            recorded_at=NOW - DAY,
        )

    def test_a_clean_request_needs_one(self, repo: Path, config: BranchRejectConfig) -> None:
        inventory = compute_inventory(repo, "feat", "main")
        assert admit_request("feat", _tip(repo), inventory, [], 0, config) == 1

    def test_a_keep_on_this_tip_is_final(self, repo: Path, config: BranchRejectConfig) -> None:
        inventory = compute_inventory(repo, "feat", "main")
        keep = self._keep(tip=_tip(repo), commits=inventory.commits)
        with pytest.raises(RejectRefusedError, match="final"):
            admit_request("feat", _tip(repo), inventory, [keep], 0, config)

    def test_one_earlier_keep_on_another_tip_needs_two(
        self, repo: Path, config: BranchRejectConfig
    ) -> None:
        inventory = compute_inventory(repo, "feat", "main")
        keep = self._keep(tip="9" * 40, commits=inventory.commits)
        assert admit_request("feat", _tip(repo), inventory, [keep], 0, config) == 2

    def test_a_rename_earns_no_fresh_start(self, repo: Path, config: BranchRejectConfig) -> None:
        inventory = compute_inventory(repo, "feat", "main")
        keep = self._keep(branch="old-name", tip="9" * 40, commits=inventory.commits)
        assert admit_request("feat", _tip(repo), inventory, [keep], 0, config) == 2

    def test_a_rename_at_the_same_tip_is_still_final(
        self, repo: Path, config: BranchRejectConfig
    ) -> None:
        inventory = compute_inventory(repo, "feat", "main")
        keep = self._keep(branch="old-name", tip=_tip(repo), commits=inventory.commits)
        with pytest.raises(RejectRefusedError, match="final"):
            admit_request("feat", _tip(repo), inventory, [keep], 0, config)

    def test_two_earlier_keeps_close_the_route(
        self, repo: Path, config: BranchRejectConfig
    ) -> None:
        inventory = compute_inventory(repo, "feat", "main")
        keeps = [self._keep(tip="8" * 40, commits=()), self._keep(tip="9" * 40, commits=())]
        with pytest.raises(RejectRefusedError, match="closed"):
            admit_request("feat", _tip(repo), inventory, keeps, 0, config)

    def test_an_unrelated_keep_does_not_count(self, repo: Path, config: BranchRejectConfig) -> None:
        inventory = compute_inventory(repo, "feat", "main")
        keep = self._keep(branch="other", tip="9" * 40, commits=("7" * 40,))
        assert admit_request("feat", _tip(repo), inventory, [keep], 0, config) == 1

    def test_the_rate_raises_the_requirement(self, repo: Path, config: BranchRejectConfig) -> None:
        inventory = compute_inventory(repo, "feat", "main")
        assert admit_request("feat", _tip(repo), inventory, [], 3, config) == 2

    def test_the_rate_refuses(self, repo: Path, config: BranchRejectConfig) -> None:
        inventory = compute_inventory(repo, "feat", "main")
        with pytest.raises(RejectRefusedError, match="rate"):
            admit_request("feat", _tip(repo), inventory, [], 10, config)


class TestMainCheckout:
    def test_the_main_checkout_is_itself(self, repo: Path) -> None:
        assert main_checkout(repo) == repo.resolve()

    def test_a_linked_worktree_resolves_to_the_main_checkout(
        self, repo: Path, tmp_path: Path
    ) -> None:
        linked = tmp_path / "linked"
        _git(repo, "worktree", "add", "-q", str(linked), "-b", "wt")
        assert main_checkout(linked) == repo.resolve()

    def test_a_bare_repository_raises(self, tmp_path: Path) -> None:
        bare = tmp_path / "bare.git"
        subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
        with pytest.raises(RejectError):
            main_checkout(bare)

    def test_not_a_repository_raises(self, tmp_path: Path) -> None:
        plain = tmp_path / "plain"
        plain.mkdir()
        with pytest.raises(RejectError):
            main_checkout(plain)


class TestBundle:
    def test_the_bundle_lands_in_the_main_checkout(
        self, repo: Path, config: BranchRejectConfig
    ) -> None:
        record = write_bundle(repo, "feat", _tip(repo), _main_sha(repo), config)
        expected = repo.resolve() / config.bundle_dir / f"feat-{_tip(repo)[:12]}.bundle"
        assert record.path == expected
        assert record.tip == _tip(repo)
        assert bundle_problems(repo, record, "feat") == []

    def test_a_run_from_a_linked_worktree_writes_into_the_main_checkout(
        self, repo: Path, tmp_path: Path, config: BranchRejectConfig
    ) -> None:
        linked = tmp_path / "linked"
        _git(repo, "worktree", "add", "-q", str(linked), "-b", "wt")
        record = write_bundle(linked, "feat", _tip(repo), _main_sha(repo), config)
        assert record.path.is_relative_to(repo.resolve() / config.bundle_dir)
        assert not (linked / config.bundle_dir).exists()
        assert bundle_problems(linked, record, "feat") == []

    def test_the_bundle_restores_the_branch(self, repo: Path, config: BranchRejectConfig) -> None:
        tip = _tip(repo)
        record = write_bundle(repo, "feat", tip, _main_sha(repo), config)
        _git(repo, "branch", "-D", "feat")
        fetch, _ = restore_commands("feat", tip, record.path)
        argv = shlex.split(fetch)
        assert argv[:2] == ["git", "fetch"]
        _git(repo, *argv[1:])
        assert _tip(repo) == tip

    def test_the_slug_replaces_unsafe_characters(
        self, repo: Path, config: BranchRejectConfig
    ) -> None:
        path = bundle_path_for(repo, config, "feat/a b", "f" * 40)
        assert path.name == f"feat-a-b-{'f' * 12}.bundle"

    def test_an_existing_bundle_is_never_overwritten(
        self, repo: Path, config: BranchRejectConfig
    ) -> None:
        first = write_bundle(repo, "feat", _tip(repo), _main_sha(repo), config)
        before = first.path.read_bytes()
        second = write_bundle(repo, "feat", _tip(repo), _main_sha(repo), config)
        assert second == first
        assert first.path.read_bytes() == before

    def test_an_existing_file_that_is_not_a_sound_bundle_refuses(
        self, repo: Path, config: BranchRejectConfig
    ) -> None:
        path = bundle_path_for(repo, config, "feat", _tip(repo))
        path.parent.mkdir(parents=True)
        path.write_bytes(b"not a bundle")
        with pytest.raises(RejectError):
            write_bundle(repo, "feat", _tip(repo), _main_sha(repo), config)
        assert path.read_bytes() == b"not a bundle"

    def test_an_unwritable_bundle_dir_raises(self, repo: Path, config: BranchRejectConfig) -> None:
        blocker = repo / config.bundle_dir
        blocker.parent.mkdir(parents=True, exist_ok=True)
        blocker.write_text("a file where the directory should be")
        with pytest.raises(RejectError):
            write_bundle(repo, "feat", _tip(repo), _main_sha(repo), config)

    def test_a_tip_that_is_not_the_branch_raises(
        self, repo: Path, config: BranchRejectConfig
    ) -> None:
        with pytest.raises(RejectError):
            write_bundle(repo, "feat", _main_sha(repo), _main_sha(repo), config)


class TestBundleProblems:
    @pytest.fixture
    def record(self, repo: Path, config: BranchRejectConfig) -> BundleRecord:
        return write_bundle(repo, "feat", _tip(repo), _main_sha(repo), config)

    def test_a_missing_file(self, repo: Path, record: BundleRecord) -> None:
        record.path.unlink()
        assert any("missing" in p for p in bundle_problems(repo, record, "feat"))

    def test_a_sha256_mismatch(self, repo: Path, record: BundleRecord) -> None:
        wrong = replace(record, sha256="0" * 64)
        assert any("sha256" in p for p in bundle_problems(repo, wrong, "feat"))

    def test_a_failed_verify(self, repo: Path, record: BundleRecord) -> None:
        record.path.write_bytes(b"# v2 git bundle\ngarbage\n")
        rehashed = replace(record, sha256=sha256_of(record.path))
        assert any("verify" in p for p in bundle_problems(repo, rehashed, "feat"))

    def test_the_tip_absent_from_the_bundle(self, repo: Path, record: BundleRecord) -> None:
        other = replace(record, tip=_main_sha(repo))
        assert any("does not list" in p for p in bundle_problems(repo, other, "feat"))

    def test_the_tip_under_another_branch_name(self, repo: Path, record: BundleRecord) -> None:
        assert any("does not list" in p for p in bundle_problems(repo, record, "other"))


class TestRestoreCommands:
    def test_both_lines(self) -> None:
        fetch, branch = restore_commands("feat", "1" * 40, Path("/m/untracked/b.bundle"))
        assert fetch == "git fetch /m/untracked/b.bundle refs/heads/feat:refs/heads/feat"
        assert branch == f"git branch feat {'1' * 40}"

    def test_a_path_with_a_space_is_quoted(self) -> None:
        fetch, _ = restore_commands("feat", "1" * 40, Path("/m n/b.bundle"))
        assert fetch.startswith("git fetch '/m n/b.bundle' ")


class TestLedger:
    def test_a_missing_ledger_is_empty(self, tmp_path: Path) -> None:
        assert read_ledger(tmp_path / ".claude" / "branch-removals.jsonl") == []

    def test_append_then_read(self, tmp_path: Path) -> None:
        path = tmp_path / ".claude" / "branch-removals.jsonl"
        first, second = _ledger_line(), _ledger_line(branch="other")
        append_ledger(path, first)
        append_ledger(path, second)
        assert read_ledger(path) == [first, second]
        assert len(path.read_text(encoding="utf-8").splitlines()) == 2

    def test_a_malformed_line_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "ledger.jsonl"
        append_ledger(path, _ledger_line())
        with path.open("a", encoding="utf-8") as handle:
            handle.write("not json\n")
        with pytest.raises(RejectError):
            read_ledger(path)

    def test_a_line_missing_a_field_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "ledger.jsonl"
        path.write_text(json.dumps({"schema": 1, "branch": "x"}) + "\n", encoding="utf-8")
        with pytest.raises(RejectError):
            read_ledger(path)

    def test_a_blank_line_is_tolerated(self, tmp_path: Path) -> None:
        path = tmp_path / "ledger.jsonl"
        append_ledger(path, _ledger_line())
        with path.open("a", encoding="utf-8") as handle:
            handle.write("\n")
        assert len(read_ledger(path)) == 1


class TestLedgerMerge:
    """RULINGS Q8: two branches appending a line each must merge as both lines."""

    def test_union_merge_keeps_both_appends(self, tmp_path: Path) -> None:
        root = tmp_path / "r"
        root.mkdir()
        _git(root, "init", "-q", "-b", "main")
        project_attributes = Path(__file__).resolve().parents[3] / ".gitattributes"
        (root / ".gitattributes").write_text(
            project_attributes.read_text(encoding="utf-8"), encoding="utf-8"
        )
        ledger = root / ".claude" / "branch-removals.jsonl"
        append_ledger(ledger, _ledger_line(branch="seed"))
        _git(root, "add", "-A")
        _git(root, "commit", "-q", "-m", "seed")
        _git(root, "switch", "-q", "-c", "a")
        append_ledger(ledger, _ledger_line(branch="from-a"))
        _git(root, "commit", "-q", "-am", "a")
        _git(root, "switch", "-q", "main")
        append_ledger(ledger, _ledger_line(branch="from-main"))
        _git(root, "commit", "-q", "-am", "main")
        _git(root, "merge", "-q", "--no-edit", "a")
        assert {line.branch for line in read_ledger(ledger)} == {"seed", "from-a", "from-main"}
