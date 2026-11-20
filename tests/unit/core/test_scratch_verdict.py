"""Scratch entry verdicts and the no-git proofs P1, P2, P5 (Plan 00627 Task 1.6)."""

from __future__ import annotations

import pytest

from claude_code_hooks_daemon.core.scratch_clock import EntryAge
from claude_code_hooks_daemon.core.scratch_verdict import (
    NOT_EVALUATED,
    Proof,
    RepositoryMarker,
    Verdict,
    judge,
)
from claude_code_hooks_daemon.core.scratch_walk import EntryStats, Node, NodeKind
from claude_code_hooks_daemon.utils.bounded_walk import Bounded, finished, stopped

_DUE = EntryAge(age_seconds=48 * 3600.0, due=True, lifetime_exceeded=None)
_FRESH = EntryAge(age_seconds=3600.0, due=False, lifetime_exceeded=None)

D = NodeKind.DIRECTORY
F = NodeKind.FILE
L = NodeKind.SYMLINK
S = NodeKind.SPECIAL


def _stats(
    *nodes: Node,
    kind: NodeKind = NodeKind.DIRECTORY,
    multi_linked: tuple[str, ...] = (),
    git_markers: tuple[str, ...] = (),
) -> EntryStats:
    name = nodes[0].path.split("/")[0] if nodes else "e"
    return EntryStats(
        name=name,
        kind=kind,
        root_ctime_ns=1,
        nodes=list(nodes),
        multi_linked=multi_linked,
        git_markers=git_markers,
    )


def _judge(
    walk: Bounded[EntryStats], age: EntryAge = _DUE, liveness: tuple[str, ...] = ()
) -> Verdict:
    return judge(walk, age=age, liveness=liveness).verdict


class TestOrdering:
    def test_liveness_wins_first(self) -> None:
        walk = stopped(_stats(git_markers=("e/.git",)), "walk deadline reached")
        judgement = judge(walk, age=_DUE, liveness=("process 1 has its working directory",))
        assert judgement.verdict is Verdict.LIVE
        assert judgement.reasons == ("process 1 has its working directory",)

    def test_within_ttl_is_live(self) -> None:
        walk = finished(_stats(Node("e", D, 0), Node("e/notes.txt", F, 4)))
        assert _judge(walk, age=_FRESH) is Verdict.LIVE

    def test_a_fresh_mtime_from_a_partial_walk_still_proves_live(self) -> None:
        walk = stopped(_stats(Node("e", D, 0)), "inode cap of 5 reached")
        assert _judge(walk, age=_FRESH) is Verdict.LIVE

    def test_an_incomplete_walk_past_ttl_is_stuck(self) -> None:
        walk = stopped(_stats(Node("e", D, 0)), "directory e/x could not be listed")
        judgement = judge(walk, age=_DUE, liveness=())
        assert judgement.verdict is Verdict.STUCK
        assert judgement.reasons == ("directory e/x could not be listed",)

    def test_an_unread_root_is_stuck(self) -> None:
        walk = stopped(_stats(kind=NodeKind.UNREAD), "entry e could not be read: OSError")
        assert _judge(walk) is Verdict.STUCK

    def test_a_multi_linked_file_is_stuck(self) -> None:
        walk = finished(_stats(Node("e", D, 0), Node("e/a.log", F, 3), multi_linked=("e/a.log",)))
        judgement = judge(walk, age=_DUE, liveness=())
        assert judgement.verdict is Verdict.STUCK
        assert "e/a.log" in judgement.reasons[0]

    def test_stuck_comes_before_repository(self) -> None:
        walk = stopped(_stats(git_markers=("e/.git",)), "walk deadline reached")
        assert _judge(walk) is Verdict.STUCK

    def test_a_git_marker_at_any_depth_is_a_repository_not_judged(self) -> None:
        walk = finished(
            _stats(
                Node("e", D, 0),
                Node("e/deep/x/.git", D, 0, empty=True),
                git_markers=("e/deep/x/.git",),
            )
        )
        judgement = judge(walk, age=_DUE, liveness=())
        assert judgement.verdict is Verdict.REPOSITORY
        assert judgement.proofs == ()

    def test_the_reason_names_the_pending_classification_and_no_ruling(self) -> None:
        walk = finished(_stats(Node("e", D, 0), git_markers=("e/.git",)))
        judgement = judge(walk, age=_DUE, liveness=())
        assert judgement.reasons == (
            "repository, not judged: which kind of repository it is (Task 2.1) is not yet known",
        )

    def test_a_git_file_marker_is_a_repository(self) -> None:
        walk = finished(_stats(Node("e", D, 0), Node("e/.git", F, 20), git_markers=("e/.git",)))
        assert _judge(walk) is Verdict.REPOSITORY


class TestRepositoryMarker:
    def test_found_is_carried_even_when_live(self) -> None:
        walk = finished(_stats(Node("e", D, 0), git_markers=("e/.git",)))
        judgement = judge(walk, age=_FRESH, liveness=())
        assert judgement.verdict is Verdict.LIVE
        assert judgement.repository is RepositoryMarker.FOUND
        assert judgement.git_markers == ("e/.git",)

    def test_found_is_carried_when_stuck(self) -> None:
        walk = stopped(_stats(git_markers=("e/.git",)), "walk deadline reached")
        assert judge(walk, age=_DUE, liveness=()).repository is RepositoryMarker.FOUND

    def test_a_partial_walk_with_no_marker_is_unknown_never_none(self) -> None:
        walk = stopped(_stats(Node("e", D, 0)), "walk deadline reached")
        assert judge(walk, age=_FRESH, liveness=()).repository is RepositoryMarker.UNKNOWN

    def test_a_complete_walk_with_no_marker_is_none(self) -> None:
        walk = finished(_stats(Node("e", D, 0), Node("e/a.log", F, 1)))
        assert judge(walk, age=_DUE, liveness=()).repository is RepositoryMarker.NONE


class TestP1:
    @pytest.mark.parametrize(
        "name",
        [
            "commit-msg.txt",
            "commit-x.md",
            "merge-1.txt",
            "merge-1.md",
            "tag-v1.txt",
            "pr-12.md",
            "issue-3.md",
            "issue-3.json",
            "comment-9.md",
            "close-9.md",
            "gh-body.md",
            "journal-entry.md",
            "build.log",
            "run.out",
            "ci-123.txt",
            "qa-run.txt",
            "push-main.txt",
        ],
    )
    def test_a_consumed_shape_is_disposable(self, name: str) -> None:
        walk = finished(_stats(Node(name, F, 10)))
        judgement = judge(walk, age=_DUE, liveness=())
        assert judgement.verdict is Verdict.DISPOSABLE
        assert judgement.proofs == (Proof.P1,)

    @pytest.mark.parametrize(
        "name", ["notes.txt", "data.json", "t.tsv", "brief-x.md", "report.md", "run.py"]
    )
    def test_a_generic_name_is_uncertain(self, name: str) -> None:
        walk = finished(_stats(Node(name, F, 10)))
        judgement = judge(walk, age=_DUE, liveness=())
        assert judgement.verdict is Verdict.UNCERTAIN
        assert judgement.uncovered == (name,)

    def test_p1_matches_inside_a_directory_entry(self) -> None:
        walk = finished(_stats(Node("e", D, 0), Node("e/sub", D, 0), Node("e/sub/a.log", F, 9)))
        assert _judge(walk) is Verdict.DISPOSABLE

    def test_a_directory_named_like_p1_covers_nothing(self) -> None:
        walk = finished(_stats(Node("qa-run", D, 0), Node("qa-run/results.txt", F, 9)))
        assert _judge(walk) is Verdict.UNCERTAIN

    def test_a_link_with_a_p1_name_is_not_covered(self) -> None:
        walk = finished(_stats(Node("a.log", L, 9), kind=L))
        assert _judge(walk) is Verdict.UNCERTAIN

    def test_a_mixed_entry_is_uncertain(self) -> None:
        walk = finished(_stats(Node("e", D, 0), Node("e/a.log", F, 9), Node("e/n.txt", F, 9)))
        judgement = judge(walk, age=_DUE, liveness=())
        assert judgement.verdict is Verdict.UNCERTAIN
        assert judgement.uncovered == ("e/n.txt",)


class TestP2:
    @pytest.mark.parametrize(
        "directory",
        [
            "__pycache__",
            ".pytest_cache",
            ".mypy_cache",
            ".ruff_cache",
            "node_modules",
            "x.egg-info",
        ],
    )
    def test_a_regenerable_directory_covers_its_contents(self, directory: str) -> None:
        walk = finished(
            _stats(
                Node("e", D, 0),
                Node(f"e/{directory}", D, 0),
                Node(f"e/{directory}/blob.bin", F, 99),
                Node(f"e/{directory}/link", L, 5),
                Node(f"e/{directory}/pipe", S, 0),
            )
        )
        judgement = judge(walk, age=_DUE, liveness=())
        assert judgement.verdict is Verdict.DISPOSABLE
        assert judgement.proofs == (Proof.P2,)

    def test_an_entry_named_pycache_is_covered(self) -> None:
        walk = finished(_stats(Node("__pycache__", D, 0), Node("__pycache__/m.pyc", F, 9)))
        assert _judge(walk) is Verdict.DISPOSABLE

    @pytest.mark.parametrize("kind", [F, L])
    def test_a_non_directory_named_like_p2_covers_nothing(self, kind: NodeKind) -> None:
        walk = finished(_stats(Node("e", D, 0), Node("e/node_modules", kind, 9)))
        assert _judge(walk) is Verdict.UNCERTAIN

    def test_a_directory_holding_pyvenv_cfg_is_covered(self) -> None:
        walk = finished(
            _stats(
                Node("e", D, 0),
                Node("e/venv", D, 0),
                Node("e/venv/pyvenv.cfg", F, 50),
                Node("e/venv/bin", D, 0),
                Node("e/venv/bin/python", L, 7),
                Node("e/venv/lib/site.py", F, 500),
            )
        )
        judgement = judge(walk, age=_DUE, liveness=())
        assert judgement.verdict is Verdict.DISPOSABLE
        assert judgement.proofs == (Proof.P2,)

    def test_pyvenv_cfg_must_be_a_regular_file(self) -> None:
        walk = finished(
            _stats(
                Node("e", D, 0),
                Node("e/venv", D, 0),
                Node("e/venv/pyvenv.cfg", L, 50),
                Node("e/venv/site.py", F, 500),
            )
        )
        assert _judge(walk) is Verdict.UNCERTAIN

    def test_pyvenv_cfg_covers_only_its_own_directory(self) -> None:
        walk = finished(
            _stats(
                Node("e", D, 0),
                Node("e/venv", D, 0),
                Node("e/venv/pyvenv.cfg", F, 50),
                Node("e/venvx", D, 0),
                Node("e/venvx/keep.py", F, 5),
            )
        )
        assert _judge(walk) is Verdict.UNCERTAIN


class TestP5:
    def test_a_zero_byte_file_is_disposable(self) -> None:
        walk = finished(_stats(Node("blank.txt", F, 0)))
        judgement = judge(walk, age=_DUE, liveness=())
        assert judgement.verdict is Verdict.DISPOSABLE
        assert judgement.proofs == (Proof.P5,)

    def test_an_empty_directory_is_disposable(self) -> None:
        walk = finished(_stats(Node("e", D, 0, empty=True)))
        assert _judge(walk) is Verdict.DISPOSABLE

    def test_proofs_are_listed_once_each_in_order(self) -> None:
        walk = finished(
            _stats(
                Node("e", D, 0),
                Node("e/__pycache__", D, 0),
                Node("e/__pycache__/m.pyc", F, 9),
                Node("e/a.log", F, 9),
                Node("e/b.log", F, 9),
                Node("e/empty", D, 0, empty=True),
            )
        )
        assert judge(walk, age=_DUE, liveness=()).proofs == (Proof.P1, Proof.P2, Proof.P5)

    def test_a_zero_byte_special_file_is_not_covered(self) -> None:
        walk = finished(_stats(Node("e", D, 0), Node("e/pipe", S, 0)))
        assert _judge(walk) is Verdict.UNCERTAIN

    def test_a_top_level_link_entry_is_uncertain(self) -> None:
        walk = finished(_stats(Node("ln", L, 12), kind=L))
        assert _judge(walk) is Verdict.UNCERTAIN


def test_not_evaluated_rungs_are_named() -> None:
    assert NOT_EVALUATED == ("KEPT", "PROTECTED", "REFERENCED")
