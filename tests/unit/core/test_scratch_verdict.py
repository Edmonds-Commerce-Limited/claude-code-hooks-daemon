"""Scratch entry verdicts and the no-git proofs P1, P2, P5 (Plan 00627 Task 1.6)."""

from __future__ import annotations

from typing import Any

import pytest

from claude_code_hooks_daemon.core.scratch_clock import EntryAge
from claude_code_hooks_daemon.core.scratch_references import References
from claude_code_hooks_daemon.core.scratch_repos import RepoFindings, RepoKind
from claude_code_hooks_daemon.core.scratch_verdict import (
    NOT_CLASSIFIED,
    NOT_EVALUATED,
    TRACKED_UNKNOWN,
    Judgement,
    Proof,
    RepositoryMarker,
    Verdict,
)
from claude_code_hooks_daemon.core.scratch_verdict import judge as real_judge
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


#: A known answer: no tracked line names the entry.
_UNREFERENCED = References(())


def judge(
    walk: Bounded[EntryStats], *, references: References = _UNREFERENCED, **kwargs: Any
) -> Judgement:
    """``judge`` with "nothing references it" unless a test says otherwise."""
    return real_judge(walk, references=references, **kwargs)


def _judge(
    walk: Bounded[EntryStats], age: EntryAge = _DUE, liveness: tuple[str, ...] = ()
) -> Verdict:
    return judge(walk, age=age, liveness=liveness).verdict


class TestKept:
    """Task 4.4: a ``.scratch-keep`` file at the top of an entry is a human's pin (R15)."""

    def _kept(self, *extra: Node) -> Bounded[EntryStats]:
        return finished(_stats(Node("e", D, 0), Node("e/.scratch-keep", F, 9), *extra))

    def test_a_marker_makes_a_due_entry_kept_with_its_reason(self) -> None:
        walk = self._kept(Node("e/a.log", F, 3))
        judgement = judge(walk, age=_DUE, liveness=(), keep_reason="my notes")
        assert judgement.verdict is Verdict.KEPT
        assert judgement.reasons == ("pinned by .scratch-keep: my notes",)

    def test_kept_beats_protected_and_disposable(self) -> None:
        walk = self._kept(Node("e/a.log", F, 3))
        judged = judge(walk, age=_DUE, liveness=(), tracked=("e/a.log",))
        assert judged.verdict is Verdict.KEPT

    def test_a_marker_with_no_reason_still_keeps(self) -> None:
        judgement = judge(self._kept(), age=_DUE, liveness=())
        assert judgement.verdict is Verdict.KEPT
        assert judgement.reasons == ("pinned by .scratch-keep: (no reason given)",)

    def test_live_and_stuck_still_come_first(self) -> None:
        assert _judge(self._kept(), age=_FRESH) is Verdict.LIVE
        walk = stopped(_stats(Node("e", D, 0), Node("e/.scratch-keep", F, 1)), "deadline")
        assert _judge(walk) is Verdict.STUCK

    @pytest.mark.parametrize(
        "node",
        [
            Node("e/.scratch-keep", L, 0),
            Node("e/.scratch-keep", D, 0, empty=True),
            Node("e/sub/.scratch-keep", F, 1),
        ],
    )
    def test_only_a_regular_file_at_the_top_counts(self, node: Node) -> None:
        walk = finished(_stats(Node("e", D, 0), Node("e/sub", D, 0), node))
        assert _judge(walk) is not Verdict.KEPT


class TestLivenessUnknown:
    def test_a_due_entry_is_stuck_when_liveness_is_unknown(self) -> None:
        walk = finished(_stats(Node("a.log", F, 5), kind=F))
        judgement = judge(walk, age=_DUE, liveness=(), liveness_unknown="no cwd readable")
        assert judgement.verdict is Verdict.STUCK
        assert judgement.reasons == ("liveness unknown: no cwd readable",)

    def test_a_known_live_signal_still_wins(self) -> None:
        walk = finished(_stats(Node("a.log", F, 5), kind=F))
        judgement = judge(walk, age=_DUE, liveness=("process 1",), liveness_unknown="x")
        assert judgement.verdict is Verdict.LIVE


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

    def test_a_git_marker_with_no_classification_is_stuck(self) -> None:
        walk = finished(
            _stats(
                Node("e", D, 0),
                Node("e/deep/x/.git", D, 0, empty=True),
                git_markers=("e/deep/x/.git",),
            )
        )
        judgement = judge(walk, age=_DUE, liveness=())
        assert judgement.verdict is Verdict.STUCK
        assert judgement.reasons == (NOT_CLASSIFIED,)
        assert judgement.proofs == ()

    def test_a_repository_that_could_not_be_classified_is_stuck(self) -> None:
        walk = finished(_stats(Node("e", D, 0), Node("e/.git", F, 20), git_markers=("e/.git",)))
        repos = RepoFindings(kinds={"e/.git": RepoKind.BROKEN}, stuck=("e/.git: broken",))
        assert judge(walk, age=_DUE, liveness=(), repos=repos).verdict is Verdict.STUCK

    def test_a_protected_repository_protects_the_entry(self) -> None:
        walk = finished(_stats(Node("e", D, 0), Node("e/.git", F, 20), git_markers=("e/.git",)))
        repos = RepoFindings(
            kinds={"e/.git": RepoKind.REGISTERED_WORKTREE}, protected=("e/.git: worktree",)
        )
        judgement = judge(walk, age=_DUE, liveness=(), repos=repos)
        assert judgement.verdict is Verdict.PROTECTED
        assert judgement.reasons == ("e/.git: worktree",)

    def test_a_standalone_repository_is_disposable_by_p7(self) -> None:
        """Coordinator's ruling applying the owner's "scratch repo ... no value" (DESIGN 0)."""
        walk = finished(
            _stats(
                Node("e", D, 0),
                Node("e/.git", D, 0),
                Node("e/.git/HEAD", F, 21),
                Node("e/.git/objects/ab/cdef", F, 90),
                Node("e/probe.py", F, 40),
                git_markers=("e/.git",),
            )
        )
        repos = RepoFindings(kinds={"e/.git": RepoKind.STANDALONE}, standalone_roots=("e",))
        judgement = judge(walk, age=_DUE, liveness=(), repos=repos)
        assert judgement.verdict is Verdict.DISPOSABLE
        assert judgement.proofs == (Proof.P7,)

    def test_p7_covers_only_the_repository_subtree_not_its_neighbours(self) -> None:
        walk = finished(
            _stats(
                Node("e", D, 0),
                Node("e/report.md", F, 300),
                Node("e/tmp/repo/.git/HEAD", F, 21),
                Node("e/tmp/repo/a.txt", F, 3),
                git_markers=("e/tmp/repo/.git",),
            )
        )
        repos = RepoFindings(
            kinds={"e/tmp/repo/.git": RepoKind.STANDALONE}, standalone_roots=("e/tmp/repo",)
        )
        judgement = judge(walk, age=_DUE, liveness=(), repos=repos)
        assert judgement.verdict is Verdict.UNCERTAIN
        assert judgement.uncovered == ("e/report.md",)

    def test_p7_stops_at_a_nested_related_repository(self) -> None:
        """A clean pushed clone inside a standalone repository keeps its own rule."""
        nodes = (
            Node("e", D, 0),
            Node("e/.git/HEAD", F, 21),
            Node("e/clone/.git/HEAD", F, 21),
            Node("e/clone/notes.txt", F, 5),
        )
        repos = RepoFindings(
            kinds={"e/.git": RepoKind.STANDALONE, "e/clone/.git": RepoKind.RELATED},
            p4_covered=("e/clone/.git",),
            p4_git_dirs=("e/clone/.git",),
            standalone_roots=("e",),
            other_roots=("e/clone",),
        )
        judgement = judge(
            finished(_stats(*nodes, git_markers=("e/.git", "e/clone/.git"))),
            age=_DUE,
            liveness=(),
            repos=repos,
        )
        assert judgement.verdict is Verdict.UNCERTAIN
        assert judgement.uncovered == ("e/clone/notes.txt",)

    def test_p7_covers_a_standalone_repository_inside_a_related_one(self) -> None:
        nodes = (
            Node("e", D, 0),
            Node("e/.git/HEAD", F, 21),
            Node("e/sub/.git/HEAD", F, 21),
            Node("e/sub/x.txt", F, 5),
        )
        repos = RepoFindings(
            kinds={"e/.git": RepoKind.RELATED, "e/sub/.git": RepoKind.STANDALONE},
            p4_covered=("e/.git",),
            p4_git_dirs=("e/.git",),
            standalone_roots=("e/sub",),
            other_roots=("e",),
        )
        judgement = judge(
            finished(_stats(*nodes, git_markers=("e/.git", "e/sub/.git"))),
            age=_DUE,
            liveness=(),
            repos=repos,
        )
        assert judgement.verdict is Verdict.DISPOSABLE
        assert judgement.proofs == (Proof.P4, Proof.P7)

    def test_a_tracked_file_beats_a_standalone_repository(self) -> None:
        walk = finished(
            _stats(Node("e", D, 0), Node("e/.git/HEAD", F, 21), git_markers=("e/.git",))
        )
        repos = RepoFindings(kinds={"e/.git": RepoKind.STANDALONE}, standalone_roots=("e",))
        judgement = judge(walk, age=_DUE, liveness=(), repos=repos, tracked=("e/.git/HEAD",))
        assert judgement.verdict is Verdict.PROTECTED

    def test_p4_covers_a_clean_pushed_clone_but_not_its_untracked_work(self) -> None:
        nodes = (
            Node("e", D, 0),
            Node("e/.git", D, 0),
            Node("e/.git/HEAD", F, 21),
            Node("e/app.py", F, 9),
        )
        repos = RepoFindings(
            kinds={"e/.git": RepoKind.RELATED},
            p4_covered=("e/.git", "e/app.py"),
            p4_git_dirs=("e/.git",),
        )
        judgement = judge(
            finished(_stats(*nodes, git_markers=("e/.git",))), age=_DUE, liveness=(), repos=repos
        )
        assert judgement.verdict is Verdict.DISPOSABLE
        assert judgement.proofs == (Proof.P4,)
        extra = finished(_stats(*nodes, Node("e/notes.txt", F, 5), git_markers=("e/.git",)))
        assert judge(extra, age=_DUE, liveness=(), repos=repos).verdict is Verdict.UNCERTAIN

    def test_a_covered_tracked_path_does_not_cover_what_lies_beneath_it(self) -> None:
        nodes = (Node("e", D, 0), Node("e/sub", D, 0), Node("e/sub/work.txt", F, 4))
        repos = RepoFindings(kinds={"e/.git": RepoKind.RELATED}, p4_covered=("e/sub",))
        judgement = judge(finished(_stats(*nodes)), age=_DUE, liveness=(), repos=repos)
        assert judgement.verdict is Verdict.UNCERTAIN

    def test_an_entry_holding_a_tracked_file_is_protected(self) -> None:
        walk = finished(_stats(Node("e", D, 0), Node("e/a.log", F, 1)))
        judgement = judge(walk, age=_DUE, liveness=(), tracked=("e/a.log",))
        assert judgement.verdict is Verdict.PROTECTED

    def test_unknown_tracked_files_make_a_due_entry_stuck(self) -> None:
        walk = finished(_stats(Node("e", D, 0), Node("e/a.log", F, 1)))
        judgement = judge(walk, age=_DUE, liveness=(), tracked=None)
        assert (judgement.verdict, judgement.reasons) == (Verdict.STUCK, (TRACKED_UNKNOWN,))


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
                Node("e/venv/lib/python3.13/site-packages/site.py", F, 500),
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

    def test_a_real_venv_layout_is_covered(self) -> None:
        """What ``python -m venv`` writes: .gitignore, a lib64 link, include/, bin/."""
        walk = finished(
            _stats(
                Node("e", D, 0),
                Node("e/venv", D, 0),
                Node("e/venv/pyvenv.cfg", F, 50),
                Node("e/venv/.gitignore", F, 70),
                Node("e/venv/lib64", L, 3),
                Node("e/venv/include", D, 0, empty=True),
                Node("e/venv/bin", D, 0),
                Node("e/venv/bin/python3", L, 7),
                Node("e/venv/bin/activate", F, 2000),
                Node("e/venv/lib", D, 0),
                Node("e/venv/lib/python3.13/site-packages/x.py", F, 9),
            )
        )
        assert _judge(walk) is Verdict.DISPOSABLE

    def test_a_windows_venv_layout_is_covered(self) -> None:
        walk = finished(
            _stats(
                Node("e", D, 0),
                Node("e/venv", D, 0),
                Node("e/venv/pyvenv.cfg", F, 50),
                Node("e/venv/Scripts", D, 0),
                Node("e/venv/Scripts/python.exe", F, 70),
                Node("e/venv/Lib", D, 0),
                Node("e/venv/Lib/site-packages/x.py", F, 9),
            )
        )
        assert _judge(walk) is Verdict.DISPOSABLE

    def test_a_lone_pyvenv_cfg_covers_nothing_beside_it(self) -> None:
        """F-BYPS 4: ``pyvenv.cfg`` beside work files is not a venv."""
        walk = finished(
            _stats(
                Node("e", D, 0),
                Node("e/pyvenv.cfg", F, 50),
                Node("e/findings.md", F, 500),
                Node("e/harness.py", F, 500),
            )
        )
        judgement = judge(walk, age=_DUE, liveness=())
        assert judgement.verdict is Verdict.UNCERTAIN
        assert "e/findings.md" in judgement.uncovered
        assert "e/harness.py" in judgement.uncovered

    def test_a_lone_pyvenv_cfg_is_not_itself_covered(self) -> None:
        walk = finished(_stats(Node("e", D, 0), Node("e/pyvenv.cfg", F, 50)))
        assert _judge(walk) is Verdict.UNCERTAIN

    @pytest.mark.parametrize(
        "missing",
        ["bin", "lib"],
    )
    def test_a_partial_venv_shape_covers_nothing(self, missing: str) -> None:
        nodes = [
            Node("e", D, 0),
            Node("e/pyvenv.cfg", F, 50),
            Node("e/bin", D, 0),
            Node("e/bin/python", L, 7),
            Node("e/lib", D, 0),
            Node("e/lib/python3.13/site.py", F, 9),
        ]
        kept = [node for node in nodes if not node.path.startswith(f"e/{missing}")]
        assert _judge(finished(_stats(*kept))) is Verdict.UNCERTAIN

    def test_a_full_venv_shape_leaves_its_siblings_uncovered(self) -> None:
        """F-BYPS 4: ``python -m venv .`` in a work directory covers only the venv layout."""
        walk = finished(
            _stats(
                Node("e", D, 0),
                Node("e/pyvenv.cfg", F, 50),
                Node("e/bin", D, 0),
                Node("e/bin/python", L, 7),
                Node("e/lib", D, 0),
                Node("e/lib/python3.13/site-packages/site.py", F, 9),
                Node("e/findings.md", F, 500),
                Node("e/notes", D, 0),
                Node("e/notes/a.txt", F, 5),
            )
        )
        judgement = judge(walk, age=_DUE, liveness=())
        assert judgement.verdict is Verdict.UNCERTAIN
        assert set(judgement.uncovered) == {"e/findings.md", "e/notes/a.txt"}

    def test_a_regular_file_named_like_a_layout_directory_is_a_sibling(self) -> None:
        walk = finished(
            _stats(
                Node("e", D, 0),
                Node("e/pyvenv.cfg", F, 50),
                Node("e/bin", D, 0),
                Node("e/bin/python", L, 7),
                Node("e/lib", D, 0),
                Node("e/lib/python3.13/site-packages/site.py", F, 9),
                Node("e/share", F, 500),
            )
        )
        judgement = judge(walk, age=_DUE, liveness=())
        assert judgement.uncovered == ("e/share",)

    @staticmethod
    def _venv_with(*extra: Node) -> Bounded[EntryStats]:
        return finished(
            _stats(
                Node("e", D, 0),
                Node("e/pyvenv.cfg", F, 50),
                Node("e/bin", D, 0),
                Node("e/bin/python", L, 7),
                Node("e/bin/python3.13", L, 6),
                Node("e/bin/pip3", F, 200),
                Node("e/bin/activate.fish", F, 200),
                Node("e/lib", D, 0),
                Node("e/lib/python3.13/site-packages/x.py", F, 9),
                *extra,
            )
        )

    def test_n3_the_venv_alone_is_covered(self) -> None:
        assert _judge(self._venv_with()) is Verdict.DISPOSABLE

    @pytest.mark.parametrize(
        "path",
        [
            "e/bin/probe.py",
            "e/bin/tool/run.sh",
            "e/bin/python-notes.txt",
            "e/lib/helpers.py",
            "e/lib/python3.13/notes.md",
            "e/lib64/helpers.py",
            "e/share/findings.md",
            "e/Lib/notes.md",
        ],
    )
    def test_n3_a_user_file_in_a_layout_folder_is_uncovered(self, path: str) -> None:
        """N3: P2 covers only the files a venv tool writes, never a user file beside them."""
        judgement = judge(self._venv_with(Node(path, F, 500)), age=_DUE, liveness=())
        assert judgement.verdict is Verdict.UNCERTAIN
        assert judgement.uncovered == (path,)

    @pytest.mark.parametrize(
        "path",
        [
            "e/bin/activate",
            "e/bin/Activate.ps1",
            "e/bin/activate_this.py",
            "e/bin/pip",
            "e/bin/pip3.13",
            "e/bin/python3",
            "e/include/site/python3.13/x.h",
            "e/lib64/python3.13/site-packages/y.py",
            "e/.gitignore",
            "e/CACHEDIR.TAG",
        ],
    )
    def test_n3_files_a_venv_tool_writes_are_covered(self, path: str) -> None:
        assert _judge(self._venv_with(Node(path, F, 500))) is Verdict.DISPOSABLE

    def test_n3_a_lib64_link_is_covered(self) -> None:
        assert _judge(self._venv_with(Node("e/lib64", L, 3))) is Verdict.DISPOSABLE

    @pytest.mark.parametrize(
        "interpreter", ["e/bin/python-notes.txt", "e/bin/pythonista", "e/bin/python/x"]
    )
    def test_n3_is_venv_needs_an_exact_interpreter(self, interpreter: str) -> None:
        """N3: ``_is_venv`` must not accept a file merely starting ``bin/python``."""
        walk = finished(
            _stats(
                Node("e", D, 0),
                Node("e/pyvenv.cfg", F, 50),
                Node(interpreter, F, 7),
                Node("e/lib/python3.13/site-packages/x.py", F, 9),
            )
        )
        judgement = judge(walk, age=_DUE, liveness=())
        assert judgement.verdict is Verdict.UNCERTAIN
        assert "e/lib/python3.13/site-packages/x.py" in judgement.uncovered

    def test_n3_is_venv_needs_a_site_packages_tree(self) -> None:
        walk = finished(
            _stats(
                Node("e", D, 0),
                Node("e/pyvenv.cfg", F, 50),
                Node("e/bin/python", L, 7),
                Node("e/lib/notes.md", F, 9),
            )
        )
        judgement = judge(walk, age=_DUE, liveness=())
        assert judgement.verdict is Verdict.UNCERTAIN
        assert "e/bin/python" in judgement.uncovered

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
    assert NOT_EVALUATED == ()


class TestReferenced:
    """DESIGN.md section 3.4 (Plan 00627 Task 2.4): REFERENCED sits after PROTECTED."""

    _SITE = References(("HEAD:docs/a.md:3", "feat:docs/b.md:1"))

    def test_a_referenced_entry_beats_every_proof(self) -> None:
        walk = finished(_stats(Node("e", D, 0), Node("e/a.log", F, 1)))
        judgement = judge(walk, age=_DUE, liveness=(), references=self._SITE)
        assert judgement.verdict is Verdict.REFERENCED
        assert judgement.reasons == ("named by 2 tracked line(s), first HEAD:docs/a.md:3",)

    def test_a_referenced_standalone_repository_is_not_disposable(self) -> None:
        walk = finished(_stats(Node("e", D, 0), Node("e/.git", D, 0), git_markers=("e/.git",)))
        repos = RepoFindings(kinds={"e/.git": RepoKind.STANDALONE}, standalone_roots=("e",))
        judgement = judge(walk, age=_DUE, liveness=(), repos=repos, references=self._SITE)
        assert judgement.verdict is Verdict.REFERENCED

    def test_protected_beats_referenced(self) -> None:
        walk = finished(_stats(Node("e", D, 0), Node("e/a.log", F, 1)))
        judgement = judge(walk, age=_DUE, liveness=(), tracked=("e/a.log",), references=self._SITE)
        assert judgement.verdict is Verdict.PROTECTED

    def test_unknown_references_make_a_due_entry_stuck(self) -> None:
        walk = finished(_stats(Node("e", D, 0), Node("e/a.log", F, 1)))
        unknown = References((), "references could not be read")
        judgement = judge(walk, age=_DUE, liveness=(), references=unknown)
        assert (judgement.verdict, judgement.reasons) == (
            Verdict.STUCK,
            ("references could not be read",),
        )

    def test_unknown_references_do_not_touch_a_live_entry(self) -> None:
        walk = finished(_stats(Node("e", D, 0), Node("e/a.log", F, 1)))
        unknown = References((), "references could not be read")
        assert judge(walk, age=_FRESH, liveness=(), references=unknown).verdict is Verdict.LIVE


class TestTtlHold:
    """LIVE "within its TTL" records what the rest of the ladder says (pressure mode, 5.5)."""

    _walk = staticmethod(
        lambda: finished(_stats(Node("e", D, 0), Node("e/__pycache__/m.pyc", F, 3)))
    )

    def test_an_idle_young_entry_holds_its_underlying_verdict(self) -> None:
        judgement = judge(self._walk(), age=_FRESH, liveness=())
        assert judgement.verdict is Verdict.LIVE
        assert judgement.reasons == ("within its TTL",)
        assert judgement.ttl_hold is Verdict.DISPOSABLE
        assert judgement.ttl_hold_proofs == (Proof.P2,)

    def test_a_liveness_reason_carries_no_hold(self) -> None:
        judgement = judge(self._walk(), age=_FRESH, liveness=("process 1",))
        assert judgement.ttl_hold is None

    def test_a_due_entry_carries_no_hold(self) -> None:
        assert judge(self._walk(), age=_DUE, liveness=()).ttl_hold is None

    def test_a_reference_holds_a_young_entry(self) -> None:
        judgement = judge(self._walk(), age=_FRESH, liveness=(), references=References(("a.md:1",)))
        assert judgement.ttl_hold is Verdict.REFERENCED

    def test_a_tracked_file_holds_a_young_entry(self) -> None:
        judgement = judge(self._walk(), age=_FRESH, liveness=(), tracked=("e/x",))
        assert judgement.ttl_hold is Verdict.PROTECTED

    def test_unknown_liveness_holds_a_young_entry(self) -> None:
        judgement = judge(self._walk(), age=_FRESH, liveness=(), liveness_unknown="no cwd")
        assert judgement.ttl_hold is Verdict.STUCK

    def test_an_unclassified_repository_holds_a_young_entry(self) -> None:
        walk = finished(_stats(Node("e", D, 0), git_markers=("e/.git",)))
        assert judge(walk, age=_FRESH, liveness=()).ttl_hold is Verdict.STUCK
