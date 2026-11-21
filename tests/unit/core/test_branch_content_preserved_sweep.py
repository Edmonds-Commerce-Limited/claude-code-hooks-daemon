"""A release branch whose work main got another way can be cleaned by its own tool.

The shape that refused: ``rc/x`` carries two merges FROM main, one content commit
and two empty commits, and main gained the same bytes through another branch, while
a linked worktree holds ``rc/x``. ``delete-branch`` said only "is checked out in a
linked worktree", and ``branch-sweep --clean`` never offered it, because the
inventory knew no content-preserved state (patch-equivalence fails on the merges).

These tests pin the fix and its limits:

- ``delete_branches`` still refuses a branch a worktree holds (git would too), but
  names the proof it found and the exact ``git worktree remove`` step;
- ``clean_sweep`` treats a merge-carrying branch whose net change the remote-tracking
  default holds as cleanable, and re-proves it at apply time;
- the default inventory (the one hooks build) is unchanged, so the WIP cap still
  counts the branch as open work;
- the UNHELD control, whose bytes main does not have, is refused everywhere.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.config.models import BranchesConfig
from claude_code_hooks_daemon.core import branch_cleanup, branch_inventory
from claude_code_hooks_daemon.core.branch_cleanup import CLEAN_STATES, cleanup_after_merge
from claude_code_hooks_daemon.core.branch_inventory import BranchState
from claude_code_hooks_daemon.core.branch_keep import keep_branch
from claude_code_hooks_daemon.daemon.branch_safety import (
    REFUSAL_WORKTREE,
    TIER_UNPROVEN,
    BranchClassification,
    classify_branch,
    delete_branches,
)
from tests.conftest import HERMETIC_GIT_EMAIL
from tests.support.git_fixtures import git_setup_timeout

_RC = "rc/1.0.0"
_CONFIG = BranchesConfig(default="main")


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=True,
        capture_output=True,
        text=True,
        timeout=git_setup_timeout(),
    ).stdout.strip()


def _write_commit(repo: Path, filename: str, text: str, message: str) -> None:
    (repo / filename).write_text(text, encoding="utf-8")
    _git(repo, "add", filename)
    _git(repo, "commit", "-q", "-m", message)


def _build(root: Path, main_bytes: str, *, worktree: bool = True) -> tuple[Path, Path]:
    """The rc/3.75.0 shape; returns ``(seed clone, worktree path)``.

    ``main_bytes`` equal to the rc's bytes is the HELD case; anything else is the
    unheld control, whose content exists only on the branch.
    """
    remote = root / "remote.git"
    seed = root / "seed"
    remote.mkdir(parents=True)
    seed.mkdir()
    _git(remote, "init", "-q", "--bare", "-b", "main")
    _git(seed, "init", "-q", "-b", "main")
    _git(seed, "config", "user.email", HERMETIC_GIT_EMAIL)
    _git(seed, "config", "user.name", "t")
    (seed / ".gitignore").write_text("untracked/\n", encoding="utf-8")
    _git(seed, "add", ".gitignore")
    _write_commit(seed, "a.txt", "base\n", "base")
    _git(seed, "remote", "add", "origin", str(remote))
    _git(seed, "push", "-q", "origin", "main")
    _git(seed, "branch", _RC)
    _write_commit(seed, "m.txt", "m1\n", "main work")
    _git(seed, "switch", "-q", _RC)
    _git(seed, "merge", "-q", "--no-ff", "-m", "Merge main into rc", "main")
    _write_commit(seed, "p.py", "formatted\n", "format p.py on rc")
    _git(seed, "commit", "-q", "--allow-empty", "-m", "Park branch: rc candidate")
    _git(seed, "commit", "-q", "--allow-empty", "-m", "Unpark branch")
    _git(seed, "push", "-q", "-u", "origin", _RC)
    _git(seed, "switch", "-q", "main")
    # The release reached main through ANOTHER branch: same bytes, different commits.
    _write_commit(seed, "p.py", main_bytes, "format p.py on main")
    _git(seed, "push", "-q", "origin", "main")
    _git(seed, "remote", "set-head", "origin", "main")
    tree = root / "wt-rc"
    if worktree:
        _git(seed, "worktree", "add", "-q", str(tree), _RC)
    return seed, tree


@pytest.fixture
def held(tmp_path: Path) -> tuple[Path, Path]:
    return _build(tmp_path / "held", "formatted\n")


@pytest.fixture
def unheld(tmp_path: Path) -> tuple[Path, Path]:
    return _build(tmp_path / "unheld", "different\n")


@pytest.fixture
def held_no_worktree(tmp_path: Path) -> Path:
    return _build(tmp_path / "held-nowt", "formatted\n", worktree=False)[0]


def _has_branch(repo: Path, name: str) -> bool:
    return bool(_git(repo, "branch", "--list", name))


class TestDeleteBranchNamesTheWorktreeStep:
    def test_a_proven_branch_is_still_refused_but_names_proof_and_step(
        self, held: tuple[Path, Path]
    ) -> None:
        seed, tree = held
        report = delete_branches(seed, [_RC], protected_ref="main", dry_run=True)
        (verdict,) = report.classifications
        assert report.refused
        assert verdict.refusal == REFUSAL_WORKTREE
        assert verdict.tier is None
        assert "content-preserved" in verdict.detail
        assert f"git worktree remove {tree}" in " ".join(report.blockers)
        assert "delete-branch" in verdict.detail

    def test_the_real_run_deletes_nothing_while_the_worktree_holds_it(
        self, held: tuple[Path, Path]
    ) -> None:
        seed, _tree = held
        report = delete_branches(seed, [_RC], protected_ref="main")
        assert report.refused
        assert report.deleted == ()
        assert _has_branch(seed, _RC)

    def test_an_unproven_branch_gets_no_removal_step(self, unheld: tuple[Path, Path]) -> None:
        seed, _tree = unheld
        report = delete_branches(seed, [_RC], protected_ref="main", dry_run=True)
        (verdict,) = report.classifications
        assert verdict.refusal == REFUSAL_WORKTREE
        assert "git worktree remove" not in verdict.detail
        assert "content-preserved" not in verdict.detail
        assert "checked out in a linked worktree" in verdict.detail

    def test_a_proven_branch_without_the_content_tier_gets_no_removal_step(
        self, held: tuple[Path, Path]
    ) -> None:
        seed, _tree = held
        report = delete_branches(
            seed, [_RC], protected_ref="main", dry_run=True, content_tier=False
        )
        assert "git worktree remove" not in report.classifications[0].detail

    def test_after_the_worktree_goes_the_branch_deletes(self, held: tuple[Path, Path]) -> None:
        seed, tree = held
        _git(seed, "worktree", "remove", str(tree))
        report = delete_branches(seed, [_RC], protected_ref="main")
        assert report.deleted == (_RC,)


class TestInventory:
    def test_the_default_inventory_is_unchanged(self, held: tuple[Path, Path]) -> None:
        seed, _tree = held
        record = branch_inventory.build_inventory(seed, _CONFIG).records[_RC]
        assert record.state == BranchState.LIVE

    def test_the_opt_in_inventory_proves_content_preserved(self, held: tuple[Path, Path]) -> None:
        seed, _tree = held
        inventory = branch_inventory.build_inventory(seed, _CONFIG, prove_content=True)
        record = inventory.records[_RC]
        assert record.state == BranchState.CONTENT_PRESERVED
        assert record.state in CLEAN_STATES

    def test_the_opt_in_inventory_leaves_the_unheld_control_live(
        self, unheld: tuple[Path, Path]
    ) -> None:
        seed, _tree = unheld
        inventory = branch_inventory.build_inventory(seed, _CONFIG, prove_content=True)
        assert inventory.records[_RC].state == BranchState.LIVE
        verdict = classify_branch(seed, _RC, protected_ref="main", ignore_worktree=True)
        assert verdict.tier == TIER_UNPROVEN

    def test_a_project_below_the_git_top_level_reads_root_relative_paths(
        self, held_no_worktree: Path
    ) -> None:
        # A branch that only DELETES a file main keeps holds nothing main has. The
        # proof reads root-relative paths; run from a subdirectory, a lookup would
        # miss and the deleted path would read as "absent", i.e. held.
        seed = held_no_worktree
        _git(seed, "switch", "-q", "-c", "deletes-a", "main")
        _git(seed, "rm", "-q", "a.txt")
        _git(seed, "commit", "-q", "-m", "delete a.txt")
        _git(seed, "push", "-q", "origin", "deletes-a")
        _git(seed, "switch", "-q", "main")
        project = seed / "proj"
        project.mkdir()
        inventory = branch_inventory.build_inventory(project, _CONFIG, prove_content=True)
        assert inventory.records["deletes-a"].state == BranchState.LIVE

    def test_an_unanswered_proof_leaves_the_branch_live(
        self, held_no_worktree: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from claude_code_hooks_daemon.core import remote_branch_proof

        def unavailable(*_args: object, **_kwargs: object) -> bool:
            raise remote_branch_proof.ProofUnavailableError("git failed")

        monkeypatch.setattr(remote_branch_proof, "holds_net_change", unavailable)
        inventory = branch_inventory.build_inventory(held_no_worktree, _CONFIG, prove_content=True)
        assert inventory.records[_RC].state == BranchState.LIVE


class TestDeleteBranchEdgeCases:
    def test_a_branch_in_the_main_checkout_gets_no_removal_step(
        self, held_no_worktree: Path, tmp_path: Path
    ) -> None:
        seed = held_no_worktree
        _git(seed, "switch", "-q", _RC)
        linked = tmp_path / "linked-main"
        _git(seed, "worktree", "add", "-q", str(linked), "main")
        report = delete_branches(linked, [_RC], protected_ref="main", dry_run=True)
        (verdict,) = report.classifications
        assert verdict.refusal == REFUSAL_WORKTREE
        assert "git worktree remove" not in verdict.detail
        assert "switch the main checkout" in verdict.detail

    def test_a_failed_reproof_keeps_the_plain_refusal(
        self, held: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from claude_code_hooks_daemon.daemon import branch_safety

        real = branch_safety.classify_branch

        def failing(repo: Path, name: str, **kwargs: Any) -> BranchClassification:
            if kwargs.get("ignore_worktree"):
                raise subprocess.CalledProcessError(127, ["git"], "", "timed out")
            return real(repo, name, **kwargs)

        monkeypatch.setattr(branch_safety, "classify_branch", failing)
        seed, _tree = held
        report = delete_branches(seed, [_RC], protected_ref="main", dry_run=True)
        (verdict,) = report.classifications
        assert report.refused
        assert verdict.refusal == REFUSAL_WORKTREE
        assert "git worktree remove" not in verdict.detail
        assert "failed" in verdict.detail


class TestCleanSweep:
    def test_the_dry_run_offers_the_held_branch(self, held: tuple[Path, Path]) -> None:
        seed, tree = held
        report = branch_cleanup.clean_sweep(seed, _CONFIG, dry_run=True)
        assert f"would remove the worktree {tree}" in report.commands
        assert f"would delete {_RC} (proven content-preserved)" in report.commands

    def test_apply_deletes_the_held_branch_beside_a_merged_one(
        self, held: tuple[Path, Path]
    ) -> None:
        seed, tree = held
        _git(seed, "branch", "merged-plain", "main~1")
        report = branch_cleanup.clean_sweep(seed, _CONFIG, dry_run=False)
        assert sorted(report.deleted) == ["merged-plain", _RC], report.skipped
        assert tree in report.removed_worktrees
        assert not _has_branch(seed, _RC)

    def test_apply_deletes_the_held_branch_without_a_worktree(self, held_no_worktree: Path) -> None:
        report = branch_cleanup.clean_sweep(held_no_worktree, _CONFIG, dry_run=False)
        assert report.deleted == (_RC,), report.skipped

    def test_the_remote_half_proves_and_deletes_the_held_copy(self, held_no_worktree: Path) -> None:
        report = branch_cleanup.clean_sweep(held_no_worktree, _CONFIG, dry_run=False, remote=True)
        assert f"origin/{_RC}" in report.deleted_remote, report.skipped

    def test_the_unheld_control_is_never_touched(self, unheld: tuple[Path, Path]) -> None:
        seed, tree = unheld
        dry = branch_cleanup.clean_sweep(seed, _CONFIG, dry_run=True, remote=True)
        assert not any(_RC in line for line in dry.commands)
        report = branch_cleanup.clean_sweep(seed, _CONFIG, dry_run=False, remote=True)
        assert _RC not in report.deleted
        assert f"origin/{_RC}" not in report.deleted_remote
        assert _has_branch(seed, _RC)
        assert tree.is_dir()
        assert _RC in _git(seed, "ls-remote", "--heads", "origin")

    def test_a_kept_content_preserved_branch_is_spared(self, held_no_worktree: Path) -> None:
        tip = _git(held_no_worktree, "rev-parse", f"refs/heads/{_RC}")
        keep_branch(
            held_no_worktree,
            [tip],
            reason="needed for the audit",
            remote="origin",
            user="t",
            now=time.time(),
        )
        report = branch_cleanup.clean_sweep(held_no_worktree, _CONFIG, dry_run=False)
        assert report.deleted == ()
        assert _has_branch(held_no_worktree, _RC)
        assert any("needed for the audit" in line for line in report.skipped)


class TestCleanupAfterMergeStaysAncestryOnly:
    def test_the_held_branch_is_not_deleted_after_a_merge(self, held_no_worktree: Path) -> None:
        report = cleanup_after_merge(
            held_no_worktree, [_RC], config=_CONFIG, target="main", mode="act"
        )
        assert report.deleted == ()
        assert _has_branch(held_no_worktree, _RC)


def _make_foreign(seed: Path) -> None:
    """``_RC`` becomes another author's: remote-only, tip authored by someone else."""
    _git(seed, "branch", "-D", _RC)
    _git(seed, "config", "user.email", "someone-else@hooks-daemon.invalid")


class TestForeignContentPreservedRemoteDelete:
    def test_the_inventory_carries_the_content_proof_for_a_foreign_branch(
        self, held_no_worktree: Path
    ) -> None:
        _make_foreign(held_no_worktree)
        inventory = branch_inventory.build_inventory(held_no_worktree, _CONFIG, prove_content=True)
        record = inventory.records[_RC]
        assert record.state == BranchState.FOREIGN
        assert record.proof_state == BranchState.CONTENT_PRESERVED
        assert record.cleanup_state in branch_cleanup.REMOTE_CLEAN_STATES

    def test_clean_remote_deletes_an_unmoved_foreign_branch(self, held_no_worktree: Path) -> None:
        _make_foreign(held_no_worktree)
        report = branch_cleanup.clean_sweep(held_no_worktree, _CONFIG, dry_run=False, remote=True)
        assert f"origin/{_RC}" in report.deleted_remote, report.skipped
        assert _RC not in _git(held_no_worktree, "ls-remote", "--heads", "origin")

    def test_a_remote_tip_moved_after_planning_is_not_deleted(
        self, held_no_worktree: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seed = held_no_worktree
        _make_foreign(seed)
        remote_url = _git(seed, "remote", "get-url", "origin")
        other = tmp_path / "other-clone"
        _git(tmp_path, "clone", "-q", "-b", _RC, remote_url, str(other))
        real = branch_cleanup._push_deletes
        planned = _git(other, "rev-parse", "HEAD")
        called: list[bool] = []

        def moved_first(repo: Path, remote: str, tips: Any) -> Any:
            called.append(True)
            _git(other, "commit", "-q", "--allow-empty", "-m", "new work after the proof")
            _git(other, "push", "-q", "origin", _RC)
            return real(repo, remote, tips)

        monkeypatch.setattr(branch_cleanup, "_push_deletes", moved_first)
        report = branch_cleanup.clean_sweep(seed, _CONFIG, dry_run=False, remote=True)
        assert called, "the remote delete was never attempted, so the lease went unexercised"
        assert f"origin/{_RC}" not in report.deleted_remote
        moved = _git(other, "rev-parse", "HEAD")
        assert moved != planned
        assert moved in _git(seed, "ls-remote", "--heads", "origin", _RC)


def _park(repo: Path, *, commit: bool) -> None:
    from claude_code_hooks_daemon.core.branch_park import park_branch

    park_branch(repo, _RC, reason="waiting on the audit", remote="origin", commit=commit)


class TestParkedContentPreservedIsSpared:
    @pytest.mark.parametrize("commit", [True, False], ids=["trailer", "record-only"])
    def test_a_parked_branch_is_not_cleaned_and_the_reason_is_reported(
        self, held_no_worktree: Path, commit: bool
    ) -> None:
        seed = held_no_worktree
        _park(seed, commit=commit)
        dry = branch_cleanup.clean_sweep(seed, _CONFIG, dry_run=True, remote=True)
        assert not any(_RC in line for line in dry.commands), dry.commands
        assert any("waiting on the audit" in line for line in dry.skipped), dry.skipped
        report = branch_cleanup.clean_sweep(seed, _CONFIG, dry_run=False, remote=True)
        assert _RC not in report.deleted
        assert f"origin/{_RC}" not in report.deleted_remote
        assert _has_branch(seed, _RC)
        assert _RC in _git(seed, "ls-remote", "--heads", "origin")
        assert any("waiting on the audit" in line for line in report.skipped)

    def test_a_park_trailer_alone_still_spares_the_branch(self, held_no_worktree: Path) -> None:
        from claude_code_hooks_daemon.core.branch_park import clear_park_record

        seed = held_no_worktree
        _park(seed, commit=True)
        clear_park_record(seed, _RC)
        report = branch_cleanup.clean_sweep(seed, _CONFIG, dry_run=False, remote=True)
        assert _RC not in report.deleted
        assert any("waiting on the audit" in line for line in report.skipped)


class TestApplyRechecksTheWorktree:
    def test_a_worktree_switched_after_planning_is_left_alone(
        self, held: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seed, tree = held
        real = branch_cleanup._apply_in_batches

        def switched_first(*args: Any, **kwargs: Any) -> Any:
            _git(tree, "switch", "-q", "-c", "fresh-claim", "main")
            return real(*args, **kwargs)

        monkeypatch.setattr(branch_cleanup, "_apply_in_batches", switched_first)
        report = branch_cleanup.clean_sweep(seed, _CONFIG, dry_run=False)
        assert tree.is_dir()
        assert tree not in report.removed_worktrees
        assert _RC not in report.deleted
        assert _has_branch(seed, _RC)
        assert any(_RC in line and "fresh-claim" in line for line in report.skipped), report.skipped


class TestMoreSpareAndRecheckEdges:
    def test_a_parked_foreign_branch_is_not_remote_deleted(self, held_no_worktree: Path) -> None:
        seed = held_no_worktree
        _park(seed, commit=True)
        _make_foreign(seed)
        report = branch_cleanup.clean_sweep(seed, _CONFIG, dry_run=False, remote=True)
        assert f"origin/{_RC}" not in report.deleted_remote
        assert _RC in _git(seed, "ls-remote", "--heads", "origin")
        assert any(
            line.startswith(f"origin/{_RC}:") and "waiting on the audit" in line
            for line in report.skipped
        ), report.skipped

    def test_an_unreadable_worktree_list_at_apply_keeps_the_worktree(
        self, held: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seed, tree = held
        real_apply = branch_cleanup._apply_in_batches

        def listing_breaks(*args: Any, **kwargs: Any) -> Any:
            def broken(_repo: Path) -> Any:
                raise RuntimeError("git worktree list failed: simulated")

            monkeypatch.setattr(branch_cleanup, "linked_worktree_records", broken)
            return real_apply(*args, **kwargs)

        monkeypatch.setattr(branch_cleanup, "_apply_in_batches", listing_breaks)
        report = branch_cleanup.clean_sweep(seed, _CONFIG, dry_run=False)
        assert tree.is_dir()
        assert _has_branch(seed, _RC)
        assert any("could not be re-read" in line for line in report.skipped), report.skipped
