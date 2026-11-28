"""The remote SCOPE of a no-value review (ledger N763).

A request, a verdict and a ledger line carry ``remote``: empty for the local route,
the remote's name for a review of ``refs/remotes/<remote>/<branch>``. A verdict of
one scope never unlocks a delete of the other, and a local record serialises exactly
as it did before the scope existed, so its ledger identity is unchanged.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from claude_code_hooks_daemon.config.models import BranchRejectConfig
from claude_code_hooks_daemon.core.branch_reject import (
    LedgerLine,
    LedgerRefusal,
    RejectError,
    RejectRequest,
    RejectStore,
    Verdict,
    branch_still_at_tip,
    branch_tip,
    bundle_path_for,
    bundle_problems,
    compose_prompt,
    compute_inventory,
    entry_key,
    restore_commands,
    subject_ref,
    write_bundle,
)
from tests.unit.core.test_branch_reject import (
    NOW,
    _git,
    _issue,
    _ledger_line,
    _main_sha,
    _problems,
    _tip,
    config,
    repo,
    store,
)

__all__ = ["config", "repo", "store"]

REMOTE = "origin"


@pytest.fixture
def tracked(repo: Path) -> Path:
    """``repo`` with ``refs/remotes/origin/{feat,main}`` at the local tips."""
    _git(repo, "update-ref", "refs/remotes/origin/feat", _tip(repo))
    _git(repo, "update-ref", "refs/remotes/origin/main", _main_sha(repo))
    return repo


def _remote_verdict(repo: Path, store: RejectStore) -> Verdict:
    verdict = _issue(repo, store)
    request = store.read_request(verdict.nonce)
    assert request is not None
    store.write_request(replace(request, remote=REMOTE))
    remote = replace(verdict, remote=REMOTE)
    store.write_verdict(remote)
    return remote


class TestSubjectRef:
    def test_local_scope_is_the_branch_ref(self) -> None:
        assert subject_ref("feat") == "refs/heads/feat"

    def test_remote_scope_is_the_tracking_ref(self) -> None:
        assert subject_ref("feat", REMOTE) == "refs/remotes/origin/feat"

    @pytest.mark.parametrize("remote", ["..", "a/b", "-x", "a b", ".hidden", "a..b"])
    def test_an_unsafe_remote_name_is_refused(self, remote: str) -> None:
        with pytest.raises(RejectError):
            subject_ref("feat", remote)

    def test_branch_tip_reads_the_tracking_ref(self, tracked: Path) -> None:
        _git(tracked, "update-ref", "refs/remotes/origin/feat", _main_sha(tracked))
        assert branch_tip(tracked, "feat", remote=REMOTE) == _main_sha(tracked)
        assert branch_tip(tracked, "feat") == _tip(tracked)


class TestSerialisation:
    def test_a_local_record_carries_no_remote_key(self, repo: Path, store: RejectStore) -> None:
        verdict = _issue(repo, store)
        assert "remote" not in verdict.to_dict()
        request = store.read_request(verdict.nonce)
        assert request is not None
        assert "remote" not in request.to_dict()
        assert "remote" not in _ledger_line().to_dict()

    def test_a_remote_record_round_trips(self, repo: Path, store: RejectStore) -> None:
        verdict = _remote_verdict(repo, store)
        assert Verdict.from_dict(verdict.to_dict()).remote == REMOTE
        request = store.read_request(verdict.nonce)
        assert request is not None and request.remote == REMOTE
        line = replace(_ledger_line(), remote=REMOTE)
        assert LedgerLine.from_dict(line.to_dict()) == line

    def test_the_local_ledger_identity_is_unchanged_by_the_scope(self) -> None:
        line = _ledger_line()
        assert entry_key(line) == entry_key(LedgerLine.from_dict(line.to_dict()))
        assert entry_key(replace(line, remote=REMOTE)) != entry_key(line)

    @pytest.mark.parametrize("bad", [7, "", "..", "a/b", None])
    def test_a_damaged_remote_field_in_a_verdict_is_an_error(
        self, repo: Path, store: RejectStore, bad: object
    ) -> None:
        data = _issue(repo, store).to_dict()
        data["remote"] = bad
        with pytest.raises(RejectError):
            Verdict.from_dict(data)

    @pytest.mark.parametrize("bad", [7, "", "..", "a/b", None])
    def test_a_damaged_remote_field_in_a_request_is_an_error(
        self, repo: Path, store: RejectStore, bad: object
    ) -> None:
        request = store.read_request(_issue(repo, store).nonce)
        assert request is not None
        data = request.to_dict()
        data["remote"] = bad
        with pytest.raises(RejectError):
            RejectRequest.from_dict(data)

    def test_a_refusal_carries_the_scope(self) -> None:
        refusal = LedgerRefusal(
            branch="feat",
            tip="1" * 40,
            verdict_ids=("a" * 32,),
            detail="git refused",
            refused_at=NOW,
            remote=REMOTE,
        )
        assert LedgerRefusal.from_dict(refusal.to_dict()) == refusal
        assert "remote" not in replace(refusal, remote="").to_dict()


class TestScopedVerdicts:
    def test_a_local_verdict_is_not_offered_to_the_remote_scope(
        self, repo: Path, store: RejectStore
    ) -> None:
        verdict = _issue(repo, store)
        assert store.verdicts_for("feat", verdict.tip) == [verdict]
        assert store.verdicts_for("feat", verdict.tip, remote=REMOTE) == []

    def test_a_remote_verdict_is_not_offered_to_the_local_scope(
        self, tracked: Path, store: RejectStore
    ) -> None:
        verdict = _remote_verdict(tracked, store)
        assert store.verdicts_for("feat", verdict.tip) == []
        assert store.verdicts_for("feat", verdict.tip, remote=REMOTE) == [verdict]
        assert store.verdicts_named("feat", remote=REMOTE) == [verdict]
        assert store.verdicts_named("other", remote=REMOTE) == []

    def test_a_verdict_disagreeing_with_its_request_on_scope_is_refused(
        self, tracked: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        verdict = _issue(tracked, store)
        forged = replace(verdict, remote=REMOTE)
        found = _problems(tracked, store, forged, config)
        assert "the verdict disagrees with its request on remote" in found

    def test_a_remote_verdict_is_judged_against_the_tracking_tip(
        self, tracked: Path, store: RejectStore, config: BranchRejectConfig
    ) -> None:
        verdict = _remote_verdict(tracked, store)
        assert _problems(tracked, store, verdict, config) == []
        _git(tracked, "update-ref", "refs/remotes/origin/feat", _main_sha(tracked))
        found = _problems(tracked, store, verdict, config)
        assert any("the tip moved" in problem for problem in found)


class TestRemoteInventoryAndBundle:
    def test_the_inventory_reads_the_tracking_ref(self, tracked: Path) -> None:
        local = compute_inventory(tracked, "feat", "main")
        remote = compute_inventory(tracked, "feat", "refs/remotes/origin/main", remote=REMOTE)
        assert remote == local
        _git(tracked, "branch", "-D", "feat")
        assert compute_inventory(tracked, "feat", "main", remote=REMOTE) == local

    def test_the_remote_bundle_path_cannot_collide_with_a_local_one(
        self, repo: Path, config: BranchRejectConfig
    ) -> None:
        tip = "1" * 40
        remote = bundle_path_for(repo, config, "feat", tip, remote=REMOTE)
        flattened = bundle_path_for(repo, config, "remotes/origin/feat", tip)
        assert remote != flattened
        assert remote.parent.name == REMOTE

    def test_a_remote_bundle_holds_the_tracking_ref_and_restores_it(
        self, tracked: Path, config: BranchRejectConfig
    ) -> None:
        tip = _tip(tracked)
        record = write_bundle(tracked, "feat", tip, _main_sha(tracked), config, remote=REMOTE)
        assert bundle_problems(tracked, record, "feat", remote=REMOTE) == []
        assert bundle_problems(tracked, record, "feat") != []
        fetch, push = restore_commands("feat", tip, record.path, remote=REMOTE)
        assert "refs/remotes/origin/feat:refs/remotes/origin/feat" in fetch
        assert push == f"git push origin {tip}:refs/heads/feat"

    def test_a_remote_bundle_refuses_a_moved_tracking_tip(
        self, tracked: Path, config: BranchRejectConfig
    ) -> None:
        tip = _tip(tracked)
        _git(tracked, "update-ref", "refs/remotes/origin/feat", _main_sha(tracked))
        with pytest.raises(RejectError):
            write_bundle(tracked, "feat", tip, _main_sha(tracked), config, remote=REMOTE)

    def test_still_at_tip_reads_the_scope(self, tracked: Path) -> None:
        line = replace(_ledger_line(), tip=_tip(tracked), remote=REMOTE)
        assert branch_still_at_tip(tracked, line) is True
        _git(tracked, "update-ref", "-d", "refs/remotes/origin/feat")
        assert branch_still_at_tip(tracked, line) is False
        assert branch_still_at_tip(tracked, replace(line, remote="")) is True


def _prompt(*, remote: str = "", pr_number: int | None = None) -> str:
    return compose_prompt(
        nonce="a" * 32,
        branch="feat",
        tip="1" * 40,
        default_sha="2" * 40,
        commits=[("1" * 40, "add feature")],
        paths=["src/feature.py"],
        keep_reasons=(),
        remote=remote,
        pr_number=pr_number,
    )


class TestRemotePrompt:
    def test_the_local_prompt_does_not_mention_a_pull_request(self) -> None:
        assert "pull request" not in _prompt()
        assert "refs/remotes" not in _prompt()

    def test_the_remote_prompt_names_the_ref_the_pr_and_the_whole_diff(self) -> None:
        prompt = _prompt(remote=REMOTE, pr_number=42)
        assert "refs/remotes/origin/feat" in prompt
        assert "pull request #42 was closed without being merged" in prompt
        assert f"git log --patch {'2' * 40}..{'1' * 40}" in prompt

    def test_a_remote_prompt_needs_its_pr_number(self) -> None:
        with pytest.raises(RejectError):
            _prompt(remote=REMOTE)
