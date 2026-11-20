"""A branch left with only empty park commits over merged work stays deletable (Plan 00617).

The one classifier (``branch_park.is_park_residue``) says a branch is merged-equivalent
only when EVERY commit the default branch lacks is a park commit the park writer wrote
(its exact message shape) AND is tree-identical to its single parent. The sweep, the
creation guard, the delete-branch guard and ``R-GIT-PUSH-DELETE-REMOTE`` all ask it,
so they cannot disagree. Every twin that carries content, or is not provably a park
commit, stays refused. Synthetic repositories with a bare remote throughout.
"""

from __future__ import annotations

import subprocess
from collections.abc import Mapping
from pathlib import Path

import pytest

from claude_code_hooks_daemon.config.models import BranchesConfig
from claude_code_hooks_daemon.core import (
    branch_cleanup,
    branch_creation,
    branch_inventory,
    branch_park,
)
from claude_code_hooks_daemon.core.branch_inventory import BranchState, Pool
from claude_code_hooks_daemon.core.branch_park import is_park_residue, park_branch
from claude_code_hooks_daemon.core.remote_branch_proof import prove_remote_merged
from claude_code_hooks_daemon.daemon import branch_safety
from claude_code_hooks_daemon.handlers.pre_tool_use.destructive_git import _remote_delete_note
from tests.conftest import HERMETIC_GIT_EMAIL
from tests.support.git_fixtures import git_setup_timeout

_WRITER_MESSAGE = "Park branch: waiting\n\nParked-Reason: waiting\nParked-By: t\n"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    bare = tmp_path / "remote.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(bare))
    path = tmp_path / "repo"
    path.mkdir()
    _git(path, "init", "-q", "-b", "main")
    _git(path, "config", "user.email", HERMETIC_GIT_EMAIL)
    _git(path, "config", "user.name", "t")
    _write(path, "base.txt", "base\n", "base")
    _git(path, "remote", "add", "origin", str(bare))
    _git(path, "push", "-q", "origin", "main")
    _git(path, "remote", "set-head", "origin", "main")
    return path


def _config() -> BranchesConfig:
    return BranchesConfig(default="main")


def _write(repo: Path, filename: str, text: str, message: str) -> None:
    (repo / filename).write_text(text, encoding="utf-8")
    _git(repo, "add", filename)
    _git(repo, "commit", "-q", "-m", message)


def _work(repo: Path, name: str) -> None:
    """``name`` with one commit of its own, pushed; main checked out."""
    _git(repo, "checkout", "-q", "-b", name, "main")
    _write(repo, f"{name}.txt", f"{name}\n", f"work {name}")
    _git(repo, "push", "-q", "-u", "origin", name)
    _git(repo, "checkout", "-q", "main")


def _merge(repo: Path, name: str, *, squash: bool = False) -> None:
    if squash:
        _git(repo, "merge", "--squash", "-q", name)
        _git(repo, "commit", "-q", "-m", f"squash {name}")
    else:
        _git(repo, "merge", "--no-ff", "-q", "-m", f"Merge {name}", name)
    _git(repo, "push", "-q", "origin", "main")


def _park(repo: Path, name: str, reason: str = "merged; waiting on the release") -> None:
    """Park ``name`` with the real park writer (commit and push)."""
    result = park_branch(repo, name, reason=reason, remote="origin")
    assert result.pushed, result.push_error


def _unpark(repo: Path, name: str) -> None:
    result = park_branch(repo, name, reason=None, remote="origin", clear=True)
    assert result.pushed, result.push_error


def _commit_on(repo: Path, name: str, message: str, *, parents: list[str], tree: str) -> str:
    """Write a commit by hand with ``message`` and move ``name`` to it, then push."""
    args = ["commit-tree", tree, "-m", message]
    for parent in parents:
        args += ["-p", parent]
    sha = _git(repo, *args)
    _git(repo, "update-ref", f"refs/heads/{name}", sha)
    _git(repo, "push", "-q", "-f", "origin", f"{name}:refs/heads/{name}")
    return sha


def _drop_local(repo: Path, name: str) -> None:
    _git(repo, "branch", "-q", "-D", name)


def _fetch(repo: Path) -> None:
    _git(repo, "fetch", "-q", "--prune", "origin")


def _remote_tip(repo: Path, name: str) -> str:
    return _git(repo, "rev-parse", f"refs/remotes/origin/{name}")


def _guard_allows(repo: Path, name: str) -> bool:
    return _remote_delete_note(f"git push origin --delete {name}", repo, _config()) is None


def _creation_pool(repo: Path, name: str) -> Pool | None:
    for pool, works in branch_creation.work_pools(repo, _config()).items():
        if any(name in work.names for work in works):
            return pool
    return None


# --- the writer's message and the walk's failure modes ---------------------------------


class TestParkMessage:
    @pytest.mark.parametrize(
        "message",
        [
            _WRITER_MESSAGE,
            "Unpark branch\n\nUnparked: t\n",
            "Park branch: a: b\n\nParked-Reason: a: b\nParked-By: some one\n",
        ],
    )
    def test_the_writers_own_text_is_a_park_message(self, message: str) -> None:
        assert branch_park.is_park_message(message)

    @pytest.mark.parametrize(
        "message",
        [
            "Park\n\nParked-Reason: waiting\nParked-By: t\n",
            "Park branch: waiting\n\nParked-Reason: other\nParked-By: t\n",
            "Park branch: waiting\n\nParked-Reason: waiting\nExtra: x\nParked-By: t\n",
            "Park branch: waiting\nParked-Reason: waiting\nParked-By: t\n",
            "Unpark branch\n\nsomething else\nUnparked: t\n",
            "Unrelated\n\nParked-Reason: waiting\nParked-By: t\n",
            "",
        ],
    )
    def test_any_other_text_is_not(self, message: str) -> None:
        assert not branch_park.is_park_message(message)


class TestWalkFailsClosed:
    def _fail(self, monkeypatch: pytest.MonkeyPatch, *, on: str, stdout: str, code: int) -> None:
        real = branch_park.run_git

        def fake(
            repo: Path,
            *args: str,
            timeout: float = git_setup_timeout(),
            env: Mapping[str, str] | None = None,
        ) -> subprocess.CompletedProcess[str]:
            if on in args:
                return subprocess.CompletedProcess(list(args), code, stdout, "")
            return real(repo, *args, timeout=timeout, env=env)

        monkeypatch.setattr(branch_park, "run_git", fake)

    @pytest.fixture
    def parked(self, repo: Path) -> Path:
        _work(repo, "feat")
        _merge(repo, "feat")
        _park(repo, "feat")
        return repo

    def test_a_failed_walk_is_none(self, parked: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self._fail(monkeypatch, on="--boundary", stdout="", code=128)
        assert (
            branch_park.walk_park_range(parked, "main", "feat", timeout=git_setup_timeout()) is None
        )
        assert not is_park_residue(parked, "feat", "main")

    def test_a_malformed_walk_line_is_none(
        self, parked: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._fail(monkeypatch, on="--boundary", stdout="only\x1ftwo\n", code=0)
        assert (
            branch_park.walk_park_range(parked, "main", "feat", timeout=git_setup_timeout()) is None
        )

    def test_a_failed_message_read_is_none(
        self, parked: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._fail(monkeypatch, on="--no-walk=unsorted", stdout="", code=128)
        assert (
            branch_park.walk_park_range(parked, "main", "feat", timeout=git_setup_timeout()) is None
        )

    def test_a_message_record_for_another_sha_is_none(
        self, parked: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        forged = f"{'0' * 40}\n{_WRITER_MESSAGE}\0"
        self._fail(monkeypatch, on="--no-walk=unsorted", stdout=forged, code=0)
        assert (
            branch_park.walk_park_range(parked, "main", "feat", timeout=git_setup_timeout()) is None
        )

    def test_an_extra_message_record_is_none(
        self, parked: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        tip = _git(parked, "rev-parse", "feat")
        extra = f"{tip}\n{_WRITER_MESSAGE}\0{tip}\n{_WRITER_MESSAGE}\0"
        self._fail(monkeypatch, on="--no-walk=unsorted", stdout=extra, code=0)
        assert (
            branch_park.walk_park_range(parked, "main", "feat", timeout=git_setup_timeout()) is None
        )

    def test_a_failed_tip_listing_marks_nothing(
        self, parked: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._fail(monkeypatch, on="for-each-ref", stdout="", code=128)
        marked = branch_park.park_marked_refs(
            parked, ["refs/heads/feat"], timeout=git_setup_timeout()
        )
        assert marked == set()

    def test_no_refs_marks_nothing(self, parked: Path) -> None:
        assert branch_park.park_marked_refs(parked, [], timeout=git_setup_timeout()) == set()


# --- the deletable shapes ---------------------------------------------------------------


class TestParkOnlyBranchIsMergedEquivalent:
    """PIN (Plan 00594 already accepts the remote copy of a writer park)."""

    def test_writer_park_over_merged_work_is_residue_and_remote_deletable(self, repo: Path) -> None:
        _work(repo, "feat")
        _merge(repo, "feat")
        _park(repo, "feat")
        _drop_local(repo, "feat")
        _fetch(repo)
        assert is_park_residue(repo, _remote_tip(repo, "feat"), "main")
        proof = prove_remote_merged(repo, "origin", ["feat"], "main", _config())
        assert proof.evidence == {"feat": "park-carried"}, proof.problems
        assert _guard_allows(repo, "feat")


class TestUnparkedTip:
    """RED: a park then an unpark leaves only writer commits; every consumer must agree."""

    @pytest.fixture
    def unparked(self, repo: Path) -> Path:
        _work(repo, "feat")
        _merge(repo, "feat")
        _park(repo, "feat")
        _unpark(repo, "feat")
        _drop_local(repo, "feat")
        _fetch(repo)
        return repo

    def test_the_inventory_calls_it_park_carried(self, unparked: Path) -> None:
        inventory = branch_inventory.build_inventory(unparked, _config())
        assert inventory.records["feat"].state == BranchState.PARK_CARRIED

    def test_the_remote_delete_proof_accepts_it(self, unparked: Path) -> None:
        proof = prove_remote_merged(unparked, "origin", ["feat"], "main", _config())
        assert proof.evidence == {"feat": "park-carried"}, proof.problems
        assert _guard_allows(unparked, "feat")

    def test_the_creation_guard_counts_it_in_no_pool(self, unparked: Path) -> None:
        assert _creation_pool(unparked, "feat") is None

    def test_clean_remote_deletes_it(self, unparked: Path) -> None:
        report = branch_cleanup.clean_sweep(unparked, _config(), dry_run=False, remote=True)
        assert report.deleted_remote == ("origin/feat",), report.skipped
        assert any(":refs/heads/feat" in line for line in report.commands)


class TestLocalCopy:
    """RED: the delete-branch guard and ``--clean`` must accept the LOCAL park-only copy."""

    def test_the_delete_branch_guard_proves_a_park_carried_tier(self, repo: Path) -> None:
        _work(repo, "feat")
        _merge(repo, "feat")
        _park(repo, "feat")
        verdict = branch_safety.classify_branch(repo, "feat", content_tier=False)
        assert verdict.tier == branch_safety.TIER_PARK_CARRIED
        assert verdict.is_safe

    def test_delete_branch_deletes_it_with_a_restore_line(self, repo: Path) -> None:
        _work(repo, "feat")
        _merge(repo, "feat")
        _park(repo, "feat")
        tip = _git(repo, "rev-parse", "feat")
        report = branch_safety.delete_branches(repo, ["feat"], content_tier=False)
        assert report.deleted == ("feat",), report.blockers
        assert report.classifications[0].tier == branch_safety.TIER_PARK_CARRIED
        assert report.restore_commands == (f"git branch feat {tip}",)

    def test_clean_deletes_the_local_and_remote_copy_with_restore_lines(self, repo: Path) -> None:
        _work(repo, "feat")
        _merge(repo, "feat")
        _park(repo, "feat")
        _fetch(repo)
        tip = _git(repo, "rev-parse", "feat")
        report = branch_cleanup.clean_sweep(repo, _config(), dry_run=False, remote=True)
        assert report.deleted == ("feat",), report.skipped
        assert report.deleted_remote == ("origin/feat",), report.skipped
        assert f"git branch feat {tip}" in report.commands
        assert f"git push origin {tip}:refs/heads/feat" in report.commands

    def test_a_squash_merged_branch_parked_after_is_patch_equivalent_locally(
        self, repo: Path
    ) -> None:
        _work(repo, "feat")
        _merge(repo, "feat", squash=True)
        _park(repo, "feat")
        verdict = branch_safety.classify_branch(repo, "feat", content_tier=False)
        assert verdict.tier == branch_safety.TIER_PATCH_EQUIVALENT
        # PIN: the park classifier itself is narrow; the real commit is not a park commit.
        assert not is_park_residue(repo, _git(repo, "rev-parse", "feat"), "main")


# --- the twins that must stay refused ---------------------------------------------------


class TestTwinsStayRefused:
    """A tree change, or any commit not provably the writer's park, keeps the branch unmerged."""

    def _assert_refused(self, repo: Path, name: str) -> None:
        _fetch(repo)
        tip = _remote_tip(repo, name)
        assert not is_park_residue(repo, tip, "main")
        proof = prove_remote_merged(repo, "origin", [name], "main", _config())
        assert name not in proof.tips
        assert not _guard_allows(repo, name)
        inventory = branch_inventory.build_inventory(repo, _config())
        assert inventory.records[name].state != BranchState.PARK_CARRIED
        if name in branch_safety.local_branches(repo):
            verdict = branch_safety.classify_branch(repo, name, content_tier=False)
            assert not verdict.is_safe, verdict.tier

    def test_park_looking_commit_that_changes_a_file(self, repo: Path) -> None:
        """PIN: the writer's exact message on a commit that adds content."""
        _work(repo, "feat")
        _merge(repo, "feat")
        _git(repo, "checkout", "-q", "feat")
        (repo / "extra.txt").write_text("unmerged\n", encoding="utf-8")
        _git(repo, "add", "extra.txt")
        _git(repo, "commit", "-q", "-m", _WRITER_MESSAGE)
        _git(repo, "push", "-q", "origin", "feat")
        _git(repo, "checkout", "-q", "main")
        self._assert_refused(repo, "feat")

    def test_real_commit_under_park_commits(self, repo: Path) -> None:
        """PIN: unmerged work, then two writer parks on top."""
        _work(repo, "feat")
        _park(repo, "feat", "first")
        _park(repo, "feat", "second")
        self._assert_refused(repo, "feat")

    def test_forged_park_message_on_a_non_empty_commit(self, repo: Path) -> None:
        """PIN: writer-shaped message, tree differs from its parent."""
        _work(repo, "feat")
        _merge(repo, "feat")
        _git(repo, "checkout", "-q", "-b", "scratch", "feat")
        _write(repo, "forged.txt", "content\n", "scratch content")
        tree = _git(repo, "rev-parse", "HEAD^{tree}")
        _git(repo, "checkout", "-q", "main")
        parent = _git(repo, "rev-parse", "feat")
        _commit_on(repo, "feat", _WRITER_MESSAGE, parents=[parent], tree=tree)
        _drop_local(repo, "scratch")
        self._assert_refused(repo, "feat")

    def test_park_whose_parent_is_another_branchs_unmerged_commit(self, repo: Path) -> None:
        """PIN: the park's parent is not the branch's merged work."""
        _work(repo, "feat")
        _merge(repo, "feat")
        _work(repo, "other")
        other = _git(repo, "rev-parse", "other")
        _commit_on(
            repo,
            "feat",
            _WRITER_MESSAGE,
            parents=[other],
            tree=_git(repo, "rev-parse", "other^{tree}"),
        )
        _drop_local(repo, "other")
        _git(repo, "push", "-q", "origin", "--delete", "other")
        self._assert_refused(repo, "feat")

    def test_parentless_park(self, repo: Path) -> None:
        """PIN: a root commit with the writer's message and main's tree."""
        _work(repo, "feat")
        _merge(repo, "feat")
        _commit_on(
            repo, "feat", _WRITER_MESSAGE, parents=[], tree=_git(repo, "rev-parse", "main^{tree}")
        )
        self._assert_refused(repo, "feat")

    def test_two_parent_park(self, repo: Path) -> None:
        """PIN: a 'park' that merges in another unmerged branch."""
        _work(repo, "feat")
        _merge(repo, "feat")
        _work(repo, "other")
        _commit_on(
            repo,
            "feat",
            _WRITER_MESSAGE,
            parents=[_git(repo, "rev-parse", "feat"), _git(repo, "rev-parse", "other")],
            tree=_git(repo, "rev-parse", "feat^{tree}"),
        )
        _drop_local(repo, "other")
        _git(repo, "push", "-q", "origin", "--delete", "other")
        self._assert_refused(repo, "feat")


class TestNonWriterEmptyCommit:
    def test_empty_trailer_commit_not_written_by_the_park_writer(self, repo: Path) -> None:
        """An empty commit carrying Parked-* trailers but not the writer's message.

        It is not a park (the inventory never calls it park-carried), but it changes no
        file, so the delete proofs accept it as ``empty-commits-only`` (Plan 00622): a
        delete loses only its message.
        """
        _work(repo, "feat")
        _merge(repo, "feat")
        _git(repo, "checkout", "-q", "feat")
        _git(
            repo,
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "Unrelated note",
            "--trailer",
            "Parked-Reason: waiting",
            "--trailer",
            "Parked-By: t",
        )
        _git(repo, "push", "-q", "origin", "feat")
        _git(repo, "checkout", "-q", "main")
        _fetch(repo)
        assert not is_park_residue(repo, _remote_tip(repo, "feat"), "main")
        inventory = branch_inventory.build_inventory(repo, _config())
        assert inventory.records["feat"].state != BranchState.PARK_CARRIED
        proof = prove_remote_merged(repo, "origin", ["feat"], "main", _config())
        assert proof.evidence == {"feat": branch_safety.TIER_EMPTY_COMMITS_ONLY}
        assert _guard_allows(repo, "feat")
        verdict = branch_safety.classify_branch(repo, "feat", content_tier=False)
        assert verdict.tier == branch_safety.TIER_EMPTY_COMMITS_ONLY
