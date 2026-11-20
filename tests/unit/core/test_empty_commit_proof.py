"""Commits that change no file never decide a delete proof (Plan 00622).

A branch whose work the default already holds, with an empty commit on top (an
``Unpark branch`` written by hand, a note, the park writer's own marker), loses
nothing a delete can lose but that commit's message. An empty commit is ONE parent
and the same tree as that parent; nothing else is empty. A commit with a marker-like
message that changes a file, a merge whose tree equals its first parent, and a
branch whose content differs from the default by one byte all stay refused.

Every case is a synthetic repository with a bare remote, judged by the three proofs
a delete rests on: ``prove_remote_merged`` (``R-GIT-PUSH-DELETE-REMOTE`` and
``branch-sweep --clean --remote``), the destructive-git guard's note, and
``classify_branch`` with and without the content tier (``delete-branch`` and the
hook-path cleanup).
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.config.models import BranchesConfig
from claude_code_hooks_daemon.core import branch_inventory, branch_park
from claude_code_hooks_daemon.core.branch_park import is_content_free
from claude_code_hooks_daemon.core.remote_branch_proof import prove_remote_merged
from claude_code_hooks_daemon.daemon import branch_safety
from claude_code_hooks_daemon.handlers.pre_tool_use.destructive_git import _remote_delete_note
from tests.conftest import HERMETIC_GIT_EMAIL

_UNPARK_WRITER = "Unpark branch\n\nUnparked: t\n"
_PARK_WRITER = "Park branch: waiting\n\nParked-Reason: waiting\nParked-By: t\n"


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


def _write(repo: Path, filename: str, text: str, message: str) -> None:
    (repo / filename).write_text(text, encoding="utf-8")
    _git(repo, "add", filename)
    _git(repo, "commit", "-q", "-m", message)


def _empty(repo: Path, message: str) -> None:
    _git(repo, "commit", "-q", "--allow-empty", "--cleanup=verbatim", "-m", message)


def _branch(repo: Path, name: str) -> None:
    _git(repo, "checkout", "-q", "-b", name, "main")


def _main_merges(repo: Path, name: str, how: str) -> None:
    _git(repo, "checkout", "-q", "main")
    if how == "merge":
        _git(repo, "merge", "--no-ff", "-q", "-m", f"Merge {name}", name)
    elif how == "ff":
        _git(repo, "merge", "--ff-only", "-q", name)
    elif how == "squash":
        _git(repo, "merge", "--squash", "-q", name)
        _git(repo, "commit", "-q", "-m", f"Squash {name}")
    else:
        raise ValueError(how)
    _git(repo, "push", "-q", "origin", "main")
    _git(repo, "checkout", "-q", name)


def _publish(repo: Path, name: str) -> None:
    _git(repo, "push", "-q", "-f", "-u", "origin", name)
    _git(repo, "checkout", "-q", "main")
    _git(repo, "fetch", "-q", "--prune", "origin")


def _verdicts(repo: Path, name: str) -> dict[str, bool]:
    """Whether each proof allows deleting ``name`` (True) or refuses it (False)."""
    remote = prove_remote_merged(repo, "origin", [name], "main", BranchesConfig(default="main"))
    guard = _remote_delete_note(
        f"git push origin --delete {name}", repo, BranchesConfig(default="main")
    )
    full = branch_safety.classify_branch(repo, name)
    fast = branch_safety.classify_branch(repo, name, content_tier=False)
    return {
        "remote": name in remote.tips,
        "guard": guard is None,
        "local": full.is_safe,
        "local-hook": fast.is_safe,
    }


def _all(value: bool) -> dict[str, bool]:
    return {"remote": value, "guard": value, "local": value, "local-hook": value}


# --- the reported shapes ----------------------------------------------------------------


class TestReportedShapesAreDeletable:
    """Content in the default, empty commits on top (RED before the Plan 00622 fix)."""

    def test_a_plain_unpark_commit_over_merged_work(self, repo: Path) -> None:
        """(a) A hand-written ``Unpark branch`` (no trailer) over merge-commit-merged work."""
        _branch(repo, "feat")
        _write(repo, "feat.txt", "feat\n", "work")
        _main_merges(repo, "feat", "merge")
        _empty(repo, "Unpark branch")
        _publish(repo, "feat")
        assert _verdicts(repo, "feat") == _all(True)

    def test_a_plain_empty_commit_over_fast_forwarded_work(self, repo: Path) -> None:
        _branch(repo, "feat")
        _write(repo, "feat.txt", "feat\n", "work")
        _main_merges(repo, "feat", "ff")
        _empty(repo, "note: nothing left to do here")
        _publish(repo, "feat")
        assert _verdicts(repo, "feat") == _all(True)

    def test_several_empty_commits_of_any_message_over_merged_work(self, repo: Path) -> None:
        _branch(repo, "feat")
        _write(repo, "feat.txt", "feat\n", "work")
        _main_merges(repo, "feat", "merge")
        _empty(repo, "Unpark branch")
        _empty(repo, "Unrelated note\n\nParked-Reason: waiting\nParked-By: t\n")
        _empty(repo, _UNPARK_WRITER)
        _publish(repo, "feat")
        assert _verdicts(repo, "feat") == _all(True)

    def test_a_cherry_picked_branch_with_a_plain_empty_commit_passes_the_net_change_route(
        self, repo: Path
    ) -> None:
        """Every content patch is in main, with an empty commit on top.

        Patch-ids alone cannot prove it: they ignore whitespace, so an empty commit
        excused there could cover a pick main took reformatted (round 2, D1). The
        proofs that check the net change pass it; the hook path, which has only
        patch-ids, refuses it.
        """
        _branch(repo, "feat")
        _write(repo, "a.txt", "a\n", "a")
        _write(repo, "b.txt", "b\n", "b")
        _empty(repo, "Unpark branch")
        _git(repo, "checkout", "-q", "main")
        _write(repo, "unrelated.txt", "u\n", "unrelated")
        _git(repo, "cherry-pick", "feat~2", "feat~1")
        _git(repo, "push", "-q", "origin", "main")
        _git(repo, "checkout", "-q", "feat")
        _publish(repo, "feat")
        verdict = branch_safety.classify_branch(repo, "feat", content_tier=False)
        assert verdict.tier == branch_safety.TIER_UNPROVEN
        assert branch_safety.classify_branch(repo, "feat").tier == (
            branch_safety.TIER_CONTENT_PRESERVED
        )
        assert _verdicts(repo, "feat") == {
            "remote": True,
            "guard": True,
            "local": True,
            "local-hook": False,
        }


class TestReportedShapesAlreadyProven:
    """PIN: shapes the current proofs already pass (the writer's exact markers)."""

    def test_the_writers_unpark_over_merged_work(self, repo: Path) -> None:
        _branch(repo, "feat")
        _write(repo, "feat.txt", "feat\n", "work")
        _main_merges(repo, "feat", "merge")
        _empty(repo, _PARK_WRITER)
        _empty(repo, _UNPARK_WRITER)
        _publish(repo, "feat")
        assert _verdicts(repo, "feat") == _all(True)

    def test_the_writers_park_over_fast_forwarded_work(self, repo: Path) -> None:
        """(b) The daemon's own park marker."""
        _branch(repo, "feat")
        _write(repo, "feat.txt", "feat\n", "work")
        _main_merges(repo, "feat", "ff")
        _empty(repo, _PARK_WRITER)
        _publish(repo, "feat")
        assert _verdicts(repo, "feat") == _all(True)

    @pytest.mark.parametrize("marker", [_UNPARK_WRITER, "Unpark branch"], ids=["writer", "plain"])
    def test_a_modified_merge_then_an_unpark_passes_the_net_change_route(
        self, repo: Path, marker: str
    ) -> None:
        """(c) Cherry marks the content commits unmerged: main took a REWRITTEN patch.

        The branch writes a.txt, b.txt, then fixes a.txt; main took ONE commit with
        the fixed a.txt and b.txt. Only the net-change proof can pass it, and does, so
        the hook path (no content tier) still refuses it.
        """
        _branch(repo, "feat")
        _write(repo, "a.txt", "a1\n", "a1")
        _write(repo, "b.txt", "b1\n", "b1")
        _write(repo, "a.txt", "a2\n", "a2")
        _git(repo, "checkout", "-q", "main")
        (repo / "a.txt").write_text("a2\n", encoding="utf-8")
        (repo / "b.txt").write_text("b1\n", encoding="utf-8")
        _git(repo, "add", "a.txt", "b.txt")
        _git(repo, "commit", "-q", "-m", "the pull request, reworked")
        _git(repo, "push", "-q", "origin", "main")
        _git(repo, "checkout", "-q", "feat")
        _empty(repo, marker)
        _publish(repo, "feat")
        unique = branch_safety.cherry_unique_shas(repo, "main", "refs/heads/feat")
        assert unique is not None and len(unique) >= 2
        assert _verdicts(repo, "feat") == {
            "remote": True,
            "guard": True,
            "local": True,
            "local-hook": False,
        }


# --- content-bearing twins stay refused ---------------------------------------------------


class TestContentBearingTwinsStayRefused:
    """PIN: none of these may ever pass; each carries content the default lacks."""

    def test_a_content_commit_named_like_an_unpark(self, repo: Path) -> None:
        _branch(repo, "feat")
        _write(repo, "feat.txt", "feat\n", "work")
        _main_merges(repo, "feat", "merge")
        _write(repo, "extra.txt", "unmerged\n", _UNPARK_WRITER)
        _publish(repo, "feat")
        assert _verdicts(repo, "feat") == _all(False)

    def test_a_content_commit_named_like_a_park(self, repo: Path) -> None:
        _branch(repo, "feat")
        _write(repo, "feat.txt", "feat\n", "work")
        _main_merges(repo, "feat", "ff")
        _write(repo, "extra.txt", "unmerged\n", _PARK_WRITER)
        _publish(repo, "feat")
        assert _verdicts(repo, "feat") == _all(False)

    def test_an_empty_commit_over_a_change_and_its_revert(self, repo: Path) -> None:
        """The net change is empty, but the change's bytes exist nowhere in main."""
        _branch(repo, "feat")
        _write(repo, "secret-work.txt", "work main never took\n", "work")
        _git(repo, "revert", "--no-edit", "HEAD")
        _empty(repo, "Unpark branch")
        _publish(repo, "feat")
        assert _verdicts(repo, "feat") == _all(False)

    def test_an_empty_commit_hiding_under_it_an_unmerged_commit(self, repo: Path) -> None:
        _branch(repo, "feat")
        _write(repo, "feat.txt", "feat\n", "work")
        _main_merges(repo, "feat", "merge")
        _write(repo, "later.txt", "unmerged\n", "later work")
        _empty(repo, "Unpark branch")
        _publish(repo, "feat")
        assert _verdicts(repo, "feat") == _all(False)

    def test_an_ours_merge_whose_tree_equals_its_first_parent(self, repo: Path) -> None:
        """A merge with its first parent's tree still carries a whole side history."""
        _branch(repo, "side")
        _write(repo, "side.txt", "side work\n", "side")
        _branch(repo, "feat")
        _write(repo, "feat.txt", "feat\n", "work")
        _main_merges(repo, "feat", "merge")
        _git(repo, "merge", "-q", "-s", "ours", "-m", "Unpark branch", "side")
        _publish(repo, "feat")
        _git(repo, "branch", "-q", "-D", "side")
        assert _verdicts(repo, "feat") == _all(False)

    def test_a_file_one_byte_different_from_mains_with_an_empty_commit(self, repo: Path) -> None:
        _branch(repo, "feat")
        _write(repo, "feat.txt", "value = 1\n", "work")
        _git(repo, "checkout", "-q", "main")
        (repo / "feat.txt").write_text("value = 2\n", encoding="utf-8")
        _git(repo, "add", "feat.txt")
        _git(repo, "commit", "-q", "-m", "the pull request, one byte changed")
        _git(repo, "push", "-q", "origin", "main")
        _git(repo, "checkout", "-q", "feat")
        _empty(repo, "Unpark branch")
        _publish(repo, "feat")
        assert _verdicts(repo, "feat") == _all(False)

    def test_a_root_commit_named_like_an_unpark(self, repo: Path) -> None:
        """No parent, so nothing it could be empty against: its content counts."""
        _branch(repo, "scratch")
        _write(repo, "root-only.txt", "held nowhere else\n", "scratch")
        tree = _git(repo, "rev-parse", "HEAD^{tree}")
        _git(repo, "checkout", "-q", "main")
        _git(repo, "branch", "-q", "-D", "scratch")
        sha = _git(repo, "commit-tree", tree, "-m", "Unpark branch")
        _git(repo, "update-ref", "refs/heads/feat", sha)
        _git(repo, "push", "-q", "origin", "feat")
        _git(repo, "fetch", "-q", "--prune", "origin")
        assert _verdicts(repo, "feat") == _all(False)

    def test_an_empty_commit_whose_parent_is_an_unmerged_commit_of_another_branch(
        self, repo: Path
    ) -> None:
        _branch(repo, "other")
        _write(repo, "other.txt", "other\n", "other work")
        _git(repo, "checkout", "-q", "-b", "feat", "other")
        _empty(repo, "Unpark branch")
        _publish(repo, "feat")
        _git(repo, "branch", "-q", "-D", "other")
        assert _verdicts(repo, "feat") == _all(False)


# --- lossy shapes the review found (Plan 00622 round 2) ----------------------------------


def _commit_tree(repo: Path, tree: str, parents: list[str], message: str) -> str:
    args = ["commit-tree", tree]
    for parent in parents:
        args += ["-p", parent]
    return _git(repo, *args, "-m", message)


class TestAnEmptyCommitNeverWidensPatchEquivalence:
    """D1: patch-ids ignore whitespace, so an empty commit must not let them stand alone.

    Each branch holds a blob the default's history lacks. Without an empty commit
    these are an older patch-id weakness; with one, the empty commit must not be the
    thing that makes them deletable.
    """

    def test_a_whitespace_only_pick_under_an_empty_commit(self, repo: Path) -> None:
        _branch(repo, "feat")
        _write(repo, "f.py", "def f():\n    return  1  \n", "fix f")
        _empty(repo, "Unpark branch")
        _git(repo, "checkout", "-q", "main")
        _write(repo, "f.py", "def f():\n    return 1\n", "fix f (whitespace cleaned)")
        _git(repo, "push", "-q", "origin", "main")
        _git(repo, "checkout", "-q", "feat")
        _publish(repo, "feat")
        blob = _git(repo, "rev-parse", "feat:f.py")
        assert blob not in _git(repo, "rev-list", "--objects", "main")
        assert _verdicts(repo, "feat") == _all(False)

    def test_an_orphan_whitespace_twin_under_an_empty_commit(self, repo: Path) -> None:
        """No merge base: ``git cherry`` compares against the whole history."""
        _git(repo, "checkout", "-q", "--orphan", "feat")
        _git(repo, "rm", "-q", "-rf", ".")
        _write(repo, "base.txt", "base  \n", "orphan root")
        _empty(repo, "note")
        _publish(repo, "feat")
        assert _verdicts(repo, "feat") == _all(False)


class TestReplaceRefsAndGraftsAreIgnored:
    """D2: every proof reads the real objects, never a replacement or a graft."""

    def _content_commit(self, repo: Path) -> tuple[str, str]:
        _branch(repo, "feat")
        _write(repo, "secret.txt", "only-here\n", "add secret")
        _publish(repo, "feat")
        return _git(repo, "rev-parse", "feat"), _git(repo, "rev-parse", "feat~1")

    @pytest.mark.parametrize("message", ["note", _PARK_WRITER], ids=["any", "park-writer"])
    def test_a_content_commit_replaced_by_an_empty_looking_one(
        self, repo: Path, message: str
    ) -> None:
        content, parent = self._content_commit(repo)
        fake = _commit_tree(repo, _git(repo, "rev-parse", f"{parent}^{{tree}}"), [parent], message)
        _git(repo, "replace", content, fake)
        assert _verdicts(repo, "feat") == _all(False)

    def test_a_content_commit_hidden_under_an_empty_commit_by_a_replace(self, repo: Path) -> None:
        _branch(repo, "feat")
        _write(repo, "secret.txt", "only-here\n", "add secret")
        content = _git(repo, "rev-parse", "HEAD")
        _empty(repo, "note")
        _publish(repo, "feat")
        parent = _git(repo, "rev-parse", f"{content}~1")
        fake = _commit_tree(repo, _git(repo, "rev-parse", f"{parent}^{{tree}}"), [parent], "n")
        _git(repo, "replace", content, fake)
        assert _verdicts(repo, "feat") == _all(False)

    def test_a_default_tip_replaced_to_descend_from_the_branch(self, repo: Path) -> None:
        content, _parent = self._content_commit(repo)
        main_tip = _git(repo, "rev-parse", "main")
        fake = _commit_tree(
            repo, _git(repo, "rev-parse", "main^{tree}"), [main_tip, content], "Merge"
        )
        _git(repo, "replace", main_tip, fake)
        assert _git(repo, "rev-parse", "origin/main") == main_tip
        # The replacement is live for plain git: the default now appears to hold the branch.
        assert _git(repo, "merge-base", "main", content) == content
        assert _verdicts(repo, "feat") == _all(False)

    def test_a_legacy_graft_making_the_default_descend_from_the_branch(self, repo: Path) -> None:
        content, _parent = self._content_commit(repo)
        _write(repo, "later.txt", "later\n", "later on main")
        _git(repo, "push", "-q", "origin", "main")
        _git(repo, "fetch", "-q", "origin")
        main_tip = _git(repo, "rev-parse", "main")
        main_parent = _git(repo, "rev-parse", "main~1")
        grafts = Path(_git(repo, "rev-parse", "--git-path", "info/grafts"))
        if not grafts.is_absolute():
            grafts = repo / grafts
        grafts.parent.mkdir(parents=True, exist_ok=True)
        grafts.write_text(f"{main_tip} {main_parent} {content}\n", encoding="utf-8")
        # The graft is live for plain git: the default now appears to hold the branch.
        assert (
            subprocess.run(
                ["git", "-C", str(repo), "merge-base", "--is-ancestor", content, "main"],
                capture_output=True,
                check=False,
            ).returncode
            == 0
        )
        assert _verdicts(repo, "feat") == _all(False)


# --- a forged commit-graph (Plan 00622 round 3, R2-1) ---------------------------------------

#: One commit-graph CDAT record: tree oid (20), parent 1 index (4), parent 2 index (4),
#: generation and time (8). SHA-1 repositories only, which is what these fixtures make.
_CDAT_RECORD = 36
_OID = 20


def _graph_file(objects: Path) -> Path:
    return objects / "info" / "commit-graph"


def _graph_chunks(data: bytearray) -> dict[bytes, int]:
    chunks: dict[bytes, int] = {}
    for index in range(data[6] + 1):
        offset = 8 + index * 12
        chunks[bytes(data[offset : offset + 4])] = int.from_bytes(
            data[offset + 4 : offset + 12], "big"
        )
    return chunks


def _graph_position(data: bytearray, sha: str) -> int:
    chunks = _graph_chunks(data)
    count = int.from_bytes(data[chunks[b"OIDF"] + 1020 : chunks[b"OIDF"] + 1024], "big")
    lookup = chunks[b"OIDL"]
    wanted = bytes.fromhex(sha)
    for position in range(count):
        if bytes(data[lookup + position * _OID : lookup + (position + 1) * _OID]) == wanted:
            return position
    raise LookupError(sha)


def _forge_graph(
    objects: Path, victim: str, *, tree: str | None = None, parent: str | None = None
) -> None:
    """Rewrite ``victim``'s commit-graph record (its tree, or its first parent) in place."""
    path = _graph_file(objects)
    data = bytearray(path.read_bytes())
    record = _graph_chunks(data)[b"CDAT"] + _graph_position(data, victim) * _CDAT_RECORD
    if tree is not None:
        data[record : record + _OID] = bytes.fromhex(tree)
    if parent is not None:
        position = _graph_position(data, parent)
        data[record + _OID : record + _OID + 4] = position.to_bytes(4, "big")
    data[-_OID:] = hashlib.sha1(bytes(data[:-_OID]), usedforsecurity=False).digest()
    path.write_bytes(bytes(data))


def _walk(repo: Path, range_spec: str) -> str:
    """What plain git (graph enabled) reports for the range, to prove a forgery is live."""
    return _git(repo, "log", "--boundary", "--format=%H %T %P", range_spec)


def _content_then_undo(repo: Path, message: str) -> tuple[str, str]:
    """C adds a file only this branch holds; the tip R removes it, so R's tree is main's."""
    _branch(repo, "feat")
    (repo / "secret.txt").write_text("only-here\n", encoding="utf-8")
    _git(repo, "add", "secret.txt")
    _git(repo, "commit", "-q", "--cleanup=verbatim", "-m", message)
    content = _git(repo, "rev-parse", "HEAD")
    _git(repo, "rm", "-q", "secret.txt")
    _git(repo, "commit", "-q", "--cleanup=verbatim", "-m", message)
    _publish(repo, "feat")
    return content, _git(repo, "rev-parse", f"{content}~1^{{tree}}")


class TestACommitGraphIsIgnored:
    """R2-1: a commit reached through a parent is filled in from the commit-graph.

    A hand-forged graph record can make a content commit below the tip read as empty,
    or drop it from the range. Every proof must read the stored commit objects.
    """

    @pytest.mark.parametrize("message", ["add secret", _PARK_WRITER], ids=["any", "park-writer"])
    def test_a_content_commit_below_the_tip_forged_empty(self, repo: Path, message: str) -> None:
        content, parent_tree = _content_then_undo(repo, message)
        _git(repo, "commit-graph", "write", "--reachable")
        _forge_graph(repo / ".git" / "objects", content, tree=parent_tree)
        assert f"{content} {parent_tree} " in _walk(repo, "main..feat")
        assert _verdicts(repo, "feat") == _all(False)

    def test_an_inherited_test_variable_cannot_re_enable_the_graph(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``GIT_TEST_COMMIT_GRAPH=1`` overrides ``core.commitGraph=false``."""
        content, parent_tree = _content_then_undo(repo, "add secret")
        _git(repo, "commit-graph", "write", "--reachable")
        _forge_graph(repo / ".git" / "objects", content, tree=parent_tree)
        monkeypatch.setenv("GIT_TEST_COMMIT_GRAPH", "1")
        assert f"{content} {parent_tree} " in _git(
            repo,
            "-c",
            "core.commitGraph=false",
            "log",
            "--boundary",
            "--format=%H %T %P",
            "main..feat",
        )
        assert _verdicts(repo, "feat") == _all(False)

    def test_a_forged_graph_in_an_alternate_object_store(self, repo: Path) -> None:
        content, parent_tree = _content_then_undo(repo, "add secret")
        store = repo.parent / "alternate.git"
        _git(repo.parent, "clone", "-q", "--bare", str(repo), str(store))
        _git(store, "commit-graph", "write", "--reachable")
        _forge_graph(store / "objects", content, tree=parent_tree)
        alternates = repo / ".git" / "objects" / "info" / "alternates"
        alternates.write_text(f"{store / 'objects'}\n", encoding="utf-8")
        assert not _graph_file(repo / ".git" / "objects").exists()
        assert f"{content} {parent_tree} " in _walk(repo, "main..feat")
        assert _verdicts(repo, "feat") == _all(False)

    def test_a_forged_parent_below_the_tip_drops_a_content_commit(self, repo: Path) -> None:
        """X adds a file, Y removes it, Z is empty; the graph gives Y main's tip as parent."""
        content, _parent_tree = _content_then_undo(repo, "add secret")
        _git(repo, "checkout", "-q", "feat")
        _empty(repo, "note")
        _publish(repo, "feat")
        undo = _git(repo, "rev-parse", "feat~1")
        main_tip = _git(repo, "rev-parse", "main")
        _git(repo, "commit-graph", "write", "--reachable")
        _forge_graph(repo / ".git" / "objects", undo, parent=main_tip)
        assert content not in _walk(repo, "main..feat")
        assert _verdicts(repo, "feat") == _all(False)


class TestTheStoredObjectReadFailsClosed:
    """The walk's emptiness is confirmed from the stored commits; any doubt is unproven."""

    def test_a_failed_object_read_is_none(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _plain_unpark_over_merged(repo)
        tip = _git(repo, "rev-parse", "feat")
        monkeypatch.setattr(branch_park, "read_blobs", lambda *_a, **_k: None)
        assert is_content_free(repo, tip, "main") is None

    def test_a_missing_object_is_none(self, repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _plain_unpark_over_merged(repo)
        tip = _git(repo, "rev-parse", "feat")
        monkeypatch.setattr(branch_park, "read_blobs", lambda *_a, **_k: {})
        assert is_content_free(repo, tip, "main") is None

    def test_a_stored_tree_the_walk_did_not_report_is_none(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _plain_unpark_over_merged(repo)
        tip = _git(repo, "rev-parse", "feat")
        real = branch_park.read_blobs

        def other_tree(directory: Path, shas: list[str], **kwargs: Any) -> object:
            stored = real(directory, shas, **kwargs)
            assert stored is not None
            body = stored[tip]
            stored[tip] = body.replace(body[5:45], b"0" * 40, 1)
            return stored

        monkeypatch.setattr(branch_park, "read_blobs", other_tree)
        assert is_content_free(repo, tip, "main") is None

    def test_a_stored_parent_the_walk_did_not_report_is_none(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Isolates the parent comparison: with the graph off the walk itself is truthful."""
        _plain_unpark_over_merged(repo)
        tip = _git(repo, "rev-parse", "feat")
        parent = _git(repo, "rev-parse", "feat~1")
        real = branch_park.read_blobs

        def other_parent(directory: Path, shas: list[str], **kwargs: Any) -> object:
            stored = real(directory, shas, **kwargs)
            assert stored is not None
            old = f"parent {parent}\n".encode()
            assert old in stored[tip]
            stored[tip] = stored[tip].replace(old, b"parent " + b"0" * 40 + b"\n", 1)
            return stored

        monkeypatch.setattr(branch_park, "read_blobs", other_parent)
        assert is_content_free(repo, tip, "main") is None

    def test_every_proof_refuses_when_the_object_read_fails(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _plain_unpark_over_merged(repo)
        real = branch_park.read_blobs
        monkeypatch.setattr(branch_park, "read_blobs", lambda *_a, **_k: None)
        assert _verdicts(repo, "feat") == _all(False)
        monkeypatch.setattr(branch_park, "read_blobs", real)
        assert _verdicts(repo, "feat") == _all(True)


class TestAProofCachedUnderAnOlderRuleIsNotHonoured:
    """R2-2: a proof an earlier rule cached is never read once the rule changes."""

    def test_a_stale_v4_empty_commits_only_entry_for_a_content_branch(self, repo: Path) -> None:
        _branch(repo, "feat")
        _write(repo, "secret.txt", "only-here\n", "add secret")
        _publish(repo, "feat")
        tip = _git(repo, "rev-parse", "origin/feat")
        main_tip = _git(repo, "rev-parse", "origin/main")
        cache = repo / branch_inventory.CACHE_RELATIVE_PATH
        cache.parent.mkdir(parents=True, exist_ok=True)
        document = json.loads(cache.read_text(encoding="utf-8")) if cache.exists() else {}
        document.update(
            {
                "version": branch_inventory._CACHE_VERSION,
                "pairs": document.get("pairs", {}),
                "containment": document.get("containment", {}),
                "park_counts": document.get("park_counts", {}),
                "proofs": {f"v4:{tip}:{main_tip}": branch_safety.TIER_EMPTY_COMMITS_ONLY},
            }
        )
        cache.write_text(json.dumps(document), encoding="utf-8")
        remote = prove_remote_merged(
            repo, "origin", ["feat"], "main", BranchesConfig(default="main")
        )
        assert remote.tips == {}
        guard = _remote_delete_note(
            "git push origin --delete feat", repo, BranchesConfig(default="main")
        )
        assert guard is not None


# --- the rule itself, and failure ---------------------------------------------------------


def _plain_unpark_over_merged(repo: Path) -> None:
    _branch(repo, "feat")
    _write(repo, "feat.txt", "feat\n", "work")
    _main_merges(repo, "feat", "merge")
    _empty(repo, "Unpark branch")
    _publish(repo, "feat")


class TestContentFreeRule:
    def test_the_tier_names_the_empty_commits(self, repo: Path) -> None:
        _plain_unpark_over_merged(repo)
        remote = prove_remote_merged(
            repo, "origin", ["feat"], "main", BranchesConfig(default="main")
        )
        assert remote.evidence == {"feat": branch_safety.TIER_EMPTY_COMMITS_ONLY}
        local = branch_safety.classify_branch(repo, "feat", content_tier=False)
        assert local.tier == branch_safety.TIER_EMPTY_COMMITS_ONLY
        assert local.proven_against == "refs/heads/main"

    def test_no_commit_beyond_the_target_is_not_content_free(self, repo: Path) -> None:
        assert is_content_free(repo, _git(repo, "rev-parse", "main"), "main") is False

    def test_a_failed_walk_is_none(self, repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _plain_unpark_over_merged(repo)
        tip = _git(repo, "rev-parse", "feat")
        monkeypatch.setattr(branch_park, "run_git", _failing_log(branch_park.run_git))
        assert is_content_free(repo, tip, "main") is None

    def test_a_malformed_walk_line_is_none(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _plain_unpark_over_merged(repo)
        tip = _git(repo, "rev-parse", "feat")
        real = branch_park.run_git

        def garbled(directory: Path, *args: str, **kwargs: Any) -> object:
            if _is_walk(args):
                return subprocess.CompletedProcess(args, 0, "not\x1fa walk line\n", "")
            return real(directory, *args, **kwargs)

        monkeypatch.setattr(branch_park, "run_git", garbled)
        assert is_content_free(repo, tip, "main") is None

    def test_every_proof_refuses_when_the_walk_fails(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _plain_unpark_over_merged(repo)
        real = branch_park.run_git
        monkeypatch.setattr(branch_park, "run_git", _failing_log(real))
        assert _verdicts(repo, "feat") == _all(False)
        # The refusal was not cached: once git answers, the same tip is proven.
        monkeypatch.setattr(branch_park, "run_git", real)
        assert _verdicts(repo, "feat") == _all(True)

    def test_a_cached_empty_commits_only_proof_is_walked_again_never_trusted(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A cached positive never authorises a remote delete: it is re-proven (Plan 00626).

        The cache is a plain file in the working tree, so a delete resting on it could
        be forged; the walk runs again and reads the stored objects again.
        """
        _plain_unpark_over_merged(repo)
        config = BranchesConfig(default="main")
        first = prove_remote_merged(repo, "origin", ["feat"], "main", config)
        assert first.evidence == {"feat": branch_safety.TIER_EMPTY_COMMITS_ONLY}
        spawned: list[tuple[str, ...]] = []
        real = branch_park.run_git

        def spy(directory: Path, *args: str, **kwargs: Any) -> object:
            spawned.append(args)
            return real(directory, *args, **kwargs)

        monkeypatch.setattr(branch_park, "run_git", spy)
        second = prove_remote_merged(repo, "origin", ["feat"], "main", config)
        assert second.evidence == {"feat": branch_safety.TIER_EMPTY_COMMITS_ONLY}
        assert [args for args in spawned if _is_walk(args)]

    def test_an_integration_line_with_an_empty_commit_stays_refused(self, repo: Path) -> None:
        """A line is proven by ancestry of the default only; empty commits never prove one."""
        config = BranchesConfig(default="main", integration_lines=["release/*"])
        _branch(repo, "release/1")
        _write(repo, "release.txt", "release\n", "release work")
        _main_merges(repo, "release/1", "merge")
        _empty(repo, "Unpark branch")
        _publish(repo, "release/1")
        remote = prove_remote_merged(repo, "origin", ["release/1"], "main", config)
        assert remote.tips == {}
        local = branch_safety.classify_branch(
            repo, "release/1", line_names=["release/*"], content_tier=False
        )
        assert not local.is_safe


def _is_walk(args: tuple[str, ...]) -> bool:
    """Whether a ``run_git`` call is the range walk, whatever global options precede it."""
    return "log" in args and "--boundary" in args


def _failing_log(real: Callable[..., subprocess.CompletedProcess[str]]) -> Callable[..., object]:
    """``run_git`` with every ``git log --boundary`` (the range walk) failing."""

    def run(directory: Path, *args: str, **kwargs: Any) -> object:
        if _is_walk(args):
            return subprocess.CompletedProcess(args, 128, "", "fatal: simulated")
        return real(directory, *args, **kwargs)

    return run
