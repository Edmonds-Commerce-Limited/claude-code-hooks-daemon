"""Branch containment for a remote that holds a tip outside ``refs/heads`` (issue #166).

Fixture: a bare remote and a clone whose branches are pushed ONLY under
``refs/archive/``. The clone never fetches that namespace, so the offline
inventory cannot see it; the explicit CLI paths ask the remote once.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.config.models import BranchesConfig
from claude_code_hooks_daemon.core import branch_inventory, branch_sweep
from claude_code_hooks_daemon.core.branch_inventory import Containment, build_inventory
from claude_code_hooks_daemon.daemon import branch_safety
from claude_code_hooks_daemon.daemon.branch_safety import TIER_REMOTE_HELD, TIER_UNPROVEN
from claude_code_hooks_daemon.utils import git_repo, remote_refs
from tests.support import archive_remote
from tests.support.archive_remote import NOW

_CONFIG = BranchesConfig()
_RunGit = Callable[..., "subprocess.CompletedProcess[str]"]


@pytest.fixture
def scratch(tmp_path: Path) -> archive_remote.ArchiveRepo:
    return archive_remote.build(tmp_path)


def _listing(scratch: archive_remote.ArchiveRepo) -> remote_refs.RemoteRefs:
    return remote_refs.list_remote_refs(scratch.clone, "origin")


def _watching(on_call: Callable[[tuple[str, ...]], None]) -> _RunGit:
    """A ``run_git`` that reports every argv to ``on_call`` and then runs for real."""

    def run(
        cwd: Path,
        *args: str,
        timeout: float = 5,
        env: Mapping[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        on_call(args)
        return git_repo.run_git(cwd, *args, timeout=timeout, env=env)

    return run


class TestOfflineInventoryWording:
    def test_archived_branch_is_nowhere_offline(self, scratch: archive_remote.ArchiveRepo) -> None:
        record = build_inventory(scratch.clone, _CONFIG, now=NOW).records["archived"]
        assert record.containment == Containment.NOWHERE

    def test_offline_text_says_what_was_checked(self, scratch: archive_remote.ArchiveRepo) -> None:
        inventory = build_inventory(scratch.clone, _CONFIG, now=NOW)
        text = "\n".join(branch_sweep.render_report(inventory, _CONFIG, cap=5))
        assert "no remote ref holds" not in text
        assert "no fetched remote-tracking ref of origin" in text
        assert "outside refs/heads" in text
        assert "branch-sweep" in text

    def test_offline_session_summary_says_what_was_checked(
        self, scratch: archive_remote.ArchiveRepo
    ) -> None:
        inventory = build_inventory(scratch.clone, _CONFIG, now=NOW)
        text = "\n".join(
            branch_sweep.session_summary(inventory, _CONFIG, cap=5, new_session=True) or []
        )
        assert "CONTAINED NOWHERE: archived" in text
        assert "no remote ref holds" not in text
        assert "no fetched remote-tracking ref of origin" in text


class TestSweepRemoteProof:
    def test_equal_sha_archive_ref_is_proof(self, scratch: archive_remote.ArchiveRepo) -> None:
        inventory = build_inventory(scratch.clone, _CONFIG, now=NOW, remote_refs=_listing(scratch))
        record = inventory.records["archived"]
        assert record.containment == Containment.REMOTE_UNFETCHED
        assert record.contained_in == "origin: refs/archive/archived"

    def test_descendant_ref_is_proof(self, scratch: archive_remote.ArchiveRepo) -> None:
        inventory = build_inventory(scratch.clone, _CONFIG, now=NOW, remote_refs=_listing(scratch))
        record = inventory.records["archived-child"]
        assert record.containment == Containment.REMOTE_UNFETCHED
        assert record.contained_in == "origin: refs/archive/kid-above"

    def test_sweep_names_the_ref_and_does_not_advise_a_push(
        self, scratch: archive_remote.ArchiveRepo
    ) -> None:
        inventory = build_inventory(scratch.clone, _CONFIG, now=NOW, remote_refs=_listing(scratch))
        text = "\n".join(branch_sweep.render_report(inventory, _CONFIG, cap=5))
        assert "refs/archive/archived" in text
        assert "git push -u origin archived" not in text
        assert "CONTAINED NOWHERE: archived " not in text
        assert "CONTAINED NOWHERE: unpushed" in text

    def test_checked_remote_that_holds_nothing_still_advises_push(
        self, scratch: archive_remote.ArchiveRepo
    ) -> None:
        inventory = build_inventory(scratch.clone, _CONFIG, now=NOW, remote_refs=_listing(scratch))
        text = "\n".join(branch_sweep.render_report(inventory, _CONFIG, cap=5))
        assert "git push -u origin unpushed" in text
        assert "the remote was checked" in text

    def test_a_failed_listing_falls_back_and_says_so(
        self, scratch: archive_remote.ArchiveRepo
    ) -> None:
        failed = remote_refs.RemoteRefs("origin", (), failure="timed out")
        inventory = build_inventory(scratch.clone, _CONFIG, now=NOW, remote_refs=failed)
        assert inventory.records["archived"].containment == Containment.NOWHERE
        text = "\n".join(branch_sweep.render_report(inventory, _CONFIG, cap=5))
        assert "could not be checked" in text
        assert "timed out" in text

    def test_json_group_is_not_contained_nowhere(self, scratch: archive_remote.ArchiveRepo) -> None:
        inventory = build_inventory(scratch.clone, _CONFIG, now=NOW, remote_refs=_listing(scratch))
        document = branch_sweep.report_json(inventory, cap=5, config=_CONFIG)
        by_name = {entry["name"]: entry for entry in document["branches"]}
        assert by_name["archived"]["group"] != "contained-nowhere"
        assert by_name["archived"]["action"] is None


class TestHookPathsStayOffline:
    def test_inventory_without_a_listing_never_runs_ls_remote(
        self, scratch: archive_remote.ArchiveRepo
    ) -> None:
        seen: list[tuple[str, ...]] = []
        watcher = _watching(seen.append)
        with (
            patch.object(branch_inventory, "run_git", watcher),
            patch.object(branch_safety, "run_git", watcher),
            patch.object(remote_refs, "run_git", watcher),
        ):
            inventory = build_inventory(scratch.clone, _CONFIG, now=NOW)
            branch_sweep.session_summary(inventory, _CONFIG, cap=5, new_session=True)
        assert seen, "the watcher saw no git call, so the test proves nothing"
        assert all("ls-remote" not in args for args in seen)
        assert inventory.records["archived"].containment == Containment.NOWHERE


class TestDeleteBranchRemoteProof:
    def test_unproven_without_a_listing(self, scratch: archive_remote.ArchiveRepo) -> None:
        verdict = branch_safety.classify_branch(scratch.clone, "archived")
        assert verdict.tier == TIER_UNPROVEN

    def test_equal_sha_is_a_remote_held_proof(self, scratch: archive_remote.ArchiveRepo) -> None:
        verdict = branch_safety.classify_branch(
            scratch.clone, "archived", remote_listing=_listing(scratch)
        )
        assert verdict.tier == TIER_REMOTE_HELD
        assert verdict.is_safe
        assert verdict.held_by == "origin: refs/archive/archived"
        assert "refs/archive/archived" in verdict.detail

    def test_descendant_is_a_remote_held_proof(self, scratch: archive_remote.ArchiveRepo) -> None:
        verdict = branch_safety.classify_branch(
            scratch.clone, "archived-child", remote_listing=_listing(scratch)
        )
        assert verdict.tier == TIER_REMOTE_HELD
        assert verdict.held_by == "origin: refs/archive/kid-above"

    def test_unheld_branch_stays_unproven(self, scratch: archive_remote.ArchiveRepo) -> None:
        verdict = branch_safety.classify_branch(
            scratch.clone, "unpushed", remote_listing=_listing(scratch)
        )
        assert verdict.tier == TIER_UNPROVEN

    def test_failed_listing_is_not_proof_and_is_named(
        self, scratch: archive_remote.ArchiveRepo
    ) -> None:
        failed = remote_refs.RemoteRefs("origin", (), failure="timed out")
        verdict = branch_safety.classify_branch(scratch.clone, "archived", remote_listing=failed)
        assert verdict.tier == TIER_UNPROVEN
        assert "remote could not be checked" in verdict.detail

    def test_delete_removes_the_branches_with_one_ls_remote(
        self, scratch: archive_remote.ArchiveRepo
    ) -> None:
        seen: list[tuple[str, ...]] = []
        with patch.object(remote_refs, "run_git", _watching(seen.append)):
            report = branch_safety.delete_branches(
                scratch.clone, ["archived", "archived-child"], remote="origin"
            )
        assert not report.refused, report.blockers
        assert set(report.deleted) == {"archived", "archived-child"}
        assert sum(1 for args in seen if args[0] == "ls-remote") == 1
        remaining = subprocess.run(
            ["git", "-C", str(scratch.clone), "branch", "--list", "archived*"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        assert remaining.strip() == ""

    def test_a_batch_with_an_unheld_branch_deletes_nothing(
        self, scratch: archive_remote.ArchiveRepo
    ) -> None:
        report = branch_safety.delete_branches(
            scratch.clone, ["archived", "unpushed"], remote="origin"
        )
        assert report.refused
        assert report.deleted == ()

    def test_no_remote_means_no_network(self, scratch: archive_remote.ArchiveRepo) -> None:
        with patch.object(remote_refs, "run_git", side_effect=AssertionError("network")):
            report = branch_safety.delete_branches(scratch.clone, ["archived"])
        assert report.refused


class TestRemoteListingIsLazy:
    def test_a_merged_branch_delete_makes_no_network_call(
        self, scratch: archive_remote.ArchiveRepo
    ) -> None:
        archive_remote.git(scratch.clone, "branch", "merged-already", "main")
        seen: list[tuple[str, ...]] = []
        with patch.object(remote_refs, "run_git", _watching(seen.append)):
            report = branch_safety.delete_branches(
                scratch.clone, ["merged-already"], remote="origin"
            )
        assert not report.refused, report.blockers
        assert not any(args[0] == "ls-remote" for args in seen)

    def test_a_sweep_with_the_lazy_source_asks_the_remote_once(
        self, scratch: archive_remote.ArchiveRepo
    ) -> None:
        seen: list[tuple[str, ...]] = []
        with patch.object(remote_refs, "run_git", _watching(seen.append)):
            inventory = build_inventory(
                scratch.clone,
                _CONFIG,
                now=NOW,
                remote_refs=remote_refs.LazyRemoteRefs(scratch.clone, "origin"),
            )
        assert sum(1 for args in seen if args[0] == "ls-remote") == 1
        assert inventory.remote_refs is not None
        assert inventory.records["archived"].containment == Containment.REMOTE_UNFETCHED

    def test_a_sweep_with_nothing_nowhere_never_asks(self, tmp_path: Path) -> None:
        repo = archive_remote.build(tmp_path)
        for branch in ("archived", "archived-child", "unpushed"):
            archive_remote.git(repo.clone, "branch", "-q", "-D", branch)
        seen: list[tuple[str, ...]] = []
        with patch.object(remote_refs, "run_git", _watching(seen.append)):
            inventory = build_inventory(
                repo.clone,
                _CONFIG,
                now=NOW,
                remote_refs=remote_refs.LazyRemoteRefs(repo.clone, "origin"),
            )
        assert not seen
        assert inventory.remote_refs is None
