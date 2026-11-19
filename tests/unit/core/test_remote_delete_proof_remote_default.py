"""Plan 00626: the remote-delete proof's cherry route, and the REMOTE default only.

Defect 1: a branch whose every commit's patch is in the default (cherry-picks the
default interleaved with its own edits, plus park and unpark markers) was refused,
because no single default commit held the whole net change. The cherry route now
proves it, but only when every changed path is held at its EXACT blob by some
first-parent commit of the default after the merge base.

Defect 2: a remote delete was proven against the LOCAL default branch, so a branch
merged only into an unpushed local default was deletable on the remote. The proof
now judges the remote-tracking default alone, confirmed equal to the remote's live
default tip, and never rests on a cached positive.

The default branch is named ``trunk`` throughout: nothing may assume ``main``.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.config.models import BranchesConfig
from claude_code_hooks_daemon.core.branch_inventory import (
    CACHE_RELATIVE_PATH,
    merge_proof_key,
)
from claude_code_hooks_daemon.core.remote_branch_proof import prove_remote_merged
from claude_code_hooks_daemon.daemon.branch_safety import (
    TIER_CONTENT_PRESERVED,
    TIER_PATCH_EQUIVALENT,
)
from claude_code_hooks_daemon.handlers.pre_tool_use.destructive_git import (
    DestructiveGitHandler,
)

_DEFAULT = "trunk"
_CONFIG = BranchesConfig(default=_DEFAULT)
_ENV = {
    "GIT_AUTHOR_NAME": "Test Author",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "Test Author",
    "GIT_COMMITTER_EMAIL": "test@example.com",
    "PATH": "/usr/bin:/bin",
}
_PARK = "Park branch: waiting\n\nParked-Reason: waiting\nParked-By: tester\n"
_UNPARK = "Unpark branch\n\nUnparked: tester\n"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        env={**_ENV, "HOME": str(repo)},
    ).stdout.strip()


def _write(repo: Path, name: str, text: str, message: str) -> str:
    (repo / name).write_text(text, encoding="utf-8")
    _git(repo, "add", name)
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    bare = tmp_path / "remote.git"
    _git(tmp_path, "init", "--quiet", "--bare", "-b", _DEFAULT, str(bare))
    path = tmp_path / "repo"
    path.mkdir()
    _git(path, "init", "-q", "-b", _DEFAULT)
    _write(path, "a.txt", "a0\n", "init a")
    _write(path, "b.txt", "b0\n", "init b")
    _git(path, "remote", "add", "origin", str(bare))
    _git(path, "push", "--quiet", "-u", "origin", _DEFAULT)
    # What a clone records: the guard's `branches.default: auto` reads the default here.
    _git(path, "remote", "set-head", "origin", "--auto")
    return path


def _publish(repo: Path) -> None:
    _git(repo, "push", "--quiet", "origin", _DEFAULT)
    _git(repo, "fetch", "--quiet", "origin")


def _branch_with_markers(repo: Path, name: str) -> tuple[str, str]:
    """Push ``name``: one commit on a.txt, one on b.txt, then a park and an unpark marker."""
    _git(repo, "checkout", "-q", "-b", name, _DEFAULT)
    first = _write(repo, "a.txt", "a0\na1\n", "feat a")
    second = _write(repo, "b.txt", "b0\nb1\n", "feat b")
    _git(repo, "commit", "-q", "--allow-empty", "-m", _PARK)
    _git(repo, "commit", "-q", "--allow-empty", "-m", _UNPARK)
    _git(repo, "push", "--quiet", "origin", name)
    _git(repo, "checkout", "-q", _DEFAULT)
    _write(repo, "c.txt", "c0\n", "the default moves on")
    return first, second


def _prove(repo: Path, name: str) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    proof = prove_remote_merged(repo, "origin", [name], _DEFAULT, _CONFIG)
    return proof.tips, proof.problems, proof.evidence


def _guard(repo: Path, command: str, *, by_proof: bool = True) -> str:
    """The guard's decision; with ``by_proof`` a deny must be the proof's, not setup's."""
    hook_input = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(repo)}
    result = DestructiveGitHandler().handle(hook_input)
    if result.decision == "deny" and by_proof:
        assert "Not deleted:" in str(result.reason)
    return str(result.decision)


class TestCherryRoute:
    def test_interleaved_cherry_picks_with_park_markers_are_proven(self, repo: Path) -> None:
        first, second = _branch_with_markers(repo, "feat")
        _git(repo, "commit", "-q", "--allow-empty", "-m", "an empty commit on the default")
        _git(repo, "cherry-pick", first)
        _write(repo, "a.txt", "a0\na1\na2\n", "the default edits a between the picks")
        _git(repo, "cherry-pick", second)
        _publish(repo)
        tips, problems, evidence = _prove(repo, "feat")
        assert problems == {}
        assert list(tips) == ["feat"]
        assert evidence == {"feat": TIER_PATCH_EQUIVALENT}

    def test_the_guard_allows_the_reported_delete(self, repo: Path) -> None:
        first, second = _branch_with_markers(repo, "feat")
        _git(repo, "cherry-pick", first)
        _write(repo, "a.txt", "a0\na1\na2\n", "the default edits a between the picks")
        _git(repo, "cherry-pick", second)
        _publish(repo)
        assert _guard(repo, "git push origin --delete feat") == "allow"

    def test_a_whitespace_only_difference_is_not_proven_by_patch_id(self, repo: Path) -> None:
        # Patch-ids ignore whitespace, so git cherry marks the commit '-'; the exact
        # blob the branch wrote is held by no commit of the default.
        _git(repo, "checkout", "-q", "-b", "ws", _DEFAULT)
        _write(repo, "a.txt", "a0\n  a1\n", "indent with spaces")
        _git(repo, "push", "--quiet", "origin", "ws")
        _git(repo, "checkout", "-q", _DEFAULT)
        _write(repo, "c.txt", "c0\n", "the default moves on")
        _write(repo, "a.txt", "a0\n\ta1\n", "indent with a tab")
        _publish(repo)
        assert _git(repo, "cherry", f"origin/{_DEFAULT}", "origin/ws").startswith("-")
        tips, problems, _evidence = _prove(repo, "ws")
        assert tips == {}
        assert "not merged" in problems["ws"]

    def test_a_branch_with_no_merge_base_is_not_proven_by_patch_id(self, repo: Path) -> None:
        # An unrelated history whose only patch the default also has: git cherry with no
        # merge base matches against the whole history, so it is never a proof.
        _git(repo, "checkout", "-q", "--orphan", "orphan")
        _git(repo, "rm", "-q", "-rf", ".")
        _write(repo, "a.txt", "a0\n", "init a, unrelated history")
        _git(repo, "push", "--quiet", "origin", "orphan")
        _git(repo, "checkout", "-q", "-f", _DEFAULT)
        _publish(repo)
        tips, problems, _evidence = _prove(repo, "orphan")
        assert tips == {}
        assert "orphan" in problems

    def test_a_path_the_default_never_held_at_that_blob_is_unproven(self, repo: Path) -> None:
        # Two commits, the second rewrites a.txt; the default takes the first by
        # cherry-pick and only a whitespace-equal version of the second.
        _git(repo, "checkout", "-q", "-b", "two", _DEFAULT)
        first = _write(repo, "a.txt", "a0\na1\n", "first")
        _write(repo, "a.txt", "a0\na1\n  a2\n", "second")
        _git(repo, "push", "--quiet", "origin", "two")
        _git(repo, "checkout", "-q", _DEFAULT)
        _write(repo, "c.txt", "c0\n", "the default moves on")
        _git(repo, "cherry-pick", first)
        _write(repo, "a.txt", "a0\na1\n\ta2\n", "second, re-indented")
        _publish(repo)
        tips, _problems, _evidence = _prove(repo, "two")
        assert tips == {}


class TestRemoteDefaultOnly:
    def test_a_branch_merged_only_into_the_unpushed_local_default_is_refused(
        self, repo: Path
    ) -> None:
        _git(repo, "checkout", "-q", "-b", "release-ci", _DEFAULT)
        _write(repo, "a.txt", "a0\nrelease\n", "release work")
        _git(repo, "push", "--quiet", "origin", "release-ci")
        _git(repo, "checkout", "-q", _DEFAULT)
        _git(repo, "merge", "-q", "--ff-only", "release-ci")
        _git(repo, "fetch", "--quiet", "origin")
        tips, problems, _evidence = _prove(repo, "release-ci")
        assert tips == {}
        assert "release-ci" in problems
        assert _guard(repo, "git push origin --delete release-ci") == "deny"

    def test_a_squash_only_on_the_unpushed_local_default_is_refused(self, repo: Path) -> None:
        _git(repo, "checkout", "-q", "-b", "sq", _DEFAULT)
        _write(repo, "a.txt", "a0\nsq\n", "squash me")
        _git(repo, "push", "--quiet", "origin", "sq")
        _git(repo, "checkout", "-q", _DEFAULT)
        _git(repo, "merge", "--squash", "-q", "sq")
        _git(repo, "commit", "-q", "-m", "squash, not pushed")
        tips, problems, _evidence = _prove(repo, "sq")
        assert tips == {}
        assert "sq" in problems

    def test_a_tracking_default_moved_locally_past_the_remote_is_refused(self, repo: Path) -> None:
        # update-ref makes the tracking ref claim what the remote never received.
        _git(repo, "checkout", "-q", "-b", "moved", _DEFAULT)
        _write(repo, "a.txt", "a0\nmoved\n", "work")
        _git(repo, "push", "--quiet", "origin", "moved")
        _git(repo, "checkout", "-q", _DEFAULT)
        _git(repo, "merge", "-q", "--ff-only", "moved")
        _git(repo, "update-ref", f"refs/remotes/origin/{_DEFAULT}", "HEAD")
        tips, problems, _evidence = _prove(repo, "moved")
        assert tips == {}
        assert "fetch" in problems["moved"]

    def test_a_missing_tracking_default_is_refused(self, repo: Path) -> None:
        _git(repo, "checkout", "-q", "-b", "done", _DEFAULT)
        _git(repo, "push", "--quiet", "origin", "done")
        _git(repo, "checkout", "-q", _DEFAULT)
        _git(repo, "fetch", "--quiet", "origin")
        _git(repo, "update-ref", "-d", f"refs/remotes/origin/{_DEFAULT}")
        tips, problems, _evidence = _prove(repo, "done")
        assert tips == {}
        assert "done" in problems

    def test_a_merge_pushed_to_the_remote_default_is_still_proven(self, repo: Path) -> None:
        _git(repo, "checkout", "-q", "-b", "landed", _DEFAULT)
        _write(repo, "a.txt", "a0\nlanded\n", "work")
        _git(repo, "push", "--quiet", "origin", "landed")
        _git(repo, "checkout", "-q", _DEFAULT)
        _git(repo, "merge", "-q", "--ff-only", "landed")
        _publish(repo)
        tips, problems, _evidence = _prove(repo, "landed")
        assert problems == {}
        assert list(tips) == ["landed"]


class TestRemoteDefaultDetection:
    def test_auto_never_takes_a_stale_local_main_for_the_remote_default(self, repo: Path) -> None:
        # The remote's default is trunk; an old `main` survives locally and on the remote,
        # and origin/HEAD is unset. Work merged into `main` only is NOT on the default.
        _git(repo, "checkout", "-q", "-b", "main", _DEFAULT)
        _git(repo, "checkout", "-q", "-b", "old-work", "main")
        _write(repo, "a.txt", "a0\nold work\n", "work merged into the old main only")
        _git(repo, "push", "--quiet", "origin", "old-work")
        _git(repo, "checkout", "-q", "main")
        _git(repo, "merge", "-q", "--ff-only", "old-work")
        _git(repo, "push", "--quiet", "origin", "main")
        _git(repo, "checkout", "-q", _DEFAULT)
        _git(repo, "remote", "set-head", "origin", "-d")
        _git(repo, "fetch", "--quiet", "origin")
        assert _guard(repo, "git push origin --delete old-work", by_proof=False) == "deny"
        # Every caller of the one proof is held to it, not only the guard: a sweep that
        # resolved `main` through the local fallback is refused by the proof itself.
        proof = prove_remote_merged(repo, "origin", ["old-work"], "main", BranchesConfig())
        assert proof.tips == {}
        assert "not confirmed" in proof.problems["old-work"]

    def test_auto_reads_the_remote_head_when_it_names_a_non_main_default(
        self, repo: Path
    ) -> None:
        _git(repo, "checkout", "-q", "-b", "landed", _DEFAULT)
        _write(repo, "a.txt", "a0\nlanded\n", "work")
        _git(repo, "push", "--quiet", "origin", "landed")
        _git(repo, "checkout", "-q", _DEFAULT)
        _git(repo, "merge", "-q", "--ff-only", "landed")
        _publish(repo)
        proof = prove_remote_merged(repo, "origin", ["landed"], _DEFAULT, BranchesConfig())
        assert list(proof.tips) == ["landed"]


class TestCacheIsNeverAProof:
    def test_a_forged_positive_cache_entry_does_not_prove_an_unmerged_branch(
        self, repo: Path
    ) -> None:
        _git(repo, "checkout", "-q", "-b", "open", _DEFAULT)
        _write(repo, "a.txt", "a0\nopen work\n", "unmerged work")
        _git(repo, "push", "--quiet", "origin", "open")
        _git(repo, "checkout", "-q", _DEFAULT)
        _git(repo, "fetch", "--quiet", "origin")
        tip = _git(repo, "rev-parse", "refs/remotes/origin/open")
        default_tip = _git(repo, "rev-parse", f"refs/remotes/origin/{_DEFAULT}")
        cache = repo / CACHE_RELATIVE_PATH
        cache.parent.mkdir(parents=True, exist_ok=True)
        forged = {merge_proof_key(tip, [default_tip]): TIER_CONTENT_PRESERVED}
        cache.write_text(json.dumps({"version": 5, "proofs": forged}), encoding="utf-8")
        tips, problems, _evidence = _prove(repo, "open")
        assert tips == {}
        assert "open" in problems
        assert _guard(repo, "git push origin --delete open") == "deny"
