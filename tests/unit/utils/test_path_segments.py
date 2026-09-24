"""``matches_path_segment`` -- the one segment-bounded, project-relative
skip-list matcher every site shares (Plan 00458).

Two failures, compounded, motivate this module:

1. **Bare substring, not segment.** ``"venv/" in file_path`` also matches
   ``"myvenv/"`` and ``"worktree-issue-53-venv/"`` -- a directory that merely
   ENDS in the skipped name (00422 N20). ``strategies/lint/common.py``'s
   ``matches_skip_path`` fixed this once; this module is where that fix now
   lives, with every other site routed onto it (Plan 00458).
2. **Absolute, not project-relative.** Even a segment-bounded match against
   the ABSOLUTE path still skips every file of a project that happens to live
   under a directory named exactly ``venv`` or ``build``. The match has to be
   made against the path relative to the project root.
"""

from __future__ import annotations

from claude_code_hooks_daemon.utils.path_segments import matches_path_segment


class TestSegmentBoundedNoProjectRoot:
    """With no ``project_root`` (or one the path is not under), this behaves
    exactly like the pre-existing lint matcher: segment-bounded on whatever
    string is handed in."""

    def test_exact_directory_matches(self) -> None:
        assert matches_path_segment("/workspace/venv/lib/x.py", ("venv/",)) is True

    def test_a_longer_name_sharing_the_suffix_does_not_match(self) -> None:
        """``myvenv/`` is not ``venv/`` -- the historical N20 bug."""
        assert matches_path_segment("/workspace/myvenv/lib/x.py", ("venv/",)) is False

    def test_a_longer_name_sharing_a_prefix_does_not_match(self) -> None:
        assert matches_path_segment("/workspace/rebuild/x.py", ("build/",)) is False

    def test_a_worktree_style_suffix_does_not_match(self) -> None:
        """The exact 00422 N20 shape: a worktree named ``...-venv``."""
        path = "/workspace/untracked/worktrees/worktree-issue-53-venv/untracked/scratch/x.py"
        assert matches_path_segment(path, ("venv/",)) is False

    def test_match_at_string_start_counts(self) -> None:
        assert matches_path_segment("venv/lib/x.py", ("venv/",)) is True

    def test_no_patterns_never_matches(self) -> None:
        assert matches_path_segment("/workspace/venv/x.py", ()) is False

    def test_multiple_patterns_any_may_match(self) -> None:
        assert matches_path_segment("/workspace/vendor/x.rb", ("venv/", "vendor/")) is True


class TestProjectRelative:
    """With a ``project_root``, matching is against the path RELATIVE to it."""

    def test_a_skip_dir_directly_under_the_project_root_matches(self) -> None:
        assert matches_path_segment("/proj/venv/lib/x.py", ("venv/",), project_root="/proj") is True

    def test_a_project_living_under_a_directory_named_venv_is_still_guarded(self) -> None:
        """The absolute path contains ``venv/`` as an ANCESTOR of the project,
        not as a directory inside it -- relative to the project root it is not
        there at all, so the site must still be guarded (not skipped)."""
        assert (
            matches_path_segment(
                "/home/dev/venv/proj/src/main.py", ("venv/",), project_root="/home/dev/venv/proj"
            )
            is False
        )

    def test_a_worktree_named_with_a_skip_suffix_is_still_guarded(self) -> None:
        """The 00422 N20 reproduction, project-relative this time: the skip
        name is in an ANCESTOR directory (the worktree's own name), not in the
        project-relative path, so the site must still be guarded."""
        root = "/workspace/untracked/worktrees/worktree-issue-53-venv"
        path = f"{root}/untracked/acceptance/acceptance-test-qa-python/sample.py"
        assert matches_path_segment(path, ("venv/",), project_root=root) is False

    def test_a_file_outside_the_project_root_is_not_skipped(self) -> None:
        """Decision (Plan 00458 team-lead spec, point 2): for a BLOCKING
        guard the safe default on an unresolvable relative path is "not
        skipped" -- skipping would fail open."""
        assert (
            matches_path_segment("/elsewhere/venv/x.py", ("venv/",), project_root="/proj") is False
        )

    def test_project_root_itself_as_the_file_path_is_not_skipped(self) -> None:
        """``os.path.relpath(root, root)`` is ``"."`` -- never a segment
        match, and must not raise."""
        assert matches_path_segment("/proj", ("venv/",), project_root="/proj") is False


class TestPathLibCompatible:
    """``project_root`` accepts anything ``str()`` renders as a path, matching
    every other caller of ``utils.path_exclusion.resolve_project_root``."""

    def test_a_path_object_root_is_accepted(self) -> None:
        from pathlib import Path

        assert (
            matches_path_segment("/proj/venv/x.py", ("venv/",), project_root=Path("/proj")) is True
        )
