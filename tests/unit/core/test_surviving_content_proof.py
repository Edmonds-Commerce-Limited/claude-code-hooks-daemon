"""The surviving-content tier of the remote-delete proof (Plan 00594 follow-up).

A remote branch the default never merged may still hold nothing unique: every file
it adds or changes already has the same mode and blob at the SAME path on the
default's tip or a declared integration line's remote tip. Real repositories with a
bare remote. The deleting agent's own claim is never an input.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.config.models import BranchesConfig
from claude_code_hooks_daemon.core.branch_inventory import read_merge_proofs
from claude_code_hooks_daemon.core.remote_branch_proof import (
    MAX_PROOF_PATHS,
    RemoteProof,
    prove_remote_merged,
)
from claude_code_hooks_daemon.daemon.branch_safety import (
    TIER_CONTENT_PRESERVED,
    TIER_MERGED,
    TIER_SURVIVING_CONTENT,
)

_ENV = {
    "GIT_AUTHOR_NAME": "Test Author",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "Test Author",
    "GIT_COMMITTER_EMAIL": "test@example.com",
    "PATH": "/usr/bin:/bin",
}
_CONFIG = BranchesConfig(default="main", integration_lines=["release/*"])


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        env={**_ENV, "HOME": str(repo)},
    ).stdout


def _write(repo: Path, name: str, content: str | bytes) -> None:
    path = repo / name
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    _git(repo, "add", name)


def _commit(repo: Path, message: str = "change") -> None:
    _git(repo, "commit", "-q", "-m", message)


def _land(repo: Path, name: str, content: str | bytes, message: str = "land") -> None:
    """Commit ``name`` on main and publish it (not the branch's own commit)."""
    _write(repo, name, content)
    _commit(repo, message)
    _git(repo, "push", "--quiet", "origin", "main")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    bare = tmp_path / "remote.git"
    _git(tmp_path, "init", "--quiet", "--bare", "-b", "main", str(bare))
    path = tmp_path / "repo"
    path.mkdir()
    _git(path, "init", "-q", "-b", "main")
    _write(path, "base.txt", "base\n")
    _commit(path, "base")
    _git(path, "remote", "add", "origin", str(bare))
    _git(path, "push", "--quiet", "origin", "main")
    return path


def _branch_from_main(repo: Path, name: str) -> None:
    """Start ``name`` at main (call it BEFORE main moves on, to give it a fork point)."""
    _git(repo, "checkout", "-q", "-b", name, "main")


def _publish_and_leave(repo: Path, name: str) -> None:
    _git(repo, "push", "--quiet", "origin", name)
    _git(repo, "checkout", "-q", "main")


def _prove(repo: Path, name: str, *, also_deleting: tuple[str, ...] = ()) -> RemoteProof:
    return prove_remote_merged(repo, "origin", [name], "main", _CONFIG, also_deleting=also_deleting)


class TestTierA:
    def test_a_tip_already_contained_in_an_integration_line_is_merged(self, repo: Path) -> None:
        _git(repo, "checkout", "-q", "-b", "release/1", "main")
        _git(repo, "push", "--quiet", "origin", "release/1")
        _git(repo, "checkout", "-q", "-b", "feat", "release/1")
        _write(repo, "a.txt", "a\n")
        _commit(repo)
        _git(repo, "push", "--quiet", "origin", "feat")
        _git(repo, "checkout", "-q", "release/1")
        _git(repo, "merge", "--ff-only", "-q", "feat")
        _git(repo, "push", "--quiet", "origin", "release/1")
        _git(repo, "checkout", "-q", "main")
        proof = _prove(repo, "feat")
        assert list(proof.tips) == ["feat"]
        assert proof.evidence == {"feat": TIER_MERGED}


class TestTierB:
    def test_content_split_across_main_and_a_line_is_proven(self, repo: Path) -> None:
        _branch_from_main(repo, "feat")
        _write(repo, "a.txt", "a\n")
        _write(repo, "b.txt", "b\n")
        _commit(repo)
        _publish_and_leave(repo, "feat")
        _land(repo, "a.txt", "a\n")
        _git(repo, "checkout", "-q", "-b", "release/1", "main")
        _write(repo, "b.txt", "b\n")
        _commit(repo, "line has b")
        _git(repo, "push", "--quiet", "origin", "release/1")
        _git(repo, "checkout", "-q", "main")
        proof = _prove(repo, "feat")
        assert list(proof.tips) == ["feat"]
        assert proof.evidence == {"feat": TIER_SURVIVING_CONTENT}

    def test_one_file_present_nowhere_refuses_and_names_it(self, repo: Path) -> None:
        _branch_from_main(repo, "feat")
        _write(repo, "a.txt", "a\n")
        _write(repo, "only-here.txt", "unique\n")
        _commit(repo)
        _publish_and_leave(repo, "feat")
        _land(repo, "a.txt", "a\n")
        proof = _prove(repo, "feat")
        assert proof.tips == {}
        assert "only-here.txt" in proof.problems["feat"]
        assert "not merged" in proof.problems["feat"]

    def test_the_same_path_with_other_content_is_not_present(self, repo: Path) -> None:
        _branch_from_main(repo, "feat")
        _write(repo, "a.txt", "branch version\n")
        _commit(repo)
        _publish_and_leave(repo, "feat")
        _land(repo, "a.txt", "main version\n")
        proof = _prove(repo, "feat")
        assert proof.tips == {}
        assert "a.txt" in proof.problems["feat"]

    def test_the_same_blob_at_another_path_is_not_present(self, repo: Path) -> None:
        _branch_from_main(repo, "feat")
        _write(repo, "a.txt", "shared\n")
        _commit(repo)
        _publish_and_leave(repo, "feat")
        _land(repo, "elsewhere.txt", "shared\n")
        proof = _prove(repo, "feat")
        assert proof.tips == {}
        assert "a.txt" in proof.problems["feat"]

    def test_an_added_then_removed_file_is_not_content(self, repo: Path) -> None:
        _branch_from_main(repo, "feat")
        _write(repo, "scratch.txt", "temporary\n")
        _write(repo, "a.txt", "a\n")
        _commit(repo, "add both")
        _git(repo, "rm", "-q", "scratch.txt")
        _commit(repo, "drop scratch")
        _publish_and_leave(repo, "feat")
        _land(repo, "a.txt", "a\n")
        proof = _prove(repo, "feat")
        assert list(proof.tips) == ["feat"]

    def test_a_deleted_file_main_still_has_is_not_unique_content(self, repo: Path) -> None:
        _land(repo, "keep.txt", "keep\n")
        _branch_from_main(repo, "feat")
        _git(repo, "rm", "-q", "keep.txt")
        _write(repo, "a.txt", "a\n")
        _commit(repo)
        _publish_and_leave(repo, "feat")
        _land(repo, "a.txt", "a\n")
        proof = _prove(repo, "feat")
        assert list(proof.tips) == ["feat"]
        assert proof.evidence == {"feat": TIER_SURVIVING_CONTENT}

    def test_a_delete_only_branch_has_no_content_to_find_and_is_refused(self, repo: Path) -> None:
        _land(repo, "keep.txt", "keep\n")
        _branch_from_main(repo, "rm")
        _git(repo, "rm", "-q", "keep.txt")
        _commit(repo)
        _publish_and_leave(repo, "rm")
        proof = _prove(repo, "rm")
        assert proof.tips == {}
        assert "not merged" in proof.problems["rm"]

    def test_a_rename_whose_new_path_exists_on_main_is_proven(self, repo: Path) -> None:
        _branch_from_main(repo, "mv")
        _git(repo, "mv", "base.txt", "moved.txt")
        _commit(repo, "rename")
        _publish_and_leave(repo, "mv")
        # Main gained the new path but kept the old one, so no single commit holds the
        # branch's whole net change (the old path is not gone): only per-file presence.
        _land(repo, "moved.txt", "base\n")
        proof = _prove(repo, "mv")
        assert list(proof.tips) == ["mv"]
        assert proof.evidence == {"mv": TIER_SURVIVING_CONTENT}

    def test_a_rename_whose_new_path_is_absent_on_main_is_refused(self, repo: Path) -> None:
        _branch_from_main(repo, "mv")
        _git(repo, "mv", "base.txt", "moved.txt")
        _commit(repo, "rename")
        _publish_and_leave(repo, "mv")
        _land(repo, "other.txt", "other\n")
        proof = _prove(repo, "mv")
        assert proof.tips == {}
        assert "moved.txt" in proof.problems["mv"]

    def test_a_binary_file_is_compared_by_blob(self, repo: Path) -> None:
        payload = b"\x00\xff\xfe binary \x00\x01"
        _branch_from_main(repo, "bin")
        _write(repo, "blob.bin", payload)
        _write(repo, "x.txt", "x\n")
        _commit(repo)
        _publish_and_leave(repo, "bin")
        _land(repo, "blob.bin", payload)
        # x.txt is absent on main, so the branch still holds it: refused.
        refused = _prove(repo, "bin")
        assert refused.tips == {}
        assert "x.txt" in refused.problems["bin"]
        _land(repo, "x.txt", "x\n")
        proven = _prove(repo, "bin")
        assert list(proven.tips) == ["bin"]
        # Both files are now on main in separate commits that together hold the net change.
        assert proven.evidence["bin"] in {TIER_SURVIVING_CONTENT, TIER_CONTENT_PRESERVED}

    def test_a_binary_file_with_other_bytes_is_refused(self, repo: Path) -> None:
        _branch_from_main(repo, "bin")
        _write(repo, "blob.bin", b"\x00\x01\x02")
        _commit(repo)
        _publish_and_leave(repo, "bin")
        _land(repo, "blob.bin", b"\x00\x01\x03")
        proof = _prove(repo, "bin")
        assert proof.tips == {}
        assert "blob.bin" in proof.problems["bin"]

    def test_an_empty_diff_is_refused(self, repo: Path) -> None:
        _branch_from_main(repo, "parked")
        _git(repo, "commit", "-q", "--allow-empty", "-m", "Park it")
        _publish_and_leave(repo, "parked")
        _land(repo, "later.txt", "later\n")
        proof = _prove(repo, "parked")
        assert proof.tips == {}
        assert "not merged" in proof.problems["parked"]

    def test_more_changed_paths_than_the_ceiling_is_refused(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("claude_code_hooks_daemon.core.remote_branch_proof.MAX_PROOF_PATHS", 1)
        assert MAX_PROOF_PATHS > 1
        _branch_from_main(repo, "wide")
        _write(repo, "a.txt", "a\n")
        _write(repo, "b.txt", "b\n")
        _commit(repo)
        _publish_and_leave(repo, "wide")
        _land(repo, "a.txt", "a\n")
        _land(repo, "b.txt", "b\n")
        assert _prove(repo, "wide").tips == {}


class TestSurvivingMeansNotBeingDeleted:
    def _line_holding_the_content(self, repo: Path) -> None:
        _git(repo, "checkout", "-q", "-b", "release/1", "main")
        _write(repo, "a.txt", "a\n")
        _commit(repo, "line has a")
        _git(repo, "push", "--quiet", "origin", "release/1")
        _git(repo, "checkout", "-q", "-b", "feat", "main")
        _write(repo, "a.txt", "a\n")
        _commit(repo, "feat has a")
        _git(repo, "push", "--quiet", "origin", "feat")
        _git(repo, "checkout", "-q", "main")

    def test_a_line_holding_the_content_vouches_for_it(self, repo: Path) -> None:
        self._line_holding_the_content(repo)
        assert list(_prove(repo, "feat").tips) == ["feat"]

    def test_a_line_deleted_in_the_same_command_does_not_vouch(self, repo: Path) -> None:
        self._line_holding_the_content(repo)
        proof = _prove(repo, "feat", also_deleting=("release/1",))
        assert proof.tips == {}
        assert "a.txt" in proof.problems["feat"]

    def test_a_line_judged_in_the_same_batch_does_not_vouch(self, repo: Path) -> None:
        self._line_holding_the_content(repo)
        proof = prove_remote_merged(repo, "origin", ["feat", "release/1"], "main", _CONFIG)
        assert "feat" not in proof.tips


class TestNeverCached:
    def test_the_tier_is_not_written_to_the_merge_proof_cache(self, repo: Path) -> None:
        _branch_from_main(repo, "feat")
        _write(repo, "a.txt", "a\n")
        _commit(repo)
        _publish_and_leave(repo, "feat")
        _land(repo, "a.txt", "a\n")
        assert list(_prove(repo, "feat").tips) == ["feat"]
        assert TIER_SURVIVING_CONTENT not in read_merge_proofs(repo).values()
