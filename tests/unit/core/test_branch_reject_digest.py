"""Tests for the removal digest (Plan 00620 Task 2.3, RULINGS.md section 3 item 5).

The digest lists every removal, every git-refused attempt and every keep verdict the
owner has not yet marked read. Four properties are the point:

- the watermark is keyed by each entry's IDENTITY (the sha256 of its canonical JSON),
  never by position or time, so a ledger line that arrives by a ``merge=union`` after
  a digest still shows as undigested;
- listing never advances the watermark; only an explicit mark-read does, and it marks
  exactly the entries that were listed;
- a damaged ledger, watermark or keep record raises, and never reads as zero;
- the digest gates nothing: ``approve_removal`` answers the same whatever its state.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from claude_code_hooks_daemon.config.models import BranchRejectConfig
from claude_code_hooks_daemon.core.branch_reject import (
    Digest,
    DigestState,
    KeepRecord,
    LedgerRefusal,
    RejectError,
    RejectRoute,
    RejectStore,
    append_ledger,
    append_refusal,
    approve_removal,
    branch_still_at_tip,
    build_digest,
    entry_key,
    mark_digest_read,
    new_id,
    read_digest_state,
    write_digest_state,
)
from tests.unit.core.test_branch_reject import (
    DAY,
    NOW,
    _issue,
    _ledger_line,
    _tip,
    config,
    repo,
    store,
)

__all__ = ["config", "repo", "store"]


@pytest.fixture
def ledger(repo: Path, config: BranchRejectConfig) -> Path:
    return repo / config.ledger_path


def _keep(branch: str = "kept", recorded_at: float = NOW) -> KeepRecord:
    return KeepRecord(
        verdict_id=new_id(),
        branch=branch,
        tip="3" * 40,
        commits=("3" * 40,),
        reasons=("still needed",),
        recorded_at=recorded_at,
    )


def _refusal(line_branch: str = "feat") -> LedgerRefusal:
    return LedgerRefusal(
        branch=line_branch,
        tip="1" * 40,
        verdict_ids=(new_id(),),
        detail="git said no",
        refused_at=NOW,
    )


def _digest(
    ledger: Path, store: RejectStore, config: BranchRejectConfig, now: float = NOW
) -> Digest:
    return build_digest(ledger, store, now=now, config=config)


class TestEntryKey:
    def test_the_key_is_the_sha256_of_the_canonical_json(self) -> None:
        line = _ledger_line()
        key = entry_key(line)
        assert len(key) == 64
        assert entry_key(replace(line)) == key

    def test_two_different_lines_have_different_keys(self) -> None:
        assert entry_key(_ledger_line()) != entry_key(_ledger_line())

    def test_a_refusal_is_keyed_too(self) -> None:
        assert len(entry_key(_refusal())) == 64


class TestDigestState:
    def test_a_missing_state_is_never_marked(self, store: RejectStore) -> None:
        state = read_digest_state(store.digest_path)
        assert state == DigestState(ledger_keys=frozenset(), keep_ids=frozenset(), marked_at=None)

    def test_it_round_trips(self, store: RejectStore) -> None:
        state = DigestState(
            ledger_keys=frozenset({"a" * 64}), keep_ids=frozenset({"b" * 32}), marked_at=NOW
        )
        write_digest_state(store.digest_path, state)
        assert read_digest_state(store.digest_path) == state

    def test_the_state_lives_in_the_store_root(self, store: RejectStore) -> None:
        assert store.digest_path.parent == store.root

    @pytest.mark.parametrize(
        "content",
        [
            "not json",
            "[]",
            json.dumps({"schema": 1, "ledger_keys": [], "keep_ids": []}),
            json.dumps({"schema": 2, "ledger_keys": [], "keep_ids": [], "marked_at": NOW}),
            json.dumps({"schema": 1, "ledger_keys": ["short"], "keep_ids": [], "marked_at": NOW}),
            json.dumps({"schema": 1, "ledger_keys": [], "keep_ids": ["x"], "marked_at": NOW}),
            json.dumps({"schema": 1, "ledger_keys": "a", "keep_ids": [], "marked_at": NOW}),
        ],
    )
    def test_a_damaged_state_raises(self, store: RejectStore, content: str) -> None:
        store.digest_path.parent.mkdir(parents=True, exist_ok=True)
        store.digest_path.write_text(content, encoding="utf-8")
        with pytest.raises(RejectError):
            read_digest_state(store.digest_path)


class TestBuildDigest:
    def test_an_empty_ledger_is_an_empty_digest(
        self, ledger: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        digest = _digest(ledger, store, config)
        assert digest.removals == ()
        assert digest.refusals == ()
        assert digest.keeps == ()
        assert digest.is_empty
        assert digest.last_marked_at is None

    def test_it_lists_removals_refusals_and_keeps(
        self, ledger: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        line = _ledger_line()
        refusal = _refusal()
        keep = _keep()
        append_ledger(ledger, line)
        append_refusal(ledger, refusal)
        store.write_keep(keep)
        digest = _digest(ledger, store, config)
        assert digest.removals == (line,)
        assert digest.refusals == (refusal,)
        assert digest.keeps == (keep,)
        assert not digest.is_empty

    def test_listing_never_advances_the_watermark(
        self, ledger: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        append_ledger(ledger, _ledger_line())
        store.write_keep(_keep())
        first = _digest(ledger, store, config)
        second = _digest(ledger, store, config)
        assert first == second
        assert not store.digest_path.exists()

    def test_mark_read_hides_what_was_listed(
        self, ledger: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        append_ledger(ledger, _ledger_line())
        store.write_keep(_keep())
        state = mark_digest_read(store, _digest(ledger, store, config), now=NOW + 5)
        assert state.marked_at == NOW + 5
        after = _digest(ledger, store, config)
        assert after.is_empty
        assert after.last_marked_at == NOW + 5

    def test_mark_read_marks_only_the_listed_snapshot(
        self, ledger: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        append_ledger(ledger, _ledger_line("first"))
        listed = _digest(ledger, store, config)
        late = _ledger_line("late")
        append_ledger(ledger, late)
        late_keep = _keep("late-keep")
        store.write_keep(late_keep)
        mark_digest_read(store, listed, now=NOW)
        after = _digest(ledger, store, config)
        assert after.removals == (late,)
        assert after.keeps == (late_keep,)

    def test_mark_read_keeps_the_earlier_marks(
        self, ledger: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        append_ledger(ledger, _ledger_line("one"))
        mark_digest_read(store, _digest(ledger, store, config), now=NOW)
        append_ledger(ledger, _ledger_line("two"))
        mark_digest_read(store, _digest(ledger, store, config), now=NOW + 1)
        assert _digest(ledger, store, config).is_empty

    def test_a_line_merged_in_after_a_digest_is_undigested(
        self, ledger: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        """``merge=union`` can put an OLDER line before ones already marked read."""
        later = _ledger_line("later", removed_at=NOW)
        append_ledger(ledger, later)
        mark_digest_read(store, _digest(ledger, store, config), now=NOW)
        merged = _ledger_line("from-another-branch", removed_at=NOW - DAY)
        text = ledger.read_text(encoding="utf-8")
        ledger.write_text(
            json.dumps(merged.to_dict(), sort_keys=True) + "\n" + text, encoding="utf-8"
        )
        digest = _digest(ledger, store, config)
        assert digest.removals == (merged,)

    def test_the_rate_state_is_reported(
        self, ledger: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        for index in range(config.two_reviewer_after):
            append_ledger(ledger, _ledger_line(f"b{index}"))
        digest = _digest(ledger, store, config)
        assert digest.removals_in_window == config.two_reviewer_after
        assert digest.reviewers_next == 2

    def test_a_refusing_route_says_so(
        self, ledger: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        for index in range(config.refuse_after):
            append_ledger(ledger, _ledger_line(f"b{index}"))
        assert _digest(ledger, store, config).reviewers_next is None

    def test_the_rate_counts_marked_removals_too(
        self, ledger: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        for index in range(config.two_reviewer_after):
            append_ledger(ledger, _ledger_line(f"b{index}"))
        mark_digest_read(store, _digest(ledger, store, config), now=NOW)
        assert _digest(ledger, store, config).reviewers_next == 2

    def test_a_damaged_ledger_raises(
        self, ledger: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        ledger.parent.mkdir(parents=True, exist_ok=True)
        ledger.write_text("{not json\n", encoding="utf-8")
        with pytest.raises(RejectError):
            _digest(ledger, store, config)

    def test_a_damaged_watermark_raises(
        self, ledger: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        store.digest_path.parent.mkdir(parents=True, exist_ok=True)
        store.digest_path.write_text("{}", encoding="utf-8")
        with pytest.raises(RejectError):
            _digest(ledger, store, config)

    def test_a_damaged_keep_raises(
        self, ledger: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        keeps = store.root / "keeps"
        keeps.mkdir(parents=True)
        (keeps / f"{new_id()}.json").write_text("[", encoding="utf-8")
        with pytest.raises(RejectError):
            _digest(ledger, store, config)

    def test_mark_read_over_a_damaged_watermark_raises(
        self, ledger: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        digest = _digest(ledger, store, config)
        store.digest_path.parent.mkdir(parents=True, exist_ok=True)
        store.digest_path.write_text("{}", encoding="utf-8")
        with pytest.raises(RejectError):
            mark_digest_read(store, digest, now=NOW)


class TestStillAtTip:
    def test_a_branch_at_its_tip_resolves(self, repo: Path) -> None:
        line = replace(_ledger_line(), tip=_tip(repo))
        assert branch_still_at_tip(repo, line) is True

    def test_a_removed_branch_does_not(self, repo: Path) -> None:
        line = replace(_ledger_line("gone"), tip=_tip(repo))
        assert branch_still_at_tip(repo, line) is False

    def test_a_branch_at_another_tip_does_not(self, repo: Path) -> None:
        assert branch_still_at_tip(repo, _ledger_line()) is False

    def test_a_git_failure_raises(self, tmp_path: Path) -> None:
        not_a_repo = tmp_path / "nowhere"
        not_a_repo.mkdir()
        with pytest.raises(RejectError):
            branch_still_at_tip(not_a_repo, _ledger_line())


class TestDigestGatesNothing:
    @pytest.mark.parametrize("state", ["empty", "marked", "damaged"])
    def test_approval_is_the_same_whatever_the_digest_state(
        self,
        repo: Path,
        ledger: Path,
        store: RejectStore,
        config: BranchRejectConfig,
        state: str,
    ) -> None:
        _issue(repo, store)
        append_ledger(ledger, _ledger_line("earlier"))
        if state == "marked":
            mark_digest_read(store, _digest(ledger, store, config), now=NOW)
        elif state == "damaged":
            store.digest_path.parent.mkdir(parents=True, exist_ok=True)
            store.digest_path.write_text("garbage", encoding="utf-8")
        route = RejectRoute(store=store, ledger_path=ledger, config=config, now=NOW)
        approval = approve_removal(
            repo, "feat", _tip(repo), route, default_ref="main", write=False
        )
        assert approval.branch == "feat"
        assert len(approval.verdicts) == 1
