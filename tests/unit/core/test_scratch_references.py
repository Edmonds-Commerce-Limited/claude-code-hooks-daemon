"""The reference set: scratch paths a tracked file names (Plan 00627 Task 2.4).

DESIGN.md section 3.4. The output format is tested against real git; the
failure cases inject a runner. Every failure must leave the set UNKNOWN, never
"known, nothing referenced".
"""

from __future__ import annotations

import dataclasses
import re
import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path

import pytest

from claude_code_hooks_daemon.core.scratch_references import (
    UNSEARCHABLE_NAME,
    ReferenceSet,
    build_references,
)
from claude_code_hooks_daemon.core.scratch_repos import ProjectGit, build_project_git
from tests.support.scratch_tree import GitProject, build_git_project, commit_file, git

_ROOT = "untracked/scratch"


def _no_live(_project: Path, _remote: str, _names: list[str]) -> dict[str, str]:
    return {}


def _project_git(gp: GitProject, default: str | None = "main") -> ProjectGit:
    return build_project_git(
        gp.project, remote="origin", default_branch=default, live_tips=_no_live
    )


def _refs(gp: GitProject, default: str | None = "main") -> ReferenceSet:
    return build_references(_project_git(gp, default), _ROOT)


def _referenced(refs: ReferenceSet, name: str) -> bool:
    found = refs.for_entry(name)
    assert found.unknown == "", found.unknown
    return bool(found.sites)


@pytest.fixture
def gp(tmp_path: Path) -> GitProject:
    return build_git_project(tmp_path)


class TestWhatCounts:
    def test_an_exact_path_counts_and_a_bare_word_does_not(self, gp: GitProject) -> None:
        commit_file(gp.project, "docs/a.md", "see untracked/scratch/foo/a.md and bar\n")
        refs = _refs(gp)
        assert refs.unknown == ""
        assert _referenced(refs, "foo")
        assert not _referenced(refs, "bar")

    def test_the_site_names_the_label_file_and_line(self, gp: GitProject) -> None:
        commit_file(gp.project, "docs/a.md", "x\ny untracked/scratch/foo\n")
        sites = _refs(gp).for_entry("foo").sites
        assert sites == ("HEAD:docs/a.md:2",)

    def test_a_reference_on_an_unmerged_branch_counts(self, gp: GitProject) -> None:
        git(gp.project, "checkout", "-q", "-b", "feat")
        commit_file(gp.project, "docs/a.md", "untracked/scratch/foo\n")
        git(gp.project, "checkout", "-q", "main")
        sites = _refs(gp).for_entry("foo").sites
        assert sites == ("feat:docs/a.md:1",)

    def test_a_line_main_removed_on_a_merged_branch_does_not_count(self, gp: GitProject) -> None:
        git(gp.project, "checkout", "-q", "-b", "old")
        commit_file(gp.project, "docs/a.md", "untracked/scratch/baz\n")
        git(gp.project, "checkout", "-q", "main")
        git(gp.project, "merge", "-q", "--ff-only", "old")
        commit_file(gp.project, "docs/a.md", "gone\n")
        assert not _referenced(_refs(gp), "baz")

    def test_with_no_local_default_every_branch_is_searched(self, gp: GitProject) -> None:
        git(gp.project, "checkout", "-q", "-b", "old")
        commit_file(gp.project, "docs/a.md", "untracked/scratch/baz\n")
        git(gp.project, "checkout", "-q", "main")
        git(gp.project, "merge", "-q", "--ff-only", "old")
        commit_file(gp.project, "docs/a.md", "gone\n")
        assert _referenced(_refs(gp, default=None), "baz")
        assert _referenced(_refs(gp, default="no-such-branch"), "baz")

    def test_the_default_tip_counts_while_head_is_on_an_older_branch(self, gp: GitProject) -> None:
        git(gp.project, "branch", "older")
        commit_file(gp.project, "docs/a.md", "untracked/scratch/qux\n")
        git(gp.project, "checkout", "-q", "older")
        assert _referenced(_refs(gp), "qux")

    def test_a_reference_to_foobar_is_not_one_to_foo(self, gp: GitProject) -> None:
        commit_file(gp.project, "docs/a.md", "untracked/scratch/foobar/x\n")
        refs = _refs(gp)
        assert _referenced(refs, "foobar")
        assert not _referenced(refs, "foo")

    def test_a_trailing_dot_or_slash_still_matches(self, gp: GitProject) -> None:
        commit_file(
            gp.project,
            "docs/a.md",
            "see untracked/scratch/foo. and untracked/scratch/bar/ and untracked/scratch/baz.\n",
        )
        refs = _refs(gp)
        assert _referenced(refs, "foo")
        assert _referenced(refs, "bar")
        assert _referenced(refs, "baz.")

    def test_a_trailing_underscore_does_not_hide_the_entry(self, gp: GitProject) -> None:
        commit_file(gp.project, "docs/a.md", "_untracked/scratch/foo_\n")
        assert _referenced(_refs(gp), "foo")

    def test_an_underscore_name_is_found_whole(self, gp: GitProject) -> None:
        commit_file(gp.project, "docs/a.md", "untracked/scratch/probe_run/out\n")
        refs = _refs(gp)
        assert _referenced(refs, "probe_run")
        assert not _referenced(refs, "probe")

    def test_a_name_the_search_cannot_match_is_unknown(self, gp: GitProject) -> None:
        refs = _refs(gp)
        assert refs.for_entry("has space").unknown == UNSEARCHABLE_NAME
        assert refs.for_entry("café").unknown == UNSEARCHABLE_NAME

    def test_dot_segments_are_resolved(self, gp: GitProject) -> None:
        commit_file(
            gp.project,
            "docs/a.md",
            "untracked/scratch/./foo/x untracked/scratch/../scratch/zed untracked/scratch/../out\n",
        )
        refs = _refs(gp)
        assert _referenced(refs, "foo")
        assert _referenced(refs, "zed")
        assert not _referenced(refs, "out")

    def test_a_reference_in_a_binary_file_counts(self, gp: GitProject) -> None:
        (gp.project / "blob.bin").write_bytes(b"\0\x01untracked/scratch/bin1/x\0\xff")
        git(gp.project, "add", "blob.bin")
        git(gp.project, "commit", "-q", "-m", "binary")
        assert _referenced(_refs(gp), "bin1")

    def test_an_uncommitted_edit_to_a_tracked_file_counts(self, gp: GitProject) -> None:
        (gp.project / "src" / "app.py").write_text("# untracked/scratch/wt1\n")
        sites = _refs(gp).for_entry("wt1").sites
        assert sites == ("working tree:src/app.py:1",)

    def test_a_file_name_with_a_colon_and_a_newline_is_parsed(self, gp: GitProject) -> None:
        commit_file(gp.project, "we:ird\nname.md", "untracked/scratch/odd\n")
        assert _refs(gp).for_entry("odd").sites == ("HEAD:we:ird\nname.md:1",)

    def test_project_grep_config_does_not_change_the_format(self, gp: GitProject) -> None:
        git(gp.project, "config", "grep.column", "true")
        git(gp.project, "config", "grep.fullName", "true")
        commit_file(gp.project, "docs/a.md", "untracked/scratch/foo\n")
        assert _referenced(_refs(gp), "foo")


Runner = Callable[..., subprocess.CompletedProcess[str]]


_SUB = "untracked/scratch/sub"


class TestSubRoot:
    """F-BYPS 3, coordinator's ruling: the root itself protects; an ancestor does not."""

    @pytest.mark.parametrize(
        "text",
        [
            "see untracked/scratch/sub for the evidence",
            "see untracked/scratch/sub/ for the evidence",
            "see untracked/scratch/sub.",
            "see `untracked/scratch/sub`",
        ],
    )
    def test_a_reference_to_the_root_itself_names_every_entry(
        self, gp: GitProject, text: str
    ) -> None:
        commit_file(gp.project, "docs/ref.md", f"{text}\n")
        refs = build_references(_project_git(gp), _SUB)
        assert refs.unknown == ""
        assert refs.for_entry("run.log").sites == ("HEAD:docs/ref.md:1",)
        assert refs.for_entry("qa-findings.md").sites == ("HEAD:docs/ref.md:1",)

    def test_a_path_under_the_sub_root_names_only_its_entry(self, gp: GitProject) -> None:
        commit_file(gp.project, "docs/ref.md", "untracked/scratch/sub/run.log\n")
        refs = build_references(_project_git(gp), _SUB)
        assert _referenced(refs, "run.log")
        assert not _referenced(refs, "other")

    @pytest.mark.parametrize(
        "text",
        ["untracked/scratch/", "untracked/scratch", "untracked/", "untracked/scratch/subway/x"],
    )
    def test_an_ancestor_or_a_sibling_names_no_entry(self, gp: GitProject, text: str) -> None:
        commit_file(gp.project, "docs/ref.md", f"mention {text} here\n")
        refs = build_references(_project_git(gp), _SUB)
        assert not _referenced(refs, "run.log")

    def test_a_root_reference_site_is_listed_once_beside_an_entry_site(
        self, gp: GitProject
    ) -> None:
        commit_file(
            gp.project, "docs/ref.md", "untracked/scratch/sub and untracked/scratch/sub/a\n"
        )
        sites = build_references(_project_git(gp), _SUB).for_entry("a").sites
        assert sites == ("HEAD:docs/ref.md:1",)

    def test_the_default_root_ignores_a_bare_mention_of_itself(self, gp: GitProject) -> None:
        commit_file(gp.project, "docs/ref.md", "files go in untracked/scratch/ always\n")
        assert not _referenced(_refs(gp), "anything")


def _intercept(
    project: ProjectGit, when: Callable[[tuple[str, ...]], bool], rc: int, out: str
) -> ProjectGit:
    real: Runner = project.runner

    def runner(
        cwd: Path, *args: str, timeout: float = 30.0, env: Mapping[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        if when(args):
            return subprocess.CompletedProcess(["git", *args], rc, out, "boom")
        return real(cwd, *args, timeout=timeout, env=env)

    return dataclasses.replace(project, runner=runner)


def _is_grep(args: tuple[str, ...]) -> bool:
    return "grep" in args


def _has_rev(args: tuple[str, ...]) -> bool:
    return any(re.fullmatch("[0-9a-f]{40}", arg) for arg in args)


def _is_rev_grep(args: tuple[str, ...]) -> bool:
    return "grep" in args and _has_rev(args)


def _is_tree_grep(args: tuple[str, ...]) -> bool:
    return "grep" in args and not _has_rev(args)


def _is_head(args: tuple[str, ...]) -> bool:
    return args[:2] == ("rev-parse", "--verify")


def _is_branches(args: tuple[str, ...]) -> bool:
    return args[:1] == ("for-each-ref",) and args[-1] == "refs/heads/"


def _is_unmerged(args: tuple[str, ...]) -> bool:
    return _is_branches(args) and any(arg.startswith("--no-merged") for arg in args)


class TestEveryFailureIsUnknown:
    @pytest.mark.parametrize(
        ("when", "rc", "out"),
        [
            (_is_grep, 128, ""),
            (_is_rev_grep, 1, "x"),
            (_is_tree_grep, 1, "x"),
            (_is_rev_grep, 0, "not a record\n"),
            (_is_tree_grep, 0, "not a record\n"),
            (_is_rev_grep, 0, ""),
            (_is_rev_grep, 0, f"{'a' * 40}:docs/a.md\x001\x00untracked/scratch/foo\n"),
            (_is_head, 1, ""),
            (_is_head, 0, "not-a-sha\n"),
            (_is_branches, 128, ""),
            (_is_branches, 0, ""),
            (_is_branches, 0, "garbage\n"),
            (_is_unmerged, 128, ""),
            (_is_unmerged, 0, "garbage\n"),
        ],
    )
    def test_a_git_failure_is_unknown(
        self, gp: GitProject, when: Callable[[tuple[str, ...]], bool], rc: int, out: str
    ) -> None:
        project = _intercept(_project_git(gp), when, rc, out)
        refs = build_references(project, _ROOT)
        assert refs.unknown
        assert refs.for_entry("anything").unknown == refs.unknown

    def test_a_timeout_is_unknown(self, gp: GitProject) -> None:
        project = _intercept(_project_git(gp), _is_grep, -9, "")
        assert build_references(project, _ROOT).unknown

    def test_no_relative_root_is_unknown(self, gp: GitProject) -> None:
        assert build_references(_project_git(gp), None).unknown

    def test_no_project_git_is_unknown(self) -> None:
        assert build_references(None, _ROOT).unknown

    def test_a_root_the_search_cannot_match_is_unknown(self, gp: GitProject) -> None:
        assert build_references(_project_git(gp), "untracked/my scratch").unknown

    def test_the_rev_grep_is_never_run_without_revs(self, gp: GitProject) -> None:
        seen: list[tuple[str, ...]] = []
        project = _project_git(gp)
        real: Runner = project.runner

        def runner(
            cwd: Path, *args: str, timeout: float = 30.0, env: Mapping[str, str] | None = None
        ) -> subprocess.CompletedProcess[str]:
            seen.append(args)
            return real(cwd, *args, timeout=timeout, env=env)

        build_references(dataclasses.replace(project, runner=runner), _ROOT)
        greps = [args for args in seen if "grep" in args]
        assert len(greps) == 2
        assert sum(_has_rev(args) for args in greps) == 1
